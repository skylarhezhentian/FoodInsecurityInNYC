"""Offline archive integrity and input-join checks; no geospatial extras required."""
import csv
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
import xml.etree.ElementTree as ET
import zipfile


ROOT = Path(__file__).resolve().parents[1]
FOOD = ROOT / "data/upstream/foodhelp"
spec = importlib.util.spec_from_file_location("reproduce_upstream", ROOT / "scripts/reproduce_upstream.py")
replay = importlib.util.module_from_spec(spec)
spec.loader.exec_module(replay)


def rows(path):
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


class PreprocessingPackageTests(unittest.TestCase):
    def test_archive_hashes_and_recorded_sanitization(self):
        manifest = json.loads((ROOT / "research/preprocessing/manifest.json").read_text())
        self.assertEqual(len(replay.source_hashes()), 51)
        changed = []
        for record in manifest["records"]:
            if record["transformations"]:
                changed.append(record["path"])
            else:
                self.assertEqual(record["source_sha256"], record["packaged_sha256"])
        self.assertEqual(set(changed), {
            "data/upstream/foodhelp/" + name + extension
            for name in ("food_help_programs", "efap_pfred_programs")
            for extension in (".csv", ".geojson")
        } | {"data/upstream/foodhelp/council_data/input/nyc_decennialcensusdata_2010_2020_change.xlsx"})

    def test_workbook_sanitization_preserves_every_nonmetadata_member(self):
        manifest = json.loads((ROOT / "research/preprocessing/manifest.json").read_text())
        record = next(row for row in manifest["records"] if row["path"].endswith(".xlsx"))
        change = record["transformations"][0]
        self.assertEqual(set(change["fields"]), {"creator", "lastModifiedBy"})
        with zipfile.ZipFile(ROOT / record["path"]) as workbook:
            expected = change["unchanged_zip_members_sha256"]
            self.assertEqual(set(workbook.namelist()), set(expected) | {"docProps/core.xml"})
            for name, digest in expected.items():
                self.assertEqual(hashlib.sha256(workbook.read(name)).hexdigest(), digest)
            fields = {node.tag.rsplit("}", 1)[-1] for node in ET.fromstring(workbook.read("docProps/core.xml"))}
            self.assertFalse({"creator", "lastModifiedBy"} & fields)

    def test_provider_redaction_and_csv_geojson_identity(self):
        excluded = {"org_phone", "Creator", "Editor", "fp_notes", "sk_notes", "dist_location_info"}
        for name, count in (("food_help_programs", 528), ("efap_pfred_programs", 842)):
            with self.subTest(snapshot=name):
                table = rows(FOOD / (name + ".csv"))
                features = json.loads((FOOD / (name + ".geojson")).read_text())["features"]
                self.assertEqual((len(table), len(features)), (count, count))
                self.assertEqual(len({row["FID"] for row in table}), count)
                self.assertFalse(excluded & set(table[0]))
                for row, feature in zip(table, features):
                    properties = feature["properties"]
                    self.assertFalse(excluded & set(properties))
                    self.assertEqual(row["FID"], str(properties["FID"]))
                    self.assertEqual(row["program"], properties["program"])
                    for coordinate in ("lat", "lon"):
                        self.assertEqual(float(row[coordinate]), float(properties[coordinate]))
                    for column in row:
                        if "_open" in column or "_close" in column:
                            self.assertEqual(row[column], properties[column] or "")

    def test_all_routing_recipients_join_preserved_provider_ids(self):
        provider = {row["FID"]: row for row in rows(FOOD / "efap_pfred_programs.csv")}
        pantries = json.loads((ROOT / "data/model/instance.json").read_text())["pantries"]
        self.assertEqual(len(pantries), 528)
        for pantry in pantries:
            row = provider[pantry["fid"]]
            self.assertEqual(pantry["name"], row["program"])
            self.assertEqual(pantry["lat"], float(row["lat"]))
            self.assertEqual(pantry["lon"], float(row["lon"]))

    def test_geographic_ids_and_recipient_equity_join(self):
        ntas = json.loads((FOOD / "analysis/data/nta_2020.geojson").read_text())["features"]
        tracts = json.loads((FOOD / "analysis/data/tracts_2020.geojson").read_text())["features"]
        nta_ids = {row["properties"]["nta2020"] for row in ntas}
        self.assertEqual(len(nta_ids), 262)
        self.assertEqual(len(tracts), 2325)
        self.assertEqual(len({row["properties"]["geoid"] for row in tracts}), 2325)
        self.assertTrue({row["properties"]["nta2020"] for row in tracts} <= nta_ids)
        equity = {row["nta2020"]: row for row in rows(FOOD / "analysis/output/nta_equity_index.csv")}
        self.assertEqual(len(equity), 197)
        self.assertTrue(set(equity) <= nta_ids)
        pantries = json.loads((ROOT / "data/model/instance.json").read_text())["pantries"]
        missing = []
        for index, pantry in enumerate(pantries):
            if pantry["nta"] not in equity:
                missing.append((index, pantry["nta"]))
                self.assertEqual((pantry["need_pct"], pantry["access_pct"]), (0.5, 0.5))
                self.assertEqual((pantry["need_t"], pantry["access_t"]), (0, 0))
                continue
            row = equity[pantry["nta"]]
            for name in ("need_pct", "access_pct", "equity_index"):
                self.assertEqual(pantry[name], round(float(row[name]), 3))
            for name in ("need_t", "access_t"):
                self.assertEqual(pantry[name], int(row[name]))
        self.assertEqual(missing, [(95, "BK0261")])

    def test_modified_archive_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "research/preprocessing").mkdir(parents=True)
            (root / "input.csv").write_bytes(b"original\n")
            record = {"path": "input.csv", "packaged_bytes": 9,
                      "packaged_sha256": hashlib.sha256(b"original\n").hexdigest()}
            (root / "research/preprocessing/manifest.json").write_text(json.dumps({"records": [record]}))
            self.assertEqual(len(replay.source_hashes(root)), 1)
            (root / "input.csv").write_bytes(b"modified\n")
            with self.assertRaisesRegex(ValueError, "differs from manifest"):
                replay.source_hashes(root)

    def test_output_cannot_overwrite_source_or_previous_run(self):
        with self.assertRaisesRegex(ValueError, "inside outputs"):
            replay.checked_output(FOOD)
        (ROOT / "outputs").mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=ROOT / "outputs") as directory:
            output = Path(directory)
            self.assertEqual(replay.checked_output(output), output.resolve())
            (output / "previous-result.json").write_text("{}")
            with self.assertRaisesRegex(ValueError, "new or empty"):
                replay.checked_output(output)

    def test_comparison_aligns_keys_and_reports_real_changes(self):
        with tempfile.TemporaryDirectory() as directory:
            saved, new = (Path(directory) / name for name in ("saved.csv", "new.csv"))
            saved.write_text("id,value,label\na,1,first\nb,2,second\n")
            new.write_text("id,value,label\nb,2,second\na,1.000000001,first\n")
            self.assertTrue(replay.compare_csv(saved, new, ["id"])["matches_at_tolerance"])
            new.write_text("id,value,label\nb,3,second\na,1,changed\n")
            result = replay.compare_csv(saved, new, ["id"])
            self.assertFalse(result["matches_at_tolerance"])
            self.assertEqual(result["difference_count"], 2)
            self.assertEqual(result["max_absolute_difference"], 1)
            new.write_text("id,value,label\na,1,first\na,2,second\n")
            with self.assertRaisesRegex(ValueError, "Duplicate comparison key"):
                replay.compare_csv(saved, new, ["id"])


if __name__ == "__main__":
    unittest.main()
