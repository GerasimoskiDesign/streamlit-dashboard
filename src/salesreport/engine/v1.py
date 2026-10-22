"""v1 - shop totals.

The first version answered one question quickly: how many renewals and how many
self-service (digital) contracts did each shop book this month? It counts contract
rows per sales point. There is no agent view, only one digital source, and duplicate
export rows are counted as they come.
"""

from __future__ import annotations

import pandas as pd

from salesreport import rules
from salesreport.engine.common import Period, is_qualifying_contract
from salesreport.engine.model import Master, owner_frame
from salesreport.engine.versions import VersionReport, duplicates, visible_in_period


def count_by_block(frame: pd.DataFrame, master: Master, column: str) -> pd.DataFrame:
    """Count rows per reporting block of their own sales point."""
    if not len(frame):
        return pd.DataFrame(columns=["block_id", "block_type", "block_name", "region", column])
    owners = owner_frame(frame["sales_point"].reset_index(drop=True), master)
    return (
        owners.groupby(["block_id", "block_type", "block_name", "region"], dropna=False)
        .size()
        .rename(column)
        .reset_index()
    )


def merge_blocks(*frames: pd.DataFrame) -> pd.DataFrame:
    """Outer-join block counts and fill missing counts with zero."""
    keys = ["block_id", "block_type", "block_name", "region"]
    out = frames[0]
    for frame in frames[1:]:
        out = out.merge(frame, on=keys, how="outer")
    for column in out.columns:
        if column not in keys:
            out[column] = out[column].fillna(0).astype(int)
    return out.sort_values("block_id").reset_index(drop=True)


def run_v1(sources: dict[str, pd.DataFrame], master: Master, period: Period) -> VersionReport:
    """Count renewal contracts and self-service contracts per shop."""
    data = visible_in_period(sources, period)
    store = data[rules.STORE].loc[lambda f: is_qualifying_contract(f)]
    selfservice = data[rules.SELFSERVICE].loc[lambda f: is_qualifying_contract(f)]
    contracts = pd.concat([store, selfservice], ignore_index=True)
    blocks = merge_blocks(
        count_by_block(contracts, master, "total"),
        count_by_block(selfservice, master, "digital"),
    )
    return VersionReport(
        version="v1",
        title="Shop totals",
        digital_sources="self-service",
        blocks=blocks,
        agents=None,
        double_counted=duplicates(contracts),
    )
