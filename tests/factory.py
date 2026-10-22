"""Builders for small, hand-made engine inputs (already in the loader's typed form)."""

from __future__ import annotations

from datetime import date

import pandas as pd

from salesreport import rules
from salesreport.engine.model import Master
from salesreport.inputs.loader import SOURCE_SPECS, empty_source

D = date(2026, 9, 10)


def master() -> Master:
    shops = pd.DataFrame(
        [
            {
                "shop_id": "SH01",
                "shop_name": "Alpha",
                "region": "North",
                "sales_points": "SP101, SP101K",
            },
            {"shop_id": "SH02", "shop_name": "Beta", "region": "North", "sales_points": "SP102"},
            {"shop_id": "SH03", "shop_name": "Gamma", "region": "South", "sales_points": "SP103"},
        ]
    )
    agents = pd.DataFrame(
        [
            {"login": "agent_001", "name": "Ana Novak", "home_shop": "SH01", "channel": "shop"},
            {"login": "agent_002", "name": "Boris Berg", "home_shop": "SH01", "channel": "shop"},
            {"login": "agent_003", "name": "", "home_shop": "SH02", "channel": "shop"},
            {"login": "agent_004", "name": "Clara Costa", "home_shop": "SH03", "channel": "shop"},
            {"login": "agent_090", "name": "Tele One", "home_shop": "", "channel": "telesales"},
            {
                "login": "agent_091",
                "name": "Partner One",
                "home_shop": "",
                "channel": "partner/consignment",
            },
            {
                "login": "agent_092",
                "name": "System",
                "home_shop": "",
                "channel": "background/system",
            },
            {"login": "agent_093", "name": "Events", "home_shop": "", "channel": "other"},
        ]
    )
    return Master(shops=shops, agents=agents)


def _row(day: date, phone: str, file_day: date | None, **fields) -> dict:
    return {
        "date": pd.Timestamp(day),
        "phone": phone,
        "file_date": pd.Timestamp(file_day or day),
        "source_file": "hand-made.xlsx",
        "row_no": 0,
        **fields,
    }


def contract(
    day: date,
    phone: str,
    *,
    sp: str = "SP101",
    agent: str = "agent_001",
    ctype: str = "renewal only",
    status: str = "active",
    file_day: date | None = None,
    record_id: str = "C1",
) -> dict:
    return _row(
        day,
        phone,
        file_day,
        contract_type=ctype,
        status=status,
        sales_point=sp,
        agent=agent,
        record_id=record_id,
    )


def express(day: date, phone: str, *, agent: str = "agent_001", sp: str = "SP101") -> dict:
    return _row(day, phone, None, agent=agent, sales_point=sp, record_id="X1")


def cc(day: date, phone: str, *, sp: str = "SP101") -> dict:
    return _row(day, phone, None, sales_point=sp, record_id="CC1")


def web(day: date, phone: str, *, order_type: str = "renewal", sp: str = "") -> dict:
    return _row(day, phone, None, order_type=order_type, sales_point=sp, record_id="W1")


def tariff(day: date, phone: str, change_type: str, product: str = "") -> dict:
    return _row(day, phone, None, change_type=change_type, product=product)


def sources(**rows: list[dict]) -> dict[str, pd.DataFrame]:
    """``sources(store_contracts=[...], express_flow=[...])`` -> engine input dict."""
    out = {}
    for name in rules.ALL_SOURCES:
        data = rows.get(name, [])
        if data:
            frame = pd.DataFrame(data)
            frame["row_no"] = range(1, len(frame) + 1)
            columns = list(empty_source(name).columns)
            for column in SOURCE_SPECS[name].values():
                if column not in frame:
                    frame[column] = ""
            out[name] = frame[columns]
        else:
            out[name] = empty_source(name)
    return out
