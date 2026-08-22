"""Acceptance tests for indicator 3.6 quality control."""

from __future__ import annotations

import unittest

from _support import assert_benchmark_contract
from governance.indicator_3_6 import benchmark, evaluate_quality


class Indicator36Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.result = benchmark()

    def test_benchmark_meets_all_quality_targets(self) -> None:
        assert_benchmark_contract(self, self.result, "3.6")
        metrics = self.result["metrics"]
        for name in ("completeness", "consistency", "timeliness", "validity"):
            with self.subTest(dimension=name):
                self.assertGreaterEqual(metrics[name], 95.0)
        self.assertGreaterEqual(metrics["minimum_dimension"], 95.0)

    def test_timeliness_uses_explicit_reference_time(self) -> None:
        records = [{"timestamp_ms": 1, "equipment_id": "CNC-01", "value": 42.0}]
        result = evaluate_quality(records, reference_time_ms=10_000, max_age_ms=100)
        self.assertEqual(result["timeliness"], 0.0)
        self.assertEqual(result["completeness"], 100.0)

    def test_invalid_quality_input_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            evaluate_quality([1])  # type: ignore[list-item]
        with self.assertRaises(ValueError):
            evaluate_quality([], max_age_ms=-1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
