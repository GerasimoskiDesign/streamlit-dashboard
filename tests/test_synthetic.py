"""End-to-end checks on the full synthetic dataset against the generator's ground truth."""

from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from salesreport import rules
from salesreport.engine.common import Period
from salesreport.engine.compare import all_versions, evolution_table, mismatched_blocks, v4_report
from salesreport.engine.v3 import run_v3
from salesreport.engine.v4 import run_v4

SEPTEMBER = Period(date(2026, 9, 1), date(2026, 9, 30))
CAMPAIGN = Period(date(2026, 9, 7), date(2026, 9, 13))


@pytest.fixture(scope="module")
def september(loaded):
    sources, master = loaded
    return run_v4(sources, master, SEPTEMBER)


def _keys(frame: pd.DataFrame) -> pd.Series:
    return pd.to_datetime(frame["date"]).dt.strftime("%Y-%m-%d") + "|" + frame["phone"]


def test_engine_reproduces_the_ground_truth_for_a_full_month(generated, september):
    result, _ = generated
    truth = result.truth.copy()
    truth = truth[(truth["date"] >= SEPTEMBER.start) & (truth["date"] <= SEPTEMBER.end)]
    truth.index = _keys(truth)
    engine = september.renewals.set_index("key")
    assert set(truth.index) == set(engine.index)
    joined = truth.join(engine, rsuffix="_engine")
    for flag in (
        "flag_selfservice",
        "flag_express",
        "flag_cc",
        "flag_web",
        "web_link",
        "contract_source",
        "agent",
    ):
        assert (joined[flag] == joined[f"{flag}_engine"]).all(), flag


def test_audit_reasons_match_what_the_generator_injected(generated, september):
    result, _ = generated
    expected = result.expected_audit.copy()
    expected = expected[(expected["date"] >= SEPTEMBER.start) & (expected["date"] <= SEPTEMBER.end)]
    expected.index = _keys(expected) + "|" + expected["source"]
    audit = september.unmatched.copy()
    audit.index = _keys(audit) + "|" + audit["source"]
    assert set(expected.index) == set(audit.index)
    assert (expected["reason_code"] == audit.loc[expected.index, "reason_code"]).all()


def test_digital_never_exceeds_total_at_any_level(september):
    renewals = september.renewals
    assert (renewals["digital"] <= renewals["renewals"]).all()
    for frame in (september.block_rows(), september.agent_rows()):
        assert (frame["digital"] <= frame["renewals"]).all()
        assert (frame["cc_only"] + frame["digital_excl_cc"] == frame["digital"]).all()
    daily = renewals.groupby(["date", "block_id"])[["digital", "renewals"]].sum()
    assert (daily["digital"] <= daily["renewals"]).all()


def test_agent_rows_sum_to_shop_rows_exactly(september):
    blocks = september.block_rows().set_index("block_id")
    sums = (
        september.agent_rows()
        .groupby("block_id")[
            list(
                blocks.columns.intersection(
                    [
                        "store",
                        "selfservice",
                        "renewals",
                        "ss_digital",
                        "express",
                        "cc",
                        "web",
                        "digital",
                        "cc_only",
                    ]
                )
            )
        ]
        .sum()
    )
    pd.testing.assert_frame_equal(
        blocks[sums.columns].sort_index(), sums.sort_index(), check_dtype=False
    )
    assert mismatched_blocks(v4_report(september)) == 0


def test_no_duplicate_renewal_keys(september):
    assert september.renewals["key"].is_unique


def test_regression_v3_breaks_invariants_on_campaign_week_and_v4_does_not(loaded):
    sources, master = loaded
    v3 = run_v3(sources, master, CAMPAIGN)
    v4 = run_v4(sources, master, CAMPAIGN)
    table = evolution_table(all_versions(sources, master, CAMPAIGN, v4)).set_index("version")
    assert table.loc["v3", "agents_over_100"] > 0
    assert table.loc["v3", "shops_over_100"] > 0
    assert table.loc["v3", "mismatched_blocks"] > 0
    assert table.loc["v3", "double_counted"] > 0
    assert (v3.agents["digital"] > v3.agents["total"]).any()
    for metric in ("agents_over_100", "shops_over_100", "mismatched_blocks", "double_counted"):
        assert table.loc["v4", metric] == 0, metric


def test_all_files_including_messy_names_were_read(generated, loaded):
    result, _ = generated
    sources, _ = loaded
    cfg = result.config
    for day, source, _ in (*cfg.cyrillic_names, *cfg.unpadded_names):
        assert (sources[source]["file_date"] == pd.Timestamp(day)).any(), (day, source)
    reexport = sources[rules.STORE].loc[
        sources[rules.STORE]["file_date"] == pd.Timestamp(cfg.reexport_day)
    ]
    assert reexport["source_file"].nunique() == 2


def test_generator_is_deterministic(tmp_path):
    from salesreport.generator import GeneratorConfig, generate

    cfg = GeneratorConfig(start=date(2026, 9, 1), end=date(2026, 9, 5))
    a = generate(cfg, tmp_path / "a")
    b = generate(cfg, tmp_path / "b")
    pd.testing.assert_frame_equal(a.truth, b.truth)
    assert all(p.startswith("999") for p in a.truth["phone"])
    file_a = (
        tmp_path / "a" / "daily" / "September" / "03.09.2026" / "web_orders_03.09.2026.xlsx"
    ).read_bytes()
    assert len(file_a) > 0


def test_build_outputs(built):
    controls = built.controls.set_index("metric")
    for metric in (
        "Agents above 100 % digital share",
        "Shops above 100 % digital share",
        "Blocks where agent rows != block row",
        "Duplicate renewal keys",
    ):
        assert controls.loc[metric, "value"] == 0
        assert controls.loc[metric, "status"] == "OK"
    assert controls.loc["Agents without a display name", "value"] == 2
    assert built.v4.period.start == date(2026, 9, 1)  # rule 8: always from day 1
    assert set(built.history) == {"2026-07", "2026-08", "2026-09"}
    links = built.v4.links
    assert len(links) > 0 and links["before_period"].any()


def test_reconciliation_matches_except_the_injected_manual_slips(generated, built):
    result, _ = generated
    recon = built.reconciliation.set_index("agent")
    differences = recon.loc[recon["status"] == "difference", "difference"].to_dict()
    # engine - manual: the manual count was +1 for one agent and -1 for another
    assert differences == {agent: -delta for agent, delta in result.manual_differences.items()}
    assert (recon["status"] == "match").sum() > 150
