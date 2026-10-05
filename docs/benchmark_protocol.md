# Corrected routing comparison

This configuration was fixed before running the corrected solver. It is an exploratory check on one modeled day, following an audit of the earlier implementation. It is not a preregistered study or an independent field evaluation.

The five policies are unweighted, random preference, need only, access only, and need/access. Each receives five solves on the same 528 recipients, 18 donor candidates, two depots, and 25 vehicles. Each solve has a 10-second search limit. The base random-preference seed is 42; replicate seeds 1–5 perturb skip penalties by at most ±0.2%. All configurations and failed solves are retained. No policy, parameter, or subset will be selected for favorable results.

The corrected solver includes donor and recipient service durations, requires service to finish before closing, and constrains cold cargo to remain between zero and total cargo at every visit. Integer expected pickups are used consistently in both optimization and reported accounting. Each returned route is independently checked for timing, capacities, inventory conservation, and recipient uniqueness.

Vehicles leave with total cargo equal to 40% of their capacity. Refrigerated vehicles carry a fixed 55% cold share, limited by their cold capacity; dry vehicles carry no cold cargo. This is a new scenario assumption, shared across all policies. The earlier implementation could stage refrigerated trucks entirely with cold cargo, while permitting mixed deliveries that implied negative ambient inventory. Its archived results are therefore not interchangeable with this corrected comparison.

The primary outcomes are sites served and the demand-weighted coverage of recipients carrying the supplied high-need label. This label is based on neighborhood need and includes 240 recipients; it is not an equal-sized third of recipient rows. The secondary reference-weighted metric uses the same gamma-one ratio as the need/access policy and is therefore not a neutral evaluation measure. One recipient has a documented missing-neighborhood fallback; supplied labels are preserved.

Summaries report the median and observed range across five perturbations. These ranges describe this search exercise, not sampling uncertainty or confidence intervals. Driving, service, waiting, and total route duration are reported separately. A failed solve or failed route check must remain visible; it cannot silently become an all-zero result or disappear from the denominator.

The cached travel matrix has the declared order of two depots, 18 donors, then 528 recipients. Its original file lacks embedded coordinates or node identifiers. The package records the current ordering and hashes, but cannot independently certify the historical cache-to-coordinate binding. Demand, supply, fleet, and cold-share inputs are scenario assumptions. These experiments do not establish real-world service gains, production readiness, or globally optimal routes.
