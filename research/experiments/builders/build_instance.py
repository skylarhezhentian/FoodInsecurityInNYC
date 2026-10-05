"""
build_instance.py -- Assemble a multi-depot VRP instance for the NYC food-rescue
routing problem.

Inputs (defaults under ./data and ../../Downloads/...):
  - data/origins.csv                       5 wholesale/supermarket origins
  - efap_pfred_programs.csv (Food Help NYC) 528 open pantries, lat/lon, hours
  - nta_equity_index.csv                   per-NTA need/access => equity weight

Output:
  - instance.json   {origins, pantries, equity_weights, fleet, params}
"""
from __future__ import annotations
import argparse, csv, json, math, sys
from collections import Counter
from datetime import datetime
from pathlib import Path

_DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


def _parse_clock(s):
    """Parse '09:00 AM' / '9AM' / '1:30 PM' -> datetime, or None."""
    s = (s or "").strip()
    if not s:
        return None
    for fmt in ("%I:%M %p", "%I %p", "%I:%M%p", "%I%p"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            pass
    return None


def weekly_hours_and_sessions(row, prefix):
    """From the per-day open/close columns (fp_* or sk_*), return
    (total_weekly_hours, n_sessions) where a session is a distinct open day.
    Slots > 14h are treated as bad data and skipped."""
    total = 0.0
    sessions = 0
    for d in _DAYS:
        day_h = 0.0
        for slot in ("1", "2", "3"):
            o = _parse_clock(row.get(f"{prefix}_{d}_open{slot}", ""))
            c = _parse_clock(row.get(f"{prefix}_{d}_close{slot}", ""))
            if o and c:
                h = (c - o).total_seconds() / 3600.0
                if 0 < h <= 14:
                    day_h += h
        if day_h > 0:
            sessions += 1
            total += day_h
    return total, sessions

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parents[2]
DEFAULT_PANTRIES = PROJECT / "data/upstream/foodhelp/efap_pfred_programs.csv"
DEFAULT_EQUITY = PROJECT / "data/upstream/foodhelp/analysis/output/nta_equity_index.csv"
DEFAULT_NTA_GEO = PROJECT / "data/upstream/foodhelp/analysis/data/nta_2020.geojson"
DEFAULT_ORIGINS = HERE.parent / "scenarios" / "origins.csv"


def haversine_min(lon1, lat1, lon2, lat2, speed_kmh=25.0):
    """Haversine distance (km) -> travel time (minutes) at speed_kmh."""
    R = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp/2)**2 + math.cos(p1)*math.cos(p2)*math.sin(dl/2)**2
    km = 2 * R * math.asin(math.sqrt(a))
    return km, km / speed_kmh * 60.0


def load_origins(path: Path):
    rows = []
    with open(path) as f:
        for r in csv.DictReader(f):
            rows.append({
                "name": r["name"],
                "category": r["category"],
                "address": r["address"],
                "lat": float(r["lat"]),
                "lon": float(r["lon"]),
                "est_lbs_yr": float(r["est_lbs_yr"]),
                "n_vehicles": int(r["n_vehicles"]),
            })
    return rows


def load_open_pantries(path: Path):
    rows = []
    with open(path) as f:
        for r in csv.DictReader(f):
            if r.get("status") != "Open":
                continue
            try:
                lat = float(r["lat"]); lon = float(r["lon"])
            except (TypeError, ValueError):
                continue
            fp_h, fp_s = weekly_hours_and_sessions(r, "fp")
            sk_h, sk_s = weekly_hours_and_sessions(r, "sk")
            rows.append({
                "fid": r["FID"],
                "name": r["program"],
                "address": r["distadd"],
                "boro": r["distboro"],
                "zip": r["distzip"],
                "type": r["program_type"],  # FP / SK / FP,SK
                "lat": lat, "lon": lon,
                "hours": r.get("fp_days_orig","").strip() or r.get("sk_days_orig","").strip(),
                "fp_weekly_hours": round(fp_h, 2), "fp_sessions": fp_s,
                "sk_weekly_hours": round(sk_h, 2), "sk_sessions": sk_s,
            })
    return rows


def load_nta_equity(path: Path):
    """Return dict nta_id -> {fi_rate, access_e2sfca, pop_2020, equity_index, need_t, access_t}."""
    out = {}
    with open(path) as f:
        for r in csv.DictReader(f):
            try:
                out[r["nta2020"]] = {
                    "boroname": r["boroname"],
                    "ntaname": r["ntaname"],
                    "fi_rate": float(r["fi_rate"]) if r["fi_rate"] else None,
                    "pop_2020": int(float(r["pop_2020"])) if r["pop_2020"] else 0,
                    "equity_index": float(r["equity_index"]) if r["equity_index"] else 0.0,
                    "need_t": int(r["need_t"]) if r["need_t"] else 0,
                    "access_t": int(r["access_t"]) if r["access_t"] else 0,
                }
            except (KeyError, ValueError):
                continue
    return out


def load_nta_geo(path: Path):
    """Return list of (nta_id, polygon) where polygon is list of (lon,lat) rings.
    Each entry is (nta_id, list of rings); each ring is list of (lon,lat) pairs."""
    if not path.exists():
        return []
    with open(path) as f:
        gj = json.load(f)
    out = []
    for feat in gj.get("features", []):
        props = feat.get("properties", {})
        nta = props.get("NTA2020") or props.get("nta2020") or props.get("ntacode")
        if not nta:
            continue
        if props.get("NTAType") not in (0, "0", None):  # residential only
            if props.get("NTAType") not in (None, "", 0):
                continue
        geom = feat.get("geometry", {})
        gtype = geom.get("type")
        coords = geom.get("coordinates", [])
        polys = []
        if gtype == "Polygon":
            polys = [coords]
        elif gtype == "MultiPolygon":
            polys = coords
        else:
            continue
        # Each polygon: outer ring + holes; we use just the outer ring for point-in-poly.
        outer_rings = [p[0] for p in polys if p]
        out.append((nta, outer_rings))
    return out


def point_in_polygon(lon, lat, rings):
    """Ray-cast: return True if (lon,lat) inside any of the rings."""
    for ring in rings:
        inside = False
        n = len(ring)
        j = n - 1
        for i in range(n):
            xi, yi = ring[i][0], ring[i][1]
            xj, yj = ring[j][0], ring[j][1]
            if ((yi > lat) != (yj > lat)) and (lon < (xj - xi) * (lat - yi) / (yj - yi + 1e-12) + xi):
                inside = not inside
            j = i
        if inside:
            return True
    return False


def assign_nta(pantries, nta_geo):
    """Assign each pantry to an NTA by point-in-polygon. Mutates pantries with 'nta'."""
    if not nta_geo:
        for p in pantries:
            p["nta"] = None
        return 0
    hit = 0
    for p in pantries:
        p["nta"] = None
        for nta_id, rings in nta_geo:
            if point_in_polygon(p["lon"], p["lat"], rings):
                p["nta"] = nta_id
                hit += 1
                break
    return hit


def derive_equity_weight(p, nta_lookup):
    """w_r = (need_t+1)/(access_t+1), clamped to [0.5, 4.0]. Falls back to 1.0 if no NTA."""
    nta = p.get("nta")
    if not nta or nta not in nta_lookup:
        return 1.0
    info = nta_lookup[nta]
    w = (info["need_t"] + 1) / (info["access_t"] + 1)
    return max(0.5, min(4.0, w))


def _sk_bump(p, base):
    """Soup kitchens have higher throughput than food pantries — scale by 1.5x."""
    t = (p.get("type") or "").upper()
    return base * (1.5 if "SK" in t else 1.0)


# --- Real-world calibration anchors (sources in README / demand notes) --------
# Feeding America / USDA "What We Eat in America": 1 meal == 1.2 lbs of food.
LBS_PER_MEAL = 1.2
# End Hunger in America pantry rule: per visit a household gets
# 4 lbs * household_size * days_of_food.
LBS_PER_PERSON_DAY = 4.0          # the "4 lbs" coefficient
NYC_HH_SIZE = 2.5                 # 2020 Census, NYC avg persons/household
DAYS_FOOD_PER_VISIT = 3           # TEFAP-style 3-day grocery supply
# => lbs per FP household-visit ~= 4 * 2.5 * 3 = 30 lbs
LBS_PER_HOUSEHOLD = LBS_PER_PERSON_DAY * NYC_HH_SIZE * DAYS_FOOD_PER_VISIT
# Throughput rates (clients processed per open hour):
FP_CLIENTS_PER_HR = 15.0          # households/hr (City Harvest partner: 20-30 new families/shift + returning)
SK_MEALS_PER_HR = 60.0            # on-site meals served/hr during a service window


def estimate_demand_lbs(p, *, mode, base_lbs, scale, per_capita,
                        nta_lookup, nta_pantry_count, rng=None,
                        donor_share=1.0, noise_cv=0.35):
    """Per-stop demand in lbs (one distribution-cycle's worth of food).

    Modes:
      flat       -> base_lbs (FP) or 1.5*base_lbs (SK).  Original v0 placeholder.
      equity     -> base_lbs * (1 + scale * equity_index).  Narrow NTA-level tilt.
      fi_pop     -> (NTA food-insecure pop / # pantries in NTA) * per_capita.
      realistic  -> capacity-driven, grounded in real anchors + pantry-specific
                    operating hours.  THE high-variation mode:

         FP:  hours_per_session * FP_CLIENTS_PER_HR * LBS_PER_HOUSEHOLD
         SK:  hours_per_session * SK_MEALS_PER_HR   * LBS_PER_MEAL

         then * need_mult (1 + 0.5*equity_index)         # mild need tilt
              * lognormal(0, noise_cv)                    # within-group spread
              * donor_share                               # these 5 donors' slice

    hours_per_session = weekly_hours / n_sessions, from the parsed open/close
    columns -- this is what makes demand vary pantry-by-pantry (median ~2.3h,
    range 0.5-14h), unlike the NTA-aggregated modes.
    """
    nta = p.get("nta")
    info = nta_lookup.get(nta) if nta else None

    if mode == "flat":
        return int(round(_sk_bump(p, base_lbs)))

    if mode == "equity":
        ei = info["equity_index"] if info else 0.5
        d = base_lbs * (1.0 + scale * ei)
        return int(round(_sk_bump(p, d)))

    if mode == "fi_pop":
        if not info or nta_pantry_count.get(nta, 0) == 0:
            return int(round(_sk_bump(p, base_lbs)))
        fi_pop = info["pop_2020"] * (info["fi_rate"] or 0.0)
        per_pantry_pop = fi_pop / nta_pantry_count[nta]
        d = per_pantry_pop * per_capita
        d = max(base_lbs * 0.5, d)  # floor so low-pop NTAs don't drop to ~0
        return int(round(_sk_bump(p, d)))

    if mode == "realistic":
        is_sk = "SK" in (p.get("type") or "").upper()
        # Pick the matching schedule; fall back to the other program's hours.
        if is_sk:
            wk_h, sess = p.get("sk_weekly_hours", 0), p.get("sk_sessions", 0)
            if wk_h <= 0:
                wk_h, sess = p.get("fp_weekly_hours", 0), p.get("fp_sessions", 0)
        else:
            wk_h, sess = p.get("fp_weekly_hours", 0), p.get("fp_sessions", 0)
            if wk_h <= 0:
                wk_h, sess = p.get("sk_weekly_hours", 0), p.get("sk_sessions", 0)
        if wk_h <= 0:                  # no hours anywhere -> assume a small 2h/1-session pantry
            wk_h, sess = 2.0, 1
        hours_per_session = wk_h / max(sess, 1)

        if is_sk:
            base = hours_per_session * SK_MEALS_PER_HR * LBS_PER_MEAL
        else:
            base = hours_per_session * FP_CLIENTS_PER_HR * LBS_PER_HOUSEHOLD

        ei = info["equity_index"] if info else 0.4
        need_mult = 1.0 + 0.5 * ei
        noise = 1.0
        if rng is not None and noise_cv > 0:
            noise = math.exp(rng.gauss(0.0, noise_cv))
        d = base * need_mult * noise * donor_share
        return max(10, int(round(d)))

    raise ValueError(f"unknown demand mode: {mode}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--origins", type=Path, default=DEFAULT_ORIGINS)
    ap.add_argument("--pantries", type=Path, default=DEFAULT_PANTRIES)
    ap.add_argument("--equity", type=Path, default=DEFAULT_EQUITY)
    ap.add_argument("--nta-geo", type=Path, default=DEFAULT_NTA_GEO)
    ap.add_argument("--out", type=Path, default=PROJECT / "outputs" / "instance_v0_rebuilt.json")
    ap.add_argument("--vehicle-cap-lbs", type=int, default=4000)
    ap.add_argument("--shift-min", type=int, default=480, help="Vehicle shift length (minutes)")
    ap.add_argument("--service-min", type=int, default=8, help="Per-stop service time (minutes)")
    ap.add_argument("--max-pantries", type=int, default=None,
                    help="Optional cap on # pantries (for faster solves)")
    ap.add_argument("--demand-mode",
                    choices=["flat", "equity", "fi_pop", "realistic"], default="realistic",
                    help="How to size per-pantry demand. "
                         "flat=80/120; equity=scales w/ NTA equity_index; "
                         "fi_pop=NTA food-insecure-pop / pantries-per-NTA * per_capita; "
                         "realistic=capacity-driven from operating hours + meal/household "
                         "anchors (high variation).")
    ap.add_argument("--demand-base-lbs", type=int, default=80,
                    help="Base demand per FP stop (flat/equity modes).")
    ap.add_argument("--demand-scale", type=float, default=2.0,
                    help="Multiplier on equity_index in equity mode.")
    ap.add_argument("--per-capita-lbs", type=float, default=0.05,
                    help="Daily lbs/food-insecure-person in fi_pop mode.")
    ap.add_argument("--donor-share", type=float, default=0.15,
                    help="realistic mode: fraction of each pantry's cycle throughput "
                         "these 5 donors supply (rest comes from other donors / the "
                         "unlisted tail). Scales total demand vs fleet. Default 0.15.")
    ap.add_argument("--noise-cv", type=float, default=0.35,
                    help="realistic mode: lognormal noise CV for within-group spread.")
    ap.add_argument("--seed", type=int, default=42, help="RNG seed for demand noise.")
    args = ap.parse_args()

    print(f"[1/5] Origins      : {args.origins}")
    origins = load_origins(args.origins)
    print(f"      loaded {len(origins)} origins, total fleet = "
          f"{sum(o['n_vehicles'] for o in origins)}")

    print(f"[2/5] Pantries     : {args.pantries}")
    pantries = load_open_pantries(args.pantries)
    print(f"      loaded {len(pantries)} Open pantries (boro: "
          f"{dict(Counter(p['boro'] for p in pantries))})")
    if args.max_pantries and len(pantries) > args.max_pantries:
        pantries = pantries[:args.max_pantries]
        print(f"      capped to {len(pantries)}")

    print(f"[3/5] Equity index : {args.equity}")
    nta_lookup = load_nta_equity(args.equity)
    print(f"      loaded {len(nta_lookup)} NTAs")

    print(f"[4/5] NTA polygons : {args.nta_geo}")
    nta_geo = load_nta_geo(args.nta_geo)
    print(f"      loaded {len(nta_geo)} NTA polygons")
    hit = assign_nta(pantries, nta_geo)
    print(f"      assigned NTA to {hit}/{len(pantries)} pantries")

    # Count pantries per NTA (needed for fi_pop mode).
    nta_pantry_count = Counter(p["nta"] for p in pantries if p.get("nta"))

    # Seeded RNG for reproducible demand noise (realistic mode).
    import random
    rng = random.Random(args.seed)

    # Attach equity weight + demand
    weight_hist = Counter()
    for p in pantries:
        p["w"] = round(derive_equity_weight(p, nta_lookup), 3)
        p["demand_lbs"] = estimate_demand_lbs(
            p,
            mode=args.demand_mode,
            base_lbs=args.demand_base_lbs,
            scale=args.demand_scale,
            per_capita=args.per_capita_lbs,
            nta_lookup=nta_lookup,
            nta_pantry_count=nta_pantry_count,
            rng=rng,
            donor_share=args.donor_share,
            noise_cv=args.noise_cv,
        )
        # Stash need tercile so the solver can report coverage by tier.
        info = nta_lookup.get(p.get("nta"))
        p["need_t"] = info["need_t"] if info else 0
        p["access_t"] = info["access_t"] if info else 0
        p["equity_index"] = round(info["equity_index"], 3) if info else 0.0
        weight_hist[p["w"]] += 1
    print(f"      equity weight distribution: "
          f"{dict(sorted(weight_hist.items()))}")

    # Demand distribution summary (variation + by need tercile).
    ds = sorted(p["demand_lbs"] for p in pantries)
    n = len(ds)
    def pct(q):
        return ds[min(n - 1, int(q * n))]
    mean = sum(ds) / n
    var = sum((x - mean) ** 2 for x in ds) / n
    cv = (var ** 0.5) / mean if mean else 0
    print(f"      demand mode = {args.demand_mode}  "
          f"(donor_share={args.donor_share}, noise_cv={args.noise_cv}, seed={args.seed})")
    print(f"      demand spread: min={ds[0]} p10={pct(.10)} median={pct(.50)} "
          f"p90={pct(.90)} max={ds[-1]}  CV={cv:.2f}  (p90/median={pct(.90)/max(pct(.50),1):.1f}x)")
    by_tier = {0: [0, 0], 1: [0, 0], 2: [0, 0]}
    for p in pantries:
        t = p["need_t"]
        by_tier[t][0] += 1
        by_tier[t][1] += p["demand_lbs"]
    for t in (0, 1, 2):
        cnt, total = by_tier[t]
        avg = total / cnt if cnt else 0
        label = ["low-need", "mid-need", "high-need"][t]
        print(f"         {label:>10}  n={cnt:3d}  total={total:>8,} lbs  "
              f"mean={avg:6.0f} lbs/stop")

    # Vehicles: each vehicle bound to its origin index
    vehicles = []
    for oi, o in enumerate(origins):
        for _ in range(o["n_vehicles"]):
            vehicles.append({
                "origin_idx": oi,
                "capacity_lbs": args.vehicle_cap_lbs,
                "shift_min": args.shift_min,
            })

    demand_desc = {
        "flat": "flat 80/120 lbs (placeholder)",
        "equity": f"scales with NTA equity_index (base={args.demand_base_lbs}, scale={args.demand_scale})",
        "fi_pop": f"food-insecure pop / pantries-per-NTA (per_capita={args.per_capita_lbs})",
        "realistic": f"capacity-driven from operating hours (donor_share={args.donor_share}, noise_cv={args.noise_cv})",
    }[args.demand_mode]
    instance = {
        "params": {
            "vehicle_cap_lbs": args.vehicle_cap_lbs,
            "shift_min": args.shift_min,
            "service_min": args.service_min,
            "speed_kmh": 25.0,
            "demand_mode": args.demand_mode,
            "demand_desc": demand_desc,
        },
        "origins": origins,
        "pantries": pantries,
        "vehicles": vehicles,
    }

    out = args.out
    with open(out, "w") as f:
        json.dump(instance, f, indent=2)
    print(f"[5/5] Wrote {out}")
    print(f"      origins={len(origins)} pantries={len(pantries)} vehicles={len(vehicles)}")
    total_demand = sum(p["demand_lbs"] for p in pantries)
    total_cap = len(vehicles) * args.vehicle_cap_lbs
    print(f"      total demand = {total_demand:,} lbs, fleet capacity = {total_cap:,} lbs "
          f"({100*total_cap/total_demand:.1f}%)")


if __name__ == "__main__":
    main()
