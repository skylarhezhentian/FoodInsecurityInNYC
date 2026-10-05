"""
fig_equity_layer_poster.py -- poster-legible redraw of the priority surface.

Changes from fig_equity_layer.py (the paper figure, left untouched):
  * colorblind-safe diverging palette (RdBu_r) centered on w = 1, where need equals
    access; the old RdYlGn relied on red-green contrast
  * color range fitted to the actual weights (0.5 to ~3) instead of the clip bound 4
  * type sized for print: the figure is drawn at poster column width (36 cm), so
    matplotlib points equal printed points
  * borough outlines under the map, and a larger map panel
  * need axis labeled MOFP/HRA to match the poster text

Out: fig_equity_layer_poster.png
"""
from pathlib import Path
import json
import numpy as np
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
from matplotlib.colors import TwoSlopeNorm
from matplotlib.lines import Line2D
import ch_experiment as CHE
from fig_equity_layer import cfg

HERE = Path(__file__).resolve().parent
BOROUGHS = HERE.parents[2] / "data/upstream/donor_model/data/nyc_boroughs.geojson"
COL_W_IN = 36 / 2.54          # poster column width: 1 matplotlib pt == 1 printed pt
CMAP = "RdBu_r"


def draw_boroughs(ax):
    """Draw borough outlines; return their (lon_min, lon_max, lat_min, lat_max)."""
    g = json.loads(BOROUGHS.read_text())
    xs, ys = [], []
    for f in g["features"]:
        for poly in f["geometry"]["coordinates"]:
            ring = np.array(poly[0])
            ax.fill(ring[:, 0], ring[:, 1], color="#f1f1f1", zorder=0, lw=0)
            ax.plot(ring[:, 0], ring[:, 1], color="#9a9a9a", lw=1.1, zorder=1)
            xs.append(ring[:, 0]); ys.append(ring[:, 1])
    xs, ys = np.concatenate(xs), np.concatenate(ys)
    return xs.min(), xs.max(), ys.min(), ys.max()


def main():
    inst, depots, donors, pantries, P, O, D, time_min = CHE.load_world(cfg())
    need = np.array([p["need_pct"] for p in pantries])
    acc = np.array([p["access_pct"] for p in pantries])
    w = np.array([p["w"] for p in pantries])
    lon = np.array([p["lon"] for p in pantries])
    lat = np.array([p["lat"] for p in pantries])
    norm = TwoSlopeNorm(vmin=0.5, vcenter=1.0, vmax=float(np.ceil(w.max() * 2) / 2))

    fig = plt.figure(figsize=(COL_W_IN, COL_W_IN * 0.52))
    gs = fig.add_gridspec(1, 3, width_ratios=[1, 1.18, 0.05], wspace=0.28)
    axA, axB, cax = fig.add_subplot(gs[0]), fig.add_subplot(gs[1]), fig.add_subplot(gs[2])

    # ---- Panel A: need vs access -------------------------------------------------
    axA.scatter(acc, need, c=w, cmap=CMAP, norm=norm, s=46,
                edgecolor="#333", linewidth=0.4, alpha=0.95)
    axA.plot([0, 1], [0, 1], ls="--", c="#444", lw=1.8)
    axA.text(0.80, 0.93, "need = access\n($w$ = 1)", fontsize=15, color="#444",
             ha="center", va="top", zorder=6, bbox=dict(boxstyle="round,pad=0.25", fc="white", ec="none", alpha=0.85))
    axA.set_xlim(0, 1); axA.set_ylim(0, 1)
    axA.set_xlabel("access percentile (E2SFCA)", fontsize=19, labelpad=8)
    axA.set_ylabel("need percentile (MOFP/HRA)", fontsize=19, labelpad=8)
    axA.set_title("A.  Weight  $w = (N/A)^{\\gamma}$", fontsize=21,
                  fontweight="bold", loc="left", pad=12)
    axA.tick_params(labelsize=16)
    axA.text(0.03, 0.97, "high need,\nlow access", transform=axA.transAxes,
             fontsize=16, fontweight="bold", color="#b2182b", va="top", zorder=6,
             bbox=dict(boxstyle="round,pad=0.25", fc="white", ec="none", alpha=0.85))
    axA.text(0.97, 0.03, "low need,\nhigh access", transform=axA.transAxes,
             fontsize=16, fontweight="bold", color="#2166ac", ha="right", zorder=6,
             bbox=dict(boxstyle="round,pad=0.25", fc="white", ec="none", alpha=0.85))
    axA.spines[["top", "right"]].set_visible(False)

    # ---- Panel B: the same weights on the map ------------------------------------
    bx0, bx1, by0, by1 = draw_boroughs(axB)
    order = np.argsort(np.abs(np.log(w)))            # draw extreme weights on top
    sc = axB.scatter(lon[order], lat[order], c=w[order], cmap=CMAP, norm=norm, s=40,
                     edgecolor="#333", linewidth=0.4, alpha=0.95, zorder=3)
    for o in depots:
        axB.scatter(o["lon"], o["lat"], s=520, c="#111", marker="*",
                    edgecolor="white", linewidth=1.6, zorder=5)
    axB.set_aspect(1 / np.cos(np.radians(40.73)))
    axB.set_xlim(bx0 - 0.01, bx1 + 0.01)
    axB.set_ylim(by0 - 0.01, by1 + 0.01)
    axB.set_xticks([]); axB.set_yticks([])
    for sp in axB.spines.values():
        sp.set_visible(False)
    axB.set_title("B.  The same weights, mapped", fontsize=21,
                  fontweight="bold", loc="left", pad=12)
    axB.legend(handles=[Line2D([0], [0], marker="*", color="w", markerfacecolor="#111",
               markeredgecolor="white", markersize=22, label="depot")],
               loc="upper left", fontsize=16, frameon=False)

    cb = fig.colorbar(sc, cax=cax, ticks=[0.5, 1, 1.5, 2, 2.5, 3])
    cb.set_label("priority weight $w$", fontsize=18, labelpad=10)
    cb.ax.tick_params(labelsize=15)

    out = HERE / "fig_equity_layer_poster.png"
    fig.savefig(out, dpi=200, bbox_inches="tight"); plt.close(fig)
    print("[plot] wrote", out)
    print(f"w range {w.min():.2f}-{w.max():.2f}, norm vmax {norm.vmax}")


if __name__ == "__main__":
    main()
