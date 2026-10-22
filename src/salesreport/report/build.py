"""``python -m salesreport build <date>`` - the full report run.

Order matters and is the point of the production hardening:

1. verify the logic lock (refuse to publish numbers from modified logic);
2. preflight every input day from day 1 (refuse to build from incomplete inputs);
3. load once, compute month-to-date from day 1 (rule 8) plus history months for the
   dashboard's "vs last month" comparison;
4. write the Excel report, then the Parquet dataset the dashboard reads.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

from salesreport import rules
from salesreport.dates import add_months, fmt, month_end, month_start
from salesreport.engine.common import Period
from salesreport.engine.compare import all_versions, block_comparison, evolution_table, unit_shares
from salesreport.engine.v4 import V4Result, run_v4
from salesreport.inputs.files import day_folder, load_overrides
from salesreport.inputs.loader import load_master, load_sources, lookback_start
from salesreport.inputs.preflight import preflight, require_complete
from salesreport.lock import verify_lock
from salesreport.report.controls import control_totals, read_manual_count, reconcile
from salesreport.report.dataset import write_dataset
from salesreport.report.excel import ReportInputs, write_workbook

log = logging.getLogger(__name__)

_MANUAL = re.compile(r"manual_count_(\d{2}\.\d{2}\.\d{4})-(\d{2}\.\d{2}\.\d{4})\.xlsx$")


@dataclass
class BuildOutputs:
    """Paths and in-memory results of a build (used by tests and the CLI)."""

    excel_path: Path
    dataset_dir: Path
    v4: V4Result
    history: dict[str, V4Result]
    evolution: pd.DataFrame
    controls: pd.DataFrame
    reconciliation: pd.DataFrame | None


def _parse(text: str) -> date:
    d, m, y = (int(p) for p in text.split("."))
    return date(y, m, d)


def find_manual_count(data_dir: Path, as_of: date) -> tuple[Path, date, date] | None:
    """A manual count file whose period lies inside the report month and is complete."""
    folder = data_dir / "manual_count"
    if not folder.is_dir():
        return None
    for path in sorted(folder.glob("manual_count_*.xlsx")):
        match = _MANUAL.search(path.name)
        if not match:
            continue
        start, end = _parse(match.group(1)), _parse(match.group(2))
        if month_start(as_of) <= start and end <= as_of:
            return path, start, end
    return None


def history_months(data_dir: Path, as_of: date, count: int) -> list[date]:
    """Earlier month starts that have data from day 1 (oldest first)."""
    months = []
    for back in range(count, 0, -1):
        first = add_months(month_start(as_of), -back)
        if day_folder(data_dir, first).is_dir():
            months.append(first)
    return months


def build(
    as_of: date,
    data_dir: Path,
    out_dir: Path,
    overrides_path: Path | None = None,
    variant: str = rules.VARIANT_STRICT,
    lookahead_days: int = rules.LOOKAHEAD_DAYS_DEFAULT,
    history: int = 2,
    check_lock: bool = True,
) -> BuildOutputs:
    """Run the whole report for the month containing ``as_of``."""
    if check_lock:
        verify_lock()
        log.info("logic lock verified")
    overrides = load_overrides(overrides_path)
    start = month_start(as_of)
    months = history_months(data_dir, as_of, history)
    first = months[0] if months else start
    look_back = lookback_start(first, lookahead_days)
    optional = tuple(look_back + timedelta(days=i) for i in range((first - look_back).days))
    report = preflight(data_dir, first, as_of, overrides, optional_days=optional)
    for warning in report.warnings:
        log.warning("preflight: %s", warning)
    require_complete(report)
    log.info("preflight OK: %s..%s, all sources present", fmt(first), fmt(as_of))

    master = load_master(data_dir)
    sources = load_sources(data_dir, look_back, as_of, overrides)

    # Rule 8: always from day 1 of the month to the chosen day.
    period = Period(start, as_of)
    v4 = run_v4(sources, master, period, lookahead_days, variant)
    results = {f"{start:%Y-%m}": v4}
    for month in months:
        hist_period = Period(month, month_end(month))
        results[f"{month:%Y-%m}"] = run_v4(sources, master, hist_period, lookahead_days, variant)

    reports = all_versions(sources, master, period, v4)
    evolution = evolution_table(reports)
    comparison = block_comparison(reports[2], reports[3])
    controls = control_totals(v4)

    reconciliation = None
    note = "No manual count file for this month."
    manual = find_manual_count(data_dir, as_of)
    if manual:
        path, m_start, m_end = manual
        recon_run = run_v4(
            sources, master, Period(m_start, m_end, visible_until=as_of), lookahead_days, variant
        )
        reconciliation = reconcile(recon_run, read_manual_count(path))
        differences = int((reconciliation["status"] != "match").sum())
        note = (
            f"Independent manual count {fmt(m_start)}-{fmt(m_end)} ({path.name}); "
            f"{len(reconciliation) - differences} agents match, {differences} differ. "
            "Used to validate the logic before it was locked."
        )

    excel_path = write_workbook(
        ReportInputs(
            v4=v4,
            controls=controls,
            evolution=evolution,
            comparison=comparison,
            reconciliation=reconciliation,
            reconciliation_note=note,
        ),
        out_dir / f"sales_report_{fmt(as_of)}.xlsx",
    )
    log.info("wrote %s", excel_path)
    dataset_dir = write_dataset(
        out_dir / "dashboard", as_of, results, evolution, unit_shares(reports), controls, v4
    )
    log.info("wrote dashboard dataset to %s", dataset_dir)
    return BuildOutputs(
        excel_path=excel_path,
        dataset_dir=dataset_dir,
        v4=v4,
        history=results,
        evolution=evolution,
        controls=controls,
        reconciliation=reconciliation,
    )
