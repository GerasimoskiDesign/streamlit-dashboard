"""Rule 7: web order look-ahead, including the window boundary and the period start."""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from factory import contract, master, sources, web

from salesreport import rules
from salesreport.engine.common import Period
from salesreport.engine.v4 import run_v4

SEP = Period(date(2026, 9, 1), date(2026, 9, 30))


def run(period: Period = SEP, lookahead: int = 3, **rows):
    return run_v4(sources(**rows), master(), period, lookahead_days=lookahead)


@pytest.mark.parametrize(("gap", "linked"), [(1, True), (2, True), (3, True), (4, False)])
def test_window_boundary(gap, linked):
    order = date(2026, 9, 10)
    result = run(
        web_orders=[web(order, "999001")],
        store_contracts=[contract(order + timedelta(days=gap), "999001")],
    )
    assert bool(result.renewals["flag_web"].iloc[0]) is linked
    assert len(result.links) == (1 if linked else 0)
    if linked:
        assert result.links["days"].iloc[0] == gap
        assert result.renewals["web_link"].iloc[0] == "lookahead"
    else:
        assert list(result.unmatched["reason_code"]) == [rules.REASON_NO_CONTRACT]


def test_window_is_configurable():
    order = date(2026, 9, 10)
    rows = {
        "web_orders": [web(order, "999001")],
        "store_contracts": [contract(order + timedelta(days=5), "999001")],
    }
    assert len(run(lookahead=5, **rows).links) == 1
    assert len(run(lookahead=3, **rows).links) == 0


def test_same_day_order_is_not_a_lookahead_link():
    day = date(2026, 9, 10)
    result = run(web_orders=[web(day, "999001")], store_contracts=[contract(day, "999001")])
    assert result.renewals["web_link"].iloc[0] == "same_day"
    assert len(result.links) == 0


def test_no_link_when_the_later_day_has_its_own_web_order():
    day = date(2026, 9, 10)
    result = run(
        web_orders=[web(day, "999001"), web(day + timedelta(days=1), "999001")],
        store_contracts=[contract(day + timedelta(days=1), "999001")],
    )
    assert result.renewals["web_link"].iloc[0] == "same_day"
    assert len(result.links) == 0
    assert len(result.unmatched) == 1  # the earlier order is audited


def test_earliest_later_renewal_wins():
    day = date(2026, 9, 10)
    result = run(
        web_orders=[web(day, "999001")],
        store_contracts=[
            contract(day + timedelta(days=1), "999001"),
            contract(day + timedelta(days=2), "999001"),
        ],
    )
    assert list(result.links["days"]) == [1]
    flagged = result.renewals.loc[result.renewals["flag_web"], "date"]
    assert list(flagged) == [result.links["renewal_date"].iloc[0]]


def test_order_before_the_period_links_into_the_period_and_is_tracked():
    result = run(
        web_orders=[web(date(2026, 8, 30), "999001")],
        store_contracts=[contract(date(2026, 9, 1), "999001")],
    )
    assert len(result.links) == 1
    assert bool(result.links["before_period"].iloc[0])
    assert int(result.renewals["digital"].sum()) == 1
    assert len(result.unmatched) == 0  # pre-period orders are never audited in this month


def test_pre_period_order_with_its_own_renewal_does_not_look_ahead():
    result = run(
        web_orders=[web(date(2026, 8, 31), "999001")],
        store_contracts=[
            contract(date(2026, 8, 31), "999001"),
            contract(date(2026, 9, 1), "999001"),
        ],
    )
    assert len(result.links) == 0
    assert int(result.renewals["digital"].sum()) == 0


def test_link_to_renewal_beyond_as_of_is_open_window_not_a_link():
    order = date(2026, 9, 16)
    period = Period(date(2026, 9, 1), date(2026, 9, 17))
    result = run(
        period,
        web_orders=[web(order, "999001")],
        store_contracts=[contract(date(2026, 9, 18), "999001")],
    )
    assert len(result.links) == 0
    assert bool(result.unmatched["window_open"].iloc[0])
