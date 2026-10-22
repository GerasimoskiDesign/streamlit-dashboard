"""Loading the engine's Parquet output for the dashboard (read-only, no business logic)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

import pandas as pd

from salesreport.report.dataset import FILES


@dataclass
class Dataset:
    """Everything the dashboard reads, exactly as the engine wrote it."""

    daily: pd.DataFrame
    evolution: pd.DataFrame
    unit_shares: pd.DataFrame
    controls: pd.DataFrame
    unmatched: pd.DataFrame
    meta: dict
    refreshed_at: datetime

    @property
    def as_of(self) -> date:
        return date.fromisoformat(self.meta["as_of"])

    @property
    def period_start(self) -> date:
        return date.fromisoformat(self.meta["period_start"])


def dataset_available(folder: Path) -> bool:
    """True when the engine has written a complete dataset into ``folder``."""
    return all((folder / name).exists() for name in FILES.values())


def load_dataset(folder: Path) -> Dataset:
    """Read all dashboard files from ``folder``."""
    daily = pd.read_parquet(folder / FILES["daily"])
    daily["date"] = pd.to_datetime(daily["date"])
    return Dataset(
        daily=daily,
        evolution=pd.read_parquet(folder / FILES["evolution"]),
        unit_shares=pd.read_parquet(folder / FILES["unit_shares"]),
        controls=pd.read_parquet(folder / FILES["controls"]),
        unmatched=pd.read_parquet(folder / FILES["unmatched"]),
        meta=json.loads((folder / FILES["meta"]).read_text(encoding="utf-8")),
        refreshed_at=datetime.fromtimestamp((folder / FILES["daily"]).stat().st_mtime),
    )


def totals(frame: pd.DataFrame) -> dict[str, float | None]:
    """KPI sums of engine-computed counts (summing, not re-deciding anything)."""
    renewals = float(frame["renewals"].sum()) if len(frame) else 0.0
    digital = float(frame["digital"].sum()) if len(frame) else 0.0
    excl = float(frame["digital_excl_cc"].sum()) if len(frame) else 0.0
    return {
        "renewals": renewals,
        "digital": digital,
        "share": digital / renewals if renewals else None,
        "share_excl_cc": excl / renewals if renewals else None,
    }
