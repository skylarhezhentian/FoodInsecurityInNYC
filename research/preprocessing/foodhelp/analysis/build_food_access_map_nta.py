"""
Food access bivariate map — v2, NTA geography, FOOD-INSECURITY-based need.

Improvements over the CD/SNAP version (build_food_access_map.py):
  * NEED   = modeled food-insecurity rate (HRA Neighborhood Prioritization 2025),
             the direct measure of need — not SNAP enrollment (a participation proxy
             that undercounts immigrant neighborhoods and is partly circular w/ access).
  * GEOG   = NTA (197 residential neighborhoods) instead of CD (59) — finer grain.
  * ACCESS = provider open-hours per 10,000 FOOD-INSECURE residents (HRA's own framing),
             so supply is weighted by the size of the population that actually needs it.

Inputs (all already downloaded):
  ../food_help_programs.geojson                                  providers + hours
  data/nta_2020.geojson                                          197 residential NTAs (9nt8-h7nd)
  ../council_data/input/Neighborhood Prioritization Map 2025.csv food-insecurity rate by NTA
  ../council_data/input/nyc_decennialcensusdata_2010_2020_change.xlsx  2020 pop by NTA (Pop_20)

Outputs (./output):
  food_access_maps_nta.png   3-panel: need / access / bivariate
  nta_summary.csv            per-NTA scores
"""

from pathlib import Path
import pandas as pd
import geopandas as gpd
import matplotlib.pyplot as plt
from matplotlib.ticker import PercentFormatter

HERE = Path(__file__).parent
DATA = HERE / "data"
OUT  = HERE / "output"; OUT.mkdir(exist_ok=True)
ROOT = HERE.parent
COUNCIL = ROOT / "council_data" / "input"
PROVIDERS = ROOT / "food_help_programs.geojson"

# ---------- 1. NTA boundaries (residential only) ----------
nta = gpd.read_file(DATA / "nta_2020.geojson")
nta = nta[nta["ntatype"] == "0"][["nta2020", "ntaname", "boroname", "geometry"]].to_crs(2263)

# ---------- 2. Food-insecurity rate (NEED) ----------
fi = pd.read_csv(COUNCIL / "Neighborhood Prioritization Map 2025.csv", encoding="utf-8-sig")
fi = fi[["NTA", "Food.Insecure.Percentage"]].dropna().rename(columns={"NTA": "nta2020"})
fi["fi_rate"] = pd.to_numeric(fi["Food.Insecure.Percentage"].str.replace("%", "", regex=False)) / 100

# ---------- 3. 2020 population by NTA ----------
pop = pd.read_excel(COUNCIL / "nyc_decennialcensusdata_2010_2020_change.xlsx",
                    sheet_name="2010, 2020, and Change", header=3)
pop = (pop[pop["GeoType"] == "NTA2020"][["GeoID", "Pop_20"]]
       .rename(columns={"GeoID": "nta2020", "Pop_20": "pop_2020"}))
pop["pop_2020"] = pd.to_numeric(pop["pop_2020"])

# ---------- 4. Providers -> weekly open hours ----------
prov = gpd.read_file(PROVIDERS).to_crs(2263)

def to_hours(s):
    if not s or pd.isna(s):
        return None
    try:
        t = pd.to_datetime(s, format="%I:%M %p")
        return t.hour + t.minute / 60
    except Exception:
        return None

DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
def weekly_hours(r):
    tot = 0.0
    for svc in ("fp", "sk"):
        for d in DAYS:
            for w in (1, 2, 3):
                o = to_hours(r.get(f"{svc}_{d}_open{w}"))
                c = to_hours(r.get(f"{svc}_{d}_close{w}"))
                if o is not None and c is not None and c > o:
                    tot += c - o
    return tot

prov["hours_per_week"] = prov.apply(weekly_hours, axis=1)

# ---------- 5. Spatial join providers -> NTA ----------
pj = gpd.sjoin(prov[["geometry", "hours_per_week", "program"]],
               nta[["nta2020", "geometry"]], how="left", predicate="within")
by_nta = pj.groupby("nta2020").agg(
    provider_count=("program", "count"),
    total_hours=("hours_per_week", "sum"),
).reset_index()

# ---------- 6. Assemble ----------
df = (nta.merge(fi[["nta2020", "fi_rate"]], on="nta2020", how="inner")
          .merge(pop, on="nta2020", how="left"))
df = df.merge(by_nta, on="nta2020", how="left")
df["provider_count"] = df["provider_count"].fillna(0).astype(int)
df["total_hours"] = df["total_hours"].fillna(0.0)

# NEED population that actually needs help, and the council's access metric
df["fi_pop"] = df["fi_rate"] * df["pop_2020"]
df["access_per10k_fi"] = df["total_hours"] / (df["fi_pop"] / 10_000)   # hrs/wk per 10k FI residents
df.loc[df["fi_pop"] <= 0, "access_per10k_fi"] = pd.NA

# ---------- 7. Tercile classify ----------
def tercile(s):
    return pd.qcut(s.rank(method="first"), 3, labels=[0, 1, 2]).astype(int)

df["need_t"]   = tercile(df["fi_rate"])
df["access_t"] = tercile(df["access_per10k_fi"].fillna(0))

PALETTE = [
    ["#e8e8e8", "#ace4e4", "#5ac8c8"],
    ["#dfb0d6", "#a5add3", "#5698b9"],
    ["#be64ac", "#8c62aa", "#3b4994"],
]
df["bivar_color"] = df.apply(lambda r: PALETTE[r["need_t"]][r["access_t"]], axis=1)

# ---------- 8. Plot ----------
dfw = df.to_crs(4326)
prov_w = prov.to_crs(4326)

# --- Figure 1: NEED + ACCESS (two univariate choropleths, one file) ---
fig1, ax = plt.subplots(1, 2, figsize=(18, 10))
fig1.suptitle("NYC Food Access by NTA — univariate views  •  "
              f"food-insecurity rate (Mayor's Office of Food Policy 2025)  •  {len(prov)} providers",
              fontsize=13, y=0.95)

dfw.plot(column="fi_rate", cmap="Reds", legend=True, ax=ax[0], edgecolor="white", linewidth=0.3,
         legend_kwds={"label": "food-insecurity rate", "shrink": 0.6,
                      "format": PercentFormatter(xmax=1.0, decimals=0)})
ax[0].set_title("NEED — food-insecurity rate"); ax[0].set_axis_off()

dfw.plot(column="access_per10k_fi", cmap="Greens", legend=True, ax=ax[1], edgecolor="white",
         linewidth=0.3, missing_kwds={"color": "#f0f0f0"},
         legend_kwds={"label": "provider hrs/wk per 10k food-insecure residents", "shrink": 0.6})
prov_w.plot(ax=ax[1], color="black", markersize=3, alpha=0.35)
ax[1].set_title("ACCESS — provider hours per 10k food-insecure residents"); ax[1].set_axis_off()

plt.savefig(OUT / "need_access_maps_nta.png", dpi=150, bbox_inches="tight")
print("wrote", OUT / "need_access_maps_nta.png")
plt.close(fig1)

# --- Figure 2: BIVARIATE need x access (separate file) ---
fig2, ax2 = plt.subplots(1, 1, figsize=(11, 11))
ax2.set_title("NYC Food Access — bivariate: need × access\n"
              "purple = high need + low access = priority", fontsize=13)
dfw.plot(color=df["bivar_color"].tolist(), ax=ax2, edgecolor="white", linewidth=0.3)
ax2.set_axis_off()

lax = fig2.add_axes([0.70, 0.12, 0.18, 0.18])
for i in range(3):
    for j in range(3):
        lax.add_patch(plt.Rectangle((j, i), 1, 1, color=PALETTE[i][j]))
lax.set_xlim(0, 3); lax.set_ylim(0, 3)
lax.set_xticks([0.5, 1.5, 2.5]); lax.set_xticklabels(["low", "mid", "high"], fontsize=8)
lax.set_yticks([0.5, 1.5, 2.5]); lax.set_yticklabels(["low", "mid", "high"], fontsize=8)
lax.set_xlabel("access →", fontsize=9); lax.set_ylabel("need →", fontsize=9)
lax.tick_params(length=0)
for s in lax.spines.values():
    s.set_visible(False)

plt.savefig(OUT / "bivariate_map_nta.png", dpi=150, bbox_inches="tight")
print("wrote", OUT / "bivariate_map_nta.png")
plt.close(fig2)

# ---------- 9. Numbers + priority list ----------
cols = ["nta2020", "ntaname", "boroname", "fi_rate", "pop_2020", "fi_pop",
        "provider_count", "total_hours", "access_per10k_fi", "need_t", "access_t"]
df[cols].sort_values("fi_rate", ascending=False).to_csv(OUT / "nta_summary.csv", index=False)
print("wrote", OUT / "nta_summary.csv")

prio = df[(df["need_t"] == 2) & (df["access_t"] == 0)].sort_values("fi_rate", ascending=False)
print(f"\n=== Priority NTAs: highest food insecurity + lowest access ({len(prio)} of {len(df)}) ===")
show = prio.copy()
show["fi_rate"] = (show["fi_rate"] * 100).round(1).astype(str) + "%"
show["fi_pop"] = show["fi_pop"].round(0).astype(int)
show["access_per10k_fi"] = show["access_per10k_fi"].round(1)
print(show[["nta2020", "ntaname", "boroname", "fi_rate", "fi_pop",
            "provider_count", "total_hours", "access_per10k_fi"]].to_string(index=False))
