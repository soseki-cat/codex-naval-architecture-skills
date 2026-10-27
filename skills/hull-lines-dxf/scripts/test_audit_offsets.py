from types import SimpleNamespace
import unittest

import numpy as np

from audit_offsets import audit


class OffsetAuditTests(unittest.TestCase):
    def test_audit_flags_spike_and_reversed_waterline_without_modifying_input(self):
        bundle = SimpleNamespace(
            inventory=[],
            fields=["WL1", "WL2", "WL3"],
            rows_effective=[{"station": "0"}, {"station": "1"}, {"station": "2"}],
            stations=np.array([0.0, 1.0, 2.0]),
            b=np.array(
                [
                    [1.0, 2.0, 3.0],
                    [4.0, 0.1, 4.2],
                    [3.0, 4.0, 5.0],
                ]
            ),
        )
        before = bundle.b.copy()
        report = audit(bundle, spike_ratio=0.35, spike_absolute_mm=500, order_drop_mm=100)
        self.assertEqual(report["status"], "user_confirmation_required")
        self.assertFalse(report["drawing_allowed"])
        self.assertTrue(
            any(item["type"] == "waterline_order_inversion" for item in report["findings"])
        )
        self.assertTrue(
            any(item["type"] == "longitudinal_spike" for item in report["findings"])
        )
        np.testing.assert_array_equal(bundle.b, before)

    def test_audit_clear_for_ordered_data(self):
        bundle = SimpleNamespace(
            inventory=[],
            fields=["WL1", "WL2", "WL3"],
            rows_effective=[{"station": "0"}, {"station": "1"}, {"station": "2"}],
            stations=np.array([0.0, 1.0, 2.0]),
            b=np.array(
                [
                    [1.0, 2.0, 3.0],
                    [2.0, 3.0, 4.0],
                    [2.5, 3.5, 4.5],
                ]
            ),
        )
        report = audit(bundle, spike_ratio=0.35, spike_absolute_mm=500, order_drop_mm=100)
        self.assertEqual(report["status"], "clear")
        self.assertTrue(report["drawing_allowed"])


if __name__ == "__main__":
    unittest.main()
