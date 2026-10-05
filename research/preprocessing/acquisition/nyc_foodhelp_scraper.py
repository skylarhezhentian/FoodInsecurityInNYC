#!/usr/bin/env python3
"""
NYC Food Help locations scraper.

The finder at https://finder.nyc.gov/foodhelp/locations is a JavaScript single-page
app: the page HTML has no data in it -- the locations are loaded from a backend JSON
API *after* the page renders. So you scrape the API, not the HTML.

TWO WAYS TO USE THIS
--------------------
1) FINDER API  (recommended; gives you exactly what the site shows)
   - Open https://finder.nyc.gov/foodhelp/locations in Chrome or Firefox
   - Press F12  ->  Network tab  ->  filter to "Fetch/XHR"
   - Reload the page (or run a location search in the UI)
   - Find the request whose response is JSON full of location records
   - Right-click it  ->  Copy  ->  "Copy URL"
   - Paste it below as FINDER_API_URL, or pass it with --url

2) NYC OPEN DATA (Socrata) fallback
   - The underlying dataset is HRA's "NYC Food Pantries and Community Kitchens" /
     Community Food Connection, published on https://data.cityofnewyork.us
   - Open the dataset, click Export / API to get its 4x4 resource id (e.g. abcd-1234)
   - Put it in SOCRATA_DATASET_ID below and run with --source socrata

RUN
---
    pip install requests
    python nyc_foodhelp_scraper.py --url "PASTE_FINDER_API_URL_HERE"
    python nyc_foodhelp_scraper.py --source socrata --dataset abcd-1234

OUTPUT
------
    nyc_foodhelp_raw.json       raw records (so you never re-hit the API while iterating)
    nyc_foodhelp_locations.csv  flattened, one row per location
    nyc_foodhelp_locations.geojson  points (for mapping), when lat/lon are present
"""

import argparse
import csv
import json
import sys
import time

import requests  # pip install requests

# ----------------------------------------------------------------------
# CONFIG -- fill these in (or pass on the command line)
# ----------------------------------------------------------------------
FINDER_API_URL = ""           # <- paste the URL from the browser Network tab
SOCRATA_DATASET_ID = ""       # <- e.g. "abcd-1234" from data.cityofnewyork.us
SOCRATA_DOMAIN = "data.cityofnewyork.us"

HEADERS = {
    # Identify yourself -- be a polite scraper.
    "User-Agent": "nyc-foodhelp-scraper/1.0 (research project; contact: you@example.com)",
    "Accept": "application/json",
}

OUT_RAW = "nyc_foodhelp_raw.json"
OUT_CSV = "nyc_foodhelp_locations.csv"
OUT_GEOJSON = "nyc_foodhelp_locations.geojson"


def flatten(record, parent_key="", sep="."):
    """Flatten a nested dict/list into a single-level dict of scalar values."""
    items = {}
    if isinstance(record, dict):
        for k, v in record.items():
            new_key = f"{parent_key}{sep}{k}" if parent_key else str(k)
            items.update(flatten(v, new_key, sep))
    elif isinstance(record, list):
        if all(not isinstance(x, (dict, list)) for x in record):
            # simple list -> join into one cell
            items[parent_key] = "; ".join("" if x is None else str(x) for x in record)
        else:
            for i, v in enumerate(record):
                items.update(flatten(v, f"{parent_key}{sep}{i}", sep))
    else:
        items[parent_key] = record
    return items


def extract_list(payload):
    """Find the list of records inside whatever shape the API returns."""
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in ("results", "locations", "items", "data", "features", "records", "rows"):
            if isinstance(payload.get(key), list):
                return payload[key]
    return []


def fetch_finder(url):
    """Pull all records from the finder JSON API, following simple pagination."""
    if not url:
        sys.exit("No FINDER_API_URL set. Paste the Network-tab URL (see top of file) "
                 "or pass --url.")
    session = requests.Session()
    session.headers.update(HEADERS)

    all_records = []
    resp = session.get(url, timeout=30)
    resp.raise_for_status()
    payload = resp.json()
    all_records.extend(extract_list(payload))

    # Follow a 'next page' link if the endpoint exposes one.
    def next_link(p):
        if isinstance(p, dict):
            return p.get("next") or p.get("nextPage") or p.get("next_url")
        return None

    nxt = next_link(payload)
    while nxt:
        time.sleep(0.3)
        resp = session.get(nxt, timeout=30)
        resp.raise_for_status()
        payload = resp.json()
        page = extract_list(payload)
        if not page:
            break
        all_records.extend(page)
        nxt = next_link(payload)

    return all_records


def fetch_socrata(dataset_id, domain=SOCRATA_DOMAIN):
    """Pull all rows from a Socrata (NYC Open Data) dataset with offset paging."""
    if not dataset_id:
        sys.exit("No SOCRATA_DATASET_ID set. Get the 4x4 id from the dataset's "
                 "Export/API panel on data.cityofnewyork.us.")
    session = requests.Session()
    session.headers.update(HEADERS)
    base = f"https://{domain}/resource/{dataset_id}.json"
    rows, offset, page_size = [], 0, 1000
    while True:
        resp = session.get(base, params={"$limit": page_size, "$offset": offset}, timeout=30)
        resp.raise_for_status()
        batch = resp.json()
        if not batch:
            break
        rows.extend(batch)
        offset += page_size
        time.sleep(0.2)
    return rows


def write_csv(records, path):
    flat = [flatten(r) for r in records]
    fields, seen = [], set()
    for r in flat:
        for k in r:
            if k not in seen:
                seen.add(k)
                fields.append(k)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(flat)
    print(f"  CSV     : {len(flat)} rows x {len(fields)} cols -> {path}")


def find_coords(flat):
    """Best-effort latitude/longitude detection from a flattened record."""
    lat = lon = None
    for k, v in flat.items():
        lk = k.lower()
        if lat is None and "lat" in lk:
            try:
                lat = float(v)
            except (TypeError, ValueError):
                pass
        if lon is None and ("lon" in lk or "lng" in lk):
            try:
                lon = float(v)
            except (TypeError, ValueError):
                pass
    return lat, lon


def write_geojson(records, path):
    feats = []
    for r in records:
        flat = flatten(r)
        lat, lon = find_coords(flat)
        if lat is None or lon is None:
            continue
        feats.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [lon, lat]},
            "properties": flat,
        })
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"type": "FeatureCollection", "features": feats}, f, indent=2)
    print(f"  GeoJSON : {len(feats)} geo-located features -> {path}")


def main():
    ap = argparse.ArgumentParser(description="Scrape NYC Food Help locations.")
    ap.add_argument("--source", choices=["finder", "socrata"], default="finder")
    ap.add_argument("--url", default=FINDER_API_URL,
                    help="Finder JSON API URL (from the browser Network tab).")
    ap.add_argument("--dataset", default=SOCRATA_DATASET_ID,
                    help="Socrata dataset 4x4 id (for --source socrata).")
    args = ap.parse_args()

    records = fetch_finder(args.url) if args.source == "finder" else fetch_socrata(args.dataset)

    if not records:
        sys.exit("No records returned. Check the URL / dataset id, and the JSON shape "
                 "(see extract_list()).")

    print(f"Fetched {len(records)} records.")
    with open(OUT_RAW, "w", encoding="utf-8") as f:
        json.dump(records, f, indent=2)
    print(f"  raw     : -> {OUT_RAW}")
    write_csv(records, OUT_CSV)
    write_geojson(records, OUT_GEOJSON)


if __name__ == "__main__":
    main()
