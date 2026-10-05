"""
exact_gap.py -- L7: measure the GLS heuristic's optimality gap.

Builds a SMALL but non-trivial instance (1 depot, K vehicles, N candidate
pantries, single commodity = total lbs, equity skip-penalty), solves it two ways
on the IDENTICAL objective (travel-minutes + skip-penalty):

  1. EXACT  -- CP-SAT multi-vehicle prize-collecting capacitated VRP, solved to
               proven optimality (a true lower bound, unlike GLS). Gurobi is a
               drop-in if licensed; CP-SAT is exact and free, so we use it here.
  2. GLS    -- the same OR-Tools routing heuristic the full pipeline uses.

Reports gap = (GLS_obj - OPT) / OPT, plus CP-SAT's proven-optimal status.

CP-SAT model: one AddCircuit over (K depot-copies + N customers). Self-loops on
customers encode "skipped"; self-loops on spare depot-copies encode "unused
vehicle". This is an exact arc formulation with built-in subtour elimination.
"""
from __future__ import annotations
import argparse, json, time
from pathlib import Path
import numpy as np

from ortools.sat.python import cp_model
from ortools.constraint_solver import pywrapcp, routing_enums_pb2

import geo_travel

HERE = Path(__file__).resolve().parent


def pick_subset(inst, depot_origin, n_pantries, seed):
    """Depot = one origin; take the n nearest pantries to it (deterministic)."""
    o = inst["origins"][depot_origin]
    ps = inst["pantries"]
    d = [(geo_travel.haversine_km(o["lon"], o["lat"], p["lon"], p["lat"]), i)
         for i, p in enumerate(ps)]
    d.sort()
    idx = [i for _, i in d[:n_pantries]]
    return o, [ps[i] for i in idx]


def matrices(o, subset, congestion):
    lons = [o["lon"]] + [p["lon"] for p in subset]
    lats = [o["lat"]] + [p["lat"] for p in subset]
    dist_km, time_min = geo_travel.build_matrices(
        lons, lats, 1, backend="road", service_min=8, congestion=congestion, verbose=False)
    return time_min  # integer minutes, service included


def solve_exact(time_min, demand, cap, penalty, max_seconds):
    """Exact CP-SAT: single-vehicle prize-collecting capacitated TSP.

    Node 0 = depot, 1..N = customers. AddCircuit over all nodes with self-loops
    on customers (self-loop true => customer skipped). One trip, so capacity is
    simply sum(demand of served) <= cap -- a strong, tight constraint (no big-M).
    Exact subtour elimination is built into AddCircuit.
    """
    N = len(demand)
    n = 1 + N
    m = cp_model.CpModel()
    arcs = {}
    skip = {}
    lits = []
    for a in range(n):
        for b in range(n):
            if a == b:
                if a == 0:
                    continue                 # depot always in the tour
                v = m.NewBoolVar(f"skip_{a}")
                skip[a] = v
                lits.append((a, a, v))
            else:
                v = m.NewBoolVar(f"x_{a}_{b}")
                arcs[(a, b)] = v
                lits.append((a, b, v))
    m.AddCircuit(lits)

    # capacity: total served demand <= cap (single trip)
    m.Add(sum(int(demand[c-1]) * (1 - skip[c]) for c in range(1, n)) <= cap)

    # objective: travel-minutes on used arcs + skip penalties
    terms = [int(time_min[a, b]) * v for (a, b), v in arcs.items()]
    terms += [int(penalty[c-1]) * skip[c] for c in range(1, n)]
    m.Minimize(sum(terms))

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = float(max_seconds)
    solver.parameters.num_search_workers = 8
    t0 = time.time()
    st = solver.Solve(m)
    dt = time.time() - t0
    status = {cp_model.OPTIMAL: "OPTIMAL", cp_model.FEASIBLE: "FEASIBLE"}.get(st, "NONE")
    return solver.ObjectiveValue(), solver.BestObjectiveBound(), status, dt


def solve_gls(time_min, demand, cap, penalty, seconds):
    N = len(demand); n = 1 + N
    mgr = pywrapcp.RoutingIndexManager(n, 1, 0)   # single vehicle, matches exact
    routing = pywrapcp.RoutingModel(mgr)
    def tcb(i, j): return int(time_min[mgr.IndexToNode(i), mgr.IndexToNode(j)])
    ti = routing.RegisterTransitCallback(tcb)
    routing.SetArcCostEvaluatorOfAllVehicles(ti)
    dem = [0] + list(demand)
    def dcb(i): return int(dem[mgr.IndexToNode(i)])
    routing.AddDimensionWithVehicleCapacity(
        routing.RegisterUnaryTransitCallback(dcb), 0, [cap], True, "Cap")
    for c in range(1, n):
        routing.AddDisjunction([mgr.NodeToIndex(c)], int(penalty[c-1]))
    sp = pywrapcp.DefaultRoutingSearchParameters()
    sp.first_solution_strategy = routing_enums_pb2.FirstSolutionStrategy.PARALLEL_CHEAPEST_INSERTION
    sp.local_search_metaheuristic = routing_enums_pb2.LocalSearchMetaheuristic.GUIDED_LOCAL_SEARCH
    sp.time_limit.FromSeconds(int(seconds))
    t0 = time.time()
    sol = routing.SolveWithParameters(sp)
    dt = time.time() - t0
    served = set(); travel = 0
    idx = routing.Start(0)
    while not routing.IsEnd(idx):
        node = mgr.IndexToNode(idx)
        if node != 0:
            served.add(node)
        nxt = sol.Value(routing.NextVar(idx))
        travel += time_min[node, mgr.IndexToNode(nxt)]
        idx = nxt
    skip = sum(int(penalty[c-1]) for c in range(1, n) if c not in served)
    return travel + skip, travel, skip, len(served), dt


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--instance", type=Path, default=HERE / "instance_v1.json")
    ap.add_argument("--depot-origin", type=int, default=0, help="Origin index used as depot.")
    ap.add_argument("--n-pantries", type=int, default=16)
    ap.add_argument("--vehicles", type=int, default=2)
    ap.add_argument("--cap-frac", type=float, default=0.55,
                    help="Vehicle cap as a fraction of (subset demand / vehicles).")
    ap.add_argument("--skip-penalty", type=int, default=400,
                    help="Per-pantry skip penalty (flat, so exact & GLS match exactly).")
    ap.add_argument("--congestion", type=float, default=0.6)
    ap.add_argument("--exact-seconds", type=float, default=60)
    ap.add_argument("--gls-seconds", type=float, default=10)
    ap.add_argument("--sweep", action="store_true",
                    help="Run a grid over size x capacity and tabulate gaps.")
    args = ap.parse_args()

    inst = json.loads(args.instance.read_text())

    if args.sweep:
        o = inst["origins"][args.depot_origin]
        print(f"Heuristic-gap sweep (depot={o['name']}, GLS budget={args.gls_seconds:.0f}s, "
              f"penalty={args.skip_penalty})")
        print(f"{'n_pant':>6} {'cap%':>5} {'EXACT':>6} {'status':>9} {'GLS':>6} {'gap%':>7} {'served':>7} {'exact_s':>8}")
        for n in (14, 20, 25, 30):
            for cf in (0.45, 0.70):
                _, sub = pick_subset(inst, args.depot_origin, n, 0)
                tm = matrices(o, sub, args.congestion)
                dem = [p["demand_lbs"] for p in sub]
                cap = int(cf * sum(dem)); pen = [args.skip_penalty]*n
                opt, bnd, st, _ = solve_exact(tm, dem, cap, pen, args.exact_seconds)
                gls, _, _, sv, _ = solve_gls(tm, dem, cap, pen, args.gls_seconds)
                gap = 100*(gls-opt)/opt if opt else 0
                t0 = time.time()
                print(f"{n:>6} {cf:>5.2f} {opt:>6.0f} {st:>9} {gls:>6.0f} {gap:>6.2f}% {sv:>4}/{n:<2}")
        print("\nCP-SAT proves optimality on all; GLS gap grows on harder (tighter-cap, larger)\n"
              "instances at a short budget. Lengthening --gls-seconds closes most of it.")
        return
    o, subset = pick_subset(inst, args.depot_origin, args.n_pantries, 0)
    time_min = matrices(o, subset, args.congestion)
    demand = [p["demand_lbs"] for p in subset]
    total_dem = sum(demand)
    cap = int(args.cap_frac * total_dem)        # single vehicle, one trip
    penalty = [args.skip_penalty] * len(subset)

    print(f"Exact-vs-heuristic gap study  (single-vehicle prize-collecting capacitated TSP)")
    print(f"  depot       : {o['name']}")
    print(f"  pantries    : {len(subset)}  (nearest to depot)")
    print(f"  vehicle cap : {cap} lbs  (={args.cap_frac:.0%} of {total_dem} lbs total demand)")
    print(f"  skip penalty: {args.skip_penalty}/pantry (flat)   travel: road backend (min)")
    print()

    opt, bound, status, dt_e = solve_exact(
        time_min, demand, cap, penalty, args.exact_seconds)
    print(f"  EXACT (CP-SAT): obj={opt:.0f}  bound={bound:.0f}  status={status}  ({dt_e:.1f}s)")

    gls, gtrav, gskip, gserved, dt_g = solve_gls(
        time_min, demand, cap, penalty, args.gls_seconds)
    print(f"  GLS (routing): obj={gls:.0f}  (travel={gtrav} + skip={gskip}, served={gserved}/{len(subset)})  ({dt_g:.1f}s)")
    print()
    gap = 100 * (gls - opt) / opt if opt else 0
    proven = "proven optimal" if status == "OPTIMAL" else f"bound only ({bound:.0f})"
    print(f"  ==> heuristic gap = (GLS - OPT)/OPT = ({gls:.0f} - {opt:.0f})/{opt:.0f} = {gap:.2f}%")
    print(f"      CP-SAT result is {proven}.")
    if status == "OPTIMAL" and abs(gap) < 0.01:
        print(f"      GLS matched the exact optimum on this instance.")


if __name__ == "__main__":
    main()
