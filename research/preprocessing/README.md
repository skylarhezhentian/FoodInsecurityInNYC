# Preprocessing research archive

These recovered programs and public-data snapshots document the work before the routing experiments. They include the earlier community-district and NTA access maps, the later E2SFCA access and equity index, and a separate donor-volume modeling study. Original scripts and saved outputs are retained; the wrapper runs copies in a fresh output directory.

## Replay offline

Use a separate environment from the routing project. The pinned environment was tested with Python 3.12.13; it has newer numerical and geospatial dependencies than the routing environment.

```sh
python3.12 -m venv .venv-preprocessing
source .venv-preprocessing/bin/activate
python -m pip install -r research/preprocessing/requirements.txt
python scripts/reproduce_upstream.py --output outputs/upstream
```

Installing dependencies requires network access unless they are already available. The replay itself uses only included files; it does not acquire data or call a routing service. It runs eight programs, generates maps and tables, compares the numerical tables against the saved outputs, and verifies that all archived inputs and programs remain unchanged. Read `outputs/upstream/validation.json` and `outputs/upstream/logs/` for the comparison and runtime details. A mismatch exits with status 2 and is reported rather than hidden.

Each run needs a new or empty directory inside `outputs/`. To repeat the full run, choose another name. To replay one stage:

```sh
python scripts/reproduce_upstream.py --stage e2sfca --output outputs/upstream-e2sfca
```

Other stages are `community`, `nta`, and `donors`. The complete optional environment supports every stage. Rendered pixels may differ across font and library versions; the comparison checks table keys, column names, text, and numeric values with relative tolerance `1e-8` and absolute tolerance `1e-10`.

The archived-input replay was run on October 4, 2026 with the pinned environment. All eight programs completed, and all 51 archived files remained unchanged. All four regenerated CSVs were byte-identical to their saved references: 59 community-district rows, 197 earlier NTA rows, 197 E2SFCA rows, and 68 donor-estimate rows. Across 4,150 numeric CSV cells the maximum difference was zero; the donor results JSON also had no differing fields. The [recorded validation](reproduction.json) contains the runtime, file hashes, and comparisons. This verifies the recovered calculations against the included snapshots, not the unrecorded acquisition process.

## What feeds what

| Stage | Recovered calculation | Saved output |
| --- | --- | --- |
| Community districts | FoodHelp opening hours, provider locations, SNAP totals, and district population | `cd_summary.csv` and map |
| Earlier NTA map | Provider hours per food-insecure population, NTA need and population | `nta_summary.csv` and maps |
| E2SFCA | Gaussian distance decay from tract representative points to provider locations; total population is the demand denominator | `nta_equity_index.csv` and maps |
| Routing instance | EFAP provider records joined to NTA geography and the saved E2SFCA equity table | [Recovered instance builders](../experiments/README.md) |
| Donor-volume exploration | Published donor anchors, manually encoded roster, category assumptions, and total-volume reconciliation | `per_donor_estimates.csv`, `results.json`, and figures |

The access-map snapshot contains 528 provider records; 526 have positive parsed weekly opening hours and enter E2SFCA. The tract geometry has 2,325 representative points. The final equity table covers 197 residential NTAs. The larger EFAP snapshot has 842 rows; the instance builder selects 528 recipients. These are different input selections, even though two counts happen to be 528.

E2SFCA uses great-circle distance with a 1,609-metre cutoff, not street-network walking times. The original comments call demand points “centroids”; the implementation uses `geometry.representative_point()`. The index is `sqrt(need_pct * (1 - access_pct))`. Percentile and tier calculations are preserved, including the tier assignment that breaks ties by row order. This geographic index is distinct from the later routing reward formula.

The donor-volume model is a separate research exploration. Its annual pounds, category priors, proxy borough assignments, and sensitivity calculations do **not** establish observed pickup-day supplies. No recovered program proves that its modeled output generated the final 18-donor routing scenario. The final donor quantities and locations remain scenario inputs documented with the routing experiments.

## Provenance and limits

[The manifest](manifest.json) records original and packaged hashes, original project-relative filenames, sizes, and transformations. Every archived Python program is preserved byte-for-byte. The four provider snapshots remove six unused fields: organization phone, editor/creator usernames, and three free-text note fields. Geometry, row order, identifiers, opening hours, and all other retained values are unchanged. The Census workbook removes only its creator and editor metadata; all 14 other ZIP members, including every worksheet, are byte-identical to the source. The sanitized files rebuild the saved routing instance byte-for-byte. See [upstream data sources](../../data/upstream/README.md) for attribution and source gaps.

The generic `acquisition/nyc_foodhelp_scraper.py` is retained as acquisition research. Its API settings are blank, its output names differ from the saved exports, and it is **not a proven generator of those exports**. It is excluded from the offline replay. Do not treat the archive as a verified record of original download dates or exact historical source-code revisions.

Historical methodology documents are preserved as research notes. Their model-based donor estimates are not measurements, and matching saved tables does not independently validate assumptions, source coverage, or scientific conclusions. The archived map scripts contain no routing solve; the routing experiment lineage is documented separately.
