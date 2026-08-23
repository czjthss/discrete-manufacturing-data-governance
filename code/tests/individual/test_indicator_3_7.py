"""Acceptance tests for indicator 3.7 sequence-relation fusion."""

from __future__ import annotations

import unittest

from _support import assert_benchmark_contract
from governance.indicator_3_7 import benchmark, fuse
from governance.public_benchmarks import load_metropt_failures, metropt_alignment_sequence


class Indicator37Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.result = benchmark()

    def test_benchmark_produces_fused_rows(self) -> None:
        assert_benchmark_contract(self, self.result, "3.7")
        metrics = self.result["metrics"]
        self.assertEqual(metrics["fused_rows"], metrics["sequence_rows"])
        self.assertTrue(metrics["full_dataset"])
        self.assertEqual(metrics["sequence_rows"], 1_516_948)
        self.assertGreater(metrics["matched_rows"], 0)
        self.assertGreater(metrics["unmatched_rows"], 0)
        self.assertEqual(metrics["fusion_accuracy_percent"], 100.0)
        self.assertEqual(metrics["source_rows_preserved"], metrics["sequence_rows"])
        self.assertGreater(metrics["rows_per_second"], 0)

    def test_left_fusion_preserves_unmatched_samples(self) -> None:
        all_sequence = metropt_alignment_sequence()
        relations = list(load_metropt_failures())
        matched = next(
            row
            for row in all_sequence
            if any(r["start_ms"] <= row["timestamp_ms"] <= r["end_ms"] for r in relations)
        )
        unmatched = next(
            row
            for row in all_sequence
            if not any(r["start_ms"] <= row["timestamp_ms"] <= r["end_ms"] for r in relations)
        )
        sequence = [matched, unmatched]
        result = fuse(sequence, relations, tolerance_ms=0)
        self.assertEqual(len(result), 2)
        self.assertIn(result[0]["relation_work_order"], {"F1", "F2", "F3", "F4"})
        self.assertTrue(result[0]["aligned"])
        self.assertFalse(result[1]["aligned"])
        self.assertNotIn("relation_work_order", result[1])


if __name__ == "__main__":
    unittest.main(verbosity=2)
