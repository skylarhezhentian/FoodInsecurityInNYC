"""
geo_travel.py -- Travel-time / distance backends for the routing instance.

Three backends (addresses the "haversine + flat speed" limitation):

  haversine : straight-line km / flat speed (v0 behavior, kept for comparison).
  road      : OSRM-CALIBRATED. Road km = haversine * DETOUR, time = road km /
              (OSRM free-flow speed * congestion). DETOUR and free-flow speed were
              fit from 3,536 real OSRM driving pairs across NYC pantries
              (detour 1.33, free-flow 46 km/h). Fast, deterministic, no network.
  osrm      : full N x N OSRM /table matrix, tiled into <=100-coord requests via
              curl (urllib SSL fails in this env), cached to disk (osrm_cache.npz).
              Free-flow (OSRM has no traffic model). Falls back to `road` per tile
              on any failure.

Returns (dist_km[NxN] float, time_min[NxN] int) including per-stop service time
added on arrival at delivery nodes.
"""
from __future__ import annotations
import json, math, subprocess, time
from pathlib import Path
import numpy as np

HERE = Path(__file__).resolve().parent

# --- constants calibrated from a real OSRM sample (see README / commit notes) ---
OSRM_DETOUR = 1.33          # road km / straight-line km, median of 3,536 pairs
OSRM_FREEFLOW_KMH = 46.0    # OSRM driving speed, no congestion
OSRM_URL = "https://router.project-osrm.org"
OSRM_MAX_COORDS = 100       # public demo server cap per /table request


def haversine_km(lon1, lat1, lon2, lat2):
    R = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp/2)**2 + math.cos(p1)*math.cos(p2)*math.sin(dl/2)**2
    return 2 * R * math.asin(math.sqrt(a))


def _haversine_matrix(lons, lats):
    n = len(lons)
    lat = np.radians(np.array(lats)); lon = np.radians(np.array(lons))
    dlat = lat[:, None] - lat[None, :]
    dlon = lon[:, None] - lon[None, :]
    a = np.sin(dlat/2)**2 + np.cos(lat)[:, None]*np.cos(lat)[None, :]*np.sin(dlon/2)**2
    return 2 * 6371.0 * np.arcsin(np.sqrt(np.clip(a, 0, 1)))


def _osrm_table(coords, sources=None, destinations=None, retries=3):
    """Call OSRM /table via curl. coords: list of (lon,lat). Returns (durations, distances)
    in seconds / meters, or None on failure."""
    coord_str = ";".join(f"{lo:.5f},{la:.5f}" for lo, la in coords)
    q = "annotations=duration,distance"
    if sources is not None:
        q += "&sources=" + ";".join(map(str, sources))
    if destinations is not None:
        q += "&destinations=" + ";".join(map(str, destinations))
    url = f"{OSRM_URL}/table/v1/driving/{coord_str}?{q}"
    for attempt in range(retries):
        try:
            out = subprocess.run(["curl", "-s", "--max-time", "45", url],
                                 capture_output=True, text=True).stdout
            d = json.loads(out)
            if d.get("code") == "Ok":
                return d.get("durations"), d.get("distances")
        except Exception:
            pass
        time.sleep(1.0 + attempt)
    return None


# --- time-of-day congestion profile (fraction of OSRM free-flow speed) ----------
# NYC reality: AM peak is slowest. Static-arc routers can't vary speed by the clock
# mid-route, so a run uses one band (AM-peak default, since delivery is morning-heavy).
# True per-arc time-dependence = a time-expanded graph / iterative re-solve (future).
TOD_CONGESTION = {"am_peak": 0.38, "midday": 0.55, "pm_peak": 0.42, "night": 0.80}


def osrm_route_lonlats(coords, retries=2):
    """OSRM /route geometry through `coords` (list of (lon,lat) in visit order).
    Returns the actual road polyline as [[lon,lat],...], or None on failure.
    One call draws a whole truck's route along real streets."""
    if len(coords) < 2:
        return None
    cs = ";".join(f"{lo:.5f},{la:.5f}" for lo, la in coords)
    url = f"{OSRM_URL}/route/v1/driving/{cs}?overview=full&geometries=geojson"
    for a in range(retries):
        try:
            out = subprocess.run(["curl", "-s", "--max-time", "30", url],
                                 capture_output=True, text=True).stdout
            d = json.loads(out)
            if d.get("code") == "Ok" and d.get("routes"):
                return d["routes"][0]["geometry"]["coordinates"]
        except Exception:
            pass
        time.sleep(0.4)
    return None


def build_matrices(lons, lats, n_origins, *, backend="road",
                   service_min=8, congestion=0.6, tod=None, cache=None, verbose=True):
    """Return (dist_km NxN, time_min NxN int). `service_min` may be a scalar or a
    length-n array (per-node dwell time, 0 for origins). `tod` (if set) selects a
    time-of-day congestion band and overrides `congestion`."""
    n = len(lons)
    if tod is not None:
        congestion = TOD_CONGESTION[tod]
    hav = _haversine_matrix(lons, lats)            # straight-line km

    if backend == "haversine":
        dist_km = hav
        speed = OSRM_FREEFLOW_KMH * congestion
        time_min = dist_km / speed * 60.0

    elif backend == "road":
        dist_km = hav * OSRM_DETOUR
        speed = OSRM_FREEFLOW_KMH * congestion     # congestion-adjusted
        time_min = dist_km / speed * 60.0

    elif backend == "osrm":
        dist_km, time_min = _build_osrm(lons, lats, hav, congestion, cache, verbose)

    else:
        raise ValueError(f"unknown travel backend: {backend}")

    # add per-stop service time on arrival. service_min: scalar -> all delivery nodes;
    # array of length n -> per-node dwell (origins should be 0).
    svc = np.zeros((n, n))
    if np.ndim(service_min) == 0:
        svc[:, n_origins:] = service_min
    else:
        svc[:, :] = np.asarray(service_min)[None, :]   # service at destination node
    np.fill_diagonal(svc, 0)
    time_min = np.rint(time_min + svc).astype(np.int64)
    np.fill_diagonal(time_min, 0)
    return dist_km, time_min


def _build_osrm(lons, lats, hav, congestion, cache, verbose):
    """Full tiled OSRM matrix with disk cache + per-tile `road` fallback."""
    n = len(lons)
    cache_path = Path(cache) if cache else (HERE / "osrm_cache.npz")
    if cache_path.exists():
        z = np.load(cache_path)
        if z["dist_km"].shape == (n, n):
            if verbose:
                print(f"[osrm] loaded cached matrix {cache_path.name}")
            return z["dist_km"], z["time_min_freeflow"] / congestion * 1.0  # apply congestion below
    coords = list(zip(lons, lats))
    dist_km = hav * OSRM_DETOUR                     # fallback init
    dur_s = (dist_km / OSRM_FREEFLOW_KMH) * 3600.0
    B = OSRM_MAX_COORDS // 2                          # 50: sources + dests <= 100
    blocks = [list(range(i, min(i+B, n))) for i in range(0, n, B)]
    n_req = len(blocks) ** 2
    ok = 0
    if verbose:
        print(f"[osrm] building {n}x{n} via {n_req} tiled requests (B={B})...")
    for bi in blocks:
        for bj in blocks:
            idx = bi + bj
            sub = [coords[k] for k in idx]
            src = list(range(len(bi)))
            dst = list(range(len(bi), len(bi)+len(bj)))
            res = _osrm_table(sub, sources=src, destinations=dst)
            if res:
                dur, dist = res
                for a, gi in enumerate(bi):
                    for b, gj in enumerate(bj):
                        if dur[a][b] is not None:
                            dur_s[gi, gj] = dur[a][b]
                        if dist[a][b] is not None:
                            dist_km[gi, gj] = dist[a][b] / 1000.0
                ok += 1
            time.sleep(0.25)
    if verbose:
        print(f"[osrm] {ok}/{n_req} tiles OK ({100*ok/n_req:.0f}%); rest used road fallback")
    time_min_freeflow = dur_s / 60.0
    np.savez_compressed(cache_path, dist_km=dist_km, time_min_freeflow=time_min_freeflow)
    # apply congestion: OSRM durations are free-flow; scale up travel time
    return dist_km, time_min_freeflow / congestion
