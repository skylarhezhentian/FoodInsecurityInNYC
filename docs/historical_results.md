# Saved study: accounting reproduction

The original saved experiment contains 55 runs: five small penalty perturbations
for each of 11 settings. The settings are random preference, need only, access
only, and eight need/access exponents (`gamma = 0, 0.25, 0.5, 0.75, 1, 1.5, 2, 3`).
Gamma zero is the unweighted baseline; gamma one is the need/access comparison.
They reuse the same saved runs rather than adding separate experiments.

`python scripts/reproduce_results.py` joins each saved served set to the supplied
recipient table. It reconstructs recipient counts, delivered demand, coverage by
need tier, and reference-weighted coverage, then checks reported run and summary
values at their saved precision. It needs no optimizer or network access.

All 55 runs reconcile: 330 joined run metrics and 385 stored summary values pass
their precision checks. The historical `travel_min` metric is retained as
stored; the original reporter sums route elapsed time, including waiting, under
its original timing model. The saved replicate file does not contain routes
from which to reconstruct that quantity.

| Historical policy | Median sites served | Median high-need coverage | Median reference-weighted coverage |
| --- | ---: | ---: | ---: |
| Unweighted | 231 | 26.3% | 29.2% |
| Random preference | 234 | 25.3% | 31.5% |
| Need only | 209 | 57.7% | 36.4% |
| Access only | 194 | 22.4% | 41.5% |
| Need / access | 183 | 44.1% | 45.7% |

These are **historical accounting results, not validated routing performance**.
The recovered full-study solver omitted service time and did not enforce cold
cargo as a subset of total cargo. Full routes were not retained for the 55 runs,
so their feasibility cannot now be established from the saved file. They must
not be used as evidence that a real operation could achieve these outcomes.

The main README instead reports the corrected comparison, with full route
records and an independent replay check. Its changed constraints and initial
cargo composition make it a different scenario.

The original source snapshot is in [research/historical](../research/historical).
It was recovered beside the saved inputs, but the saved output has no source
revision identifier. The first public two-vehicle prototype remains in
[Git history](https://github.com/skylarhezhentian/FoodInsecurityInNYC/tree/89c50c5bf44b0cdcad109db0743cc25428880e79).
It is separate from this later full-city experiment.
