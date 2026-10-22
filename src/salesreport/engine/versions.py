"""Shared result type for the four logic versions and their common input filtering.

All versions read the *same* normalised inputs, so differences in the output come
only from the counting logic - which is the point of the "How it evolved" comparison.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from salesreport.engine.common import Period, between, ts, with_key


@dataclass
class VersionReport:
    """Block rows (shops / channels), optional agent rows, and a double-count measure."""

    version: str
    title: str
    digital_sources: str
    blocks: pd.DataFrame  # block_id, block_type, block_name, region, total, digital
    agents: pd.DataFrame | None  # block_id, agent, total, digital
    double_counted: int


def visible_in_period(sources: dict[str, pd.DataFrame], period: Period) -> dict[str, pd.DataFrame]:
    """Rows dated inside the period from files visible at ``period.as_of``, with keys."""
    start, end, as_of = ts(period.start), ts(period.end), ts(period.as_of)
    return {
        name: with_key(between(frame.loc[frame["file_date"] <= as_of], start, end))
        for name, frame in sources.items()
    }


def duplicates(frame: pd.DataFrame) -> int:
    """Rows counted beyond the first for the same (date, phone) key."""
    return 0 if not len(frame) else int(len(frame) - frame["key"].nunique())
