"""
donor_geo.py -- Transparent, EDITABLE allocation of donor pounds to NYC boroughs.

IMPORTANT (read before trusting the map): the City Harvest page publishes no
donor addresses.  This module assigns pounds to boroughs with a documented rule
set, not measured geography.  Two kinds of rule:

  * a CONFIDENT facility assignment  (e.g. the Hunts Point produce complex -> Bronx)
  * a SPLIT across boroughs by a documented weight key, for multi-site chains and
    for volume that cannot be pinned to one place.

Everything here is meant to be overridden once real pickup-location data exist.
The map therefore shows "where, under these rules, sourced pounds concentrate",
and is explicitly ILLUSTRATIVE.
"""
from __future__ import annotations
from collections import defaultdict
import data as D
import model as M

BOROUGHS = ["Bronx", "Brooklyn", "Manhattan", "Queens", "Staten Island"]

# --- weight key for SPLIT volume -------------------------------------------
# NYC borough resident-population share (2020 Census) -- a first-order proxy for
# how many retail/QSR/institutional pickup points sit in each borough.  Swap for
# food-retail establishment counts (Census CBP, NAICS 445) when available.
POP_WEIGHTS = {
    "Brooklyn": 0.311, "Queens": 0.273, "Manhattan": 0.192,
    "Bronx": 0.167, "Staten Island": 0.057,
}

# --- custom splits ----------------------------------------------------------
# GrowNYC aggregate -> by the five named markets (3 Manhattan, 2 Brooklyn).
GROWNYC_SPLIT = {"Manhattan": 0.6, "Brooklyn": 0.4}

# --- confident TIER-A facility assignments ---------------------------------
# "SPLIT" = multi-site chain, allocate by POP_WEIGHTS.  "GROWNYC" = custom split.
TIER_A_BOROUGH = {
    "Amazon": "SPLIT",                       # many fulfilment sites citywide
    "Hunts Point Produce Market": "Bronx",   # the market itself
    "Baldor Specialty Foods": "Bronx",       # Hunts Point
    "Trader Joe's": "SPLIT",
    "FreshDirect": "Bronx",                  # Bronx (Port Morris/Hunts Point)
    "Whole Foods Market": "SPLIT",
    "Jacob's Village Farm": "Bronx",         # Hunts Point produce vendor
    "Costco": "SPLIT",
    "BJ's Wholesale Club": "SPLIT",
    "GrowNYC Greenmarket": "GROWNYC",
    "4C Foods": "Brooklyn",                   # 4C Foods HQ, Brooklyn
    "Pret A Manger": "SPLIT",                 # Manhattan-heavy chain (kept SPLIT)
}

# --- TIER-B category rules --------------------------------------------------
# Produce wholesale and out-of-region farms enter NYC mainly through the Hunts
# Point complex -> Bronx.  Genuinely multi-site categories -> SPLIT.
CATEGORY_BOROUGH = {
    "Wholesale": "Bronx",          # Hunts Point produce wholesale
    "Farms": "Bronx",              # out-of-region produce enters via Hunts Point
    "Manufacturers": "SPLIT",
    "Corporate": "SPLIT",
    "Quickservice": "SPLIT",
    "Bakery": "SPLIT",
    "Caterer": "SPLIT",
    "Restaurants": "SPLIT",
    "Hotels": "SPLIT",
    "Nonprofit & Gov": "SPLIT",
    "Religious": "SPLIT",
    "Special Events": "SPLIT",
}


def _resolve(rule, lbs):
    """Turn a rule + pounds into a {borough: lbs} contribution."""
    out = defaultdict(float)
    if rule == "SPLIT":
        for b, w in POP_WEIGHTS.items():
            out[b] += lbs * w
    elif rule == "GROWNYC":
        for b, w in GROWNYC_SPLIT.items():
            out[b] += lbs * w
    else:                                   # a named borough
        out[rule] += lbs
    return out


def pounds_by_borough(include_tail=False, control_total=90_000_000):
    """Return {borough: lbs} for NAMED donors (Tier A + Tier B).

    If include_tail, the unlisted tail is added by POP_WEIGHTS (very illustrative).
    Also returns a breakdown dict for transparency.
    """
    known = D.KNOWN_DONORS
    tier_b = D.build_tier_b()
    out = defaultdict(float)
    breakdown = {"confident": defaultdict(float), "split": defaultdict(float),
                 "tail": defaultdict(float)}

    # Tier A: per donor
    for name, lbs, _cat, _t in known:
        rule = TIER_A_BOROUGH.get(name, "SPLIT")
        contrib = _resolve(rule, lbs)
        bucket = "split" if rule == "SPLIT" else "confident"
        for b, v in contrib.items():
            out[b] += v; breakdown[bucket][b] += v

    # Tier B: per category (count x prior)
    tb_lbs = defaultdict(float)
    for d in tier_b:
        tb_lbs[d["category"]] += M.PRIOR_LBS_PER_DONOR.get(d["category"], 0.0)
    for cat, lbs in tb_lbs.items():
        rule = CATEGORY_BOROUGH.get(cat, "SPLIT")
        contrib = _resolve(rule, lbs)
        bucket = "split" if rule == "SPLIT" else "confident"
        for b, v in contrib.items():
            out[b] += v; breakdown[bucket][b] += v

    named_total = sum(out.values())

    if include_tail:
        rec = M.reconcile(known, tier_b, control_total,
                          M.fit_shape([d[1] for d in known]))
        tail = rec["C_unlisted_tail"]
        for b, w in POP_WEIGHTS.items():
            out[b] += tail * w; breakdown["tail"][b] += tail * w

    return dict(out), {k: dict(v) for k, v in breakdown.items()}, named_total


if __name__ == "__main__":
    vals, bd, tot = pounds_by_borough(include_tail=False)
    print("Named pounds by borough (Tier A + B):")
    for b in sorted(vals, key=lambda k: -vals[k]):
        print(f"  {b:<15} {vals[b]:>12,.0f}  ({vals[b]/tot:5.1%})")
    print(f"  {'TOTAL':<15} {tot:>12,.0f}")
    print("\nConfident vs split (named):")
    for b in BOROUGHS:
        print(f"  {b:<15} confident {bd['confident'].get(b,0):>11,.0f}   "
              f"split {bd['split'].get(b,0):>11,.0f}")
