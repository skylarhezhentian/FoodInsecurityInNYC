#!/usr/bin/env python3
"""Run the bounded, offline routing demo on a declared subset of the package."""

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from food_rescue.routing import POLICIES, RoutingConfig, load_problem, solve_problem


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--recipients", type=int, default=20, help="First N recipients in stored input order (1–50)")
    parser.add_argument("--vehicles", type=int, default=3, help="First N vehicles in stored input order (1–10)")
    parser.add_argument("--time-limit", type=float, default=3, help="Seconds per policy (0–30)")
    parser.add_argument("--policies", nargs="+", choices=POLICIES, default=["unweighted", "need_only", "equity"])
    parser.add_argument("--output", type=Path, default=ROOT / "outputs/demo/routing_demo.json")
    args = parser.parse_args()
    if not 1 <= args.recipients <= 50 or not 1 <= args.vehicles <= 10 or not 0 < args.time_limit <= 30:
        parser.error("Demo is bounded to 1–50 recipients, 1–10 vehicles, and 0–30 seconds per policy")
    if len(set(args.policies)) != len(args.policies):
        parser.error("Policies must be unique")
    output = args.output.resolve()
    if ROOT.resolve() in output.parents and (ROOT / "outputs").resolve() not in output.parents:
        parser.error("Repository output must be inside outputs/ to protect source and model inputs")
    problem = load_problem(ROOT / "data/model", args.recipients, args.vehicles)
    config = RoutingConfig(time_limit_seconds=args.time_limit)
    runs = [solve_problem(problem, policy, config) for policy in args.policies]
    payload = {"purpose": "Current corrected-model demo; not the historical study or a policy-effect estimate",
               "selection": "First recipients and vehicles in packaged input order; all donor candidates",
               "model_manifest_sha256": hashlib.sha256((ROOT / "data/model/nodes.json").read_bytes()).hexdigest(),
               "runs": runs}
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, allow_nan=False) + "\n")
    for result in runs:
        metrics = result["metrics"]
        detail = f"{metrics['served_recipients']} recipients, {metrics['delivered_lbs']} lb" if metrics else "no returned solution"
        print(f"{result['policy']}: {result['status']}; {detail}; audit={result['audit']['passed']}")
    print(f"Saved {output}")
    return 0 if all(r["status"] == "solved" and r["audit"]["passed"] for r in runs) else 1


if __name__ == "__main__":
    raise SystemExit(main())
