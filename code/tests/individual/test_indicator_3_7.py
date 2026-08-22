"""Acceptance tests for indicator 3.7 sequence-relation fusion."""

from __future__ import annotations

import unittest

from _support import assert_benchmark_contract
from governance.indicator_3_7 import benchmark, fuse


class Indicator37Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.result = benchmark()

    def test_benchmark_produces_fused_rows(self) -> None:
        assert_benchmark_contract(self, self.result, "3.7")
        metrics = self.result["metrics"]
        self.assertEqual(metrics["fused_rows"], metrics["sequence_rows"])
        self.assertGreater(metrics["matched_rows"], 0)
        self.assertGreater(metrics["rows_per_second"], 0)

    def test_left_fusion_preserves_unmatched_samples(self) -> None:
        sequence = [
            {"equipment_id": "CNC-01", "timestamp_ms": 1000, "value": 42.0},
            {"equipment_id": "CNC-02", "timestamp_ms": 1000, "value": 43.0},
        ]
        relations = [
            {"equipment_id": "CNC-01", "start_ms": 900, "end_ms": 1100, "work_order": "WO-1"}
        ]
        result = fuse(sequence, relations, tolerance_ms=0)
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["relation_work_order"], "WO-1")
        self.assertTrue(result[0]["aligned"])
        self.assertFalse(result[1]["aligned"])
        self.assertNotIn("relation_work_order", result[1])


if __name__ == "__main__":
    unittest.main(verbosity=2)
