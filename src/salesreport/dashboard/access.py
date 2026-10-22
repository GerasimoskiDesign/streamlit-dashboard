"""Role-based data access - the single place where permissions are enforced.

Every page asks :func:`allowed_rows` for its data. Hiding a widget is not security: if
a page forgot to hide something, the rows would still be there. Filtering the *data*
before any page sees it means a page simply cannot show what the user may not see,
and the Excel export of "the current view" inherits the same restriction for free.

Permission matrix (also in the README; every cell is covered by tests):

=============================================  ========  ============  ========
Resource                                       Regional  Shop manager  Employee
=============================================  ========  ============  ========
Own shop - shop totals                         yes       yes           yes
Own shop - agent detail                        yes       yes           yes
Other shops, own region - shop totals          yes       yes           no
Other shops, own region - agent detail         yes       yes           no
Other regions - shop totals (leaderboard)      yes       yes           no
Other regions - agent detail                   yes       no            no
Other channels (telesales, partner, ...)       yes       no            no
Data quality (controls, unmatched audit)       yes       no            no
How it evolved (aggregated, anonymous)         yes       yes           yes
=============================================  ========  ============  ========
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

import pandas as pd

from salesreport.engine.common import COUNT_COLUMNS


class Role(StrEnum):
    REGIONAL_MANAGER = "regional_manager"
    SHOP_MANAGER = "shop_manager"
    EMPLOYEE = "employee"


ROLE_LABELS = {
    Role.REGIONAL_MANAGER: "Regional Manager",
    Role.SHOP_MANAGER: "Shop Manager",
    Role.EMPLOYEE: "Employee",
}


@dataclass(frozen=True)
class User:
    """An authenticated dashboard user."""

    username: str
    display_name: str
    role: Role
    region: str | None = None
    shop_id: str | None = None


SALES = "sales"
DATA_QUALITY = "data_quality"
EVOLUTION = "evolution"
DATASETS = (SALES, DATA_QUALITY, EVOLUTION)

AGENT = "agent"
SHOP_TOTAL = "shop_total"

RESOURCES = (
    "own_shop_totals",
    "own_shop_agents",
    "region_shop_totals",
    "region_agents",
    "other_region_shop_totals",
    "other_region_agents",
    "other_channels",
    "data_quality",
    "evolution",
)

PERMISSION_MATRIX: dict[str, dict[Role, bool]] = {
    "own_shop_totals": {Role.REGIONAL_MANAGER: True, Role.SHOP_MANAGER: True, Role.EMPLOYEE: True},
    "own_shop_agents": {Role.REGIONAL_MANAGER: True, Role.SHOP_MANAGER: True, Role.EMPLOYEE: True},
    "region_shop_totals": {
        Role.REGIONAL_MANAGER: True,
        Role.SHOP_MANAGER: True,
        Role.EMPLOYEE: False,
    },
    "region_agents": {Role.REGIONAL_MANAGER: True, Role.SHOP_MANAGER: True, Role.EMPLOYEE: False},
    "other_region_shop_totals": {
        Role.REGIONAL_MANAGER: True,
        Role.SHOP_MANAGER: True,
        Role.EMPLOYEE: False,
    },
    "other_region_agents": {
        Role.REGIONAL_MANAGER: True,
        Role.SHOP_MANAGER: False,
        Role.EMPLOYEE: False,
    },
    "other_channels": {Role.REGIONAL_MANAGER: True, Role.SHOP_MANAGER: False, Role.EMPLOYEE: False},
    "data_quality": {Role.REGIONAL_MANAGER: True, Role.SHOP_MANAGER: False, Role.EMPLOYEE: False},
    "evolution": {Role.REGIONAL_MANAGER: True, Role.SHOP_MANAGER: True, Role.EMPLOYEE: True},
}


def _shop_totals(frame: pd.DataFrame) -> pd.DataFrame:
    """Collapse agent rows into one row per shop and day, without agent identity."""
    keys = [
        c
        for c in (
            "month",
            "date",
            "block_id",
            "block_type",
            "block_name",
            "region",
            "channel_group",
        )
        if c in frame
    ]
    if not len(frame):
        out = frame.drop(columns=["agent", "agent_name"], errors="ignore").copy()
    else:
        counts = [c for c in COUNT_COLUMNS if c in frame]
        out = frame.groupby(keys, dropna=False)[counts].sum().reset_index()
    out["agent"] = None
    out["agent_name"] = None
    out["detail"] = SHOP_TOTAL
    return out


def allowed_rows(user: User, frame: pd.DataFrame, dataset: str = SALES) -> pd.DataFrame:
    """Return only the rows (and the level of detail) ``user`` may see.

    Args:
        user: the logged-in user.
        frame: the full dataset as written by the engine.
        dataset: ``sales`` (daily per-agent counts), ``data_quality`` (control totals,
            unmatched audit) or ``evolution`` (aggregated version comparison).
    """
    if dataset not in DATASETS:
        raise ValueError(f"unknown dataset {dataset!r}")
    if dataset == EVOLUTION:
        return frame.copy()  # aggregated and anonymous by construction
    if dataset == DATA_QUALITY:
        return frame.copy() if user.role is Role.REGIONAL_MANAGER else frame.iloc[0:0].copy()

    if user.role is Role.REGIONAL_MANAGER:
        return frame.assign(detail=AGENT)
    is_shop = frame["block_type"] == "shop"
    if user.role is Role.SHOP_MANAGER:
        own = frame.loc[is_shop & (frame["region"] == user.region)].assign(detail=AGENT)
        others = _shop_totals(frame.loc[is_shop & (frame["region"] != user.region)])
        return pd.concat([own, others], ignore_index=True)
    if user.role is Role.EMPLOYEE:
        return frame.loc[is_shop & (frame["block_id"] == user.shop_id)].assign(detail=AGENT)
    return frame.iloc[0:0].assign(detail=AGENT)


def can_view(user: User, dataset: str) -> bool:
    """Whether a page backed by ``dataset`` should be offered at all (navigation only)."""
    if dataset == DATA_QUALITY:
        return user.role is Role.REGIONAL_MANAGER
    return True
