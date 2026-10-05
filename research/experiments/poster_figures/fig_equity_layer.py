"""Layer-1 equity figure: the need/access weighting and its spatial pattern.

Panel A: need_pct vs access_pct scatter, colored by the equity weight w (the
         skip-penalty multiplier), with the w=1 (need=access) diagonal.
Panel B: geographic map of the 528 pantries colored by w -- the "equity access map".

No solving; reads the instance via ch_experiment.load_world. Output: fig_equity_layer.png
"""
from pathlib import Path
import numpy as np
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
import ch_experiment as CHE

HERE = Path(__file__).resolve().parent


def cfg():
    return {"instance": "instance_ch.json", "donors_csv": "data/donors_pickup.csv",
            "cache": "osrm_cache_pickup.npz", "tod": "am_peak", "max_pantries": None,
            "skip_penalty": 8000, "time_limit": 1, "freshness_coef": 1, "decay_coef": 0.03,
            "seed": 42, "staged_frac": 0.4, "start_load_policy": "fixed", "scenarios": 1,
            "prior_age_min": 1440}


def main():
    inst, depots, donors, pantries, P, O, D, time_min = CHE.load_world(cfg())
    need = np.array([p["need_pct"] for p in pantries])
    acc = np.array([p["access_pct"] for p in pantries])
    w = np.array([p["w"] for p in pantries])
    lon = np.array([p["lon"] for p in pantries])
    lat = np.array([p["lat"] for p in pantries])

    fig, axes = plt.subplots(1, 2, figsize=(14, 6), dpi=130)
    # Panel A -- need vs access, colored by weight
    ax = axes[0]
    sc = ax.scatter(acc, need, c=w, cmap="RdYlGn_r", s=20, vmin=0.5, vmax=4.0,
                    edgecolor="k", linewidth=0.2, alpha=0.9)
    ax.plot([0, 1], [0, 1], ls="--", c="#555", lw=1.2, label="need = access (w ≈ 1)")
    ax.set_xlabel("access percentile (E2SFCA)")
    ax.set_ylabel("need percentile (Map the Meal Gap)")
    ax.set_title("A. Priority weight w = (need / access)$^\\gamma$", fontweight="bold")
    ax.set_xlim(0, 1); ax.set_ylim(0, 1)
    ax.annotate("high need / low access\n→ high priority (w→4)", xy=(0.04, 0.96),
                fontsize=9, color="#7a0000", fontweight="bold", va="top")
    ax.annotate("low need / high access\n→ low priority (w→0.5)", xy=(0.60, 0.04),
                fontsize=9, color="#1a661a", fontweight="bold")
    cb = fig.colorbar(sc, ax=ax); cb.set_label("equity weight w (skip-penalty multiplier)")
    ax.legend(loc="lower left", fontsize=9)
    # Panel B -- geographic equity access map
    ax = axes[1]
    sc2 = ax.scatter(lon, lat, c=w, cmap="RdYlGn_r", s=16, vmin=0.5, vmax=4.0,
                     edgecolor="k", linewidth=0.15, alpha=0.9)
    ax.set_aspect(1 / np.cos(np.radians(40.73)))
    for o in depots:
        ax.scatter(o["lon"], o["lat"], s=320, c="#111", marker="*",
                   edgecolor="white", linewidth=1.2, zorder=5)
    ax.set_xticks([]); ax.set_yticks([])
    ax.set_title("B. Priority surface: 528 NYC recipient locations by weight", fontweight="bold")
    cb2 = fig.colorbar(sc2, ax=ax); cb2.set_label("priority weight w")
    ax.legend(handles=[Line2D([0], [0], marker="*", color="w", markerfacecolor="#111",
              markersize=14, label="depot")], loc="lower right", fontsize=9)
    fig.suptitle("Need-access priority surface (gamma = 1)",
                 fontsize=13, fontweight="bold")
    fig.tight_layout()
    out = HERE / "fig_equity_layer.png"
    fig.savefig(out, dpi=140, bbox_inches="tight"); plt.close(fig)
    print("[plot] wrote", out)
    print(f"w: min={w.min():.2f} median={np.median(w):.2f} max={w.max():.2f} "
          f"distinct={len(set(np.round(w,3)))}")
    print(f"corr(need_pct, access_pct) = {np.corrcoef(need, acc)[0,1]:.3f}")
    print(f"share with w>1 (need-tilted): {100*np.mean(w>1):.1f}%  |  w<1: {100*np.mean(w<1):.1f}%")


if __name__ == "__main__":
    main()
