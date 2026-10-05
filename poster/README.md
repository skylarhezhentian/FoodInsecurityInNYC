# Laidlaw poster and supporting evidence

[Project overview](../README.md) · [Research walkthrough](../research/README.md) ·
[Run the project](../docs/reproduce.md) ·
[Open the symposium poster](Skylar_Tian_Laidlaw_Poster.pdf)

**Allocation Under Scarce Capacity: Equity-Aware Routing for Urban Food Rescue
in New York City** presents the original study within the
NYC Food Insecurity and Food Rescue project. This guide connects the poster to
its figures, tables, and source files. The supplied PDF is preserved unchanged.

Follow the [research walkthrough](../research/README.md) for the complete
sequence from public-data preparation through model development, the poster,
and the corrected routing benchmark. The [working-paper draft](../research/writing/README.md)
and [recovered layout source](source/README.md) retain the earlier writing and
presentation materials.

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
