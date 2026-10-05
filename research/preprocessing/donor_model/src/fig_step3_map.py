"""
fig_step3_map.py -- Step 3, geographic version: a NYC borough choropleth of
estimated pounds SOURCED per borough (named donors only).

ILLUSTRATIVE: pounds are placed by the documented rules in donor_geo.py, not by
measured donor addresses.  Same universe as the step-3 bars (named sources); the
~61M-lb unlisted tail is undisclosed and excluded from the map.

-> figures/step_3_map.png
"""
from __future__ import annotations
import os
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import FuncFormatter

import geo
import donor_geo as DG
from palette import NAVY, TEAL_DK, INK

HERE = os.path.dirname(__file__)
FIG = os.path.join(HERE, "..", "figures")
GEOJSON = os.path.join(HERE, "..", "data", "nyc_boroughs.geojson")


def main():
    boroughs = geo.load_boroughs(GEOJSON)
    vals, bd, named_total = DG.pounds_by_borough(include_tail=False)

    fig, ax = plt.subplots(figsize=(9.2, 8.4))
    fig.subplots_adjust(left=0.02, right=0.90, top=0.88, bottom=0.13)

    cmap = geo.sequential_cmap(NAVY, "whites_navy")
    sm = geo.choropleth(
        ax, boroughs, vals, cmap, vmin=0,
        label_fmt=lambda n, v: f"{n}\n{v/1e6:.1f}M",
    )
    cbar = fig.colorbar(sm, ax=ax, fraction=0.038, pad=0.02)
    cbar.set_label("estimated pounds sourced per yr (million lbs)")
    cbar.ax.yaxis.set_major_formatter(FuncFormatter(lambda t, _: f"{t/1e6:.0f}M"))

    ax.set_title("Step 3 (geographic) · estimated pounds sourced per borough\n"
                 "City Harvest named donors — ILLUSTRATIVE allocation",
                 fontsize=13, fontweight="bold", color=INK, loc="left")

    # ranked share list in the empty top-left (Hudson/NJ) corner
    order = sorted(vals, key=lambda k: -vals[k])
    lines = ["Sourced pounds (named donors):"]
    lines += [f"  {b}:  {vals[b]/1e6:.1f}M  ({vals[b]/named_total:.0%})" for b in order]
    ax.text(0.005, 0.985, "\n".join(lines), transform=ax.transAxes, ha="left",
            va="top", fontsize=8.5, color=INK,
            bbox=dict(boxstyle="round", fc="#f6f8fa", ec="#ccd3da", alpha=.95))

    fig.text(0.02, 0.025,
             "Pounds placed by transparent rules (donor_geo.py), NOT measured addresses: the Hunts Point "
             "produce complex → Bronx\n(Hunts Point Mkt, Baldor, Jacob's Village Farm, FreshDirect, produce "
             "wholesale, out-of-region farms); GrowNYC → Manhattan/Brooklyn;\n4C Foods → Brooklyn; multi-site "
             "chains & institutions split by borough population.  Excludes the ~61M-lb unlisted tail "
             "(source undisclosed).",
             fontsize=7.8, color=TEAL_DK)

    out = os.path.join(FIG, "step_3_map.png")
    fig.savefig(out, dpi=150); plt.close(fig)
    print("wrote", os.path.abspath(out))
    print(f"named total mapped: {named_total:,.0f} lbs")


if __name__ == "__main__":
    main()
