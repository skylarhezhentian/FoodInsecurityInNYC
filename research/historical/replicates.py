"""
replicates.py -- replicate solves behind the poster's Table 1 and Figure 2.

A single OR-Tools solve under a wall-clock limit varies by a few points from run to
run, which produced three visible inconsistencies: gamma=0 disagreed with Unweighted
(27.5% vs 29%), Table 1's Need-access disagreed with the sweep's gamma=1 point, and
the sweep appeared to double back past gamma=1. This script fixes all three:

  * every setting is solved R times, each with a different seeded +/-0.2% jitter on
    the skip penalties (ch_experiment.REP_JITTER), and reported as median and range;
  * Unweighted IS the equity policy at gamma=0 and Need-access IS gamma=1, so Table 1
    and the sweep come from the same solves and cannot disagree;
  * every solve uses the same time limit (the old sweep used 25s, Table 1 used 30s).

Metrics recorded per solve:
  served            breadth: number of recipient agencies served
  high_need_pct     % of demand served in the top need tercile (need_t == 2). Uses need
                    only -- no weight w, no access -- so no strategy optimizes it directly.
  nw_pct            need-weighted coverage, graded against the gamma=1 weights w_ref.
                    This IS the ratio need-access optimizes, so it is not neutral.
  travel_min        total fleet vehicle-minutes (driving + waiting; excludes dwell)
  delivered_lbs     pounds delivered

Out: replicates.json (raw + summary), replicates.md
"""
from __future__ import annotations
import argparse, json, statistics as st, time
from pathlib import Path
import ch_experiment as CHE
from pareto_frontier import smooth_w, base_cfg

HERE = Path(__file__).resolve().parent
FIXED = [("random_preference", "Random-preference"),
         ("need_only", "Need-only"),
         ("access_only", "Access-only")]
METRICS = ["served", "high_need_pct", "nw_pct", "travel_min", "delivered_lbs"]


def one_solve(cfg, world, policy, w_ref, den_ref):
    inst, depots, donors, pantries, P, O, D, time_min = world
    res = CHE.solve_policy(cfg, depots, donors, pantries, P, O, D, time_min,
                           inst["vehicles"], policy)
    if res is None:
        return None
    s = CHE.summarize(res, pantries, O, D, cfg)
    served = set(res["served"])
    dem = [p["demand_lbs"] for p in pantries]
    return {"served": s["served"],
            "high_need_pct": float(s["tier_coverage"][2]),
            "mid_need_pct": float(s["tier_coverage"][1]),
            "low_need_pct": float(s["tier_coverage"][0]),
            "nw_pct": round(100 * sum(w_ref[i] * dem[i] for i in served) / den_ref, 2),
            "travel_min": s["travel_min"],
            "delivered_lbs": s["delivered_load_lbs"],
            "served_idx": sorted(served)}


def summarize_runs(runs):
    out = {}
    for m in METRICS + ["mid_need_pct", "low_need_pct"]:
        v = [r[m] for r in runs]
        out[m] = {"median": st.median(v), "min": min(v), "max": max(v),
                  "mean": round(st.mean(v), 2), "n": len(v)}
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--time-limit", type=int, default=30)
    ap.add_argument("--reps", type=int, default=5)
    ap.add_argument("--max-pantries", type=int, default=None, help="smoke test only")
    ap.add_argument("--gammas", type=float, nargs="+",
                    default=[0.0, 0.25, 0.5, 0.75, 1.0, 1.5, 2.0, 3.0])
    args = ap.parse_args()

    cfg = base_cfg(args.time_limit)
    cfg["max_pantries"] = args.max_pantries
    world = CHE.load_world(cfg)
    pantries = world[3]
    # gamma=1 reference weights, recomputed rather than trusted from the instance file
    w_ref = [round(smooth_w(p["need_pct"], p["access_pct"], 1.0), 3) for p in pantries]
    den_ref = sum(w_ref[i] * p["demand_lbs"] for i, p in enumerate(pantries))

    settings = [(pol, lab, None) for pol, lab in FIXED] + \
               [("equity", f"gamma={g:g}", g) for g in args.gammas]
    total = len(settings) * args.reps
    out = {"config": {**cfg, "reps": args.reps, "rep_jitter": CHE.REP_JITTER},
           "settings": {}}
    t0 = time.time(); done = 0

    for pol, lab, g in settings:
        for i, p in enumerate(pantries):   # set w for this setting (only 'equity' reads it)
            p["w"] = round(smooth_w(p["need_pct"], p["access_pct"], g), 3) if g is not None else w_ref[i]
        runs = []
        for k in range(args.reps):
            c = dict(cfg); c["jitter_seed"] = 1 + k
            r = one_solve(c, world, pol, w_ref, den_ref)
            done += 1
            if r is None:
                print(f"  [{done}/{total}] {lab} rep{k}: NO SOLUTION", flush=True); continue
            r["rep"] = k; runs.append(r)
            eta = (time.time() - t0) / done * (total - done) / 60
            print(f"  [{done}/{total}] {lab:18s} rep{k}: served={r['served']:3d} "
                  f"high={r['high_need_pct']:5.1f}% nw={r['nw_pct']:5.1f}% "
                  f"travel={r['travel_min']:6d}  (eta {eta:4.1f} min)", flush=True)
        out["settings"][lab] = {"policy": pol, "gamma": g, "runs": runs,
                                "summary": summarize_runs(runs) if runs else None}
        (HERE / "replicates.json").write_text(json.dumps(out, indent=1))   # save as we go

    # ---------------- table ----------------
    def cell(lab, m, fmt):
        sm = out["settings"][lab]["summary"][m]
        return f"{fmt(sm['median'])} [{fmt(sm['min'])}-{fmt(sm['max'])}]"
    t1 = [("Unweighted (gamma=0)", "gamma=0"), ("Random-preference", "Random-preference"),
          ("Need-only", "Need-only"), ("Access-only", "Access-only"),
          ("Need-access (gamma=1)", "gamma=1")]
    L = [f"# Replicated strategy comparison ({args.reps} solves each, median [min-max])", "",
         "| metric | " + " | ".join(a for a, _ in t1) + " |", "|---|" + "---:|" * len(t1)]
    for m, name, fmt in [("served", "agencies served", lambda x: f"{x:.0f}"),
                         ("high_need_pct", "high-need tier %", lambda x: f"{x:.1f}"),
                         ("nw_pct", "need-weighted % (self-referential)", lambda x: f"{x:.1f}"),
                         ("travel_min", "travel (veh-min)", lambda x: f"{x:,.0f}"),
                         ("delivered_lbs", "delivered (lb)", lambda x: f"{x:,.0f}")]:
        L.append(f"| {name} | " + " | ".join(cell(lab, m, fmt) for _, lab in t1) + " |")
    L += ["", "## Gamma sweep (need-access)", "",
          "| gamma | served | high-need % | need-weighted % |", "|---:|---:|---:|---:|"]
    for g in args.gammas:
        lab = f"gamma={g:g}"
        L.append(f"| {g:g} | {cell(lab,'served',lambda x:f'{x:.0f}')} | "
                 f"{cell(lab,'high_need_pct',lambda x:f'{x:.1f}')} | "
                 f"{cell(lab,'nw_pct',lambda x:f'{x:.1f}')} |")
    (HERE / "replicates.md").write_text("\n".join(L) + "\n")
    print("\n" + "\n".join(L))
    print(f"\n[done] {done} solves in {(time.time()-t0)/60:.1f} min -> replicates.{{json,md}}")


if __name__ == "__main__":
    main()
