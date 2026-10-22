"""Parquet dataset for the dashboard.

The dashboard must never recompute business logic, so everything it shows is written
here by the engine: daily per-agent counts (already split into digital / C&C-only /
excl. C&C), the version comparison, the control totals and the unmatched audit.
Phone numbers are masked; the dashboard does not need them.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pandas as pd

from salesreport.dates import fmt
from salesreport.engine.common import COUNT_COLUMNS
from salesreport.engine.v4 import V4Result

GROUP = [
    "date",
    "block_id",
    "block_type",
    "block_name",
    "region",
    "channel_group",
    "agent",
    "agent_name",
]
FILES = {
    "daily": "daily_agent.parquet",
    "evolution": "evolution.parquet",
    "unit_shares": "unit_shares.parquet",
    "controls": "controls.parquet",
    "unmatched": "unmatched.parquet",
    "meta": "meta.json",
}


def mask_phone(phone: str) -> str:
    """Keep only the fake prefix and the last three digits."""
    return f"+{phone[:3]}-xxxx-{phone[-3:]}" if len(phone) > 6 else "+999-xxxx"


def daily_agent_rows(result: V4Result, month: str) -> pd.DataFrame:
    """Per day, block and agent counts for one month's result."""
    renewals = result.renewals.copy()
    renewals["region"] = renewals["region"].fillna("")
    daily = (
        renewals.groupby(GROUP, dropna=False)[list(COUNT_COLUMNS)].sum().astype(int).reset_index()
    )
    daily.insert(0, "month", month)
    return daily


def write_dataset(
    folder: Path,
    as_of: date,
    results: dict[str, V4Result],
    evolution: pd.DataFrame,
    shares: pd.DataFrame,
    controls: pd.DataFrame,
    current: V4Result,
) -> Path:
    """Write all dashboard files into ``folder``."""
    folder.mkdir(parents=True, exist_ok=True)
    daily = pd.concat(
        [daily_agent_rows(result, month) for month, result in sorted(results.items())],
        ignore_index=True,
    )
    daily.to_parquet(folder / FILES["daily"], index=False)
    evolution.to_parquet(folder / FILES["evolution"], index=False)
    shares.to_parquet(folder / FILES["unit_shares"], index=False)
    controls_out = controls.copy()
    controls_out["value"] = controls_out["value"].astype(int)
    controls_out.to_parquet(folder / FILES["controls"], index=False)
    unmatched = current.unmatched.copy()
    unmatched["phone"] = unmatched["phone"].map(mask_phone)
    unmatched.drop(columns=["record_id"]).to_parquet(folder / FILES["unmatched"], index=False)
    meta = {
        "as_of": as_of.isoformat(),
        "as_of_display": fmt(as_of),
        "period_start": current.period.start.isoformat(),
        "variant": current.variant,
        "lookahead_days": current.lookahead_days,
        "months": sorted(results),
        "logic": "v4",
    }
    (folder / FILES["meta"]).write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return folder
