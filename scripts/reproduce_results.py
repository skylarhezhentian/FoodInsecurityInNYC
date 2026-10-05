#!/usr/bin/env python3
"""Reproduce saved study tables locally; no solver or network is used."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
import tempfile

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from food_rescue.analysis import MAIN_SETTINGS, analyze_saved_results  # noqa: E402

OWNER_FILE = ".food_rescue_output.json"
OWNER = "food-rescue-saved-results-v1"
OUTPUT_NAMES = ("runs_long.csv", "summaries.csv", "main_strategy_summary.csv", "gamma_summary.csv", "validation.json", OWNER_FILE)


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def check_output_directory(output, sources):
    """Only replace named files in a new or previously owned output directory."""
    output = Path(output)
    if output.is_symlink():
        raise ValueError("Output directory must not be a symbolic link")
    resolved = output.resolve()
    for source in sources:
        source = Path(source).resolve()
        if resolved == source.parent or resolved in source.parents or source.parent in resolved.parents:
            raise ValueError("Output directory must be separate from source data")
    if output.exists():
        if not output.is_dir():
            raise ValueError("Output must be a directory")
        if any(output.iterdir()):
            marker = output / OWNER_FILE
            if not marker.is_file() or marker.is_symlink() or json.loads(marker.read_text()).get("owner") != OWNER:
                raise ValueError("Refusing to replace files in an unrelated output directory")
        if any((output / name).is_symlink() for name in OUTPUT_NAMES):
            raise ValueError("Generated output files must not be symbolic links")
    return resolved


def reproduce(data_dir, output_dir):
    data_dir = Path(data_dir).resolve()
    sources = [data_dir / "replicates.json", data_dir / "recipients.csv"]
    output = check_output_directory(output_dir, sources)
    before = {path.name: sha256(path) for path in sources}
    payload = json.loads(sources[0].read_text())
    recipients = pd.read_csv(sources[1])
    runs, summaries, validation = analyze_saved_results(payload, recipients, require_study_settings=True)
    after = {path.name: sha256(path) for path in sources}
    if before != after:
        raise RuntimeError("Source files changed during analysis")
    validation.update(input_sha256=before, inputs_unchanged=True)
    tables = {"runs_long.csv": runs, "summaries.csv": summaries,
              "main_strategy_summary.csv": summaries.loc[summaries.setting.isin(MAIN_SETTINGS)],
              "gamma_summary.csv": summaries.loc[summaries.setting.str.startswith("gamma=")]}
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".food-rescue-stage-", dir=output.parent) as directory:
        stage = Path(directory)
        for name, table in tables.items():
            table.to_csv(stage / name, index=False, float_format="%.12g")
        validation["output_sha256"] = {name: sha256(stage / name) for name in tables}
        (stage / "validation.json").write_text(json.dumps(validation, indent=2, allow_nan=False) + "\n")
        (stage / OWNER_FILE).write_text(json.dumps({"owner": OWNER}) + "\n")
        check_output_directory(output, sources)
        output.mkdir(parents=True, exist_ok=True)
        for name in OUTPUT_NAMES:
            (stage / name).replace(output / name)
    return validation


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=ROOT / "data" / "study")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "outputs" / "study")
    args = parser.parse_args()
    try:
        result = reproduce(args.data_dir, args.output_dir)
    except (ValueError, FileNotFoundError, RuntimeError) as error:
        parser.exit(1, f"Reanalysis failed: {error}\n")
    print(f"Validated {result['saved_runs']} saved runs and {result['saved_summary_scalar_checks']} summary values. "
          f"Tables: {args.output_dir}")


if __name__ == "__main__":
    main()
