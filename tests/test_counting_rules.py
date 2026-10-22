"""One small hand-built case per v4 counting rule (rule 7 has its own file)."""

from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import pytest
from factory import D, cc, contract, express, master, sources, tariff, web

from salesreport import rules
from salesreport.engine.common import Period
from salesreport.engine.compare import mismatched_blocks, v4_report
from salesreport.engine.v4 import run_v4

MONTH = Period(date(2026, 9, 1), date(2026, 9, 30))


def run(period: Period = MONTH, variant: str = rules.VARIANT_STRICT, **rows):
    return run_v4(sources(**rows), master(), period, variant=variant)


def block(result, block_id: str) -> pd.Series:
    return result.block_rows().set_index("block_id").loc[block_id]


# Rule 1 ----------------------------------------------------------------------------------
def test_rule1_same_number_same_day_same_source_collapses_to_one_renewal():
    result = run(
        store_contracts=[contract(D, "999100"), contract(D, "999100"), contract(D, "999100")],
        express_flow=[express(D, "999100"), express(D, "999100")],
    )
    assert len(result.renewals) == 1
    assert result.collapsed[rules.STORE] == 2
    assert result.collapsed[rules.EXPRESS] == 1
    assert result.events[rules.STORE] == 3


def test_rule1_same_number_on_two_days_is_two_renewals():
    result = run(store_contracts=[contract(D, "999100"), contract(D + timedelta(days=1), "999100")])
    assert len(result.renewals) == 2


# Rule 2 ----------------------------------------------------------------------------------
def test_rule2_only_qualifying_renewal_contracts_count():
    result = run(
        store_contracts=[
            contract(D, "999001", ctype="renewal with device", status="signed"),
            contract(D, "999002", ctype="renewal only", status="active"),
            contract(D, "999003", ctype="renewal only", status="cancelled"),
            contract(D, "999004", ctype="new activation", status="active"),
            contract(D, "999005", ctype="add on", status="active"),
        ]
    )
    assert set(result.renewals["phone"]) == {"999001", "999002"}


def test_rule2_total_is_store_plus_selfservice_and_a_key_in_both_counts_once():
    result = run(
        store_contracts=[contract(D, "999001"), contract(D, "999002")],
        selfservice_contracts=[
            contract(D, "999002", sp="SYS-SELF", agent="agent_092"),
            contract(D, "999003"),
        ],
    )
    row = block(result, "SH01")
    assert result.renewals["renewals"].sum() == 3
    assert row["store"] == 2 and row["selfservice"] == 1
    # the key in both sources stays with the store owner and carries a self-service flag
    shared = result.renewals.set_index("phone").loc["999002"]
    assert shared["contract_source"] == "store" and bool(shared["flag_selfservice"])


# Rule 3 ----------------------------------------------------------------------------------
def test_rule3_digital_sources_only_flag_existing_renewals():
    result = run(
        store_contracts=[contract(D, "999001")],
        express_flow=[express(D, "999001"), express(D, "999777"), express(D, "999778")],
        click_collect=[cc(D, "999779")],
        web_orders=[web(D, "999780")],
    )
    row = block(result, "SH01")
    assert row["renewals"] == 1
    assert row["digital"] == 1
    assert len(result.unmatched) == 4


# Rule 4 ----------------------------------------------------------------------------------
def test_rule4_flags_inherit_the_contract_owner_not_the_journey_agent():
    result = run(
        store_contracts=[contract(D, "999001", agent="agent_001", sp="SP101")],
        express_flow=[express(D, "999001", agent="agent_004", sp="SP103")],
    )
    agents = result.agent_rows().set_index("agent")
    assert agents.loc["agent_001", "digital"] == 1
    assert "agent_004" not in agents.index
    assert "SH03" not in set(result.block_rows()["block_id"])


def test_rule4_agent_in_two_shops_appears_under_both_and_rows_sum_to_shop():
    result = run(
        store_contracts=[
            contract(D, "999001", agent="agent_002", sp="SP101"),
            contract(D, "999002", agent="agent_002", sp="SP102"),
            contract(D, "999003", agent="agent_003", sp="SP102"),
            contract(D, "999004", agent="agent_001", sp="SP101K"),
        ],
        express_flow=[express(D, "999002", agent="agent_001")],
    )
    agents = result.agent_rows()
    assert set(agents.loc[agents["agent"] == "agent_002", "block_id"]) == {"SH01", "SH02"}
    assert mismatched_blocks(v4_report(result)) == 0
    assert block(result, "SH02")["digital"] == 1


# Rule 5 ----------------------------------------------------------------------------------
def test_rule5_digital_is_renewals_with_any_flag_and_cc_only_is_reported():
    result = run(
        store_contracts=[contract(D, "999001"), contract(D, "999002"), contract(D, "999003")],
        express_flow=[express(D, "999001")],
        click_collect=[cc(D, "999001"), cc(D, "999002")],
    )
    row = block(result, "SH01")
    assert row["express"] + row["cc"] == 3  # three flags ...
    assert row["digital"] == 2  # ... on two renewals
    assert row["cc_only"] == 1
    assert row["digital_excl_cc"] == 1
    assert row["digital"] <= row["express"] + row["cc"]


# Rule 6 ----------------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("setup", "expected"),
    [
        ({"tariff_changes": [tariff(D, "999050", "activation")]}, rules.REASON_EXCLUDED),
        ({"tariff_changes": [tariff(D, "999050", "porting")]}, rules.REASON_EXCLUDED),
        (
            {"tariff_changes": [tariff(D, "999050", "add on", "data booster 10gb")]},
            rules.REASON_EXCLUDED,
        ),
        (
            {"tariff_changes": [tariff(D, "999050", "add on", "music pass")]},
            rules.REASON_NO_CONTRACT,
        ),
        ({"store_contracts": [contract(D, "999050", ctype="add on")]}, rules.REASON_NOT_RENEWAL),
        (
            {"store_contracts": [contract(D, "999050", status="cancelled")]},
            rules.REASON_NOT_RENEWAL,
        ),
        ({}, rules.REASON_NO_CONTRACT),
    ],
)
def test_rule6_unmatched_digital_gets_a_reason(setup, expected):
    result = run(express_flow=[express(D, "999050")], **setup)
    assert list(result.unmatched["reason_code"]) == [expected]
    assert result.unmatched["reason"].iloc[0] == rules.REASON_TEXT[expected]


def test_rule6_excluded_population_wins_over_non_renewal_contract():
    result = run(
        store_contracts=[contract(D, "999050", ctype="new activation")],
        tariff_changes=[tariff(D, "999050", "activation")],
        click_collect=[cc(D, "999050")],
    )
    assert list(result.unmatched["reason_code"]) == [rules.REASON_EXCLUDED]


# Rule 8 ----------------------------------------------------------------------------------
def test_rule8_late_booking_changes_an_earlier_day_when_recomputed_from_day_1():
    day5, day7 = date(2026, 9, 5), date(2026, 9, 7)
    rows = {
        "store_contracts": [contract(day5, "999001", file_day=day7)],
        "express_flow": [express(day5, "999001")],
    }
    before = run(Period(date(2026, 9, 1), date(2026, 9, 6)), **rows)
    after = run(Period(date(2026, 9, 1), date(2026, 9, 7)), **rows)
    assert len(before.renewals) == 0
    assert list(before.unmatched["reason_code"]) == [rules.REASON_NO_CONTRACT]
    assert len(after.renewals) == 1 and int(after.renewals["digital"].sum()) == 1
    assert len(after.unmatched) == 0


# Rule 9 ----------------------------------------------------------------------------------
def test_rule9_non_shop_sales_points_group_into_other_channels():
    result = run(
        store_contracts=[
            contract(D, "999001", sp="TS-01", agent="agent_090"),
            contract(D, "999002", sp="PC-02", agent="agent_091"),
            contract(D, "999003", sp="SYS-BATCH", agent="agent_092"),
            contract(D, "999004", sp="EVT-01", agent="agent_093"),
            contract(D, "999005", sp="SP101", agent="agent_001"),
        ]
    )
    blocks = result.block_rows().set_index("block_id")
    assert blocks.loc["CH:telesales", "renewals"] == 1
    assert blocks.loc["CH:partner/consignment", "renewals"] == 1
    assert blocks.loc["CH:background/system", "renewals"] == 1
    assert blocks.loc["CH:other", "renewals"] == 1
    assert blocks.loc["SH01", "renewals"] == 1
    agents = result.agent_rows().set_index("agent")
    assert agents.loc["agent_090", "block_id"] == "CH:telesales"


# Rule 10 ---------------------------------------------------------------------------------
def test_rule10_strict_excludes_web_renewals_without_contract_and_full_adds_them():
    rows = {
        "store_contracts": [contract(D, "999001")],
        "web_orders": [web(D, "999060"), web(D, "999061", order_type="accessory")],
    }
    strict = run(**rows)
    full = run(variant=rules.VARIANT_FULL, **rows)
    assert strict.renewals["renewals"].sum() == 1 and strict.renewals["digital"].sum() == 0
    assert strict.web_without_contract == 1
    assert set(strict.unmatched["phone"]) == {"999060", "999061"}
    assert full.renewals["renewals"].sum() == 2 and full.renewals["digital"].sum() == 1
    added = full.renewals.set_index("phone").loc["999060"]
    assert added["block_id"] == "CH:other" and added["agent"] == rules.WEB_NO_CONTRACT_AGENT
    assert set(full.unmatched["phone"]) == {"999061"}


def test_unknown_variant_is_rejected():
    with pytest.raises(ValueError):
        run(variant="loose")
