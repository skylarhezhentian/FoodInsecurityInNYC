# Run the project

Run these commands from the repository root. The included data are sufficient;
the analysis and routing demo do not download data or contact an API.

## Install

Python 3.11 is used by the GitHub Actions workflow. The pinned packages also match
the local Python 3.9.6 environment used to check the model.

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

On Windows, activate with `.venv\Scripts\activate` instead.

## Recompute the historical tables

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

## Run a small routing example

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

## Run the corrected benchmark

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

## Test

```bash
python -m unittest discover -s tests -v
```

The suite includes data hashes, recipient joins, reference weights, declared
node order, and numerical matrix integrity. Those checks verify the included
files and code; they cannot recover the missing historical cache provenance.
GitHub Actions runs the suite, saved-result reanalysis, corrected-result replay,
figure generation, and bounded routing demo.
It does not run the full research benchmark.

## Files and outputs

See [the data guide](../data/README.md) for schemas, sources, and scenario
assumptions. Inputs are checked into `data/`; generated outputs are ignored by
Git. The scripts keep source inputs separate from their output directories.

[The historical source snapshot](../research/historical/README.md) is retained
for source review. It has its own original behavior and known limitations; it is
not the default runnable model. Its 55-solve harness uses time-limited search, so
even a deliberate rerun need not recover the saved historical routes.

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
