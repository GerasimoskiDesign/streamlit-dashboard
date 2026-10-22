"""Paths and environment-driven settings.

Everything configurable comes from environment variables (optionally loaded from a
local ``.env``) so the same code runs on a laptop, in CI and on a hosted dashboard
without edits. Nothing here is a secret; the pattern is kept so a production
deployment can add real credentials the same way.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[2]

load_dotenv(PROJECT_ROOT / ".env", override=False)


def _path_from_env(name: str, default: Path) -> Path:
    value = os.environ.get(name)
    if not value:
        return default
    path = Path(value)
    return path if path.is_absolute() else (PROJECT_ROOT / path).resolve()


def data_dir() -> Path:
    """Root folder of the synthetic inputs (``daily/``, ``master/``, ``manual_count/``)."""
    return _path_from_env("SALESREPORT_DATA_DIR", PROJECT_ROOT / "data")


def output_dir() -> Path:
    """Folder for the Excel report and the dashboard Parquet dataset."""
    return _path_from_env("SALESREPORT_OUTPUT_DIR", PROJECT_ROOT / "output")


def users_file() -> Path:
    """TOML file with the bcrypt-hashed demo users."""
    return _path_from_env("SALESREPORT_USERS_FILE", PROJECT_ROOT / "config" / "users.toml")


def overrides_file() -> Path:
    """Per-day file override table (see ``inputs/files.py``)."""
    return _path_from_env("SALESREPORT_OVERRIDES_FILE", PROJECT_ROOT / "config" / "overrides.csv")


def maintenance_mode() -> bool:
    """True while the daily recompute runs; the dashboard then shows a notice only."""
    return os.environ.get("SALESREPORT_MAINTENANCE", "0").strip().lower() in {"1", "true", "yes"}
