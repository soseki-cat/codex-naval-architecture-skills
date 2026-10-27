"""Data-integrity regressions; execute with python -m unittest discover."""
import json
import tempfile
import unittest
from pathlib import Path

import numpy as np

try:
    from hull_data import load_bundle
except ImportError:
    load_bundle = None


class DataTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(load_bundle, "source-preserving load_bundle must exist")
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.csv = self.write("half.csv", "station,0WL,1000WL,2000WL\n0,0,100,200\n1,0,101,201\n2,0,102,202\n3,0,103,203\n")
        self.config = self.write("config.json", json.dumps({"half_breadth_to_m": .001, "waterline_heights_m": [0, 1, 2]}))

    def write(self, name, text):
        path = self.root / name
        path.write_text(text, encoding="utf-8")
        return path

    def config_update(self, **changes):
        data = json.loads(self.config.read_text())
        data.update(changes)
        self.config.write_text(json.dumps(data))

    def test_no_manifest_preserves_source_literals_and_zero(self):
        self.csv.write_text("station,0WL,1000WL,2000WL\n0,0,100.2500,?\n1,-,200,300\n", encoding="utf-8")
        self.config_update(corrections=[{"station": 0, "column": "1000WL", "value": 999}])
        bundle = load_bundle(self.csv, self.config)
        self.assertEqual(bundle.rows_original, bundle.rows_effective)
        self.assertEqual(bundle.rows_effective[0]["1000WL"], "100.2500")
        self.assertEqual(bundle.b[0, 0], 0)
        self.assertEqual(bundle.correction_report["status"], "not_requested")
        self.assertEqual(bundle.params["languages"], ["zh", "en"])
        self.assertTrue(all(record["uses"] == [] for record in bundle.inventory))

    def test_display_factor_never_supplies_physical_distance(self):
        self.config_update(longitudinal_display_units_per_station=10)
        bundle = load_bundle(self.csv, self.config)
        np.testing.assert_equal(bundle.x, [0, 10, 20, 30])
        self.assertFalse(bundle.physical)
        with self.assertRaisesRegex(ValueError, "3D export"):
            load_bundle(self.csv, self.config, skeleton=True)
        self.config_update(station_spacing_m=2)
        physical = load_bundle(self.csv, self.config, skeleton=True)
        np.testing.assert_equal(physical.x, [0, 2, 4, 6])

    def test_scientific_breadths_keep_units_and_suspicious_magnitude_text(self):
        self.csv.write_text("station,0WL,1000WL,2000WL\n0,0,1.25E+3,2.0E+12\n1,0,200,300\n")
        bundle=load_bundle(self.csv,self.config)
        self.assertEqual(bundle.b[0,1],1.25)
        self.assertTrue(np.isnan(bundle.b[0,2]))
        cell=next(c for c in bundle.inventory if c["raw"]=="2.0E+12")
        self.assertEqual(cell["status"],"needs_interpretation")
        self.assertEqual(cell["source_unit"],"mm")
        self.assertEqual(cell["conversion_to_m"],.001)
        self.assertEqual(bundle.rows_effective[0]["2000WL"],"2.0E+12")

    def test_failed_guard_keeps_authorized_value_batch_atomic(self):
        manifest=self.write("corrections.json",json.dumps([{"station":1,"column":"1000WL","method":"value","value":9E12}]))
        bundle=load_bundle(self.csv,self.config,corrections_json=manifest)
        self.assertEqual(bundle.correction_report["status"],"not_applied")
        self.assertEqual(bundle.rows_effective,bundle.rows_original)
        self.assertIn("interpretation guard",bundle.correction_report["failures"][0])

    def test_partial_station_table_keeps_documented_midship_split(self):
        self.config_update(LBP_m=100, station_AP=0, station_FP=20)
        bundle = load_bundle(self.csv, self.config)
        self.assertEqual(bundle.split, 50)
        self.assertLess(bundle.x[-1], bundle.split)
        self.config_update(body_split_x=60)
        self.assertEqual(load_bundle(self.csv, self.config).split, 60)

    def test_correction_does_not_bridge_unapproved_missing_cells(self):
        self.csv.write_text("station,0WL,1000WL,2000WL\n0,0,100,200\n1,0,?,201\n2,0,999,202\n3,0,103,203\n")
        correction = self.write("corrections.json", '[{"station":2,"column":"1000WL"}]')
        bundle = load_bundle(self.csv, self.config, corrections_json=correction)
        self.assertEqual(bundle.correction_report["status"], "not_applied")
        self.assertEqual(bundle.rows_effective, bundle.rows_original)

    def test_correction_support_stops_at_missing_interval_boundary(self):
        self.csv.write_text("station,0WL,1000WL,2000WL\n0,0,900,200\n1,0,?,201\n2,0,100,202\n3,0,999,203\n4,0,104,204\n5,0,106,205\n")
        correction = self.write("corrections.json", '[{"station":3,"column":"1000WL"}]')
        bundle = load_bundle(self.csv, self.config, corrections_json=correction)
        self.assertEqual(bundle.correction_report["status"], "applied")
        self.assertEqual(bundle.correction_report["targets"][0]["neighbor_evidence"], [[2, 100], [4, 104], [5, 106]])

    def test_mixed_profile_values_and_alignment_by_station(self):
        profile = self.write("profile.csv", "station,C.L,1000BL,2000BL\n3,0,1647…,2.16089E+12\n2,0,100.20,1e3\n1,0,2/3,?\n0,0,200,-\n")
        bundle = load_bundle(self.csv, self.config, profile_csv=profile)
        self.assertEqual(bundle.profile_half_widths, [0, 1, 2])
        self.assertEqual(bundle.profile_rows[0]["station"], "0")
        self.assertAlmostEqual(bundle.profile_values[2, 1], .1002)
        self.assertEqual(bundle.profile_values[2, 2], 1)
        self.assertTrue(np.isnan(bundle.profile_values[3, 2]))
        statuses = {r["raw"]: r["status"] for r in bundle.inventory if r["source"] == "profile"}
        self.assertEqual(statuses["2.16089E+12"], "needs_interpretation")
        self.assertEqual(statuses["1647…"], "text")
        self.assertEqual(statuses["2/3"], "text")

    def test_unknown_or_duplicate_supplementary_rows_are_rejected(self):
        for rows in ("0,1\n0,2\n", "9,1\n", "0,1\n1,2\n"):
            deck = self.write("deck.csv", "station,UPPER_DECK\n" + rows)
            with self.subTest(rows=rows), self.assertRaisesRegex(ValueError, "station|rows"):
                load_bundle(self.csv, self.config, deck_csv=deck)

    def test_atomic_batch_keeps_every_original_when_any_target_fails(self):
        correction = self.write("corrections.json", json.dumps([{"station": 1, "column": "1000WL", "method": "value", "value": 999}, {"station": 0, "column": "2000WL"}]))
        bundle = load_bundle(self.csv, self.config, corrections_json=correction)
        self.assertEqual(bundle.correction_report["status"], "not_applied")
        self.assertEqual(bundle.rows_effective, bundle.rows_original)
        self.assertTrue(bundle.correction_report["failures"])

    def test_all_targets_excluded_before_fitting_and_half_up_rounding(self):
        self.csv.write_text("station,0WL,1000WL,2000WL\n0,0,0,200\n1,0,999,201\n2,0,888,202\n3,0,7.5,203\n")
        correction = self.write("corrections.json", json.dumps({"targets": [{"station": 1, "column": "1000WL"}, {"station": 2, "column": "1000WL"}]}))
        bundle = load_bundle(self.csv, self.config, corrections_json=correction)
        self.assertEqual(bundle.correction_report["status"], "applied")
        self.assertEqual([r["1000WL"] for r in bundle.rows_effective], ["0", "3", "5", "7.5"])
        self.assertTrue(all(r["status"] == "estimated" for r in bundle.correction_report["targets"]))

    def test_missing_target_not_filled_and_value_estimate_rejects_negative(self):
        for target in ({"station": 7, "column": "1000WL"}, {"station": 1, "column": "1000WL", "method": "value", "value": -3}, {"station": 1, "column": "0WL", "method": "value", "value": "nan"}):
            correction = self.write("corrections.json", json.dumps([target]))
            self.assertEqual(load_bundle(self.csv, self.config, corrections_json=correction).correction_report["status"], "not_applied")
        self.csv.write_text("station,0WL,1000WL,2000WL\n0,0,100,200\n1,0,?,201\n2,0,102,202\n")
        correction = self.write("corrections.json", '[{"station":1,"column":"1000WL"}]')
        self.assertEqual(load_bundle(self.csv, self.config, corrections_json=correction).correction_report["status"], "not_applied")

    def test_tagged_station_requires_explicit_consistent_mapping(self):
        self.csv.write_text("station,0WL,1000WL,2000WL\n0(AP),0,100,200\n10(FP),0,200,300\n")
        with self.assertRaisesRegex(ValueError, "AP.*FP|mapping"):
            load_bundle(self.csv, self.config)
        self.config_update(station_AP=0, station_FP=10, LBP_m=100)
        bundle = load_bundle(self.csv, self.config)
        np.testing.assert_equal(bundle.x, [0, 100])
        self.config_update(station_AP=1)
        with self.assertRaisesRegex(ValueError, "AP|mapping"):
            load_bundle(self.csv, self.config)

    def test_transom_row_has_no_assumed_longitudinal_position(self):
        self.csv.write_text("station,0WL,1000WL,2000WL\nTRANSOM,-,30,50\n0,0,100,200\n1,0,200,300\n")
        bundle = load_bundle(self.csv, self.config)
        self.assertEqual(len(bundle.stations), 2)
        self.assertIsNone(bundle.transom["longitudinal_position"])
        self.assertEqual(bundle.transom["waterline_half_breadths_raw"]["1000WL"], "30")
        self.assertTrue(any(r["row"] == "TRANSOM" for r in bundle.inventory))

    def test_latest_fixture_four_estimates_and_514_values_preserved(self):
        fixture = Path(__file__).resolve().parents[1] / "assets"
        raw = fixture / "mixed_half_breadths_original_mm.csv"
        before = raw.read_bytes()
        bundle = load_bundle(raw, fixture / "mixed_parameters.json", profile_csv=fixture / "mixed_profile_heights_mm.csv", deck_csv=fixture / "mixed_deck_half_breadths_mm.csv", transom_json=fixture / "mixed_transom_mm.json", corrections_json=fixture / "mixed_corrections.json")
        self.assertEqual(bundle.correction_report["status"], "applied")
        self.assertEqual([int(t["fitted_raw"]) for t in bundle.correction_report["targets"]], [11122, 11085, 11072, 11059])
        unchanged = sum(1 for a, b in zip(bundle.rows_original, bundle.rows_effective) for f in bundle.fields if a[f] == b[f] and a[f] not in ("", "-", "?"))
        self.assertEqual(unchanged, 514)
        self.assertEqual(raw.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
