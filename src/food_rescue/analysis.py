"""Recompute saved experiment metrics without running a routing solver.

Recipient demand and priority weights are scenario inputs. A selected recipient
is treated as receiving its full demand, matching the saved binary-service
experiment. Travel is retained from the saved runs, not reconstructed here.
"""
from __future__ import annotations

import math
from numbers import Integral, Real

import numpy as np
import pandas as pd

METRICS = ("served", "high_need_pct", "mid_need_pct", "low_need_pct", "nw_pct",
           "travel_min", "delivered_lbs")
TIERS = ("high", "mid", "low")
MAIN_SETTINGS = ("gamma=0", "Random-preference", "Need-only", "Access-only", "gamma=1")
EXPECTED_SETTINGS = frozenset(MAIN_SETTINGS + ("gamma=0.25", "gamma=0.5", "gamma=0.75",
                                               "gamma=1.5", "gamma=2", "gamma=3"))
ROUNDING_TOLERANCE = {"served": 0.0, "delivered_lbs": 0.0, "travel_min": 0.0,
                      "high_need_pct": 0.05, "mid_need_pct": 0.05,
                      "low_need_pct": 0.05, "nw_pct": 0.005}
REQUIRED_COLUMNS = ("idx", "nta", "borough", "need_pct", "access_pct", "need_tier",
                    "demand_lbs", "cold_frac", "w_gamma1")


def finite_number(value, label):
    if isinstance(value, bool) or not isinstance(value, Real) or not math.isfinite(value):
        raise ValueError(f"{label} must be a finite number")
    return float(value)


def validate_recipients(recipients):
    """Validate input schema while preserving the supplied tier labels."""
    if not isinstance(recipients, pd.DataFrame) or recipients.empty:
        raise ValueError("Recipients must be a nonempty table")
    if not set(REQUIRED_COLUMNS).issubset(recipients.columns):
        raise ValueError(f"Recipient columns must include {REQUIRED_COLUMNS}")
    if recipients[list(REQUIRED_COLUMNS)].isna().any().any():
        raise ValueError("Required recipient fields must not be missing")
    frame = recipients.copy()
    if any(isinstance(i, bool) or not isinstance(i, Integral) or i < 0 for i in frame.idx):
        raise ValueError("Recipient indices must be nonnegative integers")
    if frame.idx.duplicated().any():
        raise ValueError("Recipient indices must be unique")
    for column in ("nta", "borough"):
        if any(not isinstance(v, str) or not v.strip() for v in frame[column]):
            raise ValueError(f"{column} must contain nonempty strings")
    if set(frame.need_tier) != set(TIERS):
        raise ValueError("Need tiers must be high, mid, low, with each tier represented")
    for column in ("need_pct", "access_pct", "demand_lbs", "cold_frac", "w_gamma1"):
        frame[column] = [finite_number(v, column) for v in frame[column]]
    for column in ("need_pct", "access_pct", "cold_frac"):
        if not frame[column].between(0, 1).all():
            raise ValueError(f"{column} must lie in [0, 1]")
    if not frame.demand_lbs.gt(0).all() or not frame.w_gamma1.gt(0).all():
        raise ValueError("Demand and priority weights must be strictly positive")
    return frame.set_index("idx", drop=False)


def compute_selection_metrics(recipients, served_idx):
    """Calculate six join-verifiable metrics from a validated recipient table."""
    if not isinstance(served_idx, list):
        raise ValueError("served_idx must be a list")
    if any(isinstance(i, bool) or not isinstance(i, Integral) for i in served_idx):
        raise ValueError("Served indices must be integers")
    if len(set(served_idx)) != len(served_idx):
        raise ValueError("Served indices must not contain duplicates")
    if not set(served_idx).issubset(recipients.index):
        raise ValueError("Served indices contain unknown recipients")
    selected = recipients.loc[served_idx]
    values = {"served": len(served_idx), "delivered_lbs": float(selected.demand_lbs.sum())}
    for tier in TIERS:
        denominator = recipients.loc[recipients.need_tier.eq(tier), "demand_lbs"].sum()
        numerator = selected.loc[selected.need_tier.eq(tier), "demand_lbs"].sum()
        values[f"{tier}_need_pct"] = float(100 * numerator / denominator)
    denominator = (recipients.demand_lbs * recipients.w_gamma1).sum()
    values["nw_pct"] = float(100 * (selected.demand_lbs * selected.w_gamma1).sum() / denominator)
    return values


def statistics(values):
    return {"n": len(values), "median": float(np.median(values)), "min": float(np.min(values)),
            "max": float(np.max(values)), "mean": float(np.mean(values))}


def close_with_tolerance(left, right, tolerance):
    return abs(left - right) <= tolerance + 1e-10


def analyze_saved_results(payload, recipients, require_study_settings=False):
    """Return long run values, long summaries, and arithmetic-validation evidence.

    Summaries use unrounded joined metrics. Saved run fields are checked within
    half their displayed unit. Saved summaries are also checked independently
    against saved-run arithmetic, whose mean is rounded to two decimal places.
    For a recomputed mean, the error bound includes both rounding steps.
    """
    frame = validate_recipients(recipients)
    if not isinstance(payload, dict) or not isinstance(payload.get("settings"), dict):
        raise ValueError("Replicate file must contain a settings object")
    settings = payload["settings"]
    if not settings or payload.get("config", {}).get("reps") != 5:
        raise ValueError("Saved study must declare five replicates per setting")
    if require_study_settings and set(settings) != EXPECTED_SETTINGS:
        raise ValueError("Bundled study must contain the eleven expected settings")
    run_rows, summary_rows = [], []
    computed_checks, stored_summary_checks = 0, 0
    for name, setting in settings.items():
        if not isinstance(name, str) or not name or not isinstance(setting, dict):
            raise ValueError("Each setting must have a nonempty name and object")
        runs = setting.get("runs")
        if not isinstance(runs, list) or len(runs) != 5:
            raise ValueError(f"{name}: expected five saved runs")
        if any(not isinstance(run, dict) for run in runs):
            raise ValueError(f"{name}: runs must be objects")
        reps = [r.get("rep") for r in runs]
        if any(isinstance(rep, bool) or not isinstance(rep, Integral) for rep in reps) or set(reps) != set(range(5)):
            raise ValueError(f"{name}: replicate IDs must be unique integers 0 through 4")
        policy = setting.get("policy")
        if not isinstance(policy, str) or not policy:
            raise ValueError(f"{name}: policy must be a nonempty string")
        gamma = setting.get("gamma")
        if gamma is not None and finite_number(gamma, f"{name} gamma") < 0:
            raise ValueError(f"{name}: gamma must be nonnegative")
        values_by_metric = {metric: [] for metric in METRICS}
        saved_by_metric = {metric: [] for metric in METRICS}
        for run in runs:
            values = compute_selection_metrics(frame, run.get("served_idx"))
            travel = finite_number(run.get("travel_min"), f"{name} travel_min")
            if travel < 0:
                raise ValueError("Saved travel must be nonnegative")
            values["travel_min"] = travel
            for metric in METRICS:
                stored = finite_number(run.get(metric), f"{name} {metric}")
                value = values[metric]
                tolerance = ROUNDING_TOLERANCE[metric]
                if not close_with_tolerance(value, stored, tolerance):
                    raise ValueError(f"{name} replicate {run['rep']}: saved {metric} disagrees with recipient join")
                if metric != "travel_min":
                    computed_checks += 1
                run_rows.append({"setting": name, "policy": policy, "gamma": gamma, "rep": run["rep"],
                                 "metric": metric, "value": value,
                                 "source": "stored_unverified" if metric == "travel_min" else "recipient_join",
                                 "stored_value": stored, "absolute_difference": abs(value - stored),
                                 "within_saved_precision": True})
                values_by_metric[metric].append(value)
                saved_by_metric[metric].append(stored)
        if not isinstance(setting.get("summary"), dict):
            raise ValueError(f"{name}: missing saved summary")
        for metric in METRICS:
            computed = statistics(values_by_metric[metric])
            saved_arithmetic = statistics(saved_by_metric[metric])
            stored_summary = setting["summary"].get(metric)
            if not isinstance(stored_summary, dict):
                raise ValueError(f"{name}: missing {metric} summary")
            row = {"setting": name, "policy": policy, "gamma": gamma, "metric": metric, **computed,
                   "source": "stored_unverified" if metric == "travel_min" else "recipient_join"}
            for stat, value in computed.items():
                stored = finite_number(stored_summary.get(stat), f"{name} {metric} {stat}")
                expected = round(saved_arithmetic[stat], 2) if stat == "mean" else saved_arithmetic[stat]
                if not close_with_tolerance(expected, stored, 0):
                    raise ValueError(f"{name}: saved {metric} {stat} disagrees with saved-run arithmetic")
                stored_summary_checks += 1
                tolerance = 0 if stat == "n" else ROUNDING_TOLERANCE[metric]
                if stat == "mean":
                    tolerance += 0.005
                if not close_with_tolerance(value, stored, tolerance):
                    raise ValueError(f"{name}: recomputed {metric} {stat} exceeds rounding error bound")
                row[f"stored_{stat}"] = stored
            row["within_saved_precision"] = True
            summary_rows.append(row)
    validation = {
        "status": "passed", "settings": len(settings), "saved_runs": sum(len(s["runs"]) for s in settings.values()),
        "recipient_rows": len(frame), "recipient_ids_unique": True, "served_ids_known_and_unique": True,
        "recipient_missing_values": 0, "replicates_per_setting": 5,
        "joined_run_value_checks": computed_checks, "saved_summary_scalar_checks": stored_summary_checks,
        "total_scenario_demand_lbs": float(frame.demand_lbs.sum()),
        "tier_recipient_counts": {tier: int(frame.need_tier.eq(tier).sum()) for tier in TIERS},
        "tier_demand_lbs": {tier: float(frame.loc[frame.need_tier.eq(tier), "demand_lbs"].sum()) for tier in TIERS},
        "metric_definitions": {
            "high_need_pct": "100 * selected high-tier demand / all high-tier demand; supplied labels preserved",
            "mid_need_pct": "100 * selected mid-tier demand / all mid-tier demand; supplied labels preserved",
            "low_need_pct": "100 * selected low-tier demand / all low-tier demand; supplied labels preserved",
            "nw_pct": "100 * sum(selected demand_lbs * w_gamma1) / sum(all demand_lbs * w_gamma1)",
            "served": "Number of unique selected recipient indices",
            "delivered_lbs": "Sum of scenario demand at selected recipients; not observed deliveries",
            "travel_min": "Copied from saved runs; route-time calculation is not independently verified"},
        "run_rounding_tolerance": ROUNDING_TOLERANCE,
        "summary_precision": "Unrounded joined metrics are aggregated. Saved summary arithmetic is checked against saved runs; recomputed mean tolerance adds 0.005 for the second mean-rounding step.",
        "scope": "Arithmetic reanalysis of one saved scenario. No solver execution, route-feasibility test, source-data reconstruction, or population inference.",
        "historical_route_feasibility": "Not verified. Routes for the 55 saved runs are unavailable. Independent historical-code review found total/cold cargo constraints can admit negative ambient cargo; reproducing reported allocation metrics does not establish physically feasible routes.",
    }
    return pd.DataFrame(run_rows), pd.DataFrame(summary_rows), validation
