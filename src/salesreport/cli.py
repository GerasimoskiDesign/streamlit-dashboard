"""Command line: ``python -m salesreport <command>``.

Commands: generate, build, verify, lock, preflight, charts, dashboard.
"""

from __future__ import annotations

import argparse
import logging
import subprocess
import sys
from datetime import date
from pathlib import Path

from salesreport import rules, settings
from salesreport.dates import DateInputError, fmt, month_start, parse_report_date

log = logging.getLogger("salesreport")


def _latest_data_day(data_dir: Path) -> date | None:
    """Most recent day folder; used only as the reference for short date input."""
    days = []
    for folder in (data_dir / "daily").glob("*/*"):
        try:
            d, m, y = (int(p) for p in folder.name.split("."))
            days.append(date(y, m, d))
        except ValueError:
            continue
    return max(days) if days else None


def _resolve_date(text: str | None, data_dir: Path) -> date:
    reference = _latest_data_day(data_dir) or date(2026, 9, 30)
    if text is None:
        if not sys.stdin.isatty():
            raise DateInputError("no report date given (pass e.g. 17.09.2026)")
        text = input("Report date (17.09.2026, 17.09, 17 or 01.09.2026-17.09.2026): ")
    return parse_report_date(text, reference)


def cmd_generate(args: argparse.Namespace) -> int:
    from salesreport.generator import GeneratorConfig, generate

    cfg = GeneratorConfig(seed=args.seed)
    if args.start or args.end:
        cfg = GeneratorConfig(
            seed=args.seed,
            start=parse_report_date(args.start, cfg.start) if args.start else cfg.start,
            end=parse_report_date(args.end, cfg.end) if args.end else cfg.end,
        )
    result = generate(cfg, args.data_dir)
    log.info(
        "synthetic data ready: %d renewals, %d shops, %d agents, %s..%s",
        len(result.truth),
        len(result.master.shops),
        len(result.master.agents),
        fmt(cfg.start),
        fmt(cfg.end),
    )
    return 0


def cmd_build(args: argparse.Namespace) -> int:
    from salesreport.inputs.preflight import PreflightError
    from salesreport.lock import LogicModifiedError
    from salesreport.report.build import build

    as_of = _resolve_date(args.date, args.data_dir)
    log.info("report date %s (month to date from %s)", fmt(as_of), fmt(month_start(as_of)))
    try:
        outputs = build(
            as_of,
            args.data_dir,
            args.out_dir,
            overrides_path=args.overrides,
            variant=args.variant,
            lookahead_days=args.lookahead,
            history=args.history,
        )
    except LogicModifiedError as exc:
        log.error("%s", exc)
        log.error(
            "refusing to build. Review the change, re-validate, then run "
            "`python -m salesreport lock`."
        )
        return 3
    except PreflightError as exc:
        log.error("%s", exc)
        log.error("refusing to build from incomplete inputs.")
        return 4
    from salesreport.report.verify import verify_workbook

    check = verify_workbook(outputs.excel_path)
    if not check.ok:
        for failure in check.failures:
            log.error("verify: %s", failure)
        return 5
    log.info("verify OK (%d blocks, %d rows)", check.blocks_checked, check.rows_checked)
    log.info("report: %s", outputs.excel_path)
    return 0


def cmd_verify(args: argparse.Namespace) -> int:
    from salesreport.report.verify import verify_workbook

    path = args.workbook
    if path is None:
        found = sorted(args.out_dir.glob("sales_report_*.xlsx"), key=lambda p: p.stat().st_mtime)
        if not found:
            log.error("no workbook found in %s", args.out_dir)
            return 2
        path = found[-1]
    result = verify_workbook(path)
    if result.ok:
        log.info(
            "OK - %s: %d blocks and %d rows verified",
            path.name,
            result.blocks_checked,
            result.rows_checked,
        )
        return 0
    log.error("FAILED - %s", path.name)
    for failure in result.failures:
        log.error("  %s", failure)
    return 1


def cmd_lock(args: argparse.Namespace) -> int:
    from salesreport.lock import check_manifest, write_manifest

    if args.check:
        problems = check_manifest()
        if problems:
            for problem in problems:
                log.error("%s", problem)
            return 3
        log.info("lock OK - engine files match LOCKED_LOGIC.sha256")
        return 0
    path = write_manifest()
    log.info("wrote %s - commit it together with the reviewed change", path.name)
    return 0


def cmd_preflight(args: argparse.Namespace) -> int:
    from salesreport.inputs.files import load_overrides
    from salesreport.inputs.preflight import preflight

    as_of = _resolve_date(args.date, args.data_dir)
    report = preflight(args.data_dir, month_start(as_of), as_of, load_overrides(args.overrides))
    if report.ok:
        log.info("preflight OK: %s..%s", fmt(report.start), fmt(report.end))
        return 0
    for problem in report.problems():
        log.error("%s", problem)
    return 4


def cmd_charts(args: argparse.Namespace) -> int:
    from salesreport.report.charts import render_charts

    render_charts(args.dataset, args.out)
    return 0


def cmd_dashboard(args: argparse.Namespace) -> int:
    app = Path(__file__).parent / "dashboard" / "app.py"
    command = [sys.executable, "-m", "streamlit", "run", str(app), "--server.port", str(args.port)]
    if args.headless:
        command += ["--server.headless", "true"]
    log.info("starting dashboard on port %d (Ctrl+C to stop)", args.port)
    return subprocess.call(command, cwd=settings.PROJECT_ROOT)


def parser() -> argparse.ArgumentParser:
    """Argument parser for all commands."""
    p = argparse.ArgumentParser(prog="python -m salesreport", description=__doc__)
    p.add_argument("-v", "--verbose", action="store_true", help="debug logging")
    sub = p.add_subparsers(dest="command", required=True)

    def common(sp: argparse.ArgumentParser) -> None:
        sp.add_argument("--data-dir", type=Path, default=settings.data_dir())
        sp.add_argument("--out-dir", type=Path, default=settings.output_dir())
        sp.add_argument("--overrides", type=Path, default=settings.overrides_file())

    g = sub.add_parser("generate", help="write the seeded synthetic daily files")
    common(g)
    g.add_argument("--seed", type=int, default=42)
    g.add_argument("--start", help="first day, e.g. 01.07.2026")
    g.add_argument("--end", help="last day, e.g. 30.09.2026")
    g.set_defaults(func=cmd_generate)

    b = sub.add_parser("build", help="build the month-to-date report up to DATE")
    common(b)
    b.add_argument("date", nargs="?", help="17.09.2026, 17.09, 17 or 01.09.2026-17.09.2026")
    b.add_argument("--variant", choices=rules.VARIANTS, default=rules.VARIANT_STRICT)
    b.add_argument("--lookahead", type=int, default=rules.LOOKAHEAD_DAYS_DEFAULT)
    b.add_argument("--history", type=int, default=2, help="earlier months for the dashboard")
    b.set_defaults(func=cmd_build)

    v = sub.add_parser("verify", help="check a generated workbook")
    common(v)
    v.add_argument("workbook", nargs="?", type=Path)
    v.set_defaults(func=cmd_verify)

    lk = sub.add_parser("lock", help="regenerate LOCKED_LOGIC.sha256 after a reviewed change")
    lk.add_argument("--check", action="store_true", help="only verify, do not rewrite")
    lk.set_defaults(func=cmd_lock)

    pf = sub.add_parser("preflight", help="check that all daily inputs exist")
    common(pf)
    pf.add_argument("date", nargs="?")
    pf.set_defaults(func=cmd_preflight)

    ch = sub.add_parser("charts", help="render README charts from the dashboard dataset")
    ch.add_argument("--dataset", type=Path, default=settings.output_dir() / "dashboard")
    ch.add_argument("--out", type=Path, default=settings.PROJECT_ROOT / "docs" / "img")
    ch.set_defaults(func=cmd_charts)

    d = sub.add_parser("dashboard", help="start the Streamlit dashboard")
    d.add_argument("--port", type=int, default=8501)
    d.add_argument("--headless", action="store_true")
    d.set_defaults(func=cmd_dashboard)
    return p


def main(argv: list[str] | None = None) -> int:
    """Entry point."""
    args = parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)-7s %(message)s",
    )
    try:
        return int(args.func(args))
    except DateInputError as exc:
        log.error("%s", exc)
        return 2
