"""
compare_models.py -- City Harvest 3-model comparison on the SAME network/fleet:

  random       : random delivery-point selection (baseline)
  preferential : size/throughput-weighted selection (favor large agencies)
  equity       : need ÷ access weighted selection (our model)

Same OSRM road-network routing, same 25-truck CH fleet (Brooklyn WH + Hunts Point),
same hard 7-11am windows. We compare WHICH agencies get served and the equity of
the outcome. Outputs comparison_ch.md, compare_models.png, route_map_ch.png.
"""
from __future__ import annotations
import argparse, json, math
from argparse import Namespace
from pathlib import Path
import numpy as np
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D

import solve_routes_v1 as S

HERE = Path(__file__).resolve().parent
MODELS = ["random", "preferential", "equity"]
MCOLOR = {"random": "#9b9b9b", "preferential": "#4C78A8", "equity": "#2ca02c"}


def run_all(args):
    inst = json.loads(Path(args.instance).read_text())
    out = {}
    for m in MODELS:
        a = Namespace(travel=args.travel, congestion=args.congestion, tod=args.tod,
                      freshness_coef=args.freshness_coef, skip_penalty=args.skip_penalty,
                      time_limit=args.time_limit, seed=args.seed, cache=args.cache)
        out[m] = S.solve(inst, a, m)
    return inst, out


def plot_utilization(inst, out, out_png):
    """Deliveries per clock hour -> shows the morning surge tapering later."""
    sh = inst["params"]["shift_start"]
    sh_min = int(sh.split(":")[0]) * 60 + int(sh.split(":")[1])
    fig, ax = plt.subplots(figsize=(11, 5), dpi=130)
    hours = list(range(6, 21))
    w = 0.27
    for i, m in enumerate(MODELS):
        counts = {h: 0 for h in hours}
        for r in out[m]["routes"]:
            for s in r["stop_detail"]:
                h = int((sh_min + s["arrival_min"]) // 60)
                if h in counts:
                    counts[h] += 1
        ax.bar([h + (i-1)*w for h in hours], [counts[h] for h in hours], w,
               color=MCOLOR[m], label=m)
    ax.axvspan(7-0.5, 11-0.5, color="#ffe9b0", alpha=0.5, zorder=0,
               label="City Harvest 7–11am target")
    ax.set_xticks(hours); ax.set_xticklabels([f"{h}" for h in hours])
    ax.set_xlabel("clock hour (delivery arrival)"); ax.set_ylabel("# deliveries")
    ax.set_title("Fleet activity by hour — morning surge, tapering later\n"
                 "(statistical windows: most agencies want 7–11am)",
                 fontsize=12, fontweight="bold")
    ax.legend(); ax.grid(axis="y", alpha=.3, ls=":")
    fig.tight_layout(); fig.savefig(out_png, dpi=140, bbox_inches="tight"); plt.close(fig)
    print(f"[plot] wrote {out_png}")


def plot_bars(out, out_png):
    fig, axes = plt.subplots(1, 2, figsize=(15, 6), dpi=130, gridspec_kw=dict(width_ratios=[1.45, 1]))
    # Left: per-need-tercile coverage, grouped by model
    tiers = ["low-need", "mid-need", "high-need"]
    x = np.arange(3); w = 0.26
    ax = axes[0]
    for i, m in enumerate(MODELS):
        vals = [out[m]["summary"]["coverage_by_tier"][t]["coverage_pct"] for t in (0, 1, 2)]
        b = ax.bar(x + (i-1)*w, vals, w, color=MCOLOR[m], label=m)
        for r in b:
            ax.annotate(f"{r.get_height():.0f}", (r.get_x()+r.get_width()/2, r.get_height()),
                        xytext=(0, 2), textcoords="offset points", ha="center", fontsize=8.5)
    ax.set_xticks(x); ax.set_xticklabels(tiers)
    ax.set_ylabel("coverage (% of neighborhood demand met)")
    ax.set_ylim(0, max(60, ax.get_ylim()[1]*1.1))
    ax.set_title("Coverage by need tercile"); ax.legend(); ax.grid(axis="y", alpha=.3, ls=":")
    # Right: summary metrics per model
    ax = axes[1]
    mets = ["need-weighted\ncoverage %", "agencies\nreached", "idle %"]
    xx = np.arange(3)
    for i, m in enumerate(MODELS):
        s = out[m]["summary"]
        # scale agencies to share of NP for comparability on same axis
        vals = [s["need_weighted_coverage_pct"],
                100*s["served"]/s["n_pantries"],
                s["idle_pct"]]
        b = ax.bar(xx + (i-1)*w, vals, w, color=MCOLOR[m])
        for r in b:
            ax.annotate(f"{r.get_height():.0f}", (r.get_x()+r.get_width()/2, r.get_height()),
                        xytext=(0, 2), textcoords="offset points", ha="center", fontsize=8.5)
    ax.set_xticks(xx); ax.set_xticklabels(mets)
    ax.set_ylabel("%"); ax.set_title("Outcome metrics")
    ax.grid(axis="y", alpha=.3, ls=":")
    fig.suptitle("City Harvest delivery: random vs preferential vs equity selection\n"
                 "same 25-truck fleet · OSRM road times · hard 7–11am windows",
                 fontsize=13, fontweight="bold")
    fig.tight_layout(); fig.savefig(out_png, dpi=145, bbox_inches="tight"); plt.close(fig)
    print(f"[plot] wrote {out_png}")


def plot_map(inst, out, out_png):
    origins = inst["origins"]; pantries = inst["pantries"]; O = len(origins)
    fig, axes = plt.subplots(1, 3, figsize=(22, 8.5), dpi=120)
    fig.subplots_adjust(top=0.84, bottom=0.05, left=0.03, right=0.99, wspace=0.05)
    lons=[p["lon"] for p in pantries]; lats=[p["lat"] for p in pantries]
    xlim=(min(lons)-0.02,max(lons)+0.02); ylim=(min(lats)-0.02,max(lats)+0.02)
    for ax, m in zip(axes, MODELS):
        ax.set_xlim(*xlim); ax.set_ylim(*ylim)
        ax.set_aspect(1/math.cos(math.radians(40.73))); ax.set_facecolor("#f7f9fb")
        S._draw_basemap(ax)
        res = out[m]; sset = set(res["served_pantry_idx"]); col = MCOLOR[m]
        for i, p in enumerate(pantries):
            if i not in sset:
                ax.scatter(p["lon"], p["lat"], s=4+10*(p["w"]-0.5), c="#c8c8c8",
                           alpha=0.5, edgecolor="none", zorder=1)
        for r in res["routes"]:
            prev = None
            for s in r["stops"]:
                if s < O: lon,lat = origins[s]["lon"], origins[s]["lat"]
                else:
                    p = pantries[s-O]; lon,lat = p["lon"], p["lat"]
                    ax.scatter(lon, lat, s=10+16*(p["w"]-0.5), c=col, alpha=0.8,
                               edgecolor="white", linewidth=0.3, zorder=3)
                if prev is not None:
                    ax.plot([prev[0],lon],[prev[1],lat], c=col, alpha=0.4, lw=0.8, zorder=2)
                prev = (lon, lat)
        for o in origins:
            ax.scatter(o["lon"], o["lat"], s=360, c="#111", marker="*",
                       edgecolor="white", linewidth=1.2, zorder=5)
        s = res["summary"]
        ax.set_title(f"{m}\nserved {s['served']}  ·  need-wtd {s['need_weighted_coverage_pct']}%  ·  "
                     f"high-need {s['coverage_by_tier'][2]['coverage_pct']}%",
                     fontsize=12, color=col, fontweight="bold")
        ax.set_xticks([]); ax.set_yticks([])
    fig.legend(handles=[Line2D([0],[0],marker="*",color="w",markerfacecolor="#111",
               markeredgecolor="white",markersize=14,label="City Harvest depot (Brooklyn WH + Hunts Point)")],
               loc="upper center", bbox_to_anchor=(0.5,0.93), fontsize=10)
    fig.suptitle("City Harvest delivery routes — which agencies get reached, by selection rule "
                 "(OSRM road network · 7–11am windows)", y=0.985, fontsize=14, fontweight="bold")
    fig.savefig(out_png, dpi=140, bbox_inches="tight"); plt.close(fig)
    print(f"[plot] wrote {out_png}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--instance", default="instance_ch.json")
    ap.add_argument("--cache", default="osrm_cache_ch.npz")
    ap.add_argument("--travel", default="osrm")
    ap.add_argument("--congestion", type=float, default=0.42)
    ap.add_argument("--tod", default="am_peak",
                    choices=["am_peak", "midday", "pm_peak", "night"],
                    help="Time-of-day congestion band (morning-dominant -> am_peak).")
    ap.add_argument("--freshness-coef", type=int, default=1)
    ap.add_argument("--skip-penalty", type=int, default=5000)
    ap.add_argument("--time-limit", type=int, default=40)
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    inst, out = run_all(args)
    plot_bars(out, HERE / "compare_models.png")
    plot_map(inst, out, HERE / "route_map_ch.png")
    plot_utilization(inst, out, HERE / "fleet_utilization.png")
    Path(HERE / "routes_ch.json").write_text(json.dumps(
        {m: {"summary": out[m]["summary"], "served_pantry_idx": out[m]["served_pantry_idx"]}
         for m in MODELS}, indent=2))

    # comparison table
    L = ["# City Harvest model comparison (OSRM, 7–11am windows, 25 trucks)\n",
         "| metric | random | preferential | equity |", "|---|---:|---:|---:|"]
    def row(lbl, key):
        return f"| {lbl} | " + " | ".join(f"{out[m]['summary'][key]}" for m in MODELS) + " |"
    L.append(row("agencies reached", "served"))
    L.append(row("total delivered (lbs)", "total_delivered_lbs"))
    L.append(row("flat coverage %", "flat_coverage_pct"))
    L.append("| **need-weighted coverage %** | " +
             " | ".join(f"**{out[m]['summary']['need_weighted_coverage_pct']}**" for m in MODELS) + " |")
    for t,lbl in [(0,"low-need %"),(1,"mid-need %"),(2,"high-need %")]:
        L.append(f"| {lbl} | " + " | ".join(
            f"{out[m]['summary']['coverage_by_tier'][t]['coverage_pct']}" for m in MODELS) + " |")
    L.append(row("cold-chain coverage %", "cold_coverage_pct"))
    L.append(row("total travel (min)", "total_travel_min"))
    L.append(row("idle %", "idle_pct"))
    table = "\n".join(L)
    Path(HERE / "comparison_ch.md").write_text(table + "\n")
    print("\n" + table)


if __name__ == "__main__":
    main()
