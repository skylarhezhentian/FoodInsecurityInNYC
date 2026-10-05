# Routing model and evaluation

The research question is whether a food-rescue routing objective changes who is
served when it considers neighborhood need and food-provider access. The model
represents one delivery day in New York City, with optional donor pickups and
all-or-nothing recipient deliveries. It does not estimate changes in household
food insecurity.

## Inputs

The included instance has 528 recipient locations, 18 donor candidates, two
depots, and 25 vehicles. Geography, opening-hour fields, neighborhood need, and
provider access are derived from public sources. Demand, donor supply and
availability, fleet capacities, delivery windows, and cold shares are research
scenario assumptions. See [data provenance](../data/README.md).

Expected donor supply is supply multiplied by availability probability, floored
to integer pounds. Cold supply is floored separately from the same expectation.
A visited donor contributes that entire modeled quantity. There is no stochastic
donation realization, split delivery, or explicit pairing of a donor with a
recipient.

The cache contains estimated free-flow travel times. Its builder requests OSRM
road routes but retains a distance-based fallback for failed or missing cells;
the saved cache does not identify which cells used that fallback. The current
model divides cached times by 0.38 and rounds to integer minutes. The original
cache also lacks embedded node identities; its alignment with the current
ordered input is assumed and recorded, not independently established from the
routing service.

## Policies

Every policy uses the same constraints and base skip penalty of 8,000. For each
recipient, the penalty is multiplied by a policy weight. Let `n` and `a` be the
recipient's neighborhood need and access percentiles on `[0, 1]`.

| Policy | Weight |
| --- | --- |
| Unweighted | `1` |
| Random preference | A fixed seeded draw from `Uniform(0.3, 1.7)` |
| Need only | `clip((n + 0.15) / 0.65, 0.5, 4)` |
| Access only | `clip(0.65 / (a + 0.15), 0.5, 4)` |
| Need / access | `clip((n + 0.15) / (a + 0.15), 0.5, 4)`, rounded to three decimals |

Higher need and lower access increase the cost of skipping a recipient. These
weights encode an explicit policy preference; they are not an estimated causal
effect. In each benchmark replicate, weights receive the same seeded perturbation
of at most ±0.2%, then penalties are converted to integers. The random-preference
draw stays fixed across replicates.

## Objective and constraints

The [OR-Tools routing model](https://developers.google.com/optimization/routing)
minimizes the sum of:

1. Driving minutes over all routes.
2. Route elapsed minutes, including service and waiting, with coefficient 1.
3. Cold-delivery delay: recipient service-start minute multiplied by
   `round(0.03 × cold demand in pounds)`.
4. Penalties for recipients left unserved. Donor visits carry no skip penalty.

This mixes travel costs and policy penalties in chosen objective units. Cold
delay is a proxy, not a temperature or spoilage model. The returned objective is
reconstructed from saved routes and checked against the solver's value.
Driving contributes to both the first and second terms; service and waiting
contribute to the second term, as well as any effect on delivery delay.

Vehicles start and return to their assigned depot. Departure is minute zero;
waiting is allowed. Service takes 20 minutes at a donor and the included
`service_min` at a recipient. Service must finish within the location's window,
and the return must fit the vehicle's shift and the model horizon.

Vehicles begin with 40% of their total capacity loaded. Cold cargo is 55% of
that initial load, capped by refrigerated capacity. Dry vehicles therefore start
with ambient cargo only. At every visit, cold cargo must be nonnegative, no
greater than total cargo, and within refrigerated capacity; total cargo must
also fit capacity. Pickups and deliveries conserve integer pounds. Positive
leftover cargo may return to the depot.

Search uses parallel cheapest insertion followed by guided local search. A
10-second limit per benchmark solve bounds the search. Returned routes must pass
the independent feasibility audit; a timeout without a solution remains a failed
run. The comparison does not establish optimality. Wall-clock limits can produce
different routes on different machines or repeated runs.

## What is measured

**Sites served** measures the breadth of service, counting recipients once.

**High-need coverage** is the assumed demand served among recipients with the
provided high-need label, divided by all assumed demand in that group. The label
comes from neighborhood need and includes 240 of the 528 sites; it is not the
top third of recipient rows.

**Reference-weighted coverage** is served `demand × w_gamma1` divided by that
quantity across all recipients. Its weights favor the same need/access ratio as
one policy, so it is a secondary, preference-dependent measure. It is not the
same quantity as the solver's per-site skip penalty.

Driving, service, waiting, and elapsed times are also reported separately. The
five small perturbations are sensitivity checks, not independent sampled days;
their observed ranges are not confidence intervals. The
[fixed benchmark protocol](benchmark_protocol.md) specifies the comparison and
requires every failed or invalid run to remain visible.

## Changes from the historical study

The recovered full-study solver omitted service from its time transitions. It
also constrained cold and total cargo separately, allowing cold cargo to exceed
total cargo and thus implying negative ambient inventory. The current model
adds service, requires completion before closing, and enforces the cold subset
constraint. It also uses the same floored expected pickup quantities in both
optimization and reporting.

Initial cold staging is now a fixed 55% share. This is a new scenario assumption,
not a fitted estimate. Because both constraints and staging changed, the new
comparison cannot isolate the effect of either change or be treated as a
like-for-like replication of the historical metrics. Historical accounting is
preserved separately in [the saved-study note](historical_results.md).
