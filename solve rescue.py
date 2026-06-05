#!/usr/bin/env python3
"""
solve_rescue.py — a first deterministic solve of the food-rescue instance.

Model (v0): one commodity (total lbs). Vehicles leave the depot, PICK UP at donors
(load +) and DELIVER to recipients (load -), within time windows and capacity.
Equity enters as a SKIP PENALTY: serving recipient r is worth penalty = BASE * w_r,
so high-need / low-access (high-w) recipients are expensive to leave unserved.

Two modes are solved on the SAME subset:
  uniform  -> every recipient has equal penalty  (cost-driven coverage)
  equity   -> penalty proportional to w_r         (priority-driven coverage)
so you can see equity weighting change WHICH districts get served.

Usage:  python solve_rescue.py --boro 3 --max-recip 30 --max-donors 16 --vehicles 3
Boroughs: 1=Manhattan 2=Bronx 3=Brooklyn 4=Queens 5=Staten Island
"""
import argparse, json, math
import numpy as np
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from ortools.constraint_solver import pywrapcp, routing_enums_pb2

def hav(a,b):
    R=6371.0; la1,lo1=map(math.radians,a); la2,lo2=map(math.radians,b)
    dla=la2-la1; dlo=lo2-lo1
    h=math.sin(dla/2)**2+math.cos(la1)*math.cos(la2)*math.sin(dlo/2)**2
    return 2*R*math.asin(math.sqrt(h))

def build_subset(inst, boro, max_recip, max_donors, seed):
    rng=np.random.default_rng(seed)
    rec=[r for r in inst["recipients"] if r.get("boro")==boro]
    prio=[r for r in rec if r.get("need_t")==2 and r.get("access_t")==0]
    rest=[r for r in rec if r not in prio]
    rng.shuffle(rest)
    chosen=(prio+rest)[:max_recip]
    # donors: borough box members + the Hunts Point produce cluster
    la=[r["lat"] for r in inst["recipients"] if r.get("boro")==boro]
    lo=[r["lon"] for r in inst["recipients"] if r.get("boro")==boro]
    box=(min(la)-0.02,max(la)+0.02,min(lo)-0.02,max(lo)+0.02)
    near=[d for d in inst["donors"] if box[0]<=d["lat"]<=box[1] and box[2]<=d["lon"]<=box[3]]
    hp=[d for d in inst["donors"] if d["category"] in ("Hunts Point","Farms","Wholesale")]
    rng.shuffle(near); rng.shuffle(hp)
    donors=near[:max(max_donors-3,1)]+hp[:3]
    return chosen, donors

def solve(inst, recs, donors, n_veh, mode, base, tlimit):
    depot=inst["depot"]; P=inst["params"]
    nodes=[{"lat":depot["lat"],"lon":depot["lon"],"kind":"depot","dem":0,"tw":(0,P["horizon_min"])}]
    for d in donors:
        nodes.append({"lat":d["lat"],"lon":d["lon"],"kind":"donor","dem":int(min(d["supply_lbs"],P["vehicle_capacity_lbs"])),
                      "tw":(int(d["tw_open"]),int(d["tw_close"])),"ref":d})
    for r in recs:
        nodes.append({"lat":r["lat"],"lon":r["lon"],"kind":"recipient","dem":-int(r["demand_lbs"]),
                      "tw":(int(r["tw_open"]),int(r["tw_close"])),"ref":r})
    N=len(nodes); coords=[(x["lat"],x["lon"]) for x in nodes]
    spd=P["speed_kmh"]; serv=P["service_min"]
    tmat=[[int(round(hav(coords[i],coords[j])/spd*60)) for j in range(N)] for i in range(N)]

    mgr=pywrapcp.RoutingIndexManager(N,n_veh,0)
    routing=pywrapcp.RoutingModel(mgr)
    def tcb(fi,tj):
        f=mgr.IndexToNode(fi); t=mgr.IndexToNode(tj); return tmat[f][t]+(serv if nodes[f]["kind"]!="depot" else 0)
    tidx=routing.RegisterTransitCallback(tcb)
    routing.SetArcCostEvaluatorOfAllVehicles(tidx)
    routing.AddDimension(tidx,120,P["horizon_min"],True,"Time")
    tdim=routing.GetDimensionOrDie("Time")
    for nd in range(1,N):
        idx=mgr.NodeToIndex(nd); lo,hi=nodes[nd]["tw"]; tdim.CumulVar(idx).SetRange(lo,hi)
    for v in range(n_veh):
        tdim.CumulVar(routing.Start(v)).SetRange(0,P["horizon_min"])
    def dcb(fi): return nodes[mgr.IndexToNode(fi)]["dem"]
    didx=routing.RegisterUnaryTransitCallback(dcb)
    routing.AddDimensionWithVehicleCapacity(didx,0,[P["vehicle_capacity_lbs"]]*n_veh,True,"Load")

    for nd in range(1,N):
        idx=mgr.NodeToIndex(nd)
        if nodes[nd]["kind"]=="recipient":
            w=nodes[nd]["ref"]["w"]; pen=int(base*(w if mode=="equity" else 1.0))
            routing.AddDisjunction([idx],pen)
        else:
            routing.AddDisjunction([idx],0)   # donors optional, free

    sp=pywrapcp.DefaultRoutingSearchParameters()
    sp.first_solution_strategy=routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC
    sp.local_search_metaheuristic=routing_enums_pb2.LocalSearchMetaheuristic.GUIDED_LOCAL_SEARCH
    sp.time_limit.FromSeconds(tlimit)
    sol=routing.SolveWithParameters(sp)

    routes=[]; served=set(); travel=0
    if sol:
        for v in range(n_veh):
            idx=routing.Start(v); seq=[]
            while not routing.IsEnd(idx):
                seq.append(mgr.IndexToNode(idx)); nxt=sol.Value(routing.NextVar(idx))
                travel+=routing.GetArcCostForVehicle(idx,nxt,v); idx=nxt
            seq.append(mgr.IndexToNode(idx))
            if len(seq)>2: routes.append(seq)
        for v in range(n_veh):
            idx=routing.Start(v)
            while not routing.IsEnd(idx):
                nd=mgr.IndexToNode(idx)
                if nodes[nd]["kind"]=="recipient": served.add(nd)
                idx=sol.Value(routing.NextVar(idx))
    rec_nodes=[i for i in range(N) if nodes[i]["kind"]=="recipient"]
    prio_nodes=[i for i in rec_nodes if nodes[i]["ref"].get("need_t")==2 and nodes[i]["ref"].get("access_t")==0]
    lbs=sum(-nodes[i]["dem"] for i in served)
    m={"mode":mode,"routes":routes,"served":served,"nodes":nodes,
       "n_rec":len(rec_nodes),"n_served":len(served),
       "n_prio":len(prio_nodes),"n_prio_served":len([i for i in prio_nodes if i in served]),
       "lbs":lbs,"travel":int(travel),
       "w_served":round(sum(nodes[i]["ref"]["w"] for i in served),2),
       "w_total":round(sum(nodes[i]["ref"]["w"] for i in rec_nodes),2)}
    return m

def panel(ax, m, title):
    nodes=m["nodes"]; served=m["served"]
    for i,nd in enumerate(nodes):
        if nd["kind"]=="recipient":
            prio=nd["ref"].get("need_t")==2 and nd["ref"].get("access_t")==0
            on=i in served
            ax.scatter(nd["lon"],nd["lat"],s=40+nd["ref"]["w"]*55,
                       c=("#7C4DBC" if prio else "#2E8B57") if on else "#cccccc",
                       marker=("*" if prio else "o"),
                       edgecolors="#333" if on else "none", linewidths=0.6, zorder=3, alpha=0.95 if on else 0.7)
        elif nd["kind"]=="donor":
            ax.scatter(nd["lon"],nd["lat"],s=34,c="#D1495B",marker="^",alpha=0.85,zorder=2,edgecolors="none")
        else:
            ax.scatter(nd["lon"],nd["lat"],s=240,c="#12281F",marker="*",zorder=5,edgecolors="white",linewidths=1.2)
    cols=["#0E7C7B","#E08A1E","#3E6B7C","#9B59B6","#1F5C3D"]
    for k,seq in enumerate(m["routes"]):
        xs=[nodes[n]["lon"] for n in seq]; ys=[nodes[n]["lat"] for n in seq]
        ax.plot(xs,ys,c=cols[k%len(cols)],lw=1.7,alpha=0.8,zorder=1)
    ax.set_title(title,fontsize=11,fontweight="bold"); ax.set_xticks([]); ax.set_yticks([])

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--inst",default="instance.json"); ap.add_argument("--boro",type=int,default=3)
    ap.add_argument("--max-recip",type=int,default=30); ap.add_argument("--max-donors",type=int,default=16)
    ap.add_argument("--vehicles",type=int,default=3); ap.add_argument("--base",type=int,default=600)
    ap.add_argument("--tlimit",type=int,default=8); ap.add_argument("--seed",type=int,default=3)
    ap.add_argument("--horizon",type=int,default=None,help="override vehicle shift length (min)")
    ap.add_argument("--out",default="route_demo.png")
    a=ap.parse_args()
    inst=json.load(open(a.inst))
    if a.horizon: inst["params"]["horizon_min"]=a.horizon
    recs,donors=build_subset(inst,a.boro,a.max_recip,a.max_donors,a.seed)
    bn={1:"Manhattan",2:"Bronx",3:"Brooklyn",4:"Queens",5:"Staten Island"}[a.boro]
    print(f"Subset: {bn} — {len(recs)} recipients, {len(donors)} donors, {a.vehicles} vehicles\n")
    res={}
    for mode in ("uniform","equity"):
        res[mode]=solve(inst,recs,donors,a.vehicles,mode,a.base,a.tlimit)
    print(f"{'metric':<26}{'uniform':>12}{'equity':>12}")
    def row(lbl,k,fmt="{}"):
        print(f"{lbl:<26}{fmt.format(res['uniform'][k]):>12}{fmt.format(res['equity'][k]):>12}")
    row("recipients served","n_served"); row("of total","n_rec")
    row("priority served","n_prio_served"); row("of priority total","n_prio")
    row("lbs delivered","lbs"); row("travel (min)","travel")
    row("equity weight served","w_served")
    pu=res['uniform']; pe=res['equity']
    if pu["n_prio"]:
        print(f"\npriority coverage:  uniform {pu['n_prio_served']/pu['n_prio']:.0%}  ->  equity {pe['n_prio_served']/pe['n_prio']:.0%}")
    print(f"trade-off:  equity serves {pu['n_served']-pe['n_served']} fewer recipients total "
          f"({pu['n_served']}->{pe['n_served']}) to reach priority districts; "
          f"travel {pu['travel']}->{pe['travel']} min")

    fig,axes=plt.subplots(1,2,figsize=(13,6.2))
    panel(axes[0],pu,f"Uniform — {pu['n_served']}/{pu['n_rec']} served, {pu['n_prio_served']}/{pu['n_prio']} priority")
    panel(axes[1],pe,f"Equity-weighted — {pe['n_served']}/{pe['n_rec']} served, {pe['n_prio_served']}/{pe['n_prio']} priority")
    leg=[Line2D([0],[0],marker='*',color='w',markerfacecolor='#12281F',markersize=15,label='Depot (City Harvest)'),
         Line2D([0],[0],marker='^',color='w',markerfacecolor='#D1495B',markersize=10,label='Donor (pickup)'),
         Line2D([0],[0],marker='*',color='w',markerfacecolor='#7C4DBC',markersize=13,label='Priority recipient'),
         Line2D([0],[0],marker='o',color='w',markerfacecolor='#2E8B57',markersize=10,label='Recipient (served)'),
         Line2D([0],[0],marker='o',color='w',markerfacecolor='#cccccc',markersize=10,label='Not served')]
    fig.legend(handles=leg,loc="lower center",ncol=5,frameon=False,fontsize=9,bbox_to_anchor=(0.5,-0.02))
    fig.suptitle(f"Equity-weighted food-rescue routing — {bn} (deterministic v0)",fontsize=13,fontweight="bold")
    fig.tight_layout(rect=[0,0.04,1,0.97]); fig.savefig(a.out,dpi=150,bbox_inches="tight")
    print(f"\nsaved {a.out}")

if __name__=="__main__":
    main()
