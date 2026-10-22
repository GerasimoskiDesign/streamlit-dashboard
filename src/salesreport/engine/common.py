"""Shared engine types and helpers (LOCKED).

The period type carries three dates on purpose: the reporting window (``start`` ..
``end``) and the date up to which files are *visible* (``as_of``). Normally they are
the same, but the reconciliation sheet recomputes an earlier week with everything
that is known today, including late bookings that arrived after that week.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import pandas as pd

from salesreport import rules

COUNT_COLUMNS = (
    "store",
    "selfservice",
    "web_nocontract",
    "renewals",
    "ss_digital",
    "express",
    "cc",
    "web",
    "digital",
    "cc_only",
    "digital_excl_cc",
)


@dataclass(frozen=True)
class Period:
    """Reporting window plus the visibility date for input files."""

    start: date
    end: date
    visible_until: date | None = None

    @property
    def as_of(self) -> date:
        return self.visible_until or self.end

    def __post_init__(self) -> None:
        if self.end < self.start:
            raise ValueError(f"period end {self.end} is before start {self.start}")
        if self.visible_until is not None and self.visible_until < self.end:
            raise ValueError("files must be visible at least up to the period end")


def ts(day: date) -> pd.Timestamp:
    """Midnight timestamp for a date (all engine dates are midnight timestamps)."""
    return pd.Timestamp(day)


def with_key(frame: pd.DataFrame) -> pd.DataFrame:
    """Add the renewal key column: ``YYYY-MM-DD|phone`` (rule 1)."""
    out = frame.copy()
    if len(out):
        out["key"] = out["date"].dt.strftime("%Y-%m-%d").astype(object) + "|" + out["phone"]
    else:
        out["key"] = pd.Series(dtype=object)
    return out


def shifted_keys(frame: pd.DataFrame, days: int) -> pd.Series:
    """Key of the same phone number ``days`` later."""
    if not len(frame):
        return pd.Series(dtype=object)
    shifted = (frame["date"] + pd.Timedelta(days=days)).dt.strftime("%Y-%m-%d").astype(object)
    return shifted + "|" + frame["phone"]


def between(frame: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    """Rows whose ``date`` lies in ``[start, end]``."""
    return frame.loc[(frame["date"] >= start) & (frame["date"] <= end)]


def is_qualifying_contract(frame: pd.DataFrame) -> pd.Series:
    """Rule 2: status active/signed and a renewal contract type."""
    return frame["status"].isin(rules.QUALIFYING_STATUSES) & frame["contract_type"].isin(
        rules.RENEWAL_TYPES
    )


def collapse(frame: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    """Rule 1: keep one row per key; return the kept rows and how many were collapsed.

    The first row by (file date, file name, row number) wins, so the result does not
    depend on the order in which files were listed.
    """
    if not len(frame):
        return frame, 0
    ordered = frame.sort_values(["key", "file_date", "source_file", "row_no"], kind="stable")
    kept = ordered.drop_duplicates("key", keep="first")
    return kept, len(frame) - len(kept)


def share(numerator: float, denominator: float) -> float | None:
    """Digital share, or ``None`` when there is nothing to divide by."""
    return None if denominator == 0 else numerator / denominator
