"""Print every number the poster needs from replicates.json, and test the claims
that could flip: does need-only still dominate the gamma curve, and does the travel
ordering survive replicate noise?"""
import json
from pathlib import Path

d = json.loads((Path(__file__).parent / "replicates.json").read_text())["settings"]
S = lambda lab: d[lab]["summary"]
COLS = [("Unwt.", "gamma=0"), ("Random", "Random-preference"), ("Need", "Need-only"),
        ("Access", "Access-only"), ("Need-acc.", "gamma=1")]

print("=== medians [min-max] ===")
for m in ["served", "high_need_pct", "nw_pct", "travel_min", "delivered_lbs"]:
    print(f"{m:14s}", "  ".join(
        f"{c}={S(l)[m]['median']:g}[{S(l)[m]['min']:g}-{S(l)[m]['max']:g}]" for c, l in COLS))

print("\n=== gamma sweep medians ===")
gam = sorted((v["gamma"], v["summary"]) for v in d.values() if v["gamma"] is not None)
for g, s in gam:
    print(f"  gamma={g:<5g} served={s['served']['median']:<6g}[{s['served']['min']:g}-{s['served']['max']:g}]"
          f"  high={s['high_need_pct']['median']:<5g}[{s['high_need_pct']['min']:g}-{s['high_need_pct']['max']:g}]"
          f"  nw={s['nw_pct']['median']:g}")

print("\n=== CLAIM 1: need-only dominates every gamma>0 point (medians)? ===")
n = S("Need-only")
nx, ny = n["served"]["median"], n["high_need_pct"]["median"]
for g, s in gam:
    if g == 0: continue
    x, y = s["served"]["median"], s["high_need_pct"]["median"]
    print(f"  gamma={g:<5g} ({x:g},{y:g})  need-only ({nx:g},{ny:g})  "
          f"dominated={'YES' if nx >= x and ny >= y else 'no'}")
# stronger: does need-only's WORST replicate beat each gamma point's BEST?
print("  worst-case: need-only min high =", n["high_need_pct"]["min"],
      " vs best gamma>0 high =", max(s["high_need_pct"]["max"] for g, s in gam if g > 0))

print("\n=== CLAIM 2: travel ordering vs noise ===")
for c, l in COLS:
    t = S(l)["travel_min"]
    print(f"  {c:10s} median={t['median']:>7g}  range={t['min']:g}-{t['max']:g}  "
          f"spread={100*(t['max']-t['min'])/t['median']:.1f}%")
u, na = S("gamma=0")["travel_min"], S("gamma=1")["travel_min"]
print(f"  need-acc vs unwt median diff: {100*(na['median']/u['median']-1):+.1f}%")
print(f"  ranges overlap: {not (na['min'] > u['max'] or u['min'] > na['max'])}")
print(f"  max within-setting spread: "
      f"{max(100*(S(l)['travel_min']['max']-S(l)['travel_min']['min'])/S(l)['travel_min']['median'] for _,l in COLS):.1f}%")

print("\n=== CLAIM 3: access-only on the two metrics ===")
a = S("Access-only")
print(f"  access nw={a['nw_pct']['median']}  high={a['high_need_pct']['median']}"
      f"  vs no-signal high: unwt={S('gamma=0')['high_need_pct']['median']}"
      f" random={S('Random-preference')['high_need_pct']['median']}")
