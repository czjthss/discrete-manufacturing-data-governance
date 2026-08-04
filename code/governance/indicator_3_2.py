"""Indicator 3.2: error-bounded industrial time-series compression."""

from __future__ import annotations

import math
import struct
import time
import zlib
from dataclasses import dataclass
from typing import Any

from .common import bounded_zlib_decompress, synthetic_sequence


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


def evaluate_adapter_round_trip(
    implementation: Any,
    source: list[int] | list[float],
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
        round_trip_ok = reconstruction_error <= 0.0000005
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
        "max_absolute_error": (
            round(reconstruction_error, 9)
            if reconstruction_error is not None
            else None
        ),
    }


def benchmark() -> dict[str, Any]:
    from integrations.group_research.adapter import (
        BosIntCodec,
        RegerFloatCodec,
        RegerIntCodec,
        Ts2DiffBosFloatCodec,
        Ts2DiffBosIntCodec,
    )

    codec = PiecewiseLinearCodec()
    tolerance = 0.08
    datasets = [
        [row["value"] for row in synthetic_sequence(12000, seed=seed)]
        for seed in (2030, 2031, 2032, 2033, 2034)
    ]
    ratios = []
    baseline_ratios = []
    max_errors = []
    elapsed = []
    compressed_sizes = []
    for source in datasets:
        started = time.perf_counter()
        compressed = codec.compress(source, tolerance=tolerance)
        restored, restored_tolerance = codec.decompress(compressed)
        elapsed.append(time.perf_counter() - started)
        max_errors.append(max(abs(a - b) for a, b in zip(source, restored)))
        raw = struct.pack(f"<{len(source)}d", *source)
        compressed_sizes.append(len(compressed))
        ratios.append(len(raw) / max(len(compressed), 1))
        baseline_ratios.append(len(raw) / max(len(zlib.compress(raw, 9)), 1))
        if restored_tolerance != tolerance:
            raise AssertionError("压缩载荷中的误差阈值不一致")
    minimum_ratio = min(ratios)
    max_error = max(max_errors)
    group_source = datasets[0][:2000]
    group_int_source = [round(value * 1_000_000) for value in group_source]
    group_results: dict[str, dict[str, Any]] = {}
    for name, implementation, source in (
        ("REGER-Int64", RegerIntCodec, group_int_source),
        ("REGER-Float64", RegerFloatCodec, group_source),
        ("BOS-Int64", BosIntCodec, group_int_source),
        ("TS_2DIFF+BOS-Int64", Ts2DiffBosIntCodec, group_int_source),
        ("TS_2DIFF+BOS-Float", Ts2DiffBosFloatCodec, group_source),
    ):
        group_results[name] = {
            "provider": "课题组最新成果",
            **evaluate_adapter_round_trip(implementation, source),
        }
    passed = (
        minimum_ratio >= 9.0
        and max_error <= tolerance + 1e-9
        and all(item["round_trip_ok"] for item in group_results.values())
    )
    return {
        "indicator": ID,
        "title": TITLE,
        "target": MILESTONE_TARGET,
        "passed": passed,
        "metrics": {
            "datasets": len(datasets),
            "samples_per_dataset": len(datasets[0]),
            "raw_bytes_float64": len(datasets[0]) * 8,
            "compressed_bytes_median": sorted(compressed_sizes)[len(compressed_sizes) // 2],
            "compression_ratio": round(sum(ratios) / len(ratios), 2),
            "minimum_compression_ratio": round(minimum_ratio, 2),
            "zlib_float64_baseline_ratio": round(
                sum(baseline_ratios) / len(baseline_ratios), 2
            ),
            "max_absolute_error": round(max_error, 6),
            "configured_error_bound": tolerance,
            "median_round_trip_ms": round(
                1000.0 * sorted(elapsed)[len(elapsed) // 2], 3
            ),
            "research_group_algorithms": group_results,
        },
        "method": "采用有界误差 PLA，并对课题组最新 REGER、BOS、TS_2DIFF+BOS 实现执行独立往返与压缩率测量。",
        "reference": "Gorilla/SZ 类时序压缩中的预测编码与误差约束思想；首版为可替换算法接口。",
    }
