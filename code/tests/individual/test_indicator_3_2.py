"""Acceptance tests for indicator 3.2 time-series compression."""

from __future__ import annotations

import unittest

from _support import assert_benchmark_contract
from governance.indicator_3_2 import (
    BinaryChannelCodec,
    PiecewiseLinearCodec,
    QuantizedDeltaCodec,
    benchmark,
)
from governance.public_benchmarks import iter_metropt_full_batches
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
        self.assertGreaterEqual(metrics["compression_ratio"], 9.0)
        self.assertGreaterEqual(metrics["minimum_chunk_compression_ratio"], 9.0)
        self.assertGreaterEqual(metrics["minimum_channel_compression_ratio"], 9.0)
        self.assertTrue(metrics["full_dataset"])
        self.assertEqual(metrics["records"], 1_516_948)
        self.assertEqual(metrics["records"], metrics["expected_records"])
        self.assertEqual(metrics["sensor_channels"], 15)
        self.assertTrue(metrics["all_error_bounds_met"])
        self.assertTrue(metrics["all_binary_round_trips_met"])
        self.assertEqual(len(metrics["per_channel_results"]), 15)
        self.assertEqual(len(metrics["chunk_results"]), metrics["chunks"])
        self.assertEqual(
            sum(item["records"] for item in metrics["chunk_results"]),
            metrics["records"],
        )
        self.assertEqual(
            sum(item["raw_bytes"] for item in metrics["chunk_results"]),
            metrics["raw_bytes"],
        )
        self.assertEqual(
            sum(item["compressed_bytes"] for item in metrics["chunk_results"]),
            metrics["compressed_bytes"],
        )
        self.assertEqual(
            sum(item["raw_bytes"] for item in metrics["per_channel_results"].values()),
            metrics["raw_bytes"],
        )
        self.assertEqual(
            sum(
                item["compressed_bytes"]
                for item in metrics["per_channel_results"].values()
            ),
            metrics["compressed_bytes"],
        )
        expected_start = 0
        for chunk in metrics["chunk_results"]:
            self.assertEqual(chunk["start_row"], expected_start)
            self.assertEqual(chunk["end_row"] - chunk["start_row"] + 1, chunk["records"])
            self.assertGreaterEqual(chunk["compression_ratio"], 9.0)
            expected_start = chunk["end_row"] + 1
        self.assertEqual(expected_start, metrics["records"])
        for channel, channel_result in metrics["per_channel_results"].items():
            with self.subTest(channel=channel):
                self.assertGreaterEqual(channel_result["compression_ratio"], 9.0)
                self.assertLessEqual(
                    channel_result["max_absolute_error"],
                    channel_result["tolerance"] + 1e-9,
                )

        datasets = metrics["dataset_results"]
        self.assertEqual(set(datasets), {"metropt3", "forda"})
        self.assertEqual(datasets["metropt3"]["records"], 1_516_948)
        self.assertEqual(datasets["forda"]["records"], 4_921)
        self.assertEqual(len(datasets["forda"]["unit_results"]), 4_921)
        for dataset, result in datasets.items():
            with self.subTest(dataset=dataset):
                self.assertTrue(result["full_dataset"])
                self.assertTrue(result["all_units_meet_9_to_1"])

    def test_piecewise_codec_preserves_error_bound(self) -> None:
        _, channels = next(iter(iter_metropt_full_batches(batch_size=2_048)))
        source = channels["TP3"]
        restored, tolerance = PiecewiseLinearCodec().decompress(
            PiecewiseLinearCodec().compress(source, tolerance=0.05)
        )
        self.assertEqual(len(restored), len(source))
        self.assertLessEqual(max(abs(a - b) for a, b in zip(source, restored)), tolerance + 1e-9)

    def test_existing_codecs_round_trip_on_public_data(self) -> None:
        _, channels = next(iter(iter_metropt_full_batches(batch_size=2_000)))
        float_source = channels["Motor_current"]
        integer_source = [round(value * 1_000_000) for value in float_source]
        for codec in (RegerIntCodec, BosIntCodec, Ts2DiffBosIntCodec):
            with self.subTest(codec=codec.__name__):
                self.assertEqual(codec.decompress(codec.compress(integer_source)), integer_source)
        reger_restored = RegerFloatCodec.decompress(RegerFloatCodec.compress(float_source))
        self.assertEqual(reger_restored, float_source)
        quantized = Ts2DiffBosFloatCodec.decompress(Ts2DiffBosFloatCodec.compress(float_source))
        self.assertEqual(len(quantized), len(float_source))
        self.assertLessEqual(max(abs(a - b) for a, b in zip(float_source, quantized)), 5e-7)

    def test_selected_codecs_reject_invalid_values(self) -> None:
        analog = QuantizedDeltaCodec()
        binary = BinaryChannelCodec()
        with self.assertRaises(ValueError):
            analog.compress([float("nan")], tolerance=0.1)
        with self.assertRaises(ValueError):
            analog.compress([1.0], tolerance=0.0)
        with self.assertRaises(ValueError):
            binary.compress([0.0, 2.0])

    def test_invalid_values_are_rejected(self) -> None:
        codec = PiecewiseLinearCodec()
        with self.assertRaises(ValueError):
            codec.compress([1.0], tolerance=-0.1)
        with self.assertRaises(ValueError):
            codec.compress([float("nan")], tolerance=0.1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
