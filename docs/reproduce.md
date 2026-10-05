# Run the project

[Project overview](../README.md) · [Research walkthrough](../research/README.md) ·
[Poster and evidence](../poster/README.md)

Run commands from the repository root. This guide covers the full project:
public-data analysis, scenario construction, the original Laidlaw study, and
the corrected routing model. All documented analysis inputs are included.
Installing dependencies needs network access unless they are already available;
replaying the included data needs no API key or download.

## Set up the analysis and routing environment

Use Python 3.11, as in GitHub Actions:

```bash
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

On Windows, activate with `.venv\Scripts\activate` instead. The pinned packages
also match the local Python 3.9.6 environment used to check the model.

For a first pass through the saved research, run:

```bash
python scripts/reproduce_results.py
python scripts/reproduce_poster_figures.py
python scripts/verify_poster_archive.py
python scripts/verify_benchmark.py
```

These check the original study, redraw the poster figures, verify the preserved
research files, and replay the saved corrected routes. They do not run the
optimizer. The stages below show how to reproduce each part in more detail.

## 1. Reproduce neighborhood access and donor estimates

This stage uses geospatial dependencies pinned for Python 3.12. Keep them in a
separate environment within the same project:

```bash
deactivate
python3.12 -m venv .venv-preprocessing
source .venv-preprocessing/bin/activate
python -m pip install -r research/preprocessing/requirements.txt
python scripts/reproduce_upstream.py --output outputs/upstream
```

On Windows, use `.venv-preprocessing\Scripts\activate` for activation.
The command runs eight programs across community-district maps, neighborhood
maps, E2SFCA access calculations, and donor estimates. It compares four CSVs
and the donor results JSON with the saved references, and checks that the
51 archived input and source files stay unchanged. Read
`outputs/upstream/validation.json` and `outputs/upstream/logs/` for the results.
Use a new or empty output directory for each replay.

The [preprocessing guide](../research/preprocessing/README.md) explains each
calculation, recorded reproduction, and optional stage selection. Donor-volume
estimates are supporting research; they are not a verified generator of the
final routing donor scenario.

Switch back to the main environment for the remaining stages:

```bash
deactivate
source .venv/bin/activate
```

## 2. Reconstruct the delivery scenario

```bash
mkdir -p outputs
python research/experiments/builders/build_instance_v1.py \
  --origins research/experiments/scenarios/origins_ch.csv \
  --window-mode ch_stat --shift-start 06:00 --horizon-min 840 \
  --service-min 15 --donor-share 0.15 --vehicle-cap-lbs 2500 \
  --out outputs/poster_instance_rebuilt.json
```

The builder uses Python's standard library. Its output has been verified as
byte-identical to `data/model/instance.json`, containing 528 recipients, two
depots, and 25 vehicles. GitHub Actions repeats that comparison. The
[experiment guide](../research/experiments/README.md#rebuild-the-final-instance)
records the source joins, fallback values, and scenario assumptions. The final
18-donor table and cached travel estimates are also included in `data/model/`.

## 3. Recompute the original study tables

```bash
python scripts/reproduce_results.py
```

This reads `data/study/replicates.json` and `data/study/recipients.csv`, checks the
55 saved solves, and writes tables and `validation.json` under `outputs/study/`.
It recomputes reported accounting from the saved served-recipient sets; it does
not rerun the historical optimization or establish that those old routes satisfy
the corrected model. The historical study is retained for comparison and audit.

To select other copies of the same input schema or a separate output directory:

```bash
python scripts/reproduce_results.py --data-dir data/study --output-dir outputs/study-copy
```

## 4. Reproduce the poster figures and inspect its source

```bash
python scripts/reproduce_poster_figures.py
python scripts/verify_poster_archive.py
```

The figure command writes two poster redraws, the strategy table, gamma-sweep
data, all 528 priority-map points, an appendix decile figure, and a validation
record under `outputs/poster_figures/`. It checks the saved-study summaries and
selected earlier robustness and distributional calculations without running
an optimizer. The archive check writes `outputs/poster/archive_verification.json`.

The [poster guide](../poster/README.md) links each figure and table to its
source. The original PDF and figure assets are preserved; portable redraws are
not claimed to have identical pixels. For the original layout's LaTeX build
requirements, see [the source guide](../poster/source/README.md). A
byte-identical PDF rebuild has not been established.

## 5. Explore and validate the corrected routing model

### Small routing example

```bash
python scripts/run_routing_demo.py
```

The default demo uses the first 20 recipients and first three vehicles in stored
order, all donor candidates, and three policies with three seconds per policy. It
writes `outputs/demo/routing_demo.json`. This is a new bounded solve,
separate from the archived study. The historical travel cache has no embedded
node identifiers; the demo uses the explicit current order in
`data/model/nodes.json`, with historical cache alignment assumed.

A different bounded example can be selected explicitly:

```bash
python scripts/run_routing_demo.py --recipients 40 --vehicles 5 --time-limit 3 --output outputs/demo-40/routing_demo.json
```

### Saved results and full benchmark

To check the included corrected results without running the optimizer:

```bash
python scripts/verify_benchmark.py
python scripts/build_figures.py --output outputs/figures
```

The verifier reads `results/corrected/` by default and reconstructs route timing,
cargo, capacities, objective, and reported metrics from the packaged model inputs.
It writes `verification.json` beside the selected results.
The figure command rebuilds `policy_comparison.png` and `policy_comparison.svg`
under `outputs/figures/`.

This opt-in command runs the fixed protocol in `configs/corrected_benchmark.json`:
all 528 recipients and 25 vehicles, five policies, five penalty-perturbation seeds,
and ten seconds of search per solve.

```bash
python scripts/run_benchmark.py
```

It writes each policy/seed result, `manifest.json`, `runs.csv`, and `summary.csv`
under `outputs/benchmark/`. To retain another run separately:

```bash
python scripts/run_benchmark.py --config configs/corrected_benchmark.json --output outputs/benchmark-repeat
python scripts/verify_benchmark.py --results outputs/benchmark-repeat
```

The benchmark records the protocol, inputs, solver statuses, and route audits.
Its median and min/max summarize five small penalty perturbations; the ranges
are not confidence intervals. Time-limited heuristic search can return different
routes across machines or runs, even with the same inputs and seeds. A rerun is
therefore a new recorded experiment, not a promise of bitwise-identical routes or
historical result recovery. These are modeled allocations for one scenario day,
not estimates of real operational outcomes.

## Test the complete project

```bash
python -m unittest discover -s tests -v
```

The suite includes data hashes, recipient joins, reference weights, declared
node order, and numerical matrix integrity. Those checks verify the included
files and code; they cannot recover the missing historical cache provenance.
GitHub Actions runs the suite, saved-result reanalysis, corrected-result replay,
poster archive verification, figure generation, and bounded routing demo. A
separate Python 3.12 job reproduces the upstream tables and reconstructs the
original poster instance from the included source snapshots.
It does not run the full research benchmark.

## Where to find the outputs

| Stage | Generated output |
| --- | --- |
| Neighborhood analysis and donor estimates | `outputs/upstream/`, including `validation.json` and logs |
| Rebuilt routing instance | `outputs/poster_instance_rebuilt.json` |
| Original study accounting | `outputs/study/` |
| Poster redraws and numerical inputs | `outputs/poster_figures/` |
| Archive integrity checks | `outputs/poster/archive_verification.json` |
| Small corrected routing example | `outputs/demo/routing_demo.json` |
| Corrected comparison figure | `outputs/figures/` |
| New full benchmark, if requested | `outputs/benchmark/` |

The corrected-result verifier writes `verification.json` beside whichever
results directory it checks; by default this is `results/corrected/`. Original
study records are in `data/study/`, reviewed poster redraws in `results/poster/`,
and saved corrected routes in `results/corrected/`. These are successive stages
of one project with distinct model assumptions.

Generated `outputs/` files are ignored by Git. See [the data guide](../data/README.md)
for sources, schemas, and scenario assumptions, and the
[research walkthrough](../research/README.md) for the connection between stages.

## Optional historical rerun

This command runs the archived model, including its known feasibility limitations.
Use it only to investigate historical behavior. It launches 55 solves at the
specified time limit and is not a substitute for the corrected benchmark. Work
in a fresh generated directory so archived inputs and sources stay unchanged:

```bash
mkdir -p outputs
historical_run_dir=$(mktemp -d outputs/historical-XXXXXX)
mkdir "$historical_run_dir/data"
cp research/historical/*.py "$historical_run_dir/"
cp data/model/instance.json "$historical_run_dir/instance_ch.json"
cp data/model/donors.csv "$historical_run_dir/data/donors_pickup.csv"
cp data/model/travel.npz "$historical_run_dir/osrm_cache_pickup.npz"
cd "$historical_run_dir"
python replicates.py --time-limit 30 --reps 5
```

The complete cached matrix is supplied so no travel download is required. The
historical cache's alignment caveat still applies. These commands have not been
used to rerun the full archived experiment as part of this release.
