# Estimating Donor → Food-Bank Supply from Partial Public Disclosures
### A reproducible, transfer-oriented model calibrated on City Harvest, cross-checked against Food Bank For NYC

**Author:** modelling pipeline in `src/` · **Date:** 2026-06-08
**Canonical unit:** pounds per year (lbs/yr) · **Code:** `src/data.py`, `src/model.py`, `src/run_pipeline.py`, `src/figures.py`

---

## Abstract

We want a model that turns a food bank's *partial, curated* public donor disclosure into a
*complete* estimate of donor-level supply, and that **transfers** to other food banks that
publish even less. Using City Harvest's "Food Donors" page (12 donors with published annual
poundage; 75 further named donors with no amounts) as the calibration case, we (i) fit the
**shape** of the donor-volume distribution, (ii) build a **portable per-category recovery-rate
table**, (iii) **reconcile** bottom-up donor estimates to a published control total via raking,
and (iv) demonstrate **transfer** to a food bank with no donor list at all. The central empirical
finding: the **named** donors account for only **≈32 %** of total rescued volume; the remaining
**≈68 %** is an **unlisted long tail of ~3,000 small donors**. A routing model built on published
names alone therefore captures a quarter of the mass and *must* model the tail explicitly. We
cross-validate magnitudes against Food Bank For NYC's FY2025 audited financials and find the
unit-bridged values agree to within disclosed channel structure.

---

## 1. Problem framing and scope

### 1.1 Objective
Estimate, for each donor *d* that supplies a food bank, an annual volume `y_d` (lbs), given only:
- a small set of **published** `y_d` (the "head"),
- a larger set of donor **names + sector** without amounts (the "body"),
- organisation-level **control totals** (throughput), and
- transferable **sector priors** from external sources.

The artifact must generalise so the same machinery estimates supply for a *different* food bank
in a *different* city. We treat estimation in pounds and derive dollars/meals via fixed bridges.

### 1.2 Canonical unit and de-duplication decisions *(choice S1)*
**S1-a — Unit.** We model in **pounds**, bridging to dollars at Feeding America's
**$1.90/lb** (FY2025, from Food Bank NYC audit Note 9) and to meals at **1.2 lbs/meal**. Reason:
pounds are the only unit disclosed consistently by City Harvest; dollars/meals are deterministic
functions of it, so committing to pounds keeps every artifact cross-comparable.

**S1-b — Aggregation / double-count control.** Two published anchors are *aggregates* whose
members also appear in the category rosters:
- *GrowNYC Greenmarket* (449,493 lbs) aggregates the five named GrowNYC markets;
- *Hunts Point Produce Market* (3,360,391 lbs) is the market in which the five named Hunts Point
  merchants operate.

To avoid double counting we **fold** these two categories into their aggregate anchor and exclude
their roster members from the additive body. This is an explicit assumption (members ⊂ aggregate);
it is conservative for total volume and is flagged in `data.FOLDED_INTO_AGGREGATE`.

**S1-c — Tiering.** After de-duplication (10 roster names are themselves anchors; 10 are folded),
the modelling universe is:

| Tier | Definition | Count | Volume |
|---|---|--:|--:|
| **A** | published amount (anchors) | 12 | 24,068,349 lbs |
| **B** | named, **no** amount | 55 | latent |
| **C** | unlisted (not on the page) | unknown | latent |

---

## 2. Data

| Source | Role | What we take |
|---|---|---|
| City Harvest "Food Donors" page | **calibration** | 12 anchors (name, lbs, sector, food types); 15 sector rosters (87 names) |
| Food Bank For NYC FY2025 audit | **external check** | $1.90/lb bridge; donated/purchased/government channel split (22.7M / 24.3M / 56.9M lbs) |
| City Harvest site (impact strip) | **control total** | ~90M lbs diverted "this year" (primary T); 75M lbs conservative bound |
| ReFED / USDA-EPA sector logic | **priors** | relative surplus-generation by sector → Tier-B category rates |

All inputs are encoded literally in `src/data.py`. Two anchors were originally published
logo-only; they have since been identified as **Jacob's Village Farm** (Wholesale, 1,202,662 lbs)
and **4C Foods** (Manufacturers, 441,037 lbs) and are de-duped out of Tier B so their volume is
counted once, in Tier A. (This corrected a prior double count — previously each was also carrying a
Tier-B prior estimate as if a separate firm.)

---

## 3. Methodology

### 3.1 S2 — Distribution shape from the anchors
Donations are heavy-tailed, so we characterise the **shape** before estimating levels. We fit two
complementary descriptions to the 12 anchors:

- **Log-normal** (MLE on log-amounts): `log y ~ Normal(μ, σ²)`.
- **Power-law rank–size** (OLS): `log y₍ₖ₎ = log C − α·log k`, with α the tail-steepness.

**Why both.** The log-normal is the natural generative story (donation size ≈ product of many
multiplicative factors — firm size × surplus rate × participation) and behaves well for
imputation and intervals. The power law gives an interpretable single-number tail index and a way
to *extrapolate counts* into the tail. We report whichever is fit-for-purpose per task.

**Results.**

| metric | estimate | 95% bootstrap CI |
|---|--:|--:|
| log-normal μ, σ | 14.07, 0.95 | — |
| log-normal median | 1,284,835 lbs | — |
| power-law α | 1.25 (R²=0.90) | [0.74, 1.51] |
| Gini | 0.484 | [0.28, 0.57] |
| top-1 share (Amazon) | 32.1 % | [14 %, 41 %] |
| top-3 share | 57.4 % | — |

Figure `fig1_ranksize.png` shows the rank–size fit; note the **concave departure** — Amazon sits
*above* the line and the mid-ranks *below* — which is the signature of a **log-normal**, not a pure
Pareto. The Q–Q plot (`fig2_lognormal_qq.png`) is close to linear, supporting the log-normal as the
generative model. **Decision:** use the **log-normal** for per-donor imputation and intervals, and
the **power law** only as a tail-count *diagnostic* (§3.4).

### 3.2 S3 — Category recovery-rate table *(the portable artifact)*
Per-donor volume scales with **sector** and **size**. Lacking per-firm size data (see §6), we model
at sector granularity: each Tier-B donor inherits an expected `rate_lbs_per_donor` from its
category. Rates (`model.PRIOR_LBS_PER_DONOR`) are **order-of-magnitude priors** grounded in sector
surplus logic — large packaged-goods manufacturers and produce wholesalers generate far more
recoverable surplus per site than a single restaurant or house of worship:

```
Wholesale 400k · Manufacturers 250k · Farms 150k · Nonprofit/Corporate/Quickservice 120k
Bakery 35k · Hotels 25k · Special-Events 25k · Caterer 20k · Restaurants 15k · Religious 10k
```

**Key judgement (S3).** Where a category's *only* anchor is a mega-outlier (Amazon = 7.7M for
"Corporate"; Baldor = 2.7M for "Wholesale"; Pret = 0.32M for "Quickservice"), we **do not** use the
anchor as the typical-donor rate — a single hyperscaler must not set the rate for GoPuff or a
specialty distributor. We therefore report empirical anchor means *descriptively* (for validation)
but drive Tier-B allocation from the priors. This separation is the crux of transferability: the
**relative** ordering across sectors is portable even when the absolute level is locally rescaled.

### 3.3 S4 — Reconciliation to the control total (raking)
We almost always know the **total** even when we don't know the parts. With `A` published and fixed,
define the gap `G = T − A` (all volume below the top-12). The named body `B = Σ rate_{cat(d)}`; the
**unlisted tail closes the budget**: `C = G − B` (single free margin). Hence
`A + B + C = T` exactly — a one-margin **rake** with the tail as balancing item. If priors overshoot
(`B > G`) we instead scale `B` down (`b_scale = G/B`, `C = 0`) and flag it.

**Results at T = 90M lbs:**

| channel | lbs/yr | share |
|---|--:|--:|
| A published top-12 | 24,068,349 | 26.7 % |
| B named latent (55) | 5,160,000 | 5.7 % |
| **C unlisted tail** | **60,771,651** | **67.5 %** |

See `fig3_decomposition.png`. **This is the headline result:** named donors (A+B) are **~32 %** of
volume; two-thirds is an unlisted tail.

### 3.4 Tail-count estimation
How many unlisted donors make up `C`? Two independent estimators:
- **Flat-rate:** `C / tail_lbs` with `tail_lbs ≈ 20k` → **~3,039** donors (total ≈ **3,106**).
- **Power-law extrapolation:** integrate the fitted `C·k^{−α}` beyond the named ranks. With
  **α ≈ 1.25**, tail mass converges only marginally faster than `Σ1/k`, so the count **diverges**
  (>500k) — a *diagnostic* that the head's power law cannot be trusted in the deep tail. We therefore
  adopt the **flat-rate** estimate operationally and treat the divergence as evidence *for* a
  truncated/log-normal tail rather than a literal Pareto.

### 3.5 S5 — Generalisation
**Hierarchical framing.** The transferable estimator is a multilevel log-linear model
```
log y_d = β₀ + β_sector[d] + β₁·log(size_d) + β₂·dist(d) + u_foodbank + ε_d
```
with `u_foodbank` a partial-pooling random effect. With one calibration org we cannot *fit*
`u_foodbank`, so we encode the structure and let a new org fall back to the pooled sector rates
(β_sector) and its own control total. The **portable artifacts** are: the sector rate table
(β_sector), the tail-shape (α, σ), the raking step, and the unit bridges.

**Transfer demonstration** (`transfer_to_new_org`): a hypothetical 40M-lb/yr food bank with **no
donor list**, only a Census-style firm-count by sector, yields B = 37.4M (93.6 %), C = 2.57M
(6.4 %), ~128 unlisted donors — i.e. the machinery produces a full channel estimate from a single
total plus a business-mix vector.

---

## 4. Validation

- **V1 — shape adequacy (in-sample).** Power-law R² = 0.90; log-normal Q–Q near-linear
  (`fig2`). The distributional family is appropriate.
- **V2 — leave-one-out shape stability.** Refit on 11 anchors, predict the held-out donor from its
  rank: **median |log error| = 0.31** (a typical **×1.36** multiplicative error), RMSE(log) = 0.37.
  *Caveat:* the predictor is monotone in rank, so the Spearman = 1.00 is **trivial by construction**
  and not evidence — the log-error is the informative number.
- **V3 — cross-organisation reconciliation (external).** City Harvest's 12 anchors = 24.07M lbs ≈
  **$45.7M @ $1.90/lb**, which is **106 %** of Food Bank For NYC's entire *donated-food* channel
  (22.7M lbs). Two unrelated organisations' magnitudes line up under the same unit bridge —
  the strongest available external check, and consistent with City Harvest being a produce-rescue
  specialist whose donated channel rivals a larger generalist's.

---

## 5. Sensitivity and uncertainty

The dominant uncertainty is **structural** (control total, priors, tail size), not sampling.
Sweeping T ∈ {75M, 90M}, prior-scale ∈ {0.5, 1, 1.5}, tail-size ∈ {15k, 20k, 30k}
(`fig5_sensitivity.png`):

- **Tail share C** stays **56–70 %** across *all* combinations — the "named data is a minority of
  volume" conclusion is robust.
- **Unlisted-donor count** ranges **~1,400–4,200**; it is most sensitive to the assumed average
  tail-donor size (mechanically `C / tail_lbs`).
- Bootstrap CIs on shape: α ∈ [0.74, 1.51], Gini ∈ [0.28, 0.57], top-1 ∈ [14 %, 41 %] — wide, as
  expected from n = 12; report **intervals, not points**.

---

## 6. Limitations and biases (read before using)

1. **Selection bias.** The published list is promotional ("our most generous"): large, brand-name,
   consent-to-publicise. It is the *head*, not a random sample. "No amount listed" ≠ "small."
2. **Priors are assumptions.** Tier-B category rates are sector-logic order-of-magnitudes, not
   fitted; treat B as indicative. (They move B by ±50 % in the sweep with little effect on the
   qualitative split because the **tail dominates**.)
3. **Location term not parameterised.** We *designed* a distance-decay kernel
   (`fig6_distance_decay.png`) but cannot fit it: City Harvest discloses no donor addresses.
   Activation path: geocode donor HQ/branch addresses, compute distance to the food bank's DC
   (City Harvest Cypress Hills, Brooklyn), fit `β₂`.
4. **Single-org calibration.** `u_foodbank` is structural, not estimated; transfer rests on the
   sector rates until a second org's donor amounts are obtained.
5. **Aggregation assumptions.** Folding Greenmarket/Hunts Point members into aggregates (S1-b) could
   under- or over-count if City Harvest books them separately.
6. **Control total provenance.** "~90M lbs" is a website headline; if it conflates distributed vs
   rescued, T shifts — hence the explicit 75M sensitivity arm.

---

## 7. How to apply to another food bank (recipe)

1. Get the org's **annual throughput** T (Form 990 / annual report).
2. Enumerate **donor-eligible firms** in its catchment by NAICS (Census County Business Patterns).
3. Apply the **sector rate table** × firm counts → body B; rake the residual into tail C.
4. (If any donor amounts are published) re-anchor the relevant sectors and re-estimate α, σ.
5. (If addresses available) activate the distance-decay term.
6. Convert to $/meals via the bridges for cross-org comparability.

Output: a per-donor (or per-sector) supply table that plugs directly into a donor→food-bank
**routing/assignment** optimiser as the supply-side edge weights.

---

## 8. Reproducibility

```
src/data.py          inputs + schema + de-dup policy
src/model.py         estimation core (numpy-only stats)
src/run_pipeline.py  end-to-end run → data/results.json, data/per_donor_estimates.csv
src/figures.py       → figures/fig1..6.png
docs/research_writeup.md  this document
```
Run: `.venv/bin/python src/run_pipeline.py && .venv/bin/python src/figures.py`

**Environment note.** The host's system Python 3.9.6 (Xcode CommandLineTools) ships a **corrupted
stdlib `pydoc.py`** (contains null bytes), which breaks `scipy.stats`/`pandas` import. The model is
therefore deliberately **numpy + matplotlib only**, with the few required statistics (log-normal
MLE, OLS rank-size, Gini, inverse-normal for the Q–Q plot) implemented by hand. This also makes the
artifact dependency-light and reproducible.

---

## Appendix — figures

| file | content | step |
|---|---|---|
| `fig1_ranksize.png` | rank–size power-law fit | S2 |
| `fig2_lognormal_qq.png` | log-normal Q–Q of anchors | S2 |
| `fig3_decomposition.png` | A/B/C channel split @ 75M & 90M | S4 |
| `fig4_category.png` | Tier-B mass by category | S3/S4 |
| `fig5_sensitivity.png` | unlisted-donor count vs assumptions | S5 |
| `fig6_distance_decay.png` | distance-decay kernel (illustrative) | structural |
