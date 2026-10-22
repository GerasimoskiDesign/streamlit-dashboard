"""Preflight completeness check.

The report is month-to-date and always rebuilt from day 1 (rule 8), so one missing
daily folder silently lowers every number after it. Failing halfway through a build is
just as bad: half-written outputs look valid. The preflight therefore checks *every*
day and *every* required source up front, lists all problems at once, and the build
stops before anything is computed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from salesreport import rules
from salesreport.dates import days_between, fmt
from salesreport.inputs.files import AmbiguousFilesError, Override, day_folder, resolve_files


@dataclass
class PreflightReport:
    """Result of the completeness check."""

    start: date
    end: date
    missing_days: list[date] = field(default_factory=list)
    missing_files: list[tuple[date, str]] = field(default_factory=list)
    ambiguous: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not (self.missing_days or self.missing_files or self.ambiguous)

    def problems(self) -> list[str]:
        """Human-readable list of everything that blocks the build."""
        lines = [f"missing day folder: {fmt(d)}" for d in self.missing_days]
        lines += [f"missing file: {source} for {fmt(d)}" for d, source in self.missing_files]
        lines += [f"ambiguous: {text}" for text in self.ambiguous]
        return lines


class PreflightError(RuntimeError):
    """Raised when inputs are incomplete; the message lists every problem."""

    def __init__(self, report: PreflightReport) -> None:
        self.report = report
        joined = "\n  ".join(report.problems())
        super().__init__(
            f"inputs incomplete for {fmt(report.start)}..{fmt(report.end)}:\n  {joined}"
        )


def preflight(
    data_dir: Path,
    start: date,
    end: date,
    overrides: dict[tuple[date, str], Override] | None = None,
    sources: tuple[str, ...] = rules.ALL_SOURCES,
    optional_days: tuple[date, ...] = (),
) -> PreflightReport:
    """Check that each day from ``start`` to ``end`` has every required source file.

    ``optional_days`` (the web look-ahead days before the period) only produce warnings.
    """
    report = PreflightReport(start=start, end=end)
    for day in [*optional_days, *days_between(start, end)]:
        optional = day in optional_days
        if not day_folder(data_dir, day).is_dir():
            if optional:
                report.warnings.append(f"look-back day {fmt(day)} not available")
            else:
                report.missing_days.append(day)
            continue
        for source in sources:
            try:
                found = resolve_files(data_dir, source, day, overrides)
            except (AmbiguousFilesError, FileNotFoundError) as exc:
                report.ambiguous.append(str(exc))
                continue
            if not found:
                if optional:
                    report.warnings.append(f"look-back file {source} {fmt(day)} not available")
                else:
                    report.missing_files.append((day, source))
    return report


def require_complete(report: PreflightReport) -> None:
    """Raise :class:`PreflightError` unless the report is clean."""
    if not report.ok:
        raise PreflightError(report)
