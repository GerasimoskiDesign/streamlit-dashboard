"""Comparison of the four logic versions on the same inputs.

Three symptoms are measured for every version, because they are the ones a shop
manager notices first: digital share above 100 %, agent rows that do not add up to
their shop, and the same sale counted more than once.
"""

from __future__ import annotations

from collections.abc import Sequence

import pandas as pd

from salesreport.engine.common import Period
from salesreport.engine.model import Master
from salesreport.engine.v1 import run_v1
from salesreport.engine.v2 import run_v2
from salesreport.engine.v3 import run_v3
from salesreport.engine.v4 import V4Result
from salesreport.engine.versions import VersionReport

METRIC_LABELS = {
    "total_renewals": "Total renewals",
    "digital": "Digital (as counted)",
    "digital_share": "Network digital share",
    "agents_over_100": "Agents above 100 % digital share",
    "shops_over_100": "Shops above 100 % digital share",
    "mismatched_blocks": "Shops/channels where agent rows != shop row",
    "double_counted": "Same sale counted more than once",
}


def v4_report(result: V4Result) -> VersionReport:
    """Express a v4 result in the common version format."""
    blocks = result.block_rows().rename(columns={"renewals": "total"})
    agents = result.agent_rows().rename(columns={"renewals": "total"})
    return VersionReport(
        version="v4",
        title="Event-level engine",
        digital_sources="self-service, express, click & collect, web - flags on existing renewals",
        blocks=blocks[["block_id", "block_type", "block_name", "region", "total", "digital"]],
        agents=agents[["block_id", "agent", "total", "digital"]],
        double_counted=int(len(result.renewals) - result.renewals["key"].nunique()),
    )


def all_versions(
    sources: dict[str, pd.DataFrame], master: Master, period: Period, v4: V4Result
) -> list[VersionReport]:
    """Run v1-v3 on the same inputs and add the given v4 result."""
    return [
        run_v1(sources, master, period),
        run_v2(sources, master, period),
        run_v3(sources, master, period),
        v4_report(v4),
    ]


def mismatched_blocks(report: VersionReport) -> int | None:
    """Blocks whose agent rows do not sum to the block row (``None`` without agents)."""
    if report.agents is None:
        return None
    sums = report.agents.groupby("block_id")[["total", "digital"]].sum()
    rows = report.blocks.set_index("block_id")[["total", "digital"]]
    joined = rows.join(sums, how="outer", lsuffix="_block", rsuffix="_agents").fillna(0)
    differs = (joined["total_block"] != joined["total_agents"]) | (
        joined["digital_block"] != joined["digital_agents"]
    )
    return int(differs.sum())


def metrics(report: VersionReport) -> dict[str, object]:
    """The headline numbers for one version."""
    blocks = report.blocks
    total = int(blocks["total"].sum())
    digital = int(blocks["digital"].sum())
    shops = blocks.loc[blocks["block_type"] == "shop"]
    return {
        "version": report.version,
        "title": report.title,
        "digital_sources": report.digital_sources,
        "total_renewals": total,
        "digital": digital,
        "digital_share": (digital / total) if total else None,
        "agents_over_100": (
            None
            if report.agents is None
            else int((report.agents["digital"] > report.agents["total"]).sum())
        ),
        "shops_over_100": int((shops["digital"] > shops["total"]).sum()),
        "mismatched_blocks": mismatched_blocks(report),
        "double_counted": report.double_counted,
    }


def evolution_table(reports: Sequence[VersionReport]) -> pd.DataFrame:
    """One row per version with the headline metrics."""
    return pd.DataFrame([metrics(r) for r in reports])


def unit_shares(reports: Sequence[VersionReport]) -> pd.DataFrame:
    """Anonymous per-unit digital shares (shops and agents) for distribution charts.

    No names or ids are included, so the table is safe to show to every role.
    """
    rows = []
    for report in reports:
        shops = report.blocks.loc[report.blocks["block_type"] == "shop"]
        for total, digital in zip(shops["total"], shops["digital"], strict=True):
            if total:
                rows.append({"version": report.version, "level": "shop", "share": digital / total})
        if report.agents is not None:
            for total, digital in zip(
                report.agents["total"], report.agents["digital"], strict=True
            ):
                if total:
                    rows.append(
                        {"version": report.version, "level": "agent", "share": digital / total}
                    )
    return pd.DataFrame(rows, columns=["version", "level", "share"])


def block_comparison(v3: VersionReport, v4: VersionReport) -> pd.DataFrame:
    """Per-shop/channel v3 vs v4 table for the Excel comparison sheet."""
    agents3 = (
        v3.agents.groupby("block_id")[["total", "digital"]].sum() if v3.agents is not None else None
    )
    left = v3.blocks.set_index("block_id")
    right = v4.blocks.set_index("block_id")[["total", "digital"]]
    table = left.join(right, how="outer", lsuffix="_v3", rsuffix="_v4")
    if agents3 is not None:
        table = table.join(agents3.add_suffix("_v3_agent_sum"), how="left")
    for column in table.columns:
        if column.startswith(("total", "digital")):
            table[column] = table[column].fillna(0).astype(int)
    return table.reset_index().sort_values(["block_type", "block_id"])
