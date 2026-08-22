"""Acceptance tests for indicator 3.5 high-frequency ingestion."""

from __future__ import annotations

import unittest

from _support import assert_benchmark_contract
from governance.indicator_3_5 import HighFrequencyBuffer, benchmark


class Indicator35Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.result = benchmark()

    def test_benchmark_meets_minimum_frequency(self) -> None:
        assert_benchmark_contract(self, self.result, "3.5")
        metrics = self.result["metrics"]
        self.assertGreaterEqual(metrics["minimum_samples_per_second"], 1100.0)
        self.assertEqual(metrics["target_samples_per_second"], 1100)
        self.assertEqual(metrics["lost_samples"], 0)
        self.assertGreaterEqual(metrics["repeats"], 5)
        self.assertGreaterEqual(metrics["warmup_runs"], 1)
        self.assertEqual(len(metrics["run_samples_per_second"]), metrics["repeats"])
        self.assertEqual(
            metrics["minimum_samples_per_second"],
            min(metrics["run_samples_per_second"]),
        )
        self.assertGreaterEqual(metrics["throughput_coefficient_of_variation"], 0.0)

    def test_buffer_preserves_recent_records(self) -> None:
        buffer = HighFrequencyBuffer(capacity=3, max_batch_size=3)
        self.assertEqual(buffer.ingest_batch([{"id": 1}, {"id": 2}, {"id": 3}]), 3)
        self.assertEqual(buffer.ingest_batch([{"id": 4}]), 1)
        self.assertEqual(buffer.snapshot(10), [{"id": 2}, {"id": 3}, {"id": 4}])
        self.assertEqual(buffer.total_ingested, 4)

    def test_oversized_batch_is_rejected(self) -> None:
        buffer = HighFrequencyBuffer(max_batch_size=2)
        with self.assertRaises(ValueError):
            buffer.ingest_batch([{"id": 1}, {"id": 2}, {"id": 3}])


if __name__ == "__main__":
    unittest.main(verbosity=2)
