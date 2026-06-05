#!/usr/bin/env python3
"""
build_instance.py — assemble a food-rescue routing instance from:
  - cd_summary.csv      (your 59 community districts: need, access, providers, terciles)
  - donor_classes.csv   (donor category -> product/perishability/supply parameters)

Output: instance.json with depot + donor nodes (pickups) + recipient nodes (deliveries),
each carrying the attributes the model needs (equity weight w_r, demand/supply lbs,
cold-chain flag, shelf life, time window).

GEO IS SYNTHETIC for everything except the real anchors (City Harvest depot, Hunts Point,
GrowNYC markets). Recipients are scattered inside their borough from your CD counts.
Swap in real coordinates later with --providers (a CSV with lon,lat[,w][,demand_lbs]).

Usage:
  python build_instance.py                       # defaults
  python build_instance.py --donor-scale 0.25    # ~400 donors instead of ~1600
  python build_instance.py --providers my528.csv # use real recipient points
"""
import argparse, json, math
import numpy as np
import pandas as pd

# --- real geographic anchors (approx lat, lon) ---
DEPOT = (40.6447, -74.0117)                      # 150 52nd St, Brooklyn (Sunset Park)
HUNTS_POINT = (40.812, -73.881)                  # produce market gateway
GREENMARKETS = [(40.7359,-73.9911),(40.6726,-73.9701),(40.8470,-73.9390),
                (40.7836,-73.9776),(40.7720,-73.9560),(40.6912,-73.9740)]

# borough bounding boxes (lat_lo, lat_hi, lon_lo, lon_hi); key = first digit of boro_cd
BORO_BOX = {1:(40.700,40.875,-74.018,-73.910),   # Manhattan
            2:(40.790,40.910,-73.930,-73.785),   # Bronx
            3:(40.570,40.740,-74.040,-73.860),   # Brooklyn
            4:(40.540,40.800,-73.962,-73.700),   # Queens
            5:(40.500,40.650,-74.260,-74.050)}   # Staten Island
# weighting of "citywide" donors across boroughs, and skewed variants
W_CITY    = {1:.34,3:.27,4:.24,2:.12,5:.03}
W_CITY_MH = {1:.55,3:.22,4:.13,2:.08,5:.02}
W_CITY_QN = {4:.40,3:.30,2:.15,1:.12,5:.03}

# default donor counts per category (sum ~1,600, mirroring City Harvest's mix)
COUNTS = {"Restaurants":300,"Quickservice Restaurants":250,"Bakery":120,"Supermarkets":200,
          "Hotels":60,"Caterer":50,"Greenmarket":30,"Hunts Point":40,"Wholesale":60,
          "Wholesale Packaged":40,"Farms":80,"Manufacturers":60,"Corporate":40,
          "Nonprofit & Government Agencies":30,"Religious Institutions":80,"Special Events":20}

def sample_box(rng, box, n):
    la0,la1,lo0,lo1 = box
    return np.column_stack([rng.uniform(la0,la1,n), rng.uniform(lo0,lo1,n)])

def weighted_boros(rng, weights, n):
    keys=list(weights); p=np.array([weights[k] for k in keys]); p=p/p.sum()
    return rng.choice(keys, size=n, p=p)

def place_donors(rng, cat, hint, n):
    pts=[]
    if hint=="huntspoint":
        c=HUNTS_POINT
        pts=np.column_stack([rng.normal(c[0],0.010,n), rng.normal(c[1],0.012,n)])
    elif hint=="greenmarket":
        idx=rng.integers(0,len(GREENMARKETS),n)
        base=np.array([GREENMARKETS[i] for i in idx])
        pts=base+rng.normal(0,0.004,(n,2))
    else:
        wmap={"citywide":W_CITY,"citywide_mh":W_CITY_MH,"citywide_qns":W_CITY_QN}[hint]
        bs=weighted_boros(rng,wmap,n)
        pts=np.array([sample_box(rng,BORO_BOX[int(b)],1)[0] for b in bs])
    return pts

def lognorm(rng, mean, cv, n):
    mean=max(mean,1.0); sigma=math.sqrt(math.log(1+cv*cv)); mu=math.log(mean)-sigma*sigma/2
    return rng.lognormal(mu,sigma,n)

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--cd",default="cd_summary.csv")
    ap.add_argument("--donors",default="donor_classes.csv")
    ap.add_argument("--providers",default=None,help="optional real recipient CSV: lon,lat[,w][,demand_lbs][,boro]")
    ap.add_argument("--donor-scale",type=float,default=1.0)
    ap.add_argument("--out",default="instance.json")
    ap.add_argument("--seed",type=int,default=7)
    a=ap.parse_args()
    rng=np.random.default_rng(a.seed)

    dc=pd.read_csv(a.donors).set_index("category")

    # ---------- donors ----------
    donors=[]; k=1
    for cat,row in dc.iterrows():
        n=int(round(COUNTS.get(cat,20)*a.donor_scale))
        if n<=0: continue
        pts=place_donors(rng,cat,row["geo_hint"],n)
        sup=lognorm(rng,row["supply_mean_lbs"],row["supply_cv"],n)
        sl =rng.uniform(row["shelf_life_h_low"],row["shelf_life_h_high"],n)
        for i in range(n):
            donors.append({"id":f"D{k:04d}","kind":"donor","category":cat,
                "product_class":row["product_class"],"cold_chain":int(row["cold_chain"]),
                "lat":round(float(pts[i][0]),6),"lon":round(float(pts[i][1]),6),
                "supply_lbs":round(float(sup[i]),1),"supply_cv":float(row["supply_cv"]),
                "avail_prob":float(row["avail_prob"]),"shelf_life_h":round(float(sl[i]),1),
                "tw_open":0,"tw_close":420})
            k+=1

    # ---------- recipients ----------
    recips=[]; r=1
    if a.providers:
        pv=pd.read_csv(a.providers)
        for _,row in pv.iterrows():
            recips.append({"id":f"R{r:04d}","kind":"recipient","category":"provider",
                "lat":round(float(row["lat"]),6),"lon":round(float(row["lon"]),6),
                "w":float(row.get("w",1.0)),"demand_lbs":float(row.get("demand_lbs",150)),
                "boro":int(row.get("boro",0)),
                "tw_open":int(row.get("tw_open",60)),"tw_close":int(row.get("tw_close",360))})
            r+=1
    else:
        cd=pd.read_csv(a.cd)
        for _,row in cd.iterrows():
            boro=int(str(int(row["boro_cd"]))[0]); n=int(row["provider_count"])
            if n<=0: continue
            pts=sample_box(rng,BORO_BOX[boro],n)
            w=(int(row["need_t"])+1)/(int(row["access_t"])+1)
            per=row["snap_recipients"]/max(n,1)
            dem=float(np.clip(round(per*0.04),40,500))
            for i in range(n):
                s=int(rng.choice([0,60,120,180]))
                recips.append({"id":f"R{r:04d}","kind":"recipient","category":"provider",
                    "boro_cd":int(row["boro_cd"]),"boro":boro,
                    "lat":round(float(pts[i][0]),6),"lon":round(float(pts[i][1]),6),
                    "w":round(float(w),4),"need_t":int(row["need_t"]),"access_t":int(row["access_t"]),
                    "demand_lbs":dem,"tw_open":s,"tw_close":s+240})
                r+=1

    inst={"meta":{"depot_desc":"City Harvest, 150 52nd St, Brooklyn","note":"synthetic geo except depot/Hunts Point/Greenmarkets",
                  "n_donors":len(donors),"n_recipients":len(recips),"time_origin":"06:00 (minutes)"},
          "depot":{"lat":DEPOT[0],"lon":DEPOT[1]},
          "params":{"vehicle_capacity_lbs":4000,"n_vehicles":6,"speed_kmh":20,
                    "service_min":12,"horizon_min":540},
          "donors":donors,"recipients":recips}
    json.dump(inst,open(a.out,"w"))
    print(f"wrote {a.out}: {len(donors)} donors, {len(recips)} recipients")
    # quick summaries
    import collections
    pc=collections.Counter(d["product_class"] for d in donors)
    print("donor product mix:", dict(pc))
    wt=collections.Counter((rr["need_t"],rr["access_t"]) for rr in recips if "need_t" in rr)
    print("priority (need=2,access=0) recipients:", wt.get((2,0),0), "of", len(recips))

if __name__=="__main__":
    main()
