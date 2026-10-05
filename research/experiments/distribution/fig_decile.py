"""
fig_decile.py -- coverage by need decile, five strategies.

Reads distributional_metrics.json (produced by distributional_metrics.py) and plots
% of demand served in each equal-count need decile. Unlike need-weighted coverage,
this metric does not involve the equity weight w, so no strategy optimizes it directly.

Out: fig_decile.png
"""
from __future__ import annotations
import json
from pathlib import Path
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

HERE = Path(__file__).resolve().parent
ORDER = ["unweighted", "random_preference", "need_only", "access_only", "equity"]
PRETTY = {"unweighted": "Unweighted", "random_preference": "Random-preference",
          "need_only": "Need-only", "access_only": "Access-only",
          "equity": "Need-access (equity)"}
PCOLOR = {"unweighted": "#c7c7c7", "random_preference": "#7f7f7f",
          "need_only": "#E1812C", "access_only": "#9467bd", "equity": "#2ca02c"}
MARK = {"unweighted": "o", "random_preference": "s", "need_only": "^",
        "access_only": "D", "equity": "*"}

d = json.loads((HERE / "distributional_metrics.json").read_text())
block = d["modes"]["mode_A"]
x = list(range(1, 11))

fig, ax = plt.subplots(figsize=(12, 5.0))
for pol in ORDER:
    y = block[pol]["coverage_by_need_decile_pct"]
    lw, ms, z = (4.0, 20, 5) if pol in ("equity", "need_only") else (2.6, 12, 3)
    ax.plot(x, y, marker=MARK[pol], markersize=ms, linewidth=lw, zorder=z,
            color=PCOLOR[pol], label=PRETTY[pol],
            markeredgecolor="white", markeredgewidth=1.2)

ax.set_xticks(x)
ax.set_xlabel("Recipient need decile  (1 = lowest need,  10 = highest need)",
              fontsize=17, labelpad=10)
ax.set_ylabel("Demand served (%)", fontsize=17, labelpad=10)
ax.set_title("Who actually gets served, by neighborhood need\n"
             "(a metric no strategy optimizes directly)",
             fontsize=19, fontweight="bold", pad=14)
ax.tick_params(labelsize=15)
ax.set_ylim(-3, 103)
ax.grid(axis="y", alpha=0.3, linewidth=1.0)
ax.spines[["top", "right"]].set_visible(False)
ax.legend(fontsize=14, loc="upper left", frameon=True, framealpha=0.95, ncol=2)

fig.tight_layout()
fig.savefig(HERE / "fig_decile.png", dpi=200, bbox_inches="tight")
print("[plot] wrote fig_decile.png")
