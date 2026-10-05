"""Layer-3 efficiency–equity Pareto frontier.

Sweep the equity-weight sharpness gamma. For each gamma we recompute every pantry's
weight w = clip(((need_pct+eps)/(access_pct+eps))**gamma, 0.5, 4.0) -- exactly the
instance builder's smooth_weight -- re-solve the equity policy, and read off two
gamma-INDEPENDENT outcomes: breadth (agencies served) and equity (high-need tier
coverage). The three other policies are overlaid as reference points so the discrete
policies can be located relative to the continuous frontier.

Outputs: pareto_frontier.png, pareto_frontier.md, pareto_frontier.json
"""
import argparse, json
from pathlib import Path
import numpy as np
import matplotlib.pyplot as plt
import ch_experiment as CHE

HERE = Path(__file__).resolve().parent


def base_cfg(time_limit):
    return {"instance": "instance_ch.json", "donors_csv": "data/donors_pickup.csv",
            "cache": "osrm_cache_pickup.npz", "tod": "am_peak", "max_pantries": None,
            "skip_penalty": 8000, "time_limit": time_limit, "freshness_coef": 1,
            "decay_coef": 0.03, "seed": 42, "staged_frac": 0.4,
            "start_load_policy": "fixed", "scenarios": 1, "prior_age_min": 1440}


def smooth_w(need_pct, access_pct, gamma, eps=0.15, lo=0.5, hi=4.0):
    return max(lo, min(hi, ((need_pct + eps) / (access_pct + eps)) ** gamma))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--time-limit", type=int, default=25)
    ap.add_argument("--gammas", type=float, nargs="+",
                    default=[0.0, 0.25, 0.5, 0.75, 1.0, 1.5, 2.0, 3.0])
    args = ap.parse_args()
    cfg = base_cfg(args.time_limit)
    inst, depots, donors, pantries, P, O, D, time_min = CHE.load_world(cfg)
    vehicles = inst["vehicles"]
    w_ref = [p["w"] for p in pantries]                  # gamma=1 reference
    dem = [p["demand_lbs"] for p in pantries]
    den_ref = sum(w_ref[i] * dem[i] for i in range(len(pantries)))

    rows = []
    for g in args.gammas:
        for p in pantries:
            p["w"] = round(smooth_w(p["need_pct"], p["access_pct"], g), 3)
        res = CHE.solve_policy(cfg, depots, donors, pantries, P, O, D, time_min,
                               vehicles, "equity")
        s = CHE.summarize(res, pantries, O, D, cfg)
        served_set = set(res["served"])
        nw_ref = 100 * sum(w_ref[i] * dem[i] for i in served_set) / den_ref
        rows.append({"gamma": g, "served": s["served"],
                     "delivered": int(s["delivered_load_lbs"]),
                     "high_need_cov": s["tier_coverage"][2],
                     "mid": s["tier_coverage"][1], "low": s["tier_coverage"][0],
                     "nw_ref": round(nw_ref, 1)})
        print(rows[-1])
    for i, p in enumerate(pantries):
        p["w"] = w_ref[i]

    ref = json.loads((HERE / "ch_experiment.json").read_text())["mode_A"]
    others = {k: (ref[k]["served"], float(ref[k]["tier_coverage"]["2"]))
              for k in ("random_preference", "unweighted", "need_only", "access_only")}

    # ---------- figure ----------
    fig, ax = plt.subplots(figsize=(9.5, 6.5), dpi=130)
    xs = [r["served"] for r in rows]; ys = [r["high_need_cov"] for r in rows]
    ax.plot(xs, ys, "-o", color="#2ca02c", lw=2, zorder=3, label="equity (γ sweep)")
    for r in rows:
        ax.annotate(f"γ={r['gamma']:g}", (r["served"], r["high_need_cov"]),
                    xytext=(5, 5), textcoords="offset points", fontsize=8, color="#1a661a")
    mk = {"random_preference": ("#7f7f7f", "Random-preference"), "unweighted": ("#c7c7c7", "Unweighted"),
          "need_only": ("#E1812C", "Need-only"), "access_only": ("#9467bd", "Access-only")}
    for k, (sv, tc) in others.items():
        ax.scatter([sv], [tc], c=mk[k][0], s=140, marker="D", edgecolor="k", zorder=4,
                   label=mk[k][1])
        ax.annotate(mk[k][1], (sv, tc), xytext=(7, -11), textcoords="offset points",
                    fontsize=8)
    ax.set_xlabel("breadth  →  agencies served")
    ax.set_ylabel("equity  →  high-need tier coverage (%)")
    ax.set_title("Efficiency–equity frontier: the equity sharpness γ traces a tradeoff curve\n"
                 "(discrete policies shown as reference points)", fontweight="bold", fontsize=11)
    ax.grid(alpha=.3, ls=":"); ax.legend(fontsize=9, loc="best")
    fig.tight_layout()
    out = HERE / "pareto_frontier.png"
    fig.savefig(out, dpi=140, bbox_inches="tight"); plt.close(fig)
    print("[plot] wrote", out)

    L = ["# Efficiency–equity Pareto frontier (equity, γ sweep)\n",
         "| γ | agencies served | delivered (lb) | high-need % | mid % | low % | need-wtd % (γ=1 ref) |",
         "|---:|---:|---:|---:|---:|---:|---:|"]
    for r in rows:
        L.append(f"| {r['gamma']:g} | {r['served']} | {r['delivered']} | {r['high_need_cov']} "
                 f"| {r['mid']} | {r['low']} | {r['nw_ref']} |")
    (HERE / "pareto_frontier.md").write_text("\n".join(L) + "\n")
    (HERE / "pareto_frontier.json").write_text(json.dumps({"rows": rows, "others": others}, indent=2))
    print("[table] wrote pareto_frontier.md / .json")


if __name__ == "__main__":
    main()
