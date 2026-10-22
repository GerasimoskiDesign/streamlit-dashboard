"""Static README charts, rendered from the dashboard dataset (``python -m salesreport charts``)."""

from __future__ import annotations

import json
import logging
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

from salesreport.report.dataset import FILES

log = logging.getLogger(__name__)
logging.getLogger("matplotlib").setLevel(logging.WARNING)

SURFACE = "#fcfcfb"
INK = "#0b0b0b"
INK_2 = "#52514e"
MUTED = "#898781"
GRID = "#e1e0d9"
V3 = "#eb6834"
V4 = "#2a78d6"
NEUTRAL = "#c3c2b7"
CC = "#1baf7a"


def _style(ax: plt.Axes) -> None:
    ax.set_facecolor(SURFACE)
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color(NEUTRAL)
    ax.tick_params(colors=INK_2, labelsize=9)
    ax.grid(axis="x", color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)


def v3_vs_v4_chart(evolution: pd.DataFrame, path: Path) -> Path:
    """Symptoms under v3 vs v4 on the same month-to-date inputs (v4 must be all zero)."""
    rows = evolution.set_index("version")
    panels = [
        [
            ("Agents above 100 %\ndigital share", "agents_over_100"),
            ("Shops above 100 %\ndigital share", "shops_over_100"),
            ("Shops/channels where agent\nrows != shop row", "mismatched_blocks"),
        ],
        [("Same sale counted\nmore than once", "double_counted")],
    ]
    fig, axes = plt.subplots(
        1, 2, figsize=(10, 3.6), gridspec_kw={"width_ratios": [3, 1.3]}, facecolor=SURFACE
    )
    for ax, metrics in zip(axes, panels, strict=True):
        labels = [m[0] for m in metrics]
        y = range(len(metrics))
        v3 = [float(rows.loc["v3", m[1]]) for m in metrics]
        v4 = [float(rows.loc["v4", m[1]]) for m in metrics]
        height = 0.36
        ax.barh(
            [i - height / 2 - 0.02 for i in y], v3, height, color=V3, label="v3 prototype at scale"
        )
        ax.barh(
            [i + height / 2 + 0.02 for i in y], v4, height, color=V4, label="v4 event-level engine"
        )
        top = max([*v3, 1.0])
        for i, (a, b) in enumerate(zip(v3, v4, strict=True)):
            ax.text(
                a + top * 0.02,
                i - height / 2 - 0.02,
                f"{a:,.0f}",
                va="center",
                fontsize=9,
                color=INK,
            )
            ax.text(
                b + top * 0.02,
                i + height / 2 + 0.02,
                f"{b:,.0f}",
                va="center",
                fontsize=9,
                color=INK,
            )
        ax.set_yticks(list(y), labels)
        ax.invert_yaxis()
        ax.set_xlim(0, top * 1.18)
        _style(ax)
    handles, labels = axes[0].get_legend_handles_labels()
    fig.legend(
        handles,
        labels,
        loc="upper left",
        bbox_to_anchor=(0.005, 0.90),
        ncols=2,
        frameon=False,
        fontsize=9,
    )
    fig.suptitle(
        "Same synthetic inputs, two logics: the v3 symptoms are gone in v4",
        x=0.01,
        ha="left",
        fontsize=12,
        color=INK,
        fontweight="bold",
    )
    fig.text(
        0.01,
        0.01,
        "Synthetic data, month to date. Source: python -m salesreport build",
        fontsize=8,
        color=MUTED,
    )
    fig.tight_layout(rect=(0, 0.04, 1, 0.84))
    fig.savefig(path, dpi=150, facecolor=SURFACE)
    plt.close(fig)
    return path


def channel_mix_chart(daily: pd.DataFrame, month: str, path: Path) -> Path:
    """Daily renewals split into non-digital, digital excl. C&C and C&C-only."""
    data = (
        daily.loc[daily["month"] == month]
        .groupby("date")[["renewals", "digital_excl_cc", "cc_only"]]
        .sum()
    )
    data["non_digital"] = data["renewals"] - data["digital_excl_cc"] - data["cc_only"]
    fig, ax = plt.subplots(figsize=(10, 3.6), facecolor=SURFACE)
    labels = [d.strftime("%d.%m") for d in pd.to_datetime(data.index)]
    x = list(range(len(labels)))
    gap = dict(edgecolor=SURFACE, linewidth=1.2)
    ax.bar(x, data["digital_excl_cc"], color=V4, label="Digital excl. click & collect", **gap)
    ax.bar(
        x,
        data["cc_only"],
        bottom=data["digital_excl_cc"],
        color=CC,
        label="Digital only via click & collect",
        **gap,
    )
    ax.bar(
        x,
        data["non_digital"],
        bottom=data["digital_excl_cc"] + data["cc_only"],
        color=NEUTRAL,
        label="Not digital",
        **gap,
    )
    _style(ax)
    ax.grid(axis="x", visible=False)
    ax.grid(axis="y", color=GRID, linewidth=0.8)
    ax.set_xticks(x, labels)
    ax.tick_params(axis="x", labelrotation=0, labelsize=8)
    ax.set_ylabel("Renewals per day", color=INK_2, fontsize=9)
    ax.legend(loc="upper left", frameon=False, fontsize=9, ncols=3)
    ax.set_ylim(0, data["renewals"].max() * 1.22)
    fig.suptitle(
        "Each renewal counted once: digital is a property of the renewal, not an extra row",
        x=0.01,
        ha="left",
        fontsize=12,
        color=INK,
        fontweight="bold",
    )
    fig.text(
        0.01,
        0.01,
        "Synthetic data. The campaign week (3x volume) is visible mid-month.",
        fontsize=8,
        color=MUTED,
    )
    fig.tight_layout(rect=(0, 0.04, 1, 0.93))
    fig.savefig(path, dpi=150, facecolor=SURFACE)
    plt.close(fig)
    return path


def render_charts(dataset_dir: Path, out_dir: Path) -> list[Path]:
    """Render all README charts from an existing dataset."""
    out_dir.mkdir(parents=True, exist_ok=True)
    meta = json.loads((dataset_dir / FILES["meta"]).read_text(encoding="utf-8"))
    evolution = pd.read_parquet(dataset_dir / FILES["evolution"])
    daily = pd.read_parquet(dataset_dir / FILES["daily"])
    month = meta["period_start"][:7]
    paths = [
        v3_vs_v4_chart(evolution, out_dir / "v3_vs_v4.png"),
        channel_mix_chart(daily, month, out_dir / "channel_mix.png"),
    ]
    for p in paths:
        log.info("wrote %s", p)
    return paths
