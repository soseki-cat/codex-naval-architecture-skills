"""Regression checks for geometry, source preservation and station assumptions."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import ezdxf

SCRIPT = Path(__file__).with_name("generate_hull_lines.py")


class HullLinesTests(unittest.TestCase):
    def generate(self, csv_text, params, skeleton=False):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        params = {"languages": ["en"], **params}
        (root / "input.csv").write_text(csv_text, encoding="utf-8")
        (root / "config.json").write_text(json.dumps(params), encoding="utf-8")
        command = [sys.executable, str(SCRIPT), "--csv", str(root / "input.csv"),
                   "--config", str(root / "config.json"), "--out", str(root / "out")]
        if skeleton:
            command += ["--skeleton3d"]
        result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8")
        return result, root / "out"

    def test_half_station_distance_and_origin_do_not_force_zero_breadth(self):
        result, out = self.generate(
            "station,WL0,WL1,WL2\n0,0,100,200\n0.5,50,150,250\n1,150,250,350\n2,0,20,80\n",
            {"waterline_heights_m": [0, 1, 2], "half_breadth_to_m": 0.001,
             "LBP_m": 20, "station_AP": 0, "station_FP": 2,
             "origin_station": 1, "buttock_half_breadths_m": [0.2]}, True)
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads((out / "validation.json").read_text())
        self.assertEqual(report["station_x"], [0, 5, 10, 20])
        doc = ezdxf.readfile(out / "hull_skeleton_3d.dxf")
        points = list(doc.modelspace().query('POINT[layer=="SOURCE_POINTS"]'))
        self.assertEqual(len(points), 12)
        self.assertTrue(any(abs(p.dxf.location.x) < 1e-9 and
                            abs(p.dxf.location.y - 0.15) < 1e-9 and
                            abs(p.dxf.location.z) < 1e-9 for p in points))
        self.assertFalse(any(abs(p.dxf.location.x) < 1e-9 and
                             abs(p.dxf.location.y) < 1e-9 and
                             abs(p.dxf.location.z) < 1e-9 for p in points))
        self.assertLess(report["source_spline_point_error"], 1e-7)

    def test_missing_cell_splits_curves_and_is_not_zero(self):
        result, out = self.generate(
            "station,WL0,WL1,WL2\n0,0,100,200\n1,150,,350\n2,0,20,80\n",
            {"waterline_heights_m": [0, 1, 2], "half_breadth_to_m": 0.001,
             "LBP_m": 20, "station_AP": 0, "station_FP": 2,
             "buttock_half_breadths_m": [0.2]}, True)
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads((out / "validation.json").read_text())
        self.assertEqual(report["source_point_count"], 8)
        self.assertEqual(report["missing_cell_count"], 1)
        self.assertEqual(report["buttock_piece_count"], 0)
        doc = ezdxf.readfile(out / "hull_skeleton_3d.dxf")
        self.assertEqual(len(doc.modelspace().query('SPLINE[layer=="ST_1"]')), 0)
        self.assertEqual(len(doc.modelspace().query('SPLINE[layer=="WL_1"]')), 0)

    def test_lbp_without_ap_fp_mapping_is_rejected(self):
        result, out = self.generate(
            "station,WL0,WL1\n0,0,100\n1,100,200\n2,0,50\n",
            {"waterline_heights_m": [0, 1], "half_breadth_to_m": 0.001, "LBP_m": 20})
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((out / "waterline_plan.dxf").exists())

    def test_normalized_station_axis_has_no_physical_3d_export(self):
        result, out = self.generate(
            "station,WL0,WL1\n0,0,100\n1,100,200\n2,0,50\n",
            {"waterline_heights_m": [0, 1], "half_breadth_to_m": 0.001}, True)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((out / "hull_skeleton_3d.dxf").exists())

    def test_explicit_station_positions_override_uniform_number_mapping(self):
        result, out = self.generate(
            "station,WL0,WL1\n0,0,100\n1,100,200\n2,0,50\n",
            {"waterline_heights_m": [0, 1], "half_breadth_to_m": 0.001,
             "station_x_m": [0, 3, 20]})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads((out / "validation.json").read_text())["station_x"], [0, 3, 20])

    def test_lower_buttock_keeps_unknown_interior_bottom_gap(self):
        result, out = self.generate(
            "station,WL0,WL1,WL2\n0,0,500,1000\n1,1000,1500,2000\n2,0,500,1000\n",
            {"waterline_heights_m": [0, 1, 2], "half_breadth_to_m": 0.001,
             "LBP_m": 20, "station_AP": 0, "station_FP": 2,
             "buttock_half_breadths_m": [0.5]})
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads((out / "validation.json").read_text())
        self.assertEqual(report["buttock_piece_count"], 2)
        intervals = report["buttock_domains"]["0.5"]
        self.assertLess(intervals[0][1], intervals[1][0])

    def test_coincident_buttock_plane_is_reported_without_losing_other_views(self):
        result, out = self.generate(
            "station,WL0,WL0.3,WL1\n0,100,100,200\n1,100,100,200\n2,100,100,200\n",
            {"waterline_heights_m": [0, 0.3, 1], "half_breadth_to_m": 0.001,
             "LBP_m": 20, "station_AP": 0, "station_FP": 2,
             "buttock_half_breadths_m": [0.1]})
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads((out / "validation.json").read_text())
        self.assertEqual(report["buttock_piece_count"], 0)
        self.assertNotEqual(report["buttock_status"], "generated")
        self.assertEqual(report["source_point_count"], 9)
        self.assertGreater(report["files"]["body_plan.dxf"]["splines"], 0)
        self.assertGreater(report["files"]["waterline_plan.dxf"]["splines"], 0)

    def test_waterline_crossing_inside_a_short_station_interval_is_not_missed(self):
        result, out = self.generate(
            "station,WL0,WL1\n"
            "0,.8390495621924157,.844692675773431\n"
            "1,.1293099846572826,.1301502812036784\n"
            "2,.06238604509608048,.08733843665421097\n"
            "3,.1081431390573181,.11946055137903655\n"
            "4,.08424475644417895,.1527689692551654\n",
            {"waterline_heights_m": [0, 1], "half_breadth_to_m": 1,
             "station_x_m": [0, 1e-8, 2e-8, 3e-8, 1],
             "buttock_half_breadths_m": [0.12]})
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads((out / "validation.json").read_text())
        self.assertEqual(report["buttock_piece_count"], 0)
        self.assertNotEqual(report["buttock_status"], "generated")
        self.assertEqual(report["source_point_count"], 10)

    def test_partial_aft_station_table_uses_known_lbp_midship_split(self):
        result, out = self.generate(
            "station,WL0,WL1\n0,0,100\n0.5,50,150\n1,150,350\n",
            {"waterline_heights_m": [0, 1], "half_breadth_to_m": 0.001,
             "LBP_m": 100, "station_AP": 0, "station_FP": 10})
        self.assertEqual(result.returncode, 0, result.stderr)
        doc = ezdxf.readfile(out / "body_plan.dxf")
        pts = list(doc.modelspace().query('POINT[layer=="SOURCE_ST_1"]'))
        self.assertEqual(len(pts), 2)
        self.assertTrue(all(p.dxf.location.x < 0 for p in pts))


if __name__ == "__main__":
    unittest.main()
