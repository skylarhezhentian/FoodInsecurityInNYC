# Distributional metrics (independent of the equity weight w)

Computed offline from `ch_solution.json`; no solver run. Need deciles are equal-count
bins over the recipient need percentile. Decile 10 = highest need.

## Mode A: unrestricted common supply

| metric | Unweighted | Random-preference | Need-only | Access-only | Equity |
|---|---:|---:|---:|---:|---:|
| recipients served | 237 | 229 | 209 | 200 | 184 |
| flat coverage % | 32.8 | 32.9 | 32.9 | 33.5 | 32.4 |
| need-weighted coverage % (w-dependent, cross-check) | 30.6 | 30.5 | 36.9 | 41.2 | 44.5 |
| **top need-decile coverage %** | 47.8 | 22.4 | 93.9 | 14.3 | 43.0 |
| bottom need-decile coverage % | 8.7 | 44.3 | 1.3 | 30.5 | 1.3 |
| worst need-decile coverage % (service floor) | 8.7 | 20.8 | 0.2 | 14.3 | 1.3 |
| **need alignment (Spearman, NTA)** | 0.037 | -0.210 | 0.735 | -0.244 | 0.507 |
| NTA coverage Gini (dispersion) | 0.588 | 0.510 | 0.631 | 0.619 | 0.617 |
| NTAs with zero coverage | 63 | 50 | 79 | 36 | 56 |

### Coverage by need decile (% of demand served)

| decile | mean need pct | Unweighted | Random-preference | Need-only | Access-only | Equity |
|---:|---:|---:|---:|---:|---:|---:|
| 1 | 0.08 | 8.7 | 44.3 | 1.3 | 30.5 | 1.3 |
| 2 | 0.23 | 36.9 | 53.7 | 1.5 | 44.1 | 9.2 |
| 3 | 0.35 | 28.8 | 45.2 | 0.2 | 23.8 | 8.0 |
| 4 | 0.47 | 49.0 | 41.9 | 2.6 | 61.4 | 38.7 |
| 5 | 0.60 | 50.0 | 33.5 | 10.6 | 54.3 | 40.7 |
| 6 | 0.68 | 36.6 | 22.1 | 20.1 | 25.5 | 26.4 |
| 7 | 0.74 | 40.7 | 32.9 | 54.1 | 33.3 | 42.3 |
| 8 | 0.81 | 12.4 | 20.8 | 45.4 | 32.5 | 48.3 |
| 9 | 0.90 | 20.4 | 25.7 | 75.6 | 14.9 | 43.5 |
| 10 | 0.97 | 47.8 | 22.4 | 93.9 | 14.3 | 43.0 |

## Mode B: equal delivered volume

| metric | Unweighted | Random-preference | Need-only | Access-only | Equity |
|---|---:|---:|---:|---:|---:|
| recipients served | 235 | 227 | 208 | 197 | 174 |
| flat coverage % | 32.7 | 32.9 | 32.9 | 33.0 | 32.0 |
| need-weighted coverage % (w-dependent, cross-check) | 31.3 | 30.8 | 36.8 | 40.7 | 44.3 |
| **top need-decile coverage %** | 41.7 | 22.1 | 93.9 | 14.3 | 49.5 |
| bottom need-decile coverage % | 10.1 | 44.3 | 1.3 | 31.6 | 1.3 |
| worst need-decile coverage % (service floor) | 10.1 | 20.8 | 0.2 | 14.3 | 1.3 |
| **need alignment (Spearman, NTA)** | 0.044 | -0.192 | 0.732 | -0.227 | 0.519 |
| NTA coverage Gini (dispersion) | 0.569 | 0.511 | 0.632 | 0.629 | 0.632 |
| NTAs with zero coverage | 59 | 50 | 79 | 39 | 61 |

### Coverage by need decile (% of demand served)

| decile | mean need pct | Unweighted | Random-preference | Need-only | Access-only | Equity |
|---:|---:|---:|---:|---:|---:|---:|
| 1 | 0.08 | 10.1 | 44.3 | 1.3 | 31.6 | 1.3 |
| 2 | 0.23 | 31.3 | 48.8 | 1.5 | 41.6 | 7.3 |
| 3 | 0.35 | 27.7 | 45.2 | 0.2 | 23.8 | 8.0 |
| 4 | 0.47 | 49.0 | 45.5 | 2.6 | 61.8 | 38.7 |
| 5 | 0.60 | 52.3 | 33.5 | 10.4 | 51.3 | 39.8 |
| 6 | 0.68 | 32.1 | 22.1 | 20.0 | 24.4 | 24.2 |
| 7 | 0.74 | 43.5 | 32.9 | 54.1 | 33.3 | 33.0 |
| 8 | 0.81 | 16.8 | 20.8 | 45.4 | 32.5 | 51.2 |
| 9 | 0.90 | 23.2 | 25.7 | 75.6 | 14.7 | 41.3 |
| 10 | 0.97 | 41.7 | 22.1 | 93.9 | 14.3 | 49.5 |
