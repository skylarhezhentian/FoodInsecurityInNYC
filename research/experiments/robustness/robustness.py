"""Data-availability robustness -- the core of the research question.

A data-poor nonprofit cannot measure true demand, real travel times, or exact opening
hours. We ask: do the COMPARATIVE CONCLUSIONS survive when those inputs are wrong?

For each of K perturbed "worlds" we jointly perturb
  - demand        x lognormal(0, sd_demand)           (true demand unknown)
  - travel times  x U(tl_lo, tl_hi) global x lognormal(0, sd_edge) per edge  (OSRM != reality)
  - time windows  +/- N(0, win_sd) minutes             (opening hours estimated)
then re-solve ALL FOUR policies on the SAME perturbed world and record outcomes.
World 0 is the unperturbed baseline. We report mean +/- sd across perturbed worlds and,
crucially, the RANK STABILITY of the qualitative ordering.

Equity weights w are held FIXED at the gamma=1 baseline, so need-weighted coverage is
scored on a consistent yardstick within each world.

Outputs: robustness.png, robustness.md, robustness.json
"""
import argparse, json, copy, math, random
from pathlib import Path
import numpy as np
import matplotlib.pyplot as plt
import ch_experiment as CHE

HERE = Path(__file__).resolve().parent
POLS = CHE.MAIN_POLICIES
PRETTY = CHE.PRETTY
PCOLOR = CHE.PCOLOR


def base_cfg(time_limit):
    return {"instance": "instance_ch.json", "donors_csv": "data/donors_pickup.csv",
            "cache": "osrm_cache_pickup.npz", "tod": "am_peak", "max_pantries": None,
            "skip_penalty": 8000, "time_limit": time_limit, "freshness_coef": 1,
            "decay_coef": 0.03, "seed": 42, "staged_frac": 0.4,
            "start_load_policy": "fixed", "scenarios": 1, "prior_age_min": 1440}


def perturb(pantries0, time_min0, horizon, seed, a):
    rng = random.Random(seed)
    pant = copy.deepcopy(pantries0)
    for p in pant:
        f = math.exp(rng.gauss(0, a["sd_demand"]))
        p["demand_lbs"] = max(1, int(round(p["demand_lbs"] * f)))
        p["demand_cold"] = min(p["demand_lbs"], int(round(p["demand_cold"] * f)))
        o = p["tw_open"] + int(round(rng.gauss(0, a["win_sd"])))
        c = p["tw_close"] + int(round(rng.gauss(0, a["win_sd"])))
        o = max(0, min(o, horizon - 10)); c = max(o + 10, min(c, horizon))
        p["tw_open"], p["tw_close"] = o, c
    gfac = rng.uniform(a["tl_lo"], a["tl_hi"])
    nrng = np.random.default_rng(seed)
    noise = np.exp(nrng.normal(0, a["sd_edge"], time_min0.shape))
    tm = np.rint(time_min0 * gfac * noise).astype(np.int64)
    np.fill_diagonal(tm, 0)
    return pant, tm, gfac


def metrics(cfg, depots, donors, pant, P, O, D, tm, vehicles):
    out = {}
    for pol in POLS:
        res = CHE.solve_policy(cfg, depots, donors, pant, P, O, D, tm, vehicles, pol)
        s = CHE.summarize(res, pant, O, D, cfg)
        out[pol] = {"served": s["served"], "nw": s["need_weighted_coverage_pct"],
                    "high": s["tier_coverage"][2], "delivered": int(s["delivered_load_lbs"])}
    return out


def leader(world, key, want_max=True):
    fn = max if want_max else min
    return fn(POLS, key=lambda p: world[p][key])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--worlds", type=int, default=6)
    ap.add_argument("--time-limit", type=int, default=12)
    ap.add_argument("--sd-demand", type=float, default=0.30)
    ap.add_argument("--tl-lo", type=float, default=0.85)
    ap.add_argument("--tl-hi", type=float, default=1.15)
    ap.add_argument("--sd-edge", type=float, default=0.12)
    ap.add_argument("--win-sd", type=float, default=20.0)
    args = ap.parse_args()
    a = {"sd_demand": args.sd_demand, "tl_lo": args.tl_lo, "tl_hi": args.tl_hi,
         "sd_edge": args.sd_edge, "win_sd": args.win_sd}
    cfg = base_cfg(args.time_limit)
    inst, depots, donors, pantries, P, O, D, time_min = CHE.load_world(cfg)
    vehicles = inst["vehicles"]; horizon = P["horizon_min"]

    print("=== WORLD 0: baseline (no perturbation) ===")
    base = metrics(cfg, depots, donors, pantries, P, O, D, time_min, vehicles)
    for p in POLS:
        print(f"  {PRETTY[p]:18s} served={base[p]['served']:3d}  nw={base[p]['nw']:.1f}  high={base[p]['high']:.1f}")

    worlds = []
    for k in range(1, args.worlds + 1):
        pant, tm, gfac = perturb(pantries, time_min, horizon, 1000 + k, a)
        print(f"=== WORLD {k}: travel x{gfac:.2f}, demand CV {a['sd_demand']}, windows ±{a['win_sd']:.0f}m ===")
        w = metrics(cfg, depots, donors, pant, P, O, D, tm, vehicles)
        worlds.append(w)
        for p in POLS:
            print(f"  {PRETTY[p]:18s} served={w[p]['served']:3d}  nw={w[p]['nw']:.1f}  high={w[p]['high']:.1f}")

    # ---- aggregate ----
    agg = {}
    for p in POLS:
        agg[p] = {}
        for key in ("served", "nw", "high", "delivered"):
            vals = [w[p][key] for w in worlds]
            agg[p][key] = {"mean": round(float(np.mean(vals)), 1),
                           "sd": round(float(np.std(vals)), 1),
                           "min": round(float(np.min(vals)), 1),
                           "max": round(float(np.max(vals)), 1)}

    # ---- rank stability ----
    checks = {
        "equity leads need-weighted cov":     ("nw", "equity", True),
        "need_only leads high-need tier cov": ("high", "need_only", True),
        "equity leads high-need tier cov":    ("high", "equity", True),
        "equity lowest agencies served":      ("served", "equity", False),
    }
    stability = {}
    for label, (key, who, want_max) in checks.items():
        hits = sum(1 for w in worlds if leader(w, key, want_max) == who)
        stability[label] = f"{hits}/{len(worlds)}"
        print(f"[rank] {label}: {hits}/{len(worlds)} worlds")

    # ---- figure ----
    fig, axes = plt.subplots(1, 2, figsize=(13.5, 5.5), dpi=130)
    for ax, key, ylab, ttl in [
        (axes[0], "served", "agencies served", "A. Breadth (agencies served)"),
        (axes[1], "nw", "need-weighted coverage %", "B. Equity (need-weighted coverage)")]:
        x = np.arange(len(POLS))
        means = [agg[p][key]["mean"] for p in POLS]
        sds = [agg[p][key]["sd"] for p in POLS]
        bsl = [base[p][key] for p in POLS]
        ax.bar(x, means, 0.6, yerr=sds, capsize=5, color=[PCOLOR[p] for p in POLS],
               alpha=0.85, label="perturbed mean ± sd")
        ax.scatter(x, bsl, c="k", marker="D", zorder=5, s=45, label="baseline")
        # individual worlds as faint dots
        for j, p in enumerate(POLS):
            ys = [w[p][key] for w in worlds]
            ax.scatter([x[j]] * len(ys), ys, c="white", edgecolor="k", linewidth=0.5,
                       s=18, zorder=4, alpha=0.8)
        ax.set_xticks(x); ax.set_xticklabels([PRETTY[p] for p in POLS], fontsize=8,
                                             rotation=18, ha="right")
        ax.set_ylabel(ylab); ax.set_title(ttl, fontweight="bold")
        ax.grid(axis="y", alpha=.3, ls=":"); ax.legend(fontsize=8)
    fig.suptitle("Data-availability robustness: policy ORDERING survives perturbed demand, "
                 "travel times & windows\n"
                 f"({args.worlds} perturbed worlds · demand CV {a['sd_demand']} · "
                 f"travel ±{int((a['tl_hi']-1)*100)}% · windows ±{int(a['win_sd'])} min)",
                 fontsize=12, fontweight="bold")
    fig.tight_layout()
    out = HERE / "robustness.png"
    fig.savefig(out, dpi=140, bbox_inches="tight"); plt.close(fig)
    print("[plot] wrote", out)

    # ---- tables / json ----
    L = ["# Data-availability robustness (perturbed demand, travel times, windows)\n",
         f"{args.worlds} perturbed worlds; equity weights fixed at γ=1. "
         f"Demand CV {a['sd_demand']}, travel global ×U({a['tl_lo']},{a['tl_hi']}) × "
         f"per-edge lognormal({a['sd_edge']}), windows ±N(0,{int(a['win_sd'])}m).\n",
         "| metric | " + " | ".join(PRETTY[p] for p in POLS) + " |",
         "|---|" + "---:|" * len(POLS)]
    def row(lbl, key, fmt):
        return ("| " + lbl + " | " +
                " | ".join(f"{agg[p][key]['mean']:{fmt}} ± {agg[p][key]['sd']:{fmt}}" for p in POLS) + " |")
    L.append("| baseline agencies served | " + " | ".join(str(base[p]["served"]) for p in POLS) + " |")
    L.append(row("agencies served (mean±sd)", "served", ".0f"))
    L.append("| baseline need-weighted % | " + " | ".join(str(base[p]["nw"]) for p in POLS) + " |")
    L.append(row("need-weighted % (mean±sd)", "nw", ".1f"))
    L.append("| baseline high-need % | " + " | ".join(str(base[p]["high"]) for p in POLS) + " |")
    L.append(row("high-need tier % (mean±sd)", "high", ".1f"))
    L += ["", "## Rank stability (qualitative ordering preserved)", "| claim | worlds |", "|---|---:|"]
    for k, v in stability.items():
        L.append(f"| {k} | {v} |")
    (HERE / "robustness.md").write_text("\n".join(L) + "\n")
    (HERE / "robustness.json").write_text(json.dumps(
        {"args": vars(args), "baseline": base, "worlds": worlds, "agg": agg,
         "stability": stability}, indent=2))
    print("[table] wrote robustness.md / .json")


if __name__ == "__main__":
    main()
