# Data-availability robustness (perturbed demand, travel times, windows)

6 perturbed worlds; equity weights fixed at γ=1. Demand CV 0.3, travel global ×U(0.85,1.15) × per-edge lognormal(0.12), windows ±N(0,20m).

| metric | Unweighted | Random-preference | Need-only | Access-only | Equity |
|---|---:|---:|---:|---:|---:|
| baseline agencies served | 229 | 221 | 206 | 200 | 183 |
| agencies served (mean±sd) | 229 ± 8 | 222 ± 8 | 198 ± 5 | 191 ± 6 | 184 ± 10 |
| baseline need-weighted % | 31.2 | 32.2 | 37.9 | 41.4 | 45.7 |
| need-weighted % (mean±sd) | 30.5 ± 0.8 | 30.0 ± 0.3 | 36.5 ± 0.8 | 40.4 ± 1.4 | 44.2 ± 1.4 |
| baseline high-need % | 24.6 | 26.8 | 62.8 | 25.4 | 42.2 |
| high-need tier % (mean±sd) | 24.9 ± 1.1 | 26.0 ± 1.8 | 60.5 ± 1.9 | 23.9 ± 3.2 | 43.1 ± 2.7 |

## Rank stability (qualitative ordering preserved)
| claim | worlds |
|---|---:|
| equity leads need-weighted cov | 6/6 |
| need_only leads high-need tier cov | 6/6 |
| equity leads high-need tier cov | 0/6 |
| equity lowest agencies served | 4/6 |
