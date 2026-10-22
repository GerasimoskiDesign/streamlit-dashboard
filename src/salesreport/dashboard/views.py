"""Dashboard pages. Every page receives rows already filtered by ``allowed_rows``."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from salesreport import rules
from salesreport.dashboard.access import (
    AGENT,
    DATA_QUALITY,
    ROLE_LABELS,
    Role,
    User,
    allowed_rows,
)
from salesreport.dashboard.data import Dataset, totals
from salesreport.dates import add_months

BLUE = "#2a78d6"
ORANGE = "#eb6834"
AQUA = "#1baf7a"
YELLOW = "#eda100"
NEUTRAL = "#c3c2b7"
CRITICAL = "#d03b3b"
GOOD = "#0a7d0a"
INK = "#1f2937"
INK_2 = "#52514e"
GRID = "#e9e8e3"
REGION_COLORS = {"North": BLUE, "South": ORANGE, "East": AQUA, "West": YELLOW}
CHANNEL_NAMES = {"shop": "Retail shops", **rules.CHANNEL_LABELS}

VERSION_TEXT = {
    "v1": (
        "Shop totals",
        "Renewal and self-service contracts counted per shop for the month to date. Fast and "
        "simple - but no agent view, one digital source, and duplicate export rows count twice.",
    ),
    "v2": (
        "Per agent",
        "Each contract is attributed to its agent, each agent to a home shop. Shop managers "
        "can see "
        "who sells what. Agents working in two shops are booked to their home shop only.",
    ),
    "v3": (
        "Prototype at scale",
        "What happens when a working prototype meets messy multi-source data: every digital source "
        "is counted on its own and added up. One sale seen in two sources counts twice, journeys "
        "that never became a renewal still count, and sources without an agent reach the shop row "
        "but not the agent rows.",
    ),
    "v4": (
        "Event-level engine (production)",
        "One renewal = one (date, phone) key. Digital sources only flag an existing renewal and "
        "inherit its owner, so digital share cannot exceed 100 % and agent rows always add up to "
        "the shop. Unmatched digital transactions go to an audit table with a reason.",
    ),
}


@dataclass
class Filters:
    """Sidebar selections."""

    start: date
    end: date
    region: str | None
    channels: list[str]


def apply_filters(
    frame: pd.DataFrame, f: Filters, start: date | None = None, end: date | None = None
) -> pd.DataFrame:
    """Date range, region and channel filters (region only exists for regional managers)."""
    lo, hi = pd.Timestamp(start or f.start), pd.Timestamp(end or f.end)
    out = frame.loc[(frame["date"] >= lo) & (frame["date"] <= hi)]
    if f.region:
        out = out.loc[out["region"] == f.region]
    if f.channels:
        out = out.loc[out["channel_group"].isin(f.channels)]
    return out


def previous_period(f: Filters) -> tuple[date, date]:
    """Same days last month."""
    return add_months(f.start, -1), add_months(f.end, -1)


def page_header(title: str, subtitle: str) -> None:
    st.markdown(
        f'<div class="page-header"><h1>{title}</h1><p>{subtitle}</p></div>', unsafe_allow_html=True
    )


def style(fig: go.Figure, height: int = 340) -> go.Figure:
    """Shared, quiet Plotly styling (one axis, recessive grid, system font)."""
    fig.update_layout(
        height=height,
        margin=dict(l=8, r=8, t=64, b=8),
        title=dict(x=0, xanchor="left", y=0.98, yanchor="top", font=dict(size=15, color=INK)),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family="system-ui, -apple-system, Segoe UI, sans-serif", color=INK_2, size=12),
        legend=dict(orientation="h", yanchor="bottom", y=1.0, xanchor="right", x=1, title=None),
        hoverlabel=dict(bgcolor="white", font_size=12),
        bargap=0.25,
    )
    fig.update_xaxes(gridcolor=GRID, zeroline=False, linecolor=NEUTRAL)
    fig.update_yaxes(gridcolor=GRID, zeroline=False, linecolor=NEUTRAL)
    return fig


def pct(value: float | None) -> str:
    return "-" if value is None else f"{value * 100:.1f} %"


def scope_text(user: User) -> str:
    if user.role is Role.REGIONAL_MANAGER:
        return "all regions and channels"
    if user.role is Role.SHOP_MANAGER:
        return f"region {user.region} in detail, other regions as shop totals"
    return f"your shop ({user.shop_id})"


# --- pages ------------------------------------------------------------------------------
def overview(user: User, rows: pd.DataFrame, f: Filters) -> None:
    page_header("Overview", f"{f.start:%d.%m}-{f.end:%d.%m.%Y} | {scope_text(user)}")
    current = apply_filters(rows, f)
    prev_start, prev_end = previous_period(f)
    previous = apply_filters(rows, f, prev_start, prev_end)
    now, before = totals(current), totals(previous)
    has_previous = before["renewals"] > 0

    def count_delta(key: str) -> str | None:
        if not has_previous or not before[key]:
            return None
        change = (now[key] - before[key]) / before[key]
        return f"{change * 100:+.1f} % vs last month"

    def share_delta(key: str) -> str | None:
        if not has_previous or now[key] is None or before[key] is None:
            return None
        return f"{(now[key] - before[key]) * 100:+.1f} pp vs last month"

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Renewals", f"{now['renewals']:,.0f}", count_delta("renewals"))
    c2.metric("Digital renewals", f"{now['digital']:,.0f}", count_delta("digital"))
    c3.metric("Digital share", pct(now["share"]), share_delta("share"))
    c4.metric("Digital share excl. C&C", pct(now["share_excl_cc"]), share_delta("share_excl_cc"))

    if not len(current):
        st.info("No renewals in the selected range.")
        return
    daily = current.groupby("date")[["renewals", "digital"]].sum().reset_index()
    daily["Not digital"] = daily["renewals"] - daily["digital"]
    long = daily.melt(
        id_vars="date", value_vars=["digital", "Not digital"], var_name="kind", value_name="count"
    )
    long["kind"] = long["kind"].replace({"digital": "Digital"})
    left, right = st.columns([3, 2])
    with left:
        fig = px.bar(
            long,
            x="date",
            y="count",
            color="kind",
            color_discrete_map={"Digital": BLUE, "Not digital": NEUTRAL},
            labels={"date": "", "count": "Renewals", "kind": ""},
            title="Renewals per day",
        )
        fig.update_traces(marker_line_color="white", marker_line_width=1)
        st.plotly_chart(style(fig), width="stretch")
    with right:
        daily["share"] = daily["digital"] / daily["renewals"]
        fig = go.Figure()
        fig.add_scatter(
            x=daily["date"],
            y=daily["share"],
            mode="lines+markers",
            name="This period",
            line=dict(color=BLUE, width=2),
            marker=dict(size=8),
        )
        if has_previous:
            prev_daily = previous.groupby("date")[["renewals", "digital"]].sum().reset_index()
            prev_daily["share"] = prev_daily["digital"] / prev_daily["renewals"]
            prev_daily["date"] = prev_daily["date"].map(
                lambda d: pd.Timestamp(add_months(d.date(), 1))
            )
            fig.add_scatter(
                x=prev_daily["date"],
                y=prev_daily["share"],
                mode="lines",
                name="Same days last month",
                line=dict(color=NEUTRAL, width=2, dash="dot"),
            )
        fig.update_layout(title="Digital share per day")
        fig.update_yaxes(tickformat=".0%", rangemode="tozero")
        st.plotly_chart(style(fig), width="stretch")


def leaderboard(user: User, rows: pd.DataFrame, f: Filters) -> None:
    page_header(
        "Leaderboard", f"Shops ranked for {f.start:%d.%m}-{f.end:%d.%m.%Y} | {scope_text(user)}"
    )
    current = apply_filters(rows, f)
    shops = current.loc[current["block_type"] == "shop"]
    if not len(shops):
        st.info("No shop rows in the selected range.")
        return
    board = (
        shops.groupby(["block_id", "block_name", "region"])[
            ["renewals", "digital", "digital_excl_cc"]
        ]
        .sum()
        .reset_index()
    )
    board["share"] = board["digital"] / board["renewals"]
    board["label"] = board["block_name"] + " (" + board["block_id"] + ")"
    if user.role is Role.SHOP_MANAGER:
        board["label"] = board.apply(
            lambda r: r["label"] + (" *" if r["region"] == user.region else ""), axis=1
        )
    height = max(320, 22 * len(board) + 80)
    left, right = st.columns(2)
    for column, metric, title, fmt_ in (
        (left, "renewals", "By renewals", ",.0f"),
        (right, "share", "By digital share", ".1%"),
    ):
        ordered = board.sort_values(metric, ascending=False)  # largest on top
        fig = px.bar(
            ordered,
            x=metric,
            y="label",
            color="region",
            orientation="h",
            color_discrete_map=REGION_COLORS,
            title=title,
            labels={metric: "", "label": "", "region": "Region"},
            category_orders={"label": list(ordered["label"]), "region": list(REGION_COLORS)},
            hover_data={"renewals": ":,.0f", "share": ":.1%", "label": False},
        )
        fig.update_xaxes(tickformat=fmt_)
        with column:
            st.plotly_chart(style(fig, height), width="stretch")
    if user.role is Role.SHOP_MANAGER:
        st.caption(r"\* your region. Other regions are shown as shop totals only - no agent names.")
    table = board.sort_values("renewals", ascending=False).reset_index(drop=True)
    table.insert(0, "Rank (renewals)", range(1, len(table) + 1))
    table["Rank (digital share)"] = table["share"].rank(ascending=False, method="min").astype(int)
    st.dataframe(
        table[
            [
                "Rank (renewals)",
                "Rank (digital share)",
                "block_name",
                "region",
                "renewals",
                "digital",
                "share",
            ]
        ],
        hide_index=True,
        width="stretch",
        column_config={
            "block_name": "Shop",
            "region": "Region",
            "renewals": st.column_config.NumberColumn("Renewals", format="%d"),
            "digital": st.column_config.NumberColumn("Digital", format="%d"),
            "share": st.column_config.ProgressColumn(
                "Digital share", format="percent", min_value=0, max_value=1
            ),
        },
    )


def agent_detail(user: User, rows: pd.DataFrame, f: Filters) -> None:
    page_header(
        "Agent detail", f"{f.start:%d.%m}-{f.end:%d.%m.%Y} | agent rows where your role allows them"
    )
    current = apply_filters(rows, f)
    agents = current.loc[current["detail"] == AGENT]
    if not len(agents):
        st.info("No agent-level rows are available for your role and filters.")
        return
    blocks = agents.groupby(["block_id", "block_name"])["renewals"].sum().reset_index()
    blocks = blocks.sort_values(["block_id"])
    labels = {
        r.block_id: f"{r.block_name} ({r.block_id})"
        if not r.block_id.startswith("CH:")
        else r.block_name
        for r in blocks.itertuples()
    }
    if len(blocks) > 1:
        chosen = st.selectbox(
            "Shop / channel", list(labels), format_func=labels.get, key="agent_block"
        )
    else:
        chosen = blocks["block_id"].iloc[0]
        st.markdown(f"**{labels[chosen]}**")
    block = agents.loc[agents["block_id"] == chosen]
    table = (
        block.groupby(["agent", "agent_name"])[
            ["renewals", "store", "selfservice", "digital", "digital_excl_cc", "cc_only"]
        ]
        .sum()
        .reset_index()
    )
    table["share"] = table["digital"] / table["renewals"]
    table["share_excl_cc"] = table["digital_excl_cc"] / table["renewals"]
    table = table.sort_values("renewals", ascending=False)
    shop_total = totals(block)
    c1, c2, c3 = st.columns(3)
    c1.metric("Renewals (shop)", f"{shop_total['renewals']:,.0f}")
    c2.metric("Digital share (shop)", pct(shop_total["share"]))
    c3.metric("Agents", f"{len(table)}")
    chart = table  # already sorted, largest on top
    chart_long = pd.DataFrame(
        {
            "agent": list(chart["agent_name"] + " (" + chart["agent"] + ")") * 2,
            "kind": ["Digital"] * len(chart) + ["Not digital"] * len(chart),
            "count": list(chart["digital"]) + list(chart["renewals"] - chart["digital"]),
        }
    )
    fig = px.bar(
        chart_long,
        x="count",
        y="agent",
        color="kind",
        orientation="h",
        color_discrete_map={"Digital": BLUE, "Not digital": NEUTRAL},
        labels={"count": "Renewals", "agent": "", "kind": ""},
        title="Renewals per agent",
        category_orders={"agent": list(chart["agent_name"] + " (" + chart["agent"] + ")")},
    )
    fig.update_traces(marker_line_color="white", marker_line_width=1)
    st.plotly_chart(style(fig, max(300, 30 * len(table) + 90)), width="stretch")
    st.dataframe(
        table[
            [
                "agent",
                "agent_name",
                "renewals",
                "store",
                "selfservice",
                "digital",
                "share",
                "share_excl_cc",
                "cc_only",
            ]
        ],
        hide_index=True,
        width="stretch",
        column_config={
            "agent": "Agent",
            "agent_name": "Name",
            "renewals": "Renewals",
            "store": "Store",
            "selfservice": "Self-service",
            "digital": "Digital",
            "share": st.column_config.ProgressColumn(
                "Digital share", format="percent", min_value=0, max_value=1
            ),
            "share_excl_cc": st.column_config.NumberColumn("Share excl. C&C", format="percent"),
            "cc_only": "C&C only",
        },
    )


def channel_mix(user: User, rows: pd.DataFrame, f: Filters) -> None:
    page_header("Channel mix", f"Digital channels over time | {scope_text(user)}")
    current = apply_filters(rows, f)
    if not len(current):
        st.info("No renewals in the selected range.")
        return
    flags = {
        "ss_digital": "Self-service",
        "express": "Express",
        "cc": "Click & collect",
        "web": "Web order",
    }
    daily = current.groupby("date")[[*flags, "digital"]].sum().reset_index()
    long = daily.melt(id_vars="date", value_vars=list(flags), var_name="flag", value_name="count")
    long["flag"] = long["flag"].map(flags)
    fig = px.bar(
        long,
        x="date",
        y="count",
        color="flag",
        color_discrete_map={
            "Self-service": BLUE,
            "Express": ORANGE,
            "Click & collect": AQUA,
            "Web order": YELLOW,
        },
        labels={"date": "", "count": "Flags", "flag": ""},
        title="Digital flags per day (stacked)",
        category_orders={"flag": list(flags.values())},
    )
    fig.update_traces(marker_line_color="white", marker_line_width=1)
    fig.add_scatter(
        x=daily["date"],
        y=daily["digital"],
        mode="lines+markers",
        name="Digital renewals",
        line=dict(color=INK, width=2),
        marker=dict(size=8),
    )
    st.plotly_chart(style(fig, 380), width="stretch")
    st.caption(
        "The bars count flags, the line counts renewals. One renewal can carry several flags "
        "(for example express and click & collect), so the stack can be taller than the line - "
        "exactly the double count v3 used to publish as digital renewals."
    )
    summary = current[[*flags, "digital", "cc_only", "renewals"]].sum()
    table = pd.DataFrame(
        {
            "Measure": [*flags.values(), "Digital renewals", "Digital only via C&C", "Renewals"],
            "Count": [int(summary[c]) for c in [*flags, "digital", "cc_only", "renewals"]],
        }
    )
    st.dataframe(table, hide_index=True, width="content")


def data_quality(user: User, data: Dataset) -> None:
    page_header(
        "Data quality", "Control totals and the unmatched-digital audit for the reporting month"
    )
    controls = allowed_rows(user, data.controls, DATA_QUALITY)
    unmatched = allowed_rows(user, data.unmatched, DATA_QUALITY)
    if user.role is not Role.REGIONAL_MANAGER:
        st.warning("Data quality is available to regional managers only.")
        return
    invariants = controls.loc[controls["section"] == "Invariants"]
    columns = st.columns(len(invariants))
    for column, row in zip(columns, invariants.itertuples(), strict=True):
        status = "OK" if row.status == "OK" else "CHECK"
        css = "ok" if status == "OK" else "bad"
        column.markdown(
            f'<div class="tile {css}"><div class="tile-label">{row.metric}</div>'
            f'<div class="tile-value">{row.value}</div>'
            f'<div class="tile-status">{status} - {row.expectation}</div></div>',
            unsafe_allow_html=True,
        )
    st.markdown("#### Unmatched digital transactions")
    if len(unmatched):
        counts = unmatched.groupby(["reason_code", "source"]).size().rename("count").reset_index()
        counts["reason"] = counts["reason_code"].map(
            {
                rules.REASON_EXCLUDED: "a) excluded population",
                rules.REASON_NOT_RENEWAL: "b) contract, not a renewal",
                rules.REASON_NO_CONTRACT: "c) no contract that day",
            }
        )
        fig = px.bar(
            counts,
            x="count",
            y="reason",
            color="source",
            orientation="h",
            color_discrete_sequence=[BLUE, ORANGE, AQUA, YELLOW],
            labels={"count": "Transactions", "reason": "", "source": "Source"},
        )
        st.plotly_chart(style(fig, 260), width="stretch")
        open_window = int(unmatched["window_open"].sum())
        if open_window:
            st.caption(
                f"{open_window} web orders are still inside the look-ahead window "
                "and may link to a renewal tomorrow."
            )
    st.markdown("#### Control totals")
    st.dataframe(controls, hide_index=True, width="stretch")
    with st.expander("Unmatched audit rows (phone numbers masked)"):
        st.dataframe(unmatched.head(2000), hide_index=True, width="stretch")


def evolution(user: User, data: Dataset) -> None:
    page_header(
        "How it evolved: from prototype to production",
        "The same month-to-date inputs under each logic version. "
        "Aggregated and anonymous - safe for every role.",
    )
    table = allowed_rows(user, data.evolution, "evolution")
    shares = allowed_rows(user, data.unit_shares, "evolution")
    versions = list(table["version"])
    version = st.radio(
        "Logic version",
        versions,
        index=len(versions) - 1,
        horizontal=True,
        key="version",
        format_func=lambda v: f"{v} - {VERSION_TEXT[v][0]}",
    )
    row = table.set_index("version").loc[version]
    title, text = VERSION_TEXT[version]
    st.markdown(
        f'<div class="version-card"><h3>{version}: {title}</h3><p>{text}</p></div>',
        unsafe_allow_html=True,
    )

    def tile(column, label: str, value, problem: bool | None) -> None:
        if value is None or (isinstance(value, float) and value != value):
            shown, css, status = "n/a", "na", "no agent view"
        else:
            shown = f"{value:,.0f}" if not isinstance(value, str) else value
            css = "bad" if problem else "ok"
            status = "problem" if problem else "OK"
        column.markdown(
            f'<div class="tile {css}"><div class="tile-label">{label}</div>'
            f'<div class="tile-value">{shown}</div><div class="tile-status">{status}</div></div>',
            unsafe_allow_html=True,
        )

    cols = st.columns(5)
    share = row["digital_share"]
    cols[0].markdown(
        f'<div class="tile neutral"><div class="tile-label">Network digital share</div>'
        f'<div class="tile-value">{pct(share)}</div>'
        f'<div class="tile-status">{int(row["digital"]):,} of '
        f"{int(row['total_renewals']):,}</div></div>",
        unsafe_allow_html=True,
    )
    for column, key, label in zip(
        cols[1:],
        ["agents_over_100", "shops_over_100", "mismatched_blocks", "double_counted"],
        [
            "Agents above 100 %",
            "Shops above 100 %",
            "Agent rows != shop row",
            "Same sale counted twice",
        ],
        strict=True,
    ):
        value = row[key]
        problem = None if value is None or value != value else value > 0
        tile(column, label, value, problem)

    chosen = shares.loc[shares["version"] == version].copy()
    if len(chosen):
        chosen["share_pct"] = chosen["share"] * 100
        chosen["band"] = chosen["share"].map(
            lambda s: "Above 100 %" if s > 1 else "At or below 100 %"
        )
        fig = px.histogram(
            chosen,
            x="share_pct",
            color="band",
            facet_col="level",
            nbins=40,
            color_discrete_map={"At or below 100 %": BLUE, "Above 100 %": CRITICAL},
            labels={"share_pct": "Digital share (%)", "band": "", "level": ""},
            category_orders={
                "level": ["agent", "shop"],
                "band": ["At or below 100 %", "Above 100 %"],
            },
            title="Distribution of digital share - agents and shops",
        )
        fig.for_each_annotation(lambda a: a.update(text=a.text.split("=")[-1].capitalize() + "s"))
        fig.add_vline(x=100, line_dash="dot", line_color=INK, annotation_text="100 %")
        st.plotly_chart(style(fig, 330), width="stretch")

    st.markdown("#### All versions side by side")
    show = table[
        [
            "version",
            "title",
            "total_renewals",
            "digital",
            "digital_share",
            "agents_over_100",
            "shops_over_100",
            "mismatched_blocks",
            "double_counted",
            "digital_sources",
        ]
    ]
    st.dataframe(
        show,
        hide_index=True,
        width="stretch",
        column_config={
            "version": "Version",
            "title": "Name",
            "total_renewals": "Renewals",
            "digital": "Digital (as counted)",
            "digital_share": st.column_config.NumberColumn("Digital share", format="percent"),
            "agents_over_100": "Agents > 100 %",
            "shops_over_100": "Shops > 100 %",
            "mismatched_blocks": "Agent rows != shop",
            "double_counted": "Counted twice",
            "digital_sources": "Digital sources",
        },
    )
    st.caption(
        "v1 and v2 look clean because they only know one digital source. v3 adds the other "
        "sources by adding counts, and the symptoms appear. v4 keeps all sources but treats them "
        "as flags on one renewal, so every invariant holds by construction."
    )


def role_label(user: User) -> str:
    return ROLE_LABELS[user.role]
