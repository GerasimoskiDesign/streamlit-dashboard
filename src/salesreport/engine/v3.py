"""v3 - the prototype at scale (kept on purpose, not used for publishing).

This is what happens when a working prototype meets messy multi-source data. To cover
every digital channel, each digital source is counted on its own and the counts are
added up - per agent using the agent field of that source, per shop using the shop
field of that source:

* a renewal that shows up in express *and* click & collect is counted twice;
* an express journey that never became a renewal still counts as digital;
* click & collect and web orders have no agent, so they reach shop rows but not agent
  rows - and the agent rows no longer add up to the shop;
* the express "agent" is whoever started the journey, not who signed the contract.

The result: digital share above 100 % for some agents and shops. The README and the
dashboard use this version to show exactly those symptoms next to v4.
"""

from __future__ import annotations

import pandas as pd

from salesreport import rules
from salesreport.engine.common import Period, is_qualifying_contract
from salesreport.engine.model import Master
from salesreport.engine.v1 import count_by_block, merge_blocks
from salesreport.engine.v2 import count_by_agent, merge_agents
from salesreport.engine.versions import VersionReport, duplicates, visible_in_period


def run_v3(sources: dict[str, pd.DataFrame], master: Master, period: Period) -> VersionReport:
    """Count every digital source independently and add the counts up."""
    data = visible_in_period(sources, period)
    store = data[rules.STORE].loc[lambda f: is_qualifying_contract(f)]
    selfservice = data[rules.SELFSERVICE].loc[lambda f: is_qualifying_contract(f)]
    express = data[rules.EXPRESS]
    click_collect = data[rules.CLICK_COLLECT]
    web = data[rules.WEB]
    contracts = pd.concat([store, selfservice], ignore_index=True)

    agents = merge_agents(
        count_by_agent(contracts, master, "total"),
        count_by_agent(selfservice, master, "ss"),
        count_by_agent(express, master, "express"),
    )
    agents["digital"] = agents.pop("ss") + agents.pop("express")

    blocks = merge_blocks(
        count_by_block(contracts, master, "total"),
        count_by_block(selfservice, master, "ss"),
        count_by_block(express, master, "express"),
        count_by_block(click_collect, master, "cc"),
        count_by_block(web, master, "web"),
    )
    blocks["digital"] = (
        blocks.pop("ss") + blocks.pop("express") + blocks.pop("cc") + blocks.pop("web")
    )

    digital_rows = pd.concat([selfservice, express, click_collect, web], ignore_index=True)
    return VersionReport(
        version="v3",
        title="Prototype at scale",
        digital_sources=(
            "self-service + express + click & collect + web, counted per source and added"
        ),
        blocks=blocks,
        agents=agents,
        double_counted=duplicates(contracts) + duplicates(digital_rows),
    )
