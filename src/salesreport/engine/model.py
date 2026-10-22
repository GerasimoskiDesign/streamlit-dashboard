"""Master data and ownership (LOCKED).

Rule 4 says a renewal belongs to the agent and shop *on the contract*. The contract
carries a sales-point code; this module turns that code into the reporting block it
belongs to - a retail shop, or one of the "other channels" (rule 9) - using the shop
master. Keeping that mapping in one place is what makes numerator and denominator
land on the same owner.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from salesreport import rules
from salesreport.normalize import normalize_code, normalize_login

SHOP = "shop"
CHANNEL = "channel"


@dataclass
class Master:
    """Shops (with their sales-point codes) and agents (with display names)."""

    shops: pd.DataFrame  # shop_id, shop_name, region, sales_points (comma-separated codes)
    agents: pd.DataFrame  # login, name, home_shop, channel
    sp_to_shop: dict[str, str] = field(init=False)
    shop_info: dict[str, tuple[str, str]] = field(init=False)
    names: dict[str, str] = field(init=False)
    home_block: dict[str, str] = field(init=False)

    def __post_init__(self) -> None:
        self.sp_to_shop = {}
        self.shop_info = {}
        for row in self.shops.itertuples(index=False):
            self.shop_info[row.shop_id] = (row.shop_name, row.region)
            for code in str(row.sales_points).split(","):
                if code.strip():
                    self.sp_to_shop[normalize_code(code)] = row.shop_id
        self.names = {}
        self.home_block = {}
        for row in self.agents.itertuples(index=False):
            login = normalize_login(row.login)
            name = row.name if isinstance(row.name, str) and row.name.strip() else ""
            self.names[login] = name.strip()
            home = row.home_shop if isinstance(row.home_shop, str) and row.home_shop.strip() else ""
            channel = str(row.channel).strip() if isinstance(row.channel, str) else ""
            self.home_block[login] = home.strip() or channel_block_id(
                channel or rules.CHANNEL_OTHER
            )


def channel_for_sales_point(code: str) -> str:
    """Channel for a sales point that is not a shop; unknown prefixes go to "other"."""
    prefix = code.split("-", 1)[0] if "-" in code else code[:3]
    return rules.CHANNEL_PREFIXES.get(prefix, rules.CHANNEL_OTHER)


def channel_block_id(channel: str) -> str:
    """Block id used for an "other channels" group."""
    return f"CH:{channel}"


def block_label(block_id: str, master: Master) -> tuple[str, str, str | None, str]:
    """Return (block_type, block_name, region, channel_group) for a block id."""
    if block_id.startswith("CH:"):
        channel = block_id[3:]
        return CHANNEL, rules.CHANNEL_LABELS.get(channel, channel), None, channel
    name, region = master.shop_info.get(block_id, (block_id, None))
    return SHOP, name, region, SHOP


def owner_frame(sales_points: pd.Series, master: Master) -> pd.DataFrame:
    """Map sales-point codes to their reporting block.

    Returns columns block_id, block_type, block_name, region, channel_group.
    """
    block_ids = [
        master.sp_to_shop.get(code) or channel_block_id(channel_for_sales_point(code))
        for code in sales_points
    ]
    labels = [block_label(b, master) for b in block_ids]
    return pd.DataFrame(
        {
            "block_id": block_ids,
            "block_type": [x[0] for x in labels],
            "block_name": [x[1] for x in labels],
            "region": [x[2] for x in labels],
            "channel_group": [x[3] for x in labels],
        },
        index=sales_points.index,
    )


def display_names(logins: pd.Series, master: Master) -> pd.Series:
    """Display name per agent login, or the explicit "(no display name)" marker."""
    return pd.Series(
        [master.names.get(login) or rules.NO_DISPLAY_NAME for login in logins],
        index=logins.index,
        dtype=object,
    )
