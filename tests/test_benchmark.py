"""Independent saved-route checks using a hand-calculated pickup/delivery case."""
import copy
import csv
import json
from pathlib import Path
import sys
import tempfile
import unittest

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.verify_benchmark import (EVALUATION_METRICS, MODEL_VERSION, POLICIES,
                                      replay_record, verify_benchmark, verify_tables)


def fixture():
    protocol = {"routing": dict(time_limit_seconds=10, staged_fraction=.4, staged_cold_fraction=.55,
                                skip_penalty=8000, freshness_coefficient=1, decay_coefficient=.03,
                                preference_seed=42, jitter_fraction=0),
                "policies": ["unweighted"], "replicate_seeds": [1]}
    nodes = [dict(role="depot", source_index=0, source_id="D", total=0, cold=0, service=0, opens=0, closes=200),
             dict(role="donor", source_index=0, source_id="P", total=7, cold=3, service=20, opens=0, closes=200),
             dict(role="recipient", source_index=0, source_id="R0", total=-20, cold=-10, service=7,
                  opens=0, closes=200, need=.8, access=.5),
             dict(role="recipient", source_index=1, source_id="R1", total=-30, cold=0, service=7,
                  opens=0, closes=200, need=.2, access=.5)]
    driving = np.full((4,4), 5, dtype=int)
    np.fill_diagonal(driving, 0)
    model = dict(nodes=nodes, vehicles=[dict(origin=0, total_capacity=100, cold_capacity=100, shift=200)],
                 driving=driving, horizon=200, traffic_factor=.38, alignment_status="synthetic fixture",
                 recipients={0:dict(demand=20,weight=2,tier="high"),1:dict(demand=30,weight=.5,tier="low")})
    stops = []
    for index, time, before, after in [(0,0,(40,22),(40,22)),(1,5,(40,22),(47,25)),
                                       (2,30,(47,25),(27,15)),(0,42,(27,15),(27,15))]:
        node = nodes[index]
        stops.append(dict(node_index=index, role=node["role"], source_index=node["source_index"], source_id=node["source_id"],
                          service_start=time, service_finish=time+node["service"],
                          total_before=before[0], cold_before=before[1], total_after=after[0], cold_after=after[1]))
    accounting = dict(start_total_lbs=40, start_cold_lbs=22, pickup_total_lbs=7, pickup_cold_lbs=3,
                      delivered_total_lbs=20, delivered_cold_lbs=10, returned_total_lbs=27, returned_cold_lbs=15,
                      returned_ambient_lbs=12, driving_minutes=15, service_minutes=27, waiting_minutes=0, elapsed_minutes=42)
    metrics = dict(served_recipients=1, delivered_lbs=20, delivered_cold_lbs=10, driving_minutes=15,
                   service_minutes=27, waiting_minutes=0, elapsed_minutes=42)
    evaluation = dict(sites_served=1, high_need_coverage_pct=100, reference_weighted_coverage_pct=100*40/55,
                      delivered_lbs=20, driving_min=15, service_min=27, waiting_min=0, elapsed_min=42)
    record = dict(policy="unweighted",config=dict(protocol["routing"], jitter_seed=1),status="solved",
                  solver_status="ROUTING_SUCCESS",model_version=MODEL_VERSION,
                  input=dict(recipients=2,donors=1,vehicles=1,traffic_factor=.38,alignment_status="synthetic fixture"),
                  routes=[dict(vehicle_index=0,stops=stops,accounting=accounting)],
                  served_recipient_indices=[0],served_recipient_ids=["R0"],metrics=metrics,evaluation=evaluation,
                  audit=dict(passed=True,violations=[],routes_checked=1,visited_nodes_checked=2,metrics=copy.deepcopy(metrics)),
                  objective=dict(driving=15,route_span=42,cold_delay=0,skip_penalties=8000,total=8057))
    return record, model, protocol


class IndependentReplayTests(unittest.TestCase):
    def test_integer_pickup_service_and_subset_cargo_replay_without_solver(self):
        record, model, protocol = fixture()
        before = copy.deepcopy(record)
        result = replay_record(record, model, "unweighted", 1, protocol)
        self.assertEqual(result["elapsed_min"], 42)
        self.assertEqual(result["service_min"], 27)
        self.assertAlmostEqual(result["reference_weighted_coverage_pct"], 100*40/55)
        self.assertEqual(record, before)

    def test_saved_accounting_metrics_objective_and_lists_are_not_trusted(self):
        changes = [lambda r:r["routes"][0]["accounting"].update(returned_ambient_lbs=99),
                   lambda r:r["metrics"].update(delivered_lbs=99),
                   lambda r:r["evaluation"].update(high_need_coverage_pct=99),
                   lambda r:r["objective"].update(total=1),
                   lambda r:r.update(served_recipient_indices=[1])]
        for change in changes:
            record, model, protocol = fixture()
            change(record)
            with self.subTest(change=change):
                with self.assertRaises(ValueError):
                    replay_record(record, model, "unweighted", 1, protocol)

    def test_service_completion_and_arc_time_are_enforced(self):
        record, model, protocol = fixture()
        model["nodes"][2]["closes"] = 36
        with self.assertRaisesRegex(ValueError, "window"):
            replay_record(record, model, "unweighted", 1, protocol)
        record, model, protocol = fixture()
        record["routes"][0]["stops"][2].update(service_start=29,service_finish=36)
        with self.assertRaisesRegex(ValueError, "Travel"):
            replay_record(record, model, "unweighted", 1, protocol)

    def test_negative_ambient_inventory_is_rejected_even_if_totals_conserve(self):
        record, model, protocol = fixture()
        model["nodes"][2].update(total=-40,cold=0)
        record["routes"][0]["stops"][2].update(total_after=7,cold_after=25)
        record["routes"][0]["stops"][3].update(total_before=7,cold_before=25,total_after=7,cold_after=25)
        with self.assertRaisesRegex(ValueError, "cargo"):
            replay_record(record, model, "unweighted", 1, protocol)

    def test_malformed_node_and_noninteger_vehicle_fail_before_replay(self):
        for change in [lambda r:r["routes"][0]["stops"][1].update(node_index=99),
                       lambda r:r["routes"][0].update(vehicle_index=.5),
                       lambda r:r["routes"][0]["stops"][1].update(service_start=True)]:
            record, model, protocol = fixture()
            change(record)
            with self.assertRaises(ValueError):
                replay_record(record, model, "unweighted", 1, protocol)

    def test_duplicate_vehicle_is_not_a_complete_fleet(self):
        record, model, protocol = fixture()
        model["vehicles"].append(copy.deepcopy(model["vehicles"][0]))
        record["input"]["vehicles"] = 2
        record["routes"].append(copy.deepcopy(record["routes"][0]))
        with self.assertRaisesRegex(ValueError, "duplicate vehicle"):
            replay_record(record, model, "unweighted", 1, protocol)

    def test_visits_cannot_be_repeated_across_different_vehicles(self):
        record, model, protocol = fixture()
        model["vehicles"].append(copy.deepcopy(model["vehicles"][0]))
        record["input"]["vehicles"] = 2
        second = copy.deepcopy(record["routes"][0])
        second["vehicle_index"] = 1
        record["routes"].append(second)
        with self.assertRaisesRegex(ValueError, "Repeated visit"):
            replay_record(record, model, "unweighted", 1, protocol)


class SavedTableTests(unittest.TestCase):
    def write_incomplete_tables(self, output, record):
        failure = dict(policy="unweighted",config=dict(record["config"],jitter_seed=2),status="no_solution",
                       solver_status="ROUTING_FAIL",audit=dict(passed=False),evaluation=None)
        records = [record,failure]
        with (output/"runs.csv").open("w",newline="") as stream:
            writer=csv.DictWriter(stream,fieldnames=["policy","replicate_seed","status","solver_status","audit_passed"]+EVALUATION_METRICS)
            writer.writeheader()
            for r in records:
                writer.writerow(dict(policy=r["policy"],replicate_seed=r["config"]["jitter_seed"],status=r["status"],
                                     solver_status=r["solver_status"],audit_passed=r["audit"]["passed"],**(r["evaluation"] or {})))
        with (output/"summary.csv").open("w",newline="") as stream:
            writer=csv.DictWriter(stream,fieldnames=["policy","metric","expected_runs","valid_runs","failed_runs","median","min","max"])
            writer.writeheader()
            for metric in EVALUATION_METRICS:
                writer.writerow(dict(policy="unweighted",metric=metric,expected_runs=2,valid_runs=1,failed_runs=1))
        return records

    def test_failed_policy_remains_visible_without_headline_summary(self):
        record, _, protocol=fixture()
        protocol["replicate_seeds"]=[1,2]
        with tempfile.TemporaryDirectory() as directory:
            output=Path(directory)
            records=self.write_incomplete_tables(output,record)
            verify_tables(output,records,protocol)
            text=(output/"summary.csv").read_text().replace("2,1,1,,,", "2,1,1,1,1,1", 1)
            (output/"summary.csv").write_text(text)
            with self.assertRaisesRegex(ValueError,"Incomplete policy"):
                verify_tables(output,records,protocol)

    def test_missing_run_table_row_is_rejected(self):
        record, _, protocol=fixture()
        protocol["replicate_seeds"]=[1,2]
        with tempfile.TemporaryDirectory() as directory:
            output=Path(directory)
            records=self.write_incomplete_tables(output,record)
            lines=(output/"runs.csv").read_text().splitlines()
            (output/"runs.csv").write_text("\n".join(lines[:-1])+"\n")
            with self.assertRaisesRegex(ValueError,"missing/duplicate"):
                verify_tables(output,records,protocol)

    def test_source_checksum_change_prevents_replay(self):
        import hashlib
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);results=root/"results";results.mkdir()
            config=dict(policies=POLICIES,replicate_seeds=[1,2,3,4,5],recipient_limit=None,vehicle_limit=None)
            path=root/"protocol.json";path.write_text(json.dumps(config))
            (root/"source.txt").write_text("changed")
            manifest=dict(protocol=config,protocol_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                          input_sha256={"source.txt":"wrong"})
            (results/"manifest.json").write_text(json.dumps(manifest))
            with self.assertRaisesRegex(ValueError,"input checksum"):
                verify_benchmark(results,root,path)


if __name__ == "__main__":
    unittest.main()
