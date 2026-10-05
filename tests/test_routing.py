"""Small deterministic counterexamples for route feasibility and accounting."""

import copy
import unittest
from unittest.mock import patch

import numpy as np
from ortools.constraint_solver import pywrapcp

from food_rescue.routing import Node, Problem, RoutingConfig, Vehicle, _penalties, audit_routes, solve_problem


def node(role, index, total=0, cold=0, service=0, opens=0, closes=200):
    return Node(role, index, str(index), 40.0, -74.0, total, cold, service, opens, closes)


def problem(nodes, capacity=100, cold_capacity=100):
    n = len(nodes)
    driving = np.full((n, n), 5, dtype=np.int64)
    np.fill_diagonal(driving, 0)
    return Problem(tuple(nodes), (Vehicle(0, capacity, cold_capacity, 200),), driving, 200)


def config(**overrides):
    args = dict(time_limit_seconds=0.05, staged_fraction=1, staged_cold_fraction=0.5,
                skip_penalty=100000, freshness_coefficient=1, decay_coefficient=0)
    args.update(overrides)
    return RoutingConfig(**args)


class RoutingTests(unittest.TestCase):
    def test_driving_service_waiting_and_completion_accounting(self):
        data = problem([node("depot", 0), node("recipient", 0, -20, -10, service=7, opens=30, closes=37)])
        result = solve_problem(data, "unweighted", config())
        self.assertEqual(result["status"], "solved")
        self.assertTrue(result["audit"]["passed"])
        self.assertEqual(result["served_recipient_indices"], [0])
        self.assertEqual(result["metrics"], dict(served_recipients=1, delivered_lbs=20,
                         delivered_cold_lbs=10, driving_minutes=10, service_minutes=7,
                         waiting_minutes=25, elapsed_minutes=42))
        self.assertEqual(result["objective"]["total"], 52)

    def test_completion_after_close_cannot_be_served(self):
        data = problem([node("depot", 0), node("recipient", 0, -20, -10, service=7, opens=30, closes=36)])
        result = solve_problem(data, "unweighted", config())
        self.assertEqual(result["served_recipient_indices"], [])
        self.assertTrue(result["audit"]["passed"])

    def test_cold_cannot_exceed_total_after_ambient_delivery(self):
        # Legacy independent load dimensions could deliver 60 ambient lb from
        # 50 ambient + 50 cold, leaving 40 total but 50 cold. This must be dropped.
        data = problem([node("depot", 0), node("recipient", 0, -60, 0)])
        result = solve_problem(data, "unweighted", config())
        self.assertEqual(result["served_recipient_indices"], [])
        self.assertTrue(result["audit"]["passed"])

    def test_integer_pickup_and_donor_service_are_conserved(self):
        # These 7 total / 3 cold pounds represent a once-floored expectation.
        data = problem([node("depot", 0), node("donor", 0, 7, 3, service=20),
                        node("recipient", 0, -7, -3, service=4)])
        result = solve_problem(data, "unweighted", config(staged_fraction=0))
        self.assertEqual(result["served_recipient_indices"], [0])
        accounting = result["routes"][0]["accounting"]
        self.assertEqual((accounting["pickup_total_lbs"], accounting["pickup_cold_lbs"]), (7, 3))
        self.assertEqual((accounting["returned_total_lbs"], accounting["returned_cold_lbs"]), (0, 0))
        self.assertEqual(result["metrics"]["service_minutes"], 24)
        self.assertEqual(result["metrics"]["driving_minutes"], 15)
        self.assertTrue(result["audit"]["passed"])

    def test_dry_vehicle_cannot_pick_up_cold(self):
        data = problem([node("depot", 0), node("donor", 0, 7, 3, service=20),
                        node("recipient", 0, -7, -3)], cold_capacity=0)
        result = solve_problem(data, "unweighted", config(staged_fraction=0))
        self.assertEqual(result["served_recipient_indices"], [])
        self.assertTrue(result["audit"]["passed"])

    def test_unused_origin_is_not_a_mandatory_intermediate_stop(self):
        data = problem([node("depot", 0), node("depot", 1), node("recipient", 0, -20, -10)])
        result = solve_problem(data, "unweighted", config())
        self.assertTrue(result["audit"]["passed"])
        self.assertEqual([s["node_index"] for s in result["routes"][0]["stops"]], [0, 2, 0])

    def test_independent_audit_rejects_tampered_load_and_schedule(self):
        data = problem([node("depot", 0), node("recipient", 0, -20, -10, service=7)])
        settings = config()
        result = solve_problem(data, "unweighted", settings)
        routes = copy.deepcopy(result["routes"])
        routes[0]["stops"][1]["cold_after"] = 90
        routes[0]["stops"][1]["service_start"] = 1
        audit = audit_routes(data, routes, settings)
        self.assertFalse(audit["passed"])
        self.assertTrue(any("load does not conserve" in v for v in audit["violations"]))
        self.assertTrue(any("insufficient travel/service" in v for v in audit["violations"]))

    def test_no_assignment_is_explicit_not_zero_performance(self):
        data = problem([node("depot", 0), node("recipient", 0, -20, -10)])
        with patch.object(pywrapcp.RoutingModel, "SolveWithParameters", return_value=None):
            result = solve_problem(data, "unweighted", config())
        self.assertEqual(result["status"], "no_solution")
        self.assertIsNone(result["metrics"])
        self.assertIsNone(result["served_recipient_indices"])
        self.assertFalse(result["audit"]["passed"])

    def test_saved_record_corruption_fails_audit_without_crashing(self):
        data = problem([node("depot", 0), node("recipient", 0, -20, -10)])
        settings = config()
        result = solve_problem(data, "unweighted", settings)
        for field, value in (("node_index", 999), ("service_start", "late"), ("cold_after", None)):
            with self.subTest(field=field):
                routes = copy.deepcopy(result["routes"])
                routes[0]["stops"][1][field] = value
                self.assertFalse(audit_routes(data, routes, settings)["passed"])
        routes = copy.deepcopy(result["routes"])
        routes[0]["vehicle_index"] = 0.5
        self.assertFalse(audit_routes(data, routes, settings)["passed"])
        routes = copy.deepcopy(result["routes"])
        routes[0]["accounting"]["returned_total_lbs"] = 999
        self.assertFalse(audit_routes(data, routes, settings)["passed"])

    def test_jitter_reproducible_and_preferences_fixed_across_replicates(self):
        data = problem([node("depot", 0), node("recipient", 0, -20, -10), node("recipient", 1, -20, -10)])
        first = _penalties(data, "random_preference", config(jitter_seed=1))
        self.assertEqual(first, _penalties(data, "random_preference", config(jitter_seed=1)))
        self.assertNotEqual(first, _penalties(data, "random_preference", config(jitter_seed=2)))
        self.assertEqual(_penalties(data, "random_preference", config(jitter_seed=1, jitter_fraction=0)),
                         _penalties(data, "random_preference", config(jitter_seed=2, jitter_fraction=0)))

    def test_reject_invalid_cold_quantities_and_matrix(self):
        with self.assertRaisesRegex(ValueError, "subset"):
            problem([node("depot", 0), node("donor", 0, 2, 3)])
        with self.assertRaisesRegex(ValueError, "matrix"):
            Problem((node("depot", 0),), (Vehicle(0, 100, 100, 200),), np.array([[np.nan]]), 200)
        with self.assertRaisesRegex(ValueError, "between zero and one"):
            config(staged_cold_fraction=1.1)


if __name__ == "__main__":
    unittest.main()
