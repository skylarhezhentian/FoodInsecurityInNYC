"""
model.py -- Estimation core for donor-volume modelling (numpy only).

Pure computation: no I/O, no plotting, no scipy/pandas.  Every function maps to
a numbered step in the methodology writeup:

    S2  fit_shape()              distribution shape from the 12 anchors
    S3  category_recovery_table()per-category expected lbs/donor (portable)
    S4  reconcile()             rake A + B + C to the control total
    S5  transfer_to_new_org()   apply portable artifacts with no donor list
        loo_shape_validation()  leave-one-out predictive check
        sensitivity()           control-total / prior / tail-size sweep
        bootstrap_shape()       sampling uncertainty on shape metrics

Statistics implemented by hand (lognormal MLE, OLS rank-size, Gini) because the
host interpreter's stdlib `pydoc` is corrupted, which breaks scipy.stats import.
"""
from __future__ import annotations
import numpy as np

Z95 = 1.959964  # standard normal 0.975 quantile (hard-coded; no scipy)

# ---------------------------------------------------------------------------
# S3 priors -- expected lbs/yr per donor for Tier-B categories.
# ---------------------------------------------------------------------------
# These are ORDER-OF-MAGNITUDE priors grounded in sector surplus logic
# (large packaged manufacturers and produce wholesalers >> single-site
# restaurants / houses of worship).  They are ASSUMPTIONS, not fitted values;
# the writeup (S3) documents the rationale and the sensitivity sweep (S5)
# stress-tests them at +/-50%.  Single Tier-A anchors in these categories
# (Amazon, Baldor, Pret) are mega-outliers and are deliberately NOT used to set
# the typical-donor rate.
PRIOR_LBS_PER_DONOR = {
    "Manufacturers":  250_000,  # episodic but very large packaged-goods loads
    "Wholesale":      400_000,  # specialty distributors (smaller than Baldor flagship)
    "Farms":          150_000,  # bulk produce / gleaning, seasonal
    "Nonprofit & Gov":120_000,  # redistributors (Sharing Excess, FarmLink): large, episodic
    "Corporate":      120_000,  # non-Amazon corporate food/logistics donors
    "Quickservice":   120_000,  # chain QSR footprints (Pret-like, smaller)
    "Bakery":          35_000,
    "Hotels":          25_000,
    "Special Events":  25_000,
    "Caterer":         20_000,
    "Restaurants":     15_000,
    "Religious":       10_000,
}

# Average annual lbs for a donor in the UNLISTED tail (Tier C).  A small
# retailer / single food-drive contributor.  Parameterised; swept in S5.
DEFAULT_TAIL_LBS = 20_000


# ===========================================================================
# numpy-only statistics helpers
# ===========================================================================
def lognormal_mle(x):
    """MLE of a log-normal: returns dict(mu, sigma, median, mean) on raw scale."""
    x = np.asarray(x, float)
    lx = np.log(x)
    mu = lx.mean()
    sigma = lx.std(ddof=0)
    return {
        "mu": mu, "sigma": sigma,
        "median": float(np.exp(mu)),
        "mean": float(np.exp(mu + 0.5 * sigma**2)),
    }


def ols(x, y):
    """Ordinary least squares y = a + b x. Returns (b, a, r2)."""
    x = np.asarray(x, float); y = np.asarray(y, float)
    b, a = np.polyfit(x, y, 1)
    yhat = a + b * x
    ss_res = np.sum((y - yhat) ** 2)
    ss_tot = np.sum((y - y.mean()) ** 2)
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else float("nan")
    return float(b), float(a), float(r2)


def powerlaw_ranksize(x):
    """Fit rank-size law  log y_(k) = logC - alpha*log(k)  by OLS.

    Returns dict(alpha, logC, r2). alpha>0 measures tail steepness.
    """
    y = np.sort(np.asarray(x, float))[::-1]          # descending
    k = np.arange(1, len(y) + 1)
    b, a, r2 = ols(np.log(k), np.log(y))
    return {"alpha": -b, "logC": a, "r2": r2}


def gini(x):
    """Gini coefficient of a non-negative vector."""
    x = np.sort(np.asarray(x, float))
    n = len(x)
    cum = np.cumsum(x)
    return float((2.0 * np.sum((np.arange(1, n + 1)) * x) - (n + 1) * cum[-1])
                 / (n * cum[-1]))


def top_share(x, k):
    """Share of total held by the top-k entries."""
    xs = np.sort(np.asarray(x, float))[::-1]
    return float(xs[:k].sum() / xs.sum())


# ===========================================================================
# S2 -- distribution shape
# ===========================================================================
def fit_shape(known_lbs):
    x = np.asarray(known_lbs, float)
    ln = lognormal_mle(x)
    pl = powerlaw_ranksize(x)
    return {
        "n": int(len(x)),
        "total_lbs": float(x.sum()),
        "lognormal": ln,
        "powerlaw": pl,
        "gini": gini(x),
        "top1_share": top_share(x, 1),
        "top3_share": top_share(x, 3),
        "cv": float(x.std(ddof=1) / x.mean()),
    }


def bootstrap_shape(known_lbs, B=2000, seed=7):
    """Bootstrap CIs for alpha, gini, top1_share, lognormal sigma."""
    rng = np.random.default_rng(seed)
    x = np.asarray(known_lbs, float)
    out = {"alpha": [], "gini": [], "top1_share": [], "sigma": []}
    for _ in range(B):
        xs = rng.choice(x, size=len(x), replace=True)
        out["alpha"].append(powerlaw_ranksize(xs)["alpha"])
        out["gini"].append(gini(xs))
        out["top1_share"].append(top_share(xs, 1))
        out["sigma"].append(lognormal_mle(xs)["sigma"])
    ci = {}
    for k, v in out.items():
        v = np.asarray(v)
        ci[k] = (float(np.percentile(v, 2.5)), float(np.percentile(v, 97.5)))
    return ci


# ===========================================================================
# S3 -- category recovery-rate table (the portable artifact)
# ===========================================================================
def category_recovery_table(known_donors, tier_b, priors=PRIOR_LBS_PER_DONOR):
    """Build a per-category table with:
        n_known, anchored_mean_lbs   (empirical, from Tier-A members; descriptive)
        n_tier_b                      (count of latent donors)
        rate_lbs_per_donor           (allocation weight used for Tier B = prior)
        rate_source                  ('prior'; anchors shown separately)
    Anchored means are reported for transparency/validation but NOT used as the
    Tier-B rate when the only anchor is a mega-outlier (see S3).
    """
    from collections import defaultdict
    known_by_cat = defaultdict(list)
    for name, lbs, cat, _types in known_donors:
        known_by_cat[cat].append(lbs)
    tb_by_cat = defaultdict(int)
    for d in tier_b:
        tb_by_cat[d["category"]] += 1

    cats = sorted(set(list(known_by_cat) + list(tb_by_cat) + list(priors)))
    table = {}
    for c in cats:
        anchors = known_by_cat.get(c, [])
        table[c] = {
            "n_known": len(anchors),
            "anchored_mean_lbs": float(np.mean(anchors)) if anchors else None,
            "n_tier_b": tb_by_cat.get(c, 0),
            "rate_lbs_per_donor": float(priors.get(c, 0.0)),
            "rate_source": "prior" if c in priors else "n/a",
        }
    return table


# ===========================================================================
# S4 -- reconciliation / raking
# ===========================================================================
def reconcile(known_donors, tier_b, control_total, shape,
              priors=PRIOR_LBS_PER_DONOR, tail_lbs=DEFAULT_TAIL_LBS,
              prior_scale=1.0):
    """Close the budget  A (published) + B (named latent) + C (unlisted tail)
    == control_total, with A fixed.

    Returns a dict with the channel decomposition, per-donor Tier-B estimates,
    and two independent estimates of the unlisted-donor count.
    """
    A = float(sum(d[1] for d in known_donors))
    G = control_total - A                       # everything below the top-12

    # Tier-B mass at (scaled) priors
    per_b = []
    for d in tier_b:
        rate = priors.get(d["category"], 0.0) * prior_scale
        per_b.append({"name": d["name"], "category": d["category"],
                      "est_lbs": rate,
                      "lo_lbs": rate * 0.5, "hi_lbs": rate * 1.5})
    B_raw = float(sum(p["est_lbs"] for p in per_b))

    # Rake: if priors overshoot the gap, scale B down; else tail C absorbs slack.
    if B_raw > G:
        b_scale = G / B_raw
        for p in per_b:
            p["est_lbs"] *= b_scale; p["lo_lbs"] *= b_scale; p["hi_lbs"] *= b_scale
        B = G; C = 0.0; b_scale_applied = b_scale
    else:
        B = B_raw; C = G - B_raw; b_scale_applied = 1.0

    # Tier-C unlisted-donor count -- two independent estimates:
    # (a) flat average tail donor
    n_tail_flat = C / tail_lbs if tail_lbs > 0 else float("nan")
    # (b) power-law extrapolation: count ranks needed beyond the named set so
    #     that sum_{r=r0}^{r0+n} C0 r^-alpha == C.  NOTE: for alpha near 1 the
    #     tail mass converges very slowly, so this estimator is hyper-sensitive
    #     and mainly a DIAGNOSTIC -- we rely on the flat-rate count operationally.
    alpha = shape["powerlaw"]["alpha"]; logC = shape["powerlaw"]["logC"]
    r0 = len(known_donors) + len(tier_b) + 1
    cap = 500_000
    cum, n_tail_pl, r = 0.0, 0, r0
    C0 = np.exp(logC)
    while cum < C and n_tail_pl < cap:
        cum += C0 * r ** (-alpha)
        n_tail_pl += 1; r += 1
    pl_diverged = n_tail_pl >= cap

    return {
        "control_total": float(control_total),
        "A_published": A, "B_named_latent": float(B), "C_unlisted_tail": float(C),
        "gap_below_top12": float(G),
        "A_share": A / control_total, "B_share": B / control_total,
        "C_share": C / control_total,
        "b_scale_applied": float(b_scale_applied),
        "per_donor_tier_b": per_b,
        "n_tail_flat": float(n_tail_flat),
        "n_tail_powerlaw": int(n_tail_pl),
        "n_tail_powerlaw_diverged": bool(pl_diverged),
        "n_donors_total_flat": int(len(known_donors) + len(tier_b) + round(n_tail_flat)),
    }


# ===========================================================================
# S5 -- generalisation, validation, sensitivity
# ===========================================================================
def transfer_to_new_org(total_lbs, category_counts, priors=PRIOR_LBS_PER_DONOR,
                        tail_lbs=DEFAULT_TAIL_LBS):
    """Apply the portable artifacts to a NEW food bank for which we know only
    (i) its annual throughput and (ii) a business-mix count by category
    (e.g. from Census County Business Patterns).  No donor list required.
    """
    B_raw = sum(priors.get(c, 0.0) * n for c, n in category_counts.items())
    if B_raw > total_lbs:                       # rake down
        s = total_lbs / B_raw
        B = total_lbs; C = 0.0; scale = s
    else:
        B = B_raw; C = total_lbs - B_raw; scale = 1.0
    return {
        "total_lbs": total_lbs,
        "B_named_modelled": B, "C_unlisted_tail": C,
        "B_share": B / total_lbs, "C_share": C / total_lbs,
        "prior_scale_applied": scale,
        "n_tail_flat": C / tail_lbs if tail_lbs > 0 else float("nan"),
    }


def loo_shape_validation(known_lbs):
    """Leave-one-out test of the rank-size shape: refit on n-1, predict the
    held-out donor's amount from its rank.  Reports log-scale error + Spearman.

    Caveat (S5): uses the donor's rank, so it tests shape STABILITY, not blind
    a-priori prediction.  Cross-org reconciliation (S5/V3) is the external test.
    """
    x = np.sort(np.asarray(known_lbs, float))[::-1]
    n = len(x)
    preds, actuals = [], []
    for i in range(n):
        mask = np.ones(n, bool); mask[i] = False
        xtr = x[mask]
        ktr = np.arange(1, n + 1)[mask]
        b, a, _ = ols(np.log(ktr), np.log(xtr))
        yhat = np.exp(a + b * np.log(i + 1))
        preds.append(yhat); actuals.append(x[i])
    preds = np.asarray(preds); actuals = np.asarray(actuals)
    log_err = np.log(preds) - np.log(actuals)
    # Spearman = Pearson on ranks
    rp = np.argsort(np.argsort(preds)); ra = np.argsort(np.argsort(actuals))
    spearman = float(np.corrcoef(rp, ra)[0, 1])
    return {
        "median_abs_log_err": float(np.median(np.abs(log_err))),
        "rmse_log": float(np.sqrt(np.mean(log_err**2))),
        "mean_ratio": float(np.mean(preds / actuals)),
        "spearman_rank_corr": spearman,
    }


def cross_org_reconciliation(shape, fbnyc, usd_per_lb):
    """V3: independent check -- convert City Harvest donated-food shape to a
    $/lb-implied value and compare against Food Bank NYC's audited donated
    channel (a *different* organisation).  Agreement validates the unit bridge.
    """
    ch_top12_value = shape["total_lbs"] * usd_per_lb
    fb_donated_value = fbnyc["donated_lbs"] * usd_per_lb
    return {
        "ch_top12_lbs": shape["total_lbs"],
        "ch_top12_value_usd": ch_top12_value,
        "fbnyc_donated_lbs": fbnyc["donated_lbs"],
        "fbnyc_donated_value_usd": fb_donated_value,
        "ch_as_pct_of_fbnyc_donated": shape["total_lbs"] / fbnyc["donated_lbs"],
        "usd_per_lb": usd_per_lb,
    }


def sensitivity(known_donors, tier_b, shape, totals, prior_scales, tail_sizes):
    """Sweep control total x prior scale x tail size; report C and tail count."""
    rows = []
    for T in totals:
        for ps in prior_scales:
            for tl in tail_sizes:
                r = reconcile(known_donors, tier_b, T, shape,
                              tail_lbs=tl, prior_scale=ps)
                rows.append({
                    "control_total": T, "prior_scale": ps, "tail_lbs": tl,
                    "B": r["B_named_latent"], "C": r["C_unlisted_tail"],
                    "C_share": r["C_share"],
                    "n_tail_flat": r["n_tail_flat"],
                    "n_total_flat": r["n_donors_total_flat"],
                })
    return rows
