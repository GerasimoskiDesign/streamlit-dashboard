"""Control totals and the reconciliation against an independent manual count."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from salesreport import rules
from salesreport.engine.compare import mismatched_blocks, v4_report
from salesreport.engine.v4 import V4Result
from salesreport.inputs.excel_reader import read_table
from salesreport.normalize import normalize_login_series

CONTROL_COLUMNS = ["section", "metric", "value", "expectation", "status"]


def control_totals(result: V4Result) -> pd.DataFrame:
    """The numbers a reviewer checks before publishing."""
    renewals = result.renewals
    blocks = result.block_rows()
    agents = result.agent_rows()
    shops = blocks.loc[blocks["block_type"] == "shop"]
    unmatched = result.unmatched
    rows: list[tuple[str, str, object, str]] = [
        ("Totals", "Renewals - all channels", int(renewals["renewals"].sum()), ""),
        ("Totals", "Renewals - shops only", int(shops["renewals"].sum()), ""),
        (
            "Totals",
            "Renewals - other channels",
            int(blocks.loc[blocks["block_type"] == "channel", "renewals"].sum()),
            "",
        ),
        ("Totals", "Digital renewals - all channels", int(renewals["digital"].sum()), ""),
        ("Totals", "Digital renewals - shops only", int(shops["digital"].sum()), ""),
    ]
    for source in rules.ALL_SOURCES:
        rows.append(("Events per source", source, int(result.events.get(source, 0)), ""))
    for source in rules.ALL_SOURCES:
        rows.append(("Collapsed rows (rule 1)", source, int(result.collapsed.get(source, 0)), ""))
    rows.append(("Unmatched digital (rule 6)", "Total", len(unmatched), ""))
    for code in (rules.REASON_EXCLUDED, rules.REASON_NOT_RENEWAL, rules.REASON_NO_CONTRACT):
        rows.append(
            ("Unmatched digital (rule 6)", code, int((unmatched["reason_code"] == code).sum()), "")
        )
    rows.append(
        (
            "Unmatched digital (rule 6)",
            "web orders with look-ahead window still open",
            int(unmatched["window_open"].sum()),
            "",
        )
    )
    rows.append(("Web look-ahead (rule 7)", "Links", len(result.links), ""))
    rows.append(
        (
            "Web look-ahead (rule 7)",
            "Links from orders placed before the period",
            int(result.links["before_period"].sum()) if len(result.links) else 0,
            "",
        )
    )
    treatment = (
        "added on both sides" if result.variant == rules.VARIANT_FULL else "excluded (strict)"
    )
    rows.append(
        (
            "Variant (rule 10)",
            f"Web renewals without contract record - {treatment}",
            result.web_without_contract,
            "",
        )
    )
    rows.append(
        (
            "Invariants",
            "Agents above 100 % digital share",
            int((agents["digital"] > agents["renewals"]).sum()),
            "must be 0",
        )
    )
    rows.append(
        (
            "Invariants",
            "Shops above 100 % digital share",
            int((shops["digital"] > shops["renewals"]).sum()),
            "must be 0",
        )
    )
    rows.append(
        (
            "Invariants",
            "Blocks where agent rows != block row",
            mismatched_blocks(v4_report(result)) or 0,
            "must be 0",
        )
    )
    rows.append(
        (
            "Invariants",
            "Duplicate renewal keys",
            int(len(renewals) - renewals["key"].nunique()),
            "must be 0",
        )
    )
    rows.append(
        (
            "Master data",
            "Agents without a display name",
            int(agents.loc[agents["agent_name"] == rules.NO_DISPLAY_NAME, "agent"].nunique()),
            "review",
        )
    )
    frame = pd.DataFrame(rows, columns=["section", "metric", "value", "expectation"])
    frame["status"] = [
        ("OK" if value == 0 else "CHECK") if expectation == "must be 0" else ""
        for value, expectation in zip(frame["value"], frame["expectation"], strict=True)
    ]
    return frame


def read_manual_count(path: Path) -> pd.DataFrame:
    """Read the manual count (agent login, renewals)."""
    raw = read_table(path, ["agent login", "manual renewals"])
    return pd.DataFrame(
        {
            "agent": normalize_login_series(raw["agent login"]),
            "manual": pd.to_numeric(raw["manual renewals"], errors="coerce").fillna(0).astype(int),
        }
    )


def reconcile(result: V4Result, manual: pd.DataFrame) -> pd.DataFrame:
    """Per-agent engine totals next to the manual count (agents in two shops summed)."""
    grouped = result.renewals.groupby("agent")
    engine = pd.DataFrame(
        {
            "name": grouped["agent_name"].first(),
            "engine": grouped["renewals"].sum().astype(int),
        }
    ).reset_index()
    table = engine.merge(manual, on="agent", how="outer")
    table["name"] = table["name"].fillna("")
    table["engine"] = table["engine"].fillna(0).astype(int)
    table["manual"] = table["manual"].fillna(0).astype(int)
    table["difference"] = table["engine"] - table["manual"]
    table["status"] = ["match" if d == 0 else "difference" for d in table["difference"]]
    return table.sort_values(["status", "agent"], ascending=[True, True]).reset_index(drop=True)
