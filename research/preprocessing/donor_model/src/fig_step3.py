"""
fig_step3.py -- Step 3 in its own file (panel C).

    (C) per-source bars : attribute the NAMED volume to each source category.
        published (navy) + estimated (magenta), stacked, sorted, labelled.

Colours follow src/palette.py (teal / magenta / navy / grey).
-> figures/step_3_per_source.png
"""
from __future__ import annotations
import os
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

import data as D
import model as M
import figutil as U
from palette import NAVY, MAGENTA, TEAL_DK, GREY, INK

FIG = os.path.join(os.path.dirname(__file__), "..", "figures")


def main():
    known = D.KNOWN_DONORS
    tier_b = D.build_tier_b()
    rec90 = M.reconcile(known, tier_b, 90_000_000, M.fit_shape([d[1] for d in known]))

    cats, aval, bval = U.per_category_named(known, tier_b)
    ncnt = U.n_donors_per_cat(known, tier_b)
    labels = [f"{c}  (n={ncnt[c]})" for c in cats]
    aval = np.array(aval) / 1e6
    bval = np.array(bval) / 1e6

    fig, ax = plt.subplots(figsize=(9.6, 7.0))
    fig.subplots_adjust(left=0.22, right=0.95, top=0.88, bottom=0.10)
    ax.barh(labels, aval, color=NAVY, label="published (Tier A)")
    ax.barh(labels, bval, left=aval, color=MAGENTA, label="estimated (Tier B)")
    for i, (a_, b_) in enumerate(zip(aval, bval)):
        tot = a_ + b_
        if tot > 0.04:
            ax.text(tot + 0.12, i, f"{tot:.1f}M", va="center", fontsize=8, color=INK)
    ax.set_xlabel("annual lbs received from this source (million lbs)")
    ax.set_title("Step 3 · How much food from each source\n"
                 "(the per-source distribution estimate)",
                 fontweight="bold", loc="left", color=INK)
    ax.legend(fontsize=9, loc="center right")
    ax.grid(True, axis="x", color=GREY, alpha=.6)
    ax.margins(x=0.14)
    ax.text(0.99, 0.015,
            f"+ {rec90['C_unlisted_tail']/1e6:.0f}M lbs from the unlisted tail "
            "(source not identified)",
            transform=ax.transAxes, ha="right", va="bottom", fontsize=8.5,
            style="italic", color=TEAL_DK)

    out = os.path.join(FIG, "step_3_per_source.png")
    fig.savefig(out, dpi=150); plt.close(fig)
    print("wrote", os.path.abspath(out))


if __name__ == "__main__":
    main()
