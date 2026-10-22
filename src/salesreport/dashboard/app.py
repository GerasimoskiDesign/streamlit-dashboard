"""Streamlit entry point: ``python -m salesreport dashboard``.

The app reads the engine's Parquet output and never recomputes business logic. All
data passes through ``allowed_rows`` before any page sees it.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import streamlit as st

from salesreport import settings
from salesreport.dashboard.access import (
    DATA_QUALITY,
    ROLE_LABELS,
    Role,
    User,
    allowed_rows,
    can_view,
)
from salesreport.dashboard.auth import authenticate, load_users
from salesreport.dashboard.data import Dataset, dataset_available, load_dataset
from salesreport.dashboard.export import to_excel_bytes
from salesreport.dashboard.views import (
    CHANNEL_NAMES,
    Filters,
    agent_detail,
    apply_filters,
    channel_mix,
    data_quality,
    evolution,
    leaderboard,
    overview,
)

PAGES = ["Overview", "Leaderboard", "Agent detail", "Channel mix", "Data quality", "How it evolved"]

CSS = """
<style>
#MainMenu, footer {visibility: hidden;}
.block-container {padding-top: 2.2rem; max-width: 1400px;}
.page-header {border-left: 4px solid #2a78d6; padding: 0.15rem 0 0.15rem 0.9rem;
  margin-bottom: 1.1rem;}
.page-header h1 {font-size: 1.65rem; margin: 0; padding: 0; color: #1f2937; font-weight: 700;}
.page-header p {margin: 0.2rem 0 0 0; color: #52514e; font-size: 0.92rem;}
[data-testid="stMetric"] {background: #ffffff; border: 1px solid #e1e0d9; border-radius: 10px;
  padding: 0.85rem 1rem; box-shadow: 0 1px 2px rgba(15, 23, 42, 0.04);}
[data-testid="stMetricLabel"] p {font-size: 0.82rem; color: #52514e; text-transform: uppercase;
  letter-spacing: 0.04em;}
.tile {background: #ffffff; border: 1px solid #e1e0d9; border-radius: 10px; padding: 0.85rem 1rem;
  min-height: 112px; border-top: 4px solid #c3c2b7;}
.tile.ok {border-top-color: #0ca30c;}
.tile.bad {border-top-color: #d03b3b; background: #fff8f7;}
.tile.neutral {border-top-color: #2a78d6;}
.tile.na {border-top-color: #c3c2b7; background: #fafaf8;}
.tile-label {font-size: 0.78rem; color: #52514e; text-transform: uppercase; letter-spacing: 0.04em;}
.tile-value {font-size: 1.9rem; font-weight: 700; color: #1f2937; margin-top: 0.2rem;}
.tile-status {font-size: 0.8rem; color: #52514e;}
.tile.bad .tile-status {color: #b42318; font-weight: 600;}
.tile.ok .tile-status {color: #0a7d0a; font-weight: 600;}
.version-card {background: #ffffff; border: 1px solid #e1e0d9; border-radius: 10px;
  padding: 0.9rem 1.1rem; margin: 0.4rem 0 1rem 0;}
.version-card h3 {margin: 0 0 0.3rem 0; font-size: 1.1rem; color: #1f2937;}
.version-card p {margin: 0; color: #52514e;}
.user-card {background: rgba(255,255,255,0.06); border: 1px solid rgba(255,255,255,0.12);
  border-radius: 10px; padding: 0.7rem 0.8rem; margin-bottom: 0.6rem;}
.user-card .name {font-weight: 600;}
.user-card .role {font-size: 0.8rem; opacity: 0.8;}
.login-card {max-width: 440px; margin: 6vh auto 0 auto;}
.brand {font-size: 0.78rem; letter-spacing: 0.12em; text-transform: uppercase; color: #2a78d6;
  font-weight: 700;}
</style>
"""


@st.cache_data(show_spinner=False)
def _cached_dataset(folder: str, mtime: float) -> Dataset:
    return load_dataset(Path(folder))


@st.cache_resource(show_spinner=False)
def _cached_users(path: str, mtime: float):
    return load_users(Path(path))


def render_login() -> None:
    _, center, _ = st.columns([1, 1.2, 1])
    with center:
        st.markdown('<div class="brand">Renewals reporting</div>', unsafe_allow_html=True)
        st.markdown("## Sign in")
        st.caption("Synthetic demo data. Demo accounts are listed in the README.")
        username = st.text_input("Username", key="login_user")
        password = st.text_input("Password", type="password", key="login_password")
        if st.button("Sign in", type="primary", key="login_submit", width="stretch"):
            users_path = settings.users_file()
            users = _cached_users(str(users_path), users_path.stat().st_mtime)
            user = authenticate(username, password, users)
            if user is None:
                st.error("Unknown user or wrong password.")
            else:
                st.session_state["user"] = user
                st.rerun()
        st.caption("In production this screen is replaced by the company single sign-on.")


def sidebar(user: User, data: Dataset, scoped: pd.DataFrame) -> tuple[str, Filters]:
    with st.sidebar:
        st.markdown(
            f'<div class="user-card"><div class="name">{user.display_name}</div>'
            f'<div class="role">{ROLE_LABELS[user.role]} | {user.username}</div></div>',
            unsafe_allow_html=True,
        )
        pages = [p for p in PAGES if p != "Data quality" or can_view(user, DATA_QUALITY)]
        page = st.radio("Page", pages, key="page", label_visibility="collapsed")
        st.divider()
        first = scoped["date"].min().date() if len(scoped) else data.period_start
        start_end = st.date_input(
            "Date range",
            value=(data.period_start, data.as_of),
            min_value=first,
            max_value=data.as_of,
            format="DD.MM.YYYY",
            key="date_range",
        )
        if isinstance(start_end, tuple | list) and len(start_end) == 2:
            start, end = start_end
        else:
            start = end = start_end[0] if isinstance(start_end, tuple | list) else start_end
        region: str | None = None
        if user.role is Role.REGIONAL_MANAGER:
            regions = sorted(r for r in scoped["region"].dropna().unique() if r)
            choice = st.selectbox("Region", ["All regions", *regions], key="region")
            region = None if choice == "All regions" else choice
        else:
            st.selectbox(
                "Region",
                [user.region or ""],
                disabled=True,
                key="region_locked",
                help="Your role is locked to this region.",
            )
        available = [c for c in CHANNEL_NAMES if c in set(scoped["channel_group"])]
        channels = st.multiselect(
            "Channel", available, default=available, format_func=CHANNEL_NAMES.get, key="channels"
        )
        filters = Filters(start=start, end=end, region=region, channels=channels)
        st.divider()
        view = apply_filters(scoped, filters)
        st.download_button(
            "Export current view (.xlsx)",
            data=to_excel_bytes(
                view, f"{page} | {start:%d.%m.%Y}-{end:%d.%m.%Y} | {user.username}"
            ),
            file_name=f"renewals_view_{end:%Y%m%d}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            width="stretch",
            key="export",
        )
        st.caption(
            f"Data up to {data.as_of:%d.%m.%Y} | "
            f"last refreshed {data.refreshed_at:%d.%m.%Y %H:%M} | "
            f"logic {data.meta.get('logic', 'v4')} ({data.meta.get('variant', 'strict')})"
        )
        if st.button("Log out", key="logout", width="stretch"):
            for key in list(st.session_state.keys()):
                del st.session_state[key]
            st.rerun()
    return page, filters


def main() -> None:
    st.set_page_config(
        page_title="Renewals reporting", page_icon=":material/insights:", layout="wide"
    )
    st.markdown(CSS, unsafe_allow_html=True)
    if settings.maintenance_mode():
        st.info("Refreshing data, check back in a few minutes.", icon=":material/autorenew:")
        st.stop()
    folder = settings.output_dir() / "dashboard"
    if not dataset_available(folder):
        st.error(
            "No dashboard data yet. Run `python -m salesreport generate` and "
            "`python -m salesreport build 17.09.2026` first."
        )
        st.stop()
    data = _cached_dataset(str(folder), (folder / "daily_agent.parquet").stat().st_mtime)
    user: User | None = st.session_state.get("user")
    if user is None:
        render_login()
        st.stop()

    scoped = allowed_rows(user, data.daily)
    page, filters = sidebar(user, data, scoped)
    if page == "Overview":
        overview(user, scoped, filters)
    elif page == "Leaderboard":
        leaderboard(user, scoped, filters)
    elif page == "Agent detail":
        agent_detail(user, scoped, filters)
    elif page == "Channel mix":
        channel_mix(user, scoped, filters)
    elif page == "Data quality":
        data_quality(user, data)
    else:
        evolution(user, data)


main()
