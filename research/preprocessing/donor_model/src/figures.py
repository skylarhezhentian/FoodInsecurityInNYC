"""
figures.py -- Generate the six diagnostic figures for the writeup.

    fig1_ranksize.png        rank-size power-law fit (S2)
    fig2_lognormal_qq.png    log-normal Q-Q of the 12 anchors (S2)
    fig3_decomposition.png   A/B/C channel decomposition at T=75M & 90M (S4)
    fig4_category.png        Tier-B allocated mass by category (S3/S4)
    fig5_sensitivity.png     unlisted-donor count vs assumptions (S5)
    fig6_distance_decay.png  illustrative distance-decay kernel (structural)

Pure numpy + matplotlib (Agg).  No scipy: the normal quantile for the Q-Q plot
uses Acklam's inverse-CDF approximation, implemented inline.
"""
from __future__ import annotations
import os
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

import data as D
import model as M

FIG = os.path.join(os.path.dirname(__file__), "..", "figures")
os.makedirs(FIG, exist_ok=True)
# palette echoing the NYC bivariate need×access map (navy/magenta/teal/grey)
from palette import NAVY as BLUE, MAGENTA as ORANGE, TEAL as GREEN, GREY  # noqa: E402


def norm_ppf(p):
    """Acklam inverse standard-normal CDF (no scipy)."""
    a = [-3.969683028665376e1, 2.209460984245205e2, -2.759285104469687e2,
         1.383577518672690e2, -3.066479806614716e1, 2.506628277459239e0]
    b = [-5.447609879822406e1, 1.615858368580409e2, -1.556989798598866e2,
         6.680131188771972e1, -1.328068155288572e1]
    c = [-7.784894002430293e-3, -3.223964580411365e-1, -2.400758277161838e0,
         -2.549732539343734e0, 4.374664141464968e0, 2.938163982698783e0]
    d = [7.784695709041462e-3, 3.224671290700398e-1, 2.445134137142996e0,
         3.754408661907416e0]
    p = np.asarray(p, float); out = np.empty_like(p)
    plow, phigh = 0.02425, 1 - 0.02425
    lo, hi = p < plow, p > phigh; mid = ~(lo | hi)
    q = np.sqrt(-2 * np.log(p[lo])) if lo.any() else np.array([])
    if lo.any():
        out[lo] = (((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) / \
                  ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1)
    if hi.any():
        q = np.sqrt(-2 * np.log(1 - p[hi]))
        out[hi] = -(((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) / \
                   ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1)
    if mid.any():
        q = p[mid] - 0.5; r = q*q
        out[mid] = (((((a[0]*r+a[1])*r+a[2])*r+a[3])*r+a[4])*r+a[5])*q / \
                   (((((b[0]*r+b[1])*r+b[2])*r+b[3])*r+b[4])*r+1)
    return out


def fig1_ranksize(known_lbs, shape):
    y = np.sort(np.asarray(known_lbs, float))[::-1]
    k = np.arange(1, len(y) + 1)
    alpha, logC = shape["powerlaw"]["alpha"], shape["powerlaw"]["logC"]
    fig, ax = plt.subplots(figsize=(6.4, 4.6))
    ax.scatter(k, y, color=BLUE, zorder=3, label="published top-12")
    kk = np.linspace(1, len(y), 100)
    ax.plot(kk, np.exp(logC) * kk ** (-alpha), color=ORANGE,
            label=f"power law  α={alpha:.2f}  (R²={shape['powerlaw']['r2']:.2f})")
    ax.set_xscale("log"); ax.set_yscale("log")
    ax.set_xlabel("rank (log)"); ax.set_ylabel("annual lbs (log)")
    ax.set_title("S2 · Rank–size law of City Harvest donor volumes")
    ax.legend(); ax.grid(True, which="both", alpha=.25)
    fig.tight_layout(); fig.savefig(f"{FIG}/fig1_ranksize.png", dpi=140); plt.close(fig)


def fig2_qq(known_lbs, shape):
    lx = np.sort(np.log(np.asarray(known_lbs, float)))
    n = len(lx)
    pp = (np.arange(1, n + 1) - 0.5) / n
    theo = norm_ppf(pp)
    mu, sigma = shape["lognormal"]["mu"], shape["lognormal"]["sigma"]
    fig, ax = plt.subplots(figsize=(6.4, 4.6))
    ax.scatter(theo, lx, color=BLUE, zorder=3)
    xs = np.linspace(theo.min(), theo.max(), 50)
    ax.plot(xs, mu + sigma * xs, color=ORANGE,
            label=f"log-normal fit  μ={mu:.2f}, σ={sigma:.2f}")
    ax.set_xlabel("theoretical normal quantile")
    ax.set_ylabel("observed log(lbs)")
    ax.set_title("S2 · Log-normal Q–Q plot (12 anchors)")
    ax.legend(); ax.grid(True, alpha=.25)
    fig.tight_layout(); fig.savefig(f"{FIG}/fig2_lognormal_qq.png", dpi=140); plt.close(fig)


def fig3_decomposition(known, tier_b, shape):
    fig, ax = plt.subplots(figsize=(6.4, 4.6))
    totals = [75_000_000, 90_000_000]
    labels = ["T = 75M lbs", "T = 90M lbs"]
    A = B = None
    for i, T in enumerate(totals):
        r = M.reconcile(known, tier_b, T, shape)
        A, B, C = r["A_published"], r["B_named_latent"], r["C_unlisted_tail"]
        ax.bar(i, A/1e6, color=BLUE)
        ax.bar(i, B/1e6, bottom=A/1e6, color=ORANGE)
        ax.bar(i, C/1e6, bottom=(A+B)/1e6, color=GREEN)
        ax.text(i, (A/2)/1e6, f"A\n{A/1e6:.0f}M", ha="center", va="center", color="w", fontsize=9)
        ax.text(i, (A+B/2)/1e6, f"B {B/1e6:.0f}M", ha="center", va="center", fontsize=8)
        ax.text(i, (A+B+C/2)/1e6, f"C (unlisted tail)\n{C/1e6:.0f}M", ha="center", va="center", color="w", fontsize=9)
    ax.set_xticks(range(len(totals))); ax.set_xticklabels(labels)
    ax.set_ylabel("million lbs / yr")
    ax.set_title("S4 · Volume decomposition: published vs named-latent vs unlisted tail")
    from matplotlib.patches import Patch
    ax.legend(handles=[Patch(color=BLUE, label="A published top-12"),
                       Patch(color=ORANGE, label="B named, no amount (57)"),
                       Patch(color=GREEN, label="C unlisted tail")], loc="upper left")
    fig.tight_layout(); fig.savefig(f"{FIG}/fig3_decomposition.png", dpi=140); plt.close(fig)


def fig4_category(known, tier_b):
    cat = M.category_recovery_table(known, tier_b)
    rows = [(c, r["rate_lbs_per_donor"] * r["n_tier_b"], r["n_tier_b"])
            for c, r in cat.items() if r["n_tier_b"] > 0]
    rows.sort(key=lambda t: t[1])
    names = [f"{c}  (n={n})" for c, _m, n in rows]
    mass = [m/1e6 for _c, m, n in rows]
    fig, ax = plt.subplots(figsize=(6.8, 4.8))
    ax.barh(names, mass, color=ORANGE)
    ax.set_xlabel("allocated Tier-B mass (million lbs/yr)")
    ax.set_title("S3/S4 · Named-latent volume by category (rate × count)")
    ax.grid(True, axis="x", alpha=.25)
    fig.tight_layout(); fig.savefig(f"{FIG}/fig4_category.png", dpi=140); plt.close(fig)


def fig5_sensitivity(known, tier_b, shape):
    tail_sizes = np.array([15_000, 20_000, 25_000, 30_000, 40_000])
    fig, ax = plt.subplots(figsize=(6.4, 4.6))
    for T, col in [(75_000_000, GREY), (90_000_000, BLUE)]:
        counts = [M.reconcile(known, tier_b, T, shape, tail_lbs=ts)["n_tail_flat"]
                  for ts in tail_sizes]
        ax.plot(tail_sizes/1e3, counts, "o-", color=col, label=f"T = {T/1e6:.0f}M lbs")
    ax.set_xlabel("assumed average tail-donor size (thousand lbs/yr)")
    ax.set_ylabel("implied # of unlisted donors")
    ax.set_title("S5 · Sensitivity of unlisted-donor count")
    ax.legend(); ax.grid(True, alpha=.25)
    fig.tight_layout(); fig.savefig(f"{FIG}/fig5_sensitivity.png", dpi=140); plt.close(fig)


def fig6_distance_decay():
    d = np.linspace(0, 80, 200)
    fig, ax = plt.subplots(figsize=(6.4, 4.6))
    for d0, col in [(10, BLUE), (25, ORANGE), (50, GREEN)]:
        ax.plot(d, np.exp(-d/d0), color=col, label=f"d₀ = {d0} km")
    ax.set_xlabel("distance from donor to food-bank DC (km)")
    ax.set_ylabel("relative recovery weight  w(d) = exp(−d/d₀)")
    ax.set_title("Structural term · distance-decay kernel (illustrative)")
    ax.text(0.98, 0.95, "inactive in current fit —\nactivate with geocoded donor addresses",
            transform=ax.transAxes, ha="right", va="top", fontsize=8, color=GREY,
            bbox=dict(boxstyle="round", fc="#f7fafc", ec=GREY))
    ax.legend(); ax.grid(True, alpha=.25)
    fig.tight_layout(); fig.savefig(f"{FIG}/fig6_distance_decay.png", dpi=140); plt.close(fig)


def main():
    known = D.KNOWN_DONORS
    tier_b = D.build_tier_b()
    known_lbs = [d[1] for d in known]
    shape = M.fit_shape(known_lbs)
    fig1_ranksize(known_lbs, shape)
    fig2_qq(known_lbs, shape)
    fig3_decomposition(known, tier_b, shape)
    fig4_category(known, tier_b)
    fig5_sensitivity(known, tier_b, shape)
    fig6_distance_decay()
    print("wrote 6 figures to", os.path.abspath(FIG))


if __name__ == "__main__":
    main()
