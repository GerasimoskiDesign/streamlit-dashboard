"""Entry point for hosted demos (e.g. Streamlit Community Cloud).

A hosted app starts from a clean checkout with no generated data. On first start this
wrapper runs the *engine* (generator + build) once into a temp folder, then starts the
normal dashboard. The dashboard itself still only reads the engine's Parquet output.
Locally, `python -m salesreport dashboard` is the usual way in.
"""

from __future__ import annotations

import os
import runpy
import tempfile
from datetime import date
from pathlib import Path

import streamlit as st

from salesreport import settings
from salesreport.dashboard.data import dataset_available

APP = Path(__file__).parent / "src" / "salesreport" / "dashboard" / "app.py"
DEMO_DATE = date(2026, 9, 17)


@st.cache_resource(show_spinner="Preparing synthetic demo data (first start only)...")
def prepare_demo_data() -> str:
    """Generate and build once per server process; returns the output folder."""
    from salesreport.generator import GeneratorConfig, generate
    from salesreport.report.build import build

    base = Path(tempfile.gettempdir()) / "salesreport-demo"
    data_dir, out_dir = base / "data", base / "output"
    if not dataset_available(out_dir / "dashboard"):
        generate(GeneratorConfig(), data_dir)
        build(DEMO_DATE, data_dir, out_dir, overrides_path=settings.overrides_file())
    return str(out_dir)


if not dataset_available(settings.output_dir() / "dashboard"):
    os.environ["SALESREPORT_OUTPUT_DIR"] = prepare_demo_data()

runpy.run_path(str(APP), run_name="__main__")
