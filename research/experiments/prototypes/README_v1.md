# NYC Food-Rescue Routing — v1

v1 rebuilds the v0 toy into a multi-depot, multi-commodity, time-windowed model
on **OSRM road-network travel times**, with smooth equity weights and a
published-number optimality check. Each bullet below is a v0 limitation addressed.

## Travel-time matrix (canonical backend)

> **The final model uses OSRM / OpenStreetMap road-network travel times as the
> travel-time matrix. It no longer optimizes over straight-line distance. Traffic
> is represented only through a calibrated congestion factor unless live /
> time-dependent traffic data is added later.**

`--travel osrm` is the default. The full 539-node OSRM matrix is built once (121
tiled `/table` requests, cached to `osrm_cache.npz`) and every headline
artifact — the route solution, route map, equity chart, and summary stats — is
generated from it. See `backend_audit.md` (nodes, OD pairs, fallback = 0,
OSRM-vs-Level-1) and `validation_v1.md` (feasibility proof).

## Pipeline

```
data/origins_v1.csv + efap_pfred_programs.csv + nta_equity_index.csv + data/donor_classes.csv
   └─ build_instance_v1.py ─ instance_v1.json ─┐
   build_osrm_cache.py ─ osrm_cache.npz ────────┤
                                                 └─ solve_routes_v1.py ─ routes_v1.json (canonical solution)
                                                                          route_map_v1.png  (OSRM + borough basemap)
                                                                          coverage_bars_v1.png
   validate_solution.py ─ validation_v1.md   backend_audit.py ─ backend_audit.md
   plot_equity_case.py ─ equity_case.png     exact_gap.py ─ heuristic optimality gap
```

```bash
.venv/bin/python build_instance_v1.py                 # -> instance_v1.json
.venv/bin/python build_osrm_cache.py                  # -> osrm_cache.npz (once; ~2 min)
.venv/bin/python solve_routes_v1.py                   # -> OSRM solution + map + bars (canonical)
.venv/bin/python validate_solution.py                 # -> feasibility table (exits nonzero on any violation)
.venv/bin/python backend_audit.py                     # -> backend audit (OSRM vs Level-1)
.venv/bin/python plot_equity_case.py                  # -> equity_case.png
.venv/bin/python exact_gap.py --sweep                 # GLS vs proven optimum
```

## The 7 limitations, addressed

### L1 — Demand is a placeholder → capacity × catchment
Per-pantry demand is now `hours_capacity × catchment × need × noise × donor_share`:
- **hours_capacity** — operating hours/session × throughput rate × unit weight
  (15 households/hr × 30 lb, or 60 meals/hr × 1.2 lb). Real, pantry-specific.
- **catchment** — the food-insecure population *nearest* this pantry (NTA
  food-insecure pop ÷ pantries in that NTA), blended in at weight `--catchment-wt`.
  So a pantry's demand reflects both how much it can move **and** how many hungry
  people it serves. Result: demand CV ≈ 1.0, range 10–1,200+ lbs (vs flat 80/120).

### L2 — Haversine + flat speed → OSRM road-network times *(canonical)*
`geo_travel.py` has three backends; **`osrm` is the default and the headline basis**:
- `osrm` *(default)* — full 539×539 OSRM `/table` road-network matrix, tiled into
  ≤100-coord requests (via curl), cached to `osrm_cache.npz`. Build audit: **121/121
  tiles OK, 0 OD-pairs fell back**, realized detour 1.35×, mean OD time 56 min.
  Congestion enters as a flat `--congestion` multiplier on OSRM free-flow
  (default 0.42 → ~19 km/h citywide; Manhattan CBD is ~13 km/h per NYC DOT).
- `road` — Level-1 fallback: haversine × **1.33** (detour fit from 3,536 real OSRM
  pairs) × congestion. Offline/deterministic. Validates against osrm at corr **0.979**.
- `haversine` — the old straight-line model, kept only for comparison.

The two travel models give the **same equity conclusion** (see `backend_audit.md`):
need-weighted coverage 56.6→72.9% (osrm) vs 59.8→72.8% (road).

### L3 — No time windows → per-pantry delivery windows
Each pantry's open/close on the **service day** (`--service-day wed`, the busiest
with 180 open) is parsed into a `[open, close]` window (minutes from a 07:00
shift start) and enforced on the solver's `Time` dimension; vehicles may wait.
Pantries closed that day are deliverable anytime in the shift.

### L4 — Single commodity → cold-chain, two-fleet, freshness
Demand splits into **cold** (produce/dairy/prepared/meat) vs **ambient**
(bakery/dry/beverage) per `data/donor_classes.csv`. Two capacity dimensions; the
fleet is **reefer** (carries both) + **dry** (cold capacity 0, so cold orders can
only ride reefers). ~20% of pantries are dry-goods-only so the dry fleet has work.
**Freshness**: a span-cost on the `Time` dimension keeps cold food moving; we
report the **cold-lb-weighted delivery time** (avg minutes cold food sits before
drop-off). `donor_classes.csv` also carries shelf-life and value-decay per class
for a future age-decay objective.

### L5 — Chains as one point → multi-site depots
Trader Joe's (4 sites) and Whole Foods (4 sites) are now **real NYC locations**
with supply and vehicles split across them; Hunts Point / Baldor / FreshDirect
stay single-site. **11 depots across 5 donors**, still 20 vehicles. Vehicles are
bound to their site; routes on the map are colored by donor, solid=reefer,
dashed=dry.

### L6 — Tercile weights → smooth percentile weights
`w_r = ((need_pct + ε) / (access_pct + ε))^γ`, clamped to [0.5, 4.0], using the
**continuous** `need_pct` / `access_pct` percentiles (not the 3-bin terciles).
**128 distinct weights** across pantries vs 6 tercile values — no discrete jumps
at bin edges. `--gamma` sharpens/softens the tilt.

### L7 — GLS has no optimality guarantee → exact gap study
`exact_gap.py` builds a small single-vehicle prize-collecting capacitated TSP and
solves it two ways on the **identical objective** (travel + skip penalty):
- **CP-SAT** (exact, free; Gurobi is a drop-in if licensed) — `AddCircuit` with
  customer self-loops = skip; capacity = Σ served demand ≤ cap. Proves optimality.
- **GLS** — the same routing heuristic the pipeline uses.

Sweep (`--sweep`, GLS budget 5 s):

| pantries | cap % | EXACT | GLS | gap |
|---:|---:|---:|---:|---:|
| 14 | 45 | 2089 | 2089 | 0.0% |
| 20 | 70 | 1371 | 1756 | **28.1%** |
| 25 | 45 | 3372 | 3752 | 11.3% |
| 30 | 70 | 2242 | 2627 | 17.2% |

CP-SAT proves optimality on every instance; GLS is optimal on easy ones but
**leaves up to ~28% on the table** on tighter/larger instances at a short budget
(the gap shrinks as `--gls-seconds` grows). This is the honest answer to "GLS is
a heuristic with no gap": now we can quote one.

## v1 result (road times, Wed windows, cold-chain, smooth weights)

| | uniform | equity |
|---|---:|---:|
| pantries served | 459 | 440 |
| flat coverage % | 85.0 | 86.7 |
| **need-weighted coverage %** | 84.7 | **91.8** |
| cold-chain coverage % | 87.6 | 86.7 |
| high-need tier % | 89.2 | **97.4** |
| low-need tier % | 83.2 | 49.2 |
| travel (min) | 6,366 | 7,537 |

Same fleet; equity reallocates toward high-need (89→97%) and lifts need-weighted
coverage 84.7 → 91.8%, trading low-need (83→49%) and ~18% more travel. Cold-chain
coverage (~87%) is set by the reefer fleet size — tune with `--reefer-frac`.

## Still simplified (honest notes)
- Single delivery per pantry (no split cold/ambient across two trucks).
- OSRM is free-flow; the congestion factor is a flat scalar, not time-of-day.
- Demand throughput rates and `donor_share` are calibrated, not measured.
- Time windows use **client** open-hours as a delivery-window proxy.
- Perishability is a span-cost proxy; the per-class `value_decay` in
  `donor_classes.csv` isn't yet an explicit objective term.

See `README.md` for the v0 model and the demand-model source citations.
