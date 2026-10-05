"""
run_pipeline.py -- Execute the full estimation pipeline end-to-end.

Outputs:
    data/per_donor_estimates.csv   per-donor table (Tier A/B + tail aggregate)
    data/results.json              machine-readable results bundle
    stdout                         human-readable research report

Run:  .venv/bin/python src/run_pipeline.py
"""
from __future__ import annotations
import os, json, csv
import numpy as np

import data as D
import model as M

OUT = os.path.join(os.path.dirname(__file__), "..", "data")
os.makedirs(OUT, exist_ok=True)


def banner(t):
    print("\n" + "=" * 78 + f"\n{t}\n" + "=" * 78)


def main():
    known = D.KNOWN_DONORS
    tier_b = D.build_tier_b()
    known_lbs = [d[1] for d in known]

    # ---- S2 shape ---------------------------------------------------------
    banner("S2  DISTRIBUTION SHAPE (from 12 published anchors)")
    shape = M.fit_shape(known_lbs)
    ci = M.bootstrap_shape(known_lbs)
    print(f"  published total (Tier A)      : {shape['total_lbs']:>14,.0f} lbs")
    print(f"  log-normal  mu={shape['lognormal']['mu']:.3f}  sigma={shape['lognormal']['sigma']:.3f}")
    print(f"  log-normal  median            : {shape['lognormal']['median']:>14,.0f} lbs")
    print(f"  log-normal  mean              : {shape['lognormal']['mean']:>14,.0f} lbs")
    print(f"  power-law   alpha             : {shape['powerlaw']['alpha']:.3f}  "
          f"(R^2={shape['powerlaw']['r2']:.3f})   95% CI [{ci['alpha'][0]:.2f}, {ci['alpha'][1]:.2f}]")
    print(f"  Gini                          : {shape['gini']:.3f}            95% CI [{ci['gini'][0]:.2f}, {ci['gini'][1]:.2f}]")
    print(f"  top-1 share (Amazon)          : {shape['top1_share']:.1%}           95% CI [{ci['top1_share'][0]:.0%}, {ci['top1_share'][1]:.0%}]")
    print(f"  top-3 share                   : {shape['top3_share']:.1%}")

    # ---- S3 category table ------------------------------------------------
    banner("S3  CATEGORY RECOVERY-RATE TABLE (portable artifact)")
    cat = M.category_recovery_table(known, tier_b)
    print(f"  {'category':<18}{'n_known':>8}{'anchor_mean':>14}{'n_tierB':>8}{'rate_lbs/donor':>16}")
    for c, r in sorted(cat.items(), key=lambda kv: -(kv[1]['rate_lbs_per_donor'])):
        am = f"{r['anchored_mean_lbs']:,.0f}" if r['anchored_mean_lbs'] else "-"
        print(f"  {c:<18}{r['n_known']:>8}{am:>14}{r['n_tier_b']:>8}{r['rate_lbs_per_donor']:>16,.0f}")

    # ---- S4 reconciliation ------------------------------------------------
    banner("S4  RECONCILIATION TO CONTROL TOTAL (raking, A fixed)")
    rec = M.reconcile(known, tier_b, D.CONTROL_TOTAL_LBS, shape)
    print(f"  control total T               : {rec['control_total']:>14,.0f} lbs")
    print(f"  A  published top-12           : {rec['A_published']:>14,.0f} lbs  ({rec['A_share']:.1%})")
    print(f"  B  named latent ({len(tier_b)} donors)   : {rec['B_named_latent']:>14,.0f} lbs  ({rec['B_share']:.1%})")
    print(f"  C  unlisted tail              : {rec['C_unlisted_tail']:>14,.0f} lbs  ({rec['C_share']:.1%})")
    pl = (">500,000 (diverges; alpha~1)" if rec["n_tail_powerlaw_diverged"]
          else f"{rec['n_tail_powerlaw']:,}")
    print(f"  implied unlisted-donor count  : flat={rec['n_tail_flat']:,.0f}   power-law={pl}")
    print(f"  implied TOTAL donor count     : ~{rec['n_donors_total_flat']:,}  (flat-rate basis)")

    # ---- S5 validation ----------------------------------------------------
    banner("S5  VALIDATION")
    loo = M.loo_shape_validation(known_lbs)
    print("  V2 leave-one-out (rank-size shape):")
    print(f"     median |log error|         : {loo['median_abs_log_err']:.3f}  "
          f"(=> typical x{np.exp(loo['median_abs_log_err']):.2f} multiplicative error)")
    print(f"     RMSE(log)                  : {loo['rmse_log']:.3f}")
    print(f"     Spearman rank corr         : {loo['spearman_rank_corr']:.3f}")
    xo = M.cross_org_reconciliation(shape, D.FBNYC_FY25, D.USD_PER_LB_2025)
    print("  V3 cross-organisation reconciliation (vs Food Bank NYC audit):")
    print(f"     CH top-12 implied $ value  : ${xo['ch_top12_value_usd']:,.0f}  (@ ${xo['usd_per_lb']}/lb)")
    print(f"     CH top-12 vs FBNYC donated : {xo['ch_as_pct_of_fbnyc_donated']:.0%} of FBNYC's donated-food channel")

    # ---- S5 transfer demo -------------------------------------------------
    banner("S5  TRANSFER DEMO -- a new food bank with NO donor list")
    # Hypothetical mid-size food bank: 40M lbs/yr; business mix from a notional
    # Census County Business Patterns pull (counts of donor-eligible firms).
    new_org_total = 40_000_000
    # Notional donor-eligible firm counts for a mid-size metro (the kind of
    # numbers a Census County Business Patterns pull by NAICS would yield).
    biz_mix = {"Supermarkets": 12, "Wholesale": 8, "Manufacturers": 6,
               "Farms": 20, "Restaurants": 120, "Bakery": 25, "Hotels": 15,
               "Caterer": 20, "Quickservice": 50, "Corporate": 5,
               "Nonprofit & Gov": 8, "Religious": 60, "Special Events": 5}
    # Supermarkets/Wholesale need a rate; reuse anchored means as their prior.
    pri = dict(M.PRIOR_LBS_PER_DONOR)
    pri.setdefault("Supermarkets", 1_500_000)   # ~ anchored supermarket mean
    tr = M.transfer_to_new_org(new_org_total, biz_mix, priors=pri)
    print(f"  new-org throughput            : {tr['total_lbs']:>14,.0f} lbs")
    print(f"  B modelled from business mix  : {tr['B_named_modelled']:>14,.0f} lbs  ({tr['B_share']:.1%})")
    print(f"  C unlisted tail (residual)    : {tr['C_unlisted_tail']:>14,.0f} lbs  ({tr['C_share']:.1%})")
    print(f"  implied unlisted-donor count  : ~{tr['n_tail_flat']:,.0f}")

    # ---- S5 sensitivity ---------------------------------------------------
    banner("S5  SENSITIVITY SWEEP  (control total x prior scale x tail size)")
    sens = M.sensitivity(known, tier_b, shape,
                         totals=list(D.CONTROL_TOTAL_SENSITIVITY),
                         prior_scales=[0.5, 1.0, 1.5],
                         tail_sizes=[15_000, 20_000, 30_000])
    print(f"  {'T(lbs)':>10}{'prior_x':>9}{'tail_lbs':>10}{'C(lbs)':>14}{'C_share':>9}{'n_tail':>10}")
    for r in sens:
        print(f"  {r['control_total']:>10,.0f}{r['prior_scale']:>9.1f}{r['tail_lbs']:>10,.0f}"
              f"{r['C']:>14,.0f}{r['C_share']:>9.1%}{r['n_tail_flat']:>10,.0f}")

    # ---- write per-donor CSV ---------------------------------------------
    csv_path = os.path.join(OUT, "per_donor_estimates.csv")
    with open(csv_path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["tier", "name", "category", "est_lbs", "lo_lbs", "hi_lbs",
                    "est_value_usd", "source"])
        for name, lbs, c, _t in known:
            w.writerow(["A", name, c, lbs, lbs, lbs,
                        round(lbs * D.USD_PER_LB_2025), "published"])
        for p in rec["per_donor_tier_b"]:
            w.writerow(["B", p["name"], p["category"],
                        round(p["est_lbs"]), round(p["lo_lbs"]), round(p["hi_lbs"]),
                        round(p["est_lbs"] * D.USD_PER_LB_2025), "category-prior"])
        w.writerow(["C", f"<unlisted tail: ~{rec['n_tail_flat']:,.0f} donors>",
                    "Mixed", round(rec["C_unlisted_tail"]), "", "",
                    round(rec["C_unlisted_tail"] * D.USD_PER_LB_2025), "residual-rake"])
    print(f"\n  wrote {csv_path}")

    # ---- write results bundle --------------------------------------------
    bundle = {
        "shape": shape, "shape_ci": ci, "category_table": cat,
        "reconciliation": {k: v for k, v in rec.items() if k != "per_donor_tier_b"},
        "validation_loo": loo, "validation_cross_org": xo,
        "transfer_demo": tr, "sensitivity": sens,
        "constants": {"usd_per_lb_2025": D.USD_PER_LB_2025,
                      "lbs_per_meal": D.LBS_PER_MEAL,
                      "control_total_lbs": D.CONTROL_TOTAL_LBS},
    }
    json_path = os.path.join(OUT, "results.json")
    with open(json_path, "w") as f:
        json.dump(bundle, f, indent=2, default=float)
    print(f"  wrote {json_path}")
    return bundle


if __name__ == "__main__":
    main()
