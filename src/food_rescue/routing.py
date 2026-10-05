"""Offline food-rescue routing model, derived from the archived study solver.

The current model accounts for service, requires service to finish inside each
window, and treats refrigerated load as a subset of total load. These changes
are intentional; its solutions do not reproduce the historical 55 runs.
"""

import csv
import hashlib
import json
import math
import random
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Optional, Tuple

import numpy as np
from ortools.constraint_solver import pywrapcp, routing_enums_pb2


POLICIES = ("unweighted", "random_preference", "need_only", "access_only", "equity")


@dataclass(frozen=True)
class Node:
    role: str
    source_index: int
    source_id: str
    latitude: float
    longitude: float
    total_delta: int
    cold_delta: int
    service_minutes: int
    opens: int
    closes: int
    need_pct: float = 0.5
    access_pct: float = 0.5


@dataclass(frozen=True)
class Vehicle:
    origin: int
    total_capacity: int
    cold_capacity: int
    shift_minutes: int


@dataclass(frozen=True)
class RoutingConfig:
    time_limit_seconds: float = 3
    staged_fraction: float = 0.4
    staged_cold_fraction: float = 0.55
    skip_penalty: int = 8000
    freshness_coefficient: int = 1
    decay_coefficient: float = 0.03
    preference_seed: int = 42
    jitter_seed: Optional[int] = None
    jitter_fraction: float = 0.002

    def __post_init__(self):
        for name in ("time_limit_seconds", "staged_fraction", "staged_cold_fraction",
                     "decay_coefficient", "jitter_fraction"):
            if not math.isfinite(getattr(self, name)):
                raise ValueError(f"{name} must be finite")
        if not 0 < self.time_limit_seconds <= 300:
            raise ValueError("time_limit_seconds must be in (0, 300]")
        for name in ("staged_fraction", "staged_cold_fraction", "jitter_fraction"):
            if not 0 <= getattr(self, name) <= 1:
                raise ValueError(f"{name} must be between zero and one")
        for name in ("skip_penalty", "freshness_coefficient"):
            _integer(getattr(self, name), name)
        if self.decay_coefficient < 0:
            raise ValueError("decay_coefficient must be nonnegative")


@dataclass(frozen=True)
class Problem:
    nodes: Tuple[Node, ...]
    vehicles: Tuple[Vehicle, ...]
    driving_minutes: np.ndarray
    horizon_minutes: int
    traffic_factor: float = 0.38
    alignment_status: str = "synthetic test instance"

    def __post_init__(self):
        _integer(self.horizon_minutes, "horizon_minutes", minimum=1)
        if not self.nodes or not self.vehicles:
            raise ValueError("At least one node and vehicle are required")
        matrix = np.asarray(self.driving_minutes)
        if (matrix.shape != (len(self.nodes), len(self.nodes))
                or not np.isfinite(matrix).all() or (matrix < 0).any()
                or not np.equal(matrix, np.floor(matrix)).all()
                or np.any(np.diag(matrix) != 0)):
            raise ValueError("Driving matrix must be square, finite, nonnegative integer minutes with zero diagonal")
        ids = set()
        for node in self.nodes:
            if node.role not in {"depot", "donor", "recipient"}:
                raise ValueError(f"Unknown node role: {node.role}")
            key = (node.role, node.source_index)
            if key in ids:
                raise ValueError(f"Duplicate node source index: {key}")
            ids.add(key)
            for name in ("source_index", "service_minutes", "opens", "closes"):
                _integer(getattr(node, name), name)
            if not 0 <= node.opens <= node.closes <= self.horizon_minutes:
                raise ValueError("Node window must lie inside the horizon")
            for name in ("total_delta", "cold_delta"):
                value = getattr(node, name)
                if isinstance(value, bool) or not isinstance(value, (int, np.integer)):
                    raise ValueError(f"{name} must be an integer")
            if node.role == "depot" and (node.total_delta or node.cold_delta or node.service_minutes):
                raise ValueError("Depot load changes and service must be zero")
            if node.role == "donor" and not 0 <= node.cold_delta <= node.total_delta:
                raise ValueError("Donor cold quantity must be a subset of total quantity")
            if node.role == "recipient" and not node.total_delta <= node.cold_delta <= 0:
                raise ValueError("Recipient cold demand must be a subset of total demand")
            for name in ("need_pct", "access_pct"):
                value = getattr(node, name)
                if not math.isfinite(value) or not 0 <= value <= 1:
                    raise ValueError(f"{name} must be a percentile between zero and one")
        for vehicle in self.vehicles:
            _integer(vehicle.origin, "origin")
            _integer(vehicle.total_capacity, "total_capacity", minimum=1)
            _integer(vehicle.cold_capacity, "cold_capacity")
            _integer(vehicle.shift_minutes, "shift_minutes", minimum=1)
            if vehicle.origin >= len(self.nodes) or self.nodes[vehicle.origin].role != "depot":
                raise ValueError("Vehicle origin must reference a depot")
            if vehicle.cold_capacity > vehicle.total_capacity:
                raise ValueError("Cold capacity cannot exceed total capacity")


def _integer(value, name, minimum=0):
    if isinstance(value, bool) or not isinstance(value, (int, np.integer)) or value < minimum:
        raise ValueError(f"{name} must be an integer >= {minimum}")
    return int(value)


def _number(value, name):
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{name} must be finite")
    return result


def load_problem(model_dir, recipient_limit=20, vehicle_limit=3, traffic_factor=0.38):
    """Load only the bundled cache; verify its declared inputs and node order.

    The manifest prevents accidental reordering/replacement of packaged files.
    It cannot retroactively establish how the historical cache was generated.
    """
    model_dir = Path(model_dir)
    for limit, name in ((recipient_limit, "recipient_limit"), (vehicle_limit, "vehicle_limit")):
        if limit is not None:
            _integer(limit, name, minimum=1)
    if not math.isfinite(traffic_factor) or not 0 < traffic_factor <= 1:
        raise ValueError("traffic_factor must be in (0, 1]")
    manifest = json.loads((model_dir / "nodes.json").read_text())
    for name in ("instance.json", "donors.csv", "travel.npz"):
        raw = (model_dir / name).read_bytes()
        declared = manifest["source_files"][name]
        if len(raw) != declared["bytes"] or hashlib.sha256(raw).hexdigest() != declared["sha256"]:
            raise ValueError(f"Packaged input checksum mismatch: {name}")
    instance = json.loads((model_dir / "instance.json").read_text())
    with (model_dir / "donors.csv").open(newline="") as stream:
        donors = list(csv.DictReader(stream))
    horizon = _integer(instance["params"]["horizon_min"], "horizon_min", minimum=1)
    nodes = []
    for i, row in enumerate(instance["origins"]):
        nodes.append(Node("depot", i, str(row["name"]), float(row["lat"]), float(row["lon"]),
                          0, 0, 0, 0, horizon))
    for i, row in enumerate(donors):
        supply = _number(row["supply_lbs"], "supply_lbs")
        probability = _number(row["avail_prob"], "avail_prob")
        cold_fraction = _number(row["cold_frac"], "cold_frac")
        if supply < 0 or not 0 <= probability <= 1 or not 0 <= cold_fraction <= 1:
            raise ValueError("Invalid donor supply, probability, or cold fraction")
        # Floor once; optimization, extraction, and audit use these same pounds.
        total = int(supply * probability)
        cold = int(supply * probability * cold_fraction)
        nodes.append(Node("donor", i, str(row["name"]), float(row["lat"]), float(row["lon"]),
                          total, cold, 20, 0, min(480, horizon)))
    for i, row in enumerate(instance["pantries"]):
        total = _integer(row["demand_lbs"], "demand_lbs")
        cold = _integer(row["demand_cold"], "demand_cold")
        nodes.append(Node("recipient", i, str(row["fid"]), float(row["lat"]), float(row["lon"]),
                          -total, -cold, _integer(row["service_min"], "service_min"),
                          _integer(row["tw_open"], "tw_open"), _integer(row["tw_close"], "tw_close"),
                          _number(row["need_pct"], "need_pct"), _number(row["access_pct"], "access_pct")))
    declared_nodes = manifest["nodes"]
    if manifest["node_count"] != len(nodes) or len(declared_nodes) != len(nodes):
        raise ValueError("Node manifest count does not match input files")
    for i, (node, declared) in enumerate(zip(nodes, declared_nodes)):
        identity = (i, node.role, node.source_index, node.source_id)
        expected = tuple(declared[k] for k in ("matrix_index", "role", "source_index", "source_id"))
        if identity != expected or not math.isclose(node.latitude, declared["latitude"], abs_tol=1e-9) or not math.isclose(node.longitude, declared["longitude"], abs_tol=1e-9):
            raise ValueError(f"Node manifest order/coordinates mismatch at index {i}")
    with np.load(model_dir / "travel.npz", allow_pickle=False) as cache:
        freeflow = np.asarray(cache["time_min_freeflow"])
        if freeflow.shape != (len(nodes), len(nodes)) or not np.isfinite(freeflow).all() or (freeflow < 0).any():
            raise ValueError("Cached travel-time matrix has invalid shape or values")
        driving = np.rint(freeflow / traffic_factor).astype(np.int64)
    selected = [i for i, node in enumerate(nodes)
                if node.role != "recipient" or recipient_limit is None or node.source_index < recipient_limit]
    vehicles = tuple(Vehicle(_integer(v["origin_idx"], "origin_idx"),
                             _integer(v["cap_total_lbs"], "cap_total_lbs", minimum=1),
                             _integer(v["cap_cold_lbs"], "cap_cold_lbs"),
                             _integer(v["shift_min"], "shift_min", minimum=1))
                     for v in instance["vehicles"][:vehicle_limit])
    return Problem(tuple(nodes[i] for i in selected), vehicles, driving[np.ix_(selected, selected)],
                   horizon, traffic_factor, manifest["status"])


def _start_load(vehicle, config):
    total = int(config.staged_fraction * vehicle.total_capacity)
    return total, min(vehicle.cold_capacity, int(total * config.staged_cold_fraction))


def _penalties(problem, policy, config):
    if policy not in POLICIES:
        raise ValueError(f"Unknown policy: {policy}")
    preferences = random.Random(config.preference_seed)
    jitter = random.Random(config.jitter_seed)
    penalties = {}
    for i, node in enumerate(problem.nodes):
        if node.role != "recipient":
            continue
        if policy == "unweighted":
            weight = 1.0
        elif policy == "random_preference":
            weight = preferences.uniform(0.3, 1.7)
        elif policy == "need_only":
            weight = max(0.5, min(4.0, (node.need_pct + 0.15) / 0.65))
        elif policy == "access_only":
            weight = max(0.5, min(4.0, 0.65 / (node.access_pct + 0.15)))
        else:
            weight = round(max(0.5, min(4.0, (node.need_pct + 0.15) / (node.access_pct + 0.15))), 3)
        perturbation = jitter.uniform(-config.jitter_fraction, config.jitter_fraction) if config.jitter_seed is not None else 0.0
        penalties[i] = int(config.skip_penalty * weight * (1.0 + perturbation))
    return penalties


def solve_problem(problem, policy, config=None):
    """Solve one bounded deterministic expected-supply scenario and audit it."""
    config = config or RoutingConfig()
    penalties = _penalties(problem, policy, config)
    starts = [vehicle.origin for vehicle in problem.vehicles]
    manager = pywrapcp.RoutingIndexManager(len(problem.nodes), len(starts), starts, starts)
    routing = pywrapcp.RoutingModel(manager)
    solver = routing.solver()

    def driving(a, b):
        return int(problem.driving_minutes[manager.IndexToNode(a), manager.IndexToNode(b)])

    def elapsed(a, b):
        return driving(a, b) + problem.nodes[manager.IndexToNode(a)].service_minutes

    routing.SetArcCostEvaluatorOfAllVehicles(routing.RegisterTransitCallback(driving))
    for name, field, capacities in (
        ("Total", "total_delta", [v.total_capacity for v in problem.vehicles]),
        ("Cold", "cold_delta", [v.cold_capacity for v in problem.vehicles]),
    ):
        callback = routing.RegisterUnaryTransitCallback(
            lambda index, field=field: getattr(problem.nodes[manager.IndexToNode(index)], field))
        routing.AddDimensionWithVehicleCapacity(callback, 0, capacities, False, name)
    total = routing.GetDimensionOrDie("Total")
    cold = routing.GetDimensionOrDie("Cold")
    # Cumul is the inventory before service; with zero load slack, the next
    # cumul is exactly the inventory after service. Include every route end.
    for index in range(manager.GetNumberOfIndices()):
        solver.Add(cold.CumulVar(index) <= total.CumulVar(index))
    for i, vehicle in enumerate(problem.vehicles):
        start_total, start_cold = _start_load(vehicle, config)
        total.CumulVar(routing.Start(i)).SetValue(start_total)
        cold.CumulVar(routing.Start(i)).SetValue(start_cold)

    routing.AddDimension(routing.RegisterTransitCallback(elapsed), problem.horizon_minutes,
                         problem.horizon_minutes, True, "Time")
    time = routing.GetDimensionOrDie("Time")
    time.SetSpanCostCoefficientForAllVehicles(config.freshness_coefficient)
    for i, node in enumerate(problem.nodes):
        if node.role == "depot":
            # A subset of the fleet may leave an origin unused. OR-Tools would
            # otherwise treat that ordinary node as a mandatory intermediate stop.
            index = manager.NodeToIndex(i)
            if index >= 0 and not routing.IsStart(index):
                routing.AddDisjunction([index], 0)
                solver.Add(routing.ActiveVar(index) == 0)
            continue
        index = manager.NodeToIndex(i)
        latest_start = node.closes - node.service_minutes
        if latest_start < node.opens:
            solver.Add(routing.ActiveVar(index) == 0)
        else:
            time.CumulVar(index).SetRange(node.opens, latest_start)
        routing.AddDisjunction([index], penalties.get(i, 0))
        if node.role == "recipient":
            coefficient = int(round(config.decay_coefficient * -node.cold_delta))
            time.SetCumulVarSoftUpperBound(index, 0, coefficient)
    for i, vehicle in enumerate(problem.vehicles):
        time.CumulVar(routing.End(i)).SetMax(min(problem.horizon_minutes, vehicle.shift_minutes))
    search = pywrapcp.DefaultRoutingSearchParameters()
    search.first_solution_strategy = routing_enums_pb2.FirstSolutionStrategy.PARALLEL_CHEAPEST_INSERTION
    search.local_search_metaheuristic = routing_enums_pb2.LocalSearchMetaheuristic.GUIDED_LOCAL_SEARCH
    search.time_limit.FromMilliseconds(max(1, int(config.time_limit_seconds * 1000)))
    assignment = routing.SolveWithParameters(search)
    status_enum = routing_enums_pb2.RoutingSearchStatus.DESCRIPTOR.enum_types_by_name["Value"]
    solver_status = status_enum.values_by_number[routing.status()].name
    result = {"status": "no_solution", "solver_status": solver_status, "policy": policy,
              "config": asdict(config), "model_version": "service-completion-and-cold-subset-v1",
              "input": {"recipients": sum(n.role == "recipient" for n in problem.nodes),
                        "donors": sum(n.role == "donor" for n in problem.nodes),
                        "vehicles": len(problem.vehicles), "traffic_factor": problem.traffic_factor,
                        "alignment_status": problem.alignment_status},
              "served_recipient_indices": None, "served_recipient_ids": None, "routes": [],
              "metrics": None, "objective": None,
              "audit": {"passed": False, "violations": ["No solution returned by the bounded search"]}}
    if assignment is None:
        return result
    routes = []
    for vehicle_index, vehicle in enumerate(problem.vehicles):
        index = routing.Start(vehicle_index)
        stops = []
        while True:
            node_index = manager.IndexToNode(index)
            node = problem.nodes[node_index]
            before_total = assignment.Value(total.CumulVar(index))
            before_cold = assignment.Value(cold.CumulVar(index))
            service_start = assignment.Value(time.CumulVar(index))
            stops.append({"node_index": node_index, "role": node.role, "source_index": node.source_index,
                          "source_id": node.source_id, "service_start": service_start,
                          "service_finish": service_start + node.service_minutes,
                          "total_before": before_total, "cold_before": before_cold,
                          "total_after": before_total + node.total_delta,
                          "cold_after": before_cold + node.cold_delta})
            if routing.IsEnd(index):
                break
            index = assignment.Value(routing.NextVar(index))
        routes.append({"vehicle_index": vehicle_index, "stops": stops})
    result.update(status="solved", routes=routes)
    audit = audit_routes(problem, routes, config)
    result["audit"] = audit
    result["metrics"] = audit["metrics"]
    served_nodes = {s["node_index"] for route in routes for s in route["stops"][1:-1]
                    if s["role"] == "recipient"}
    result["served_recipient_indices"] = sorted(problem.nodes[i].source_index for i in served_nodes)
    result["served_recipient_ids"] = [problem.nodes[i].source_id for i in sorted(served_nodes)]
    objective = {"driving": audit["metrics"]["driving_minutes"],
                 "route_span": config.freshness_coefficient * audit["metrics"]["elapsed_minutes"],
                 "cold_delay": sum(int(round(config.decay_coefficient * -problem.nodes[s["node_index"]].cold_delta)) * s["service_start"]
                                   for route in routes for s in route["stops"][1:-1] if s["role"] == "recipient"),
                 "skip_penalties": sum(value for i, value in penalties.items() if i not in served_nodes)}
    objective["total"] = int(assignment.ObjectiveValue())
    result["objective"] = objective
    if objective["total"] != sum(objective[k] for k in ("driving", "route_span", "cold_delay", "skip_penalties")):
        audit["violations"].append("Objective does not match independently reconstructed components")
        audit["passed"] = False
    if not audit["passed"]:
        result["status"] = "invalid"
    return result


def audit_routes(problem, routes, config):
    """Reconstruct loads and elapsed time from ordered stops, independently of OR-Tools.

    Positive returned inventory is allowed. Recipient service is all-or-nothing;
    each donor contributes its entire floored expected supply when visited.
    """
    violations = []
    seen_nodes, seen_vehicles = set(), set()
    metrics = dict(served_recipients=0, delivered_lbs=0, delivered_cold_lbs=0,
                   driving_minutes=0, service_minutes=0, waiting_minutes=0, elapsed_minutes=0)
    if not isinstance(routes, list):
        return {"passed": False, "violations": ["Routes must be a list"], "routes_checked": 0,
                "visited_nodes_checked": 0, "metrics": metrics}
    for route in routes:
        if not isinstance(route, dict) or not {"vehicle_index", "stops"} <= route.keys():
            violations.append("Route is missing a vehicle index or stops")
            continue
        vi = route["vehicle_index"]
        if isinstance(vi, bool) or not isinstance(vi, int) or vi in seen_vehicles or not 0 <= vi < len(problem.vehicles):
            violations.append(f"Invalid or duplicate vehicle index: {vi}")
            continue
        seen_vehicles.add(vi)
        vehicle = problem.vehicles[vi]
        stops = route["stops"]
        if not isinstance(stops, list) or len(stops) < 2:
            violations.append(f"Vehicle {vi}: stops must contain at least a start and return")
            continue
        integer_fields = {"node_index", "source_index", "service_start", "service_finish",
                          "total_before", "cold_before", "total_after", "cold_after"}
        required_fields = integer_fields | {"role", "source_id"}
        malformed = False
        for j, stop in enumerate(stops):
            if (not isinstance(stop, dict) or not required_fields <= stop.keys()
                    or any(isinstance(stop[k], bool) or not isinstance(stop[k], int) for k in integer_fields)
                    or not 0 <= stop["node_index"] < len(problem.nodes)):
                violations.append(f"Vehicle {vi}, stop {j}: malformed fields or node index")
                malformed = True
        if malformed:
            continue
        if stops[0]["node_index"] != vehicle.origin or stops[-1]["node_index"] != vehicle.origin:
            violations.append(f"Vehicle {vi}: missing expected start or return depot")
            continue
        total, cold = _start_load(vehicle, config)
        route_drive, route_service, route_wait = 0, 0, 0
        pickup_total = pickup_cold = delivered_total = delivered_cold = 0
        for j, stop in enumerate(stops):
            index = stop["node_index"]
            node = problem.nodes[index]
            label = f"Vehicle {vi}, stop {j} ({node.role} {node.source_id})"
            if (stop["role"], stop["source_index"], stop["source_id"]) != (node.role, node.source_index, node.source_id):
                violations.append(f"{label}: identity does not match model node")
            if 0 < j < len(stops) - 1:
                if node.role == "depot" or index in seen_nodes:
                    violations.append(f"{label}: repeated visit or intermediate depot")
                seen_nodes.add(index)
            service_start = stop["service_start"]
            if j == 0 and service_start != 0:
                violations.append(f"{label}: route must start at minute zero")
            if stop["service_finish"] != service_start + node.service_minutes:
                violations.append(f"{label}: service finish mismatch")
            if service_start < node.opens or service_start + node.service_minutes > node.closes:
                violations.append(f"{label}: service does not fit opening window")
            if j:
                previous = stops[j - 1]
                previous_node = problem.nodes[previous["node_index"]]
                drive = int(problem.driving_minutes[previous["node_index"], index])
                wait = service_start - previous["service_start"] - previous_node.service_minutes - drive
                if wait < 0:
                    violations.append(f"{label}: schedule leaves insufficient travel/service time")
                route_drive += drive
                route_wait += wait
                route_service += previous_node.service_minutes
            for state, expected_total, expected_cold in (
                    ("before", total, cold),
                    ("after", total + node.total_delta, cold + node.cold_delta)):
                if (stop[f"total_{state}"], stop[f"cold_{state}"]) != (expected_total, expected_cold):
                    violations.append(f"{label}: {state} load does not conserve integer pounds")
                if not 0 <= expected_cold <= expected_total <= vehicle.total_capacity or expected_cold > vehicle.cold_capacity:
                    violations.append(f"{label}: infeasible {state} cold/ambient/total inventory")
            total += node.total_delta
            cold += node.cold_delta
            if node.role == "donor":
                pickup_total += node.total_delta
                pickup_cold += node.cold_delta
            elif node.role == "recipient":
                delivered_total -= node.total_delta
                delivered_cold -= node.cold_delta
                metrics["served_recipients"] += 1
        elapsed = stops[-1]["service_start"] - stops[0]["service_start"]
        if elapsed > min(vehicle.shift_minutes, problem.horizon_minutes):
            violations.append(f"Vehicle {vi}: route exceeds shift or horizon")
        if elapsed != route_drive + route_service + route_wait:
            violations.append(f"Vehicle {vi}: elapsed time does not equal driving + service + waiting")
        accounting = {"start_total_lbs": _start_load(vehicle, config)[0],
                               "start_cold_lbs": _start_load(vehicle, config)[1],
                               "pickup_total_lbs": pickup_total, "pickup_cold_lbs": pickup_cold,
                               "delivered_total_lbs": delivered_total, "delivered_cold_lbs": delivered_cold,
                               "returned_total_lbs": total, "returned_cold_lbs": cold,
                               "returned_ambient_lbs": total - cold,
                               "driving_minutes": route_drive, "service_minutes": route_service,
                               "waiting_minutes": route_wait, "elapsed_minutes": elapsed}
        if "accounting" in route and route["accounting"] != accounting:
            violations.append(f"Vehicle {vi}: saved accounting does not match reconstructed route")
        route["accounting"] = accounting
        metrics["delivered_lbs"] += delivered_total
        metrics["delivered_cold_lbs"] += delivered_cold
        for key, value in (("driving_minutes", route_drive), ("service_minutes", route_service),
                           ("waiting_minutes", route_wait), ("elapsed_minutes", elapsed)):
            metrics[key] += value
    if seen_vehicles != set(range(len(problem.vehicles))):
        violations.append("Route output must include each vehicle exactly once, including unused vehicles")
    return {"passed": not violations, "violations": violations, "routes_checked": len(routes),
            "visited_nodes_checked": len(seen_nodes), "metrics": metrics}
