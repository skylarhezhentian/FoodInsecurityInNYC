# Reconstructed poster evidence

This is the reviewed snapshot of portable redraws and their numerical inputs.
The original poster bitmaps are preserved separately in
[`poster/source/figures`](../../poster/source/figures).

- `figure1_priority_surface.*` uses the archived instance's stored priority
  weights, including their original rounding.
- `figure2_equity_dial.*`, `table1.csv`, and `gamma_sweep.csv` use the final
  55-run saved results, after checking their recipient joins and summaries.
- `appendix_distribution.*` and `distributional_reanalysis.json` reconstruct
  an earlier single-run analysis; they are not the final poster's main results.
- `validation.json` records input and generated-file hashes and the scope of
  the numerical checks. `priority_points.csv` contains the map coordinates and
  weights already present in the public model data.

Run `python scripts/reproduce_poster_figures.py` from the repository root to
generate a fresh copy under `outputs/poster_figures/`. This command is offline,
does not run the routing solver, and does not overwrite this snapshot. Redraws
use portable fonts and layout; their pixels are not claimed to match the
original images.

These figures retain the historical results for traceability. They do not
establish historical route feasibility or an optimal frontier. The corrected
comparison is in [`results/corrected`](../corrected). The complete lineage and
metric definitions are in
[`research/experiments`](../../research/experiments).
