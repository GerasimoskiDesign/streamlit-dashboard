"""Session fixtures: one synthetic dataset and one full build shared by the slow tests."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from salesreport.generator import GenerationResult, GeneratorConfig, generate
from salesreport.report.build import BuildOutputs, build
from salesreport.settings import PROJECT_ROOT

AS_OF = date(2026, 9, 17)
OVERRIDES = PROJECT_ROOT / "config" / "overrides.csv"


@pytest.fixture(scope="session")
def generated(tmp_path_factory: pytest.TempPathFactory) -> tuple[GenerationResult, Path]:
    """Default generator config (Jul-Sep 2026, seed 42) written to a temp folder."""
    data_dir = tmp_path_factory.mktemp("data")
    return generate(GeneratorConfig(), data_dir), data_dir


@pytest.fixture(scope="session")
def built(generated, tmp_path_factory: pytest.TempPathFactory) -> BuildOutputs:
    """``build 17.09.2026`` on the synthetic data (lock checked, preflight run)."""
    _, data_dir = generated
    out_dir = tmp_path_factory.mktemp("output")
    return build(AS_OF, data_dir, out_dir, overrides_path=OVERRIDES)


@pytest.fixture(scope="session")
def loaded(generated):
    """All sources for the whole generated range plus master data."""
    from salesreport.inputs.files import load_overrides
    from salesreport.inputs.loader import load_master, load_sources

    result, data_dir = generated
    cfg = result.config
    return (
        load_sources(data_dir, cfg.start, cfg.end, load_overrides(OVERRIDES)),
        load_master(data_dir),
    )
