"""Runnable adapters for compressed queries, schema matching and quality windows."""

from __future__ import annotations

import math
from difflib import SequenceMatcher
from typing import Any

from governance.indicator_3_2 import PiecewiseLinearCodec
from governance.indicator_3_4 import ALIASES, canonical_key
from governance.indicator_3_6 import evaluate_quality


class CompressedQueryAdapter:
    """Block metadata pruning with deferred decompression for numeric series."""

    @staticmethod
    def compress(
        values: list[float], *, block_size: int = 512, tolerance: float = 0.0
    ) -> dict[str, Any]:
        if not isinstance(block_size, int) or isinstance(block_size, bool) or block_size <= 0:
            raise ValueError("块大小必须是正整数")
        codec = PiecewiseLinearCodec()
        blocks = []
        for start in range(0, len(values), block_size):
            block = values[start : start + block_size]
            payload = codec.compress(block, tolerance)
            blocks.append(
                {
                    "start": start,
                    "count": len(block),
                    "minimum": min(block),
                    "maximum": max(block),
                    "payload": payload,
                }
            )
        return {
            "count": len(values),
            "block_size": block_size,
            "tolerance": tolerance,
            "blocks": blocks,
        }

    @staticmethod
    def range_filter(
        compressed: dict[str, Any], lower: float, upper: float
    ) -> dict[str, Any]:
        if not math.isfinite(float(lower)) or not math.isfinite(float(upper)) or lower > upper:
            raise ValueError("查询范围无效")
        codec = PiecewiseLinearCodec()
        matches = []
        decompressed_blocks = 0
        for block in compressed.get("blocks", []):
            if block["maximum"] < lower or block["minimum"] > upper:
                continue
            values, _ = codec.decompress(block["payload"])
            decompressed_blocks += 1
            matches.extend(
                {"index": block["start"] + index, "value": value}
                for index, value in enumerate(values)
                if lower <= value <= upper
            )
        return {
            "matches": matches,
            "total_blocks": len(compressed.get("blocks", [])),
            "decompressed_blocks": decompressed_blocks,
        }

    @classmethod
    def healthcheck(cls) -> bool:
        source = [float(index) for index in range(32)]
        packed = cls.compress(source, block_size=8)
        result = cls.range_filter(packed, 10, 12)
        return [item["value"] for item in result["matches"]] == [10.0, 11.0, 12.0]


class SchemaMatcherAdapter:
    """Candidate generation, refinement and confidence scoring for field names."""

    @staticmethod
    def match(source_schema: list[str], target_schema: list[str]) -> list[dict[str, Any]]:
        if not source_schema or not target_schema:
            return []
        output = []
        for source in source_schema:
            source_canonical = canonical_key(source)
            candidates = []
            for target in target_schema:
                target_canonical = canonical_key(target)
                lexical = SequenceMatcher(
                    None, source.strip().lower(), target.strip().lower()
                ).ratio()
                semantic = 1.0 if source_canonical == target_canonical else 0.0
                alias_support = 1.0 if any(
                    source.lower() in aliases and target.lower() in aliases
                    for aliases in ALIASES.values()
                ) else 0.0
                confidence = max(semantic, 0.75 * alias_support + 0.25 * lexical)
                candidates.append((confidence, target))
            confidence, target = max(candidates, key=lambda item: (item[0], item[1]))
            output.append(
                {
                    "source": source,
                    "target": target,
                    "confidence": round(confidence, 4),
                    "accepted": confidence >= 0.75,
                }
            )
        return output

    @classmethod
    def healthcheck(cls) -> bool:
        matches = cls.match(["机床编号", "采集时间"], ["equipment_id", "timestamp_ms"])
        return all(item["accepted"] for item in matches)


class WindowQualityAdapter:
    """Calculates four quality dimensions over explicit event-time windows."""

    @staticmethod
    def evaluate_windows(
        records: list[dict[str, Any]], *, window_ms: float = 60_000
    ) -> list[dict[str, Any]]:
        if not math.isfinite(float(window_ms)) or window_ms <= 0:
            raise ValueError("质量窗口必须是有限正数")
        windows: dict[int, list[dict[str, Any]]] = {}
        for row in records:
            try:
                timestamp = float(row.get("timestamp_ms"))
            except (TypeError, ValueError):
                timestamp = -1
            bucket = math.floor(timestamp / window_ms) if math.isfinite(timestamp) else -1
            windows.setdefault(bucket, []).append(row)
        return [
            {
                "window_start_ms": bucket * window_ms if bucket >= 0 else None,
                "records": len(items),
                "dimensions": evaluate_quality(
                    items,
                    reference_time_ms=(bucket + 1) * window_ms if bucket >= 0 else 0,
                    max_age_ms=window_ms,
                ),
            }
            for bucket, items in sorted(windows.items())
        ]

    @classmethod
    def healthcheck(cls) -> bool:
        result = cls.evaluate_windows(
            [{"timestamp_ms": 1, "equipment_id": "CNC-01", "value": 1}],
            window_ms=1000,
        )
        return len(result) == 1 and result[0]["dimensions"]["validity"] == 100.0
