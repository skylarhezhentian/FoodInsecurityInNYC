"""
pickup_model.py -- collect-and-distribute VRP: trucks pick up at DONORS (load+)
then deliver to PANTRIES (load-), under capacity, cold-chain, and time windows.
Adds the pickup half of City Harvest's operation (their "60% of driving") and a
stochastic stress-test for BLIND DONATIONS (donors that may have no food).

Nodes (order matters, matches build_pickup_cache.py):
    [depots]  +  [donors]  +  [pantries]
Reuses pantry demand/windows/equity-weights from instance_ch.json; donor supply,
reliability (avail_prob) and variability (supply_cv) from data/donors_pickup.csv.

Outputs: routes_pickup.json, route_map_pickup.png, pickup_uncertainty.png.
"""
from __future__ import annotations
import argparse, csv, json, math, random
from pathlib import Path
import numpy as np
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from ortools.constraint_solver import pywrapcp, routing_enums_pb2
import geo_travel
import solve_routes_v1 as S   # for _draw_basemap

HERE = Path(__file__).resolve().parent
DONOR_SVC = 20          # minutes to load at a donor
DONOR_WIN = 480         # donors available 6am-2pm (minutes from shift start)


def load_all(instance, donors_csv):
    inst = json.loads(Path(instance).read_text())
    depots = inst["origins"]; pantries = inst["pantries"]; P = inst["params"]
    donors = []
    for d in csv.DictReader(open(donors_csv)):
        s = float(d["supply_lbs"]); cf = float(d["cold_frac"])
        donors.append({"name": d["name"], "anchor": int(d["anchor"]),
                       "lat": float(d["lat"]), "lon": float(d["lon"]),
                       "supply_lbs": s, "supply_cold": s*cf,
                       "avail_prob": float(d["avail_prob"]), "supply_cv": float(d["supply_cv"])})
    return inst, depots, donors, pantries, P


def build(depots, donors, pantries, P, cache, tod):
    O, D, NP = len(depots), len(donors), len(pantries)
    N = O + D + NP
    lons = [o["lon"] for o in depots]+[d["lon"] for d in donors]+[p["lon"] for p in pantries]
    lats = [o["lat"] for o in depots]+[d["lat"] for d in donors]+[p["lat"] for p in pantries]
    svc = [0]*O + [DONOR_SVC]*D + [p.get("service_min", P["service_min"]) for p in pantries]
    dist_km, time_min = geo_travel.build_matrices(
        lons, lats, O, backend="osrm", service_min=svc, congestion=0.42, tod=tod,
        cache=cache, verbose=True)
    return O, D, NP, N, time_min


def don_idx(O, d): return O + d
def pan_idx(O, D, p): return O + D + p


def solve(depots, donors, pantries, P, O, D, NP, time_min, vehicles, *, mode,
          skip_penalty, time_limit, freshness_coef, seed, supply_mult=None,
          staged_frac=0.4, decay_coef=0.0):
    """supply_mult[d] in [0,1] scales donor d's EXPECTED supply (used by the
    stochastic re-plan; default None = plan on expected supply)."""
    N = O + D + NP
    horizon = P["horizon_min"]
    starts = [v["origin_idx"] for v in vehicles]; ends = list(starts)
    mgr = pywrapcp.RoutingIndexManager(N, len(vehicles), starts, ends)
    routing = pywrapcp.RoutingModel(mgr)

    def tcb(i, j): return int(time_min[mgr.IndexToNode(i), mgr.IndexToNode(j)])
    tci = routing.RegisterTransitCallback(tcb)
    routing.SetArcCostEvaluatorOfAllVehicles(tci)

    # supply per donor (expected = avail_prob*supply, the planner's best guess)
    exp_sup = [donors[d]["avail_prob"]*donors[d]["supply_lbs"] for d in range(D)]
    exp_cold = [donors[d]["avail_prob"]*donors[d]["supply_cold"] for d in range(D)]
    if supply_mult is not None:
        exp_sup = [exp_sup[d]*supply_mult[d] for d in range(D)]
        exp_cold = [exp_cold[d]*supply_mult[d] for d in range(D)]

    # Load delta: +supply at donor, -demand at pantry, 0 at depot
    def load_cb(i):
        n = mgr.IndexToNode(i)
        if n < O: return 0
        if n < O+D: return int(exp_sup[n-O])
        return -int(pantries[n-O-D]["demand_lbs"])
    routing.AddDimensionWithVehicleCapacity(
        routing.RegisterUnaryTransitCallback(load_cb), 0,
        [v["cap_total_lbs"] for v in vehicles], False, "Load")    # start cumul set below

    def cold_cb(i):
        n = mgr.IndexToNode(i)
        if n < O: return 0
        if n < O+D: return int(exp_cold[n-O])
        return -int(pantries[n-O-D]["demand_cold"])
    routing.AddDimensionWithVehicleCapacity(
        routing.RegisterUnaryTransitCallback(cold_cb), 0,
        [v["cap_cold_lbs"] for v in vehicles], False, "ColdLoad")

    # Warehouse staging: each truck leaves the depot partly loaded with consolidated
    # food (City Harvest's Brooklyn warehouse); donor pickups TOP IT UP en route.
    # This matches reality and avoids a 'must reach a donor before any delivery' trap.
    load_dim = routing.GetDimensionOrDie("Load")
    cold_dim = routing.GetDimensionOrDie("ColdLoad")
    for v in range(len(vehicles)):
        st = routing.Start(v)
        load_dim.CumulVar(st).SetRange(0, int(staged_frac * vehicles[v]["cap_total_lbs"]))
        cold_dim.CumulVar(st).SetRange(0, int(staged_frac * vehicles[v]["cap_cold_lbs"]))

    # time windows: pantries fixed; donors available through the morning
    routing.AddDimension(tci, horizon, horizon, True, "Time")
    tdim = routing.GetDimensionOrDie("Time")
    for d in range(D):
        tdim.CumulVar(mgr.NodeToIndex(don_idx(O, d))).SetRange(0, DONOR_WIN)
    for pi, p in enumerate(pantries):
        tdim.CumulVar(mgr.NodeToIndex(pan_idx(O, D, pi))).SetRange(int(p["tw_open"]), int(p["tw_close"]))
    tdim.SetSpanCostCoefficientForAllVehicles(freshness_coef)

    # PERISHABILITY OBJECTIVE: cold food loses value the later it's delivered.
    # Soft upper bound at time 0 on each cold delivery, weighted by its cold lbs ->
    # cost = decay_coef * cold_lbs * arrival_min. Pushes perishables earlier (and,
    # if too late to be worth it, lets the solver drop them).
    if decay_coef > 0:
        for pi, p in enumerate(pantries):
            if p["demand_cold"] > 0:
                coef = int(round(decay_coef * p["demand_cold"]))
                if coef > 0:
                    tdim.SetCumulVarSoftUpperBound(mgr.NodeToIndex(pan_idx(O, D, pi)), 0, coef)

    # donors are droppable for free (visited only instrumentally to enable deliveries)
    for d in range(D):
        routing.AddDisjunction([mgr.NodeToIndex(don_idx(O, d))], 0)
    # pantries droppable at the equity/uniform skip penalty
    rng = random.Random(seed)
    dvals = sorted(p["demand_lbs"] for p in pantries); med = dvals[len(dvals)//2] or 1
    for pi, p in enumerate(pantries):
        mult = p["w"] if mode == "equity" else (
               min(3.0, p["demand_lbs"]/med) if mode == "preferential" else
               rng.uniform(0.3, 1.7) if mode == "random" else 1.0)
        routing.AddDisjunction([mgr.NodeToIndex(pan_idx(O, D, pi))], int(skip_penalty*mult))

    sp = pywrapcp.DefaultRoutingSearchParameters()
    sp.first_solution_strategy = routing_enums_pb2.FirstSolutionStrategy.PARALLEL_CHEAPEST_INSERTION
    sp.local_search_metaheuristic = routing_enums_pb2.LocalSearchMetaheuristic.GUIDED_LOCAL_SEARCH
    sp.time_limit.FromSeconds(time_limit)
    sol = routing.SolveWithParameters(sp)
    if sol is None:
        return None

    routes = []; served = set(); pickups_used = set(); tot_travel = 0
    cold_t_num = 0.0; cold_t_den = 0.0          # freshness: cold-lb-weighted delivery time
    for v in range(len(vehicles)):
        idx = routing.Start(v); seq = []
        while not routing.IsEnd(idx):
            n = mgr.IndexToNode(idx)
            if O <= n < O+D:
                pickups_used.add(n-O)
            elif n >= O+D:
                served.add(n-O-D)
                p = pantries[n-O-D]
                if p["demand_cold"] > 0:
                    t = sol.Value(tdim.CumulVar(idx))
                    cold_t_num += p["demand_cold"] * t; cold_t_den += p["demand_cold"]
            seq.append(n)
            nxt = sol.Value(routing.NextVar(idx))
            tot_travel += time_min[n, mgr.IndexToNode(nxt)]
            idx = nxt
        seq.append(mgr.IndexToNode(idx))
        routes.append({"vehicle": v, "type": vehicles[v]["type"],
                       "origin_idx": vehicles[v]["origin_idx"], "seq": seq})
    fresh = round(cold_t_num / cold_t_den, 1) if cold_t_den else 0.0
    return {"routes": routes, "served": sorted(served), "pickups": sorted(pickups_used),
            "travel": int(tot_travel), "cold_delivery_min": fresh,
            "exp_sup": exp_sup, "exp_cold": exp_cold}


def summarize(res, pantries, O, D, label):
    sset = set(res["served"])
    tot_dem = sum(p["demand_lbs"] for p in pantries)
    got = sum(pantries[i]["demand_lbs"] for i in res["served"])
    num = sum(pantries[i]["w"]*pantries[i]["demand_lbs"] for i in res["served"])
    den = sum(p["w"]*p["demand_lbs"] for p in pantries)
    tiers = {t: [i for i,p in enumerate(pantries) if p["need_t"]==t] for t in (0,1,2)}
    tcov = {t: round(100*sum(pantries[i]["demand_lbs"] for i in tiers[t] if i in sset)/
                     max(1,sum(pantries[i]["demand_lbs"] for i in tiers[t])),1) for t in (0,1,2)}
    s = {"label": label, "served": len(sset), "n_pantries": len(pantries),
         "pickups_used": len(res["pickups"]), "n_donors": D,
         "delivered_lbs": int(got), "flat_coverage_pct": round(100*got/tot_dem,1),
         "need_weighted_coverage_pct": round(100*num/den,1),
         "tier_coverage": tcov, "travel_min": res["travel"],
         "cold_delivery_min": res.get("cold_delivery_min", 0.0)}
    print(f"[{label}] served={s['served']}/{len(pantries)}  pickups={s['pickups_used']}/{D}  "
          f"need-wtd={s['need_weighted_coverage_pct']}%  "
          f"tiers low/mid/high={tcov[0]}/{tcov[1]}/{tcov[2]}%  travel={s['travel_min']}min  "
          f"freshness(cold Δt)={s['cold_delivery_min']}min")
    return s


# ----------------------------------------------------------------- stochastic stress test
def sample_supply(donors, rng):
    """Realized donor supply: Bernoulli(avail_prob) availability x lognormal(cv) amount."""
    mult = []
    for d in donors:
        if rng.random() > d["avail_prob"]:
            mult.append(0.0)                       # blind: showed up to no food
        else:
            z = max(-2, min(2, rng.gauss(0, 1)))
            mult.append(max(0.0, math.exp(d["supply_cv"]*z) ))
    return mult


def evaluate(res, donors, pantries, O, D, rng, vehicles, staged_frac):
    """Apply COMMITTED routes to a sampled supply realization. Warehouse-staged load
    is certain; only DONOR pickups are uncertain (blind donations). A pantry is
    served only if the truck has enough realized load on arrival (else stockout)."""
    realized = sample_supply(donors, rng)
    served = set()
    for r in res["routes"]:
        cap_t = vehicles[r["vehicle"]]["cap_total_lbs"]
        cap_c = vehicles[r["vehicle"]]["cap_cold_lbs"]
        load_t = staged_frac * cap_t          # certain warehouse staging
        load_c = staged_frac * cap_c
        for n in r["seq"]:
            if O <= n < O+D:                       # donor pickup (realized supply)
                d = n-O
                load_t += donors[d]["supply_lbs"]*realized[d]
                load_c += donors[d]["supply_cold"]*realized[d]
            elif n >= O+D:                         # pantry delivery
                p = pantries[n-O-D]
                if load_t >= p["demand_lbs"] and load_c >= p["demand_cold"]:
                    load_t -= p["demand_lbs"]; load_c -= p["demand_cold"]; served.add(n-O-D)
                # else: stockout -- not served this realization
    num = sum(pantries[i]["w"]*pantries[i]["demand_lbs"] for i in served)
    den = sum(p["w"]*p["demand_lbs"] for p in pantries)
    return len(served), round(100*num/den, 1)


def plot_uncertainty(planned, samples, out_png):
    served = [s[0] for s in samples]; nw = [s[1] for s in samples]
    fig, axes = plt.subplots(1, 2, figsize=(13, 5), dpi=130)
    for ax, data, plan, lab in [(axes[0], served, planned["served"], "agencies reached"),
                                (axes[1], nw, planned["need_weighted_coverage_pct"],
                                 "need-weighted coverage %")]:
        ax.hist(data, bins=18, color="#4C78A8", alpha=0.8)
        ax.axvline(plan, color="#d62728", lw=2.5, label=f"deterministic plan = {plan}")
        ax.axvline(np.mean(data), color="#2ca02c", lw=2.5, ls="--",
                   label=f"realized mean = {np.mean(data):.1f}")
        ax.set_xlabel(lab); ax.set_ylabel("# scenarios"); ax.legend(fontsize=9)
        ax.grid(axis="y", alpha=.3, ls=":")
    fig.suptitle("Blind-donation uncertainty: committed routes vs realized outcomes\n"
                 f"{len(samples)} sampled supply scenarios (anchors reliable, others may have no food)",
                 fontsize=12, fontweight="bold")
    fig.tight_layout(); fig.savefig(out_png, dpi=140, bbox_inches="tight"); plt.close(fig)
    print(f"[plot] wrote {out_png}")


def plot_map(depots, donors, pantries, res, O, D, out_png):
    fig, ax = plt.subplots(figsize=(13, 12), dpi=120)
    lons=[p["lon"] for p in pantries]; lats=[p["lat"] for p in pantries]
    ax.set_xlim(min(lons)-0.02,max(lons)+0.02); ax.set_ylim(min(lats)-0.02,max(lats)+0.02)
    ax.set_aspect(1/math.cos(math.radians(40.73))); ax.set_facecolor("#f7f9fb")
    S._draw_basemap(ax)
    sset=set(res["served"])
    for i,p in enumerate(pantries):
        if i not in sset:
            ax.scatter(p["lon"],p["lat"],s=5,c="#cccccc",alpha=0.5,zorder=1)
    nodexy = ([(o["lon"],o["lat"]) for o in depots] +
              [(d["lon"],d["lat"]) for d in donors] +
              [(p["lon"],p["lat"]) for p in pantries])
    # draw each truck's path along ACTUAL roads (OSRM /route geometry); fallback to
    # straight segments if a call fails.
    n_road = 0
    for r in res["routes"]:
        waypts = [nodexy[n] for n in r["seq"]]
        if len(waypts) < 2:
            continue
        geom = geo_travel.osrm_route_lonlats(waypts)
        if geom:
            xs = [c[0] for c in geom]; ys = [c[1] for c in geom]
            ax.plot(xs, ys, c="#2ca02c", alpha=0.35, lw=0.8, zorder=2); n_road += 1
        else:
            xs = [w[0] for w in waypts]; ys = [w[1] for w in waypts]
            ax.plot(xs, ys, c="#2ca02c", alpha=0.30, lw=0.7, ls=":", zorder=2)
        for n in r["seq"]:
            if n >= O+D and (n-O-D) in sset:
                lon, lat = nodexy[n]
                ax.scatter(lon,lat,s=14,c="#2ca02c",alpha=0.85,edgecolor="white",linewidth=0.3,zorder=3)
    print(f"      drew {n_road}/{len(res['routes'])} routes along real roads (OSRM /route)")
    for d in donors:
        ax.scatter(d["lon"],d["lat"],s=130,c=("#d62728" if d["anchor"] else "#ff9d3a"),
                   marker="^",edgecolor="black",linewidth=0.8,zorder=4)
    for o in depots:
        ax.scatter(o["lon"],o["lat"],s=360,c="#111",marker="*",edgecolor="white",linewidth=1.2,zorder=5)
    ax.set_xticks([]); ax.set_yticks([])
    ax.legend(handles=[
        Line2D([0],[0],marker="*",color="w",markerfacecolor="#111",markersize=15,label="depot"),
        Line2D([0],[0],marker="^",color="w",markerfacecolor="#d62728",markersize=11,label="reliable donor pickup"),
        Line2D([0],[0],marker="^",color="w",markerfacecolor="#ff9d3a",markersize=11,label="uncertain donor pickup"),
        Line2D([0],[0],marker="o",color="w",markerfacecolor="#2ca02c",markersize=9,label="recipient served")],
        loc="lower right", fontsize=9)
    ax.set_title("Illustrative collect-and-distribute routing scenario, NYC (equity strategy)\n"
                 "trucks pick up at donors then deliver to recipients along OSRM road paths",
                 fontsize=13, fontweight="bold")
    fig.savefig(out_png, dpi=140, bbox_inches="tight"); plt.close(fig)
    print(f"[plot] wrote {out_png}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--instance", default="instance_ch.json")
    ap.add_argument("--donors", default="data/donors_pickup.csv")
    ap.add_argument("--cache", default="osrm_cache_pickup.npz")
    ap.add_argument("--mode", default="equity", choices=["equity","preferential","random","uniform"])
    ap.add_argument("--tod", default="am_peak")
    ap.add_argument("--skip-penalty", type=int, default=5000)
    ap.add_argument("--freshness-coef", type=int, default=1)
    ap.add_argument("--time-limit", type=int, default=40)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--scenarios", type=int, default=200, help="stochastic stress-test samples")
    ap.add_argument("--staged-frac", type=float, default=0.4,
                    help="Fraction of capacity pre-staged from the warehouse; donor "
                         "pickups top up the rest (and are the uncertain part).")
    ap.add_argument("--decay-coef", type=float, default=0.0,
                    help="Perishability: cost = decay_coef * cold_lbs * arrival_min. "
                         "0 = off; ~0.03 pushes perishables earlier.")
    args = ap.parse_args()

    inst, depots, donors, pantries, P = load_all(args.instance, args.donors)
    vehicles = inst["vehicles"]
    O, D, NP, N, time_min = build(depots, donors, pantries, P, args.cache, args.tod)
    exp_total = sum(d["avail_prob"]*d["supply_lbs"] for d in donors)
    print(f"nodes={N} ({O} depots + {D} donors + {NP} pantries); "
          f"expected donor supply ~ {exp_total:,.0f} lbs/day")

    res = solve(depots, donors, pantries, P, O, D, NP, time_min, vehicles,
                mode=args.mode, skip_penalty=args.skip_penalty, time_limit=args.time_limit,
                freshness_coef=args.freshness_coef, seed=args.seed, staged_frac=args.staged_frac,
                decay_coef=args.decay_coef)
    if res is None:
        print("NO SOLUTION"); return
    planned = summarize(res, pantries, O, D, f"{args.mode} (deterministic, expected supply)")
    plot_map(depots, donors, pantries, res, O, D, HERE / "route_map_pickup.png")

    # stochastic stress test: committed routes vs sampled blind donations
    rng = random.Random(args.seed + 7)
    samples = [evaluate(res, donors, pantries, O, D, rng, vehicles, args.staged_frac)
               for _ in range(args.scenarios)]
    import statistics as st
    sv = [s[0] for s in samples]; nw = [s[1] for s in samples]
    print(f"\n=== stochastic stress test ({args.scenarios} scenarios) ===")
    print(f"  planned (expected supply):  served={planned['served']}  "
          f"need-wtd={planned['need_weighted_coverage_pct']}%")
    print(f"  realized mean:              served={st.mean(sv):.0f}  need-wtd={st.mean(nw):.1f}%")
    print(f"  realized p10/p90:           served={np.percentile(sv,10):.0f}/{np.percentile(sv,90):.0f}  "
          f"need-wtd={np.percentile(nw,10):.1f}/{np.percentile(nw,90):.1f}%")
    degr = planned['need_weighted_coverage_pct'] - st.mean(nw)
    print(f"  brittleness (plan - realized): {degr:.1f} pts lost to blind donations")
    plot_uncertainty(planned, samples, HERE / "pickup_uncertainty.png")

    Path(HERE / "routes_pickup.json").write_text(json.dumps(
        {"planned": planned, "stochastic": {"mean_served": st.mean(sv),
         "mean_need_weighted": st.mean(nw), "brittleness_pts": round(degr,1),
         "n_scenarios": args.scenarios}}, indent=2))
    print(f"[done] wrote routes_pickup.json")


if __name__ == "__main__":
    main()
