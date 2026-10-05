# NYC Food-Rescue Routing (laidlaw-vrptw)

> **v1 is here.** A multi-depot, multi-commodity (cold-chain), time-windowed
> rebuild on road-network travel times with smooth equity weights and an exact
> optimality-gap check — see **[README_v1.md](README_v1.md)**. The v0 model below
> is kept for reference and comparison.

---

## v0 (reference)


Multi-depot CVRP that dispatches a **20-vehicle fleet from the 5 largest NYC
wholesale/supermarket origins** to **528 open NYC food pantries**, with an
equity-weighted skip penalty so high-need / low-access neighborhoods can't be
ignored. Builds on `foodbank-donor-model` (per-donor estimates) and
`foodhelp-nyc` (provider list + NTA E2SFCA equity index).

Pipeline: **`origins.csv` + `efap_pfred_programs.csv` + `nta_equity_index.csv`
→ `build_instance.py` → `instance.json` → `solve_routes.py` → `routes.json` +
`route_map.png`.**

## Files

- `data/origins.csv` — the 5 origin depots (name, address, lat/lon, est_lbs/yr, n_vehicles).
- `build_instance.py` — loads origins + pantries + NTA equity, point-in-polygon
  assigns each pantry to its NTA, derives `w_r = (need_t+1)/(access_t+1)` clamped
  to [0.5, 4.0], and writes `instance.json`.
- `solve_routes.py` — OR-Tools multi-depot CVRP. Each vehicle starts and returns to
  its assigned origin. Pantries are droppable for a penalty
  (`uniform`: BASE; `equity`: BASE × w_r). Compares the two modes side-by-side and
  plots the routes.
- `instance.json`, `routes.json`, `route_map*.png` — generated artifacts.

## The 5 origins

Picked from `per_donor_estimates.csv` (Tier A) — the largest wholesale and
supermarket donors by estimated annual lbs to City Harvest:

| # | Name | Borough | est lbs/yr | Veh |
|---|------|---------|-----------:|----:|
| 1 | Hunts Point Produce Market | Bronx (Hunts Point) | 3,360,391 | 4 |
| 2 | Baldor Specialty Foods | Bronx (Hunts Point) | 2,735,367 | 4 |
| 3 | Trader Joe's flagship (14 St) | Manhattan (Union Sq) | 2,673,191 | 4 |
| 4 | FreshDirect | Bronx (Port Morris) | 2,522,874 | 4 |
| 5 | Whole Foods Market (Bowery) | Manhattan (LES) | 1,368,433 | 4 |

3 of the 5 sit in/near the Hunts Point complex — that's not an artifact of the
data, that's where NYC's wholesale food actually lives.

## Quickstart

```bash
python3 -m venv .venv
.venv/bin/pip install ortools numpy matplotlib pandas
.venv/bin/python build_instance.py         # -> instance.json (5 origins, 528 pantries, 20 vehicles)
.venv/bin/python solve_routes.py           # -> routes.json, route_map.png (uniform vs equity)
.venv/bin/python solve_routes.py --tight   # constrained fleet — surfaces the equity trade-off
```

## The v0 model

One commodity (total lbs). Each vehicle leaves its origin, **delivers** lbs to a
sequence of pantry stops within capacity and shift length, then returns. Distances
are haversine, travel time at 25 km/h, service 8 min/stop.

### Per-pantry demand (`--demand-mode`)

Four ways to size how much each pantry needs, increasingly grounded:

| mode | basis | spread |
|---|---|---|
| `flat` | 80 lbs FP / 120 SK (v0 placeholder) | none |
| `equity` | `80 · (1 + 2·equity_index)` — NTA-level tilt | narrow (80–284) |
| `fi_pop` | NTA food-insecure pop ÷ pantries-in-NTA · per_capita | medium |
| `realistic` *(default)* | **capacity-driven from each pantry's operating hours** | **wide (CV 0.79, 10–1,493 lbs)** |

The **`realistic`** model is the high-variation one and uses real anchors:

```
FP demand = hours_per_session · 15 households/hr · 30 lbs/household · need_mult · noise · donor_share
SK demand = hours_per_session · 60 meals/hr      · 1.2 lbs/meal     · need_mult · noise · donor_share
```

- **hours_per_session** = weekly open-hours ÷ #open-days, parsed from the
  `fp_*_open/close` columns. This is the pantry-specific signal that makes demand
  vary (median 2.3 h, range 0.5–14 h) — same neighborhood, different pantry sizes.
- **30 lbs/household** = 4 lbs × 2.5 persons (NYC avg household, 2020 Census) ×
  3 days of food — the End Hunger in America pantry-allotment rule.
- **1.2 lbs/meal** = USDA *What We Eat in America* / Feeding America conversion.
- **15 households/hr** anchored to a City Harvest partner pantry (20–30 new
  families/shift + returning); **60 meals/hr** for on-site soup-kitchen service.
- **need_mult** = `1 + 0.5·equity_index` — a mild tilt so high-need areas need more.
- **noise** = seeded lognormal(0, 0.35) — within-group spread; two same-size
  pantries don't get identical demand.
- **donor_share** = 0.15 — these 5 donors supply ~15% of each pantry's throughput
  (the rest comes from other donors / the unlisted tail). Scales total demand vs
  fleet. Echoes the donor model's finding that *named* donors are ~32% of volume.

Note a real consequence: a **food pantry moves more weight per open-hour than a
soup kitchen** (~450 vs ~72 lbs/hr) — bulk groceries outweigh prepared meals.

Equity is a **skip penalty**: serving pantry *r* is worth `BASE × w_r`, so
high-need / low-access NTAs are expensive to leave unserved. The two modes
(`uniform` vs `equity`) run on the same instance — the only thing that changes
is whether `w_r` multiplies the penalty.

NTA equity weights come from `foodhelp-nyc/analysis/output/nta_equity_index.csv`
(E2SFCA access tercile × food-insecurity need tercile). Each open pantry is
point-in-polygon assigned to one of 262 NTA polygons; 528/528 pantries match.

## What the demo shows

With **`realistic` demand** (default), total demand (~98,900 lbs) just exceeds
fleet capacity (80,000 lbs), so the solver must skip some pantries — the equity
term decides which. Same total food delivered (~80k lbs), redistributed:

|                              | uniform | equity  |
|------------------------------|--------:|--------:|
| pantries served              |  462    |  432    |
| priority pantries served     |  85/103 | **103/103** |
| total travel (min)           | 5,815   | 5,547   |
| total delivered (lbs)        | 79,847  | 79,934  |
| **flat coverage (% lbs)**    |  80.8   |  80.8   |
| **need-weighted coverage**   |  80.8   | **90.3** |
| low-need tier coverage       |  70.4   |  16.4   |
| mid-need tier coverage       |  80.6   | **100.0** |
| **high-need tier coverage**  |  86.0   | **100.0** |

Same trucks, same total lbs — but equity drives **mid- and high-need tiers to
100% coverage** by pulling out of low-need areas (70%→16%). The metric that moves
is **need-weighted coverage: 80.8 → 90.3%**. See `coverage_bars.png`,
`route_map_realistic.png`, and the demand spread in `demand_distribution.png`.

A `--tight` flag (1,500 lb capacity, 4-hr shift) makes scarcity even sharper.

## What is real vs placeholder (replace as you go)

- **Origins**: top 5 by est lbs from `per_donor_estimates.csv` (Tier A
  wholesale/supermarket donors). Geocoded by hand to known facility addresses.
  Trader Joe's and Whole Foods are multi-site chains; the flagship store stands
  in as a single-pickup proxy. Swap for true distribution-center coords if known.
- **Pantries**: 528 real, currently-open NYC pantries with lat/lon from
  Food Help NYC (`efap_pfred_programs.csv`). Hours are loaded but the v0 solver
  doesn't enforce time windows — only a single shift cap per vehicle.
- **Equity weights** `w_r ∈ [0.5, 4.0]`: real, derived from
  E2SFCA × food-insecurity terciles per NTA.
- **Demand lbs**: `realistic` mode is now **derived from real operating hours +
  published meal/household anchors** (see above), not a flat placeholder. Still
  synthetic in that throughput rates (15 households/hr, 60 meals/hr) and
  donor_share (0.15) are calibrated, not measured — replace with City Harvest
  delivery logs or DOHMH meal counts when available.
- **Travel**: haversine at 25 km/h — swap in OSRM road times for realism.
- **Single commodity**: no perishability, no cold-chain split fleet, no product
  classes.

## Roadmap

- **v1**: pantry **time windows** from `fp_mon..fp_sun` columns; OSRM road times;
  proportional vehicle allocation (more vehicles to higher-throughput depots).
- **v2**: multi-product with a cold-chain fleet (refrigerated vehicles for
  produce / dairy / prepared meals from the perishability column in the donor
  category table); add a freshness term using shelf life + age-decay value.
- **v3**: two-stage stochastic donations — sample supply scenarios from each
  donor's expected `avail_prob` × `supply_cv`, commit routes first stage,
  re-allocate deliveries as recourse, average over scenarios (SAA).

## Demand-model sources

- **1.2 lbs = 1 meal** — Feeding America meal-conversion (USDA *What We Eat in
  America*). https://www.feedingamerica.org/
- **4 lbs × household size × days of food** per pantry visit — End Hunger in
  America, "How to Run a Food Pantry" FAQ.
  https://www.endhungerinamerica.org/publications/how-to-run-a-food-pantry/frequently-asked-questions/
- **NYC avg household ≈ 2.5 persons** — 2020 Census, NYC Dept. of City Planning.
  https://www.nyc.gov/site/planning/planning-level/nyc-population/2020-census.page
- **Pantry intake 20–30 families/shift** — City Harvest partner (Golden Harvest,
  Brooklyn). https://www.cityharvest.org/food-distribution/
- **Largest NYC soup kitchen ≈ 5,000 meals/week** — Holy Apostles NYC.
  https://holyapostlesnyc.org/soup-kitchen-and-pantry/daily-meal-service/
- **System scale: 1.4M residents, ~25M visits/yr, 532 facilities** — NYC Food
  Policy Center. https://www.nycfoodpolicy.org/nyc-by-the-numbers-food-insecure-households-pantries/

*This is a synthetic-demand instance built on real NYC pantry geography for
validating the pipeline and the equity mechanism — not a model of actual City
Harvest or Food Bank for NYC operations.*
