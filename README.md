# Food-rescue routing toolkit (v0)

Turns your spatial analysis into a runnable, equity-aware routing instance and a first solve.
The pipeline is: **`cd_summary.csv` + `donor_classes.csv` → `build_instance.py` → `instance.json` → `solve_rescue.py` → routes + `route_demo.png`.**

## Files

- `donor_classes.csv` — City Harvest’s donor categories mapped to product class, cold-chain flag (ρ), shelf-life range (L_p), and supply behaviour (mean lbs, variability, availability). This is your parameter spec.
- `cd_summary.csv` — your 59 community districts (need, access, providers, terciles).
- `build_instance.py` — assembles depot + donor nodes (pickups) + recipient nodes (deliveries) with equity weights `w_r = (need_t+1)/(access_t+1)`. Writes `instance.json`.
- `solve_rescue.py` — deterministic single-commodity solve with OR-Tools; equity enters as a skip-penalty; compares uniform vs equity modes and plots routes.
- `instance.json`, `route_demo.png` — generated artifacts.

## Quickstart

```bash
pip install ortools pandas numpy matplotlib
python build_instance.py                 # -> instance.json (1,460 donors, 528 recipients)
python solve_rescue.py --boro 3 --vehicles 2 --horizon 300 --max-recip 40
```

## The v0 model

One commodity (total lbs). Vehicles leave the depot, **pick up** at donors (load +) and **deliver** to recipients (load −), within time windows and vehicle capacity. The load dimension can’t go negative, so deliveries can’t precede pickups. Equity is a **skip penalty**: serving recipient *r* is worth `BASE × w_r`, so high-need/low-access districts are expensive to leave unserved. Two modes run on the same subset — `uniform` (equal penalties) vs `equity` (penalty ∝ w_r).

## What the demo shows (Brooklyn, 2 vehicles, 5-hour shift, 40 recipients)

|                             |uniform|equity |
|-----------------------------|-------|-------|
|recipients served            |24/40  |19/40  |
|**priority districts served**|**1/6**|**5/6**|
|travel (min)                 |570    |525    |

Equity reallocates a scarce fleet toward the priority (high-need, low-access) districts — fewer recipients overall, but the underserved get reached. That throughput-vs-priority gap is your first empirical slice of the efficiency–equity trade-off. See `route_demo.png`.

## What is real vs placeholder (replace as you go)

- **Geography is synthetic** except the depot (150 52nd St, Brooklyn), Hunts Point, and the GrowNYC markets. Swap in your real 528-provider coordinates: `python build_instance.py --providers my_providers.csv` (columns: `lon,lat[,w][,demand_lbs][,boro]`). Geocode donors from the City Harvest list, OSM/Overpass, or DOHMH.
- **Time windows** are placeholders — replace with real provider open-hours and donor availability.
- **Supply/demand lbs** are heuristic — calibrate to City Harvest volume (~90M lbs/yr) and pantry throughput.
- **Distances** are haversine — swap in OSRM road travel times.
- **Product classes / perishability / cold-chain** live in `donor_classes.csv` but the v0 solver aggregates to total lbs.

## Roadmap to the full formulation

- **v1:** real geo; multi-product with a cold-chain fleet (split capacity, refrigerated vehicles only carry ρ=1 products); add a freshness term using shelf life + an age-decay value φ_p.
- **v2:** two-stage stochastic donations — sample supply scenarios from each donor’s `avail_prob` and `supply_cv`, commit routes first-stage, re-allocate deliveries as recourse, and average over scenarios (SAA). OR-Tools is ideal for the deterministic/heuristic core; pair it with an SAA wrapper, or move to a MIP/branch-price-and-cut for exact stochastic results.

*This is a synthetic instance for validating the pipeline and the equity mechanism — not a model of actual City Harvest operations.*