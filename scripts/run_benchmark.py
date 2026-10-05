#!/usr/bin/env python3
"""Run the fixed five-policy comparison and retain every route and failure."""

import argparse
import csv
import hashlib
import importlib.metadata
import json
import platform
import statistics
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from food_rescue.routing import RoutingConfig, load_problem, solve_problem


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def coverage_metrics(recipients, served_indices):
    """Use the preserved study labels and reference weights for every policy."""
    selected = set(served_indices)
    if len(selected) != len(served_indices) or not selected <= set(recipients):
        raise ValueError("Served recipient indices must be unique and present in the study table")
    high = {i for i, row in recipients.items() if row["tier"] == "high"}
    high_demand = sum(recipients[i]["demand"] for i in high)
    reference_demand = sum(row["demand"] * row["weight"] for row in recipients.values())
    if high_demand <= 0 or reference_demand <= 0:
        raise ValueError("Coverage denominators must be positive")
    return {
        "sites_served": len(selected),
        "high_need_coverage_pct": 100 * sum(recipients[i]["demand"] for i in selected & high) / high_demand,
        "reference_weighted_coverage_pct": 100 * sum(recipients[i]["demand"] * recipients[i]["weight"] for i in selected) / reference_demand,
    }


def load_recipients(path):
    with path.open(newline="") as stream:
        rows = list(csv.DictReader(stream))
    # Column names are intentionally fixed to the preserved study schema.
    recipients = {}
    for row in rows:
        idx = int(row["idx"])
        if idx in recipients:
            raise ValueError("Duplicate recipient index")
        recipients[idx] = {"tier": row["need_tier"], "demand": float(row["demand_lbs"]),
                           "weight": float(row["w_gamma1"])}
    return recipients


def write_tables(output, records, policies, seeds):
    metric_names = ["sites_served", "high_need_coverage_pct", "reference_weighted_coverage_pct",
                    "delivered_lbs", "driving_min", "service_min", "waiting_min", "elapsed_min"]
    fields = ["policy", "replicate_seed", "status", "solver_status", "audit_passed"] + metric_names
    with (output / "runs.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for record in records:
            writer.writerow(dict(policy=record["policy"], replicate_seed=record["config"]["jitter_seed"],
                                 status=record["status"], solver_status=record["solver_status"],
                                 audit_passed=record["audit"]["passed"], **(record.get("evaluation") or {})))
    with (output / "summary.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=["policy", "metric", "expected_runs", "valid_runs", "failed_runs", "median", "min", "max"])
        writer.writeheader()
        for policy in policies:
            subset = [r for r in records if r["policy"] == policy]
            valid = [r for r in subset if r["status"] == "solved" and r["audit"]["passed"]]
            # Incomplete policies have no headline summary; all run records remain visible.
            complete = len(valid) == len(seeds) == len(subset)
            for metric in metric_names:
                values = [r["evaluation"][metric] for r in valid]
                writer.writerow(dict(policy=policy, metric=metric, expected_runs=len(seeds),
                                     valid_runs=len(valid), failed_runs=len(subset) - len(valid),
                                     median=statistics.median(values) if complete else None,
                                     min=min(values) if complete else None, max=max(values) if complete else None))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=ROOT / "configs/corrected_benchmark.json")
    parser.add_argument("--output", type=Path, default=ROOT / "outputs/benchmark")
    args = parser.parse_args()
    config = json.loads(args.config.read_text())
    expected_policies = ["unweighted", "random_preference", "need_only", "access_only", "equity"]
    if config["policies"] != expected_policies or config["replicate_seeds"] != [1, 2, 3, 4, 5]:
        parser.error("This benchmark requires the fixed five policies and replicate seeds 1–5")
    if config["recipient_limit"] is not None or config["vehicle_limit"] is not None:
        parser.error("The fixed benchmark uses all recipients and vehicles")
    RoutingConfig(**config["routing"])
    output = args.output.resolve()
    if output.exists() and any(output.iterdir()):
        parser.error("Output directory must be empty; choose a new --output to retain previous results")
    if not output.is_relative_to((ROOT / "outputs").resolve()):
        parser.error("Choose an output directory inside this repository's outputs/ folder")
    output.mkdir(parents=True, exist_ok=True)
    model_dir = ROOT / config["model_data"]
    recipient_path = ROOT / config["recipient_data"]
    inputs = [*sorted(model_dir.iterdir()), recipient_path, ROOT / "src/food_rescue/routing.py",
              ROOT / "scripts/run_benchmark.py"]
    hashes = {str(path.relative_to(ROOT)): sha256(path) for path in inputs if path.is_file()}
    manifest = {"schema_version": 1, "started_utc": datetime.now(timezone.utc).isoformat(),
                "protocol": config, "protocol_sha256": sha256(args.config), "input_sha256": hashes,
                "python": platform.python_version(), "platform": platform.system(),
                "packages": {name: importlib.metadata.version(name) for name in ("numpy", "ortools")},
                "note": "Time-limited search can vary across machines; saved routes can be checked without re-solving."}
    write_json(output / "manifest.json", manifest)
    recipients = load_recipients(recipient_path)
    problem = load_problem(model_dir, recipient_limit=config["recipient_limit"], vehicle_limit=config["vehicle_limit"],
                           traffic_factor=config["traffic_factor"])
    model_indices = {node.source_index for node in problem.nodes if node.role == "recipient"}
    if model_indices != set(recipients):
        raise ValueError("Benchmark coverage table must match the full modeled recipient set")
    for node in problem.nodes:
        if node.role == "recipient" and recipients[node.source_index]["demand"] != -node.total_delta:
            raise ValueError(f"Demand mismatch for recipient {node.source_index}")
    records = []
    for policy in config["policies"]:
        for seed in config["replicate_seeds"]:
            routing_config = dict(config["routing"], jitter_seed=seed)
            try:
                result = solve_problem(problem, policy, RoutingConfig(**routing_config))
                if result["status"] == "solved" and result["audit"]["passed"]:
                    result["evaluation"] = coverage_metrics(recipients, result["served_recipient_indices"])
                    metrics = result["metrics"]
                    result["evaluation"]["delivered_lbs"] = metrics["delivered_lbs"]
                    for name in ("driving", "service", "waiting", "elapsed"):
                        result["evaluation"][name + "_min"] = metrics[name + "_minutes"]
                else:
                    result["evaluation"] = None
            except Exception as exc:
                result = {"policy": policy, "config": routing_config, "status": "error",
                          "solver_status": "EXCEPTION", "audit": {"passed": False, "violations": [f"{type(exc).__name__}: {exc}"]},
                          "evaluation": None, "routes": [], "served_recipient_indices": None}
            records.append(result)
            write_json(output / f"{policy}-{seed}.json", result)
            print(f"{policy:18s} seed={seed} {result['status']:11s} {result.get('evaluation')}", flush=True)
    write_tables(output, records, config["policies"], config["replicate_seeds"])
    unchanged = all(sha256(ROOT / name) == value for name, value in hashes.items()) and sha256(args.config) == manifest["protocol_sha256"]
    passed = sum(r["status"] == "solved" and r["audit"]["passed"] for r in records)
    manifest.update(finished_utc=datetime.now(timezone.utc).isoformat(), expected_runs=len(config["policies"]) * len(config["replicate_seeds"]),
                    completed_records=len(records), valid_runs=passed, inputs_unchanged=unchanged,
                    output_sha256={path.name: sha256(path) for path in sorted(output.iterdir()) if path.name != "manifest.json"})
    write_json(output / "manifest.json", manifest)
    print(f"Retained {len(records)} records; {passed} passed route audit. Inputs unchanged: {unchanged}")
    return 0 if passed == manifest["expected_runs"] and unchanged else 1


if __name__ == "__main__":
    sys.exit(main())
