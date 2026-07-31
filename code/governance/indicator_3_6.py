"""Indicator 3.6: sequence and relational data quality controls."""

from __future__ import annotations

import math
from typing import Any

from .common import mean, pct, synthetic_sequence


ID = "3.6"
TITLE = "数据质量稳控"
MILESTONE_TARGET = "完整性、一致性、时效性、有效性等质量指标均不低于 95%"


def evaluate_quality(records: list[dict[str, Any]]) -> dict[str, float]:
    if not records:
        return {
            "completeness": 0.0,
            "consistency": 0.0,
            "timeliness": 0.0,
            "validity": 0.0,
        }
    required = ("timestamp_ms", "equipment_id", "value")
    complete = sum(
        all(row.get(key) not in (None, "") for key in required) for row in records
    )
    consistent = 0
    valid = 0
    timely = 0
    previous_by_equipment: dict[str, float] = {}
    parsed_timestamps: list[float] = []
    for row in records:
        try:
            timestamp = float(row.get("timestamp_ms"))
        except (TypeError, ValueError):
            continue
        if math.isfinite(timestamp) and timestamp > 0:
            parsed_timestamps.append(timestamp)
    latest = max(parsed_timestamps) if parsed_timestamps else None
    for row in records:
        try:
            timestamp = float(row.get("timestamp_ms"))
            value = float(row.get("value"))
            equipment = str(row.get("equipment_id", ""))
            timestamp_valid = math.isfinite(timestamp) and timestamp > 0
            value_valid = math.isfinite(value) and -1_000_000 <= value <= 1_000_000
            valid += int(bool(equipment) and value_valid and timestamp_valid)
            if not timestamp_valid:
                continue
            previous = previous_by_equipment.get(equipment)
            consistent += int(previous is None or timestamp >= previous)
            previous_by_equipment[equipment] = timestamp
            timely += int(
                latest is not None and latest - timestamp <= 15 * 60 * 1000
            )
        except (TypeError, ValueError):
            pass
    return {
        "completeness": pct(complete, len(records)),
        "consistency": pct(consistent, len(records)),
        "timeliness": pct(timely, len(records)),
        "validity": pct(valid, len(records)),
    }


def benchmark() -> dict[str, Any]:
    records = synthetic_sequence(5000)
    metrics = evaluate_quality(records)
    minimum = min(metrics.values())
    return {
        "indicator": ID,
        "title": TITLE,
        "target": MILESTONE_TARGET,
        "passed": minimum >= 95.0,
        "metrics": {
            **metrics,
            "overall_average": round(mean(metrics.values()), 2),
            "minimum_dimension": minimum,
        },
        "method": "逐记录检查必填字段、类型/范围、同设备时间单调性与数据窗口时效性。",
        "notice": "本模块可形成第三方检测前的预检证据；里程碑2正式验收仍需有检测能力的第三方机构出具报告。",
    }
