"""
figutil.py -- small shared helpers for the figure scripts.
"""
from collections import defaultdict
import model as M


def per_category_named(known, tier_b):
    """Per-category named volume: (categories, published_lbs, estimated_lbs),
    sorted ascending by total so matplotlib barh shows largest at the top."""
    a = defaultdict(float); b = defaultdict(float)
    for _n, lbs, cat, _t in known:
        a[cat] += lbs
    for d in tier_b:
        b[d["category"]] += M.PRIOR_LBS_PER_DONOR.get(d["category"], 0.0)
    cats = sorted(set(a) | set(b), key=lambda c: a[c] + b[c])
    return cats, [a[c] for c in cats], [b[c] for c in cats]


def n_donors_per_cat(known, tier_b):
    n = defaultdict(int)
    for _n, _l, cat, _t in known:
        n[cat] += 1
    for d in tier_b:
        n[d["category"]] += 1
    return n
