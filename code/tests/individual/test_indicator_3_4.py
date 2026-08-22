"""Acceptance tests for indicator 3.4 semantic and temporal alignment."""

from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from _support import CODE_ROOT, assert_benchmark_contract
from governance.indicator_3_4 import align_records, benchmark


class Indicator34Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.result = benchmark()

    def test_benchmark_meets_alignment_target(self) -> None:
        assert_benchmark_contract(self, self.result, "3.4")
        metrics = self.result["metrics"]
        self.assertGreaterEqual(metrics["alignment_accuracy_percent"], 90.0)
        self.assertEqual(metrics["correct_alignments"], metrics["samples"])
        self.assertGreater(metrics["fuzzy_entity_samples"], 0)
        self.assertGreater(metrics["negative_samples"], 0)
        self.assertEqual(metrics["labeled_dataset_id"], "indicator-3.4-labeled-v1")
        self.assertIn("不用于推断", metrics["accuracy_interval_scope"])

    def test_labeled_dataset_hash_is_enforced(self) -> None:
        with (
            patch("governance.indicator_3_4.BENCHMARK_DATA_SHA256", "0" * 64),
            self.assertRaisesRegex(ValueError, "哈希不一致"),
        ):
            benchmark()

    def test_versioned_labeled_dataset_meets_accuracy_target(self) -> None:
        dataset = json.loads(
            (CODE_ROOT / "governance" / "benchmark_data" / "indicator_3_4_labeled.json")
            .read_text(encoding="utf-8")
        )
        results = align_records(
            dataset["sequence"],
            dataset["relations"],
            tolerance_ms=dataset["tolerance_ms"],
        )
        predicted = [
            row["relation"].get("work_order") if row["relation"] else None
            for row in results
        ]
        expected = dataset["expected_work_orders"]
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
