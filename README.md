# Equity-aware food rescue in New York City

[![Reproduce and test](https://github.com/skylarhezhentian/FoodInsecurityInNYC/actions/workflows/tests.yml/badge.svg)](https://github.com/skylarhezhentian/FoodInsecurityInNYC/actions/workflows/tests.yml)

Food-rescue routes can reach many sites while leaving high-need neighborhoods
underserved. This Laidlaw research project asks how route priorities change the
balance between broad coverage, neighborhood need, and access to existing food
providers.

The project combines public NYC geography and neighborhood indicators with an
OR-Tools vehicle-routing model. Five policies share the same recipient demand,
fleet, travel estimates, time windows, and refrigerated-cargo constraints. The
included scenario has **528 recipient sites, 18 donor candidates, two depots,
and 25 vehicles**.

## Poster and research trail

Read the [Laidlaw symposium poster](poster/Skylar_Tian_Laidlaw_Poster.pdf) or
follow the [source-data-to-poster guide](poster/README.md). The archive includes
data preparation, access calculations, donor modeling, earlier experiments,
the final 55 saved study runs, figure code, manuscript drafts, and the recovered
poster source. The poster reports the original study; the results below use the
later corrected routing model.

## Example results

In the corrected comparison, need/access priorities gave the highest median
high-need coverage; access-only priorities reached the most sites. Both used
more total route time than the unweighted baseline. The table shows medians
across five small penalty perturbations per policy.

| Policy | Sites served | High-need demand covered |
| --- | ---: | ---: |
| Unweighted | 95 | 7.0% |
| Random preference | 109 | 10.8% |
| Need only | 92 | 28.8% |
| Access only | 171 | 22.5% |
| Need / access | 160 | 39.3% |

High-need coverage is demand-weighted within the 240 sites carrying the supplied
high-need label. The ranges below show sensitivity to the small perturbations and
bounded search; they are not confidence intervals or evidence of a universal
policy ranking.

![Sites served and high-need coverage across the five policies](docs/assets/policy_comparison.png)

These are modeled allocations, not observed deliveries or estimates of reduced
food insecurity. Search is time-limited; another run can find different routes.
All 25 saved solves include their full routes, inputs, settings, and checks in
[results/corrected](results/corrected). See [full results and timing](docs/results.md)
and the [methods](docs/methodology.md) for the objective, metrics, and assumptions.

## Run it

Use Python 3.11. All inputs for the documented commands are included; no API key
or data download is needed.

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python scripts/verify_benchmark.py
python scripts/run_routing_demo.py
```

The first script independently rebuilds the saved results from every route,
without running the optimizer. The second solves a small, three-policy example
and checks timing, capacities, and cargo conservation.

To reproduce the earlier 55-run study tables, run
`python scripts/reproduce_results.py`. To run the full new comparison, use
`python scripts/run_benchmark.py` (25 solves, each with a 10-second search limit).
See the [run guide](docs/reproduce.md) for figures, tests, outputs, and Windows
setup.

## Repository guide

| Folder | Contents |
| --- | --- |
| `src/food_rescue/` | Current routing model, route audit, and saved-study analysis. |
| `scripts/` | Commands to solve, replay results, reproduce tables, and draw the figure. |
| `data/` | Public source snapshots, intermediate tables, model inputs, original saved study, and provenance. |
| `configs/` | Fixed settings for the corrected five-policy comparison. |
| `results/corrected/` | All 25 new route records, summaries, and verification evidence. |
| `docs/` | Methods, experiment protocol, reproduction guide, and figures. |
| `tests/` | Data integrity, accounting, feasibility, and saved-result regression tests. |
| `poster/` | Original poster PDF, recovered layout source, references, and evidence guide. |
| `research/` | Preprocessing, historical solvers, earlier experiments, and working-paper drafts. |

## Data and research limits

Locations and neighborhood indicators come from public sources. Supply, demand,
fleet, and cold-share quantities are scenario assumptions. The cached travel
estimates may include distance-based fallbacks, and their historical coordinate
alignment cannot be independently certified. [Data provenance](data/README.md)
records these limits and the source attribution.

The earlier full-study solver omitted service time and allowed inconsistent
cold/ambient inventory. Its 55 saved outputs remain available for
[accounting reproduction](docs/historical_results.md). The current model corrects
those constraints and changes initial cold staging; the two sets of results
describe different scenarios.

## Acknowledgments

Skylar Tian · Columbia University · Laidlaw Undergraduate Research and Leadership
Program. Faculty mentor: George Dragomir.

Travel estimates use OSRM and © [OpenStreetMap contributors](https://www.openstreetmap.org/copyright).
