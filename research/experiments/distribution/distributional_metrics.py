"""
distributional_metrics.py -- neutral distributional metrics from ch_solution.json.

The headline metric in ch_experiment.py, need-weighted coverage, is defined through the
same weight w = (need/access)^gamma that the 'equity' strategy maximizes, so that strategy
leads it partly by construction. The metrics here are deliberately independent of w and of
the access term: they are computed from need percentiles and delivered demand only, so no
strategy optimizes them directly.

Reads  : ch_solution.json (per-recipient allocation)
Writes : distributional_metrics.{md,json}
Deps   : numpy only.
"""
from __future__ import annotations
import json
from pathlib import Path
import numpy as np

HERE = Path(__file__).resolve().parent
PRETTY = {"unweighted": "Unweighted", "random_preference": "Random-preference",
          "need_only": "Need-only", "access_only": "Access-only", "equity": "Equity"}
ORDER = ["unweighted", "random_preference", "need_only", "access_only", "equity"]
NDEC = 10


def gini(x, weights=None):
    """Gini coefficient of a non-negative array (0 = uniform, 1 = maximally concentrated)."""
    x = np.asarray(x, dtype=float)
    w = np.ones_like(x) if weights is None else np.asarray(weights, dtype=float)
    keep = w > 0
    x, w = x[keep], w[keep]
    if x.size == 0 or x.sum() <= 0:
        return float("nan")
    o = np.argsort(x)
    x, w = x[o], w[o]
    cw = np.cumsum(w)
    cxw = np.cumsum(x * w)
    # weighted Gini via the Lorenz trapezoid
    num = np.sum(w * (cxw - 0.5 * x * w))
    return float(1.0 - 2.0 * num / (cw[-1] * cxw[-1]))


def spearman(a, b):
    """Rank correlation, average ranks for ties. Avoids a scipy dependency."""
    a, b = np.asarray(a, dtype=float), np.asarray(b, dtype=float)
    if a.size < 3:
        return float("nan")
    ra, rb = _rank(a), _rank(b)
    ra, rb = ra - ra.mean(), rb - rb.mean()
    den = np.sqrt((ra**2).sum() * (rb**2).sum())
    return float((ra * rb).sum() / den) if den > 0 else float("nan")


def _rank(x):
    o = np.argsort(x, kind="mergesort")
    r = np.empty(len(x), dtype=float)
    r[o] = np.arange(1, len(x) + 1, dtype=float)
    # average ranks within tie groups
    for v in np.unique(x):
        m = x == v
        if m.sum() > 1:
            r[m] = r[m].mean()
    return r


def metrics_for(served_idx, need, demand, nta):
    """All distributional metrics for one policy's served set."""
    served = np.zeros(len(need), dtype=bool)
    served[np.asarray(served_idx, dtype=int)] = True
    got = demand * served

    # --- coverage by need decile (equal-count bins over the need percentile) ---
    order = np.argsort(need, kind="mergesort")
    bins = np.array_split(order, NDEC)
    dec_cov, dec_need = [], []
    for b in bins:
        tot = demand[b].sum()
        dec_cov.append(100.0 * got[b].sum() / tot if tot > 0 else 0.0)
        dec_need.append(float(need[b].mean()))

    # --- per-NTA coverage rate, for dispersion and need-alignment ---
    ntas = sorted(set(nta))
    cov_n, need_n, dem_n = [], [], []
    for n in ntas:
        m = np.array([v == n for v in nta])
        tot = demand[m].sum()
        if tot <= 0:
            continue
        cov_n.append(got[m].sum() / tot)
        need_n.append(need[m].mean())
        dem_n.append(tot)
    cov_n, need_n, dem_n = map(np.asarray, (cov_n, need_n, dem_n))

    return {
        "coverage_by_need_decile_pct": [round(v, 1) for v in dec_cov],
        "decile_mean_need_pct": [round(v, 3) for v in dec_need],
        "top_decile_coverage_pct": round(dec_cov[-1], 1),
        "bottom_decile_coverage_pct": round(dec_cov[0], 1),
        "min_decile_coverage_pct": round(min(dec_cov), 1),
        "need_alignment_spearman": round(spearman(cov_n, need_n), 3),
        "nta_coverage_gini": round(gini(cov_n, weights=dem_n), 3),
        "n_ntas_zero_coverage": int((cov_n <= 0).sum()),
        "n_ntas": int(len(cov_n)),
        "flat_coverage_pct": round(100.0 * got.sum() / demand.sum(), 1),
        "served": int(served.sum()),
    }


def main():
    sol = json.loads((HERE / "ch_solution.json").read_text())
    recs = sol["recipients"]
    need = np.array([r["need_pct"] for r in recs], dtype=float)
    demand = np.array([r["demand_lbs"] for r in recs], dtype=float)
    nta = [r["nta"] for r in recs]
    w = np.array([r["w"] for r in recs], dtype=float)

    out = {"n_recipients": len(recs), "source": "ch_solution.json", "modes": {}}
    for mode in ("mode_A", "mode_B_equal_throughput"):
        block = sol.get(mode) or {}
        out["modes"][mode] = {}
        for pol in ORDER:
            rec = block.get(pol)
            if not rec:
                continue
            m = metrics_for(rec["served_idx"], need, demand, nta)
            # cross-check: reproduce the summary's need-weighted coverage from the dump
            s = np.zeros(len(need), dtype=bool); s[rec["served_idx"]] = True
            m["need_weighted_coverage_pct"] = round(
                100.0 * (w * demand * s).sum() / (w * demand).sum(), 1)
            out["modes"][mode][pol] = m

    (HERE / "distributional_metrics.json").write_text(json.dumps(out, indent=2))

    # ---------------- markdown ----------------
    L = ["# Distributional metrics (independent of the equity weight w)", "",
         "Computed offline from `ch_solution.json`; no solver run. Need deciles are equal-count",
         "bins over the recipient need percentile. Decile 10 = highest need.", ""]
    for mode, title in (("mode_A", "Mode A: unrestricted common supply"),
                        ("mode_B_equal_throughput", "Mode B: equal delivered volume")):
        block = out["modes"].get(mode) or {}
        if not block:
            continue
        pols = [p for p in ORDER if p in block]
        L += [f"## {title}", "",
              "| metric | " + " | ".join(PRETTY[p] for p in pols) + " |",
              "|---|" + "---:|" * len(pols)]
        rows = [
            ("recipients served", "served", 0),
            ("flat coverage %", "flat_coverage_pct", 1),
            ("need-weighted coverage % (w-dependent, cross-check)", "need_weighted_coverage_pct", 1),
            ("**top need-decile coverage %**", "top_decile_coverage_pct", 1),
            ("bottom need-decile coverage %", "bottom_decile_coverage_pct", 1),
            ("worst need-decile coverage % (service floor)", "min_decile_coverage_pct", 1),
            ("**need alignment (Spearman, NTA)**", "need_alignment_spearman", 3),
            ("NTA coverage Gini (dispersion)", "nta_coverage_gini", 3),
            ("NTAs with zero coverage", "n_ntas_zero_coverage", 0),
        ]
        for label, key, nd in rows:
            vals = [block[p][key] for p in pols]
            fmt = [f"{v:.{nd}f}" if isinstance(v, float) else str(v) for v in vals]
            L.append(f"| {label} | " + " | ".join(fmt) + " |")
        L += ["", "### Coverage by need decile (% of demand served)", "",
              "| decile | mean need pct | " + " | ".join(PRETTY[p] for p in pols) + " |",
              "|---:|---:|" + "---:|" * len(pols)]
        for i in range(NDEC):
            mn = block[pols[0]]["decile_mean_need_pct"][i]
            vals = " | ".join(f"{block[p]['coverage_by_need_decile_pct'][i]:.1f}" for p in pols)
            L.append(f"| {i+1} | {mn:.2f} | {vals} |")
        L.append("")
    (HERE / "distributional_metrics.md").write_text("\n".join(L))
    print("[ok] wrote distributional_metrics.{md,json}")
    print("\n".join(L[:40]))


if __name__ == "__main__":
    main()
