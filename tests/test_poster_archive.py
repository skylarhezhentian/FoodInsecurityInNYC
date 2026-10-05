"""Protect the supplied poster and archived source bytes during publication."""

import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.verify_poster_archive import verify_archive


def record(name, data):
    return {"path": name, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}


class PosterArchiveTests(unittest.TestCase):
    def fixture(self, root):
        source = root / "poster/source"
        source.mkdir(parents=True)
        poster = b"stand-in poster bytes"
        (root / "poster/original.pdf").write_bytes(poster)
        (source / "TEMPLATE_README.md").write_bytes(b"template attribution")
        entry = record("TEMPLATE_README.md", b"template attribution")
        entry["source_entry"] = "README.md"
        source_manifest = {"supplied_pdf_sha256": hashlib.sha256(poster).hexdigest(),
                           "copied_entries": {"TEMPLATE_README.md": entry}}
        (source / "manifest.json").write_text(json.dumps(source_manifest))
        files = [record(p.relative_to(root).as_posix(), p.read_bytes()) for p in sorted(root.rglob("*")) if p.is_file()]
        manifest = {"schema_version": 1, "files": files, "original_poster": record("poster/original.pdf", poster),
                    "source_archive_manifest": "poster/source/manifest.json"}
        (root / "poster/manifest.json").write_text(json.dumps(manifest))
        return manifest

    def test_relocated_template_preserves_original_source_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.fixture(root)
            result = verify_archive(root)
            self.assertEqual(result["files_verified"], 3)
            self.assertEqual(result["source_entries_verified"], 1)

    def test_changed_poster_or_source_is_rejected(self):
        for name in ("poster/original.pdf", "poster/source/TEMPLATE_README.md"):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                self.fixture(root)
                (root / name).write_bytes(b"replacement")
                with self.assertRaisesRegex(ValueError, "differs from recorded bytes"):
                    verify_archive(root)

    def test_inventory_cannot_leave_repository_or_repeat_a_path(self):
        for mode in ("escape", "duplicate"):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                manifest = self.fixture(root)
                if mode == "escape":
                    manifest["files"][0]["path"] = "../elsewhere"
                else:
                    manifest["files"].append(manifest["files"][0])
                (root / "poster/manifest.json").write_text(json.dumps(manifest))
                with self.assertRaises(ValueError):
                    verify_archive(root)

    def test_committed_archive_matches_manifest(self):
        result = verify_archive()
        self.assertEqual(result["status"], "passed")
        self.assertEqual(result["source_entries_verified"], 17)


if __name__ == "__main__":
    unittest.main()
