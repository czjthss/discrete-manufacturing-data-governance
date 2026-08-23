"""Acceptance tests for indicator 3.5 high-frequency ingestion."""

from __future__ import annotations

import unittest

from _support import assert_benchmark_contract
from governance.indicator_3_5 import HighFrequencyBuffer, benchmark
from governance.public_benchmarks import load_forda_series


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
        self.assertEqual(metrics["samples"], 1_521_869)
        self.assertGreaterEqual(metrics["repeats"], 5)
        self.assertGreaterEqual(metrics["warmup_runs"], 1)
        datasets = metrics["dataset_results"]
        self.assertEqual(set(datasets), {"metropt3", "forda"})
        self.assertEqual(datasets["metropt3"]["samples"], 1_516_948)
        self.assertEqual(datasets["forda"]["samples"], 4_921)
        for dataset, result in datasets.items():
            with self.subTest(dataset=dataset):
                self.assertTrue(result["software_throughput_passed"])
                self.assertEqual(len(result["run_samples_per_second"]), 7)
                self.assertEqual(result["lost_samples"], 0)

    def test_buffer_preserves_recent_records(self) -> None:
        source = load_forda_series()[:4]
        buffer = HighFrequencyBuffer(capacity=3, max_batch_size=3)
        self.assertEqual(buffer.ingest_batch(source[:3]), 3)
        self.assertEqual(buffer.ingest_batch(source[3:]), 1)
        self.assertEqual(buffer.snapshot(10), list(source[1:]))
        self.assertEqual(buffer.total_ingested, 4)

    def test_oversized_batch_is_rejected(self) -> None:
        source = load_forda_series()[:3]
        buffer = HighFrequencyBuffer(max_batch_size=2)
        with self.assertRaises(ValueError):
            buffer.ingest_batch(source)


if __name__ == "__main__":
    unittest.main(verbosity=2)
