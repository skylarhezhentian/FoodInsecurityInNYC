"""
Food access bivariate map: NYC community districts colored by SNAP need × provider access.

Inputs (already downloaded):
  ../food_help_programs.geojson     - 528 pantries/soup kitchens with per-day hours
  data/community_districts.geojson  - 71 CD polygons (NYC Open Data 5crt-au7u)
  data/snap_cd_all_months.json      - SNAP recipients per CD per month (5awp-wfkt)
  data/cd_population.json           - CD population 1970-2010 (xi7c-iiu2)

Outputs (written to ./output):
  food_access_maps.png  - 3-panel figure: need / access / bivariate
  cd_summary.csv        - per-CD scores
"""

from pathlib import Path
import pandas as pd
import geopandas as gpd
import matplotlib.pyplot as plt
from matplotlib.patches import Patch

HERE = Path(__file__).parent
DATA = HERE / "data"
OUT  = HERE / "output"; OUT.mkdir(exist_ok=True)
PROVIDERS = HERE.parent / "food_help_programs.geojson"

# ---------- 1. Load polygons ----------
cds = gpd.read_file(DATA / "community_districts.geojson")
cds["boro_cd"] = cds["boro_cd"].astype(str)
cds = cds.to_crs(2263)  # NY State Plane (feet) — accurate area / centroid ops

# ---------- 2. Load + clean SNAP, latest month only ----------
snap = pd.read_json(DATA / "snap_cd_all_months.json")
snap["month"] = pd.to_datetime(snap["month"])
snap_latest = snap[snap["month"] == snap["month"].max()].copy()
# SNAP CD codes are "M03" "B05" "K07" "Q06" "S03"; boundary file uses "103" "205" "307" "406" "503"
PREFIX = {"M": "1", "B": "2", "K": "3", "Q": "4", "S": "5"}
snap_latest["boro_cd"] = snap_latest["community_district"].apply(
    lambda c: PREFIX[c[0]] + c[1:].zfill(2)
)
snap_latest["snap_recipients"] = pd.to_numeric(snap_latest["bc_snap_recipients"])
snap_month = snap_latest["month"].iloc[0].strftime("%Y-%m")

# ---------- 3. Load CD population (2010 census, the only series in this source) ----------
pop = pd.read_json(DATA / "cd_population.json")
BORO = {"Manhattan": "1", "Bronx": "2", "Brooklyn": "3", "Queens": "4", "Staten Island": "5"}
pop["boro_cd"] = pop["borough"].map(BORO) + pop["cd_number"].astype(int).map("{:02d}".format)
pop["pop_2010"] = pd.to_numeric(pop["_2010_population"])

# ---------- 4. Load providers, parse open-hours-per-week ----------
prov = gpd.read_file(PROVIDERS).to_crs(2263)

def hrs(s):
    if not s or pd.isna(s):
        return None
    try:
        t = pd.to_datetime(s, format="%I:%M %p")
        return t.hour + t.minute / 60
    except Exception:
        return None

DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
WINS = [1, 2, 3]
def weekly_hours(row):
    total = 0.0
    for svc in ("fp", "sk"):
        for d in DAYS:
            for w in WINS:
                o = hrs(row.get(f"{svc}_{d}_open{w}"))
                c = hrs(row.get(f"{svc}_{d}_close{w}"))
                if o is not None and c is not None and c > o:
                    total += c - o
    return total

prov["hours_per_week"] = prov.apply(weekly_hours, axis=1)

# ---------- 5. Spatial join providers -> CDs ----------
prov_cd = gpd.sjoin(
    prov[["geometry", "hours_per_week", "program"]],
    cds[["boro_cd", "geometry"]],
    how="left", predicate="within",
)

by_cd = prov_cd.groupby("boro_cd").agg(
    provider_count=("program", "count"),
    total_hours=("hours_per_week", "sum"),
).reset_index()

# ---------- 6. Merge everything ----------
df = (
    cds
    .merge(snap_latest[["boro_cd", "snap_recipients"]], on="boro_cd", how="left")
    .merge(pop[["boro_cd", "pop_2010"]], on="boro_cd", how="left")
    .merge(by_cd, on="boro_cd", how="left")
)
df["provider_count"] = df["provider_count"].fillna(0).astype(int)
df["total_hours"] = df["total_hours"].fillna(0.0)

# Residential CDs only (drop airports/parks/cemeteries — they have no SNAP / no pop)
df = df.dropna(subset=["snap_recipients", "pop_2010"]).copy()
df["snap_rate"] = df["snap_recipients"] / df["pop_2010"]                  # NEED axis
df["access_score"] = df["total_hours"] / (df["pop_2010"] / 1000)          # ACCESS axis (hrs/wk per 1k residents)

# ---------- 7. Tercile-classify each axis for the bivariate map ----------
def tercile(s):
    return pd.qcut(s.rank(method="first"), 3, labels=[0, 1, 2]).astype(int)

df["need_t"]   = tercile(df["snap_rate"])
df["access_t"] = tercile(df["access_score"])

# 3x3 palette: rows = need (low->high), cols = access (low->high).
# The eye-catching cell is top-left: HIGH NEED + LOW ACCESS (deep purple).
PALETTE = [
    ["#e8e8e8", "#ace4e4", "#5ac8c8"],  # low need
    ["#dfb0d6", "#a5add3", "#5698b9"],  # mid need
    ["#be64ac", "#8c62aa", "#3b4994"],  # high need
]
df["bivar_color"] = df.apply(lambda r: PALETTE[r["need_t"]][r["access_t"]], axis=1)

# ---------- 8. Plot ----------
df_wgs = df.to_crs(4326)
prov_wgs = prov.to_crs(4326)

fig, axes = plt.subplots(1, 3, figsize=(24, 10))
fig.suptitle(
    f"NYC Food Access — by Community District  •  SNAP data: {snap_month}  •  Providers: {len(prov)} pantries+kitchens",
    fontsize=14, y=0.97,
)

# Panel 1: NEED
df_wgs.plot(column="snap_rate", cmap="Reds", legend=True, ax=axes[0],
            edgecolor="white", linewidth=0.4,
            legend_kwds={"label": "SNAP recipients / 2010 pop", "shrink": 0.6})
axes[0].set_title("NEED — SNAP enrollment rate")
axes[0].set_axis_off()

# Panel 2: ACCESS
df_wgs.plot(column="access_score", cmap="Greens", legend=True, ax=axes[1],
            edgecolor="white", linewidth=0.4,
            legend_kwds={"label": "weekly provider hours per 1,000 residents", "shrink": 0.6})
prov_wgs.plot(ax=axes[1], color="black", markersize=3, alpha=0.4)
axes[1].set_title("ACCESS — provider open-hours density (dots = providers)")
axes[1].set_axis_off()

# Panel 3: BIVARIATE
df_wgs.plot(color=df["bivar_color"].tolist(), ax=axes[2], edgecolor="white", linewidth=0.4)
axes[2].set_title("BIVARIATE — need × access\n(purple = high need + low access = priority)")
axes[2].set_axis_off()

# Inset legend for bivariate
legend_ax = fig.add_axes([0.84, 0.18, 0.10, 0.10])
for i in range(3):
    for j in range(3):
        legend_ax.add_patch(plt.Rectangle((j, i), 1, 1, color=PALETTE[i][j]))
legend_ax.set_xlim(0, 3); legend_ax.set_ylim(0, 3)
legend_ax.set_xticks([0.5, 1.5, 2.5]); legend_ax.set_xticklabels(["low", "mid", "high"], fontsize=7)
legend_ax.set_yticks([0.5, 1.5, 2.5]); legend_ax.set_yticklabels(["low", "mid", "high"], fontsize=7)
legend_ax.set_xlabel("access →", fontsize=8); legend_ax.set_ylabel("need →", fontsize=8)
legend_ax.tick_params(length=0)
for s in legend_ax.spines.values():
    s.set_visible(False)

plt.savefig(OUT / "food_access_maps.png", dpi=150, bbox_inches="tight")
print(f"wrote {OUT/'food_access_maps.png'}")

# ---------- 9. Save the underlying numbers + print priority list ----------
cols = ["boro_cd", "snap_recipients", "pop_2010", "snap_rate",
        "provider_count", "total_hours", "access_score", "need_t", "access_t"]
df[cols].sort_values("snap_rate", ascending=False).to_csv(OUT / "cd_summary.csv", index=False)
print(f"wrote {OUT/'cd_summary.csv'}")

priority = df[(df["need_t"] == 2) & (df["access_t"] == 0)].sort_values("snap_rate", ascending=False)
print(f"\n=== High-need + low-access CDs ({len(priority)} of {len(df)}) ===")
print(priority[["boro_cd", "snap_recipients", "pop_2010", "snap_rate",
                "provider_count", "total_hours", "access_score"]].to_string(index=False))
