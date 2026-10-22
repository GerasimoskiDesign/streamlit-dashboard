"""Seeded synthetic data generator (``python -m salesreport generate``).

See data/GENERATOR.md for everything that is injected and why.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from salesreport.dates import fmt
from salesreport.generator.events import GeneratorConfig, Simulator
from salesreport.generator.master import MasterData, build_master
from salesreport.generator.writer import write_daily, write_manual_count, write_master

log = logging.getLogger(__name__)

__all__ = ["GenerationResult", "GeneratorConfig", "generate", "manual_count_path"]


@dataclass
class GenerationResult:
    """What was generated, including the ground truth used by the tests."""

    config: GeneratorConfig
    master: MasterData
    truth: pd.DataFrame
    expected_audit: pd.DataFrame
    web_no_contract: pd.DataFrame
    manual_differences: dict[str, int]
    files_written: int


def manual_count_path(data_dir: Path, start, end) -> Path:
    """Location of the manual count file for a period."""
    return data_dir / "manual_count" / f"manual_count_{fmt(start)}-{fmt(end)}.xlsx"


def generate(cfg: GeneratorConfig, data_dir: Path) -> GenerationResult:
    """Generate master data, daily exports and the manual count into ``data_dir``."""
    rng = np.random.default_rng(cfg.seed)
    master = build_master(rng, cfg.n_shops, cfg.n_agents)
    sim = Simulator(cfg, master, rng).run()
    truth = pd.DataFrame(sim.truth)
    expected = pd.DataFrame(sim.expected_audit).drop_duplicates(["date", "phone", "source"])
    web_no_contract = pd.DataFrame(sim.web_no_contract, columns=["date", "phone"])

    write_master(master, data_dir)
    files = write_daily(cfg, sim, data_dir)

    differences: dict[str, int] = {}
    if cfg.start <= cfg.manual_count_start and cfg.manual_count_end <= cfg.end and len(truth):
        period = truth[
            (truth["date"] >= cfg.manual_count_start) & (truth["date"] <= cfg.manual_count_end)
        ]
        counts = period.groupby("agent").size().astype(int).to_dict()
        # Two honest human slips, so the reconciliation sheet shows what a difference
        # looks like: one duplicate export row counted twice, one late booking missed.
        manual_rng = np.random.default_rng([cfg.seed, 11])
        eligible = sorted(a for a, n in counts.items() if n >= 3) or sorted(counts)
        picks = manual_rng.choice(eligible, 2, replace=False)
        differences = {str(picks[0]): +1, str(picks[1]): -1}
        manual = {a: n + differences.get(a, 0) for a, n in counts.items()}
        write_manual_count(
            manual_count_path(data_dir, cfg.manual_count_start, cfg.manual_count_end),
            manual,
            cfg.manual_count_start,
            cfg.manual_count_end,
        )
    log.info(
        "generated %d renewals, %d expected audit rows, %d files",
        len(truth),
        len(expected),
        files,
    )
    return GenerationResult(
        config=cfg,
        master=master,
        truth=truth,
        expected_audit=expected,
        web_no_contract=web_no_contract,
        manual_differences=differences,
        files_written=files,
    )
