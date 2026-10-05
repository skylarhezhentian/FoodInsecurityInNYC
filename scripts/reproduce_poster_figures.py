#!/usr/bin/env python3
"""Rebuild poster figures and check earlier saved analyses, entirely offline.

The original poster images remain in poster/source/figures. These redraws use
portable fonts and the same saved numerical inputs, not new route solutions.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
import tempfile

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import TwoSlopeNorm
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))
from food_rescue.analysis import MAIN_SETTINGS, analyze_saved_results
from research.experiments.distribution.distributional_metrics import metrics_for

EXPERIMENTS = ROOT / "research/experiments"
OWNER = "saved-poster-evidence-v1"
MARKER = ".poster_results.json"
COLORS = {"unweighted":"#777777", "random_preference":"#AAAAAA", "need_only":"#d88924",
          "access_only":"#8064a2", "equity":"#24774d"}
POLICIES = list(COLORS)


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def priority_points(instance, recipients):
    """Preserve the original map's stored weights, including its rounding path."""
    rows = []
    expected = recipients.set_index("idx")
    if len(instance["pantries"]) != len(expected) or not expected.index.is_unique:
        raise ValueError("Poster map and study recipient cohorts differ")
    for index, pantry in enumerate(instance["pantries"]):
        original = expected.loc[index]
        for field in ("need_pct", "access_pct", "demand_lbs"):
            if pantry[field] != original[field]:
                raise ValueError(f"Poster map/study {field} differs at recipient {index}")
        rows.append({"idx":index, "longitude":pantry["lon"], "latitude":pantry["lat"],
                     "need_pct":pantry["need_pct"], "access_pct":pantry["access_pct"],
                     "poster_weight":pantry["w"], "study_reference_weight":original.w_gamma1})
    result = pd.DataFrame(rows)
    if not np.isfinite(result.select_dtypes("number")).all().all() or not result.poster_weight.gt(0).all():
        raise ValueError("Invalid poster map values")
    return result


def poster_tables(payload):
    """Use the saved rounded summaries plotted in the original poster."""
    settings = payload["settings"]
    table = []
    labels = ["Unweighted", "Random-preference", "Need-only", "Access-only", "Need-access"]
    for label, setting in zip(labels, MAIN_SETTINGS):
        for metric in ("served", "high_need_pct", "nw_pct", "travel_min"):
            summary = settings[setting]["summary"][metric]
            table.append(dict(strategy=label,setting=setting,metric=metric,median=summary["median"],
                              minimum=summary["min"],maximum=summary["max"],poster_display=f"{summary['median']:,.0f}"))
    curve = []
    for setting, value in settings.items():
        if value["gamma"] is None:
            continue
        s = value["summary"]
        curve.append(dict(setting=setting,gamma=value["gamma"],sites=s["served"]["median"],
                          sites_min=s["served"]["min"],sites_max=s["served"]["max"],
                          coverage=s["high_need_pct"]["median"],coverage_min=s["high_need_pct"]["min"],
                          coverage_max=s["high_need_pct"]["max"]))
    return pd.DataFrame(table), pd.DataFrame(curve).sort_values("gamma")


def check_distribution(solution, saved):
    """Recompute the precursor's distributional results, preserving tie order."""
    records = solution["recipients"]
    if [row["idx"] for row in records] != list(range(len(records))):
        raise ValueError("Historical recipient indices must match their stored row order")
    need = np.array([row["need_pct"] for row in records])
    demand = np.array([row["demand_lbs"] for row in records])
    weight = np.array([row["w"] for row in records])
    nta = [row["nta"] for row in records]
    output = {"n_recipients":len(records), "source":"ch_solution.json", "modes":{}}
    for mode in ("mode_A", "mode_B_equal_throughput"):
        output["modes"][mode] = {}
        for policy in POLICIES:
            selected = solution[mode][policy]["served_idx"]
            if len(set(selected)) != len(selected) or not set(selected).issubset(range(len(records))):
                raise ValueError("Invalid historical served recipient set")
            result = metrics_for(selected, need, demand, nta)
            result["need_weighted_coverage_pct"] = round(float(100*(demand[selected]*weight[selected]).sum()/(demand*weight).sum()),1)
            output["modes"][mode][policy] = result
    if output != saved:
        raise ValueError("Recomputed historical distributional results differ from their saved file")
    return output


def check_robustness(saved):
    """Check statistics from the six saved worlds, without recreating any solve."""
    worlds = saved["worlds"]
    if len(worlds) != saved["args"]["worlds"] or not worlds:
        raise ValueError("Robustness world count differs from declared configuration")
    checks = 0
    for policy in POLICIES:
        for metric in ("served", "nw", "high", "delivered"):
            values = np.array([world[policy][metric] for world in worlds], dtype=float)
            if not np.isfinite(values).all():
                raise ValueError("Nonfinite robustness value")
            expected = {"mean":round(float(values.mean()),1), "sd":round(float(values.std(ddof=0)),1),
                        "min":round(float(values.min()),1), "max":round(float(values.max()),1)}
            if expected != saved["agg"][policy][metric]:
                raise ValueError(f"Saved robustness statistics disagree: {policy}/{metric}")
            checks += 4
    statements = {"equity leads need-weighted cov":("nw","equity",max),
                  "need_only leads high-need tier cov":("high","need_only",max),
                  "equity leads high-need tier cov":("high","equity",max),
                  "equity lowest agencies served":("served","equity",min)}
    for label, (metric, policy, choose) in statements.items():
        count = sum(choose(POLICIES,key=lambda p:world[p][metric]) == policy for world in worlds)
        if saved["stability"][label] != f"{count}/{len(worlds)}":
            raise ValueError(f"Saved rank-stability statement disagrees: {label}")
    return {"worlds":len(worlds), "aggregate_values_checked":checks, "rank_statements_checked":len(statements),
            "scope":"Statistics of saved world summaries only; perturbed routes and solver feasibility are not revalidated."}


def save_figure(fig, path):
    fig.savefig(path.with_suffix(".svg"), bbox_inches="tight", metadata={"Date":None})
    fig.savefig(path.with_suffix(".png"), dpi=170, bbox_inches="tight", metadata={"Software":"Matplotlib"})
    plt.close(fig)


def draw_priority(points, instance, boroughs, output):
    norm = TwoSlopeNorm(vmin=.5,vcenter=1,vmax=float(np.ceil(points.poster_weight.max()*2)/2))
    fig, axes = plt.subplots(1,2,figsize=(12.5,6.2),gridspec_kw={"width_ratios":[1,1.1]},layout="constrained")
    ax = axes[0]
    ax.scatter(points.access_pct,points.need_pct,c=points.poster_weight,cmap="RdBu_r",norm=norm,s=24,edgecolor="#444",linewidth=.25)
    ax.plot([0,1],[0,1],"--",color="#777",linewidth=1)
    ax.set(xlim=(0,1),ylim=(0,1),xlabel="Access percentile",ylabel="Need percentile",
           title="A. Need, access, and priority")
    ax = axes[1]
    for feature in boroughs["features"]:
        geometry = feature["geometry"]
        polygons = geometry["coordinates"] if geometry["type"] == "MultiPolygon" else [geometry["coordinates"]]
        for polygon in polygons:
            ring = np.asarray(polygon[0])
            ax.fill(ring[:,0],ring[:,1],color="#f3f3f3",edgecolor="#aaa",linewidth=.45)
    order = np.argsort(np.abs(np.log(points.poster_weight)))
    selected = points.iloc[order]
    scatter = ax.scatter(selected.longitude,selected.latitude,c=selected.poster_weight,cmap="RdBu_r",norm=norm,s=21,edgecolor="#444",linewidth=.2)
    for depot in instance["origins"]:
        ax.scatter(depot["lon"],depot["lat"],marker="*",s=130,color="#111",edgecolor="white",linewidth=.7,zorder=5)
    ax.set_aspect(1/np.cos(np.radians(40.73)))
    ax.set(xticks=[],yticks=[],title="B. The same weights across NYC")
    for axis in axes:
        axis.spines[["top","right"]].set_visible(False)
    fig.colorbar(scatter,ax=axes,shrink=.82,label="Stored priority weight (gamma = 1)")
    fig.suptitle("Historical poster · priority surface",fontsize=15)
    save_figure(fig,output/"figure1_priority_surface")


def draw_dial(payload, curve, output):
    fig, ax = plt.subplots(figsize=(11,7.2),layout="constrained")
    ax.errorbar(curve.sites,curve.coverage,
                xerr=[curve.sites-curve.sites_min,curve.sites_max-curve.sites],
                yerr=[curve.coverage-curve.coverage_min,curve.coverage_max-curve.coverage],
                color=COLORS["equity"],fmt="o-",capsize=3,linewidth=2,alpha=.85,label="Need-access gamma sweep")
    labels={0:(231,32),.25:(191,36),.5:(174,39),.75:(166,48),1:(194,43),1.5:(166,53),2:(166,50.5),3:(166,55.5)}
    for row in curve.itertuples():
        ax.annotate(f"γ = {row.gamma:g}",(row.sites,row.coverage),xytext=labels[row.gamma],
                    fontsize=10,color=COLORS["equity"],arrowprops={"arrowstyle":"-","lw":.6})
    for key, policy, offset in (("Random-preference","random_preference",(0,-19)),
                                ("Need-only","need_only",(12,3)),("Access-only","access_only",(12,-1))):
        summary=payload["settings"][key]["summary"]
        x,y=summary["served"],summary["high_need_pct"]
        ax.errorbar(x["median"],y["median"],xerr=[[x["median"]-x["min"]],[x["max"]-x["median"]]],
                    yerr=[[y["median"]-y["min"]],[y["max"]-y["median"]]],fmt="D",capsize=3,markersize=8,color=COLORS[policy])
        ax.annotate(key,(x["median"],y["median"]),xytext=offset,textcoords="offset points",fontsize=11,color=COLORS[policy])
    ax.set(xlim=(162,246),ylim=(17,62),xlabel="Recipient sites served",ylabel="High-need demand covered (%)",
           title="Historical poster · the tested equity dial")
    ax.grid(alpha=.2)
    ax.spines[["top","right"]].set_visible(False)
    ax.text(.01,.01,"Five penalty-perturbed solves per setting; whiskers are observed min–max.\nHistorical model, not the corrected benchmark or a proven frontier.",
            transform=ax.transAxes,fontsize=9,va="bottom")
    save_figure(fig,output/"figure2_equity_dial")


def draw_distribution(distribution, output):
    fig, ax = plt.subplots(figsize=(11,5),layout="constrained")
    for policy in POLICIES:
        values=distribution["modes"]["mode_A"][policy]["coverage_by_need_decile_pct"]
        ax.plot(range(1,11),values,"o-",color=COLORS[policy],label=policy.replace("_"," "))
    ax.set(xticks=range(1,11),ylim=(0,100),xlabel="Equal-count recipient need decile",ylabel="Demand covered (%)",
           title="Earlier single-run distributional analysis · not a poster headline result")
    ax.legend(ncol=3,fontsize=9)
    ax.grid(alpha=.2)
    save_figure(fig,output/"appendix_distribution")


def validate_output(output):
    """Allow generated artifacts only in an owned subdirectory of outputs/."""
    output=Path(output).absolute()
    base=ROOT/"outputs"
    if base.is_symlink() or output.is_symlink() or any(parent.is_symlink() for parent in output.parents):
        raise ValueError("Poster output path must not contain a symlink")
    output=output.resolve()
    if output == base.resolve() or not output.is_relative_to(base.resolve()):
        raise ValueError("Poster output must be a subdirectory of outputs/")
    if output.exists() and not output.is_dir():
        raise ValueError("Poster output must be a directory")
    if output.exists() and any(output.iterdir()):
        marker=output/MARKER
        if not marker.is_file() or marker.is_symlink() or json.loads(marker.read_text()).get("owner") != OWNER:
            raise ValueError("Refusing to write into an unrelated nonempty directory")
    return output


def reproduce(output):
    output=validate_output(output)
    archive=json.loads((EXPERIMENTS/"manifest.json").read_text())
    for entry in archive["files"]:
        if sha256(ROOT/entry["path"]) != entry["packaged_sha256"]:
            raise ValueError(f"Historical archive checksum changed: {entry['path']}")
    paths={"replicates":ROOT/"data/study/replicates.json", "recipients":ROOT/"data/study/recipients.csv",
           "instance":ROOT/"data/model/instance.json", "boroughs":ROOT/"data/upstream/donor_model/data/nyc_boroughs.geojson",
           "solution":EXPERIMENTS/"single_run/ch_solution.json", "distribution":EXPERIMENTS/"distribution/distributional_metrics.json",
           "robustness":EXPERIMENTS/"robustness/robustness.json"}
    before={str(path.relative_to(ROOT)):sha256(path) for path in paths.values()}
    payload=json.loads(paths["replicates"].read_text())
    recipients=pd.read_csv(paths["recipients"])
    _,_,validation=analyze_saved_results(payload,recipients,require_study_settings=True)
    instance=json.loads(paths["instance"].read_text())
    points=priority_points(instance,recipients)
    table,curve=poster_tables(payload)
    distribution=check_distribution(json.loads(paths["solution"].read_text()),json.loads(paths["distribution"].read_text()))
    robustness=check_robustness(json.loads(paths["robustness"].read_text()))
    plt.rcParams.update({"font.family":"DejaVu Sans","svg.hashsalt":"laidlaw-poster-evidence-v1"})
    output.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".poster-figures-",dir=output.parent) as directory:
        stage=Path(directory)
        points.to_csv(stage/"priority_points.csv",index=False,float_format="%.12g")
        table.to_csv(stage/"table1.csv",index=False,float_format="%.12g")
        curve.to_csv(stage/"gamma_sweep.csv",index=False,float_format="%.12g")
        (stage/"distributional_reanalysis.json").write_text(json.dumps(distribution,indent=2,allow_nan=False)+"\n")
        draw_priority(points,instance,json.loads(paths["boroughs"].read_text()),stage)
        draw_dial(payload,curve,stage)
        draw_distribution(distribution,stage)
        after={str(path.relative_to(ROOT)):sha256(path) for path in paths.values()}
        if before != after:
            raise ValueError("Source files changed during figure reproduction")
        result={"status":"passed","inputs_unchanged":True,"input_sha256":before,
                "saved_runs_checked":validation["saved_runs"],"saved_summary_values_checked":validation["saved_summary_scalar_checks"],
                "priority_points":len(points),"poster_study_weight_rounding_differences":int(points.poster_weight.ne(points.study_reference_weight).sum()),
                "distribution_modes_recomputed":list(distribution["modes"]),"robustness":robustness,
                "output_sha256":{path.name:sha256(path) for path in stage.iterdir()},
                "scope":"Poster redraws use saved rounded summaries and stored map weights. Original bitmaps are preserved separately. Historical route feasibility is not established; earlier distribution/robustness outputs are not poster headline evidence."}
        (stage/"validation.json").write_text(json.dumps(result,indent=2,allow_nan=False)+"\n")
        (stage/MARKER).write_text(json.dumps({"owner":OWNER})+"\n")
        output.mkdir(parents=True,exist_ok=True)
        for path in stage.iterdir():
            destination=output/path.name
            if destination.is_symlink():
                raise ValueError("Generated poster output must not be a symlink")
        for path in stage.iterdir():
            path.replace(output/path.name)
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output",type=Path,default=ROOT/"outputs/poster_figures")
    args=parser.parse_args()
    result=reproduce(args.output)
    print(f"Rebuilt both poster figures from {result['saved_runs_checked']} saved runs; inputs unchanged.")


if __name__ == "__main__":
    main()
