"""Robust inputs: normalisation, header detection, file-name resolution, preflight, dates."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from salesreport import rules
from salesreport.dates import DateInputError, add_months, parse_report_date
from salesreport.generator.writer import COLUMNS, write_table
from salesreport.inputs.excel_reader import HeaderNotFoundError, read_table
from salesreport.inputs.files import (
    AmbiguousFilesError,
    day_folder,
    load_overrides,
    resolve_files,
)
from salesreport.inputs.loader import load_source_day
from salesreport.inputs.preflight import PreflightError, preflight, require_complete
from salesreport.normalize import normalize_code, normalize_phone, normalize_text

REF = date(2026, 9, 30)


# --- text and phone normalisation --------------------------------------------------------
@pytest.mark.parametrize(
    "raw",
    [
        "Renewal_Only",
        "renewal only",
        "RENEWAL ONLY ",
        "renewal   only",
        "Renewal only",
        "Ｒenewal only",
    ],
)
def test_text_variants_normalise_to_the_same_value(raw):
    assert normalize_text(raw) == "renewal only"


def test_text_normalisation_handles_missing_values():
    assert normalize_text(None) == ""
    assert normalize_text(float("nan")) == ""
    assert normalize_text("Add-on") == normalize_text("ADD_ON") == "add on"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("+999 70 123 456", "99970123456"),
        (99970123456.0, "99970123456"),
        ("99970123456.0", "99970123456"),
        ("999-70-123-456", "99970123456"),
        ("+999 (70) 123456", "99970123456"),
        (99970123456, "99970123456"),
        (None, ""),
    ],
)
def test_phone_normalisation(raw, expected):
    assert normalize_phone(raw) == expected


def test_float_suffix_is_stripped_before_digits_not_appended():
    # the naive digits-only approach would turn "...456.0" into "...4560"
    assert normalize_phone("999123456.0") != "9991234560"


def test_code_normalisation():
    assert normalize_code(" sp101k ") == "SP101K"
    assert normalize_code("TS-01") == "TS-01"


# --- header auto-detection ----------------------------------------------------------------
def _rows():
    return [
        {
            "Contract Date": "10.09.2026",
            "MSISDN": "+999 70 111 222",
            "Contract Type": "Renewal_Only",
            "Status": "ACTIVE ",
            "Sales Point": " sp101 ",
            "Agent Login": "AGENT_001",
            "Contract ID": "C1",
        },
        {
            "Contract Date": "10.09.2026",
            "MSISDN": 99970111333.0,
            "Contract Type": "renewal with device",
            "Status": "signed",
            "Sales Point": "SP102",
            "Agent Login": "agent_002",
            "Contract ID": "C2",
        },
    ]


def test_header_detected_below_title_rows_and_footer_ignored(tmp_path: Path):
    path = tmp_path / "x.xlsx"
    write_table(
        path,
        COLUMNS[rules.STORE],
        _rows(),
        title_rows=[["Daily export - store contracts"], ["Export date 10.09.2026"], []],
        footer_after_blanks=6,
    )
    frame = read_table(path, ["contract date", "msisdn", "contract type"])
    assert len(frame) == 2  # footer "Rows exported" after a blank run is not data
    assert "contract date" in frame.columns


def test_header_found_on_second_sheet_and_in_upper_case(tmp_path: Path):
    path = tmp_path / "x.xlsx"
    write_table(path, COLUMNS[rules.STORE], _rows(), info_sheet=True, upper_header=True)
    frame = read_table(path, ["contract date", "msisdn"])
    assert len(frame) == 2


def test_isolated_blank_rows_do_not_stop_reading(tmp_path: Path):
    rows = [_rows()[0], {}, _rows()[1]]
    path = tmp_path / "x.xlsx"
    write_table(path, COLUMNS[rules.STORE], rows)
    assert len(read_table(path, ["msisdn"])) == 2


def test_missing_header_raises(tmp_path: Path):
    path = tmp_path / "x.xlsx"
    write_table(path, ["Something", "Else"], [{"Something": 1, "Else": 2}])
    with pytest.raises(HeaderNotFoundError):
        read_table(path, ["msisdn"])


def test_loader_types_and_normalises_a_messy_file(tmp_path: Path):
    day = date(2026, 9, 10)
    write_table(
        day_folder(tmp_path, day) / "store_contracts_10.09.2026.xlsx",
        COLUMNS[rules.STORE],
        _rows(),
        title_rows=[["title"]],
    )
    frame = load_source_day(tmp_path, rules.STORE, day)
    assert list(frame["phone"]) == ["99970111222", "99970111333"]
    assert list(frame["contract_type"]) == ["renewal only", "renewal with device"]
    assert list(frame["status"]) == ["active", "signed"]
    assert list(frame["sales_point"]) == ["SP101", "SP102"]
    assert list(frame["agent"]) == ["agent_001", "agent_002"]


# --- file-name resolution -----------------------------------------------------------------
def _touch(folder: Path, name: str) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / name
    write_table(path, COLUMNS[rules.STORE], [])
    return path


@pytest.mark.parametrize(
    "name",
    [
        "store_contracts_04.09.2026.xlsx",
        "store_contracts_4.09.2026.xlsx",
        "store_contracts_4.9.2026.xlsx",
        "ѕtore_contracts_04.09.2026.xlsx",  # Cyrillic dze instead of Latin s
        "ѕtоre_cоntracts_04.09.2026.xlsx",  # several Cyrillic look-alikes
    ],
)
def test_file_name_variants_resolve(tmp_path: Path, name: str):
    day = date(2026, 9, 4)
    path = _touch(day_folder(tmp_path, day), name)
    assert resolve_files(tmp_path, rules.STORE, day) == [path]


def test_other_sources_and_days_do_not_match(tmp_path: Path):
    day = date(2026, 9, 4)
    _touch(day_folder(tmp_path, day), "selfservice_contracts_04.09.2026.xlsx")
    _touch(day_folder(tmp_path, day), "store_contracts_05.09.2026.xlsx")
    assert resolve_files(tmp_path, rules.STORE, day) == []


def test_two_candidates_without_override_is_an_error(tmp_path: Path):
    day = date(2026, 9, 9)
    _touch(day_folder(tmp_path, day), "store_contracts_09.09.2026.xlsx")
    _touch(day_folder(tmp_path, day), "store_contracts_09.09.2026_reexport.xlsx")
    with pytest.raises(AmbiguousFilesError):
        resolve_files(tmp_path, rules.STORE, day)


def test_override_table_selects_files(tmp_path: Path):
    day = date(2026, 9, 9)
    a = _touch(day_folder(tmp_path, day), "store_contracts_09.09.2026.xlsx")
    b = _touch(day_folder(tmp_path, day), "store_contracts_09.09.2026_reexport.xlsx")
    table = tmp_path / "overrides.csv"
    table.write_text(
        "date,source,files,reason\n"
        "09.09.2026,store_contracts,store_contracts_09.09.2026.xlsx;store_contracts_09.09.2026_reexport.xlsx,partial\n",
        encoding="utf-8",
    )
    overrides = load_overrides(table)
    assert resolve_files(tmp_path, rules.STORE, day, overrides) == [a, b]


def test_override_naming_a_missing_file_fails_loudly(tmp_path: Path):
    day = date(2026, 9, 9)
    _touch(day_folder(tmp_path, day), "store_contracts_09.09.2026.xlsx")
    table = tmp_path / "overrides.csv"
    table.write_text(
        "date,source,files,reason\n09.09.2026,store_contracts,nope.xlsx,x\n", encoding="utf-8"
    )
    with pytest.raises(FileNotFoundError):
        resolve_files(tmp_path, rules.STORE, day, load_overrides(table))


def test_repo_override_table_parses():
    from salesreport.settings import PROJECT_ROOT

    overrides = load_overrides(PROJECT_ROOT / "config" / "overrides.csv")
    entry = overrides[(date(2026, 9, 9), rules.STORE)]
    assert len(entry.files) == 2 and entry.reason


# --- preflight ----------------------------------------------------------------------------
def test_preflight_lists_every_missing_day_and_file(tmp_path: Path):
    start, end = date(2026, 9, 1), date(2026, 9, 4)
    for d in (1, 2, 4):
        day = date(2026, 9, d)
        for source in rules.ALL_SOURCES:
            if not (d == 4 and source == rules.WEB):
                _touch(day_folder(tmp_path, day), f"{source}_{day:%d.%m.%Y}.xlsx")
    report = preflight(tmp_path, start, end)
    assert not report.ok
    assert report.missing_days == [date(2026, 9, 3)]
    assert report.missing_files == [(date(2026, 9, 4), rules.WEB)]
    with pytest.raises(PreflightError) as excinfo:
        require_complete(report)
    assert "03.09.2026" in str(excinfo.value) and "web_orders" in str(excinfo.value)


def test_preflight_passes_on_generated_data(generated):
    from salesreport.inputs.files import load_overrides as lo
    from salesreport.settings import PROJECT_ROOT

    _, data_dir = generated
    report = preflight(
        data_dir, date(2026, 9, 1), date(2026, 9, 17), lo(PROJECT_ROOT / "config" / "overrides.csv")
    )
    assert report.ok, report.problems()


def test_preflight_reports_the_reexport_day_without_override(generated):
    _, data_dir = generated
    report = preflight(data_dir, date(2026, 9, 9), date(2026, 9, 9))
    assert not report.ok and report.ambiguous


# --- forgiving dates ----------------------------------------------------------------------
@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("17.09.2026", date(2026, 9, 17)),
        ("17.09", date(2026, 9, 17)),
        ("17", date(2026, 9, 17)),
        ("7.9.2026", date(2026, 9, 7)),
        ("01.09.2026-17.09.2026", date(2026, 9, 17)),
        ("01.09.2026 - 17.09.2026", date(2026, 9, 17)),
        ("01.09.2026–17.09.2026", date(2026, 9, 17)),
        ("2026-09-17", date(2026, 9, 17)),
        (" 17.09.2026 ", date(2026, 9, 17)),
    ],
)
def test_date_parser_accepts_forgiving_input(text, expected):
    assert parse_report_date(text, REF) == expected


@pytest.mark.parametrize("text", ["", "31.02.2026", "hello", "17/09/2026", "32"])
def test_date_parser_rejects_invalid_input(text):
    with pytest.raises(DateInputError):
        parse_report_date(text, REF)


def test_add_months_clamps_day():
    assert add_months(date(2026, 3, 31), -1) == date(2026, 2, 28)
    assert add_months(date(2026, 1, 15), -1) == date(2025, 12, 15)
