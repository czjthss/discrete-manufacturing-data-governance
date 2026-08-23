"""Acceptance tests for indicator 3.4 semantic and temporal alignment."""

from __future__ import annotations

import unittest

from _support import assert_benchmark_contract
from governance.indicator_3_4 import align_records, benchmark
from governance.public_benchmarks import load_metropt_failures, metropt_alignment_sequence


class Indicator34Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.result = benchmark()

    def test_benchmark_meets_alignment_target(self) -> None:
        assert_benchmark_contract(self, self.result, "3.4")
        metrics = self.result["metrics"]
        self.assertGreaterEqual(metrics["alignment_accuracy_percent"], 90.0)
        self.assertEqual(metrics["correct_alignments"], metrics["samples"])
        self.assertTrue(metrics["full_dataset"])
        self.assertEqual(metrics["samples"], 1_516_948)
        self.assertGreater(metrics["positive_samples"], 0)
        self.assertGreater(metrics["negative_samples"], 0)

    def test_metropt_maintenance_windows_are_independent_truth(self) -> None:
        sequence = metropt_alignment_sequence()
        relations = list(load_metropt_failures())
        results = align_records(sequence, relations, tolerance_ms=0)
        predicted = [
            row["relation"].get("work_order") if row["relation"] else None
            for row in results
        ]
        expected = [
            next(
                (
                    relation["work_order"]
                    for relation in relations
                    if relation["start_ms"] <= row["timestamp_ms"] <= relation["end_ms"]
                ),
                None,
            )
            for row in sequence
        ]
        correct = sum(actual == label for actual, label in zip(predicted, expected))
        self.assertEqual(len(predicted), len(expected))
        self.assertGreaterEqual(100.0 * correct / len(expected), 90.0)

    def test_narrower_matching_window_has_priority(self) -> None:
        sequence = [{"机床编号": "CNC-01", "采集时间": 1000, "测量值": 42.0}]
        relations = [
            {"equipment_id": "CNC-01", "start_ms": 0, "end_ms": 2000, "work_order": "BROAD"},
            {"device_id": "CNC-01", "开始时间": 990, "结束时间": 1010, "work_order": "PRECISE"},
        ]
        result = align_records(sequence, relations, tolerance_ms=0)
        self.assertTrue(result[0]["aligned"])
        self.assertEqual(result[0]["relation"]["work_order"], "PRECISE")

    def test_invalid_timestamp_does_not_raise_or_match(self) -> None:
        result = align_records(
            [{"equipment_id": "CNC-01", "timestamp_ms": "bad", "value": 1}],
            [{"equipment_id": "CNC-01", "start_ms": 0, "end_ms": 10}],
        )
        self.assertFalse(result[0]["aligned"])
        self.assertIn("时间戳", result[0]["alignment_reason"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
