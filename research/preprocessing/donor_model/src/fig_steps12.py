"""
fig_steps12.py -- Steps 1 & 2 in one file (panels A and B).

    (A) rank-size      : measure the donor-size distribution      (S2)
    (B) decomposition  : split the yearly total into A / B / C    (S4)

Colours follow src/palette.py (teal / magenta / navy / grey).
-> figures/steps_1_2.png
"""
from __future__ import annotations
import os
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Patch

import data as D
import model as M
from palette import NAVY, MAGENTA, TEAL, GREY, INK

FIG = os.path.join(os.path.dirname(__file__), "..", "figures")


def main():
    known = D.KNOWN_DONORS
    tier_b = D.build_tier_b()
    known_lbs = [d[1] for d in known]
    shape = M.fit_shape(known_lbs)

    fig, (axA, axB) = plt.subplots(1, 2, figsize=(12.6, 5.2),
                                   gridspec_kw=dict(width_ratios=[1.15, 0.85],
                                                    wspace=0.28))
    fig.subplots_adjust(left=0.07, right=0.97, top=0.82, bottom=0.16)

    # ---- (A) rank-size --------------------------------------------------
    y = np.sort(np.asarray(known_lbs, float))[::-1]
    k = np.arange(1, len(y) + 1)
    alpha, logC = shape["powerlaw"]["alpha"], shape["powerlaw"]["logC"]
    axA.scatter(k, y, color=NAVY, zorder=3, s=46, label="12 published donors")
    kk = np.linspace(1, len(y), 100)
    axA.plot(kk, np.exp(logC) * kk ** (-alpha), color=MAGENTA, lw=2.2,
             label=f"power-law fit  α={alpha:.2f} (R²={shape['powerlaw']['r2']:.2f})")
    axA.set_xscale("log"); axA.set_yscale("log")
    axA.set_xlabel("donor rank (1 = largest)"); axA.set_ylabel("annual lbs")
    axA.set_title("(A)  Step 1 · measure the donor-size distribution",
                  fontweight="bold", loc="left", color=INK)
    axA.legend(fontsize=8.5); axA.grid(True, which="both", color=GREY, alpha=.5)

    # ---- (B) decomposition ---------------------------------------------
    for i, T in enumerate([75_000_000, 90_000_000]):
        r = M.reconcile(known, tier_b, T, shape)
        A, B, C = r["A_published"], r["B_named_latent"], r["C_unlisted_tail"]
        axB.bar(i, A/1e6, color=NAVY)
        axB.bar(i, B/1e6, bottom=A/1e6, color=MAGENTA)
        axB.bar(i, C/1e6, bottom=(A+B)/1e6, color=TEAL)
        axB.text(i, (A/2)/1e6, f"A {A/1e6:.0f}M", ha="center", va="center",
                 color="white", fontsize=8.5, fontweight="bold")
        axB.text(i, (A+B+C/2)/1e6, f"C {C/1e6:.0f}M", ha="center", va="center",
                 color=INK, fontsize=8.5, fontweight="bold")
    axB.set_xticks([0, 1]); axB.set_xticklabels(["total = 75M", "total = 90M"])
    axB.set_ylabel("million lbs / yr")
    axB.set_title("(B)  Step 2 · split the yearly total",
                  fontweight="bold", loc="left", color=INK)
    axB.legend(handles=[Patch(color=NAVY, label="A published (12)"),
                        Patch(color=MAGENTA, label="B named, estimated (55)"),
                        Patch(color=TEAL, label="C unlisted tail (~3,000)")],
               fontsize=8.5, loc="upper left")
    axB.grid(True, axis="y", color=GREY, alpha=.5)

    fig.suptitle("Steps 1–2 · Measure the donor distribution, then split the yearly total",
                 fontsize=13.5, fontweight="bold", color=INK)
    out = os.path.join(FIG, "steps_1_2.png")
    fig.savefig(out, dpi=150); plt.close(fig)
    print("wrote", os.path.abspath(out))


if __name__ == "__main__":
    main()
