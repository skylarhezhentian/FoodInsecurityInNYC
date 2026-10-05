# Corrected benchmark results

All 25 solves returned solutions that passed both the routing model's audit and
a separate replay that does not import the solver. Replay checks all 625 vehicle
routes, including unused vehicles. It verifies cargo conservation, cold cargo as
a subset of total cargo, capacities, completion windows, driving/service/waiting
time, depot returns, unique visits, coverage metrics, and objective components.
It also checks the recorded inputs and all result-file hashes.

The five-policy comparison was specified before execution in
[the protocol](benchmark_protocol.md). It uses one modeled day, five small skip-
penalty perturbations per policy, and a ten-second search limit per solve. There
were no failed solves or omitted runs in this batch.

| Policy | Sites served, median [range] | High-need coverage, median [range] | Reference-weighted coverage, median | Elapsed fleet minutes, median |
| --- | ---: | ---: | ---: | ---: |
| Unweighted | 95 [86–110] | 7.0% [6.3–7.4] | 11.5% | 7,639 |
| Random preference | 109 [103–138] | 10.8% [10.6–17.0] | 12.7% | 9,519 |
| Need only | 92 [79–105] | 28.8% [28.4–33.6] | 16.6% | 8,835 |
| Access only | 171 [109–177] | 22.5% [16.0–23.9] | 37.5% | 14,621 |
| Need / access | 160 [117–172] | 39.3% [31.5–41.0] | 40.7% | 14,983 |

Need/access has the highest median high-need coverage in this batch. Access-only
has the highest median site count. These priorities also use more fleet time;
the comparison does not hold realized travel or elapsed time constant. The
need-only and need/access high-need ranges overlap, and several policies have
wide site-count ranges. These results support a sensitivity exercise on this
scenario, not a claim that one policy is uniformly best or that the heuristic
found an efficient frontier.

The reference-weighted metric favors the same ratio used by the need/access
policy. It is included for transparency, but the separate high-need metric is
more useful for evaluating coverage of the supplied high-need group.

The high-need ranking differs from the archived results. Service, inventory
constraints, and initial cold staging changed together, so the change in ranking
cannot be attributed to one isolated correction. The historical results also
lack route-feasibility evidence.

## Inspect or reproduce

- [Per-run metrics](../results/corrected/runs.csv) retain all 25 runs.
- [Full summaries](../results/corrected/summary.csv) include driving, service,
  waiting, elapsed time, and scenario pounds delivered.
- [Manifest](../results/corrected/manifest.json) records the protocol, runtime,
  code/input hashes, and output hashes.
- [Verification](../results/corrected/verification.json) records the independent
  replay checks. `python scripts/verify_benchmark.py` regenerates this evidence.
- [Route records](../results/corrected) include every stop and its before/after
  load and service times. `python scripts/run_benchmark.py` runs a new batch.

Exact new routes may vary with wall-clock search, hardware, and library version.
The saved records can be replayed exactly without re-solving. Passing replay
establishes consistency with the specified model, not optimality, historical
travel-cache provenance, or real-world feasibility.
