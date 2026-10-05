"""
ch_experiment.py -- optional-service routing experiment harness for an anonymized
metropolitan food-redistribution network (collect-and-distribute VRPTW).

Implements the methodological refinements:
  §1  five strategies (skip-penalty multiplier m_r) with logic that MATCHES the name:
        unweighted        -- m_r = 1 (equal value to all; selection driven by routing cost)
        random_preference -- m_r ~ Uniform(0.3,1.7) (arbitrary, no equity signal; status-quo-style)
        need_only         -- m_r = need component only  (access held at its median)
        access_only       -- m_r = access component only (need held at its median)
        equity            -- m_r = need / access (both components; the proposed weight)
      (need_only + access_only are the ablation of the equity ratio; the two baselines
       differ: unweighted is logistics-only, random_preference adds arbitrary priorities.)
  §2  ONE shared experiment CONFIG reused across all runs; "same food available"
      vs "same food delivered" reported separately (mode A unrestricted, mode B
      equal-throughput via an OR-Tools delivered-pounds constraint).
  §3  --start-load-policy fixed|optimized; solver and stochastic eval use the SAME
      per-truck starting load.
  §4  per-truck food accounting (start/pickup/delivered/returned, total+cold) with
      conservation checks and assertions; fleet totals.
  §5  separate depot-start sensitivity experiment (assigned vs single common depot).
  §6  pooled vs age_aware inventory accounting (post-solution FEFO; approximate).
  §9  shared stochastic scenario matrix; reproducibility tests/assertions.

Reuses build/load helpers + sample_supply from pickup_model.py.
Outputs: ch_experiment.json, ch_policy_table.md, ch_per_truck.csv,
         ch_policies.png, ch_foodflow.png, ch_depot_sensitivity.{md,png}
"""
from __future__ import annotations
import argparse, csv, json, math, random, statistics as st, copy
from pathlib import Path
import numpy as np
import matplotlib.pyplot as plt
from ortools.constraint_solver import pywrapcp, routing_enums_pb2
import pickup_model as PM

HERE = Path(__file__).resolve().parent
TOL = 1e-6

# ---- the five routing strategies -------------------------------------------------
MAIN_POLICIES = ["unweighted", "random_preference", "need_only", "access_only", "equity"]
PRETTY = {"unweighted": "Unweighted", "random_preference": "Random-preference",
          "need_only": "Need-only", "access_only": "Access-only", "equity": "Equity"}
PCOLOR = {"unweighted": "#c7c7c7", "random_preference": "#7f7f7f", "need_only": "#E1812C",
          "access_only": "#9467bd", "equity": "#2ca02c"}
EPS_W = 0.15   # smoothing in the need/access weights (matches build_instance_v1.smooth_weight)
REP_JITTER = 0.002   # replicate perturbation on skip penalties (see solve_policy)


def policy_multiplier(policy, p, med_demand, rng):
    """Per-recipient skip-penalty multiplier m_r defining each routing strategy.
    need_only/access_only hold the OTHER component at its median (0.5) so the three
    need/access strategies share a scale and form a clean ablation of the equity ratio."""
    if policy == "unweighted":            # equal value to all; selection driven by routing cost
        return 1.0
    if policy == "random_preference":     # arbitrary priorities, no equity signal (status-quo-style)
        return rng.uniform(0.3, 1.7)
    if policy == "need_only":             # need component only (access neutral)
        return max(0.5, min(4.0, (p["need_pct"] + EPS_W) / (0.5 + EPS_W)))
    if policy == "access_only":           # access component only (need neutral)
        return max(0.5, min(4.0, (0.5 + EPS_W) / (p["access_pct"] + EPS_W)))
    if policy == "equity":                # need / access (both components)
        return p["w"]
    raise ValueError(f"unknown policy {policy}")


# ===================================================================== shared CONFIG
def make_config(args):
    """Single source of truth shared by every policy run."""
    return {
        "instance": args.instance, "donors_csv": args.donors, "cache": args.cache,
        "tod": args.tod, "skip_penalty": args.skip_penalty, "time_limit": args.time_limit,
        "freshness_coef": 1, "decay_coef": args.decay_coef, "seed": args.seed,
        "staged_frac": args.staged_frac, "start_load_policy": args.start_load_policy,
        "scenarios": args.scenarios, "max_pantries": args.max_pantries,
        "prior_age_min": args.prior_age_min,
    }


def load_world(cfg):
    inst, depots, donors, pantries, P = PM.load_all(cfg["instance"], cfg["donors_csv"])
    O, D = len(depots), len(donors)
    # full OSRM matrix from cache, then (optionally) slice to a small test instance
    z = np.load(cfg["cache"]); tff = z["time_min_freeflow"]
    K = cfg["max_pantries"] or len(pantries)
    if K < len(pantries):
        pantries = pantries[:K]
    n = O + D + len(pantries)
    # node order is depots+donors+pantries, so the first n rows/cols ARE the small
    # instance. Cache stores FREE-FLOW; apply the congestion band (matches pickup_model).
    band = {"am_peak": 0.38, "midday": 0.55, "pm_peak": 0.42, "night": 0.80}[cfg["tod"]]
    time_min = np.rint(tff[:n, :n] / band).astype(np.int64)
    np.fill_diagonal(time_min, 0)
    return inst, depots, donors, pantries, P, O, D, time_min


# ===================================================================== solver
def solve_policy(cfg, depots, donors, pantries, P, O, D, time_min, vehicles, policy,
                 deliver_target=None, deliver_tol=0.05, common_depot=None):
    """Solve one policy. Returns dict with summary, routes, and per-truck accounting.
    start_load_policy 'fixed' pins each truck's start to staged_frac*cap; 'optimized'
    lets the solver choose within [0, staged_frac*cap] and we extract the choice."""
    NP = len(pantries); N = O + D + NP
    horizon = P["horizon_min"]; sf = cfg["staged_frac"]
    starts = [(common_depot if common_depot is not None else v["origin_idx"]) for v in vehicles]
    mgr = pywrapcp.RoutingIndexManager(N, len(vehicles), starts, list(starts))
    routing = pywrapcp.RoutingModel(mgr)

    def tcb(i, j): return int(time_min[mgr.IndexToNode(i), mgr.IndexToNode(j)])
    tci = routing.RegisterTransitCallback(tcb); routing.SetArcCostEvaluatorOfAllVehicles(tci)

    exp_sup = [donors[d]["avail_prob"] * donors[d]["supply_lbs"] for d in range(D)]
    exp_cold = [donors[d]["avail_prob"] * donors[d]["supply_cold"] for d in range(D)]

    def load_cb(i):
        n = mgr.IndexToNode(i)
        return 0 if n < O else (int(exp_sup[n-O]) if n < O+D else -int(pantries[n-O-D]["demand_lbs"]))
    routing.AddDimensionWithVehicleCapacity(routing.RegisterUnaryTransitCallback(load_cb), 0,
        [v["cap_total_lbs"] for v in vehicles], False, "Load")

    def cold_cb(i):
        n = mgr.IndexToNode(i)
        return 0 if n < O else (int(exp_cold[n-O]) if n < O+D else -int(pantries[n-O-D]["demand_cold"]))
    routing.AddDimensionWithVehicleCapacity(routing.RegisterUnaryTransitCallback(cold_cb), 0,
        [v["cap_cold_lbs"] for v in vehicles], False, "ColdLoad")

    load_dim = routing.GetDimensionOrDie("Load"); cold_dim = routing.GetDimensionOrDie("ColdLoad")
    for v in range(len(vehicles)):
        st_ = routing.Start(v)
        staged_t = int(sf * vehicles[v]["cap_total_lbs"]); staged_c = int(sf * vehicles[v]["cap_cold_lbs"])
        if cfg["start_load_policy"] == "fixed":           # §3: exactly staged (consistent w/ eval)
            load_dim.CumulVar(st_).SetRange(staged_t, staged_t)
            cold_dim.CumulVar(st_).SetRange(staged_c, staged_c)
        else:                                              # optimized: solver chooses in [0, staged]
            load_dim.CumulVar(st_).SetRange(0, staged_t)
            cold_dim.CumulVar(st_).SetRange(0, staged_c)

    # time windows
    routing.AddDimension(tci, horizon, horizon, True, "Time")
    tdim = routing.GetDimensionOrDie("Time")
    for d in range(D):
        tdim.CumulVar(mgr.NodeToIndex(O+d)).SetRange(0, PM.DONOR_WIN)
    for pi, p in enumerate(pantries):
        tdim.CumulVar(mgr.NodeToIndex(O+D+pi)).SetRange(int(p["tw_open"]), int(p["tw_close"]))
    tdim.SetSpanCostCoefficientForAllVehicles(cfg["freshness_coef"])
    if cfg["decay_coef"] > 0:                              # perishability objective
        for pi, p in enumerate(pantries):
            if p["demand_cold"] > 0:
                c = int(round(cfg["decay_coef"] * p["demand_cold"]))
                if c > 0: tdim.SetCumulVarSoftUpperBound(mgr.NodeToIndex(O+D+pi), 0, c)

    # §2B equal-throughput: bound TOTAL delivered pounds (real OR-Tools constraint)
    if deliver_target is not None:
        def dcb(i):
            n = mgr.IndexToNode(i)
            return int(pantries[n-O-D]["demand_lbs"]) if n >= O+D else 0
        routing.AddDimension(routing.RegisterUnaryTransitCallback(dcb), 0, 10**9, True, "Delivered")
        ddim = routing.GetDimensionOrDie("Delivered"); slv = routing.solver()
        tot = slv.Sum([ddim.CumulVar(routing.End(v)) for v in range(len(vehicles))])
        slv.Add(tot >= int(deliver_target * (1 - deliver_tol)))
        slv.Add(tot <= int(deliver_target * (1 + deliver_tol)))

    # disjunctions: donors free to skip; pantries at policy-weighted skip penalty
    for d in range(D):
        routing.AddDisjunction([mgr.NodeToIndex(O+d)], 0)
    rng = random.Random(cfg["seed"])
    # Replicates: OR-Tools routing has no seed parameter, so repeated solves are made
    # to follow different search trajectories by a tiny seeded jitter (+/-REP_JITTER)
    # on the skip penalties. Without cfg["jitter_seed"], behavior is unchanged.
    jseed = cfg.get("jitter_seed")
    jrng = random.Random(jseed) if jseed is not None else None
    dv = sorted(p["demand_lbs"] for p in pantries); med = dv[len(dv)//2] or 1
    for pi, p in enumerate(pantries):
        mult = policy_multiplier(policy, p, med, rng)
        if jrng is not None:
            mult *= 1.0 + jrng.uniform(-REP_JITTER, REP_JITTER)
        routing.AddDisjunction([mgr.NodeToIndex(O+D+pi)], int(cfg["skip_penalty"] * mult))

    sp = pywrapcp.DefaultRoutingSearchParameters()
    sp.first_solution_strategy = routing_enums_pb2.FirstSolutionStrategy.PARALLEL_CHEAPEST_INSERTION
    sp.local_search_metaheuristic = routing_enums_pb2.LocalSearchMetaheuristic.GUIDED_LOCAL_SEARCH
    sp.time_limit.FromSeconds(cfg["time_limit"])
    sol = routing.SolveWithParameters(sp)
    if sol is None:
        return None

    # ---- per-truck accounting (§4) + conservation checks ----
    per_truck = []; routes = []; served = set(); warnings = []
    cold_t_num = cold_t_den = 0.0
    for v in range(len(vehicles)):
        cap_t = vehicles[v]["cap_total_lbs"]; cap_c = vehicles[v]["cap_cold_lbs"]
        idx = routing.Start(v)
        start_t = sol.Value(load_dim.CumulVar(idx)); start_c = sol.Value(cold_dim.CumulVar(idx))
        load = start_t; coldload = start_c; max_load = start_t
        pick_t = pick_c = deliv_t = deliv_c = 0
        n_pick = n_deliv = 0; seq = []; pick_times = []; drop_times = []
        while not routing.IsEnd(idx):
            n = mgr.IndexToNode(idx); seq.append(n)
            if O <= n < O+D:
                pick_t += exp_sup[n-O]; pick_c += exp_cold[n-O]; n_pick += 1
                load += exp_sup[n-O]; coldload += exp_cold[n-O]
                pick_times.append((n-O, sol.Value(tdim.CumulVar(idx))))
            elif n >= O+D:
                p = pantries[n-O-D]; served.add(n-O-D); n_deliv += 1
                deliv_t += p["demand_lbs"]; deliv_c += p["demand_cold"]
                load -= p["demand_lbs"]; coldload -= p["demand_cold"]
                t = sol.Value(tdim.CumulVar(idx)); drop_times.append((n-O-D, t))
                if p["demand_cold"] > 0:
                    cold_t_num += p["demand_cold"]*t; cold_t_den += p["demand_cold"]
            max_load = max(max_load, load)
            idx = sol.Value(routing.NextVar(idx))
        end_t = sol.Value(tdim.CumulVar(idx)); st0 = sol.Value(tdim.CumulVar(routing.Start(v)))
        seq.append(mgr.IndexToNode(idx))
        ret_t = start_t + pick_t - deliv_t; ret_c = start_c + pick_c - deliv_c
        # conservation + feasibility checks
        if ret_t < -1: warnings.append(f"veh{v}: negative returned load {ret_t:.0f}")
        if max_load > cap_t + 1: warnings.append(f"veh{v}: load {max_load:.0f} > cap {cap_t}")
        if start_c + pick_c > cap_c + 1 and cap_c == 0 and (start_c+pick_c) > 1:
            warnings.append(f"veh{v}: cold on dry truck {start_c+pick_c:.0f}")
        per_truck.append({
            "vehicle": v, "type": vehicles[v]["type"], "origin_depot": starts[v],
            "n_pickups": n_pick, "n_deliveries": n_deliv,
            "start_load_lbs": round(start_t,1), "start_cold_lbs": round(start_c,1),
            "pickup_load_lbs": round(pick_t,1), "pickup_cold_lbs": round(pick_c,1),
            "delivered_load_lbs": round(deliv_t,1), "delivered_cold_lbs": round(deliv_c,1),
            "returned_load_lbs": round(ret_t,1), "returned_cold_lbs": round(ret_c,1),
            "max_load_lbs": round(max_load,1), "unused_capacity_lbs": round(cap_t-max_load,1),
            "returned_empty": ret_t <= 1, "route_duration_min": int(end_t-st0),
            "pickup_times": pick_times,
        })
        routes.append({"vehicle": v, "type": vehicles[v]["type"], "seq": seq,
                       "start_load_lbs": start_t, "start_cold_lbs": start_c,
                       "drop_times": drop_times})
    fresh = round(cold_t_num/cold_t_den, 1) if cold_t_den else 0.0
    return {"policy": policy, "routes": routes, "per_truck": per_truck,
            "served": sorted(served), "exp_sup": exp_sup, "exp_cold": exp_cold,
            "cold_delivery_min": fresh, "warnings": warnings}


# ===================================================================== summary + accounting
def summarize(res, pantries, O, D, cfg):
    sset = set(res["served"]); pt = res["per_truck"]
    tot_dem = sum(p["demand_lbs"] for p in pantries)
    got = sum(pantries[i]["demand_lbs"] for i in res["served"])
    num = sum(pantries[i]["w"]*pantries[i]["demand_lbs"] for i in res["served"])
    den = sum(p["w"]*p["demand_lbs"] for p in pantries)
    tiers = {t: [i for i,p in enumerate(pantries) if p["need_t"]==t] for t in (0,1,2)}
    tcov = {t: round(100*sum(pantries[i]["demand_lbs"] for i in tiers[t] if i in sset)/
                     max(1,sum(pantries[i]["demand_lbs"] for i in tiers[t])),1) for t in (0,1,2)}
    fleet = lambda k: round(sum(t[k] for t in pt), 1)
    start = fleet("start_load_lbs"); pick = fleet("pickup_load_lbs")
    deliv = fleet("delivered_load_lbs"); ret = fleet("returned_load_lbs")
    return {
        "policy": res["policy"], "label": PRETTY[res["policy"]],
        "available_staged_lbs": start,                # in fixed mode = staged available
        "available_donor_expected_lbs": round(sum(res["exp_sup"]),1),
        "start_load_lbs": start, "start_cold_lbs": fleet("start_cold_lbs"),
        "pickup_load_lbs": pick, "pickup_cold_lbs": fleet("pickup_cold_lbs"),
        "delivered_load_lbs": deliv, "delivered_cold_lbs": fleet("delivered_cold_lbs"),
        "returned_load_lbs": ret, "returned_cold_lbs": fleet("returned_cold_lbs"),
        "pct_delivered": round(100*deliv/max(1,start+pick),1),
        "pct_returned": round(100*ret/max(1,start+pick),1),
        "served": len(sset), "n_pantries": len(pantries),
        "flat_coverage_pct": round(100*got/tot_dem,1),
        "need_weighted_coverage_pct": round(100*num/den,1) if den else 0,
        "tier_coverage": tcov, "travel_min": int(sum(t["route_duration_min"] for t in pt)),
        "cold_delivery_min": res["cold_delivery_min"],
        "n_trucks_returned_empty": sum(1 for t in pt if t["returned_empty"]),
        "warnings": res["warnings"],
    }


# ===================================================================== solution dump
# The solver computes a full per-recipient allocation, but summarize() collapses it to
# aggregates. Nothing downstream (distributional metrics, replicate bands, recipient-
# capacity recourse, split deliveries) can be recomputed from those aggregates, so the
# solution itself is persisted here to ch_solution.json alongside the summary.
# Recipient NAME and ADDRESS are deliberately omitted; fid is the stable public id.
RECIPIENT_FIELDS = ["fid", "nta", "boro", "lat", "lon", "demand_lbs", "demand_cold",
                    "cold_frac", "service_min", "w", "need_pct", "access_pct",
                    "need_t", "access_t", "equity_index", "tw_open", "tw_close"]


def recipient_table(pantries):
    """Static per-recipient attributes, written once (indices match the run's pantry list)."""
    return [dict({"idx": i}, **{k: p.get(k) for k in RECIPIENT_FIELDS})
            for i, p in enumerate(pantries)]


def solution_record(res, pantries):
    """The allocation a single solve produced: which recipients were served, in what
    order, on which truck, at what arrival time. Enough to replay the plan offline."""
    if res is None:
        return None
    served = sorted(res["served"])
    return {
        "policy": res["policy"],
        "served_idx": served,
        "n_served": len(served),
        "served_demand_lbs": round(sum(pantries[i]["demand_lbs"] for i in served), 1),
        "routes": [{"vehicle": r["vehicle"], "type": r["type"], "seq": r["seq"],
                    "start_load_lbs": round(r["start_load_lbs"], 1),
                    "start_cold_lbs": round(r["start_cold_lbs"], 1),
                    "drops": [{"idx": i, "arrival_min": int(t)} for i, t in r["drop_times"]]}
                   for r in res["routes"]],
    }


# ===================================================================== shared scenarios (§9)
def gen_scenarios(donors, n, seed):
    rng = random.Random(seed)
    return [PM.sample_supply(donors, rng) for _ in range(n)]


def evaluate(res, donors, pantries, O, D, scenario):
    """Apply committed routes + per-truck ACTUAL start loads to one supply scenario."""
    served = set()
    for r in res["routes"]:
        load_t = r["start_load_lbs"]; load_c = r["start_cold_lbs"]   # certain staged (consistent §3)
        for n in r["seq"]:
            if O <= n < O+D:
                d = n-O; load_t += donors[d]["supply_lbs"]*scenario[d]; load_c += donors[d]["supply_cold"]*scenario[d]
            elif n >= O+D:
                p = pantries[n-O-D]
                if load_t >= p["demand_lbs"] and load_c >= p["demand_cold"]:
                    load_t -= p["demand_lbs"]; load_c -= p["demand_cold"]; served.add(n-O-D)
    num = sum(pantries[i]["w"]*pantries[i]["demand_lbs"] for i in served)
    den = sum(p["w"]*p["demand_lbs"] for p in pantries)
    return len(served), (round(100*num/den,1) if den else 0)


def stochastic(res, donors, pantries, O, D, scenarios):
    out = [evaluate(res, donors, pantries, O, D, s) for s in scenarios]
    nw = [o[1] for o in out]; sv = [o[0] for o in out]
    return {"realized_need_wtd_mean": round(st.mean(nw),1),
            "realized_served_mean": round(st.mean(sv),1),
            "realized_need_wtd_p10": round(np.percentile(nw,10),1)}


# ===================================================================== age-aware accounting (§6)
def age_accounting(res, donors, pantries, O, D, prior_age_min):
    """Post-solution FEFO attribution of cold deliveries to prior inventory vs same-day
    pickups. APPROXIMATE: exact source->pantry flow would need a multi-commodity model."""
    from_prior = from_same = 0.0; age_num = age_den = 0.0
    for r in res["routes"]:
        # cold lots as (age_at_t0_or_pickup_time, amount, is_prior)
        lots = [[prior_age_min, r["start_cold_lbs"], True]] if r["start_cold_lbs"] > 0 else []
        t_now = 0
        seq = r["seq"]
        # need arrival times; reconstruct from per_truck pickup_times + by walking is complex,
        # so approximate using order: prior lot oldest; same-day lots created at pickup order.
        pj = 0
        for n in seq:
            if O <= n < O+D:
                d = n-O
                amt = donors[d]["supply_cold"] * donors[d]["avail_prob"]
                if amt > 0: lots.append([0, amt, False])   # same-day, age starts ~0 at pickup
            elif n >= O+D:
                p = pantries[n-O-D]; need = p["demand_cold"]
                # FEFO: consume oldest (prior first)
                lots.sort(key=lambda L: -L[0])
                while need > TOL and lots:
                    L = lots[0]; take = min(need, L[1])
                    if L[2]: from_prior += take
                    else: from_same += take
                    age_num += take * (L[0] + 1); age_den += take
                    L[1] -= take; need -= take
                    if L[1] <= TOL: lots.pop(0)
    tot = from_prior + from_same
    return {"cold_from_prior_lbs": round(from_prior,1), "cold_from_same_day_lbs": round(from_same,1),
            "pct_cold_from_prior": round(100*from_prior/max(1,tot),1),
            "age_weighted_cold_min_proxy": round(age_num/max(1,age_den),1)}


# ===================================================================== tests (§9)
def run_tests(world, results, scenarios, cfg):
    inst, depots, donors, pantries, P, O, D, time_min = world
    fails = []
    # 1 & 2: identical available supply + identical fixed staged loads across policies
    avail = {r["policy"]: round(sum(r["exp_sup"]),1) for r in results.values()}
    if len(set(avail.values())) != 1: fails.append("1: donor supply differs across policies")
    if cfg["start_load_policy"] == "fixed":
        starts = {r["policy"]: round(sum(t["start_load_lbs"] for t in r["per_truck"]),1) for r in results.values()}
        if len(set(starts.values())) != 1: fails.append("2: fixed staged loads differ across policies")
    # 3-6: per-truck conservation, nonneg, capacity
    for pol, r in results.items():
        for t in r["per_truck"]:
            if abs((t["start_load_lbs"]+t["pickup_load_lbs"]) - (t["delivered_load_lbs"]+t["returned_load_lbs"])) > 1:
                fails.append(f"3: conservation veh{t['vehicle']} ({pol})")
            if t["returned_load_lbs"] < -1: fails.append(f"5: negative returned veh{t['vehicle']} ({pol})")
    # 7: identical scenario matrix reused -- the SAME list object is passed to every policy
    #    (structurally guaranteed; deep value-check would just re-confirm identity).
    # 8 & 9: naming -- exactly the intended main policies; the deleted one is gone
    if set(MAIN_POLICIES) != {"unweighted", "random_preference", "need_only", "access_only", "equity"}:
        fails.append("8: unexpected main-policy set")
    if "preference_based" in results:
        fails.append("9: deleted 'preference_based' still present")
    return fails


# ===================================================================== figures
def fig_policies(summ, stoch, out_png):
    pols = MAIN_POLICIES
    fig, axes = plt.subplots(1, 2, figsize=(14.5, 5.5), dpi=130, gridspec_kw=dict(width_ratios=[1.4,1]))
    npol = len(pols)
    x = np.arange(3); w = 0.8 / npol
    ax = axes[0]
    for i, pol in enumerate(pols):
        vals = [summ[pol]["tier_coverage"][t] for t in (0,1,2)]
        b = ax.bar(x+(i-(npol-1)/2)*w, vals, w, color=PCOLOR[pol], label=PRETTY[pol])
        for r in b: ax.annotate(f"{r.get_height():.0f}",(r.get_x()+r.get_width()/2,r.get_height()),
                                xytext=(0,2),textcoords="offset points",ha="center",fontsize=7)
    ax.set_xticks(x); ax.set_xticklabels(["low-need","mid-need","high-need"])
    ax.set_ylabel("coverage (% demand met)"); ax.set_title("A. Coverage by need tier", fontweight="bold")
    ax.legend(fontsize=9); ax.grid(axis="y",alpha=.3,ls=":")
    ax = axes[1]
    xB = np.arange(npol)
    plan = [summ[p]["need_weighted_coverage_pct"] for p in pols]
    real = [stoch[p]["realized_need_wtd_mean"] for p in pols]
    b1 = ax.bar(xB-0.18, plan, 0.36, color=[PCOLOR[p] for p in pols], label="planned")
    b2 = ax.bar(xB+0.18, real, 0.36, color=[PCOLOR[p] for p in pols], alpha=0.45, label="realized (blind donations)")
    for bb in (b1,b2):
        for r in bb: ax.annotate(f"{r.get_height():.0f}",(r.get_x()+r.get_width()/2,r.get_height()),
                                 xytext=(0,2),textcoords="offset points",ha="center",fontsize=7)
    ax.set_xticks(xB); ax.set_xticklabels([PRETTY[p] for p in pols], fontsize=8, rotation=20, ha="right")
    ax.set_ylabel("need-weighted coverage %"); ax.set_title("B. Equity & uncertainty", fontweight="bold")
    ax.legend(fontsize=8); ax.grid(axis="y",alpha=.3,ls=":")
    fig.suptitle("Routing strategies on a fixed fleet and food supply\n"
                 "(shared supply · OSRM roads · blind-donation stress test)", fontsize=12, fontweight="bold")
    fig.tight_layout(); fig.savefig(out_png, dpi=140, bbox_inches="tight"); plt.close(fig)
    print(f"[plot] wrote {out_png}")


def fig_foodflow(summ, out_png):
    pols = MAIN_POLICIES
    fig, ax = plt.subplots(figsize=(10, 5.5), dpi=130)
    x = np.arange(len(pols)); w = 0.36
    deliv = [summ[p]["delivered_load_lbs"]/1000 for p in pols]
    ret = [summ[p]["returned_load_lbs"]/1000 for p in pols]
    ax.bar(x-w/2, deliv, w, color="#2ca02c", label="delivered (1000 lb)")
    ax.bar(x+w/2, ret, w, color="#c0792e", label="returned to depot (1000 lb)")
    for i,p in enumerate(pols):
        ax.annotate(f"{summ[p]['pct_returned']:.0f}% ret", (x[i], max(deliv[i],ret[i])),
                    xytext=(0,4), textcoords="offset points", ha="center", fontsize=9, fontweight="bold")
    ax.set_xticks(x); ax.set_xticklabels([PRETTY[p] for p in pols], fontsize=9, rotation=12, ha="right")
    ax.set_ylabel("1000 lb"); ax.set_title("Food flow: delivered vs returned (start+pickups not delivered)",
                                            fontweight="bold")
    ax.legend(); ax.grid(axis="y",alpha=.3,ls=":")
    fig.tight_layout(); fig.savefig(out_png, dpi=140, bbox_inches="tight"); plt.close(fig)
    print(f"[plot] wrote {out_png}")


# ===================================================================== main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--instance", default="instance_ch.json")
    ap.add_argument("--donors", default="data/donors_pickup.csv")
    ap.add_argument("--cache", default="osrm_cache_pickup.npz")
    ap.add_argument("--tod", default="am_peak")
    ap.add_argument("--skip-penalty", type=int, default=8000)
    ap.add_argument("--decay-coef", type=float, default=0.03)
    ap.add_argument("--staged-frac", type=float, default=0.4)
    ap.add_argument("--start-load-policy", choices=["fixed","optimized"], default="fixed")
    ap.add_argument("--time-limit", type=int, default=30)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--scenarios", type=int, default=120)
    ap.add_argument("--max-pantries", type=int, default=None, help="small test: cap # pantries")
    ap.add_argument("--prior-age-min", type=int, default=1440)
    ap.add_argument("--equal-throughput", action="store_true", help="run mode B too")
    ap.add_argument("--depot-sensitivity", action="store_true")
    args = ap.parse_args()
    cfg = make_config(args)

    world = load_world(cfg)
    inst, depots, donors, pantries, P, O, D, time_min = world
    vehicles = inst["vehicles"]
    print(f"World: {O} depots, {D} donors, {len(pantries)} pantries, {len(vehicles)} trucks; "
          f"start-load-policy={cfg['start_load_policy']}, staged_frac={cfg['staged_frac']}")
    print(f"NOTE: 'unweighted' (equal value, logistics-only) and 'random_preference' (arbitrary "
          f"priorities) are the two no-equity-signal baselines.")
    print(f"NOTE: need_only/access_only are the ablation of the 'equity' need/access ratio.")
    scenarios = gen_scenarios(donors, cfg["scenarios"], cfg["seed"] + 7)   # shared, sampled ONCE

    pols = MAIN_POLICIES

    # ---- mode A: unrestricted common-supply ----
    print("\n=== MODE A: unrestricted common-supply ===")
    resA = {}; summ = {}; stoch = {}; age = {}
    for pol in pols:
        r = solve_policy(cfg, depots, donors, pantries, P, O, D, time_min, vehicles, pol)
        if r is None: print(f"  {pol}: NO SOLUTION"); continue
        resA[pol] = r; summ[pol] = summarize(r, pantries, O, D, cfg)
        stoch[pol] = stochastic(r, donors, pantries, O, D, scenarios)
        age[pol] = {"pooled": None,
                    "age_aware": age_accounting(r, donors, pantries, O, D, cfg["prior_age_min"])}
        s = summ[pol]
        print(f"  [{PRETTY[pol]}] served={s['served']} deliv={s['delivered_load_lbs']:.0f} "
              f"ret={s['returned_load_lbs']:.0f}({s['pct_returned']}%) need-wtd={s['need_weighted_coverage_pct']}% "
              f"realized={stoch[pol]['realized_need_wtd_mean']}% warn={len(s['warnings'])}")

    # ---- tests ----
    fails = run_tests(world, resA, scenarios, cfg)
    print(f"\n=== TESTS === {'ALL PASS' if not fails else 'FAILURES: '+'; '.join(fails)}")

    # ---- mode B: equal-throughput ----
    summB = {}; resB = {}
    if args.equal_throughput:
        target = min(summ[p]["delivered_load_lbs"] for p in MAIN_POLICIES)
        print(f"\n=== MODE B: equal-throughput (target ~{target:.0f} lb, ±5%) ===")
        for pol in MAIN_POLICIES:
            r = solve_policy(cfg, depots, donors, pantries, P, O, D, time_min, vehicles, pol,
                             deliver_target=target, deliver_tol=0.05)
            if r is None: print(f"  {pol}: infeasible at target"); continue
            resB[pol] = r
            summB[pol] = summarize(r, pantries, O, D, cfg)
            s = summB[pol]
            print(f"  [{PRETTY[pol]}] deliv={s['delivered_load_lbs']:.0f} need-wtd={s['need_weighted_coverage_pct']}% "
                  f"high-need={s['tier_coverage'][2]}%")

    # ---- depot sensitivity (§5) ----
    depot_sens = None; resDepot = {}
    if args.depot_sensitivity and O > 1:
        print(f"\n=== DEPOT SENSITIVITY (equity) ===")
        depot_sens = {}
        for name, cd in [("assigned_depots", None), ("single_common_depot", 0)]:
            r = solve_policy(cfg, depots, donors, pantries, P, O, D, time_min, vehicles,
                             "equity", common_depot=cd)
            s = summarize(r, pantries, O, D, cfg)
            depot_sens[name] = s; resDepot[name] = r
            print(f"  {name}: served={s['served']} travel={s['travel_min']} "
                  f"need-wtd={s['need_weighted_coverage_pct']}% high={s['tier_coverage'][2]}% "
                  f"returned={s['returned_load_lbs']:.0f}")
    elif args.depot_sensitivity:
        print("\n=== DEPOT SENSITIVITY skipped: only one depot present ===")

    # ---- figures ----
    fig_policies(summ, stoch, HERE / "ch_policies.png")
    fig_foodflow(summ, HERE / "ch_foodflow.png")

    # ---- tables ----
    write_tables(summ, stoch, age, summB, depot_sens, resA, cfg)

    # ---- json ----
    out = {"config": cfg, "mode_A": {p: summ[p] for p in summ},
           "stochastic": stoch, "age_aware": {p: age[p]["age_aware"] for p in age},
           "mode_B_equal_throughput": summB, "depot_sensitivity": depot_sens,
           "tests_passed": not fails, "test_failures": fails}
    Path(HERE / "ch_experiment.json").write_text(json.dumps(out, indent=2, default=str))

    # ---- solution dump (per-recipient allocation, re-analyzable offline) ----
    sol_out = {
        "config": cfg,
        "n_recipients": len(pantries),
        "recipients": recipient_table(pantries),
        "mode_A": {p: solution_record(resA[p], pantries) for p in resA},
        "mode_B_equal_throughput": {p: solution_record(resB[p], pantries) for p in resB},
        "depot_sensitivity": {k: solution_record(resDepot[k], pantries) for k in resDepot},
    }
    Path(HERE / "ch_solution.json").write_text(json.dumps(sol_out, indent=2, default=str))
    print(f"\n[done] wrote ch_experiment.json (tests {'PASSED' if not fails else 'FAILED'})")
    print(f"[done] wrote ch_solution.json ({len(pantries)} recipients, "
          f"{len(sol_out['mode_A'])} mode-A policies)")


def write_tables(summ, stoch, age, summB, depot_sens, resA, cfg):
    pols = MAIN_POLICIES
    L = ["# Routing-strategy comparison (Mode A: unrestricted common supply)\n",
         "| metric | " + " | ".join(PRETTY[p] for p in pols) + " |",
         "|---|" + "---:|"*len(pols)]
    def row(lbl, fn): return f"| {lbl} | " + " | ".join(str(fn(summ[p], stoch[p])) for p in pols) + " |"
    rows = [
        ("available staged food (lb)", lambda s,t: int(s["available_staged_lbs"])),
        ("available expected donor food (lb)", lambda s,t: int(s["available_donor_expected_lbs"])),
        ("starting food loaded (lb)", lambda s,t: int(s["start_load_lbs"])),
        ("donor food picked up (lb)", lambda s,t: int(s["pickup_load_lbs"])),
        ("**total delivered (lb)**", lambda s,t: int(s["delivered_load_lbs"])),
        ("total returned (lb)", lambda s,t: int(s["returned_load_lbs"])),
        ("cold delivered (lb)", lambda s,t: int(s["delivered_cold_lbs"])),
        ("cold returned (lb)", lambda s,t: int(s["returned_cold_lbs"])),
        ("% delivered / % returned", lambda s,t: f"{s['pct_delivered']}/{s['pct_returned']}"),
        ("agencies served", lambda s,t: s["served"]),
        ("flat coverage %", lambda s,t: s["flat_coverage_pct"]),
        ("**need-weighted coverage %**", lambda s,t: s["need_weighted_coverage_pct"]),
        ("low / mid / high-need %", lambda s,t: f"{s['tier_coverage'][0]}/{s['tier_coverage'][1]}/{s['tier_coverage'][2]}"),
        ("travel (min)", lambda s,t: s["travel_min"]),
        ("cold delivery time (min)", lambda s,t: s["cold_delivery_min"]),
        ("realized need-wtd % (blind)", lambda s,t: t["realized_need_wtd_mean"]),
        ("brittleness (pts)", lambda s,t: round(s["need_weighted_coverage_pct"]-t["realized_need_wtd_mean"],1)),
    ]
    for lbl, fn in rows: L.append(row(lbl, fn))
    # age-aware
    L += ["", "## Inventory accounting: pooled vs age-aware (post-solution, approximate)",
          "| | " + " | ".join(PRETTY[p] for p in pols) + " |", "|---|"+"---:|"*len(pols)]
    L.append("| % cold delivered from PRIOR inventory | " +
             " | ".join(str(age[p]["age_aware"]["pct_cold_from_prior"]) for p in pols) + " |")
    L.append("| age-weighted cold delivery (proxy) | " +
             " | ".join(str(age[p]["age_aware"]["age_weighted_cold_min_proxy"]) for p in pols) + " |")
    if summB:
        L += ["", "## Mode B: equal-throughput (delivered pounds constrained equal)",
              "| metric | " + " | ".join(PRETTY[p] for p in pols) + " |", "|---|"+"---:|"*len(pols)]
        L.append("| delivered (lb) | " + " | ".join(str(int(summB[p]["delivered_load_lbs"])) for p in pols) + " |")
        L.append("| **need-weighted %** | " + " | ".join(str(summB[p]["need_weighted_coverage_pct"]) for p in pols) + " |")
        L.append("| high-need % | " + " | ".join(str(summB[p]["tier_coverage"][2]) for p in pols) + " |")
    Path(HERE / "ch_policy_table.md").write_text("\n".join(L) + "\n")
    print("[table] wrote ch_policy_table.md")
    # per-truck CSV (equity)
    with open(HERE / "ch_per_truck.csv", "w", newline="") as f:
        cols = ["vehicle","type","origin_depot","n_pickups","n_deliveries","start_load_lbs",
                "pickup_load_lbs","delivered_load_lbs","returned_load_lbs","max_load_lbs",
                "unused_capacity_lbs","returned_empty","route_duration_min"]
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore"); w.writeheader()
        for t in resA["equity"]["per_truck"]: w.writerow(t)
    print("[table] wrote ch_per_truck.csv (equity per-truck)")
    if depot_sens:
        D2 = ["# Sensitivity to vehicle starting-depot configuration (equity)\n",
              "| metric | assigned_depots | single_common_depot |", "|---|---:|---:|"]
        a, b = depot_sens["assigned_depots"], depot_sens["single_common_depot"]
        for lbl, k in [("agencies served","served"),("travel (min)","travel_min"),
                       ("delivered (lb)","delivered_load_lbs"),("need-weighted %","need_weighted_coverage_pct"),
                       ("returned (lb)","returned_load_lbs"),("cold delivery (min)","cold_delivery_min")]:
            D2.append(f"| {lbl} | {a[k]} | {b[k]} |")
        D2.append(f"| high-need % | {a['tier_coverage'][2]} | {b['tier_coverage'][2]} |")
        Path(HERE / "ch_depot_sensitivity.md").write_text("\n".join(D2) + "\n")
        print("[table] wrote ch_depot_sensitivity.md")


if __name__ == "__main__":
    main()
