"""Role-based access: every cell of the permission matrix, the export and the app itself."""

from __future__ import annotations

from io import BytesIO
from pathlib import Path

import pandas as pd
import pytest

from salesreport.dashboard.access import (
    AGENT,
    DATA_QUALITY,
    EVOLUTION,
    PERMISSION_MATRIX,
    RESOURCES,
    SHOP_TOTAL,
    Role,
    User,
    allowed_rows,
    can_view,
)
from salesreport.dashboard.auth import authenticate, load_users
from salesreport.dashboard.export import to_excel_bytes
from salesreport.settings import PROJECT_ROOT

COUNTS = {
    "renewals": 1,
    "digital": 1,
    "digital_excl_cc": 1,
    "cc_only": 0,
    "store": 1,
    "selfservice": 0,
}


def _row(block_id, block_type, region, agent, channel="shop"):
    return {
        "month": "2026-09",
        "date": pd.Timestamp("2026-09-10"),
        "block_id": block_id,
        "block_type": block_type,
        "block_name": block_id,
        "region": region,
        "channel_group": channel,
        "agent": agent,
        "agent_name": f"Name {agent}",
        **COUNTS,
    }


@pytest.fixture
def daily() -> pd.DataFrame:
    """Two regions, two shops each, two agents per shop, plus a telesales block."""
    rows = []
    for region, shops in (("North", ("SH01", "SH02")), ("South", ("SH03", "SH04"))):
        for shop in shops:
            rows += [
                _row(shop, "shop", region, f"{shop}_a"),
                _row(shop, "shop", region, f"{shop}_b"),
            ]
    rows.append(_row("CH:telesales", "channel", "", "tele_a", channel="telesales"))
    return pd.DataFrame(rows)


USERS = {
    Role.REGIONAL_MANAGER: User("rm", "RM", Role.REGIONAL_MANAGER),
    Role.SHOP_MANAGER: User("sm", "SM", Role.SHOP_MANAGER, region="North"),
    Role.EMPLOYEE: User("emp", "EMP", Role.EMPLOYEE, region="North", shop_id="SH01"),
}


def observed(user: User, daily: pd.DataFrame, resource: str) -> bool:
    """What the user can actually see, measured on allowed_rows' output."""
    if resource == "data_quality":
        controls = pd.DataFrame({"metric": ["x"], "value": [0]})
        return len(allowed_rows(user, controls, DATA_QUALITY)) > 0
    if resource == "evolution":
        return len(allowed_rows(user, pd.DataFrame({"version": ["v4"]}), EVOLUTION)) > 0
    rows = allowed_rows(user, daily)
    agents = rows.loc[(rows["detail"] == AGENT) & rows["agent"].notna()]
    own_shop = user.shop_id or "SH01"  # managers: a shop in their own region
    own_region = user.region or "North"
    region_other_shop = "SH02"
    other_region_shop = "SH03"
    checks = {
        "own_shop_totals": own_shop in set(rows["block_id"]),
        "own_shop_agents": own_shop in set(agents["block_id"]),
        "region_shop_totals": region_other_shop
        in set(rows.loc[rows["region"] == own_region, "block_id"]),
        "region_agents": region_other_shop in set(agents["block_id"]),
        "other_region_shop_totals": other_region_shop in set(rows["block_id"]),
        "other_region_agents": other_region_shop in set(agents["block_id"]),
        "other_channels": "CH:telesales" in set(rows["block_id"]),
    }
    return checks[resource]


@pytest.mark.parametrize("role", list(Role))
@pytest.mark.parametrize("resource", RESOURCES)
def test_permission_matrix_cell(daily, role, resource):
    assert observed(USERS[role], daily, resource) is PERMISSION_MATRIX[resource][role]


def test_shop_manager_sees_other_regions_without_agent_identity(daily):
    rows = allowed_rows(USERS[Role.SHOP_MANAGER], daily)
    other = rows.loc[rows["region"] == "South"]
    assert set(other["detail"]) == {SHOP_TOTAL}
    assert other["agent"].isna().all() and other["agent_name"].isna().all()
    assert other.groupby("block_id")["renewals"].sum().to_dict() == {"SH03": 2, "SH04": 2}
    assert not rows["agent_name"].fillna("").str.contains("SH03|SH04").any()


def test_employee_sees_only_own_shop(daily):
    rows = allowed_rows(USERS[Role.EMPLOYEE], daily)
    assert set(rows["block_id"]) == {"SH01"}


def test_totals_are_preserved_by_masking(daily):
    rm = allowed_rows(USERS[Role.REGIONAL_MANAGER], daily)
    sm = allowed_rows(USERS[Role.SHOP_MANAGER], daily)
    shops = rm.loc[rm["block_type"] == "shop"]
    assert shops["renewals"].sum() == sm["renewals"].sum()


def test_unknown_dataset_is_rejected(daily):
    with pytest.raises(ValueError):
        allowed_rows(USERS[Role.REGIONAL_MANAGER], daily, "everything")


def test_navigation_hides_data_quality_for_non_managers():
    assert can_view(USERS[Role.REGIONAL_MANAGER], DATA_QUALITY)
    assert not can_view(USERS[Role.SHOP_MANAGER], DATA_QUALITY)
    assert not can_view(USERS[Role.EMPLOYEE], DATA_QUALITY)


@pytest.mark.parametrize("role", list(Role))
def test_excel_export_contains_only_permitted_rows(daily, role):
    user = USERS[role]
    content = to_excel_bytes(allowed_rows(user, daily), "test")
    exported = pd.read_excel(BytesIO(content), sheet_name="Current view", header=2)
    shops = set(exported["Shop / channel"])
    agents = set(exported["Agent"].dropna())
    if role is Role.REGIONAL_MANAGER:
        assert shops == {"SH01", "SH02", "SH03", "SH04", "CH:telesales"}
        assert "SH03_a" in agents
    elif role is Role.SHOP_MANAGER:
        assert shops == {"SH01", "SH02", "SH03", "SH04"}
        assert agents == {"SH01_a", "SH01_b", "SH02_a", "SH02_b"}
    else:
        assert shops == {"SH01"} and agents == {"SH01_a", "SH01_b"}
    assert exported["Total renewals"].sum() == allowed_rows(user, daily)["renewals"].sum()


# --- auth ---------------------------------------------------------------------------------
def test_demo_users_cover_every_role_and_several_regions():
    users = load_users(PROJECT_ROOT / "config" / "users.toml")
    roles = {u.user.role for u in users.values()}
    regions = {u.user.region for u in users.values() if u.user.region}
    assert roles == set(Role)
    assert len(regions) >= 2


def test_authentication_with_bcrypt():
    users = load_users(PROJECT_ROOT / "config" / "users.toml")
    assert authenticate("regional", "demo-regional", users).role is Role.REGIONAL_MANAGER
    assert authenticate("Regional ", "demo-regional", users) is not None
    assert authenticate("regional", "wrong", users) is None
    assert authenticate("nobody", "demo-regional", users) is None
    assert authenticate("regional", "", users) is None


def test_user_file_validation(tmp_path: Path):
    bad = tmp_path / "users.toml"
    bad.write_text(
        '[users.x]\nrole = "employee"\nregion = "North"\npassword_hash = "x"\n', encoding="utf-8"
    )
    with pytest.raises(ValueError, match="shop_id"):
        load_users(bad)


# --- the app itself -------------------------------------------------------------------------
APP = str(PROJECT_ROOT / "src" / "salesreport" / "dashboard" / "app.py")


def _login(monkeypatch, built, username: str, password: str):
    from streamlit.testing.v1 import AppTest

    monkeypatch.setenv("SALESREPORT_OUTPUT_DIR", str(built.dataset_dir.parent))
    monkeypatch.setenv("SALESREPORT_MAINTENANCE", "0")
    at = AppTest.from_file(APP, default_timeout=60)
    at.run()
    at.text_input(key="login_user").input(username)
    at.text_input(key="login_password").input(password)
    at.button(key="login_submit").click().run()
    assert not at.exception
    return at


def test_app_overview_for_regional_manager(monkeypatch, built):
    at = _login(monkeypatch, built, "regional", "demo-regional")
    labels = [m.label for m in at.metric]
    assert labels == ["Renewals", "Digital renewals", "Digital share", "Digital share excl. C&C"]
    renewals = int(at.metric[0].value.replace(",", ""))
    assert renewals == int(built.v4.renewals["renewals"].sum())
    for page in ("Leaderboard", "Agent detail", "Channel mix", "Data quality", "How it evolved"):
        at.sidebar.radio(key="page").set_value(page).run()
        assert not at.exception, page


def test_app_employee_cannot_reach_data_quality(monkeypatch, built):
    at = _login(monkeypatch, built, "northgate.employee", "demo-northgate")
    assert "Data quality" not in at.sidebar.radio(key="page").options
    renewals = int(at.metric[0].value.replace(",", ""))
    shop = built.v4.block_rows().set_index("block_id").loc["SH01", "renewals"]
    assert renewals == shop


def test_app_maintenance_mode(monkeypatch, built):
    from streamlit.testing.v1 import AppTest

    monkeypatch.setenv("SALESREPORT_MAINTENANCE", "1")
    at = AppTest.from_file(APP, default_timeout=60)
    at.run()
    assert "Refreshing data" in at.info[0].value
    assert len(at.text_input) == 0
