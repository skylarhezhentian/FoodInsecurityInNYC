import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))
from food_rescue.analysis import (METRICS, analyze_saved_results, compute_selection_metrics,
                                 validate_recipients)
from scripts.reproduce_results import OWNER, OWNER_FILE, check_output_directory


def recipients_fixture():
    return pd.DataFrame({"idx": [0, 1, 2, 3], "nta": ["A", "A", "B", "C"],
                         "borough": ["BX"] * 4, "need_pct": [.8, .8, .5, .2],
                         "access_pct": [.5] * 4, "need_tier": ["high", "high", "mid", "low"],
                         "demand_lbs": [90, 10, 100, 100], "cold_frac": [.2] * 4,
                         "w_gamma1": [2, 2, 1, .5]})


def payload_fixture(selected=None):
    selected = [0] if selected is None else selected
    # Independent known values for this hand-built fixture, avoiding use of the
    # implementation under test to generate its expected coverage.
    demand = [90, 10, 100, 100]
    weight = [2, 2, 1, .5]
    values = {"served": len(selected), "delivered_lbs": sum(demand[i] for i in selected),
              "high_need_pct": sum(demand[i] for i in selected if i < 2),
              "mid_need_pct": 100 if 2 in selected else 0,
              "low_need_pct": 100 if 3 in selected else 0,
              "nw_pct": round(100 * sum(demand[i] * weight[i] for i in selected) / 350, 2),
              "travel_min": 10}
    runs = [{**values, "rep": rep, "served_idx": list(selected)} for rep in range(5)]
    summary = {metric: {"median": values[metric], "min": values[metric], "max": values[metric],
                        "mean": values[metric], "n": 5} for metric in METRICS}
    return {"config": {"reps": 5}, "settings": {"Need-only": {
        "policy": "need_only", "gamma": None, "runs": runs, "summary": summary}}}


class CoverageTests(unittest.TestCase):
    def test_demand_weighted_coverage_is_not_recipient_count(self):
        frame = validate_recipients(recipients_fixture())
        result = compute_selection_metrics(frame, [0])
        self.assertEqual(result["high_need_pct"], 90)
        self.assertNotEqual(result["high_need_pct"], 50)
        self.assertAlmostEqual(result["nw_pct"], 100 * 180 / 350)

    def test_unequal_tiers_and_supplied_labels_are_preserved(self):
        frame = recipients_fixture()
        frame.loc[3, "need_pct"] = .5
        result = compute_selection_metrics(validate_recipients(frame), [3])
        self.assertEqual(result["low_need_pct"], 100)
        self.assertEqual(result["mid_need_pct"], 0)

    def test_empty_selection_has_zero_coverage(self):
        runs, summary, validation = analyze_saved_results(payload_fixture([]), recipients_fixture())
        self.assertTrue(runs.loc[runs.metric.ne("travel_min"), "value"].eq(0).all())
        self.assertTrue(summary.loc[summary.metric.ne("travel_min"), "median"].eq(0).all())
        self.assertEqual(validation["status"], "passed")

    def test_unrounded_values_feed_summaries_and_travel_is_labeled(self):
        runs, summary, validation = analyze_saved_results(payload_fixture(), recipients_fixture())
        expected = 100 * 180 / 350
        self.assertAlmostEqual(summary.loc[summary.metric.eq("nw_pct"), "mean"].iloc[0], expected)
        self.assertNotEqual(expected, round(expected, 2))
        self.assertTrue(runs.loc[runs.metric.eq("travel_min"), "source"].eq("stored_unverified").all())
        self.assertEqual(validation["joined_run_value_checks"], 30)
        self.assertEqual(validation["saved_summary_scalar_checks"], 35)

    def test_two_rounding_steps_do_not_discard_valid_unrounded_means(self):
        # The five weighted coverages round to 10,10,10,10,10.02. Their
        # stored mean then rounds again to10.00; the true mean is10.008.
        frame = pd.DataFrame({"idx": list(range(6)), "nta": ["A"] * 6, "borough": ["BX"] * 6,
                              "need_pct": [.8] * 4 + [.5, .2], "access_pct": [.5] * 6,
                              "need_tier": ["high"] * 4 + ["mid", "low"], "demand_lbs": [1] * 6,
                              "cold_frac": [0.] * 6, "w_gamma1": [10.004] * 4 + [10.024, 49.96]})
        runs = [{"served": 1, "delivered_lbs": 1, "travel_min": 10,
                 "high_need_pct": 25 if rep < 4 else 0,
                 "mid_need_pct": 0 if rep < 4 else 100, "low_need_pct": 0,
                 "nw_pct": 10.0 if rep < 4 else 10.02, "served_idx": [rep], "rep": rep}
                for rep in range(5)]
        summary = {}
        for metric in METRICS:
            values = [run[metric] for run in runs]
            summary[metric] = {"n": 5, "median": float(np.median(values)), "min": min(values),
                               "max": max(values), "mean": round(sum(values) / 5, 2)}
        payload = {"config": {"reps": 5}, "settings": {"Need-only": {
            "policy": "need_only", "gamma": None, "runs": runs, "summary": summary}}}
        _, result, _ = analyze_saved_results(payload, frame)
        row = result.loc[result.metric.eq("nw_pct")].iloc[0]
        self.assertAlmostEqual(row["mean"], 10.008)
        self.assertEqual(row["stored_mean"], 10.0)


class InputIntegrityTests(unittest.TestCase):
    def test_duplicate_recipient_indices_rejected(self):
        recipients = recipients_fixture()
        recipients.loc[1, "idx"] = 0
        with self.assertRaisesRegex(ValueError, "unique"):
            analyze_saved_results(payload_fixture(), recipients)

    def test_unknown_and_duplicate_served_indices_rejected(self):
        for bad in ([0, 99], [0, 0], [True], [0.0]):
            with self.subTest(bad=bad):
                payload = payload_fixture()
                payload["settings"]["Need-only"]["runs"][0]["served_idx"] = bad
                with self.assertRaises(ValueError):
                    analyze_saved_results(payload, recipients_fixture())

    def test_invalid_demand_and_nonfinite_scores_rejected(self):
        for column, value in (("demand_lbs", 0), ("demand_lbs", -1), ("need_pct", np.inf),
                              ("w_gamma1", np.nan), ("access_pct", 1.1), ("cold_frac", -.1)):
            with self.subTest(column=column, value=value):
                recipients = recipients_fixture()
                recipients.loc[0, column] = value
                with self.assertRaises(ValueError):
                    analyze_saved_results(payload_fixture(), recipients)

    def test_unknown_or_missing_tier_rejected(self):
        for tier in ("unknown", "high"):
            recipients = recipients_fixture()
            recipients.loc[3, "need_tier"] = tier
            with self.assertRaisesRegex(ValueError, "tier"):
                analyze_saved_results(payload_fixture(), recipients)

    def test_five_replicates_and_unique_rep_ids_required(self):
        payload = payload_fixture()
        payload["settings"]["Need-only"]["runs"].pop()
        with self.assertRaisesRegex(ValueError, "five"):
            analyze_saved_results(payload, recipients_fixture())
        payload = payload_fixture()
        payload["settings"]["Need-only"]["runs"][1]["rep"] = 0
        with self.assertRaisesRegex(ValueError, "replicate IDs"):
            analyze_saved_results(payload, recipients_fixture())

    def test_saved_run_metric_corruption_rejected(self):
        payload = payload_fixture()
        payload["settings"]["Need-only"]["runs"][0]["high_need_pct"] += .2
        with self.assertRaisesRegex(ValueError, "recipient join"):
            analyze_saved_results(payload, recipients_fixture())

    def test_summary_corruption_cannot_hide_behind_join_tolerance(self):
        payload = payload_fixture()
        payload["settings"]["Need-only"]["summary"]["nw_pct"]["median"] += .001
        with self.assertRaisesRegex(ValueError, "saved-run arithmetic"):
            analyze_saved_results(payload, recipients_fixture())

    def test_analysis_leaves_inputs_unchanged(self):
        payload, frame = payload_fixture(), recipients_fixture()
        original_payload, original_frame = copy.deepcopy(payload), frame.copy(deep=True)
        analyze_saved_results(payload, frame)
        self.assertEqual(payload, original_payload)
        pd.testing.assert_frame_equal(frame, original_frame)


class OutputProtectionTests(unittest.TestCase):
    def test_source_output_overlap_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "data" / "recipients.csv"
            for output in (source.parent, source.parent / "nested", source.parent.parent):
                with self.subTest(output=output):
                    with self.assertRaisesRegex(ValueError, "separate"):
                        check_output_directory(output, [source])

    def test_unrelated_directory_is_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "result"
            output.mkdir()
            sentinel = output / "notes.txt"
            sentinel.write_text("keep")
            with self.assertRaisesRegex(ValueError, "unrelated"):
                check_output_directory(output, [Path(directory) / "data" / "source.csv"])
            self.assertEqual(sentinel.read_text(), "keep")

    def test_owned_directory_accepts_extra_files_but_rejects_output_symlink(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            output = base / "result"
            output.mkdir()
            (output / OWNER_FILE).write_text(json.dumps({"owner": OWNER}))
            (output / "notes.txt").write_text("keep")
            source = base / "data" / "source.csv"
            self.assertEqual(check_output_directory(output, [source]), output.resolve())
            (output / "runs_long.csv").symlink_to(base / "other.csv")
            with self.assertRaisesRegex(ValueError, "symbolic"):
                check_output_directory(output, [source])


if __name__ == "__main__":
    unittest.main()
