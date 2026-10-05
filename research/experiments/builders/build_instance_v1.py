"""
build_instance_v1.py -- v1 instance builder. Addresses limitations:

  L1 richer demand : hours-capacity x nearest-pantry food-insecure CATCHMENT,
                     not a flat per-stop number.
  L3 time windows  : per-pantry [open, close] on a chosen service day, parsed
                     from the fp_*/sk_* open/close columns.
  L4 cold-chain    : demand split into COLD (produce/dairy/prepared/meat) vs
                     AMBIENT (bakery/dry) buckets via data/donor_classes.csv.
  L5 multi-site    : Trader Joe's & Whole Foods are several real NYC depots
                     (data/origins_v1.csv), supply + vehicles split across sites.
  L6 smooth weights: equity weight from CONTINUOUS need_pct / access_pct
                     percentiles, not (need_t+1)/(access_t+1) terciles.

Output: instance_v1.json
"""
from __future__ import annotations
import argparse, csv, json, math, random
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

# reuse geometry + hours helpers from the v0 builder
import build_instance as B0

HERE = Path(__file__).resolve().parent
DEFAULT_PANTRIES = B0.DEFAULT_PANTRIES
DEFAULT_EQUITY = B0.DEFAULT_EQUITY
DEFAULT_NTA_GEO = B0.DEFAULT_NTA_GEO
DEFAULT_ORIGINS = HERE.parent / "scenarios" / "origins_v1.csv"
DEFAULT_CLASSES = HERE.parent / "scenarios" / "donor_classes.csv"

_DAY_KEY = {0: "mon", 1: "tue", 2: "wed", 3: "thu", 4: "fri", 5: "sat", 6: "sun"}

# real-world anchors (see README "Demand-model sources")
LBS_PER_MEAL = 1.2
LBS_PER_HOUSEHOLD = 4.0 * 2.5 * 3       # 4 lb * 2.5 persons * 3 days = 30 lb
FP_CLIENTS_PER_HR = 15.0
SK_MEALS_PER_HR = 60.0


# ----------------------------------------------------------------------------- origins
def load_origins_multisite(path: Path):
    rows = []
    with open(path) as f:
        for r in csv.DictReader(f):
            rows.append({
                "donor": r["donor"],
                "name": r["site_name"],
                "category": r["category"],
                "address": r["address"],
                "lat": float(r["lat"]), "lon": float(r["lon"]),
                "est_lbs_yr": float(r["est_lbs_yr"]),
                "n_vehicles": int(r["n_vehicles"]),
                "cold_frac": float(r["cold_frac"]),
            })
    return rows


# ----------------------------------------------------------------------------- time windows
def day_window_minutes(row, prefix, day_key, shift_start_min):
    """Earliest open & latest close (minutes from midnight) for `day_key`,
    returned relative to shift_start_min. None if closed that day."""
    opens, closes = [], []
    for slot in ("1", "2", "3"):
        o = B0._parse_clock(row.get(f"{prefix}_{day_key}_open{slot}", ""))
        c = B0._parse_clock(row.get(f"{prefix}_{day_key}_close{slot}", ""))
        if o and c:
            om = o.hour * 60 + o.minute
            cm = c.hour * 60 + c.minute
            if 0 <= cm - om <= 14 * 60:
                opens.append(om); closes.append(cm)
    if not opens:
        return None
    return (min(opens) - shift_start_min, max(closes) - shift_start_min)


# ----------------------------------------------------------------------------- equity (smooth)
def load_nta_equity_smooth(path: Path):
    """Like B0.load_nta_equity but also keep continuous need_pct / access_pct."""
    out = {}
    with open(path) as f:
        for r in csv.DictReader(f):
            try:
                out[r["nta2020"]] = {
                    "boroname": r["boroname"], "ntaname": r["ntaname"],
                    "fi_rate": float(r["fi_rate"]) if r["fi_rate"] else 0.0,
                    "pop_2020": int(float(r["pop_2020"])) if r["pop_2020"] else 0,
                    "need_pct": float(r["need_pct"]) if r["need_pct"] else 0.5,
                    "access_pct": float(r["access_pct"]) if r["access_pct"] else 0.5,
                    "equity_index": float(r["equity_index"]) if r["equity_index"] else 0.0,
                    "need_t": int(r["need_t"]) if r["need_t"] else 0,
                    "access_t": int(r["access_t"]) if r["access_t"] else 0,
                }
            except (KeyError, ValueError):
                continue
    return out


def smooth_weight(info, gamma=1.0, lo=0.5, hi=4.0):
    """Continuous equity weight from percentiles (no tercile bin jumps).

    w = ((need_pct + eps) / (access_pct + eps)) ** gamma, clamped.
    need_pct high (very food-insecure) and access_pct low (poorly served)
    -> large w. gamma sharpens/softens the tilt.
    """
    if not info:
        return 1.0
    eps = 0.15
    raw = ((info["need_pct"] + eps) / (info["access_pct"] + eps)) ** gamma
    return max(lo, min(hi, raw))


def sample_window(rng_w, am_frac, win_width, shift_start_min, horizon):
    """Sample a delivery window (minutes from shift start) from a realistic
    distribution: most agencies want 7-11am (truncated normal peaked ~8:30am),
    a minority spread into the afternoon. Models 'mostly morning, some later'
    instead of a single rigid 7-11am slot for everyone."""
    if rng_w.random() < am_frac:                       # 7-11am AM peak
        start = rng_w.gauss(8 * 60 + 30, 55)           # ~8:30am, sd 55min
        start = max(7 * 60, min(10 * 60, start))       # clamp 7:00-10:00
    else:                                              # spread into the day
        start = rng_w.uniform(11 * 60, 17 * 60)        # 11:00-17:00
    o = start - shift_start_min
    c = o + win_width
    return int(max(0, min(horizon, o))), int(max(0, min(horizon, c)))


def stop_service_min(demand_lbs, base=15, per_lb=150, cap=30):
    """Per-stop delivery/dwell time in minutes: base + 2 min per `per_lb` lbs,
    capped. Bigger drops take longer to unload. Default range ~15-30 min
    (parking + unloading + agency sign-off), matching City Harvest dwell."""
    return int(min(cap, base + 2 * (demand_lbs // per_lb)))


# ----------------------------------------------------------------------------- demand
def build_classes(path: Path):
    """Read the food-type table; split into cold vs ambient by model_bucket.
    Columns: food_type, requires_cold, shelf_life_hours, urgency,
             compatible_vehicle, model_bucket, notes."""
    cold, ambient = [], []
    with open(path) as f:
        for r in csv.DictReader(f):
            (cold if r["model_bucket"] == "cold" else ambient).append(r)
    return cold, ambient


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--origins", type=Path, default=DEFAULT_ORIGINS)
    ap.add_argument("--pantries", type=Path, default=DEFAULT_PANTRIES)
    ap.add_argument("--equity", type=Path, default=DEFAULT_EQUITY)
    ap.add_argument("--nta-geo", type=Path, default=DEFAULT_NTA_GEO)
    ap.add_argument("--classes", type=Path, default=DEFAULT_CLASSES)
    ap.add_argument("--out", type=Path, default=B0.PROJECT / "outputs" / "instance_v1_rebuilt.json")
    # fleet
    ap.add_argument("--reefer-frac", type=float, default=0.7,
                    help="Fraction of each site's vehicles that are refrigerated.")
    ap.add_argument("--vehicle-cap-lbs", type=int, default=4000)
    # time / shift
    ap.add_argument("--service-day", default="wed",
                    help="Day whose open/close hours become delivery windows (busiest=wed).")
    ap.add_argument("--window-mode", choices=["hours", "ch711", "ch_stat", "hybrid"],
                    default="hours",
                    help="Time-window source: hours=pantry posted hours; "
                         "ch711=City Harvest 7-11am for all; "
                         "ch_stat=sampled (mostly 7-11am, some later); hybrid=real hours else 7-11am.")
    ap.add_argument("--am-frac", type=float, default=0.75,
                    help="ch_stat: fraction of agencies wanting the 7-11am morning slot.")
    ap.add_argument("--win-width", type=int, default=120,
                    help="ch_stat: delivery-window width in minutes.")
    ap.add_argument("--shift-start", default="07:00", help="Shift start clock (HH:MM).")
    ap.add_argument("--horizon-min", type=int, default=480, help="Shift length (minutes).")
    ap.add_argument("--service-min", type=int, default=8)
    # demand
    ap.add_argument("--donor-share", type=float, default=0.12)
    ap.add_argument("--cold-fraction", type=float, default=0.55,
                    help="SCENARIO: system cold share (mixed pantries' mean cold fraction). "
                         "Sweep 0.3/0.5/0.7 — calibrate to donor product data when available.")
    ap.add_argument("--ambient-only-frac", type=float, default=0.20,
                    help="Fraction of pantries that take only shelf-stable (cold=0).")
    ap.add_argument("--noise-cv", type=float, default=0.30,
                    help="Lognormal noise CV (z truncated to +/-2 sigma).")
    ap.add_argument("--hps-cap", type=float, default=5.0,
                    help="Max hours-per-session (a single distribution runs 2-5h).")
    ap.add_argument("--catch-cap", type=float, default=3.0,
                    help="Max catchment multiple of median (caps mega-catchment tail).")
    ap.add_argument("--catchment-wt", type=float, default=0.5,
                    help="Blend: demand *= (1-wt) + wt*catchment_norm.")
    ap.add_argument("--gamma", type=float, default=1.0, help="Equity-weight sharpness.")
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()
    rng = random.Random(args.seed)

    sh = datetime.strptime(args.shift_start, "%H:%M")
    shift_start_min = sh.hour * 60 + sh.minute

    print(f"[1/6] origins (multi-site) : {args.origins}")
    origins = load_origins_multisite(args.origins)
    donors = sorted({o["donor"] for o in origins})
    print(f"      {len(origins)} sites across {len(donors)} donors, "
          f"fleet = {sum(o['n_vehicles'] for o in origins)} vehicles")

    print(f"[2/6] pantries             : {args.pantries}")
    pantries = B0.load_open_pantries(args.pantries)
    print(f"      {len(pantries)} open pantries")

    print(f"[3/6] equity (smooth pct)  : {args.equity}")
    nta = load_nta_equity_smooth(args.equity)
    nta_geo = B0.load_nta_geo(args.nta_geo)
    B0.assign_nta(pantries, nta_geo)
    print(f"      {len(nta)} NTAs; assigned {sum(1 for p in pantries if p.get('nta'))}/"
          f"{len(pantries)} pantries to an NTA")

    print(f"[4/6] cold-chain classes   : {args.classes}")
    cold_classes, ambient_classes = build_classes(args.classes)
    print(f"      cold (reefer-only)={[c['food_type'] for c in cold_classes]}")
    print(f"      ambient (any vehicle)={[c['food_type'] for c in ambient_classes]}")

    # catchment: food-insecure people nearest THIS pantry (Voronoi-ish via NTA share)
    nta_pantries = defaultdict(list)
    for p in pantries:
        if p.get("nta"):
            nta_pantries[p["nta"]].append(p)
    catch = {}
    for p in pantries:
        info = nta.get(p.get("nta"))
        if info and nta_pantries[p["nta"]]:
            fi_pop = info["pop_2020"] * info["fi_rate"]
            catch[id(p)] = fi_pop / len(nta_pantries[p["nta"]])
        else:
            catch[id(p)] = 0.0
    med_catch = sorted(catch.values())[len(catch)//2] or 1.0

    print(f"[5/6] demand + windows     : service-day={args.service_day} "
          f"shift={args.shift_start}+{args.horizon_min}min")
    tw_count = 0
    for p in pantries:
        info = nta.get(p.get("nta"))
        is_sk = "SK" in (p.get("type") or "").upper()
        # ---- capacity from operating hours
        if is_sk:
            wk_h, sess = p.get("sk_weekly_hours", 0), p.get("sk_sessions", 0)
            if wk_h <= 0:
                wk_h, sess = p.get("fp_weekly_hours", 0), p.get("fp_sessions", 0)
        else:
            wk_h, sess = p.get("fp_weekly_hours", 0), p.get("fp_sessions", 0)
            if wk_h <= 0:
                wk_h, sess = p.get("sk_weekly_hours", 0), p.get("sk_sessions", 0)
        if wk_h <= 0:
            wk_h, sess = 2.0, 1
        # hours-per-session, CAPPED: a single staffed distribution runs ~2-5h, not
        # 14h. Pantries with high weekly hours but few *recorded* distinct days were
        # the source of the old 8,452-lb tail; cap so no session exceeds HPS_CAP.
        hps = min(wk_h / max(sess, 1), args.hps_cap)
        cap_lbs = (hps * SK_MEALS_PER_HR * LBS_PER_MEAL) if is_sk \
            else (hps * FP_CLIENTS_PER_HR * LBS_PER_HOUSEHOLD)
        # ---- catchment blend (L1: demand reflects people served, not just hours)
        catch_norm = min(catch[id(p)] / med_catch, args.catch_cap)  # cap extreme catchments
        catch_mult = (1 - args.catchment_wt) + args.catchment_wt * catch_norm
        # ---- need tilt + noise (bounded to +/-2 sigma) + donor share
        ei = info["equity_index"] if info else 0.4
        need_mult = 1.0 + 0.5 * ei
        z = max(-2.0, min(2.0, rng.gauss(0, 1)))         # truncated normal
        noise = math.exp(args.noise_cv * z)
        total = max(10.0, cap_lbs * catch_mult * need_mult * noise * args.donor_share)
        # ---- cold/ambient split (L4): SCENARIO ASSUMPTION, not measured fact.
        # System cold share is a tunable knob (--cold-fraction); per-pantry values
        # vary around it via a Beta with that mean. ~ambient_only_frac of pantries
        # are dry-goods-only (cold=0) so the dry fleet has work and the reefer
        # constraint isn't all-or-nothing. Replace with donor product breakdowns
        # when available (see data/donor_classes.csv for the food_type mapping).
        if rng.random() < args.ambient_only_frac:
            cf = 0.0
        else:
            m = args.cold_fraction; k = 5.0           # Beta mean = m, concentration k
            cf = min(0.95, max(0.05, rng.betavariate(max(0.5, m*k), max(0.5, (1-m)*k))))
        p["demand_cold"] = int(round(total * cf))
        p["demand_ambient"] = int(round(total * (1 - cf)))
        p["demand_lbs"] = p["demand_cold"] + p["demand_ambient"]
        p["cold_frac"] = round(cf, 3)
        # per-stop delivery/dwell time scales with how much is dropped (L3+)
        p["service_min"] = stop_service_min(p["demand_lbs"], base=args.service_min)
        # ---- smooth equity weight (L6)
        p["w"] = round(smooth_weight(info, gamma=args.gamma), 3)
        p["need_pct"] = round(info["need_pct"], 3) if info else 0.5
        p["access_pct"] = round(info["access_pct"], 3) if info else 0.5
        p["need_t"] = info["need_t"] if info else 0
        p["access_t"] = info["access_t"] if info else 0
        p["equity_index"] = round(info["equity_index"], 3) if info else 0.0
        # ---- time window (L3)
        # find the raw CSV row again for per-day open/close: re-parse from stored fields
        win = None
        # we parsed weekly hours but not per-day windows; redo from the source row
        # (pantries dict doesn't carry raw row, so we re-read below in a second pass)
        p["_is_sk"] = is_sk

    # second pass: time windows. window-mode controls the source.
    #   hours  : each pantry's own posted open/close on the service day (v1 default)
    #   ch711  : City Harvest reality -- a tight 7-11am slot for ALL stops
    #   hybrid : pantry's real posted hours where known, else the 7-11am slot
    #   ch_stat: sampled -- most agencies 7-11am, a minority spread later (realistic)
    ch_open = 7 * 60 - shift_start_min       # 7:00 relative to shift start
    ch_close = 11 * 60 - shift_start_min     # 11:00 relative to shift start
    rng_w = random.Random(args.seed + 1)
    src = {r["FID"]: r for r in csv.DictReader(open(args.pantries)) if r["status"] == "Open"}
    am_in_window = 0
    for p in pantries:
        win = None
        if args.window_mode in ("hours", "hybrid"):
            r = src.get(p["fid"])
            if r is not None:
                prefix = "sk" if p["_is_sk"] else "fp"
                win = day_window_minutes(r, prefix, args.service_day, shift_start_min)
                if win is None:
                    win = day_window_minutes(r, "fp" if prefix == "sk" else "sk",
                                             args.service_day, shift_start_min)
        if args.window_mode == "ch_stat":
            win = sample_window(rng_w, args.am_frac, args.win_width,
                                shift_start_min, args.horizon_min)
        elif args.window_mode == "ch711" or (args.window_mode == "hybrid" and win is None):
            win = (ch_open, ch_close)         # CH 7-11am hard window
        if win is not None:
            o, c = win
            o = max(0, min(args.horizon_min, o)); c = max(0, min(args.horizon_min, c))
            if c - o < p.get("service_min", args.service_min):
                c = min(args.horizon_min, o + 60)
            p["tw_open"], p["tw_close"], p["has_window"] = int(o), int(c), True
            tw_count += 1
            if o <= (10 * 60 - shift_start_min):   # window starts by 10am -> "morning"
                am_in_window += 1
        else:
            p["tw_open"], p["tw_close"], p["has_window"] = 0, args.horizon_min, False
        del p["_is_sk"]
    svcs = [p["service_min"] for p in pantries]
    print(f"      window-mode={args.window_mode}: {tw_count}/{len(pantries)} pantries have a "
          f"hard delivery window ({am_in_window} starting by 10am = morning)")
    print(f"      per-stop dwell time: min={min(svcs)} median={sorted(svcs)[len(svcs)//2]} "
          f"max={max(svcs)} min  (scales with drop size)")

    # ---- vehicles: split each site's fleet into reefer (cold-capable) vs dry
    vehicles = []
    for oi, o in enumerate(origins):
        n_reefer = int(round(o["n_vehicles"] * args.reefer_frac))
        for k in range(o["n_vehicles"]):
            is_reefer = k < n_reefer
            vehicles.append({
                "origin_idx": oi,
                "donor": o["donor"],
                "type": "reefer" if is_reefer else "dry",
                "cap_total_lbs": args.vehicle_cap_lbs,
                "cap_cold_lbs": args.vehicle_cap_lbs if is_reefer else 0,
                "shift_min": args.horizon_min,
            })
    n_reefer = sum(1 for v in vehicles if v["type"] == "reefer")

    # ---- report demand distribution
    ds = sorted(p["demand_lbs"] for p in pantries)
    n = len(ds); mean = sum(ds)/n
    cv = (sum((x-mean)**2 for x in ds)/n) ** 0.5 / mean
    tot_cold = sum(p["demand_cold"] for p in pantries)
    tot_amb = sum(p["demand_ambient"] for p in pantries)

    print(f"[6/6] write {args.out.name}")
    instance = {
        "params": {
            "service_day": args.service_day, "shift_start": args.shift_start,
            "window_mode": args.window_mode,
            "horizon_min": args.horizon_min, "service_min": args.service_min,
            "vehicle_cap_lbs": args.vehicle_cap_lbs, "reefer_frac": args.reefer_frac,
            "donor_share": args.donor_share, "gamma": args.gamma,
            "catchment_wt": args.catchment_wt, "seed": args.seed,
            "demand_desc": (f"hours-capacity x catchment (wt={args.catchment_wt}), "
                            f"cold/ambient split, donor_share={args.donor_share}"),
            "n_donors": len(donors),
        },
        "origins": origins, "pantries": pantries, "vehicles": vehicles,
    }
    args.out.write_text(json.dumps(instance, indent=2))

    fleet_cap = len(vehicles) * args.vehicle_cap_lbs
    reefer_cap = n_reefer * args.vehicle_cap_lbs
    print(f"      sites={len(origins)} donors={len(donors)} pantries={n} "
          f"vehicles={len(vehicles)} ({n_reefer} reefer / {len(vehicles)-n_reefer} dry)")
    print(f"      demand: total={sum(ds):,} lbs  cold={tot_cold:,} ({100*tot_cold/sum(ds):.0f}%)  "
          f"ambient={tot_amb:,}")
    print(f"      spread: min={ds[0]} median={ds[n//2]} max={ds[-1]} CV={cv:.2f}")
    print(f"      weights (smooth): min={min(p['w'] for p in pantries):.2f} "
          f"max={max(p['w'] for p in pantries):.2f} "
          f"distinct={len(set(p['w'] for p in pantries))} values "
          f"(vs 6 tercile values in v0)")
    print(f"      capacity: fleet={fleet_cap:,} lbs (cold-capable={reefer_cap:,}); "
          f"demand/cap={100*sum(ds)/fleet_cap:.0f}%, cold demand/cold cap="
          f"{100*tot_cold/reefer_cap:.0f}%")


if __name__ == "__main__":
    main()
