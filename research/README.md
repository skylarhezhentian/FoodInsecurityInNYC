# Research walkthrough

[Project overview](../README.md) · [Run every stage](../docs/reproduce.md) ·
[Laidlaw poster](../poster/Skylar_Tian_Laidlaw_Poster.pdf)

The research asks how food-rescue allocation changes when route priorities
account for both neighborhood need and access to existing providers. The work
progresses from geographic analysis to a constrained routing scenario, the
Laidlaw study, and a later corrected model.

## 1. Locate gaps in food access

The [included public snapshots](../data/upstream/README.md) cover provider
locations and schedules, neighborhood food-insecurity estimates, Census
population, and geographic boundaries. The [preprocessing work](preprocessing/README.md)
starts with community-district and neighborhood maps, then calculates enhanced
two-step floating catchment area (E2SFCA) accessibility using provider opening
hours, population, and distance decay.

The final access table covers 197 residential neighborhood tabulation areas
(NTAs). Replaying the included snapshots reproduced all four saved CSV tables,
including the donor estimates, byte for byte. This checks the recovered
calculations; original acquisition dates and code revisions were not recorded
for every file.

## 2. Develop a delivery scenario

The [instance builders](experiments/README.md#rebuild-the-final-instance) join
recipient locations to the neighborhood equity table and assign scenario
demand, delivery windows, depots, and vehicles. The final instance contains
528 recipients, two depots, and 25 vehicles; the donor table adds 18 pickup
candidates. The included inputs rebuild the saved instance byte for byte.

The [donor-volume study](preprocessing/donor_model/) explores published donation
anchors, category assumptions, and total-volume reconciliation. It is supporting
research: no recovered program establishes that its estimates generated the
final 18-donor scenario. Pickup-day supplies and recipient demands remain
modeled assumptions.

## 3. Compare routing priorities

[The experiment guide](experiments/README.md) traces the early prototypes,
five-policy allocations, depot sensitivity, equity-weight sweep, robustness
worlds, and distributional analysis. [Historical source](historical/README.md)
preserves the implementations used during this work.

The final poster study retains 55 runs: five perturbations for each of eleven
settings. [Recipient-level records](../data/study/) allow its served counts and
coverage metrics to be recomputed. Earlier scenarios and sensitivity exercises
have their own records; their results are not pooled with the final study.

## 4. Present the Laidlaw findings

The [poster guide](../poster/README.md) connects each figure and table to its
inputs and construction. The repository includes the original PDF, recovered
LaTeX source and figure assets, [portable figure redraws](../results/poster/),
and the [earlier working-paper draft](writing/README.md).

The poster describes the original model. Later review found that the full-study
solver omitted service time and could permit cold cargo to exceed total cargo.
Its saved served sets reproduce allocation statistics, but the full routes were
not retained and their feasibility cannot be established. The poster guide
records these limitations alongside the unchanged research output.

## 5. Correct the model and check every route

The [current implementation](../src/food_rescue/routing.py) includes service
completion within delivery windows, total and refrigerated capacity checks,
cold cargo bounded by total cargo, and consistent integer pickup quantities.
It also changes the initial cold staging assumption.

The [fixed benchmark protocol](../docs/benchmark_protocol.md) compares five
policies across five small penalty perturbations. All 25 saved solves include
full routes and input provenance. An independent replay checks timing, cargo,
capacities, objectives, and metrics for all 625 vehicle routes. Read the
[current results](../docs/results.md) and [methodology](../docs/methodology.md)
for the comparison and its limits.

This is a later model version within the same research project. Its numerical
results cannot be substituted into the original poster: model constraints and
initial staging differ, and neither study measures actual deliveries or changes
in household food insecurity.

## Reproduce the work

The [shared run guide](../docs/reproduce.md) follows these stages, with commands,
environment requirements, output locations, and a quick path for checking the
included results. All documented analysis inputs are included. Dependencies
need to be installed first; the replay itself uses no API keys or downloads.
