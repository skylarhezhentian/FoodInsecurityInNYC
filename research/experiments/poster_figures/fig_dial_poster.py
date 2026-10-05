"""
fig_dial_poster.py -- the poster centerpiece: every strategy on two axes that no
objective optimizes directly.

  x = breadth: recipient agencies served
  y = high-need tier coverage: % of demand served in the neediest third of
      neighborhoods (need_t == 2). Uses need only, no weight w and no access.

Points are MEDIANS of the replicate solves in replicates.json; whiskers show the
min-max range. The green curve is need-access as gamma rises; its gamma=0 end IS the
Unweighted strategy (identical model), so the two can no longer disagree.

No legend: every point is labeled directly. Drawn at poster column width so
matplotlib points equal printed points.

Out: fig_dial_poster.png
"""
from pathlib import Path
import json
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager
# Times New Roman to match the poster's Times text (Termes). The figure is a raster,
# so the Mac's own Times New Roman is baked in and needs nothing on Overleaf.
_TNR = "/System/Library/Fonts/Supplemental/"
for _f in ("Times New Roman.ttf", "Times New Roman Bold.ttf",
           "Times New Roman Italic.ttf", "Times New Roman Bold Italic.ttf"):
    font_manager.fontManager.addfont(_TNR + _f)
plt.rcParams.update({"font.family": "serif", "font.serif": ["Times New Roman"],
                     "mathtext.fontset": "stix"})

HERE = Path(__file__).resolve().parent
COL_W_IN = 36 / 2.54
GREEN = "#1b7837"
FIXED = {"Random-preference": ("#7f7f7f", "Random-preference"),
         "Need-only":         ("#e08214", "Need-only"),
         "Access-only":       ("#8073ac", "Access-only")}


def med(sm, m):  return sm[m]["median"]
def lo(sm, m):   return sm[m]["median"] - sm[m]["min"]
def hi(sm, m):   return sm[m]["max"] - sm[m]["median"]


def main(label_offsets=None):
    d = json.loads((HERE / "replicates.json").read_text())["settings"]
    gam = sorted((v["gamma"], v["summary"]) for v in d.values()
                 if v["gamma"] is not None and v["summary"])

    fig, ax = plt.subplots(figsize=(COL_W_IN, COL_W_IN * 0.66))

    # Label positions in DATA coordinates. The plateau points (gamma >= 0.75) land within
    # a few sites and ~1.5 points of each other, so their labels are fanned into the
    # empty upper-left on leader lines. Top-to-bottom order follows the points'
    # x-position right-to-left, which keeps the leaders from crossing.
    L = {
        0.0:  (224.0, 33.0, "center", True,  "γ = 0  (Unweighted)"),
        0.25: (190.0, 38.2, "right",  False, "γ = 0.25"),
        0.5:  (177.8, 40.4, "right",  False, "γ = 0.5"),
        # gamma = 1 is the Table 1 point: labeled on its own, below-right of the cluster
        1.0:  (189.0, 42.6, "left",   True,  "γ = 1  (Need-access)"),
        3.0:  (166.0, 58.5, "left",   True,  "γ = 3"),
        1.5:  (166.0, 55.5, "left",   True,  "γ = 1.5"),
        2.0:  (166.0, 52.5, "left",   True,  "γ = 2"),
        0.75: (166.0, 49.5, "left",   True,  "γ = 0.75"),
        "Need-only":         (216.0, 57.7, "left",   False, "Need-only"),
        "Access-only":       (200.0, 22.4, "left",   False, "Access-only"),
        "Random-preference": (224.0, 19.6, "center", True,  "Random-preference"),
    }
    if label_offsets:
        L.update(label_offsets)

    def label(key, x, y, color, size):
        tx, ty, ha, leader, text = L[key]
        kw = dict(fontsize=size, color=color, fontweight="bold", ha=ha, va="center", zorder=7)
        if leader:
            kw["arrowprops"] = dict(arrowstyle="-", color=color, lw=1.4, alpha=0.75,
                                    shrinkA=5, shrinkB=11)
        ax.annotate(text, (x, y), xytext=(tx, ty), textcoords="data", **kw)

    # ---- need-access gamma curve ---------------------------------------------
    xs = [med(s, "served") for _, s in gam]
    ys = [med(s, "high_need_pct") for _, s in gam]
    ax.errorbar(xs, ys,
                xerr=[[lo(s, "served") for _, s in gam], [hi(s, "served") for _, s in gam]],
                yerr=[[lo(s, "high_need_pct") for _, s in gam], [hi(s, "high_need_pct") for _, s in gam]],
                fmt="none", ecolor=GREEN, alpha=0.25, elinewidth=1.8, capsize=0, zorder=2)
    ax.plot(xs, ys, "-o", color=GREEN, lw=4, ms=15, zorder=3,
            markeredgecolor="white", markeredgewidth=1.8)
    for (g, _), x, y in zip(gam, xs, ys):
        label(g, x, y, GREEN, 17)

    # ---- the three fixed strategies --------------------------------------------
    for key, (col, name) in FIXED.items():
        if key not in d or not d[key]["summary"]:
            continue
        s = d[key]["summary"]
        x, y = med(s, "served"), med(s, "high_need_pct")
        ax.errorbar([x], [y], xerr=[[lo(s, "served")], [hi(s, "served")]],
                    yerr=[[lo(s, "high_need_pct")], [hi(s, "high_need_pct")]],
                    fmt="none", ecolor=col, alpha=0.4, elinewidth=2.0, capsize=0, zorder=2)
        ax.scatter([x], [y], s=620, marker="D", c=col, edgecolor="#222",
                   linewidth=1.8, zorder=4)
        label(key, x, y, col, 19)

    ax.set_xlabel("breadth: recipient agencies served  →", fontsize=20, labelpad=10)
    ax.set_ylabel("high-need tier coverage (%)  →", fontsize=20, labelpad=10)
    ax.tick_params(labelsize=17)
    ax.grid(alpha=0.3, ls=":", lw=1.2)
    ax.spines[["top", "right"]].set_visible(False)
    ax.set_xlim(163, 246)
    ax.set_ylim(17.5, 61.5)

    fig.tight_layout()
    out = HERE / "fig_dial_poster.png"
    fig.savefig(out, dpi=200, bbox_inches="tight"); plt.close(fig)
    print("[plot] wrote", out)
    return gam, d


if __name__ == "__main__":
    main()
