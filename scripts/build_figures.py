#!/usr/bin/env python3
"""Plot every saved benchmark run, plus medians and observed ranges."""

import argparse
import csv
import statistics
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parents[1]
POLICIES = ["unweighted", "random_preference", "need_only", "access_only", "equity"]
LABELS = ["Unweighted", "Random preference", "Need only", "Access only", "Need / access"]
COLORS = ["#5D6B7A", "#9B8570", "#246C83", "#8070A0", "#248C7D"]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results", type=Path, default=ROOT / "results/corrected")
    parser.add_argument("--output", type=Path, default=ROOT / "outputs/figures")
    args = parser.parse_args()
    output = args.output.resolve()
    if not output.is_relative_to((ROOT / "outputs").resolve()):
        parser.error("Generated figures must be written inside outputs/")
    with (args.results / "runs.csv").open(newline="") as stream:
        rows = list(csv.DictReader(stream))
    if len(rows) != 25 or any(r["status"] != "solved" or r["audit_passed"] != "True" for r in rows):
        parser.error("The comparison figure requires all 25 valid runs; inspect any failed runs first")
    groups = [[r for r in rows if r["policy"] == policy] for policy in POLICIES]
    if any(len(group) != 5 or {int(r["replicate_seed"]) for r in group} != set(range(1, 6)) for group in groups):
        parser.error("Expected each of five policies with seeds 1–5 exactly once")
    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 10,
                         "axes.labelcolor": "#344456", "text.color": "#1D2C3E",
                         "xtick.color": "#607080", "ytick.color": "#344456"})
    figure, axes = plt.subplots(1, 2, figsize=(11.2, 4.6), sharey=True)
    for ax, key, title in zip(axes, ["sites_served", "high_need_coverage_pct"],
                              ["Sites served", "High-need demand covered (%)"]):
        for y, (group, color) in enumerate(zip(groups, COLORS)):
            values = [float(r[key]) for r in group]
            median = statistics.median(values)
            ax.hlines(y, min(values), max(values), color=color, linewidth=2, alpha=0.65)
            ax.scatter(values, [y + offset for offset in [-0.06, -0.03, 0, 0.03, 0.06]],
                       s=28, color=color, alpha=0.48, edgecolors="none", zorder=3)
            ax.scatter([median], [y], s=62, marker="D", color=color, edgecolors="white", linewidths=0.8, zorder=4)
            label = f"{median:.0f}" if key == "sites_served" else f"{median:.1f}%"
            ax.annotate(label, (max(values), y), xytext=(9, 0), textcoords="offset points",
                        va="center", fontsize=10, color=color, fontweight="bold")
        ax.set_title(title, loc="left", fontsize=12, pad=15, fontweight="bold")
        upper = max(float(row[key]) for row in rows)
        ax.set_xlim(0, upper * 1.22)
        ax.set_ylim(4.55, -0.65)
        ax.set_yticks(range(5), LABELS)
        ax.tick_params(axis="both", length=0, pad=8)
        ax.grid(axis="x", color="#E6EAEE", linewidth=0.8)
        ax.set_axisbelow(True)
        for spine in ax.spines.values():
            spine.set_visible(False)
    figure.suptitle("Equity priorities change the allocation", x=0.02, y=0.98,
                    ha="left", fontsize=18, fontweight="bold")
    figure.text(0.02, 0.905, "One modeled day · 528 recipient sites · 5 perturbations per policy · 10-second search limit", fontsize=10, color="#607080")
    figure.text(0.02, 0.025, "Circles: individual runs. Diamonds: medians. Lines: observed ranges, not confidence intervals.", fontsize=9, color="#607080")
    figure.subplots_adjust(left=0.175, right=0.97, top=0.75, bottom=0.13, wspace=0.22)
    output.mkdir(parents=True, exist_ok=True)
    figure.savefig(output / "policy_comparison.png", dpi=180, facecolor="white")
    figure.savefig(output / "policy_comparison.svg", facecolor="white")
    plt.close(figure)
    print(f"Wrote comparison figures to {output}")


if __name__ == "__main__":
    main()
