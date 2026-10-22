"""Load and type the daily sources and the master data (LOCKED).

Each source has a small spec: the column names that must be present (used to find the
header row) and the canonical field each one maps to. After reading, every value is
normalised once - dates to midnight timestamps, phones to digits, codes and free text
to their comparable forms - so the engine never compares raw strings.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

from salesreport import rules
from salesreport.dates import days_between, parse_cell_date
from salesreport.engine.model import Master
from salesreport.inputs.excel_reader import read_table
from salesreport.inputs.files import Override, resolve_files
from salesreport.normalize import (
    normalize_code_series,
    normalize_login_series,
    normalize_phone_series,
    normalize_text_series,
)

log = logging.getLogger(__name__)

_CONTRACT = {
    "contract date": "date",
    "msisdn": "phone",
    "contract type": "contract_type",
    "status": "status",
    "sales point": "sales_point",
    "agent login": "agent",
    "contract id": "record_id",
}

#: required column (normalised header) -> canonical field, per source
SOURCE_SPECS: dict[str, dict[str, str]] = {
    rules.STORE: _CONTRACT,
    rules.SELFSERVICE: _CONTRACT,
    rules.EXPRESS: {
        "flow date": "date",
        "phone": "phone",
        "agent": "agent",
        "sales point": "sales_point",
        "flow id": "record_id",
    },
    rules.CLICK_COLLECT: {
        "order date": "date",
        "phone number": "phone",
        "order id": "record_id",
        "pickup shop": "sales_point",
    },
    rules.WEB: {
        "order date": "date",
        "phone": "phone",
        "order no": "record_id",
        "order type": "order_type",
        "sales point": "sales_point",
    },
    rules.TARIFF: {
        "change date": "date",
        "msisdn": "phone",
        "change type": "change_type",
        "product": "product",
    },
}

_TEXT_FIELDS = ("contract_type", "status", "order_type", "change_type", "product")
BASE_COLUMNS = ("date", "phone", "file_date", "source_file", "row_no")


def empty_source(source: str) -> pd.DataFrame:
    """An empty, correctly typed frame for ``source``."""
    columns = list(BASE_COLUMNS) + [
        c for c in SOURCE_SPECS[source].values() if c not in BASE_COLUMNS
    ]
    frame = pd.DataFrame({c: pd.Series(dtype=object) for c in columns})
    frame["date"] = pd.to_datetime(frame["date"])
    frame["file_date"] = pd.to_datetime(frame["file_date"])
    return frame


def type_source(raw: pd.DataFrame, source: str, file_day: date, file_name: str) -> pd.DataFrame:
    """Rename to canonical fields and normalise every value.

    Rows without a readable date or phone number cannot form a key (rule 1) and are
    dropped with a warning rather than guessed.
    """
    spec = SOURCE_SPECS[source]
    frame = raw.loc[:, list(spec)].rename(columns=spec).copy()
    frame["date"] = pd.to_datetime([parse_cell_date(v) for v in frame["date"]])
    frame["phone"] = normalize_phone_series(frame["phone"])
    for column in _TEXT_FIELDS:
        if column in frame:
            frame[column] = normalize_text_series(frame[column])
    if "sales_point" in frame:
        frame["sales_point"] = normalize_code_series(frame["sales_point"])
    if "agent" in frame:
        frame["agent"] = normalize_login_series(frame["agent"])
    if "record_id" in frame:
        frame["record_id"] = (
            frame["record_id"].map(lambda v: "" if v is None else str(v)).astype(object)
        )
    frame["file_date"] = pd.Timestamp(file_day)
    frame["source_file"] = file_name
    frame["row_no"] = range(1, len(frame) + 1)
    bad = frame["date"].isna() | (frame["phone"] == "")
    if bad.any():
        log.warning(
            "%s: dropped %d row(s) without a date or phone number", file_name, int(bad.sum())
        )
        frame = frame.loc[~bad]
    return frame.reset_index(drop=True)


def load_source_day(
    data_dir: Path,
    source: str,
    day: date,
    overrides: dict[tuple[date, str], Override] | None = None,
) -> pd.DataFrame | None:
    """Load one source for one day; ``None`` when no file exists for that day."""
    paths = resolve_files(data_dir, source, day, overrides)
    if not paths:
        return None
    frames = []
    for path in paths:
        raw = read_table(path, SOURCE_SPECS[source])
        frames.append(type_source(raw, source, day, path.name))
    return pd.concat(frames, ignore_index=True) if len(frames) > 1 else frames[0]


def load_sources(
    data_dir: Path,
    start: date,
    end: date,
    overrides: dict[tuple[date, str], Override] | None = None,
    sources: Iterable[str] = rules.ALL_SOURCES,
) -> dict[str, pd.DataFrame]:
    """Load every source for every day folder from ``start`` to ``end`` inclusive.

    Days that are missing are skipped here; the preflight check is what decides
    whether a missing day is acceptable.
    """
    result: dict[str, pd.DataFrame] = {}
    for source in sources:
        frames = []
        for day in days_between(start, end):
            frame = load_source_day(data_dir, source, day, overrides)
            if frame is not None and len(frame):
                frames.append(frame)
        result[source] = pd.concat(frames, ignore_index=True) if frames else empty_source(source)
        log.info("loaded %-22s %7d rows (%s..%s)", source, len(result[source]), start, end)
    return result


def load_master(data_dir: Path) -> Master:
    """Read ``master/shops.xlsx`` and ``master/agents.xlsx`` (same robust reader)."""
    shops_raw = read_table(
        data_dir / "master" / "shops.xlsx", ["shop id", "shop name", "region", "sales points"]
    )
    shops = pd.DataFrame(
        {
            "shop_id": normalize_code_series(shops_raw["shop id"]),
            "shop_name": shops_raw["shop name"].astype(str).str.strip(),
            "region": shops_raw["region"].astype(str).str.strip(),
            "sales_points": shops_raw["sales points"].astype(str),
        }
    )
    agents_raw = read_table(
        data_dir / "master" / "agents.xlsx", ["agent login", "display name", "home shop", "channel"]
    )
    agents = pd.DataFrame(
        {
            "login": normalize_login_series(agents_raw["agent login"]),
            "name": agents_raw["display name"].map(lambda v: "" if v is None else str(v)),
            "home_shop": normalize_code_series(agents_raw["home shop"]),
            "channel": agents_raw["channel"].map(lambda v: "" if v is None else str(v).strip()),
        }
    )
    return Master(shops=shops, agents=agents)


def lookback_start(start: date, lookahead_days: int) -> date:
    """First day to load so web orders placed before the period can still be linked (rule 7)."""
    return start - timedelta(days=lookahead_days)
