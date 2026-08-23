"""Indicator 3.2: error-bounded industrial time-series compression."""

from __future__ import annotations

import math
import statistics
import struct
import sys
import time
import zlib
from array import array
from dataclasses import dataclass
from typing import Any

from .common import bounded_zlib_decompress
from .public_benchmarks import (
    METRO_ANALOG_CHANNELS,
    METRO_DIGITAL_CHANNELS,
    benchmark_manifest,
    benchmark_provenance,
    iter_metropt_full_batches,
    load_forda_series,
)


ID = "3.2"
TITLE = "工业时序数据压缩"
MILESTONE_TARGET = "工业时序数据压缩比达到 9:1"


@dataclass
class Segment:
    start: int
    end: int
    start_value: float
    end_value: float


class PiecewiseLinearCodec:
    """A deterministic, bounded-error PLA codec for smooth sensor streams."""

    HEADER = struct.Struct("<Id")
    SEGMENT = struct.Struct("<IIdd")
    MAX_SAMPLES = 2_000_000

    def compress(self, values: list[float], tolerance: float = 0.08) -> bytes:
        if not isinstance(tolerance, (int, float)) or isinstance(tolerance, bool):
            raise ValueError("误差阈值必须是有限非负数")
        tolerance = float(tolerance)
        if not math.isfinite(tolerance) or tolerance < 0:
            raise ValueError("误差阈值必须是有限非负数")
        normalized: list[float] = []
        for index, value in enumerate(values):
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                raise ValueError(f"第 {index} 个样本不是数值")
            number = float(value)
            if not math.isfinite(number):
                raise ValueError(f"第 {index} 个样本不是有限数值")
            normalized.append(number)
        values = normalized
        if len(values) > self.MAX_SAMPLES:
            raise ValueError(f"样本数超过上限 {self.MAX_SAMPLES}")
        if not values:
            return zlib.compress(self.HEADER.pack(0, tolerance), level=9)
        if len(values) == 1:
            raw = self.HEADER.pack(1, tolerance) + self.SEGMENT.pack(
                0, 0, values[0], values[0]
            )
            return zlib.compress(raw, level=9)

        count = len(values)
        segments: list[Segment] = []
        start = 0
        while start < count - 1:
            start_value = values[start]
            lower_slope = float("-inf")
            upper_slope = float("inf")
            best = start
            for candidate in range(start + 1, count):
                distance = candidate - start
                low = (values[candidate] - tolerance - start_value) / distance
                high = (values[candidate] + tolerance - start_value) / distance
                next_lower = max(lower_slope, low)
                next_upper = min(upper_slope, high)
                if next_lower > next_upper:
                    break
                lower_slope, upper_slope = next_lower, next_upper
                best = candidate

            if best == start:
                best = start + 1
                lower_slope = upper_slope = values[best] - start_value

            actual_slope = (values[best] - start_value) / (best - start)
            slope = min(max(actual_slope, lower_slope), upper_slope)
            end_value = start_value + slope * (best - start)
            segments.append(Segment(start, best, start_value, end_value))
            start = best

        payload = bytearray(self.HEADER.pack(count, tolerance))
        for segment in segments:
            payload.extend(
                self.SEGMENT.pack(
                    segment.start,
                    segment.end,
                    segment.start_value,
                    segment.end_value,
                )
            )
        return zlib.compress(bytes(payload), level=9)

    def decompress(self, payload: bytes) -> tuple[list[float], float]:
        raw = bounded_zlib_decompress(
            payload,
            self.HEADER.size + self.MAX_SAMPLES * self.SEGMENT.size,
        )
        if len(raw) < self.HEADER.size:
            raise ValueError("压缩载荷缺少头部")
        count, tolerance = self.HEADER.unpack_from(raw, 0)
        if count > self.MAX_SAMPLES:
            raise ValueError(f"载荷样本数超过上限 {self.MAX_SAMPLES}")
        if not math.isfinite(tolerance) or tolerance < 0:
            raise ValueError("载荷误差阈值无效")
        remaining = len(raw) - self.HEADER.size
        if remaining % self.SEGMENT.size:
            raise ValueError("压缩载荷包含不完整分段")
        if count == 0:
            if remaining:
                raise ValueError("空序列载荷不应包含分段")
            return [], tolerance
        values = [0.0] * count
        offset = self.HEADER.size
        previous_end: int | None = None
        while offset < len(raw):
            start, end, start_value, end_value = self.SEGMENT.unpack_from(raw, offset)
            offset += self.SEGMENT.size
            if start > end or end >= count:
                raise ValueError("压缩载荷分段索引越界")
            if not math.isfinite(start_value) or not math.isfinite(end_value):
                raise ValueError("压缩载荷包含非有限数值")
            if previous_end is None and start != 0:
                raise ValueError("压缩载荷未从首个样本开始")
            if previous_end is not None and start != previous_end:
                raise ValueError("压缩载荷分段不连续")
            if end == start:
                values[start] = start_value
                previous_end = end
                continue
            for index in range(start, end + 1):
                ratio = (index - start) / (end - start)
                values[index] = start_value + ratio * (end_value - start_value)
            previous_end = end
        if previous_end != count - 1:
            raise ValueError("压缩载荷未覆盖全部样本")
        return values, tolerance


class QuantizedDeltaCodec:
    """Error-bounded analog codec using fixed-step quantization and delta coding."""

    HEADER = struct.Struct("<4sIdq")
    MAGIC = b"QDL1"
    MAX_SAMPLES = 2_000_000

    def compress(self, values: list[float], tolerance: float) -> bytes:
        if not isinstance(tolerance, (int, float)) or isinstance(tolerance, bool):
            raise ValueError("误差阈值必须是有限正数")
        tolerance = float(tolerance)
        if not math.isfinite(tolerance) or tolerance <= 0:
            raise ValueError("误差阈值必须是有限正数")
        if len(values) > self.MAX_SAMPLES:
            raise ValueError(f"样本数超过上限 {self.MAX_SAMPLES}")
        step = tolerance * 2.0
        quantized: list[int] = []
        for index, value in enumerate(values):
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                raise ValueError(f"第 {index} 个样本不是数值")
            number = float(value)
            if not math.isfinite(number):
                raise ValueError(f"第 {index} 个样本不是有限数值")
            quantized.append(round(number / step))
        first = quantized[0] if quantized else 0
        deltas = array("i")
        previous = first
        for value in quantized[1:]:
            delta = value - previous
            if not -(2**31) <= delta < 2**31:
                raise ValueError("量化差分超出 Int32 范围")
            deltas.append(delta)
            previous = value
        if sys.byteorder != "little":
            deltas.byteswap()
        raw = self.HEADER.pack(self.MAGIC, len(values), step, first) + deltas.tobytes()
        return zlib.compress(raw, level=9)

    def decompress(self, payload: bytes) -> tuple[list[float], float]:
        raw = bounded_zlib_decompress(
            payload,
            self.HEADER.size + max(0, self.MAX_SAMPLES - 1) * 4,
        )
        if len(raw) < self.HEADER.size:
            raise ValueError("量化差分载荷缺少头部")
        magic, count, step, first = self.HEADER.unpack_from(raw)
        if magic != self.MAGIC or count > self.MAX_SAMPLES:
            raise ValueError("量化差分载荷头部无效")
        if not math.isfinite(step) or step <= 0:
            raise ValueError("量化步长无效")
        expected = self.HEADER.size + max(0, count - 1) * 4
        if len(raw) != expected:
            raise ValueError("量化差分载荷长度不一致")
        deltas = array("i")
        deltas.frombytes(raw[self.HEADER.size :])
        if sys.byteorder != "little":
            deltas.byteswap()
        quantized = [first]
        for delta in deltas:
            quantized.append(quantized[-1] + delta)
        if count == 0:
            quantized = []
        if len(quantized) != count:
            raise ValueError("量化差分载荷样本数不一致")
        return [value * step for value in quantized], step / 2.0


class BinaryChannelCodec:
    """Lossless binary-channel codec with explicit sample count."""

    HEADER = struct.Struct("<4sI")
    MAGIC = b"BIN1"
    MAX_SAMPLES = 2_000_000

    def compress(self, values: list[float]) -> bytes:
        if len(values) > self.MAX_SAMPLES:
            raise ValueError(f"样本数超过上限 {self.MAX_SAMPLES}")
        encoded = bytearray()
        for index, value in enumerate(values):
            if value not in (0, 0.0, 1, 1.0, False, True):
                raise ValueError(f"第 {index} 个样本不是二值数据")
            encoded.append(int(value))
        return zlib.compress(self.HEADER.pack(self.MAGIC, len(encoded)) + encoded, 9)

    def decompress(self, payload: bytes) -> list[float]:
        raw = bounded_zlib_decompress(payload, self.HEADER.size + self.MAX_SAMPLES)
        if len(raw) < self.HEADER.size:
            raise ValueError("二值载荷缺少头部")
        magic, count = self.HEADER.unpack_from(raw)
        values = raw[self.HEADER.size :]
        if magic != self.MAGIC or count > self.MAX_SAMPLES or len(values) != count:
            raise ValueError("二值载荷头部或长度无效")
        if any(value not in (0, 1) for value in values):
            raise ValueError("二值载荷包含非法值")
        return [float(value) for value in values]


def benchmark_adaptive_series(
    units: list[tuple[str, list[float]]], tolerance: float
) -> dict[str, Any]:
    pla = PiecewiseLinearCodec()
    delta = QuantizedDeltaCodec()
    raw_bytes = 0
    compressed_bytes = 0
    codec_counts = {"PiecewiseLinearCodec": 0, "QuantizedDeltaCodec": 0}
    unit_results = []
    for unit_name, values in units:
        candidates = []
        pla_payload = pla.compress(values, tolerance=tolerance)
        pla_restored, _ = pla.decompress(pla_payload)
        candidates.append(("PiecewiseLinearCodec", pla_payload, pla_restored))
        delta_payload = delta.compress(values, tolerance=tolerance)
        delta_restored, _ = delta.decompress(delta_payload)
        candidates.append(("QuantizedDeltaCodec", delta_payload, delta_restored))
        codec_name, payload, restored = min(candidates, key=lambda item: len(item[1]))
        max_error = max(abs(source - target) for source, target in zip(values, restored))
        unit_raw_bytes = len(values) * 8
        raw_bytes += unit_raw_bytes
        compressed_bytes += len(payload)
        codec_counts[codec_name] += 1
        unit_results.append(
            {
                "unit": unit_name,
                "samples": len(values),
                "codec": codec_name,
                "raw_bytes": unit_raw_bytes,
                "compressed_bytes": len(payload),
                "compression_ratio": round(unit_raw_bytes / max(len(payload), 1), 3),
                "max_absolute_error": round(max_error, 12),
            }
        )
    ratios = [item["compression_ratio"] for item in unit_results]
    return {
        "tolerance": tolerance,
        "selection": "minimum payload per unit from PiecewiseLinearCodec and QuantizedDeltaCodec",
        "units": len(unit_results),
        "raw_bytes": raw_bytes,
        "compressed_bytes": compressed_bytes,
        "compression_ratio": round(raw_bytes / max(compressed_bytes, 1), 3),
        "minimum_unit_compression_ratio": min(ratios),
        "median_unit_compression_ratio": round(statistics.median(ratios), 3),
        "maximum_unit_compression_ratio": max(ratios),
        "all_error_bounds_met": all(
            item["max_absolute_error"] <= tolerance + 1e-9
            for item in unit_results
        ),
        "all_units_meet_9_to_1": min(ratios) >= 9.0,
        "codec_counts": codec_counts,
        "unit_results": unit_results,
    }


def evaluate_adapter_round_trip(
    implementation: Any,
    source: list[int] | list[float],
    *,
    float_tolerance: float | None = 0.0000005,
) -> dict[str, Any]:
    payload = implementation.compress(source)
    reconstructed = implementation.decompress(payload)
    sample_count_matches = len(reconstructed) == len(source)
    is_float_source = bool(source) and isinstance(source[0], float)
    if is_float_source and sample_count_matches:
        reconstruction_error: float | None = max(
            (
                abs(float(left) - float(right))
                for left, right in zip(source, reconstructed)
            ),
            default=0.0,
        )
        round_trip_ok = (
            reconstructed == source
            if float_tolerance is None
            else reconstruction_error <= float_tolerance
        )
    elif is_float_source:
        reconstruction_error = None
        round_trip_ok = False
    else:
        reconstruction_error = 0.0 if sample_count_matches else None
        round_trip_ok = sample_count_matches and reconstructed == source
    return {
        "samples": len(source),
        "reconstructed_samples": len(reconstructed),
        "sample_count_matches": sample_count_matches,
        "compressed_bytes": len(payload),
        "compression_ratio": round(len(source) * 8 / max(len(payload), 1), 2),
        "round_trip_ok": round_trip_ok,
        "precision_mode": (
            "exact_float64"
            if is_float_source and float_tolerance is None
            else "absolute_error_bound"
            if is_float_source
            else "exact_int64"
        ),
        "allowed_absolute_error": float_tolerance if is_float_source else 0.0,
        "max_absolute_error": (
            round(reconstruction_error, 9)
            if reconstruction_error is not None
            else None
        ),
    }


def benchmark() -> dict[str, Any]:
    analog_codec = QuantizedDeltaCodec()
    binary_codec = BinaryChannelCodec()
    tolerances = {
        "TP2": 0.001,
        "TP3": 0.001,
        "H1": 0.001,
        "DV_pressure": 0.001,
        "Reservoirs": 0.001,
        "Oil_temperature": 0.0125,
        "Motor_current": 0.01,
    }
    expected_records = int(
        benchmark_manifest()["datasets"]["metropt3"]["full_archive"]["records"]
    )
    raw_bytes_total = 0
    compressed_bytes_total = 0
    total_records = 0
    elapsed_seconds = 0.0
    benchmark_started = time.perf_counter()
    channel_totals = {
        channel: {"raw_bytes": 0, "compressed_bytes": 0, "max_absolute_error": 0.0}
        for channel in (*METRO_ANALOG_CHANNELS, *METRO_DIGITAL_CHANNELS)
    }
    chunk_results = []
    all_error_bounds_met = True
    all_binary_round_trips_met = True
    for chunk_index, (start_row, channels) in enumerate(iter_metropt_full_batches()):
        rows = len(channels[METRO_ANALOG_CHANNELS[0]])
        chunk_raw_bytes = 0
        chunk_compressed_bytes = 0
        chunk_errors: dict[str, float] = {}
        started = time.perf_counter()
        for channel in METRO_ANALOG_CHANNELS:
            source = channels[channel]
            tolerance = tolerances[channel]
            compressed = analog_codec.compress(source, tolerance)
            restored, restored_tolerance = analog_codec.decompress(compressed)
            max_error = max(abs(a - b) for a, b in zip(source, restored))
            raw_bytes = rows * 8
            error_bound_met = max_error <= tolerance + 1e-9
            all_error_bounds_met = all_error_bounds_met and error_bound_met
            if abs(restored_tolerance - tolerance) > 1e-12:
                raise AssertionError("压缩载荷中的误差阈值不一致")
            chunk_raw_bytes += raw_bytes
            chunk_compressed_bytes += len(compressed)
            channel_totals[channel]["raw_bytes"] += raw_bytes
            channel_totals[channel]["compressed_bytes"] += len(compressed)
            channel_totals[channel]["max_absolute_error"] = max(
                channel_totals[channel]["max_absolute_error"], max_error
            )
            chunk_errors[channel] = round(max_error, 9)
        for channel in METRO_DIGITAL_CHANNELS:
            source = channels[channel]
            compressed = binary_codec.compress(source)
            restored = binary_codec.decompress(compressed)
            round_trip_met = restored == source
            all_binary_round_trips_met = all_binary_round_trips_met and round_trip_met
            raw_bytes = rows
            chunk_raw_bytes += raw_bytes
            chunk_compressed_bytes += len(compressed)
            channel_totals[channel]["raw_bytes"] += raw_bytes
            channel_totals[channel]["compressed_bytes"] += len(compressed)
        elapsed_seconds += time.perf_counter() - started
        total_records += rows
        raw_bytes_total += chunk_raw_bytes
        compressed_bytes_total += chunk_compressed_bytes
        chunk_results.append(
            {
                "chunk": chunk_index,
                "start_row": start_row,
                "end_row": start_row + rows - 1,
                "records": rows,
                "raw_bytes": chunk_raw_bytes,
                "compressed_bytes": chunk_compressed_bytes,
                "compression_ratio": round(
                    chunk_raw_bytes / max(chunk_compressed_bytes, 1), 3
                ),
                "max_absolute_error_by_analog_channel": chunk_errors,
            }
        )
    aggregate_ratio = raw_bytes_total / max(compressed_bytes_total, 1)
    per_channel_results = {
        channel: {
            "raw_bytes": int(values["raw_bytes"]),
            "compressed_bytes": int(values["compressed_bytes"]),
            "compression_ratio": round(
                values["raw_bytes"] / max(values["compressed_bytes"], 1), 3
            ),
            "mode": "bounded_error" if channel in METRO_ANALOG_CHANNELS else "lossless",
            "tolerance": tolerances.get(channel, 0.0),
            "max_absolute_error": round(values["max_absolute_error"], 9),
        }
        for channel, values in channel_totals.items()
    }
    chunk_ratios = sorted(item["compression_ratio"] for item in chunk_results)
    channel_ratios = sorted(
        item["compression_ratio"] for item in per_channel_results.values()
    )
    forda_rows = load_forda_series()
    forda_result = benchmark_adaptive_series(
        [
            (f"series_{row['series_id']:04d}", list(row["values"]))
            for row in forda_rows
        ],
        tolerance=0.08,
    )
    passed = (
        total_records == expected_records
        and aggregate_ratio >= 9.0
        and min(chunk_ratios) >= 9.0
        and min(channel_ratios) >= 9.0
        and all_error_bounds_met
        and all_binary_round_trips_met
    )
    return {
        "indicator": ID,
        "title": TITLE,
        "target": MILESTONE_TARGET,
        "passed": passed,
        "metrics": {
            "dataset": "MetroPT-3",
            "full_dataset": True,
            "records": total_records,
            "expected_records": expected_records,
            "sensor_channels": len(METRO_ANALOG_CHANNELS) + len(METRO_DIGITAL_CHANNELS),
            "analog_channels": len(METRO_ANALOG_CHANNELS),
            "digital_channels": len(METRO_DIGITAL_CHANNELS),
            "raw_layout": "analog Float64 + digital UInt8; timestamp excluded from sensor payload",
            "raw_bytes": raw_bytes_total,
            "compressed_bytes": compressed_bytes_total,
            "compression_ratio": round(aggregate_ratio, 3),
            "target_compression_ratio": 9.0,
            "chunks": len(chunk_results),
            "chunk_size": 65_536,
            "minimum_chunk_compression_ratio": min(chunk_ratios),
            "median_chunk_compression_ratio": chunk_ratios[len(chunk_ratios) // 2],
            "maximum_chunk_compression_ratio": max(chunk_ratios),
            "minimum_channel_compression_ratio": min(channel_ratios),
            "chunk_results": chunk_results,
            "per_channel_results": per_channel_results,
            "configured_error_bounds": tolerances,
            "max_absolute_error_by_channel": {
                channel: per_channel_results[channel]["max_absolute_error"]
                for channel in METRO_ANALOG_CHANNELS
            },
            "all_error_bounds_met": all_error_bounds_met,
            "all_binary_round_trips_met": all_binary_round_trips_met,
            "codec_elapsed_seconds": round(elapsed_seconds, 3),
            "wall_elapsed_seconds": round(time.perf_counter() - benchmark_started, 3),
            "processed_sensor_values": total_records
            * (len(METRO_ANALOG_CHANNELS) + len(METRO_DIGITAL_CHANNELS)),
            "dataset_results": {
                "metropt3": {
                    "role": "acceptance",
                    "full_dataset": True,
                    "records": total_records,
                    "sensor_channels": len(METRO_ANALOG_CHANNELS)
                    + len(METRO_DIGITAL_CHANNELS),
                    "compression_ratio": round(aggregate_ratio, 3),
                    "minimum_unit_compression_ratio": min(
                        min(chunk_ratios), min(channel_ratios)
                    ),
                    "all_units_meet_9_to_1": min(
                        min(chunk_ratios), min(channel_ratios)
                    )
                    >= 9.0,
                    "chunk_compression_ratios": [
                        item["compression_ratio"] for item in chunk_results
                    ],
                    "channel_compression_ratios": {
                        channel: result["compression_ratio"]
                        for channel, result in per_channel_results.items()
                    },
                },
                "forda": {
                    "role": "supplementary",
                    "full_dataset": True,
                    "records": len(forda_rows),
                    "points_per_series": 500,
                    **forda_result,
                },
            },
        },
        "benchmark_provenance": benchmark_provenance(("metropt3", "forda")),
        "method": "正式 9:1 判据流式读取 UCI MetroPT-3 官方完整归档的全部 1,516,948 行和 15 个传感器通道；同时在 UCR FordA TRAIN+TEST 的全部 4,921 条、2,460,500 个时序点上逐序列选择现有两种误差有界编码中载荷更小者，完整披露总体与逐序列结果。",
        "reference": "MetroPT-3 是正式验收数据集；FordA TRAIN+TEST 是同一指标的跨数据集补充结果，不参与替换或放宽 MetroPT-3 的 9:1 正式判据。",
    }
