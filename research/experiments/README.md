# How the experiments led to the poster

The poster uses the final 55-run comparison, not every earlier result in this
folder. This archive keeps the earlier model stages and the analyses that led
to that comparison. The original poster figures are preserved in
[`poster/source/figures`](../../poster/source/figures); portable redraws and their
numerical inputs are in [`results/poster`](../../results/poster).

All these experiments precede the corrected routing model. The later full-study
solver omitted unloading time and could allow refrigerated cargo to exceed total
cargo. Its saved 55-run allocation statistics remain reproducible, but those
routes are not established as physically feasible. Earlier prototypes have not
been validated against the corrected model. Use
[`results/corrected`](../../results/corrected) for the corrected comparison.

## Stages and evidence

| Folder | What it contributes | What can be checked offline |
|---|---|---|
| `builders/` | The original demand, neighborhood join, fleet, cold/ambient split, and delivery-window builders | The final poster instance rebuilds byte for byte from included upstream snapshots. |
| `scenarios/` | Five-origin prototype, eleven-site expansion, final two-depot fleet, and food-class assumptions | Explicit source parameters; these are modeled scenarios, not measured daily donations or fleet records. |
| `prototypes/` | Early five-origin and eleven-site models, saved solutions, the three-policy comparison, and their source/report files | Original artifacts are retained. These are different scenarios; their numbers should not be merged with the poster's final table. |
| `single_run/` | Five-policy allocations, vehicle accounting, equal-throughput mode, depot sensitivity, and aggregate donation/age proxies | Selected recipients and demand can be reanalyzed. The saved inventory totals expose historical feasibility limitations. |
| `gamma_sweep/` | The earlier single-run gamma sweep and its plotting source | Its saved curve can be replotted, but it is not the replicated curve in the final poster and is not a proven Pareto frontier. |
| `robustness/` | Six perturbed worlds, each comparing five policies | All 80 aggregate statistics and four rank counts reproduce from the saved world summaries. Routes and realized perturbation arrays were not retained here. |
| `distribution/` | Need-decile coverage, NTA coverage dispersion, and need alignment for two earlier single-run modes | Every saved metric reproduces from `single_run/ch_solution.json`; no solver is needed. |
| `poster_figures/` | Original sources for the priority map, final equity-dial figure, and poster-number extraction | The portable command below reads their original inputs directly and avoids solver imports and machine-specific fonts. |

The six shared historical solver modules remain in
[`../historical`](../historical). The final instance, donor table, travel matrix,
and replicate results are referenced from `data/model/` and `data/study/` rather
than duplicated here. Earlier generated travel caches, virtual environments,
backup scripts, prompt files, and private handoff notes are excluded.

## Reproduce the poster evidence

From the repository root:

```bash
python scripts/reproduce_poster_figures.py
```

This creates the two poster redraws in SVG and PNG, the original table values,
the replicated gamma curve, all 528 map points, an appendix decile figure, and a
validation record in `outputs/poster_figures/`. The reviewed redraws in
`results/poster/` are a fixed snapshot; this command does not change them.
It checks all 55 runs against the
recipient table, all 385 saved summary values, the earlier distributional
results, and the six-world summary arithmetic. It does not solve routes or use
the network. The preserved original images remain untouched; portable fonts and
layout mean the redraws are not claimed to have identical pixels.

Figure 1 uses the original instance's stored `w`. Figure 2 and Table 1 use the
saved rounded replicate summaries, after checking them against the selected
recipients. This distinction matters: for the first recipient the map's weight
is 1.422, while the replicate reference weight is 1.423 because its calculation
starts from rounded percentile inputs. Neither is silently substituted for the
other.

The original `travel_min` field is reported fleet time including waiting and
excluding unloading, according to the historical implementation. Reproducing
its median verifies the saved arithmetic, not driving-only time or route
feasibility. The poster's broad whole-curve dominance and unloading-invariance
claims are not adopted by this reconstruction.

The appendix deciles preserve the historical convention: recipients are sorted
by need with their original order breaking ties, then split into ten groups.
Equal neighborhood need scores can therefore span adjacent deciles. The six
robustness worlds use population standard deviation (`ddof=0`) as in their
original report. These analyses are kept separate from the five perturbations
per setting used for the final poster.

## Rebuild the final instance

The instance builders use Python's standard library; they do not require the
separate geospatial environment used to reproduce the upstream analyses.

```bash
mkdir -p outputs
python research/experiments/builders/build_instance_v1.py \
  --origins research/experiments/scenarios/origins_ch.csv \
  --window-mode ch_stat --shift-start 06:00 --horizon-min 840 \
  --service-min 15 --donor-share 0.15 --vehicle-cap-lbs 2500 \
  --out outputs/poster_instance_rebuilt.json
```

This command was run using the included provider, neighborhood equity, and
boundary snapshots. Its output was **byte-identical** to
`data/model/instance.json`: 528 recipients, 103,990 lb total modeled demand,
45,385 lb cold demand, 25 vehicles, and two depots. The command, input hashes,
Python version, and matching output hash are recorded in
[`instance_reconstruction.json`](instance_reconstruction.json).

The builder applies the documented `need_pct=access_pct=0.5`, `need_t=0` fallback
when an assigned NTA has no equity-table row. This explains recipient index 95
(BK0261), which is absent from the included 197-row equity table. Its supplied
low-tier label is preserved in the historical analysis.

`ch_stat` windows and donor quantities are scenario assumptions. Rebuilding the
instance verifies its construction, not the realism of those assumptions. The
current builder did not reproduce an earlier stage unless explicitly stated;
older saved instances remain their own source of truth.

## Provenance and limits

[`manifest.json`](manifest.json) records the original and packaged hash of each
of the 42 archived files. Thirty-nine are byte-identical. The two instance
builders and the original map plotter have only default file paths adapted for
the packaged layout. Their algorithms are retained. The original plotter also
retains its historical font/import setup; use the portable command above for
routine reproduction.

The original source folder was a working directory without a recorded revision
for every solve. Source recovery is not proof that the latest saved script
produced every older solution. The final instance's exact reconstruction and
the final replicate file's exact match are stronger, separately verified links.
Earlier route optimality, exact-gap claims in prose, stochastic donation
outcomes, and historical route feasibility are not certified by this archive.
No new historical optimization runs were performed during packaging.
