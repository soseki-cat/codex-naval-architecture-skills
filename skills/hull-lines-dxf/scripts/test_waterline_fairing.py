from pathlib import Path
import csv
import json
import tempfile
import unittest

import numpy as np

from check_waterline_intersections import compare
from refit_waterlines import main as refit_main


ASSETS = Path(__file__).resolve().parents[1] / "assets"


class WaterlineFairingTests(unittest.TestCase):
    def test_refit_produces_ordered_rows_and_preserves_source(self):
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory) / "refit.csv"
            ledger = Path(directory) / "ledger.csv"
            summary = Path(directory) / "summary.json"
            code = refit_main(
                [
                    "--csv",
                    str(ASSETS / "mixed_half_breadths_original_mm.csv"),
                    "--config",
                    str(ASSETS / "mixed_parameters.json"),
                    "--corrections",
                    str(ASSETS / "mixed_corrections.json"),
                    "--out",
                    str(out),
                    "--ledger",
                    str(ledger),
                    "--summary",
                    str(summary),
                    "--approve-refit",
                ]
            )
            self.assertEqual(code, 0)
            with out.open(encoding="utf-8-sig", newline="") as stream:
                reader = csv.DictReader(stream)
                fields = reader.fieldnames[1:]
                rows = list(reader)
            for row in rows:
                known = [
                    float(row[field])
                    for field in fields
                    if row[field].strip() not in {"", "-", "?"}
                ]
                self.assertTrue(
                    all(right >= left for left, right in zip(known, known[1:]))
                )
            self.assertGreater(len(rows), 20)
            self.assertTrue(ledger.is_file())
            self.assertTrue(summary.is_file())

    def test_refit_requires_explicit_approval_before_writing(self):
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory) / "refit.csv"
            summary = Path(directory) / "summary.json"
            code = refit_main(
                [
                    "--csv",
                    str(ASSETS / "mixed_half_breadths_original_mm.csv"),
                    "--config",
                    str(ASSETS / "mixed_parameters.json"),
                    "--corrections",
                    str(ASSETS / "mixed_corrections.json"),
                    "--out",
                    str(out),
                    "--summary",
                    str(summary),
                ]
            )
            self.assertEqual(code, 2)
            self.assertFalse(out.exists())
            review = json.loads(summary.read_text(encoding="utf-8"))
            self.assertEqual(review["status"], "user_confirmation_required")
            self.assertTrue(review["approval_required"])

    def test_intersection_check_accepts_ordered_and_rejects_crossed_curves(self):
        x = np.linspace(1, 10, 101)
        ordered = [
            {"number": 1, "layer": "WL_1", "side": 1, "points": np.column_stack([x, x * 0.1])},
            {"number": 2, "layer": "WL_2", "side": 1, "points": np.column_stack([x, x * 0.2])},
        ]
        crossings, minimum = compare(ordered, 201)
        self.assertEqual(crossings, [])
        self.assertGreater(minimum, 0)

        crossed = [
            {"number": 1, "layer": "WL_1", "side": -1, "points": np.column_stack([x, -x * 0.2])},
            {"number": 2, "layer": "WL_2", "side": -1, "points": np.column_stack([x, -x * 0.1])},
        ]
        crossings, minimum = compare(crossed, 201)
        self.assertTrue(crossings)
        self.assertLess(minimum, 0)


if __name__ == "__main__":
    unittest.main()
