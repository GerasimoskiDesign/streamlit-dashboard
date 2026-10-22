"""Forgiving report-date input and small date helpers.

The person running the report types whatever is quickest: ``17.09.2026``, ``17.09``,
``17``, or pastes the range they see in another report (``01.09.2026-17.09.2026``).
All of these mean "month to date, up to the 17th", so the parser accepts them and
always returns the end date. The *reference* date (for a missing month/year) is an
argument - never the system clock - so the same input always gives the same result.
"""

from __future__ import annotations

import calendar
import re
from datetime import date, datetime, timedelta

_RANGE_SPLIT = re.compile(r"\s*[-–—]\s*(?=\d)")
_FULL = re.compile(r"^(\d{1,2})\.(\d{1,2})\.(\d{4})\.?$")
_DAY_MONTH = re.compile(r"^(\d{1,2})\.(\d{1,2})\.?$")
_DAY = re.compile(r"^(\d{1,2})\.?$")
_ISO = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")


class DateInputError(ValueError):
    """Raised when a report date cannot be understood."""


def parse_report_date(text: str, reference: date) -> date:
    """Parse a forgiving report-date string.

    Args:
        text: ``17.09.2026``, ``17.09``, ``17``, ``2026-09-17`` or a range such as
            ``01.09.2026-17.09.2026`` (the end date is taken).
        reference: supplies the month/year when the input omits them.

    Raises:
        DateInputError: if the text is empty or not a valid calendar date.
    """
    raw = (text or "").strip()
    if not raw:
        raise DateInputError("empty date")
    if _ISO.match(raw):
        try:
            return date.fromisoformat(raw)
        except ValueError as exc:
            raise DateInputError(f"not a valid date: {text!r}") from exc
    parts = _RANGE_SPLIT.split(raw)
    candidate = parts[-1].strip()
    try:
        if m := _FULL.match(candidate):
            return date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
        if m := _DAY_MONTH.match(candidate):
            return date(reference.year, int(m.group(2)), int(m.group(1)))
        if m := _DAY.match(candidate):
            return date(reference.year, reference.month, int(m.group(1)))
    except ValueError as exc:
        raise DateInputError(f"not a valid date: {text!r}") from exc
    raise DateInputError(
        f"could not read {text!r}; use 17.09.2026, 17.09, 17 or 01.09.2026-17.09.2026"
    )


def parse_cell_date(value: object) -> date | None:
    """Read a date from an Excel cell that may hold a datetime, a date or text."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    if not text:
        return None
    for fmt in ("%d.%m.%Y %H:%M:%S", "%d.%m.%Y %H:%M", "%d.%m.%Y", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def month_start(day: date) -> date:
    """First day of the month containing ``day``."""
    return day.replace(day=1)


def month_end(day: date) -> date:
    """Last day of the month containing ``day``."""
    return day.replace(day=calendar.monthrange(day.year, day.month)[1])


def add_months(day: date, months: int) -> date:
    """Shift by whole months, clamping the day (31 Mar - 1 month -> 28/29 Feb)."""
    month_index = day.year * 12 + (day.month - 1) + months
    year, month = divmod(month_index, 12)
    month += 1
    last = calendar.monthrange(year, month)[1]
    return date(year, month, min(day.day, last))


def days_between(start: date, end: date) -> list[date]:
    """Inclusive list of days from ``start`` to ``end``."""
    return [start + timedelta(days=i) for i in range((end - start).days + 1)]


def fmt(day: date) -> str:
    """The DD.MM.YYYY format used in folder and file names."""
    return day.strftime("%d.%m.%Y")
