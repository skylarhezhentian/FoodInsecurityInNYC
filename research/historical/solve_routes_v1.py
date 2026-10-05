"""
solve_routes_v1.py -- v1 multi-depot, multi-commodity, time-windowed CVRP.

Upgrades over v0:
  L2 travel      : road-network times via geo_travel (road | osrm | haversine).
  L3 time windows: per-pantry [open, close] enforced on the Time dimension.
  L4 cold-chain  : two capacity dims (cold, total); dry trucks have 0 cold cap so
                   cold orders route to reefers. Freshness = span-cost on Time
                   keeps cold food moving; we report cold-lb-weighted delivery time.
  L5 multi-site  : 11 depots across 5 donors; vehicles bound to their site.
  L6 smooth wts  : equity skip-penalty uses continuous percentile weight w.

Outputs: routes_v1.json, route_map_v1.png, coverage_bars_v1.png.
"""
from __future__ import annotations
import argparse, json, math
from collections import defaultdict
from pathlib import Path

import numpy as np
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D

from ortools.constraint_solver import pywrapcp, routing_enums_pb2

import geo_travel

HERE = Path(__file__).resolve().parent
BOROUGHS_GEOJSON = Path(__file__).resolve().parent / "data" / "nyc_boroughs.geojson"


def _draw_basemap(ax):
    """Light NYC borough outlines so viewers can judge geographic plausibility."""
    if not BOROUGHS_GEOJSON.exists():
        return
    try:
        gj = json.loads(BOROUGHS_GEOJSON.read_text())
    except Exception:
        return
    for feat in gj.get("features", []):
        geom = feat.get("geometry", {})
        polys = geom.get("coordinates", [])
        if geom.get("type") == "Polygon":
            polys = [polys]
        for poly in polys:
            if not poly:
                continue
            ring = poly[0]
            xs = [pt[0] for pt in ring]; ys = [pt[1] for pt in ring]
            ax.fill(xs, ys, facecolor="#e9e9e4", edgecolor="#c4c4bc",
                    linewidth=0.8, zorder=0)


# distinct colors per donor (not per site) so the map stays readable
DONOR_COLORS = {
    "Hunts Point Produce Market": "#d62728",
    "Baldor Specialty Foods": "#1f77b4",
    "FreshDirect": "#2ca02c",
    "Trader Joe's": "#9467bd",
    "Whole Foods Market": "#ff7f0e",
}


def solve(instance, args, mode):
    origins = instance["origins"]; pantries = instance["pantries"]; vehicles = instance["vehicles"]
    P = instance["params"]
    O, NP, V = len(origins), len(pantries), len(vehicles)
    N = O + NP

    lons = [o["lon"] for o in origins] + [p["lon"] for p in pantries]
    lats = [o["lat"] for o in origins] + [p["lat"] for p in pantries]
    base_svc = P["service_min"]
    svc_arr = [0]*O + [p.get("service_min", base_svc) for p in pantries]   # per-node dwell
    dist_km, time_min = geo_travel.build_matrices(
        lons, lats, O, backend=args.travel, service_min=svc_arr,
        congestion=args.congestion, tod=getattr(args, "tod", None),
        cache=getattr(args, "cache", None), verbose=(mode in ("uniform", "random")))

    demand_total = [0]*O + [p["demand_lbs"] for p in pantries]
    demand_cold = [0]*O + [p["demand_cold"] for p in pantries]
    cap_total = [v["cap_total_lbs"] for v in vehicles]
    cap_cold = [v["cap_cold_lbs"] for v in vehicles]
    starts = [v["origin_idx"] for v in vehicles]; ends = list(starts)

    mgr = pywrapcp.RoutingIndexManager(N, V, starts, ends)
    routing = pywrapcp.RoutingModel(mgr)

    def time_cb(i, j):
        return int(time_min[mgr.IndexToNode(i), mgr.IndexToNode(j)])
    tcb = routing.RegisterTransitCallback(time_cb)
    routing.SetArcCostEvaluatorOfAllVehicles(tcb)

    # total-weight capacity
    def dtot(i): return int(demand_total[mgr.IndexToNode(i)])
    routing.AddDimensionWithVehicleCapacity(
        routing.RegisterUnaryTransitCallback(dtot), 0, cap_total, True, "Total")
    # cold-weight capacity (dry trucks have 0 -> can't carry any cold order)
    def dcold(i): return int(demand_cold[mgr.IndexToNode(i)])
    routing.AddDimensionWithVehicleCapacity(
        routing.RegisterUnaryTransitCallback(dcold), 0, cap_cold, True, "Cold")

    # time dimension with windows (L3)
    horizon = P["horizon_min"]
    routing.AddDimension(tcb, horizon, horizon, True, "Time")  # allow waiting up to horizon
    tdim = routing.GetDimensionOrDie("Time")
    for pi, p in enumerate(pantries):
        idx = mgr.NodeToIndex(O + pi)
        tdim.CumulVar(idx).SetRange(int(p["tw_open"]), int(p["tw_close"]))
    # freshness (L4): penalize long routes so cold food is delivered sooner
    tdim.SetSpanCostCoefficientForAllVehicles(args.freshness_coef)

    # Per-stop "value" = skip penalty. The SELECTION STRATEGY is exactly this value:
    #   uniform      -> equal value (throughput-only; routes by efficiency alone)
    #   random       -> seeded random value (random delivery points)
    #   preferential -> value ∝ agency size / throughput (favor large pantries)
    #   equity       -> value ∝ need weight w = (need_pct/access_pct)^γ
    # Same VRP, same constraints; only which stops are worth keeping changes.
    BASE = args.skip_penalty
    import random as _random
    rng = _random.Random(getattr(args, "seed", 0))
    dvals = sorted(p["demand_lbs"] for p in pantries)
    med_d = dvals[len(dvals) // 2] or 1
    for pi, p in enumerate(pantries):
        if mode == "equity":
            mult = p["w"]
        elif mode == "preferential":
            mult = min(3.0, p["demand_lbs"] / med_d)          # size-weighted
        elif mode == "random":
            mult = rng.uniform(0.30, 1.70)                    # random selection
        else:                                                  # uniform
            mult = 1.0
        routing.AddDisjunction([mgr.NodeToIndex(O + pi)], int(round(BASE * mult)))

    sp = pywrapcp.DefaultRoutingSearchParameters()
    sp.first_solution_strategy = routing_enums_pb2.FirstSolutionStrategy.PARALLEL_CHEAPEST_INSERTION
    sp.local_search_metaheuristic = routing_enums_pb2.LocalSearchMetaheuristic.GUIDED_LOCAL_SEARCH
    sp.time_limit.FromSeconds(args.time_limit)
    sol = routing.SolveWithParameters(sp)
    if sol is None:
        print(f"[solve:{mode}] NO SOLUTION"); return None

    routes = []; served = set()
    tot_travel = 0; tot_span = 0
    cold_time_num = 0.0; cold_time_den = 0.0
    reefer_used = dry_used = 0
    svc_min = P["service_min"]
    for v in range(V):
        vtype = vehicles[v]["type"]
        vcap_t, vcap_c = cap_total[v], cap_cold[v]
        idx = routing.Start(v); stops = []; detail = []
        load_t = load_c = 0
        route_travel = 0
        start_cumul = sol.Value(tdim.CumulVar(idx))
        while not routing.IsEnd(idx):
            node = mgr.IndexToNode(idx)
            cumul = sol.Value(tdim.CumulVar(idx))
            if node >= O:                                  # a pantry (delivery)
                served.add(node)
                pi = node - O; p = pantries[pi]
                load_t += demand_total[node]; load_c += demand_cold[node]
                cold_time_num += demand_cold[node] * cumul; cold_time_den += demand_cold[node]
                detail.append({
                    "seq": len(detail) + 1, "pantry_idx": pi, "name": p["name"],
                    "boro": p["boro"],
                    "arrival_min": int(cumul),            # Time cumul (travel + upstream service)
                    "service_min": p.get("service_min", svc_min),
                    "tw_open": p["tw_open"], "tw_close": p["tw_close"],
                    "has_window": p["has_window"],
                    "in_window": p["tw_open"] <= cumul <= p["tw_close"],
                    "demand_total_lbs": demand_total[node],
                    "demand_cold_lbs": demand_cold[node],
                    "cum_load_total_lbs": load_t, "cum_load_cold_lbs": load_c,
                    "needs_reefer": demand_cold[node] > 0,
                    "vehicle_compatible": (demand_cold[node] == 0) or (vtype == "reefer"),
                })
            stops.append(node)
            nxt = sol.Value(routing.NextVar(idx))
            route_travel += time_min[node, mgr.IndexToNode(nxt)]
            idx = nxt
        stops.append(mgr.IndexToNode(idx))
        end_cumul = sol.Value(tdim.CumulVar(idx))
        tot_travel += route_travel
        npan = len(detail)
        if npan:
            tot_span += (end_cumul - start_cumul)          # elapsed; waiting = span - travel
            if vtype == "reefer": reefer_used += 1
            else: dry_used += 1
        routes.append({
            "vehicle": v, "origin_site": origins[starts[v]]["name"], "donor": vehicles[v]["donor"],
            "type": vtype, "cap_total_lbs": vcap_t, "cap_cold_lbs": vcap_c,
            "n_pantry_stops": npan,
            "load_total_lbs": load_t, "load_cold_lbs": load_c,
            "load_total_pct": round(100*load_t/vcap_t, 1) if vcap_t else 0,
            "route_end_min": int(end_cumul), "route_travel_min": int(route_travel),
            "stops": stops, "stop_detail": detail,
        })

    served_idx = sorted(s - O for s in served); sset = set(served_idx)

    def cov(sel):
        dem = sum(pantries[i]["demand_lbs"] for i in sel)
        got = sum(pantries[i]["demand_lbs"] for i in sel if i in sset)
        return got, dem, (100*got/dem if dem else 0.0)

    tiers = {t: [i for i, p in enumerate(pantries) if p["need_t"] == t] for t in (0, 1, 2)}
    cov_tier = {}
    for t in (0, 1, 2):
        g, d, pc = cov(tiers[t])
        cov_tier[t] = {"label": ["low-need","mid-need","high-need"][t],
                       "n": len(tiers[t]), "served": sum(1 for i in tiers[t] if i in sset),
                       "delivered_lbs": int(g), "demand_lbs": int(d), "coverage_pct": round(pc,1)}
    cold_idx = [i for i,p in enumerate(pantries) if p["demand_cold"] > 0]
    amb_only = [i for i,p in enumerate(pantries) if p["demand_cold"] == 0]
    g_c = sum(pantries[i]["demand_cold"] for i in cold_idx if i in sset)
    d_c = sum(pantries[i]["demand_cold"] for i in cold_idx)
    num = sum(pantries[i]["w"]*pantries[i]["demand_lbs"] for i in served_idx)
    den = sum(p["w"]*p["demand_lbs"] for p in pantries)
    tot_dem = sum(p["demand_lbs"] for p in pantries)
    got_all = sum(pantries[i]["demand_lbs"] for i in served_idx)

    summary = {
        "mode": mode, "travel": args.travel, "n_sites": O, "n_donors": P.get("n_donors"),
        "n_vehicles": V, "n_pantries": NP, "served": len(served_idx),
        "unserved": NP - len(served_idx),
        "total_delivered_lbs": int(got_all), "total_demand_lbs": int(tot_dem),
        "flat_coverage_pct": round(100*got_all/tot_dem, 1),
        "need_weighted_coverage_pct": round(100*num/den, 1) if den else 0,
        "cold_coverage_pct": round(100*g_c/d_c, 1) if d_c else 0,
        "total_travel_min": int(tot_travel),
        "total_idle_min": int(max(0, tot_span - tot_travel)),   # waiting = elapsed - driving
        "idle_pct": round(100*max(0, tot_span - tot_travel)/tot_span, 1) if tot_span else 0,
        "cold_weighted_delivery_min": round(cold_time_num/cold_time_den, 1) if cold_time_den else 0,
        "reefer_used": reefer_used, "dry_used": dry_used,
        "coverage_by_tier": cov_tier,
    }
    print(f"[solve:{mode}] travel={args.travel} served={summary['served']}/{NP} "
          f"flat={summary['flat_coverage_pct']}% need-wtd={summary['need_weighted_coverage_pct']}% "
          f"cold={summary['cold_coverage_pct']}% "
          f"travel={summary['total_travel_min']}min "
          f"fresh(coldΔt)={summary['cold_weighted_delivery_min']}min "
          f"reefer/dry used={reefer_used}/{dry_used}")
    for t in (0,1,2):
        c = cov_tier[t]
        print(f"        {c['label']:>10}  {c['served']:>3}/{c['n']:<3}  {c['coverage_pct']:>5.1f}%")
    return {"summary": summary, "routes": routes, "served_pantry_idx": served_idx,
            "unserved_pantry_idx": [i for i in range(NP) if i not in sset]}


def plot_map(instance, uni, equ, out_png):
    origins = instance["origins"]; pantries = instance["pantries"]; O = len(origins)
    fig, axes = plt.subplots(1, 2, figsize=(22, 13), dpi=120)
    fig.subplots_adjust(top=0.84, bottom=0.05, left=0.04, right=0.98, wspace=0.06)
    lons=[p["lon"] for p in pantries]; lats=[p["lat"] for p in pantries]
    xlim=(min(lons)-0.015,max(lons)+0.015); ylim=(min(lats)-0.015,max(lats)+0.015)
    for ax, res, name in zip(axes, [uni, equ], ["uniform", "equity"]):
        ax.set_xlim(*xlim); ax.set_ylim(*ylim)
        ax.set_aspect(1/math.cos(math.radians(40.73))); ax.set_facecolor("#f7f9fb")
        _draw_basemap(ax)                       # NYC borough outlines
        sset = set(res["served_pantry_idx"])
        for i, p in enumerate(pantries):
            if i not in sset:
                ax.scatter(p["lon"], p["lat"], s=4+12*(p["w"]-0.5), c="#bcbcbc",
                           alpha=0.5, edgecolor="none", zorder=1)
        for r in res["routes"]:
            col = DONOR_COLORS.get(r["donor"], "#555")
            ls = "-" if r["type"] == "reefer" else (0, (4, 2))
            prev = None
            for s in r["stops"]:
                if s < O: lon, lat = origins[s]["lon"], origins[s]["lat"]
                else:
                    p = pantries[s-O]; lon, lat = p["lon"], p["lat"]
                    ax.scatter(lon, lat, s=12+18*(p["w"]-0.5), c=col, alpha=0.85,
                               edgecolor="white", linewidth=0.4, zorder=3)
                if prev is not None:
                    ax.plot([prev[0],lon],[prev[1],lat], c=col, alpha=0.5, lw=1.0,
                            ls=ls, zorder=2)
                prev = (lon, lat)
        for o in origins:
            col = DONOR_COLORS.get(o["donor"], "#555")
            ax.scatter(o["lon"], o["lat"], s=300, c=col, marker="*",
                       edgecolor="black", linewidth=1.2, zorder=5)
        s = res["summary"]
        ax.set_title(f"mode = {name}\nserved {s['served']}/{s['n_pantries']}  ·  "
                     f"need-wtd {s['need_weighted_coverage_pct']}%  ·  cold {s['cold_coverage_pct']}%  ·  "
                     f"travel {s['total_travel_min']:,}min", fontsize=11)
        ax.set_xlabel("Longitude"); ax.set_ylabel("Latitude"); ax.grid(alpha=0.18, ls=":")
    items = [Line2D([0],[0], marker="*", color="w", markerfacecolor=c, markeredgecolor="black",
                    markersize=13, label=d) for d, c in DONOR_COLORS.items()]
    items += [Line2D([0],[0], color="#555", lw=1.5, ls="-", label="reefer route"),
              Line2D([0],[0], color="#555", lw=1.5, ls=(0,(4,2)), label="dry route"),
              Line2D([0],[0], marker="o", color="w", markerfacecolor="#bcbcbc", markersize=7,
                     label="unserved (size∝weight)")]
    fig.legend(handles=items, loc="upper center", ncol=4, fontsize=9.5,
               bbox_to_anchor=(0.5, 0.93), title="5 donors / 11 sites · 20 vehicles (reefer + dry)")
    P = instance["params"]
    backend = uni["summary"].get("travel", "osrm")
    blabel = {"osrm": "OSRM road-network travel times",
              "road": "calibrated road times (haversine×1.33)",
              "haversine": "straight-line distance"}.get(backend, backend)
    fig.suptitle(f"NYC food-rescue routing v1 · {blabel} · time windows ({P['service_day']}) · "
                 f"cold-chain · smooth equity weights", y=0.985, fontsize=14, fontweight="bold")
    fig.savefig(out_png, dpi=140, bbox_inches="tight"); plt.close(fig)
    print(f"[plot] wrote {out_png}")


def plot_bars(uni, equ, out_png, desc):
    fig, axes = plt.subplots(1, 2, figsize=(14, 6), dpi=120, gridspec_kw=dict(width_ratios=[1.5,1]))
    tiers=["low-need","mid-need","high-need"]
    def _ct(s, t):  # coverage_by_tier keys are ints in-process, strings from JSON
        cbt = s["coverage_by_tier"]; return (cbt.get(t) or cbt.get(str(t)))["coverage_pct"]
    uc=[_ct(uni["summary"], t) for t in (0,1,2)]
    ec=[_ct(equ["summary"], t) for t in (0,1,2)]
    x=np.arange(3); w=0.38; ax=axes[0]
    for bars in (ax.bar(x-w/2,uc,w,color="#999",label="uniform"),
                 ax.bar(x+w/2,ec,w,color="#2ca02c",label="equity")):
        for b in bars: ax.annotate(f"{b.get_height():.0f}",(b.get_x()+b.get_width()/2,b.get_height()),
                                   xytext=(0,3),textcoords="offset points",ha="center",fontsize=9)
    ax.set_xticks(x); ax.set_xticklabels(tiers); ax.set_ylabel("coverage (% demand-lbs)")
    ax.set_ylim(0,108); ax.set_title("Per-tercile coverage"); ax.legend(); ax.grid(axis="y",alpha=.3,ls=":")
    ax=axes[1]
    labs=["flat","need-weighted","cold-chain"]
    us=[uni["summary"]["flat_coverage_pct"],uni["summary"]["need_weighted_coverage_pct"],uni["summary"]["cold_coverage_pct"]]
    es=[equ["summary"]["flat_coverage_pct"],equ["summary"]["need_weighted_coverage_pct"],equ["summary"]["cold_coverage_pct"]]
    x=np.arange(3)
    for bars in (ax.bar(x-w/2,us,w,color="#999",label="uniform"),
                 ax.bar(x+w/2,es,w,color="#2ca02c",label="equity")):
        for b in bars: ax.annotate(f"{b.get_height():.0f}",(b.get_x()+b.get_width()/2,b.get_height()),
                                   xytext=(0,3),textcoords="offset points",ha="center",fontsize=9)
    ax.set_xticks(x); ax.set_xticklabels(labs); ax.set_ylim(0,108)
    ax.set_title("Overall coverage"); ax.grid(axis="y",alpha=.3,ls=":")
    bk = {"osrm": "OSRM road-network times", "road": "calibrated road times",
          "haversine": "straight-line"}.get(uni["summary"].get("travel", "osrm"))
    fig.suptitle(f"v1 equity vs uniform · {bk} · {desc}\nserved U:{uni['summary']['served']} / "
                 f"E:{equ['summary']['served']} of {uni['summary']['n_pantries']}",
                 fontsize=11.5, fontweight="bold")
    fig.tight_layout(); fig.savefig(out_png, dpi=140, bbox_inches="tight"); plt.close(fig)
    print(f"[plot] wrote {out_png}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--instance", type=Path, default=HERE / "instance_v1.json")
    ap.add_argument("--travel", choices=["osrm","road","haversine"], default="osrm",
                    help="Travel-time matrix. osrm=full OSRM road network (canonical/default); "
                         "road=OSRM-calibrated haversine x1.33 (Level-1 fallback); haversine=straight-line.")
    ap.add_argument("--congestion", type=float, default=0.42,
                    help="Speed multiplier on OSRM free-flow 46km/h. 0.42 -> ~19 km/h "
                         "citywide effective (Manhattan CBD ~13 km/h, outer boroughs faster).")
    ap.add_argument("--freshness-coef", type=int, default=1,
                    help="Span-cost on Time dim (keeps cold food moving).")
    ap.add_argument("--skip-penalty", type=int, default=3000)
    ap.add_argument("--time-limit", type=int, default=60)
    ap.add_argument("--routes-out", type=Path, default=HERE / "routes_v1.json")
    ap.add_argument("--map-out", type=Path, default=HERE / "route_map_v1.png")
    args = ap.parse_args()

    inst = json.loads(args.instance.read_text())
    out = {}
    for mode in ("uniform", "equity"):
        out[mode] = solve(inst, args, mode)
    plot_map(inst, out["uniform"], out["equity"], args.map_out)
    plot_bars(out["uniform"], out["equity"], args.map_out.with_name("coverage_bars_v1.png"),
              inst["params"]["demand_desc"])
    args.routes_out.write_text(json.dumps(out, indent=2))

    u, e = out["uniform"]["summary"], out["equity"]["summary"]
    print("\n=== v1 comparison ===")
    print(f"                              uniform   equity")
    print(f"  served                      {u['served']:>7}   {e['served']:>6}")
    print(f"  flat coverage %             {u['flat_coverage_pct']:>7}   {e['flat_coverage_pct']:>6}")
    print(f"  need-weighted coverage %    {u['need_weighted_coverage_pct']:>7}   {e['need_weighted_coverage_pct']:>6}")
    print(f"  cold-chain coverage %       {u['cold_coverage_pct']:>7}   {e['cold_coverage_pct']:>6}")
    print(f"  travel (min)                {u['total_travel_min']:>7}   {e['total_travel_min']:>6}")
    print(f"  cold-wtd delivery time min  {u['cold_weighted_delivery_min']:>7}   {e['cold_weighted_delivery_min']:>6}")
    print(f"[done] wrote {args.routes_out}")


if __name__ == "__main__":
    main()
