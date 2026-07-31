"""Indicator 3.2: error-bounded industrial time-series compression."""

from __future__ import annotations

import struct
import zlib
from dataclasses import dataclass
from typing import Any

from .common import synthetic_sequence


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

    def compress(self, values: list[float], tolerance: float = 0.08) -> bytes:
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
        raw = zlib.decompress(payload)
        count, tolerance = self.HEADER.unpack_from(raw, 0)
        values = [0.0] * count
        offset = self.HEADER.size
        while offset < len(raw):
            start, end, start_value, end_value = self.SEGMENT.unpack_from(raw, offset)
            offset += self.SEGMENT.size
            if end == start:
                values[start] = start_value
                continue
            for index in range(start, end + 1):
                ratio = (index - start) / (end - start)
                values[index] = start_value + ratio * (end_value - start_value)
        return values, tolerance


def benchmark() -> dict[str, Any]:
    source = [row["value"] for row in synthetic_sequence(12000)]
    codec = PiecewiseLinearCodec()
    compressed = codec.compress(source, tolerance=0.08)
    restored, tolerance = codec.decompress(compressed)
    max_error = max(abs(a - b) for a, b in zip(source, restored))
    raw_bytes = len(source) * 8
    ratio = raw_bytes / max(len(compressed), 1)
    passed = ratio >= 9.0 and max_error <= tolerance + 1e-9
    return {
        "indicator": ID,
        "title": TITLE,
        "target": MILESTONE_TARGET,
        "passed": passed,
        "metrics": {
            "samples": len(source),
            "raw_bytes_float64": raw_bytes,
            "compressed_bytes": len(compressed),
            "compression_ratio": round(ratio, 2),
            "max_absolute_error": round(max_error, 6),
            "configured_error_bound": tolerance,
        },
        "method": "采用有界误差分段线性表示（PLA）并进行二次无损压缩；报告同时披露压缩比和最大重构误差。",
        "reference": "Gorilla/SZ 类时序压缩中的预测编码与误差约束思想；首版为可替换算法接口。",
    }
