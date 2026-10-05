# Feasibility validation — canonical OSRM solution

Backend: **osrm**  ·  horizon: 480 min  ·  instance: 5 donors / 11 sites / 528 pantries / 20 vehicles

| check | uniform | equity | status |
|---|---:|---:|:--:|
| served stops | 311 | 306 | — |
| time-window violations | 0 | 0 | ✅ PASS |
| capacity violations (total+cold) | 0 | 0 | ✅ PASS |
| cold-chain incompatibility | 0 | 0 | ✅ PASS |
| route exceeds shift horizon | 0 | 0 | ✅ PASS |
| OSRM road-fallback arcs used in routes | — | 0 | ✅ PASS |

**Overall: ✅ ALL FEASIBILITY CHECKS PASS**

_Arrival time is the Time-dimension cumulative value (travel + upstream service); per-stop service is listed separately in routes_v1.json. The window constraint is enforced on this quantity, so feasibility holds by construction and is re-verified here independently._
