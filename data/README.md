# Included data

The repository includes the saved study results and the compact inputs needed to
inspect the routing model. The five original data files are preserved byte for
byte. `manifest.json` records their original filenames, sizes, and SHA-256 hashes.
No download or API key is needed to use them.

| File | Contents |
| --- | --- |
| `study/replicates.json` | 55 saved solves: five penalty perturbations for each of 11 settings, with served recipient indices and summary metrics. |
| `study/recipients.csv` | 528 recipients, keyed by zero-based `idx`, with NTA, borough, need/access percentiles, historical need tier, assumed demand, cold fraction, and the gamma=1 reference weight. |
| `model/instance.json` | Two depot locations, 528 recipients, and 25 modeled vehicles; includes scenario demand, capacities, service durations, and time windows. |
| `model/donors.csv` | 18 donor locations and assumed supply, availability, variability, and cold fractions. |
| `model/travel.npz` | Two 548 × 548 arrays: `dist_km` and `time_min_freeflow`. Distances are kilometres and times are free-flow minutes. Congestion is applied by the routing model. |
| `model/nodes.json` | Explicit current node order and coordinates, plus hashes of the instance, donor, and travel files. |

All rates and percentiles are fractions on `[0, 1]`; demand and supply are in
pounds. `study/recipients.csv` deliberately omits names and addresses. The model
input retains public agency/business names, locations, and operating-hour fields.
It contains no personal contact fields.

## Where the inputs came from

The original local preprocessing pipeline identifies the following sources:

| Input | Source and interpretation |
| --- | --- |
| Recipient geography and hours | NYC HRA / [Food Help NYC](https://finder.nyc.gov/foodhelp/locations), linked by [HRA's Community Food Connection page](https://www.nyc.gov/site/hra/help/food-assistance.page). The instance builder reads the original `efap_pfred_programs.csv`; the access-index pipeline reads the Food Help provider layer. |
| Neighborhood need | Preserved local export *Neighborhood Prioritization Map 2025*, using modeled food-insecurity percentage per 2020 NTA. The [NYC Supply Gap Analysis page](https://www.nyc.gov/site/foodpolicy/programs/supply-gap.page) links the [2025 dashboard](https://public.tableau.com/app/profile/claire.reynolds6296/viz/SupplyGap2025/Dashboard1) and [Emergency Food Supply Gap dataset](https://data.cityofnewyork.us/City-Government/Emergency-Food-Supply-Gap/4kc9-zrs2/about_data). The analysis is produced by NYC Opportunity with the Mayor's Office of Food Policy. These are modeled estimates, not survey counts collected for this project. |
| Population | NYC Department of City Planning, [Decennial Census 2010/2020 Change workbook](https://www.nyc.gov/assets/planning/download/office/planning-level/nyc-population/census2020/nyc_decennialcensusdata_2010_2020_change.xlsx?r=3). The access model uses total tract population. |
| NTA boundaries | NYC Open Data, [2020 Neighborhood Tabulation Areas](https://data.cityofnewyork.us/City-Government/2020-Neighborhood-Tabulation-Areas-NTAs-/9nt8-h7nd). |
| Access | Derived by the original E2SFCA pipeline from provider opening hours and total population: Gaussian distance decay with a one-mile catchment, aggregated from tracts to NTAs. |
| Road distances and times | Cached estimates built with the [OSRM routing service](https://project-osrm.org/), based on OpenStreetMap road data. The original code called `router.project-osrm.org` and allowed a distance-based fallback when requests failed. |
| Demand, fleet, donor supply, cold fractions, and delivery windows | Labeled research scenario assumptions. They are not operational records supplied by a food-rescue organization. |

The larger raw geography/preprocessing inputs are not duplicated here. The local
source material identifies public origins but does not contain a dataset-specific
redistribution license or retrieval-date manifest. Inclusion does not grant new
rights over third-party source material; the source terms and attribution remain
applicable.

Road data © [OpenStreetMap contributors](https://www.openstreetmap.org/copyright),
available under the [Open Database License (ODbL) 1.0](https://opendatacommons.org/licenses/odbl/1-0/).
Routing was computed with OSRM. Public links identify the source publishers;
they do not replace the missing historical retrieval dates or certify that a
current download is identical to the preserved study input.

## Provenance limits

**Historical travel alignment is assumed.** The original cache contains numeric
arrays only: no node identifiers, coordinates, retrieval date, or input hash. Its
dimensions match the original builder convention: 2 depots, then 18 donors, then
528 recipients. `nodes.json` records that order for the current included files;
it cannot retrospectively certify which coordinates generated the historical
cache. The bounded routing demo uses this declared alignment.

**Fallback cells are not labeled.** The historical builder initialized distances
as `1.33 × haversine distance` and free-flow times at 46 km/h, then replaced entries
from successful OSRM responses. Failed requests or null responses could leave
these estimates in the cache. The saved file contains no per-cell source flags
or successful-request count, so it does not certify a road-network estimate for
every pair.

**One recipient used a missing-neighborhood fallback.** Recipient `idx=95`, NTA
`BK0261`, is absent from the 197-row upstream equity table. The historical builder
assigned need/access percentiles of `0.5` and need tier `low`. Those values are
preserved to reproduce the saved accounting; they are not evidence of low need.

Recipient indices, need/access percentiles, demand, borough, NTA, and mapped tiers
match the included instance for all 528 rows. The saved `w_gamma1` weights are
recomputed from the rounded percentiles as
`clip((need_pct + 0.15) / (access_pct + 0.15), 0.5, 4)`, rounded to three decimals.
They differ from the instance's older `w` field for 188 rows. Saved-result analysis
uses `w_gamma1` to match the original replicate harness.
