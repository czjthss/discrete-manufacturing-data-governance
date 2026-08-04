"""Indicator 3.6: sequence and relational data quality controls."""

from __future__ import annotations

import math
import time
from typing import Any

from .common import mean, pct, synthetic_sequence


ID = "3.6"
TITLE = "数据质量稳控"
MILESTONE_TARGET = "完整性、一致性、时效性、有效性等质量指标均不低于 95%"


def evaluate_quality(
    records: list[dict[str, Any]],
    *,
    reference_time_ms: float | None = None,
    max_age_ms: float = 15 * 60 * 1000,
) -> dict[str, float]:
    if not isinstance(records, list) or not all(isinstance(row, dict) for row in records):
        raise ValueError("质量测评输入必须是对象数组")
    if reference_time_ms is None:
        reference_time_ms = time.time() * 1000.0
    try:
        reference_time_ms = float(reference_time_ms)
        max_age_ms = float(max_age_ms)
    except (TypeError, ValueError) as exc:
        raise ValueError("时效性参数必须是数值") from exc
    if not math.isfinite(reference_time_ms) or not math.isfinite(max_age_ms):
        raise ValueError("时效性参数必须是有限数值")
    if max_age_ms < 0:
        raise ValueError("最大数据年龄不能为负数")
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
                0 <= reference_time_ms - timestamp <= max_age_ms
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
    reference_time_ms = max(float(row["timestamp_ms"]) for row in records) + 30_000
    # The labeled set includes missing fields, malformed values, stale records and
    # local ordering faults while keeping each target dimension independently measurable.
    records[101] = {**records[101], "value": None}
    records[503] = {**records[503], "equipment_id": ""}
    records[1003] = {**records[1003], "timestamp_ms": "invalid"}
    records[1501] = {**records[1501], "value": float("inf")}
    records[2001] = {
        **records[2001],
        "timestamp_ms": reference_time_ms - 20 * 60 * 1000,
    }
    records[2501], records[2502] = records[2502], records[2501]
    metrics = evaluate_quality(records, reference_time_ms=reference_time_ms)
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
            "records": len(records),
            "reference_time_ms": reference_time_ms,
            "max_age_ms": 15 * 60 * 1000,
            "labeled_anomalies": 6,
        },
        "method": "逐记录检查必填字段、类型/范围、同设备时间单调性，并相对显式评测时刻计算数据年龄。",
        "notice": "本模块可形成第三方检测前的预检证据；里程碑2正式验收仍需有检测能力的第三方机构出具报告。",
    }
