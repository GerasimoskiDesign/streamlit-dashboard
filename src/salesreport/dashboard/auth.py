"""Demo authentication: bcrypt-hashed users from a TOML file.

Good enough to demonstrate role-based access; a production deployment would sit behind
the company's single sign-on and map SSO groups to the same three roles.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path

import bcrypt

from salesreport.dashboard.access import Role, User

_DUMMY_HASH = bcrypt.hashpw(b"timing-equaliser", bcrypt.gensalt(rounds=12))


@dataclass(frozen=True)
class StoredUser:
    """A user record including the password hash (never leaves this module)."""

    user: User
    password_hash: bytes


def load_users(path: Path) -> dict[str, StoredUser]:
    """Read and validate the user file."""
    with path.open("rb") as handle:
        raw = tomllib.load(handle)
    users: dict[str, StoredUser] = {}
    for username, entry in raw.get("users", {}).items():
        role = Role(entry["role"])
        region = entry.get("region")
        shop_id = entry.get("shop_id")
        if role in (Role.SHOP_MANAGER, Role.EMPLOYEE) and not region:
            raise ValueError(f"user {username}: region is required for {role.value}")
        if role is Role.EMPLOYEE and not shop_id:
            raise ValueError(f"user {username}: shop_id is required for employees")
        users[username] = StoredUser(
            user=User(
                username=username,
                display_name=entry.get("display_name", username),
                role=role,
                region=region,
                shop_id=shop_id,
            ),
            password_hash=entry["password_hash"].encode(),
        )
    return users


def authenticate(username: str, password: str, users: dict[str, StoredUser]) -> User | None:
    """Return the user if the password matches its bcrypt hash, else ``None``."""
    stored = users.get((username or "").strip().lower())
    if stored is None or not password:
        # Still spend the time of a bcrypt check so unknown usernames are not faster.
        bcrypt.checkpw(b"x", _DUMMY_HASH)
        return None
    if bcrypt.checkpw(password.encode(), stored.password_hash):
        return stored.user
    return None
