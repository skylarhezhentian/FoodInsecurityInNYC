"""Checks that the included research records retain their declared identity."""
import csv
import hashlib
import json
from pathlib import Path
import unittest

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"


class StudyPackageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = json.loads((DATA / "manifest.json").read_text())
        cls.instance = json.loads((DATA / "model/instance.json").read_text())
        cls.nodes = json.loads((DATA / "model/nodes.json").read_text())
        with (DATA / "model/donors.csv").open(newline="") as handle:
            cls.donors = list(csv.DictReader(handle))
        with (DATA / "study/recipients.csv").open(newline="") as handle:
            cls.recipients = list(csv.DictReader(handle))

    def test_original_data_hashes_and_sizes(self):
        self.assertEqual(len(self.manifest["files"]), 5)
        for record in self.manifest["files"] + [self.manifest["node_order"]]:
            with self.subTest(path=record["path"]):
                content = (DATA / record["path"]).read_bytes()
                self.assertEqual(len(content), record["bytes"])
                self.assertEqual(hashlib.sha256(content).hexdigest(), record["sha256"])

    def test_declared_current_node_order_and_coordinate_binding(self):
        expected = []
        for role, rows in (("depot", self.instance["origins"]),
                           ("donor", self.donors),
                           ("recipient", self.instance["pantries"])):
            for source_index, row in enumerate(rows):
                expected.append({
                    "matrix_index": len(expected), "role": role,
                    "source_index": source_index,
                    "source_id": str(row.get("fid", row["name"])),
                    "latitude": float(row["lat"]), "longitude": float(row["lon"]),
                })
        self.assertEqual(self.nodes["nodes"], expected)
        self.assertEqual(self.nodes["node_count"], 548)
        self.assertEqual(len(expected), self.nodes["node_count"])
        self.assertIn("assumed", self.nodes["status"])
        coordinates = np.asarray([[row["latitude"], row["longitude"]] for row in expected])
        self.assertTrue(np.isfinite(coordinates).all())
        self.assertTrue((np.abs(coordinates[:, 0]) <= 90).all())
        self.assertTrue((np.abs(coordinates[:, 1]) <= 180).all())
        for name, record in self.nodes["source_files"].items():
            content = (DATA / "model" / name).read_bytes()
            self.assertEqual(hashlib.sha256(content).hexdigest(), record["sha256"])

    def test_matrix_dimensions_units_and_basic_integrity(self):
        with np.load(DATA / "model/travel.npz", allow_pickle=False) as cache:
            self.assertEqual(set(cache.files), {"dist_km", "time_min_freeflow"})
            for name in cache.files:
                matrix = cache[name]
                self.assertEqual(matrix.shape, (self.nodes["node_count"],) * 2)
                self.assertTrue(np.isfinite(matrix).all())
                self.assertTrue((matrix >= 0).all())
                np.testing.assert_array_equal(np.diag(matrix), np.zeros(548))

    def test_saved_recipient_indices_and_reference_weights(self):
        self.assertEqual([int(row["idx"]) for row in self.recipients], list(range(528)))
        tier_names = {0: "low", 1: "mid", 2: "high"}
        weight_differences = 0
        for row in self.recipients:
            pantry = self.instance["pantries"][int(row["idx"])]
            for key in ("need_pct", "access_pct", "demand_lbs", "cold_frac"):
                self.assertEqual(float(row[key]), float(pantry[key]))
            self.assertEqual(row["nta"], pantry["nta"])
            self.assertEqual(row["borough"], pantry["boro"])
            self.assertEqual(row["need_tier"], tier_names[pantry["need_t"]])
            reference = round(max(0.5, min(4.0, (float(row["need_pct"]) + 0.15)
                                          / (float(row["access_pct"]) + 0.15))), 3)
            self.assertEqual(float(row["w_gamma1"]), reference)
            weight_differences += float(row["w_gamma1"]) != pantry["w"]
        self.assertEqual(weight_differences, 188)
        fallback = self.recipients[95]
        self.assertEqual((fallback["nta"], fallback["need_tier"]), ("BK0261", "low"))
        self.assertEqual(float(fallback["need_pct"]), 0.5)

    def test_historical_source_snapshot_hashes(self):
        historical = ROOT / "research/historical"
        manifest = json.loads((historical / "manifest.json").read_text())
        self.assertEqual(len(manifest["files"]), 6)
        modified = []
        for record in manifest["files"]:
            content = (historical / record["path"]).read_bytes()
            self.assertEqual(hashlib.sha256(content).hexdigest(), record["packaged_sha256"])
            if record["changes"]:
                modified.append(record["path"])
            else:
                self.assertEqual(record["original_sha256"], record["packaged_sha256"])
        self.assertEqual(modified, ["solve_routes_v1.py"])


if __name__ == "__main__":
    unittest.main()
