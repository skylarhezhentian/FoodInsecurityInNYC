"""Poster-source selection, historical metric definitions, and input integrity."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.reproduce_poster_figures import (POLICIES, check_distribution, check_robustness,
                                              metrics_for, poster_tables, priority_points, validate_output,
                                              MARKER, OWNER)


class OutputProtectionTests(unittest.TestCase):
    def test_generated_figures_cannot_replace_published_or_source_files(self):
        for path in (ROOT/"results/poster", ROOT/"data/study", ROOT/"research/experiments", ROOT/"outputs"):
            with self.subTest(path=path), self.assertRaisesRegex(ValueError,"subdirectory of outputs"):
                validate_output(path)

    def test_unrelated_nonempty_directory_is_preserved(self):
        with tempfile.TemporaryDirectory() as folder, patch("scripts.reproduce_poster_figures.ROOT",Path(folder).resolve()):
            output=Path(folder).resolve()/"outputs/figures"
            output.mkdir(parents=True)
            (output/"keep.txt").write_text("not generated")
            with self.assertRaisesRegex(ValueError,"unrelated"):
                validate_output(output)
            self.assertEqual((output/"keep.txt").read_text(),"not generated")
            (output/MARKER).write_text(json.dumps({"owner":OWNER}))
            self.assertEqual(validate_output(output),output.resolve())

    def test_symlink_parent_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder, patch("scripts.reproduce_poster_figures.ROOT",Path(folder).resolve()):
            base=Path(folder).resolve()
            (base/"outputs").mkdir()
            (base/"source").mkdir()
            (base/"outputs/link").symlink_to(base/"source",target_is_directory=True)
            with self.assertRaisesRegex(ValueError,"symlink"):
                validate_output(base/"outputs/link/figures")


class PosterFigureSourceTests(unittest.TestCase):
    def test_map_preserves_original_weight_instead_of_recalculating_study_weight(self):
        instance={"pantries":[dict(lon=-74,lat=40.7,need_pct=.944,access_pct=.619,demand_lbs=336,w=1.422)]}
        recipients=pd.DataFrame([dict(idx=0,need_pct=.944,access_pct=.619,demand_lbs=336,w_gamma1=1.423)])
        points=priority_points(instance,recipients)
        self.assertEqual(points.poster_weight.iloc[0],1.422)
        self.assertEqual(points.study_reference_weight.iloc[0],1.423)

    def test_map_study_cohort_mismatch_fails(self):
        instance={"pantries":[dict(lon=-74,lat=40.7,need_pct=.8,access_pct=.5,demand_lbs=100,w=1.4)]}
        recipients=pd.DataFrame([dict(idx=0,need_pct=.8,access_pct=.5,demand_lbs=101,w_gamma1=1.4)])
        with self.assertRaisesRegex(ValueError,"demand_lbs"):
            priority_points(instance,recipients)

    def test_final_poster_uses_replicated_sweep_including_gamma_zero(self):
        payload=json.loads((ROOT/"data/study/replicates.json").read_text())
        table,curve=poster_tables(payload)
        self.assertEqual(curve.gamma.tolist(),[0,.25,.5,.75,1,1.5,2,3])
        self.assertEqual(curve.loc[curve.gamma.eq(0),"sites"].iloc[0],231)
        # The earlier single-run sweep has gamma1 high coverage46.9; it is not
        # the poster's replicated evidence (44.1).
        self.assertEqual(curve.loc[curve.gamma.eq(1),"coverage"].iloc[0],44.1)
        row=table.loc[table.strategy.eq("Need-only")&table.metric.eq("high_need_pct")].iloc[0]
        self.assertEqual(row.poster_display,"58")


class EarlierAnalysisTests(unittest.TestCase):
    def test_historical_deciles_split_ties_in_stored_recipient_order(self):
        # Preserve this archival convention explicitly; it is not a claim that
        # identical neighborhood need scores form distinct substantive groups.
        need=np.full(20,.5);demand=np.ones(20);nta=[str(i) for i in range(20)]
        result=metrics_for([0,1],need,demand,nta)
        self.assertEqual(result["coverage_by_need_decile_pct"],[100.]+[0.]*9)

    def test_distribution_reanalysis_matches_all_saved_modes_without_mutation(self):
        base=ROOT/"research/experiments"
        solution=json.loads((base/"single_run/ch_solution.json").read_text())
        saved=json.loads((base/"distribution/distributional_metrics.json").read_text())
        original=copy.deepcopy(solution)
        self.assertEqual(check_distribution(solution,saved),saved)
        self.assertEqual(solution,original)
        solution["mode_A"]["unweighted"]["served_idx"].append(solution["mode_A"]["unweighted"]["served_idx"][0])
        with self.assertRaisesRegex(ValueError,"Invalid historical"):
            check_distribution(solution,saved)

    def test_robustness_uses_population_sd_and_detects_changed_summary(self):
        worlds=[{policy:{metric:value for metric in ("served","nw","high","delivered")}
                 for policy in POLICIES} for value in (1,3)]
        aggregates={policy:{metric:dict(mean=2.,sd=1.,min=1.,max=3.)
                            for metric in ("served","nw","high","delivered")} for policy in POLICIES}
        saved={"worlds":worlds,"args":{"worlds":2},"agg":aggregates,"stability":{
            "equity leads need-weighted cov":"0/2","need_only leads high-need tier cov":"0/2",
            "equity leads high-need tier cov":"0/2","equity lowest agencies served":"0/2"}}
        self.assertEqual(check_robustness(saved)["aggregate_values_checked"],80)
        saved["agg"]["unweighted"]["served"]["sd"]=1.4
        with self.assertRaisesRegex(ValueError,"statistics disagree"):
            check_robustness(saved)


if __name__ == "__main__":
    unittest.main()
