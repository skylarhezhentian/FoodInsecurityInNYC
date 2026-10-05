#!/usr/bin/env python3
"""Replay recovered preprocessing offline in a fresh output directory."""
from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.metadata
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
ARCHIVE = ROOT / "research/preprocessing"
UPSTREAM = ROOT / "data/upstream"
STAGES = ("community", "nta", "e2sfca", "donors")
MAP_SCRIPTS = {"community": "build_food_access_map.py", "nta": "build_food_access_map_nta.py",
               "e2sfca": "build_e2sfca_index.py"}


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def source_hashes(root=ROOT):
    manifest = json.loads((root / "research/preprocessing/manifest.json").read_text())
    hashes = {}
    for record in manifest["records"]:
        path = root / record["path"]
        if path.is_symlink() or not path.is_file():
            raise ValueError(f"Missing or symbolic source file: {record['path']}")
        digest = sha256(path)
        if digest != record["packaged_sha256"] or path.stat().st_size != record["packaged_bytes"]:
            raise ValueError(f"Source snapshot differs from manifest: {record['path']}")
        hashes[record["path"]] = digest
    return hashes


def checked_output(path):
    raw = Path(path)
    output = raw.resolve()
    if (raw.is_symlink() or (ROOT / "outputs").is_symlink()
            or not output.is_relative_to((ROOT / "outputs").resolve())):
        raise ValueError("Choose an output directory inside outputs/, separate from source snapshots")
    if output.exists() and (not output.is_dir() or any(output.iterdir())):
        raise ValueError("Output directory must be new or empty; choose another --output-dir")
    return output


def compare_values(saved, new, path="", differences=None):
    differences = [] if differences is None else differences
    if isinstance(saved, dict) and isinstance(new, dict):
        if set(saved) != set(new):
            differences.append({"field": path, "kind": "keys", "saved": sorted(saved), "new": sorted(new)})
        for key in saved.keys() & new.keys():
            compare_values(saved[key], new[key], f"{path}.{key}", differences)
    elif isinstance(saved, list) and isinstance(new, list):
        if len(saved) != len(new):
            differences.append({"field": path, "kind": "length", "saved": len(saved), "new": len(new)})
        for index, (left, right) in enumerate(zip(saved, new)):
            compare_values(left, right, f"{path}[{index}]", differences)
    elif isinstance(saved, (int, float)) and isinstance(new, (int, float)):
        if not math.isclose(saved, new, rel_tol=1e-8, abs_tol=1e-10):
            differences.append({"field": path, "kind": "numeric", "saved": saved, "new": new,
                                "absolute_difference": abs(saved - new)})
    elif saved != new:
        differences.append({"field": path, "kind": "value", "saved": saved, "new": new})
    return differences


def compare_csv(saved_path, new_path, keys):
    def read(path):
        with path.open(newline="", encoding="utf-8-sig") as handle:
            reader = csv.DictReader(handle)
            columns = reader.fieldnames
            result = {}
            for row in reader:
                key = tuple(row[name] for name in keys)
                if key in result:
                    raise ValueError(f"Duplicate comparison key {key} in {path.name}")
                result[key] = row
            return columns, result
    saved_columns, saved = read(saved_path)
    new_columns, new = read(new_path)
    differences = []
    if saved_columns != new_columns:
        differences.append({"kind": "columns", "saved": saved_columns, "new": new_columns})
    if set(saved) != set(new):
        differences.append({"kind": "row_keys", "saved_only": sorted(set(saved) - set(new)),
                            "new_only": sorted(set(new) - set(saved))})
    numeric_cells = 0
    max_absolute_difference = 0.0
    for key in sorted(set(saved) & set(new)):
        for column in set(saved_columns) & set(new_columns):
            left, right = saved[key][column], new[key][column]
            try:
                a, b = float(left), float(right)
            except (ValueError, TypeError):
                if left != right:
                    differences.append({"kind": "value", "row": key, "column": column,
                                        "saved": left, "new": right})
                continue
            numeric_cells += 1
            if not (math.isfinite(a) and math.isfinite(b)):
                if not (math.isnan(a) and math.isnan(b)):
                    differences.append({"kind": "nonfinite", "row": key, "column": column})
                continue
            delta = abs(a - b)
            max_absolute_difference = max(max_absolute_difference, delta)
            if not math.isclose(a, b, rel_tol=1e-8, abs_tol=1e-10):
                differences.append({"kind": "numeric", "row": key, "column": column,
                                    "saved": a, "new": b, "absolute_difference": delta})
    return {"saved_rows": len(saved), "new_rows": len(new), "numeric_cells_compared": numeric_cells,
            "max_absolute_difference": max_absolute_difference, "difference_count": len(differences),
            "differences": differences, "matches_at_tolerance": not differences,
            "byte_identical": saved_path.read_bytes() == new_path.read_bytes()}


def replay(stage, output):
    output = checked_output(output)
    before = source_hashes()
    output.mkdir(parents=True, exist_ok=True)
    work = output / "work"
    work.mkdir()
    chosen = STAGES if stage == "all" else (stage,)
    commands = []
    if set(chosen) & set(MAP_SCRIPTS):
        food = work / "foodhelp"
        shutil.copytree(UPSTREAM / "foodhelp", food,
                        ignore=lambda directory, names: {"output"} if Path(directory).name == "analysis" else set())
        shutil.copytree(ARCHIVE / "foodhelp/analysis", food / "analysis", dirs_exist_ok=True)
        for name in chosen:
            if name in MAP_SCRIPTS:
                commands.append((name, food / "analysis" / MAP_SCRIPTS[name]))
    if "donors" in chosen:
        donor = work / "donor_model"
        shutil.copytree(ARCHIVE / "donor_model/src", donor / "src")
        (donor / "data").mkdir()
        shutil.copyfile(UPSTREAM / "donor_model/data/nyc_boroughs.geojson", donor / "data/nyc_boroughs.geojson")
        for name in ("run_pipeline.py", "figures.py", "fig_steps12.py", "fig_step3.py", "fig_step3_map.py"):
            commands.append(("donors", donor / "src" / name))
    env = dict(os.environ, MPLBACKEND="Agg", PYTHONDONTWRITEBYTECODE="1", PROJ_NETWORK="OFF",
               MPLCONFIGDIR=os.environ.get("MPLCONFIGDIR", str(output / "cache/matplotlib")))
    logs = output / "logs"
    logs.mkdir()
    command_results = []
    for name, script in commands:
        print(f"Running {name}: {script.name}", flush=True)
        result = subprocess.run([sys.executable, str(script)], cwd=script.parent, env=env,
                                capture_output=True, text=True)
        (logs / f"{script.stem}.log").write_text(result.stdout + result.stderr)
        command_results.append({"stage": name, "script": script.name, "returncode": result.returncode})
        if result.returncode:
            raise RuntimeError(f"{script.name} failed; inspect {logs / (script.stem + '.log')}")
    comparisons = {}
    for name, filename, keys in (("community", "cd_summary.csv", ["boro_cd"]),
                                  ("nta", "nta_summary.csv", ["nta2020"]),
                                  ("e2sfca", "nta_equity_index.csv", ["nta2020"])):
        if name in chosen:
            comparisons[name] = compare_csv(UPSTREAM / "foodhelp/analysis/output" / filename,
                                             work / "foodhelp/analysis/output" / filename, keys)
    if "donors" in chosen:
        comparisons["donor_table"] = compare_csv(UPSTREAM / "donor_model/data/per_donor_estimates.csv",
                                                  work / "donor_model/data/per_donor_estimates.csv", ["tier", "name"])
        saved = json.loads((UPSTREAM / "donor_model/data/results.json").read_text())
        new = json.loads((work / "donor_model/data/results.json").read_text())
        differences = compare_values(saved, new)
        comparisons["donor_results"] = {"matches_at_tolerance": not differences,
                                        "difference_count": len(differences), "differences": differences}
    after = source_hashes()
    report = {"stage": stage, "runtime": {"python": sys.version, "packages": {
        name: importlib.metadata.version(name) for name in ("numpy", "pandas", "geopandas", "shapely",
                                                            "pyproj", "pyogrio", "openpyxl", "matplotlib")}},
        "source_hashes": before, "sources_unchanged": before == after, "commands": command_results,
        "comparisons": comparisons, "numeric_tolerance": {"relative": 1e-8, "absolute": 1e-10},
        "all_compared_tables_match": all(row["matches_at_tolerance"] for row in comparisons.values()),
        "scope": "Offline replay of recovered preprocessing. Matching saved tables does not establish historical source revision identity or validate scenario assumptions."}
    (output / "validation.json").write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
    if not report["sources_unchanged"]:
        raise RuntimeError("Source snapshots changed during replay")
    print(f"Source snapshots unchanged. Saved-table match: {report['all_compared_tables_match']}. Report: {output / 'validation.json'}")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", choices=("all",) + STAGES, default="all")
    parser.add_argument("--output", "--output-dir", dest="output_dir", type=Path, default=ROOT / "outputs/upstream")
    args = parser.parse_args()
    try:
        result = replay(args.stage, args.output_dir)
    except (ValueError, OSError, RuntimeError) as error:
        parser.exit(1, f"Preprocessing replay failed: {error}\n")
    return 0 if result["all_compared_tables_match"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
