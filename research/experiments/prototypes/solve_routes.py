"""
solve_routes.py -- Multi-depot CVRP for the NYC food-rescue instance.

Solver: OR-Tools (constraint_solver.routing). 20 vehicles, 5 origin depots
(4 vehicles each). Each pantry is a delivery node; the solver chooses which
pantries to serve and which to skip (skip penalty = BASE * equity_weight).

Outputs:
  - routes.json     per-vehicle stop sequences
  - route_map.png   map of NYC with origins, served/unserved pantries, and routes
"""
from __future__ import annotations
import argparse, json, math, sys
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.lines import Line2D

from ortools.constraint_solver import pywrapcp
from ortools.constraint_solver import routing_enums_pb2

HERE = Path(__file__).resolve().parent

ORIGIN_COLORS = ["#d62728", "#1f77b4", "#2ca02c", "#9467bd", "#ff7f0e"]


def haversine_km(lon1, lat1, lon2, lat2):
    R = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp/2)**2 + math.cos(p1)*math.cos(p2)*math.sin(dl/2)**2
    return 2 * R * math.asin(math.sqrt(a))


def build_matrices(origins, pantries, speed_kmh, service_min):
    """Return (n, time_min[NxN], dist_km[NxN]) where N = len(origins)+len(pantries).
    Node order: origins first, then pantries.
    """
    O = len(origins); P = len(pantries)
    N = O + P
    lats = [o["lat"] for o in origins] + [p["lat"] for p in pantries]
    lons = [o["lon"] for o in origins] + [p["lon"] for p in pantries]
    dist = np.zeros((N, N), dtype=np.float64)
    time = np.zeros((N, N), dtype=np.int64)
    for i in range(N):
        for j in range(N):
            if i == j:
                continue
            km = haversine_km(lons[i], lats[i], lons[j], lats[j])
            dist[i, j] = km
            # travel + service at destination (service only at pantry deliveries)
            travel = km / speed_kmh * 60.0
            svc = service_min if j >= O else 0
            time[i, j] = int(round(travel + svc))
    return N, time, dist


def solve(instance: dict, args):
    origins = instance["origins"]
    pantries = instance["pantries"]
    vehicles = instance["vehicles"]
    params = instance["params"]
    O = len(origins); P = len(pantries); V = len(vehicles)

    N, time_mat, dist_mat = build_matrices(
        origins, pantries,
        speed_kmh=params["speed_kmh"],
        service_min=params["service_min"],
    )

    # Demands: origins have 0 demand, pantries have demand_lbs.
    demands = [0]*O + [p["demand_lbs"] for p in pantries]
    # Apply CLI overrides (for sensitivity / tight-fleet experiments).
    cap_override = getattr(args, "vehicle_cap_lbs", None)
    shift_override = getattr(args, "shift_min", None)
    capacities = [cap_override or v["capacity_lbs"] for v in vehicles]
    shift_mins = [shift_override or v["shift_min"] for v in vehicles]
    starts = [v["origin_idx"] for v in vehicles]
    ends = list(starts)  # return to origin

    mgr = pywrapcp.RoutingIndexManager(N, V, starts, ends)
    routing = pywrapcp.RoutingModel(mgr)

    # Travel time arc cost (minutes).
    def time_cb(from_idx, to_idx):
        return int(time_mat[mgr.IndexToNode(from_idx), mgr.IndexToNode(to_idx)])
    time_cb_idx = routing.RegisterTransitCallback(time_cb)
    routing.SetArcCostEvaluatorOfAllVehicles(time_cb_idx)

    # Capacity dimension (lbs).
    def demand_cb(from_idx):
        return int(demands[mgr.IndexToNode(from_idx)])
    demand_cb_idx = routing.RegisterUnaryTransitCallback(demand_cb)
    routing.AddDimensionWithVehicleCapacity(
        demand_cb_idx, 0, capacities, True, "Capacity"
    )

    # Time dimension (per-vehicle shift cap).
    routing.AddDimensionWithVehicleCapacity(
        time_cb_idx, 0, shift_mins, True, "Time"
    )

    # Equity-weighted skip penalty. Each pantry node is droppable for a price.
    # mode "uniform": penalty = BASE for everyone; "equity": penalty = BASE * w.
    BASE = args.skip_penalty
    for p_idx, p in enumerate(pantries):
        node = O + p_idx
        if args.mode == "equity":
            penalty = int(round(BASE * p["w"]))
        else:
            penalty = BASE
        routing.AddDisjunction([mgr.NodeToIndex(node)], penalty)

    # Search.
    sp = pywrapcp.DefaultRoutingSearchParameters()
    sp.first_solution_strategy = routing_enums_pb2.FirstSolutionStrategy.PARALLEL_CHEAPEST_INSERTION
    sp.local_search_metaheuristic = routing_enums_pb2.LocalSearchMetaheuristic.GUIDED_LOCAL_SEARCH
    sp.time_limit.FromSeconds(args.time_limit)
    sp.log_search = args.verbose

    print(f"[solve] mode={args.mode} time_limit={args.time_limit}s "
          f"vehicles={V} pantries={P} origins={O}")
    solution = routing.SolveWithParameters(sp)
    if solution is None:
        print("[solve] NO SOLUTION")
        return None

    routes = []
    served_nodes = set()
    total_travel_min = 0
    total_lbs = 0
    for v in range(V):
        idx = routing.Start(v)
        stops = []
        load = 0
        travel_min = 0
        prev_node = mgr.IndexToNode(idx)
        while not routing.IsEnd(idx):
            node = mgr.IndexToNode(idx)
            if node >= O:
                served_nodes.add(node)
            stops.append(node)
            nxt = solution.Value(routing.NextVar(idx))
            nxt_node = mgr.IndexToNode(nxt)
            travel_min += time_mat[node, nxt_node]
            load += demands[node]
            idx = nxt
        stops.append(mgr.IndexToNode(idx))  # end (origin)
        routes.append({
            "vehicle": v,
            "origin": starts[v],
            "stops": stops,
            "n_pantry_stops": len([s for s in stops if s >= O]),
            "lbs_delivered": int(load),
            "travel_min": int(travel_min),
        })
        total_travel_min += travel_min
        total_lbs += load

    served_pantries = sorted(n - O for n in served_nodes)
    served_set = set(served_pantries)
    unserved = [i for i in range(P) if i not in served_set]

    # Equity-aware summary
    priority_idx = [i for i, p in enumerate(pantries) if p["w"] >= 1.5]
    priority_served = sum(1 for i in priority_idx if i in served_set)

    # Coverage by need tercile: demand vs delivered.
    tier_label = ["low-need", "mid-need", "high-need"]
    coverage_by_tier = {}
    for t in (0, 1, 2):
        idx_in_tier = [i for i, p in enumerate(pantries) if p.get("need_t", 0) == t]
        demand_lbs = sum(pantries[i]["demand_lbs"] for i in idx_in_tier)
        served_in_tier = [i for i in idx_in_tier if i in served_set]
        delivered_lbs = sum(pantries[i]["demand_lbs"] for i in served_in_tier)
        coverage_by_tier[t] = {
            "label": tier_label[t],
            "n_pantries": len(idx_in_tier),
            "n_served": len(served_in_tier),
            "demand_lbs": int(demand_lbs),
            "delivered_lbs": int(delivered_lbs),
            "coverage_pct": round(100 * delivered_lbs / demand_lbs, 1) if demand_lbs else 0.0,
        }

    # Need-weighted coverage: sum(w_r * delivered) / sum(w_r * demand).
    num = sum(p["w"] * p["demand_lbs"] for i, p in enumerate(pantries) if i in served_set)
    den = sum(p["w"] * p["demand_lbs"] for p in pantries)
    need_weighted_coverage = round(100 * num / den, 1) if den else 0.0
    flat_coverage = round(100 * total_lbs / sum(p["demand_lbs"] for p in pantries), 1)

    summary = {
        "mode": args.mode,
        "n_origins": O,
        "n_vehicles": V,
        "n_pantries": P,
        "served": len(served_pantries),
        "unserved": len(unserved),
        "priority_pantries": len(priority_idx),
        "priority_served": priority_served,
        "total_demand_lbs": int(sum(p["demand_lbs"] for p in pantries)),
        "total_delivered_lbs": int(total_lbs),
        "total_travel_min": int(total_travel_min),
        "flat_coverage_pct": flat_coverage,
        "need_weighted_coverage_pct": need_weighted_coverage,
        "coverage_by_tier": coverage_by_tier,
    }
    print(f"[solve] served={summary['served']}/{P} "
          f"(priority {priority_served}/{len(priority_idx)}) "
          f"travel={summary['total_travel_min']}min "
          f"lbs={summary['total_delivered_lbs']}/{summary['total_demand_lbs']} "
          f"(flat {flat_coverage}% / need-wtd {need_weighted_coverage}%)")
    for t in (0, 1, 2):
        c = coverage_by_tier[t]
        print(f"        {c['label']:>10}  served {c['n_served']:>3}/{c['n_pantries']:<3}  "
              f"delivered {c['delivered_lbs']:>6,}/{c['demand_lbs']:<6,} lbs "
              f"({c['coverage_pct']:>5.1f}%)")

    return {"summary": summary, "routes": routes,
            "served_pantry_idx": served_pantries, "unserved_pantry_idx": unserved}


def plot_map(instance, result, out_png: Path, title: str):
    origins = instance["origins"]
    pantries = instance["pantries"]
    O = len(origins)

    fig, ax = plt.subplots(figsize=(12, 12), dpi=120)

    # Background NYC outline (rough bbox via pantries).
    pl_lats = [p["lat"] for p in pantries]
    pl_lons = [p["lon"] for p in pantries]
    ax.set_xlim(min(pl_lons + [-74.27]) - 0.01, max(pl_lons + [-73.69]) + 0.01)
    ax.set_ylim(min(pl_lats + [40.49]) - 0.01, max(pl_lats + [40.92]) + 0.01)
    ax.set_aspect(1 / math.cos(math.radians(40.73)))
    ax.set_facecolor("#f5f5f3")

    # Unserved pantries (gray).
    served_set = set(result["served_pantry_idx"])
    for i, p in enumerate(pantries):
        if i in served_set:
            continue
        sz = 5 + 10 * (p["w"] - 0.5)
        ax.scatter(p["lon"], p["lat"], s=sz, c="#bbbbbb",
                   alpha=0.55, edgecolor="none", zorder=1)

    # Routes (colored per origin) + served pantries.
    served_per_origin = defaultdict(int)
    for r in result["routes"]:
        oi = r["origin"]
        color = ORIGIN_COLORS[oi % len(ORIGIN_COLORS)]
        prev = None
        for s in r["stops"]:
            if s < O:
                lon, lat = origins[s]["lon"], origins[s]["lat"]
            else:
                p = pantries[s - O]
                lon, lat = p["lon"], p["lat"]
                served_per_origin[oi] += 1
                sz = 18 + 22 * (p["w"] - 0.5)
                ax.scatter(lon, lat, s=sz, c=color, alpha=0.85,
                           edgecolor="white", linewidth=0.5, zorder=3)
            if prev is not None:
                ax.plot([prev[0], lon], [prev[1], lat],
                        c=color, alpha=0.55, lw=1.1, zorder=2)
            prev = (lon, lat)

    # Origins (big star).
    for oi, o in enumerate(origins):
        color = ORIGIN_COLORS[oi % len(ORIGIN_COLORS)]
        ax.scatter(o["lon"], o["lat"], s=400, c=color, marker="*",
                   edgecolor="black", linewidth=1.4, zorder=5)
        ax.annotate(
            f"{oi+1}. {o['name'].split('(')[0].strip()}",
            (o["lon"], o["lat"]),
            xytext=(8, 8), textcoords="offset points",
            fontsize=9, fontweight="bold",
            bbox=dict(boxstyle="round,pad=0.3", fc="white", ec=color, lw=1, alpha=0.92),
            zorder=6,
        )

    # Legend.
    legend_items = []
    for oi, o in enumerate(origins):
        color = ORIGIN_COLORS[oi % len(ORIGIN_COLORS)]
        legend_items.append(
            Line2D([0], [0], marker="*", color="w", markerfacecolor=color,
                   markeredgecolor="black", markersize=14,
                   label=f"{o['name'][:30]}  ({served_per_origin[oi]} stops)")
        )
    legend_items.append(
        Line2D([0], [0], marker="o", color="w", markerfacecolor="#bbbbbb",
               markersize=8, label=f"Unserved pantry  ({len(result['unserved_pantry_idx'])})")
    )
    ax.legend(handles=legend_items, loc="lower right", fontsize=8,
              framealpha=0.93, title="Origin depots (top-5 NYC wholesale/supermarket)")

    s = result["summary"]
    ax.set_title(
        f"{title}\n"
        f"served {s['served']}/{s['n_pantries']} pantries "
        f"(priority {s['priority_served']}/{s['priority_pantries']})  "
        f"·  travel {s['total_travel_min']:,} min  "
        f"·  {s['total_delivered_lbs']:,}/{s['total_demand_lbs']:,} lbs  "
        f"·  need-wtd coverage {s['need_weighted_coverage_pct']:.1f}%",
        fontsize=12,
    )
    ax.set_xlabel("Longitude"); ax.set_ylabel("Latitude")
    ax.grid(alpha=0.18, linestyle=":")

    fig.tight_layout()
    fig.savefig(out_png, dpi=140, bbox_inches="tight")
    print(f"[plot] wrote {out_png}")
    plt.close(fig)


def plot_compare(instance, uni, equ, out_png: Path):
    """Side-by-side uniform vs equity."""
    origins = instance["origins"]
    pantries = instance["pantries"]
    O = len(origins)

    fig, axes = plt.subplots(1, 2, figsize=(22, 14), dpi=120)
    fig.subplots_adjust(top=0.82, bottom=0.06, left=0.04, right=0.98, wspace=0.06)

    pl_lats = [p["lat"] for p in pantries]
    pl_lons = [p["lon"] for p in pantries]
    xlim = (min(pl_lons) - 0.015, max(pl_lons) + 0.015)
    ylim = (min(pl_lats) - 0.015, max(pl_lats) + 0.015)

    for ax, result, name in zip(axes, [uni, equ], ["uniform", "equity"]):
        ax.set_xlim(*xlim); ax.set_ylim(*ylim)
        ax.set_aspect(1 / math.cos(math.radians(40.73)))
        ax.set_facecolor("#f5f5f3")

        served_set = set(result["served_pantry_idx"])
        for i, p in enumerate(pantries):
            if i in served_set:
                continue
            ax.scatter(p["lon"], p["lat"], s=4 + 12 * (p["w"] - 0.5),
                       c="#bbbbbb", alpha=0.55, edgecolor="none", zorder=1)

        for r in result["routes"]:
            oi = r["origin"]
            color = ORIGIN_COLORS[oi % len(ORIGIN_COLORS)]
            prev = None
            for s in r["stops"]:
                if s < O:
                    lon, lat = origins[s]["lon"], origins[s]["lat"]
                else:
                    p = pantries[s - O]
                    lon, lat = p["lon"], p["lat"]
                    ax.scatter(lon, lat, s=14 + 20 * (p["w"] - 0.5),
                               c=color, alpha=0.85, edgecolor="white",
                               linewidth=0.4, zorder=3)
                if prev is not None:
                    ax.plot([prev[0], lon], [prev[1], lat],
                            c=color, alpha=0.55, lw=1.0, zorder=2)
                prev = (lon, lat)

        for oi, o in enumerate(origins):
            color = ORIGIN_COLORS[oi % len(ORIGIN_COLORS)]
            ax.scatter(o["lon"], o["lat"], s=340, c=color, marker="*",
                       edgecolor="black", linewidth=1.3, zorder=5)

        s = result["summary"]
        ax.set_title(
            f"mode = {name}\n"
            f"served {s['served']}/{s['n_pantries']}    "
            f"priority {s['priority_served']}/{s['priority_pantries']}    "
            f"travel {s['total_travel_min']:,} min",
            fontsize=12,
        )
        ax.set_xlabel("Longitude"); ax.set_ylabel("Latitude")
        ax.grid(alpha=0.18, linestyle=":")

    legend_items = []
    for oi, o in enumerate(origins):
        legend_items.append(
            Line2D([0], [0], marker="*", color="w",
                   markerfacecolor=ORIGIN_COLORS[oi % len(ORIGIN_COLORS)],
                   markeredgecolor="black", markersize=12,
                   label=f"{o['name'][:32]}")
        )
    legend_items.append(
        Line2D([0], [0], marker="o", color="w", markerfacecolor="#bbbbbb",
               markersize=7, label="Unserved pantry (size ∝ equity weight)")
    )
    fig.legend(handles=legend_items, loc="upper center", ncol=3,
               fontsize=10, bbox_to_anchor=(0.5, 0.92),
               frameon=True, framealpha=0.95,
               title="20-vehicle fleet from 5 NYC wholesale/supermarket origins")

    fig.suptitle(
        "NYC food-rescue routing  ·  5 origins  ·  20 vehicles  ·  528 pantries",
        y=0.985, fontsize=15, fontweight="bold",
    )
    fig.savefig(out_png, dpi=140, bbox_inches="tight")
    print(f"[plot] wrote {out_png}")
    plt.close(fig)


def plot_coverage(uni, equ, out_png: Path, demand_desc="dynamic demand"):
    """Bar chart: per-tier coverage (% of demand lbs delivered) + need-weighted summary."""
    tiers = ["low-need", "mid-need", "high-need"]
    uni_cov = [uni["summary"]["coverage_by_tier"][t]["coverage_pct"] for t in (0, 1, 2)]
    equ_cov = [equ["summary"]["coverage_by_tier"][t]["coverage_pct"] for t in (0, 1, 2)]

    fig, axes = plt.subplots(1, 2, figsize=(14, 6), dpi=120,
                             gridspec_kw=dict(width_ratios=[1.4, 1]))

    # Left: per-tier grouped bars
    ax = axes[0]
    x = np.arange(len(tiers))
    w = 0.38
    b1 = ax.bar(x - w/2, uni_cov, w, color="#999999", label="uniform")
    b2 = ax.bar(x + w/2, equ_cov, w, color="#2ca02c", label="equity")
    for bars in (b1, b2):
        for b in bars:
            ax.annotate(f"{b.get_height():.1f}%", xy=(b.get_x()+b.get_width()/2, b.get_height()),
                        xytext=(0, 3), textcoords="offset points",
                        ha="center", fontsize=9)
    ax.set_xticks(x); ax.set_xticklabels(tiers)
    ax.set_ylabel("Coverage (% of demand-lbs delivered)")
    ax.set_ylim(0, max(max(uni_cov), max(equ_cov)) * 1.18)
    ax.set_title("Per-tercile demand coverage")
    ax.grid(axis="y", alpha=0.3, linestyle=":")
    ax.legend(loc="upper left")

    # Right: scalar summary bars
    ax = axes[1]
    labels = ["flat\ncoverage", "need-weighted\ncoverage"]
    uni_s = [uni["summary"]["flat_coverage_pct"], uni["summary"]["need_weighted_coverage_pct"]]
    equ_s = [equ["summary"]["flat_coverage_pct"], equ["summary"]["need_weighted_coverage_pct"]]
    x = np.arange(len(labels))
    w = 0.38
    b1 = ax.bar(x - w/2, uni_s, w, color="#999999", label="uniform")
    b2 = ax.bar(x + w/2, equ_s, w, color="#2ca02c", label="equity")
    for bars in (b1, b2):
        for b in bars:
            ax.annotate(f"{b.get_height():.1f}%", xy=(b.get_x()+b.get_width()/2, b.get_height()),
                        xytext=(0, 3), textcoords="offset points",
                        ha="center", fontsize=9)
    ax.set_xticks(x); ax.set_xticklabels(labels)
    ax.set_ylabel("Coverage (%)")
    ax.set_ylim(0, max(max(uni_s), max(equ_s)) * 1.22)
    ax.set_title("Overall coverage")
    ax.grid(axis="y", alpha=0.3, linestyle=":")

    fig.suptitle(
        "Equity vs uniform routing — coverage by need tercile\n"
        f"demand: {demand_desc}  ·  "
        f"served U:{uni['summary']['served']} / E:{equ['summary']['served']} of "
        f"{uni['summary']['n_pantries']} pantries",
        fontsize=12, fontweight="bold",
    )
    fig.tight_layout()
    fig.savefig(out_png, dpi=140, bbox_inches="tight")
    print(f"[plot] wrote {out_png}")
    plt.close(fig)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--instance", type=Path, default=HERE / "instance.json")
    ap.add_argument("--mode", choices=["uniform", "equity", "both"], default="both")
    ap.add_argument("--skip-penalty", type=int, default=2000,
                    help="Penalty (in solver-internal units, ~minutes) for skipping a node.")
    ap.add_argument("--time-limit", type=int, default=30, help="Solver wallclock seconds.")
    ap.add_argument("--vehicle-cap-lbs", type=int, default=None,
                    help="Override per-vehicle capacity (lbs).")
    ap.add_argument("--shift-min", type=int, default=None,
                    help="Override per-vehicle shift cap (minutes).")
    ap.add_argument("--tight", action="store_true",
                    help="Shortcut: 1500 lb capacity & 240 min shift (forces skipping).")
    ap.add_argument("--verbose", action="store_true")
    ap.add_argument("--routes-out", type=Path, default=HERE / "routes.json")
    ap.add_argument("--map-out", type=Path, default=HERE / "route_map.png")
    args = ap.parse_args()

    if args.tight:
        args.vehicle_cap_lbs = args.vehicle_cap_lbs or 1500
        args.shift_min = args.shift_min or 240

    instance = json.loads(args.instance.read_text())

    out = {}
    if args.mode in ("uniform", "both"):
        a = argparse.Namespace(**vars(args)); a.mode = "uniform"
        out["uniform"] = solve(instance, a)
        plot_map(instance, out["uniform"], HERE / "route_map_uniform.png",
                 "Uniform routing (equal skip penalty)")
    if args.mode in ("equity", "both"):
        a = argparse.Namespace(**vars(args)); a.mode = "equity"
        out["equity"] = solve(instance, a)
        plot_map(instance, out["equity"], HERE / "route_map_equity.png",
                 "Equity-weighted routing (penalty ∝ need/access)")
    if args.mode == "both":
        plot_compare(instance, out["uniform"], out["equity"], args.map_out)
        plot_coverage(out["uniform"], out["equity"],
                      args.map_out.with_name("coverage_bars.png"),
                      demand_desc=instance["params"].get("demand_desc", "dynamic demand"))
    else:
        plot_map(instance, out[args.mode], args.map_out,
                 f"NYC food-rescue routes ({args.mode})")

    args.routes_out.write_text(json.dumps(out, indent=2))
    print(f"[done] wrote {args.routes_out}")

    if "uniform" in out and "equity" in out:
        u = out["uniform"]["summary"]; e = out["equity"]["summary"]
        print("\n=== comparison ===")
        print(f"                                   uniform   equity")
        print(f"  pantries served                   {u['served']:>7}   {e['served']:>6}")
        print(f"  priority served                   {u['priority_served']:>4}/{u['priority_pantries']:<3}   "
              f"{e['priority_served']:>4}/{e['priority_pantries']:<3}")
        print(f"  total travel (min)                {u['total_travel_min']:>7}   {e['total_travel_min']:>6}")
        print(f"  delivered / demand (lbs)          {u['total_delivered_lbs']:>7}/{u['total_demand_lbs']:<6}   "
              f"{e['total_delivered_lbs']:>5}/{e['total_demand_lbs']:<6}")
        print(f"  flat coverage  %                  {u['flat_coverage_pct']:>7.1f}   {e['flat_coverage_pct']:>6.1f}")
        print(f"  need-weighted coverage  %         {u['need_weighted_coverage_pct']:>7.1f}   {e['need_weighted_coverage_pct']:>6.1f}")
        print("\n  per-tier coverage (% of demand lbs delivered):")
        for t in (0, 1, 2):
            ut = u["coverage_by_tier"][str(t)] if str(t) in u["coverage_by_tier"] else u["coverage_by_tier"][t]
            et = e["coverage_by_tier"][str(t)] if str(t) in e["coverage_by_tier"] else e["coverage_by_tier"][t]
            print(f"    {ut['label']:>10}              "
                  f"{ut['coverage_pct']:>11.1f}   {et['coverage_pct']:>6.1f}")


if __name__ == "__main__":
    main()
