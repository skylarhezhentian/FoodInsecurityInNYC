#!/usr/bin/env python3
"""Independently replay the saved corrected benchmark without importing a solver.

The replay reconstructs route quantities from packaged inputs, not the saved
accounting totals. Passing establishes consistency with this specified model;
it does not certify the historical travel cache or real-world operations.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import random
import statistics
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
POLICIES = ["unweighted", "random_preference", "need_only", "access_only", "equity"]
EVALUATION_METRICS = ["sites_served", "high_need_coverage_pct", "reference_weighted_coverage_pct",
                      "delivered_lbs", "driving_min", "service_min", "waiting_min", "elapsed_min"]
MODEL_VERSION = "service-completion-and-cold-subset-v1"


def require(condition, message):
    if not condition:
        raise ValueError(message)


def integer(value, label):
    require(type(value) is int, f"{label} must be an integer")
    return value


def number(value, label):
    require(type(value) in (int, float) and math.isfinite(value), f"{label} must be finite numeric data")
    return value


def same_number(actual, expected, label):
    number(actual, label)
    require(math.isclose(actual, expected, rel_tol=1e-12, abs_tol=1e-9), f"{label}: expected {expected}, found {actual}")


def same_metrics(actual, expected, label):
    require(isinstance(actual, dict) and set(actual) == set(expected), f"{label}: metric keys differ")
    for name, value in expected.items():
        same_number(actual[name], value, f"{label}.{name}")


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read_json(path):
    return json.loads(Path(path).read_text())


def contained_path(root, name):
    root = Path(root).resolve()
    path = (root / name).resolve()
    require(path.is_relative_to(root), f"Path leaves its declared directory: {name}")
    return path


def load_replay_inputs(model_dir, recipients_path, traffic_factor):
    """Reconstruct the declared v1 model directly from JSON/CSV/NPZ inputs."""
    instance = read_json(model_dir / "instance.json")
    node_manifest = read_json(model_dir / "nodes.json")
    for name, expected in node_manifest["source_files"].items():
        path = contained_path(model_dir, name)
        require(path.stat().st_size == expected["bytes"] and sha256(path) == expected["sha256"],
                f"Node manifest source mismatch: {name}")
    horizon = integer(instance["params"]["horizon_min"], "horizon")
    nodes = []
    for i, origin in enumerate(instance["origins"]):
        nodes.append(dict(role="depot", source_index=i, source_id=str(origin["name"]),
                          total=0, cold=0, service=0, opens=0, closes=horizon))
    with (model_dir / "donors.csv").open(newline="") as stream:
        donors = list(csv.DictReader(stream))
    for i, donor in enumerate(donors):
        expected_supply = float(donor["supply_lbs"]) * float(donor["avail_prob"])
        nodes.append(dict(role="donor", source_index=i, source_id=str(donor["name"]),
                          total=int(expected_supply), cold=int(expected_supply * float(donor["cold_frac"])),
                          service=20, opens=0, closes=min(480, horizon)))
    for i, recipient in enumerate(instance["pantries"]):
        nodes.append(dict(role="recipient", source_index=i, source_id=str(recipient["fid"]),
                          total=-integer(recipient["demand_lbs"], "demand_lbs"),
                          cold=-integer(recipient["demand_cold"], "demand_cold"),
                          service=integer(recipient["service_min"], "service_min"),
                          opens=integer(recipient["tw_open"], "tw_open"),
                          closes=integer(recipient["tw_close"], "tw_close"),
                          need=float(recipient["need_pct"]), access=float(recipient["access_pct"])))
    require(len(nodes) == node_manifest["node_count"] == len(node_manifest["nodes"]), "Node count mismatch")
    for i, (node, declared) in enumerate(zip(nodes, node_manifest["nodes"])):
        require((i, node["role"], node["source_index"], node["source_id"]) ==
                tuple(declared[k] for k in ("matrix_index", "role", "source_index", "source_id")),
                f"Node order mismatch at {i}")
    require(0 < number(traffic_factor, "traffic_factor") <= 1, "Invalid traffic factor")
    with np.load(model_dir / "travel.npz", allow_pickle=False) as cache:
        freeflow = cache["time_min_freeflow"]
        require(freeflow.shape == (len(nodes), len(nodes)) and np.isfinite(freeflow).all()
                and (freeflow >= 0).all(), "Invalid travel cache")
        driving = np.rint(freeflow / traffic_factor).astype(np.int64)
    require((np.diag(driving) == 0).all(), "Travel diagonal must be zero")
    vehicles = [dict(origin=v["origin_idx"], total_capacity=v["cap_total_lbs"],
                     cold_capacity=v["cap_cold_lbs"], shift=v["shift_min"]) for v in instance["vehicles"]]
    with recipients_path.open(newline="") as stream:
        rows = list(csv.DictReader(stream))
    recipients = {}
    for row in rows:
        index = int(row["idx"])
        require(index not in recipients, "Duplicate recipient row index")
        demand, weight = float(row["demand_lbs"]), float(row["w_gamma1"])
        require(math.isfinite(demand) and demand > 0 and math.isfinite(weight) and weight > 0,
                "Recipient demand/weight must be finite and positive")
        require(row["need_tier"] in ("high", "mid", "low"), "Unknown recipient tier")
        recipients[index] = dict(demand=demand, weight=weight, tier=row["need_tier"])
    modeled = {node["source_index"]: -node["total"] for node in nodes if node["role"] == "recipient"}
    require(set(modeled) == set(recipients), "Model and study recipient sets differ")
    require(all(demand == recipients[i]["demand"] for i, demand in modeled.items()), "Model and study demand differ")
    return dict(nodes=nodes, vehicles=vehicles, driving=driving, horizon=horizon,
                recipients=recipients, traffic_factor=traffic_factor, alignment_status=node_manifest["status"])


def expected_penalties(nodes, policy, config):
    preference, jitter = random.Random(config["preference_seed"]), random.Random(config["jitter_seed"])
    penalties = {}
    for index, node in enumerate(nodes):
        if node["role"] != "recipient":
            continue
        if policy == "unweighted":
            weight = 1.0
        elif policy == "random_preference":
            weight = preference.uniform(.3, 1.7)
        elif policy == "need_only":
            weight = max(.5, min(4., (node["need"] + .15) / .65))
        elif policy == "access_only":
            weight = max(.5, min(4., .65 / (node["access"] + .15)))
        else:
            require(policy == "equity", "Unknown policy")
            weight = round(max(.5, min(4., (node["need"] + .15) / (node["access"] + .15))), 3)
        perturbation = jitter.uniform(-config["jitter_fraction"], config["jitter_fraction"])
        penalties[index] = int(config["skip_penalty"] * weight * (1 + perturbation))
    return penalties


def replay_record(record, model, policy, seed, protocol):
    """Recompute a complete result using no routing implementation functions."""
    require(record["policy"] == policy, "Record policy does not match its filename")
    config = dict(protocol["routing"], jitter_seed=seed)
    require(record["config"] == config, "Record configuration differs from fixed protocol")
    require(record["status"] == "solved" and record["audit"]["passed"] is True, "Record is not a solved audited route")
    require(record["model_version"] == MODEL_VERSION, "Unsupported model version")
    nodes, vehicles, driving = model["nodes"], model["vehicles"], model["driving"]
    for field, expected in (("recipients", len(model["recipients"])), ("vehicles", len(vehicles)),
                            ("donors", sum(n["role"] == "donor" for n in nodes)),
                            ("traffic_factor", model["traffic_factor"])):
        same_number(record["input"][field], expected, f"input.{field}")
    require(record["input"]["alignment_status"] == model["alignment_status"], "Cache alignment status changed")
    require(isinstance(record["routes"], list) and len(record["routes"]) == len(vehicles), "Missing vehicle routes")
    seen_nodes, seen_vehicles, served_nodes = set(), set(), set()
    metrics = dict(served_recipients=0, delivered_lbs=0, delivered_cold_lbs=0,
                   driving_minutes=0, service_minutes=0, waiting_minutes=0, elapsed_minutes=0)
    cold_delay = 0
    for route in record["routes"]:
        vi = integer(route["vehicle_index"], "vehicle_index")
        require(0 <= vi < len(vehicles) and vi not in seen_vehicles, "Unknown or duplicate vehicle")
        seen_vehicles.add(vi)
        vehicle, stops = vehicles[vi], route["stops"]
        require(isinstance(stops, list) and len(stops) >= 2, "A route must include start and return")
        for stop in stops:
            index = integer(stop["node_index"], "node_index")
            require(0 <= index < len(nodes), "Unknown route node")
            for field in ("source_index", "service_start", "service_finish", "total_before", "cold_before", "total_after", "cold_after"):
                integer(stop[field], field)
        require(stops[0]["node_index"] == stops[-1]["node_index"] == vehicle["origin"], "Wrong start/return depot")
        start_total = int(config["staged_fraction"] * vehicle["total_capacity"])
        start_cold = min(vehicle["cold_capacity"], int(start_total * config["staged_cold_fraction"]))
        total, cold = start_total, start_cold
        drive_sum = service_sum = wait_sum = pickup_total = pickup_cold = delivered_total = delivered_cold = 0
        for position, stop in enumerate(stops):
            index, time = stop["node_index"], stop["service_start"]
            node = nodes[index]
            require(all(stop[key] == node[key] for key in ("role", "source_index", "source_id")), "Stop identity mismatch")
            if position == 0:
                require(time == 0, "Route must begin at minute zero")
            elif position < len(stops) - 1:
                require(node["role"] != "depot" and index not in seen_nodes, "Repeated visit or intermediate depot")
                seen_nodes.add(index)
            require(stop["service_finish"] == time + node["service"], "Service finish mismatch")
            require(node["opens"] <= time and time + node["service"] <= node["closes"], "Service window violation")
            if position:
                previous = stops[position - 1]
                previous_node = nodes[previous["node_index"]]
                drive = int(driving[previous["node_index"], index])
                wait = time - previous["service_start"] - previous_node["service"] - drive
                require(wait >= 0, "Travel or service time missing from schedule")
                drive_sum += drive
                service_sum += previous_node["service"]
                wait_sum += wait
            require((stop["total_before"], stop["cold_before"]) == (total, cold), "Arrival load does not conserve supply")
            require(0 <= cold <= total <= vehicle["total_capacity"] and cold <= vehicle["cold_capacity"], "Infeasible arrival cargo")
            total += node["total"]
            cold += node["cold"]
            require((stop["total_after"], stop["cold_after"]) == (total, cold), "Departure load does not conserve supply")
            require(0 <= cold <= total <= vehicle["total_capacity"] and cold <= vehicle["cold_capacity"], "Infeasible departure cargo")
            if node["role"] == "donor":
                pickup_total += node["total"]
                pickup_cold += node["cold"]
            elif node["role"] == "recipient":
                served_nodes.add(index)
                delivered_total -= node["total"]
                delivered_cold -= node["cold"]
                cold_delay += int(round(config["decay_coefficient"] * -node["cold"])) * time
        elapsed = stops[-1]["service_start"]
        require(elapsed <= min(vehicle["shift"], model["horizon"]), "Vehicle exceeds shift/horizon")
        require(elapsed == drive_sum + service_sum + wait_sum, "Route time decomposition mismatch")
        accounting = dict(start_total_lbs=start_total, start_cold_lbs=start_cold, pickup_total_lbs=pickup_total,
                          pickup_cold_lbs=pickup_cold, delivered_total_lbs=delivered_total, delivered_cold_lbs=delivered_cold,
                          returned_total_lbs=total, returned_cold_lbs=cold, returned_ambient_lbs=total-cold,
                          driving_minutes=drive_sum, service_minutes=service_sum, waiting_minutes=wait_sum, elapsed_minutes=elapsed)
        same_metrics(route["accounting"], accounting, f"vehicle {vi} accounting")
        metrics["delivered_lbs"] += delivered_total
        metrics["delivered_cold_lbs"] += delivered_cold
        for field in ("driving_minutes", "service_minutes", "waiting_minutes", "elapsed_minutes"):
            metrics[field] += accounting[field]
    indices = sorted(nodes[i]["source_index"] for i in served_nodes)
    ids = [nodes[i]["source_id"] for i in sorted(served_nodes)]
    require(isinstance(record["served_recipient_indices"], list)
            and all(type(index) is int for index in record["served_recipient_indices"]), "Saved served indices must be integers")
    require(record["served_recipient_indices"] == indices and record["served_recipient_ids"] == ids, "Saved served list disagrees with routes")
    metrics["served_recipients"] = len(indices)
    same_metrics(record["metrics"], metrics, "metrics")
    same_metrics(record["audit"]["metrics"], metrics, "saved audit metrics")
    require(not record["audit"]["violations"], "Passed audit contains violations")
    same_number(record["audit"]["routes_checked"], len(vehicles), "routes_checked")
    same_number(record["audit"]["visited_nodes_checked"], len(seen_nodes), "visited_nodes_checked")
    recipients = model["recipients"]
    high = {i for i, row in recipients.items() if row["tier"] == "high"}
    high_demand = sum(recipients[i]["demand"] for i in high)
    weighted_demand = sum(row["demand"] * row["weight"] for row in recipients.values())
    require(high_demand > 0 and weighted_demand > 0, "Coverage denominators must be positive")
    evaluation = dict(sites_served=len(indices),
                      high_need_coverage_pct=100*sum(recipients[i]["demand"] for i in set(indices) & high)/high_demand,
                      reference_weighted_coverage_pct=100*sum(recipients[i]["demand"]*recipients[i]["weight"] for i in indices)/weighted_demand,
                      delivered_lbs=metrics["delivered_lbs"],
                      **{name+"_min":metrics[name+"_minutes"] for name in ("driving", "service", "waiting", "elapsed")})
    same_metrics(record["evaluation"], evaluation, "evaluation")
    penalties = expected_penalties(nodes, policy, config)
    objective = dict(driving=metrics["driving_minutes"], route_span=config["freshness_coefficient"]*metrics["elapsed_minutes"],
                     cold_delay=cold_delay, skip_penalties=sum(v for i, v in penalties.items() if i not in served_nodes))
    objective["total"] = sum(objective.values())
    same_metrics(record["objective"], objective, "objective")
    return evaluation


def verify_tables(results, records, protocol):
    """Check every run row and suppress summaries for any incomplete policy."""
    with (results / "runs.csv").open(newline="") as stream:
        runs = list(csv.DictReader(stream))
    expected_keys = {(r["policy"], r["config"]["jitter_seed"]) for r in records}
    keys = [(row["policy"], int(row["replicate_seed"])) for row in runs]
    require(len(keys) == len(set(keys)) and set(keys) == expected_keys, "Run table has missing/duplicate/unexpected rows")
    by_key = {(row["policy"], int(row["replicate_seed"])):row for row in runs}
    for record in records:
        row = by_key[(record["policy"], record["config"]["jitter_seed"])]
        for field in ("status", "solver_status"):
            require(row[field] == record[field], f"Run table {field} mismatch")
        require(row["audit_passed"] == str(record["audit"]["passed"]), "Run table audit flag mismatch")
        for metric in EVALUATION_METRICS:
            if record["evaluation"] is None:
                require(row[metric] == "", "Failed record must not have numeric performance")
            else:
                same_number(float(row[metric]), record["evaluation"][metric], f"runs.csv {metric}")
    with (results / "summary.csv").open(newline="") as stream:
        rows = list(csv.DictReader(stream))
    keys = [(row["policy"], row["metric"]) for row in rows]
    expected = {(policy, metric) for policy in protocol["policies"] for metric in EVALUATION_METRICS}
    require(len(keys) == len(set(keys)) and set(keys) == expected, "Summary table has missing/duplicate/unexpected rows")
    for row in rows:
        subset = [r for r in records if r["policy"] == row["policy"]]
        valid = [r for r in subset if r["status"] == "solved" and r["audit"]["passed"] is True]
        expected_n = len(protocol["replicate_seeds"])
        require(int(row["expected_runs"]) == expected_n and int(row["valid_runs"]) == len(valid)
                and int(row["failed_runs"]) == len(subset)-len(valid), "Summary run counts differ")
        if len(valid) != expected_n:
            require(all(row[k] == "" for k in ("median", "min", "max")), "Incomplete policy has a headline summary")
        else:
            values = [r["evaluation"][row["metric"]] for r in valid]
            for field, value in (("median", statistics.median(values)), ("min", min(values)), ("max", max(values))):
                same_number(float(row[field]), value, f"summary.csv {row['policy']} {row['metric']} {field}")


def verify_benchmark(results, root=ROOT, config_path=None):
    results, root = Path(results), Path(root)
    config_path = Path(config_path) if config_path is not None else root / "configs/corrected_benchmark.json"
    manifest = read_json(results / "manifest.json")
    protocol = read_json(config_path)
    require(manifest["protocol"] == protocol and manifest["protocol_sha256"] == sha256(config_path), "Protocol differs from saved manifest")
    require(protocol["policies"] == POLICIES and protocol["replicate_seeds"] == [1,2,3,4,5], "Unexpected benchmark policy/seed grid")
    require(protocol["recipient_limit"] is None and protocol["vehicle_limit"] is None, "Benchmark must use the full model")
    for name, expected in manifest["input_sha256"].items():
        require(sha256(contained_path(root, name)) == expected, f"Manifest input checksum mismatch: {name}")
    required_inputs = {protocol["recipient_data"], "src/food_rescue/routing.py", "scripts/run_benchmark.py"}
    required_inputs.update(f"{protocol['model_data']}/{name}" for name in ("instance.json", "donors.csv", "travel.npz", "nodes.json"))
    require(required_inputs.issubset(manifest["input_sha256"]), "Manifest omits required input checksums")
    expected_records = [f"{policy}-{seed}.json" for policy in protocol["policies"] for seed in protocol["replicate_seeds"]]
    require(set(manifest["output_sha256"]) == set(expected_records+['runs.csv','summary.csv']), "Manifest output inventory differs")
    for name, expected in manifest["output_sha256"].items():
        require(sha256(contained_path(results, name)) == expected, f"Saved output checksum mismatch: {name}")
    model = load_replay_inputs(contained_path(root, protocol["model_data"]),
                               contained_path(root, protocol["recipient_data"]), protocol["traffic_factor"])
    records, valid = [], 0
    for policy in protocol["policies"]:
        for seed in protocol["replicate_seeds"]:
            record = read_json(results / f"{policy}-{seed}.json")
            require(record["policy"] == policy and record["config"] == dict(protocol["routing"], jitter_seed=seed), "Failed/solved record differs from protocol")
            if record["status"] == "solved":
                replay_record(record, model, policy, seed, protocol)
                valid += 1
            else:
                require(record["status"] in ("error", "no_solution", "invalid") and record["audit"]["passed"] is False
                        and record["evaluation"] is None, "Failed solve is presented as valid performance")
            records.append(record)
    require(manifest["expected_runs"] == manifest["completed_records"] == len(records) == 25, "Manifest run counts differ")
    require(manifest["valid_runs"] == valid and manifest["inputs_unchanged"] is True, "Manifest validity/preservation claims differ")
    verify_tables(results, records, protocol)
    return {"status": "passed", "complete": valid == 25, "records_checked": len(records), "routes_replayed": valid*len(model["vehicles"]),
            "valid_runs": valid, "failed_runs": len(records)-valid, "policy_summaries_checked": len(POLICIES)*len(EVALUATION_METRICS),
            "input_sha256": manifest["input_sha256"], "output_sha256": manifest["output_sha256"],
            "checks": ["protocol and source/output checksums", "integer cargo, cold subset, and capacities at every stop",
                       "node identity and unique visits", "service completion, travel, waiting, return depot, and shift",
                       "saved route accounting, served lists, fleet metrics, coverage, and objective components",
                       "all run table rows and complete/incomplete policy summaries"],
            "scope": "Independent replay without routing.py or OR-Tools imports. No re-solving, optimality proof, historical cache certification, or real-world validation."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results", type=Path, default=ROOT / "results/corrected")
    args = parser.parse_args()
    try:
        result = verify_benchmark(args.results)
    except (ValueError, KeyError, TypeError, OSError) as error:
        parser.exit(1, f"Verification failed: {error}\n")
    destination = args.results / "verification.json"
    require(not destination.is_symlink(), "Verification output must not be a symbolic link")
    destination.write_text(json.dumps(result, indent=2, allow_nan=False)+"\n")
    print(f"Replayed {result['valid_runs']}/{result['records_checked']} valid saved runs; complete={result['complete']}.")
    return 0 if result["complete"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
