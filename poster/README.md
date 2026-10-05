# From source data to the Laidlaw poster

[Open the symposium poster](Skylar_Tian_Laidlaw_Poster.pdf).

This archive follows the work behind **Allocation Under Scarce Capacity:
Equity-Aware Routing for Urban Food Rescue in New York City**. It includes the
public-data snapshots, preprocessing, model development, saved experiments,
figure code, working paper, and recovered poster source. The supplied PDF is
preserved unchanged.

## Research sequence

| Stage | Files to start with | What it contributes |
| --- | --- | --- |
| Public-data collection | [Source snapshots](../data/upstream/) and [preprocessing guide](../research/preprocessing/README.md) | Food Help locations and schedules, neighborhood food-insecurity estimates, Census population, and geographic boundaries. |
| Need and access measures | [Food-access calculations](../research/preprocessing/foodhelp/analysis/) | Early community-district and NTA analyses, followed by the population-based E2SFCA access score and NTA equity table. |
| Donation-supply exploration | [Donor model](../research/preprocessing/donor_model/) | Public donor anchors, estimation assumptions, reconciliation, and saved outputs. This is background research; the routing donors remain a labeled scenario. |
| Routing instance | [Instance builders](../research/experiments/builders/) and [scenario inputs](../research/experiments/scenarios/) | Recipient joins, demands, delivery windows, depots, fleet, and donor assumptions. The retained final instance is in [data/model](../data/model/). |
| Model development | [Earlier experiments](../research/experiments/README.md) and [historical solver](../research/historical/) | Prototype routes, five-policy comparison, depot checks, gamma sweep, robustness, and distributional analyses. These retain their original model behavior. |
| Final poster study | [55 saved runs](../data/study/replicates.json), [recipient table](../data/study/recipients.csv), and [replicate harness](../research/historical/replicates.py) | Five perturbations for each of 11 settings. These are the records behind the poster's strategy table and equity-dial figure. |
| Writing and presentation | [Working paper](../research/writing/README.md), [poster source](source/README.md), and [reference guide](references.md) | The earlier manuscript, LaTeX layout, original figure assets, bibliography, logos, and template attribution. |

The upstream archive includes both original snapshots and their saved derived
tables. Acquisition dates and exact historical code revisions were not recorded
for every file. The generic scraper is retained as a template, not claimed as
the proven source of the saved directory exports. Individual manifests identify
unchanged copies, portable-path changes, and removal of unused contact or editor
fields from public provider exports.

## Trace the poster's figures and table

| Poster item | Evidence and construction |
| --- | --- |
| Figure 1: need/access weights and map | [Original figure builder](../research/experiments/poster_figures/fig_equity_layer_poster.py), the retained [instance](../data/model/instance.json), and borough boundaries. It uses the instance's stored weights, which differ slightly from the later replicate reference weights for some recipients. |
| Table 1: five-strategy comparison | The five-replicate summaries in [replicates.json](../data/study/replicates.json). [Saved-study reanalysis](../scripts/reproduce_results.py) checks counts and coverage against the recipient-level served sets. |
| Figure 2: equity dial | [Original dial builder](../research/experiments/poster_figures/fig_dial_poster.py) and the same saved replicate file. Gamma zero is the unweighted point; the eight gamma settings reuse their existing records. |
| Context statistics and prior work | [Reference guide](references.md), with primary-source links and bibliographic corrections recorded separately from the unchanged poster. |

Both original figure images and the Columbia logo match the pixels embedded in
the supplied PDF. The layout source was recovered from the original poster ZIP;
its manifest records the archive and entry hashes. A byte-identical rebuild of
the PDF has not been established.

## Reproduce the evidence

After installing the root requirements, run:

```bash
python scripts/reproduce_results.py
python scripts/reproduce_poster_figures.py
python scripts/verify_poster_archive.py
```

These commands use included files and do not rerun the routing optimizer. They
recompute the saved-study tables, rebuild the poster's analytical figures, and
check the archive inventory. Generated output stays under `outputs/`.

For the earlier data preparation, use the separate environment and commands in
[the preprocessing guide](../research/preprocessing/README.md). The
[experiment guide](../research/experiments/README.md) documents instance
reconstruction and the role of each earlier experiment. The poster's original
LaTeX build dependencies are listed in [the source guide](source/README.md).

## How to read the historical conclusions

The poster describes the earlier implementation. Later review found omitted
service time and an inventory constraint that could allow cold cargo to exceed
total cargo. The original 55-run file records served sets but not full routes,
so reproducing its metrics does not establish route feasibility. The
[current benchmark](../docs/results.md) uses corrected constraints and different
initial cold staging; its results cannot be substituted into the old poster as
if they came from the same scenario.

Three wording limits also matter when reading the unchanged PDF:

- The claim that need-only dominates the equity curve in both breadth and
  high-need coverage applies to the tested **positive gamma** settings, not the
  unweighted gamma-zero endpoint.
- The historical `travel_min` reporter sums route elapsed time, including
  waiting. Overlapping five-run ranges do not establish that driving is
  unaffected or demonstrate statistical equivalence.
- Using total population in the access calculation avoids mechanically using
  food-insecure population in both scores. It does not prove statistical
  independence between neighborhood need and access.

These qualifications are kept alongside the poster so the research history is
inspectable. The original PDF, source, and saved experiment records are not
silently rewritten.
