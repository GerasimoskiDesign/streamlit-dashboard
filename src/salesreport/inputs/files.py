"""Locating the daily source files.

Layout: ``<data>/daily/<Month>/<DD.MM.YYYY>/<source>_<DD.MM.YYYY>.xlsx``.

Real folders are not that tidy, so resolution is tolerant on purpose:

* the day and month in the file name may be zero-padded or not (``4.09.2026``);
* a file name may be typed with Cyrillic letters that look Latin (``с`` instead of
  ``c``) - visually identical, but a plain string match would call the file missing;
* the same day may hold two files for one source after a partial re-export.

Tolerance must not turn into guessing, though. When more than one candidate matches a
source/day, resolution refuses and asks for an explicit entry in the override table
(``config/overrides.csv``) that names the file(s) to use and why.
"""

from __future__ import annotations

import csv
import re
import unicodedata
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from salesreport.dates import fmt

#: Cyrillic letters that are visually identical to Latin ones in file names.
HOMOGLYPHS = str.maketrans(
    {
        "а": "a", "с": "c", "е": "e", "о": "o", "р": "p", "х": "x", "у": "y",
        "ѕ": "s", "і": "i", "ј": "j", "ԁ": "d", "һ": "h", "ӏ": "l",
        "А": "A", "В": "B", "С": "C", "Е": "E", "Н": "H", "К": "K", "М": "M",
        "О": "O", "Р": "P", "Т": "T", "Х": "X", "Ѕ": "S", "І": "I", "Ј": "J",
    }
)  # fmt: skip

MONTH_NAMES = (
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
)  # fmt: skip

_NAME = re.compile(
    r"^(?P<source>[a-z_]+?)_(?P<d>\d{1,2})\.(?P<m>\d{1,2})\.(?P<y>\d{4})(?P<suffix>[^/\\]*)\.xlsx$"
)


class AmbiguousFilesError(ValueError):
    """More than one file matches a source/day and no override says which to use."""


@dataclass(frozen=True)
class Override:
    """One row of the override table."""

    day: date
    source: str
    files: tuple[str, ...]
    reason: str


def canonical_name(name: str) -> str:
    """File name with Unicode compatibility folding, homoglyphs mapped to Latin, lower case."""
    return unicodedata.normalize("NFKC", name).translate(HOMOGLYPHS).lower()


def month_folder(day: date) -> str:
    """Month folder name, e.g. ``September`` (fixed English names, independent of locale)."""
    return MONTH_NAMES[day.month - 1]


def day_folder(data_dir: Path, day: date) -> Path:
    """Folder holding all source files for one day."""
    return data_dir / "daily" / month_folder(day) / fmt(day)


def load_overrides(path: Path | None) -> dict[tuple[date, str], Override]:
    """Read ``date,source,files,reason`` rows; ``files`` is a ``;``-separated list."""
    if path is None or not path.exists():
        return {}
    table: dict[tuple[date, str], Override] = {}
    with path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            if not row.get("date") or row["date"].startswith("#"):
                continue
            d, m, y = (int(p) for p in row["date"].strip().split("."))
            entry = Override(
                day=date(y, m, d),
                source=row["source"].strip(),
                files=tuple(f.strip() for f in row["files"].split(";") if f.strip()),
                reason=(row.get("reason") or "").strip(),
            )
            table[(entry.day, entry.source)] = entry
    return table


def candidates(folder: Path, source: str, day: date) -> list[Path]:
    """All files in ``folder`` that look like ``source`` for ``day`` (tolerant match)."""
    if not folder.is_dir():
        return []
    found = []
    for path in sorted(folder.iterdir()):
        if not path.is_file() or path.name.startswith("~$"):
            continue
        match = _NAME.match(canonical_name(path.name))
        if not match or match.group("source") != source:
            continue
        try:
            file_day = date(int(match.group("y")), int(match.group("m")), int(match.group("d")))
        except ValueError:
            continue
        if file_day == day:
            found.append(path)
    return found


def resolve_files(
    data_dir: Path,
    source: str,
    day: date,
    overrides: dict[tuple[date, str], Override] | None = None,
) -> list[Path]:
    """Return the file(s) to read for ``source`` on ``day``.

    Returns an empty list when nothing matches (the preflight check reports it).

    Raises:
        AmbiguousFilesError: several candidates and no override entry.
        FileNotFoundError: an override names a file that does not exist.
    """
    folder = day_folder(data_dir, day)
    override = (overrides or {}).get((day, source))
    if override is not None:
        paths = [folder / name for name in override.files]
        missing = [p.name for p in paths if not p.exists()]
        if missing:
            raise FileNotFoundError(
                f"override for {source} {fmt(day)} names missing files {missing}"
            )
        return paths
    found = candidates(folder, source, day)
    if len(found) > 1:
        names = ", ".join(p.name for p in found)
        raise AmbiguousFilesError(
            f"{source} {fmt(day)}: {len(found)} candidate files ({names}); "
            "add an entry to the override table to say which to use"
        )
    return found
