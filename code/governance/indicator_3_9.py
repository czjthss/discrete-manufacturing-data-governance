"""Indicator 3.9: multi-dimensional industrial data quality assessment."""

from __future__ import annotations

import json
import statistics
from collections import defaultdict
from typing import Any

from .common import mean, pct, synthetic_sequence
from .indicator_3_6 import evaluate_quality


ID = "3.9"
TITLE = "工业数据质量综合测评"
MILESTONE_TARGET = "支持 5 个以上维度的工业数据质量综合测评"

DEFAULT_MASTER_DATA = {
    "equipment_id": {f"CNC-{index:02d}" for index in range(1, 51)},
    "work_order": {f"WO-{index:03d}" for index in range(1, 1001)},
}


def _signature(row: dict[str, Any]) -> str:
    return json.dumps(
        [row.get("equipment_id"), row.get("timestamp_ms"), row.get("value")],
        ensure_ascii=False,
        sort_keys=True,
        default=str,
    )


def _referential_integrity(
    records: list[dict[str, Any]], reference_data: dict[str, set[str]]
) -> tuple[float, int]:
    checked = 0
    valid = 0
    for row in records:
        row_checks = []
        for field_name, allowed in reference_data.items():
            if field_name in row and row.get(field_name) not in (None, ""):
                checked += 1
                row_checks.append(str(row[field_name]) in allowed)
        if row_checks:
            valid += sum(row_checks)
    return (pct(valid, checked) if checked else 100.0), checked


def _stability(records: list[dict[str, Any]]) -> float:
    streams: dict[str, list[float]] = defaultdict(list)
    for row in records:
        try:
            value = float(row.get("value"))
        except (TypeError, ValueError):
            continue
        if value == value and abs(value) != float("inf"):
            streams[str(row.get("equipment_id", ""))].append(value)
    checked = 0
    stable = 0
    for values in streams.values():
        if len(values) < 3:
            stable += len(values)
            checked += len(values)
            continue
        center = statistics.median(values)
        mad = statistics.median(abs(value - center) for value in values)
        threshold = max(12 * mad, 1e-9)
        stable += sum(abs(value - center) <= threshold for value in values)
        checked += len(values)
    return pct(stable, checked)


def assess(
    records: list[dict[str, Any]],
    *,
    reference_data: dict[str, set[str]] | None = None,
    reference_time_ms: float | None = None,
) -> dict[str, Any]:
    if not isinstance(records, list) or not all(isinstance(row, dict) for row in records):
        raise ValueError("质量测评输入必须是对象数组")
    base = evaluate_quality(records, reference_time_ms=reference_time_ms)
    if not records:
        dimensions = {
            **base,
            "uniqueness": 0.0,
            "referential_integrity": 0.0,
            "stability": 0.0,
        }
        return {
            "dimensions": dimensions,
            "overall": 0.0,
            "minimum": 0.0,
            "evidence": {"referential_checks": 0},
        }
    references = DEFAULT_MASTER_DATA if reference_data is None else reference_data
    normalized_references = {
        str(field): {str(value) for value in values}
        for field, values in references.items()
    }
    signatures = {_signature(row) for row in records}
    uniqueness = pct(len(signatures), len(records))
    integrity, referential_checks = _referential_integrity(
        records, normalized_references
    )
    dimensions = {
        **base,
        "uniqueness": uniqueness,
        "referential_integrity": integrity,
        "stability": _stability(records),
    }
    return {
        "dimensions": dimensions,
        "overall": round(mean(dimensions.values()), 2),
        "minimum": min(dimensions.values()),
        "evidence": {
            "referential_checks": referential_checks,
            "master_data_fields": sorted(normalized_references),
        },
    }


def benchmark() -> dict[str, Any]:
    records = synthetic_sequence(5000)
    reference_time_ms = max(float(row["timestamp_ms"]) for row in records) + 30_000
    records[301] = {**records[301], "equipment_id": "CNC-UNKNOWN"}
    records[901] = dict(records[900])
    records[1701] = {**records[1701], "value": 1_000_000.0}
    result = assess(records, reference_time_ms=reference_time_ms)
    dimensions = result["dimensions"]
    return {
        "indicator": ID,
        "title": TITLE,
        "target": MILESTONE_TARGET,
        "passed": len(dimensions) >= 6 and result["minimum"] >= 95.0,
        "metrics": {
            "dimension_count": len(dimensions),
            "dimensions": dimensions,
            "overall_score": result["overall"],
            "minimum_dimension": result["minimum"],
            "labeled_anomalies": 3,
            **result["evidence"],
        },
        "method": "综合测评完整性、一致性、时效性、有效性、唯一性、主数据参照完整性和分设备稳定性 7 个维度。",
    }
