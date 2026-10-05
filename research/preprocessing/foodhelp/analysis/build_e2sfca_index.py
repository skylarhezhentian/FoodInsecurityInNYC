"""
E2SFCA access score + re-derived equity index (NTA).

Replaces the crude point-in-polygon access (build_food_access_map_nta.py) with a
Gaussian-decay Enhanced Two-Step Floating Catchment Area model (Luo & Qi 2009;
Dai 2010), then builds a continuous, partially non-compensatory equity index.

KEY DESIGN CHOICE — access is need-INDEPENDENT:
  demand weight = TOTAL population (not food-insecure population). This avoids the
  double-counting flaw in the old pipeline, where the food-insecurity rate appeared
  in BOTH the need axis and the access denominator. Need re-enters only in the index.

Demand points : 2020 census tract centroids (2,325), D_i = 2020 population
Supply points : 528 providers, S_j = weekly open hours
Catchment     : 1 mile (1609 m) walk, continuous Gaussian decay
Aggregation   : tract access -> NTA (population-weighted mean), to combine with NTA need

Outputs (./output):
  access_e2sfca_nta.png      E2SFCA access surface + providers
  equity_index_nta.png       continuous equity index (the headline)
  bivariate_e2sfca_nta.png   need x access bivariate, rebuilt on E2SFCA access
  nta_equity_index.csv       per-NTA scores + priority ranking
"""

from pathlib import Path
import numpy as np
import pandas as pd
import geopandas as gpd
import matplotlib.pyplot as plt
from matplotlib.ticker import PercentFormatter

HERE = Path(__file__).parent
DATA = HERE / "data"
OUT  = HERE / "output"; OUT.mkdir(exist_ok=True)
ROOT = HERE.parent
COUNCIL = ROOT / "council_data" / "input"

D0 = 1609.0     # catchment radius, metres (1 mile walking)
SIGMA = D0 / 3  # Gaussian bandwidth

# ============================================================ load supply
prov = gpd.read_file(ROOT / "food_help_programs.geojson").to_crs(4326)

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

prov["S"] = prov.apply(weekly_hours, axis=1)
prov = prov[prov["S"] > 0].copy()
sup_lon = prov.geometry.x.to_numpy()
sup_lat = prov.geometry.y.to_numpy()
S = prov["S"].to_numpy()                                    # supply capacity (hours)

# ============================================================ load demand (tracts)
tr = gpd.read_file(DATA / "tracts_2020.geojson")[["geoid", "nta2020", "geometry"]].to_crs(4326)
cen = tr.geometry.representative_point()
tr["lon"], tr["lat"] = cen.x.to_numpy(), cen.y.to_numpy()

pop = pd.read_excel(COUNCIL / "nyc_decennialcensusdata_2010_2020_change.xlsx",
                    sheet_name="2010, 2020, and Change", header=3)
pop = pop[pop["GeoType"] == "CT2020"][["GeoID", "Pop_20"]].copy()
pop["geoid"] = pop["GeoID"].astype("int64").astype(str)
pop["Pop_20"] = pd.to_numeric(pop["Pop_20"])
tr = tr.merge(pop[["geoid", "Pop_20"]], on="geoid", how="left")
tr["Pop_20"] = tr["Pop_20"].fillna(0.0)

dem_lon = tr["lon"].to_numpy()
dem_lat = tr["lat"].to_numpy()
D = tr["Pop_20"].to_numpy()                                 # demand weight = TOTAL population

# ============================================================ distance + decay
def haversine_m(lat1, lon1, lat2, lon2):
    """Pairwise great-circle metres between demand (rows) and supply (cols)."""
    R = 6_371_000.0
    p1, p2 = np.radians(lat1)[:, None], np.radians(lat2)[None, :]
    dphi = p2 - p1
    dlmb = np.radians(lon2)[None, :] - np.radians(lon1)[:, None]
    a = np.sin(dphi / 2) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(dlmb / 2) ** 2
    return 2 * R * np.arcsin(np.sqrt(a))

dist = haversine_m(dem_lat, dem_lon, sup_lat, sup_lon)      # (nTract, nProv) metres

# continuous Gaussian decay, truncated at D0 (Kwan 1998 / Dai 2010), W(0)=1, W(D0)=0
g0 = np.exp(-0.5 * (D0 / SIGMA) ** 2)
W = (np.exp(-0.5 * (dist / SIGMA) ** 2) - g0) / (1 - g0)
W[dist > D0] = 0.0                                          # outside catchment

# ============================================================ E2SFCA two steps
# Step 1 — provider-to-population ratio:  R_j = S_j / sum_i D_i * W_ij
denom = W.T @ D                                             # (nProv,)
Rj = np.divide(S, denom, out=np.zeros_like(S), where=denom > 0)

# Step 2 — accessibility at each tract:   A_i = sum_j R_j * W_ij
A_tract = W @ Rj                                            # (nTract,) hours per person
tr["access"] = A_tract * 10_000                             # -> per 10,000 residents

# ============================================================ aggregate tract -> NTA
def pop_wmean(g):
    w = g["Pop_20"].to_numpy()
    return np.average(g["access"].to_numpy(), weights=w) if w.sum() > 0 else 0.0

nta_acc = (tr.groupby("nta2020").apply(pop_wmean, include_groups=False)
             .rename("access_e2sfca").reset_index())
nta_pop = tr.groupby("nta2020")["Pop_20"].sum().rename("pop_2020").reset_index()

# ============================================================ need + index
nta = gpd.read_file(DATA / "nta_2020.geojson")
nta = nta[nta["ntatype"] == "0"][["nta2020", "ntaname", "boroname", "geometry"]]

fi = pd.read_csv(COUNCIL / "Neighborhood Prioritization Map 2025.csv", encoding="utf-8-sig")
fi = fi[["NTA", "Food.Insecure.Percentage"]].dropna().rename(columns={"NTA": "nta2020"})
fi["fi_rate"] = pd.to_numeric(fi["Food.Insecure.Percentage"].str.replace("%", "", regex=False)) / 100

df = (nta.merge(fi[["nta2020", "fi_rate"]], on="nta2020", how="inner")
          .merge(nta_acc, on="nta2020", how="left")
          .merge(nta_pop, on="nta2020", how="left"))
df["access_e2sfca"] = df["access_e2sfca"].fillna(0.0)

# percentile ranks (robust to skew), then geometric-mean equity index
df["need_pct"]   = df["fi_rate"].rank(pct=True)
df["access_pct"] = df["access_e2sfca"].rank(pct=True)
#   E_i = sqrt( need_pct * (1 - access_pct) )   -- partially NON-compensatory:
#   high need OR abundant access alone cannot make a neighbourhood high-priority;
#   it must be high need AND low access. Range [0,1].
df["equity_index"] = np.sqrt(df["need_pct"] * (1 - df["access_pct"]))
df["rank"] = df["equity_index"].rank(ascending=False, method="min").astype(int)

# terciles for the bivariate view (kept for continuity with prior figure)
def tercile(s):
    return pd.qcut(s.rank(method="first"), 3, labels=[0, 1, 2]).astype(int)
df["need_t"], df["access_t"] = tercile(df["fi_rate"]), tercile(df["access_e2sfca"])
PALETTE = [["#e8e8e8", "#ace4e4", "#5ac8c8"],
           ["#dfb0d6", "#a5add3", "#5698b9"],
           ["#be64ac", "#8c62aa", "#3b4994"]]
df["bivar_color"] = df.apply(lambda r: PALETTE[r["need_t"]][r["access_t"]], axis=1)

# ============================================================ figures
dfw, prov_w = df.to_crs(4326), prov.to_crs(4326)

# (1) E2SFCA access surface
fig, ax = plt.subplots(figsize=(11, 11))
ax.set_title(f"NYC food access — E2SFCA score (1-mi walk, Gaussian decay)\n"
             f"provider hrs/wk per 10k residents, spatially smoothed", fontsize=13)
dfw.plot(column="access_e2sfca", cmap="Greens", legend=True, ax=ax, edgecolor="white",
         linewidth=0.3, legend_kwds={"label": "E2SFCA access", "shrink": 0.6})
prov_w.plot(ax=ax, color="black", markersize=3, alpha=0.35)
ax.set_axis_off()
plt.savefig(OUT / "access_e2sfca_nta.png", dpi=150, bbox_inches="tight"); plt.close(fig)
print("wrote", OUT / "access_e2sfca_nta.png")

# (2) equity index — the headline
fig, ax = plt.subplots(figsize=(11, 11))
ax.set_title("NYC food-access EQUITY INDEX\n"
             "E = √(need_pct · (1 − access_pct))  —  dark = highest priority", fontsize=13)
dfw.plot(column="equity_index", cmap="magma_r", legend=True, ax=ax, edgecolor="white",
         linewidth=0.3, legend_kwds={"label": "equity index (0–1)", "shrink": 0.6})
# label the top-8 priority neighbourhoods
for _, r in df.nlargest(8, "equity_index").to_crs(4326).iterrows():
    c = r.geometry.representative_point()
    ax.annotate(r["ntaname"][:24], (c.x, c.y), fontsize=6, ha="center",
                color="white", weight="bold")
ax.set_axis_off()
plt.savefig(OUT / "equity_index_nta.png", dpi=150, bbox_inches="tight"); plt.close(fig)
print("wrote", OUT / "equity_index_nta.png")

# (3) bivariate rebuilt on E2SFCA access
fig, ax = plt.subplots(figsize=(11, 11))
ax.set_title("NYC food access — bivariate need × E2SFCA access\n"
             "purple = high need + low access", fontsize=13)
dfw.plot(color=df["bivar_color"].tolist(), ax=ax, edgecolor="white", linewidth=0.3)
ax.set_axis_off()
lax = fig.add_axes([0.70, 0.12, 0.18, 0.18])
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
plt.savefig(OUT / "bivariate_e2sfca_nta.png", dpi=150, bbox_inches="tight"); plt.close(fig)
print("wrote", OUT / "bivariate_e2sfca_nta.png")

# ============================================================ table
out = df.drop(columns=["geometry", "bivar_color"]).sort_values("rank")
out.to_csv(OUT / "nta_equity_index.csv", index=False)
print("wrote", OUT / "nta_equity_index.csv")

print(f"\nproviders used: {len(prov)} (hours>0) | tracts: {len(tr)} | NTAs: {len(df)}")
print(f"access score range: {df.access_e2sfca.min():.2f}–{df.access_e2sfca.max():.2f} | "
      f"zero-access NTAs: {(df.access_e2sfca==0).sum()}")
print("\n=== Top 15 priority neighbourhoods (by equity index) ===")
top = df.nlargest(15, "equity_index").copy()
top["FI%"] = (top["fi_rate"] * 100).round(1)
top["access"] = top["access_e2sfca"].round(2)
top["E"] = top["equity_index"].round(3)
print(top[["rank", "ntaname", "boroname", "FI%", "access", "E"]].to_string(index=False))
