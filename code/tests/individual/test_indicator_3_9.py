"""Acceptance tests for indicator 3.9 multi-dimensional assessment."""

from __future__ import annotations

import unittest

from _support import assert_benchmark_contract
from governance.indicator_3_9 import assess, benchmark


class Indicator39Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.result = benchmark()

    def test_benchmark_meets_dimension_and_score_targets(self) -> None:
        assert_benchmark_contract(self, self.result, "3.9")
        metrics = self.result["metrics"]
        self.assertGreaterEqual(metrics["dimension_count"], 6)
        self.assertGreaterEqual(metrics["minimum_dimension"], 95.0)
        self.assertIn("referential_integrity", metrics["dimensions"])
        self.assertIn("truth_cell_accuracy", metrics["dimensions"])
        self.assertEqual(metrics["holoclean_truth_cells"], 19000)
        self.assertEqual(metrics["holoclean_error_cells"], 509)
        self.assertGreater(metrics["referential_checks"], 0)
        self.assertEqual(
            set(metrics["dataset_results"]),
            {"metropt3", "forda", "secom", "holoclean_hospital"},
        )
        for dataset, result in metrics["dataset_results"].items():
            for dimension, value in result["dimensions"].items():
                with self.subTest(dataset=dataset, dimension=dimension):
                    if value is not None:
                        self.assertGreaterEqual(value, 95.0)

    def test_master_data_violation_reduces_referential_integrity(self) -> None:
        records = [
            {"timestamp_ms": 1000, "equipment_id": "CNC-01", "work_order": "WO-1", "value": 1.0},
            {"timestamp_ms": 1001, "equipment_id": "UNKNOWN", "work_order": "WO-1", "value": 1.1},
        ]
        result = assess(
            records,
            reference_data={"equipment_id": {"CNC-01"}, "work_order": {"WO-1"}},
            reference_time_ms=1001,
        )
        self.assertEqual(result["dimensions"]["referential_integrity"], 75.0)
        self.assertEqual(result["evidence"]["referential_checks"], 4)

    def test_empty_input_has_zero_composite_score(self) -> None:
        result = assess([])
        self.assertEqual(result["overall"], 0.0)
        self.assertEqual(result["minimum"], 0.0)
        self.assertEqual(len(result["dimensions"]), 7)


if __name__ == "__main__":
    unittest.main(verbosity=2)
