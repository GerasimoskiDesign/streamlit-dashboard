"""v4 - event-level engine (production logic, LOCKED).

The engine works on *events*, not on per-source counts:

1. one renewal = one (date, phone) key, duplicates collapsed per source (rule 1);
2. only qualifying store / self-service contracts create renewals (rule 2);
3. digital sources only *flag* an existing renewal, so digital <= total (rule 3);
4. the renewal's owner comes from its contract and flags inherit it, so agent rows
   always add up to their shop (rule 4);
5. a renewal is digital if it has at least one flag (rule 5);
6. every digital transaction without a renewal goes to an audit table with a reason
   (rule 6);
7. web orders may link to a renewal booked up to N days later (rule 7);
8. callers always pass a period that starts on day 1 of the month (rule 8);
9. non-shop sales points are grouped into other channels (rule 9);
10. ``variant`` chooses strict or full treatment of web renewals without a contract
    (rule 10).

See docs/COUNTING_RULES.md for the reason behind each rule.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta

import numpy as np
import pandas as pd

from salesreport import rules
from salesreport.engine.common import (
    COUNT_COLUMNS,
    Period,
    between,
    collapse,
    is_qualifying_contract,
    shifted_keys,
    ts,
    with_key,
)
from salesreport.engine.model import Master, display_names, owner_frame

AUDIT_COLUMNS = ("date", "phone", "source", "reason_code", "reason", "window_open", "record_id")
LINK_COLUMNS = ("order_date", "phone", "renewal_date", "days", "before_period", "order_id")


@dataclass
class V4Result:
    """Everything the report, the dashboard and the checks need from one run."""

    period: Period
    variant: str
    lookahead_days: int
    renewals: pd.DataFrame
    unmatched: pd.DataFrame
    links: pd.DataFrame
    events: dict[str, int]
    collapsed: dict[str, int]
    web_without_contract: int
    master: Master
    _blocks: pd.DataFrame | None = field(default=None, repr=False)
    _agents: pd.DataFrame | None = field(default=None, repr=False)

    def block_rows(self) -> pd.DataFrame:
        """One row per shop / channel block, computed directly from the events."""
        if self._blocks is None:
            self._blocks = aggregate(self.renewals, ["block_id"])
        return self._blocks

    def agent_rows(self) -> pd.DataFrame:
        """One row per (block, agent) - an agent in two shops appears in both."""
        if self._agents is None:
            self._agents = aggregate(self.renewals, ["block_id", "agent"])
        return self._agents


def _flag_frame(renewals: pd.DataFrame) -> pd.DataFrame:
    out = renewals
    out["store"] = out["contract_source"] == "store"
    out["selfservice"] = out["contract_source"] == "selfservice"
    out["web_nocontract"] = out["contract_source"] == "web"
    out["renewals"] = True
    out["ss_digital"] = out["flag_selfservice"]
    out["express"] = out["flag_express"]
    out["cc"] = out["flag_cc"]
    out["web"] = out["flag_web"]
    out["digital"] = out["ss_digital"] | out["express"] | out["cc"] | out["web"]
    out["cc_only"] = out["cc"] & ~(out["ss_digital"] | out["express"] | out["web"])
    out["digital_excl_cc"] = out["digital"] & ~out["cc_only"]
    return out


def aggregate(renewals: pd.DataFrame, by: list[str]) -> pd.DataFrame:
    """Sum the per-renewal booleans into counts for the given grouping."""
    attrs = ["block_type", "block_name", "region", "channel_group"]
    if "agent" in by:
        attrs.append("agent_name")
    if not len(renewals):
        return pd.DataFrame(columns=[*by, *attrs, "sales_points", *COUNT_COLUMNS])
    grouped = renewals.groupby(by, sort=True, dropna=False)
    counts = grouped[list(COUNT_COLUMNS)].sum().astype(int)
    first = grouped[attrs].first()
    points = grouped["sales_point"].agg(lambda s: ", ".join(sorted({p for p in s if p})))
    out = pd.concat([first, points.rename("sales_points"), counts], axis=1).reset_index()
    return out


def _owners(frame: pd.DataFrame, master: Master) -> pd.DataFrame:
    owners = owner_frame(frame["sales_point"], master)
    out = pd.concat([frame, owners], axis=1)
    out["agent_name"] = display_names(out["agent"], master)
    return out


def run_v4(
    sources: dict[str, pd.DataFrame],
    master: Master,
    period: Period,
    lookahead_days: int = rules.LOOKAHEAD_DAYS_DEFAULT,
    variant: str = rules.VARIANT_STRICT,
) -> V4Result:
    """Run the production counting rules for ``period``."""
    if variant not in rules.VARIANTS:
        raise ValueError(f"variant must be one of {rules.VARIANTS}")
    start, end, as_of = ts(period.start), ts(period.end), ts(period.as_of)
    context_start = start - pd.Timedelta(days=lookahead_days)

    visible = {
        name: with_key(frame.loc[frame["file_date"] <= as_of]) for name, frame in sources.items()
    }

    events: dict[str, int] = {}
    collapsed: dict[str, int] = {}
    in_period: dict[str, pd.DataFrame] = {}
    for name in rules.ALL_SOURCES:
        rows = between(visible[name], start, end)
        events[name] = len(rows)
        if name in rules.CONTRACT_SOURCES:
            rows = rows.loc[is_qualifying_contract(rows)]
        kept, dropped = collapse(rows)
        collapsed[name] = dropped
        in_period[name] = kept

    # Rule 2: the denominator. Store contracts take precedence for ownership; a key
    # that also exists in self-service is one renewal with a self-service flag.
    store = in_period[rules.STORE].assign(contract_source="store")
    selfservice_only = (
        in_period[rules.SELFSERVICE]
        .loc[lambda f: ~f["key"].isin(set(store["key"]))]
        .assign(contract_source="selfservice")
    )
    renewals = pd.concat([store, selfservice_only], ignore_index=True)
    renewal_keys = set(renewals["key"])

    # Renewals in the look-back days are needed only to decide whether an early web
    # order already had its own renewal (then it must not look ahead into this period).
    context_contracts = pd.concat(
        [
            between(visible[s], context_start, end).loc[lambda f: is_qualifying_contract(f)]
            for s in rules.CONTRACT_SOURCES
        ]
    )
    context_keys = set(context_contracts["key"])

    # Rule 3: digital sources flag existing renewals only.
    all_ss_keys = set(between(visible[rules.SELFSERVICE], start, end)["key"])
    renewals["flag_selfservice"] = renewals["key"].isin(all_ss_keys)
    renewals["flag_express"] = renewals["key"].isin(set(in_period[rules.EXPRESS]["key"]))
    renewals["flag_cc"] = renewals["key"].isin(set(in_period[rules.CLICK_COLLECT]["key"]))

    # Rule 7: web orders - same day, else look ahead up to N days.
    web_context, _ = collapse(between(visible[rules.WEB], context_start, end))
    web_keys = set(web_context["key"])
    same_day = web_context["key"].isin(renewal_keys)
    candidates = web_context.loc[~web_context["key"].isin(context_keys)]
    target = pd.Series(index=candidates.index, dtype=object)
    gap = pd.Series(0, index=candidates.index, dtype=int)
    for days in range(1, lookahead_days + 1):
        later = shifted_keys(candidates, days)
        ok = target.isna() & later.isin(context_keys) & ~later.isin(web_keys)
        target[ok] = later[ok]
        gap[ok] = days
    linked = target.notna() & target.isin(renewal_keys)
    links = pd.DataFrame(
        {
            "order_date": candidates.loc[linked, "date"],
            "phone": candidates.loc[linked, "phone"],
            "renewal_date": candidates.loc[linked, "date"] + pd.to_timedelta(gap[linked], unit="D"),
            "days": gap[linked],
            "before_period": candidates.loc[linked, "date"] < start,
            "order_id": candidates.loc[linked, "record_id"],
        }
    ).reset_index(drop=True)
    lookahead_keys = set(target[linked])
    same_day_keys = set(web_context.loc[same_day, "key"])
    renewals["flag_web"] = renewals["key"].isin(same_day_keys | lookahead_keys)
    renewals["web_link"] = np.where(
        renewals["key"].isin(same_day_keys),
        "same_day",
        np.where(renewals["key"].isin(lookahead_keys), "lookahead", ""),
    )

    # Rule 6: audit every digital transaction that found no renewal.
    tariff = between(visible[rules.TARIFF], start, end)
    excluded = tariff["change_type"].isin(rules.EXCLUDED_CHANGE_TYPES) | (
        (tariff["change_type"] == rules.ADDON_CHANGE_TYPE)
        & tariff["product"].isin(rules.EXCLUDED_ADDON_PRODUCTS)
    )
    excluded_keys = set(tariff.loc[excluded, "key"])
    any_contract_keys = set(between(visible[rules.STORE], start, end)["key"]) | all_ss_keys

    selfservice_rows, _ = collapse(between(visible[rules.SELFSERVICE], start, end))
    web_period = web_context.loc[web_context["date"] >= start]
    web_linked_index = set(candidates.index[linked])
    audit_parts = [
        selfservice_rows.loc[~selfservice_rows["key"].isin(renewal_keys)].assign(
            source=rules.SELFSERVICE
        ),
        in_period[rules.EXPRESS]
        .loc[lambda f: ~f["key"].isin(renewal_keys)]
        .assign(source=rules.EXPRESS),
        in_period[rules.CLICK_COLLECT]
        .loc[lambda f: ~f["key"].isin(renewal_keys)]
        .assign(source=rules.CLICK_COLLECT),
        web_period.loc[
            ~web_period["key"].isin(renewal_keys) & ~web_period.index.isin(web_linked_index)
        ].assign(source=rules.WEB),
    ]
    audit_parts = [p for p in audit_parts if len(p)]
    if audit_parts:
        audit = pd.concat(audit_parts, ignore_index=True)
    else:
        audit = pd.DataFrame(columns=["date", "phone", "key", "source", "record_id", "order_type"])
    if "order_type" not in audit:
        audit["order_type"] = ""
    if len(audit):
        audit["reason_code"] = np.select(
            [audit["key"].isin(excluded_keys), audit["key"].isin(any_contract_keys)],
            [rules.REASON_EXCLUDED, rules.REASON_NOT_RENEWAL],
            default=rules.REASON_NO_CONTRACT,
        )
        audit["window_open"] = (
            (audit["source"] == rules.WEB)
            & (audit["reason_code"] == rules.REASON_NO_CONTRACT)
            & (audit["date"] + pd.Timedelta(days=lookahead_days) > as_of)
        )
    else:
        audit = audit.assign(reason_code=pd.Series(dtype=object), window_open=pd.Series(dtype=bool))

    # Rule 10: in the full variant, web renewals without any contract record are
    # added on both sides (numerator and denominator), under "other channels".
    web_no_contract = (
        (audit["source"] == rules.WEB)
        & (audit["reason_code"] == rules.REASON_NO_CONTRACT)
        & (audit["order_type"] == rules.WEB_RENEWAL_ORDER_TYPE)
    )
    web_without_contract = int(web_no_contract.sum())
    if variant == rules.VARIANT_FULL and web_without_contract:
        added = audit.loc[web_no_contract].copy()
        added["contract_source"] = "web"
        added["agent"] = rules.WEB_NO_CONTRACT_AGENT
        added["sales_point"] = ""
        added["flag_selfservice"] = False
        added["flag_express"] = added["key"].isin(set(in_period[rules.EXPRESS]["key"]))
        added["flag_cc"] = added["key"].isin(set(in_period[rules.CLICK_COLLECT]["key"]))
        added["flag_web"] = True
        added["web_link"] = "no_contract"
        renewals = pd.concat([renewals, added.reindex(columns=renewals.columns)], ignore_index=True)
        audit = audit.loc[~web_no_contract]
        # flags from other sources on these keys are no longer unmatched
        audit = audit.loc[~audit["key"].isin(set(added["key"]))]

    audit["reason"] = audit["reason_code"].map(rules.REASON_TEXT)
    unmatched = (
        audit.loc[:, list(AUDIT_COLUMNS)]
        .sort_values(["date", "source", "phone"], kind="stable")
        .reset_index(drop=True)
    )

    renewals = _owners(renewals, master)
    web_owner = renewals["agent"] == rules.WEB_NO_CONTRACT_AGENT
    renewals.loc[web_owner, "agent_name"] = rules.WEB_NO_CONTRACT_NAME
    renewals = _flag_frame(renewals)
    keep = [
        "date",
        "phone",
        "key",
        "contract_source",
        "record_id",
        "agent",
        "agent_name",
        "sales_point",
        "block_id",
        "block_type",
        "block_name",
        "region",
        "channel_group",
        "flag_selfservice",
        "flag_express",
        "flag_cc",
        "flag_web",
        "web_link",
        *COUNT_COLUMNS,
    ]
    renewals = renewals.loc[:, keep].sort_values(["date", "phone"], kind="stable")
    return V4Result(
        period=period,
        variant=variant,
        lookahead_days=lookahead_days,
        renewals=renewals.reset_index(drop=True),
        unmatched=unmatched,
        links=links.sort_values(["order_date", "phone"]).reset_index(drop=True),
        events=events,
        collapsed=collapsed,
        web_without_contract=web_without_contract,
        master=master,
    )


def lookback_days_needed(lookahead_days: int) -> timedelta:
    """How far before the period the inputs must reach for rule 7."""
    return timedelta(days=lookahead_days)
