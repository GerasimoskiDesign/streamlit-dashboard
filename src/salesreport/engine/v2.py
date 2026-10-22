"""v2 - per agent.

Shop managers wanted to see who sells what, so every contract is attributed to its
agent and every agent to a shop. The agent's shop comes from the agent master (their
home shop), and the shop row is the sum of its agents. Consistent, but an agent who
also works in a second shop has all their sales booked to the home shop, and digital
still means self-service only.
"""

from __future__ import annotations

import pandas as pd

from salesreport import rules
from salesreport.engine.common import Period, is_qualifying_contract
from salesreport.engine.model import Master, block_label
from salesreport.engine.versions import VersionReport, duplicates, visible_in_period


def count_by_agent(frame: pd.DataFrame, master: Master, column: str) -> pd.DataFrame:
    """Count rows per agent, placing each agent in their master-data home block."""
    if not len(frame):
        return pd.DataFrame(columns=["block_id", "agent", column])
    agents = frame["agent"].reset_index(drop=True)
    homes = agents.map(lambda a: master.home_block.get(a, "CH:other"))
    return (
        pd.DataFrame({"block_id": homes, "agent": agents})
        .groupby(["block_id", "agent"])
        .size()
        .rename(column)
        .reset_index()
    )


def merge_agents(*frames: pd.DataFrame) -> pd.DataFrame:
    """Outer-join agent counts, filling gaps with zero."""
    out = frames[0]
    for frame in frames[1:]:
        out = out.merge(frame, on=["block_id", "agent"], how="outer")
    for column in out.columns:
        if column not in ("block_id", "agent"):
            out[column] = out[column].fillna(0).astype(int)
    return out.sort_values(["block_id", "agent"]).reset_index(drop=True)


def blocks_from_agents(agents: pd.DataFrame, master: Master) -> pd.DataFrame:
    """Block rows as the sum of their agent rows (v2's definition of a shop total)."""
    sums = agents.groupby("block_id")[["total", "digital"]].sum().reset_index()
    labels = [block_label(b, master) for b in sums["block_id"]]
    sums.insert(1, "block_type", [x[0] for x in labels])
    sums.insert(2, "block_name", [x[1] for x in labels])
    sums.insert(3, "region", [x[2] for x in labels])
    return sums


def run_v2(sources: dict[str, pd.DataFrame], master: Master, period: Period) -> VersionReport:
    """Count renewals and self-service contracts per agent; shops are agent sums."""
    data = visible_in_period(sources, period)
    store = data[rules.STORE].loc[lambda f: is_qualifying_contract(f)]
    selfservice = data[rules.SELFSERVICE].loc[lambda f: is_qualifying_contract(f)]
    contracts = pd.concat([store, selfservice], ignore_index=True)
    agents = merge_agents(
        count_by_agent(contracts, master, "total"),
        count_by_agent(selfservice, master, "digital"),
    )
    return VersionReport(
        version="v2",
        title="Per agent",
        digital_sources="self-service",
        blocks=blocks_from_agents(agents, master),
        agents=agents,
        double_counted=duplicates(contracts),
    )
