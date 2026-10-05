#!/usr/bin/env python3
"""Check the poster research archive against its committed file inventory."""

import argparse
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def checked_path(root, name):
    if not isinstance(name, str) or not name or Path(name).is_absolute() or ".." in Path(name).parts:
        raise ValueError(f"Archive path must be relative and contained: {name}")
    path = (root / name).resolve()
    if not path.is_relative_to(root.resolve()):
        raise ValueError(f"Archive path leaves repository: {name}")
    return path


def check_file(path, expected, label):
    raw = path.read_bytes()
    if len(raw) != expected["bytes"] or hashlib.sha256(raw).hexdigest() != expected["sha256"]:
        raise ValueError(f"Archive file differs from recorded bytes: {label}")
    return len(raw)


def verify_archive(root=ROOT, manifest_path=None):
    root = Path(root).resolve()
    manifest_path = manifest_path or root / "poster/manifest.json"
    manifest = json.loads(Path(manifest_path).read_text())
    if manifest["schema_version"] != 1 or not manifest["files"]:
        raise ValueError("Expected nonempty version-one poster inventory")
    seen, total = set(), 0
    for entry in manifest["files"]:
        name = entry["path"]
        if name in seen:
            raise ValueError(f"Duplicate archive path: {name}")
        seen.add(name)
        total += check_file(checked_path(root, name), entry, name)
    poster = manifest["original_poster"]
    if poster["path"] not in seen:
        raise ValueError("Original poster must be part of the archive inventory")
    check_file(checked_path(root, poster["path"]), poster, poster["path"])
    source_manifest_path = checked_path(root, manifest["source_archive_manifest"])
    if manifest["source_archive_manifest"] not in seen:
        raise ValueError("Source archive manifest must be inventoried")
    source_manifest = json.loads(source_manifest_path.read_text())
    if source_manifest["supplied_pdf_sha256"] != poster["sha256"]:
        raise ValueError("Poster and source archive identify different PDFs")
    for name, entry in source_manifest["copied_entries"].items():
        path = checked_path(source_manifest_path.parent, name)
        relative = path.relative_to(root).as_posix()
        if relative not in seen:
            raise ValueError(f"Source entry is absent from overall archive: {relative}")
        check_file(path, entry, relative)
    return {"status": "passed", "files_verified": len(seen), "bytes_verified": total,
            "source_entries_verified": len(source_manifest["copied_entries"]),
            "original_poster_sha256": poster["sha256"],
            "scope": "File integrity and original poster/source identity. Does not re-solve models, rebuild the PDF, or validate every historical claim."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "outputs/poster/archive_verification.json")
    args = parser.parse_args()
    output = args.output.resolve()
    if not output.is_relative_to((ROOT / "outputs").resolve()):
        parser.error("Verification output must stay inside outputs/")
    try:
        result = verify_archive()
    except (OSError, ValueError, KeyError, TypeError) as exc:
        parser.exit(1, f"Archive verification failed: {exc}\n")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2) + "\n")
    print(f"Verified {result['files_verified']} archive files and {result['source_entries_verified']} original source entries.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
