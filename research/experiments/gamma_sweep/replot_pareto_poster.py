"""
replot_pareto_poster.py -- poster-legible redraw of the equity frontier.

Reads the SAVED sweep in pareto_frontier.json (no re-solve, so the numbers stay
identical to the ones in the report) and redraws it with larger type and
collision-free labels. Writes pareto_frontier_poster.png; the paper's
pareto_frontier.png is left untouched.
"""
from __future__ import annotations
import json
from pathlib import Path
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

HERE = Path(__file__).resolve().parent
d = json.loads((HERE / "pareto_frontier.json").read_text())
rows, others = d["rows"], d["others"]

MK = {"random_preference": ("#7f7f7f", "Random-preference", (-12, -6), "right"),
      "unweighted":        ("#c7c7c7", "Unweighted",        (-12,  6), "right"),
      "need_only":         ("#E1812C", "Need-only",         ( 14,  0), "left"),
      "access_only":       ("#9467bd", "Access-only",       ( 14,  0), "left")}
# per-gamma label nudges; gamma=0 is pushed down so it clears the Unweighted marker
GOFF = {0.0: ((0, -24), "center"), 0.25: ((10, 6), "left"), 0.5: ((12, -4), "left"),
        1.0: ((0, 13), "center"), 2.0: ((-4, 12), "right"), 3.0: ((-4, -17), "right")}
# 0.75 and 1.5 sit inside the crowded knee; their points are plotted but unlabeled
SKIP = {0.75, 1.5}

fig, ax = plt.subplots(figsize=(10.5, 7.2))
xs = [r["served"] for r in rows]
ys = [r["high_need_cov"] for r in rows]
ax.plot(xs, ys, "-o", color="#2ca02c", lw=3.2, markersize=11, zorder=3,
        label=r"Need-access, $\gamma$ sweep")

for r in rows:
    if r["gamma"] in SKIP:
        continue
    off, ha = GOFF[r["gamma"]]
    ax.annotate(rf"$\gamma$={r['gamma']:g}", (r["served"], r["high_need_cov"]),
                xytext=off, textcoords="offset points", fontsize=13,
                color="#1a661a", ha=ha, fontweight="bold")

for k, (sv, tc) in others.items():
    c, lab, off, ha = MK[k]
    ax.scatter([sv], [tc], c=c, s=330, marker="D", edgecolor="k",
               linewidth=1.4, zorder=4, label=lab)
    ax.annotate(lab, (sv, tc), xytext=off, textcoords="offset points",
                fontsize=13, ha=ha, va="center")

ax.set_xlim(168, 250)
ax.set_ylim(20, 72)   # headroom so the legend clears every marker
ax.set_xlabel("breadth  $\\rightarrow$  recipient agencies served", fontsize=16, labelpad=10)
ax.set_ylabel("equity  $\\rightarrow$  high-need tier coverage (%)", fontsize=16, labelpad=10)
ax.set_title("The equity dial traces a tradeoff curve\n"
             "(the four fixed strategies shown as reference points)",
             fontweight="bold", fontsize=17, pad=14)
ax.tick_params(labelsize=14)
ax.grid(alpha=0.3, ls=":")
ax.spines[["top", "right"]].set_visible(False)
ax.legend(fontsize=13, loc="upper left", ncol=2, framealpha=0.95)

fig.tight_layout()
fig.savefig(HERE / "pareto_frontier_poster.png", dpi=200, bbox_inches="tight")
print("[plot] wrote pareto_frontier_poster.png")
