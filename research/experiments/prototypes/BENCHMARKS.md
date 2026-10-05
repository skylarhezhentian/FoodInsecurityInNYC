# Benchmark validation — every number in the model

Every constant, where it comes from, and a sanity check. **Bold source** = external
published figure; *italic* = calibrated/assumed (replace with measured data when you
have it). Two numbers were corrected after review — see the last section.

## Demand model

| Parameter | Value | Source | Sanity check |
|---|---|---|---|
| Meal → weight | **1.2 lb/meal** | USDA *What We Eat in America*, used by Feeding America | Consistent across HACAP, Feeding America FAQ, food banks |
| Daily food/person | **3.6 lb/day** (= 1.2 × 3 meals) | Feeding America | — |
| Pantry visit allotment | **4 lb × household × days** | End Hunger in America "How to Run a Food Pantry" | Their example: 3 people × 4 days = 48 lb |
| NYC household size | **2.5 persons** | 2020 Census (NYC DCP) | Pantry clients skew larger; 2.5 is conservative |
| Days of food per visit | *3 days* | TEFAP-style 3-day supply (common standard) | Many pantries do 3–5; 3 is conservative |
| **⇒ lb per FP household-visit** | **30 lb** (4×2.5×3) | derived | vs End Hunger's 48 lb (3p×4d) — conservative |
| FP throughput | *15 households/hr* | City Harvest partner: 20–30 *new* families/shift + returning | Bounds: tiny pantry ~5/hr; CTX mobile mega-event ~505/hr. 15 is mid-low for a staffed neighborhood pantry |
| SK throughput | *60 meals/hr* | Holy Apostles NYC ~5,000 meals/wk (largest) | A mid-size kitchen serves 50–150/session |
| Hours/session | data, **capped 5 h** | parsed `fp_*/sk_*` open/close | A single distribution runs 2–5 h (see correction below) |
| donor_share | *0.12* | these 5 donors ≈ a slice of supply; donor model: *named* donors ≈ 32% of rescued volume | ⇒ implied full pantry throughput p50 ≈ 1,040 lb, max ≈ 7,860 lb/cycle (Capuchin pantry ≈ 12,500 lb/day) |
| Need tilt | *1 + 0.5·equity_index* | mild; demand rises with neighborhood need | bounded 1.0–1.4 |
| Noise | *lognormal CV 0.30, ±2σ* | within-group spread | bounded so no fat tail |

**Resulting per-delivery demand (v1):** min 10, median 125, p99 596, **max 943 lb** — i.e.
a single delivery is 0–31 households' worth of the food *these 5 donors* supply. The pantry's
full distribution (all donors) is ~8× larger, which lands in the published per-pantry range.

## Equity weights

| Parameter | Value | Source | Sanity check |
|---|---|---|---|
| Food-insecurity rate (need) | per-NTA | **Map the Meal Gap** (Feeding America) regression on USDA CPS, applied to NTA demographics | NYC analysis: 197/197 NTAs matched |
| Access score | per-NTA | **E2SFCA** (enhanced 2-step floating catchment) on 528 providers × open-hours | standard accessibility method |
| need_pct, access_pct | continuous percentiles | from the two above | replaces 3-bin terciles → 128 distinct weights |
| w = (need_pct/access_pct)^γ | clamped **[0.5, 4.0]** | this model (L6) | γ=1 default; smooth, no bin jumps |

## Travel times

| Parameter | Value | Source | Sanity check |
|---|---|---|---|
| Detour factor | **1.33** | fit from **3,536 real OSRM driving pairs** across NYC pantries | literature urban circuity 1.3–1.4 ✓ |
| OSRM free-flow speed | **46 km/h** | the same OSRM sample (no traffic) | highway-weighted, no congestion |
| Congestion factor | *0.42* → ~19 km/h effective | calibrated to NYC reality | Manhattan CBD **8.2 mph ≈ 13 km/h** (NYC DOT); outer-borough/highway faster → ~19 km/h citywide trip-average is reasonable |
| road vs full-OSRM | corr **0.979** (dist), times 40.2 vs 39.9 min | validation run | calibration holds |

## Fleet / operations

| Parameter | Value | Source | Sanity check |
|---|---|---|---|
| Vehicles | 20 (17 reefer + 3 dry) | the brief; reefer_frac 0.7 | — |
| Vehicle capacity | *2,500 lb* (scarce scenario) / 4,000 lb (default) | reefer box van | reefer vans carry ~2,000–7,000 lb palletized |
| Shift | *480 min from 07:00* | assumption | a morning delivery shift |
| Service/stop | *8 min* | assumption | curbside drop |
| Cold fraction | *Beta(2.4,1.8)≈0.57*, 20% ambient-only | donor mix (produce-heavy) | rescued food is produce/dairy-heavy |
| Skip penalty | *3,000–5,000* (× w in equity) | tuning so weights drive selection | ≫ per-stop travel, so all stops worth serving unless capacity-bound |

## Two corrections made after review

1. **The 8,452 lb outlier** came from the *uncalibrated prototype* (no `donor_share`) where a
   pantry's "hours per session" hit 14 h (high weekly hours ÷ few recorded distinct days) and
   compounded with unbounded noise: 15 × 14 × 30 × 1.35 ≈ 8,500 lb. It never shipped. Fix:
   **cap hours/session at 5 h**, **truncate noise at ±2σ**, **cap catchment at 3× median**.
   New max = **943 lb**, p99 = 596 lb.

2. **Travel speed.** The earlier congestion factor (0.6 → 27 km/h) was too fast given Manhattan
   CBD averages ~8 mph. Lowered to 0.42 → ~19 km/h citywide effective, with the CBD figure cited.

*Calibrated (italic) parameters are the honest weak points — throughput rates, donor_share, and
the operational assumptions. Each is bounded by a published figure but not measured; the model
exposes every one as a CLI flag, and the equity result (reallocation toward need at ~no
throughput cost) is robust to their exact values because it depends on relative weights, not levels.*
