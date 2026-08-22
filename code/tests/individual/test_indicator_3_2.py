"""Acceptance tests for indicator 3.2 time-series compression."""

from __future__ import annotations

import unittest

from _support import assert_benchmark_contract
from governance.indicator_3_2 import PiecewiseLinearCodec, benchmark
from integrations.group_research.adapter import (
    BosIntCodec,
    RegerFloatCodec,
    RegerIntCodec,
    Ts2DiffBosFloatCodec,
    Ts2DiffBosIntCodec,
)


class Indicator32Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.result = benchmark()

    def test_benchmark_meets_ratio_and_error_targets(self) -> None:
        assert_benchmark_contract(self, self.result, "3.2")
        metrics = self.result["metrics"]
        self.assertGreaterEqual(metrics["minimum_compression_ratio"], 9.0)
        self.assertLessEqual(
            metrics["max_absolute_error"],
            metrics["configured_error_bound"] + 1e-9,
        )
        group_results = metrics["research_group_algorithms"]
        self.assertEqual(len(group_results), 5)
        self.assertTrue(all(item["round_trip_ok"] for item in group_results.values()))
        self.assertTrue(all(item["provider"] == "课题组最新成果" for item in group_results.values()))
        self.assertEqual(group_results["REGER-Float64"]["precision_mode"], "exact_float64")
        self.assertIsNone(group_results["REGER-Float64"]["allowed_absolute_error"])

    def test_piecewise_codec_preserves_error_bound(self) -> None:
        source = [40.0, 40.03, 40.07, 40.09, 40.12, 40.15]
        restored, tolerance = PiecewiseLinearCodec().decompress(
            PiecewiseLinearCodec().compress(source, tolerance=0.05)
        )
        self.assertEqual(len(restored), len(source))
        self.assertLessEqual(max(abs(a - b) for a, b in zip(source, restored)), tolerance + 1e-9)

    def test_research_group_codecs_round_trip(self) -> None:
        integer_source = [1000, 1001, 1003, 1006, 1010, 1015]
        float_source = [1.25, 1.5, 1.75, 2.0, 2.125]
        for codec in (RegerIntCodec, BosIntCodec, Ts2DiffBosIntCodec):
            with self.subTest(codec=codec.__name__):
                self.assertEqual(codec.decompress(codec.compress(integer_source)), integer_source)
        reger_restored = RegerFloatCodec.decompress(RegerFloatCodec.compress(float_source))
        self.assertEqual(reger_restored, float_source)
        quantized = Ts2DiffBosFloatCodec.decompress(Ts2DiffBosFloatCodec.compress(float_source))
        self.assertEqual(len(quantized), len(float_source))
        self.assertLessEqual(max(abs(a - b) for a, b in zip(float_source, quantized)), 5e-7)

    def test_invalid_values_are_rejected(self) -> None:
        codec = PiecewiseLinearCodec()
        with self.assertRaises(ValueError):
            codec.compress([1.0], tolerance=-0.1)
        with self.assertRaises(ValueError):
            codec.compress([float("nan")], tolerance=0.1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
