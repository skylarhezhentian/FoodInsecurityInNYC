# Backend audit — OSRM road-network travel matrix

| metric | value |
|---|---|
| nodes | 539  (11 origin sites + 528 pantries) |
| OD pairs (off-diagonal) | 289,982 |
| tile requests (≤100 coords each, B=50) | 121 |
| OSRM tiles OK | 121/121 (100%) at build |
| **OD pairs using road fallback** | **0** (0.000%) |
| co-located OD pairs (same building, dist≈0) | 36 (not fallback) |
| realized detour (OSRM road km ÷ straight-line) | 1.35× |
| mean OD travel time (congestion 0.42) | 56.4 min |
| median OD travel time | 56.4 min |
| mean OD road distance | 18.9 km |

## OSRM (Level 2) vs Level-1 (haversine×1.33×congestion)

| metric | Level-1 road | **OSRM (headline)** |
|---|---:|---:|
| need-weighted coverage (uni→eq) | 59.8→72.8% | 56.6→72.9% |
| equity total travel (min) | 7,682 | 8,356 |

**Headline backend = `osrm`** — ✅ confirmed OSRM, zero road fallback.

The canonical solution (`routes_v1.json`), route map, equity chart and summary statistics are all generated from this OSRM matrix.
