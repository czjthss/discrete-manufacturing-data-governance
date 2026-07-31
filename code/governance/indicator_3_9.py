"""Indicator 3.9: multi-dimensional industrial data quality assessment."""

from __future__ import annotations

import statistics
from typing import Any

from .common import mean, pct, synthetic_sequence
from .indicator_3_6 import evaluate_quality


ID = "3.9"
TITLE = "工业数据质量综合测评"
MILESTONE_TARGET = "支持 5 个以上维度的工业数据质量综合测评"


def assess(records: list[dict[str, Any]]) -> dict[str, Any]:
    base = evaluate_quality(records)
    if not records:
        dimensions = {
            **base,
            "uniqueness": 0.0,
            "integrity": 0.0,
            "stability": 0.0,
        }
        return {"dimensions": dimensions, "overall": 0.0}
    signatures = {
        (
            row.get("equipment_id"),
            row.get("timestamp_ms"),
            row.get("value"),
        )
        for row in records
    }
    uniqueness = pct(len(signatures), len(records))
    integrity = pct(
        sum("equipment_id" in row and "timestamp_ms" in row for row in records),
        len(records),
    )
    values = []
    for row in records:
        try:
            values.append(float(row.get("value")))
        except (TypeError, ValueError):
            pass
    if len(values) < 2:
        stability = 100.0 if values else 0.0
    else:
        center = statistics.median(values)
        deviations = [abs(value - center) for value in values]
        mad = statistics.median(deviations) or 1.0
        stable = sum(abs(value - center) <= 12 * mad for value in values)
        stability = pct(stable, len(values))
    dimensions = {
        **base,
        "uniqueness": uniqueness,
        "integrity": integrity,
        "stability": stability,
    }
    return {
        "dimensions": dimensions,
        "overall": round(mean(dimensions.values()), 2),
        "minimum": min(dimensions.values()),
    }


def benchmark() -> dict[str, Any]:
    result = assess(synthetic_sequence(5000))
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
        },
        "method": "综合测评完整性、一致性、时效性、有效性、唯一性、参照完整性和稳定性 7 个维度。",
    }

