# NYC Food Access — Methodology

> **Current method = E2SFCA + equity index** (`build_e2sfca_index.py`, §6). Sections 3–4
> below describe the earlier point-in-polygon access and tercile bivariate, kept for
> provenance. §6 supersedes the access measure (eqs 3–4) and the priority definition.

Pipelines:
- `build_e2sfca_index.py` → `output/{access_e2sfca_nta.png, equity_index_nta.png, bivariate_e2sfca_nta.png, nta_equity_index.csv}` **(current)**
- `build_food_access_map_nta.py` → `output/{need_access_maps_nta.png, bivariate_map_nta.png, nta_summary.csv}` (v1 access)

Unit of analysis: **2020 Neighborhood Tabulation Area (NTA)** — 197 residential neighborhoods.

---

## 1. Data used

| Role | Dataset | Source / ID | What we take |
|---|---|---|---|
| **Need** | Neighborhood Prioritization Map 2025 | NYC Mayor's Office of Food Policy / HRA "Supply Gap" (Tableau) | `Food.Insecure.Percentage` per NTA |
| **Population** | Decennial Census 2010/2020 Change | NYC DCP (`nyc_decennialcensusdata_2010_2020_change.xlsx`, GeoType=`NTA2020`) | `Pop_20` (2020 total pop) per NTA |
| **Supply** | Food Help NYC providers | ArcGIS FeatureService behind finder.nyc.gov/foodhelp | 528 pantries/kitchens: lat/lon + per-day open/close hours |
| **Boundaries** | 2020 NTAs | NYC Open Data `9nt8-h7nd` | polygons; `ntatype==0` keeps residential only |

All four join cleanly on the 2020 NTA code (e.g. `BK0101`); 197/197 matched.

---

## 2. How the food-insecurity rate is measured (the "need" input)

We did **not** compute food insecurity ourselves — it is an external **modeled small-area estimate** supplied by the Mayor's Office of Food Policy / HRA, used as their official neighborhood-prioritization input. The standard methodology behind this class of estimate is **Feeding America's *Map the Meal Gap* (MMG)**.

MMG is **not** a direct survey count. It fits a regression on the USDA Current Population Survey Food Security Supplement at the **state-year** level, then applies the fitted coefficients to **local** demographics to produce sub-county estimates. The state-level model:

```
FI_st = α
        + β_UN · UN_st        (unemployment rate)
        + β_POV · POV_st      (poverty rate)
        + β_MI · MI_st        (median income)
        + β_HISP · HISP_st    (% Hispanic households)
        + β_BLACK · BLACK_st  (% Black households)
        + β_OWN · OWN_st      (% homeowners)
        + β_DSBL · DSBL_st    (% households with a disability)
        + μ_t + υ_s + ε_st    (year FE, state FE, error)
```

Local food-insecurity rate `r_i` for neighborhood `i` ≈ apply `{α, β...}` to neighborhood `i`'s own UN, POV, MI, HISP, BLACK, OWN, DSBL.

**Implications you must keep in mind:**
- It is **modeled, not counted** — driven by poverty/unemployment/income/demographics, so it correlates with those by construction.
- It is **annual**, not monthly.
- It is the reason we switched *away* from SNAP enrollment: SNAP measures program *participation* (undercounts immigrant/ineligible populations, partly circular with access); food-insecurity rate is the direct *outcome* measure of need.

In our pipeline `r_i` is taken as given (a fraction in [0,1]).

---

## 3. Equations computed in this pipeline

Indices: `i` = NTA, `p` = provider. `D = {Mon,…,Sun}`, service types `s ∈ {fp (pantry), sk (kitchen)}`, daily windows `w ∈ {1,2,3}` (handles split shifts).

**(1) Food-insecure population**
```
F_i = r_i · P_i
```
`r_i` = food-insecurity rate, `P_i` = 2020 census population.

**(2) Provider weekly open-hours**
```
H_p = Σ_{s} Σ_{d∈D} Σ_{w} max(0, c_{p,s,d,w} − o_{p,s,d,w})
```
`o, c` = open/close clock times converted to decimal hours; `max(0, ·)` drops blank/invalid windows.

**(3) Supply assigned to a neighborhood (point-in-polygon)**
```
T_i = Σ_{p : x_p ∈ Ω_i} H_p
```
`x_p` = provider location, `Ω_i` = NTA `i` polygon. (Spatial join, CRS EPSG:2263.)

**(4) Access score — supply per unit need**
```
A_i = T_i / (F_i / 10,000) = 10,000 · T_i / F_i
```
= weekly provider-hours available **per 10,000 food-insecure residents** (HRA's own "per-10k-food-insecure" framing). Undefined where `F_i = 0`.

**(5) Tercile classification** (relative, equal-count bins). For variable `v` with empirical 33.3rd/66.7th percentiles `q₁, q₂`:
```
tercile(v) = 0 if v ≤ q₁   (low)
             1 if q₁ < v ≤ q₂ (mid)
             2 if v > q₂     (high)
```
Need class `n_i = tercile(r_i)`; access class `a_i = tercile(A_i)`.

**(6) Bivariate class & priority set**
```
B_i = (n_i, a_i) ∈ {0,1,2}²   → one of 9 colors in a 3×3 matrix
Priority = { i : n_i = 2 ∧ a_i = 0 }   (highest need ∩ lowest access)
```

---

## 4. Why a bivariate map

The operational question is **"where is need *not* being met?"** — a property of the **interaction** of two variables, not of either one alone.

- **Two separate maps** (need; access) force a reader to mentally overlay them NTA-by-NTA to find the high-need-and-low-access neighborhoods. That overlay is exactly the error-prone cognitive step a map should remove.
- **A bivariate map** encodes the joint (need × access) distribution in a single color, so the decision-relevant cell — high need + low access — appears as its own distinct hue (deep purple here) and pops out spatially. It answers the gap question directly.

The cost of a bivariate map is per-variable precision: 9 classes are harder to read for the exact value of *one* variable than a clean sequential ramp. That is **why this analysis ships both**:

- `need_access_maps_nta.png` — the two univariate ramps, for reading each variable's gradient precisely.
- `bivariate_map_nta.png` — the joint view, for spotting the priority gap.

They are complementary, not redundant: univariate for *magnitude*, bivariate for *coincidence*.

---

## 5. Known limitations

1. **Modeled need** — `r_i` is a regression estimate (see §2), not a measured count; annual, demographically driven.
2. **Hard boundaries** — point-in-polygon (eq. 3) ignores providers just over an NTA line and treats a provider across a river as equally reachable; isochrone/network accessibility would fix this.
3. **Equal weighting of hours** — an hour Tue 9–11am counts the same as a Saturday evening hour; no weighting for peak-need times yet.
4. **One provider layer** — uses the 528-record finder layer; the 842-record EFAP layer is not yet merged/deduped.
5. **Relative terciles** — "high need" = top third *of NYC*, not an absolute threshold.

---

## 6. E2SFCA access + equity index (CURRENT method — `build_e2sfca_index.py`)

Two problems with the v1 access (eqs 3–4) drove this rewrite:
1. **Hard boundaries** — point-in-polygon counted a provider only inside its own NTA, so a pantry one block over a line counted zero (Chinatown read "0 providers" spuriously).
2. **Double counting** — the v1 access denominator was food-insecure population `F_i = r_i·P_i`, so the need rate `r_i` sat in *both* the need axis and the access axis. Crossing them partly plotted need against itself.

Fix: a **Gaussian-decay Enhanced Two-Step Floating Catchment Area** model (Luo & Qi 2009; Dai 2010) on **total population** demand (need-independent), at census-tract resolution.

**Entities.** Demand `i` = 2020 census tract centroid, weight `D_i` = 2020 **total** population (2,325 tracts). Supply `j` = provider, capacity `S_j = H_j` (weekly hours, eq. 2; 526 providers with `H_j>0`).

**(6.1) Distance** — pairwise great-circle metres `d_ij` (haversine) between tract centroids and providers.

**(6.2) Gaussian distance decay** (Kwan 1998 form), catchment `d₀ = 1609 m` (1-mi walk), bandwidth `σ = d₀/3`:
```
            exp(−½(d/σ)²) − exp(−½(d₀/σ)²)
  W(d) =  ───────────────────────────────────   for d ≤ d₀,   else 0
                 1 − exp(−½(d₀/σ)²)
```
`W(0)=1`, `W(d₀)=0`, smooth in between.

**(6.3) Step 1 — provider-to-population ratio** (supply spread over the demand it can reach):
```
  R_j = S_j / Σ_i D_i · W(d_ij)
```

**(6.4) Step 2 — tract accessibility** (sum reachable provider ratios):
```
  A_i = Σ_j R_j · W(d_ij)          [hours per person]
```

**(6.5) Aggregate tract → NTA** (population-weighted), scaled to per-10k:
```
  Access_n = 10⁴ · ( Σ_{t∈n} P_t·A_t ) / ( Σ_{t∈n} P_t )
```

**(6.6) Equity index** — percentile ranks (robust to skew), geometric mean:
```
  need_pct  = rank-percentile of r_n   (food-insecurity rate)
  acc_pct   = rank-percentile of Access_n
  E_n = √( need_pct · (1 − acc_pct) )            ∈ [0,1]
```
Priority ranking = `E_n` descending (continuous — no terciles needed).

**Why geometric mean (partially non-compensatory).** With an additive index, abundant access could cancel extreme need. The product form makes `E_n → 0` if *either* need is low *or* access is high, so a neighborhood ranks high **only if** it is both high-need **and** low-access — the correct semantics for an equity/triage index. Percentile inputs keep both factors on a common [0,1] scale and resist the right-skew in both variables.

**Effect of the upgrade.** Spurious zero-access NTAs dropped from many (point-in-polygon) to **7** (genuinely >1 mi from any provider). Chinatown–Two Bridges moved from "0" to a real low-but-nonzero score and remains high-priority on need — now for the right reason.

**Residual limitations.** (a) Distance is haversine, not street/transit network — still crosses rivers/parks as the crow flies; swapping a network matrix into eq. 6.1 is the next step. (b) `d₀ = 1 mi` is a walkability choice; results shift if you model transit/car access. (c) Capacity = open hours, a throughput proxy, not actual food volume.
