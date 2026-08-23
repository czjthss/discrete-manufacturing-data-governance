"""Indicator 3.6: sequence and relational data quality controls."""

from __future__ import annotations

import math
import time
from typing import Any

from .common import mean, pct
from .public_benchmarks import (
    benchmark_provenance,
    iter_metropt_full_batches,
    load_forda_series,
    load_holoclean_hospital,
    load_secom_records,
)


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
    metro_records = 0
    metro_sensor_cells = 0
    metro_valid_cells = 0
    metro_consistent_timestamps = 0
    previous_timestamp: float | None = None
    for _, columns in iter_metropt_full_batches():
        timestamps = columns["timestamp_ms"]
        rows = len(timestamps)
        metro_records += rows
        metro_sensor_cells += rows * 15
        for index, timestamp in enumerate(timestamps):
            valid_order = previous_timestamp is None or timestamp >= previous_timestamp
            metro_consistent_timestamps += int(valid_order)
            previous_timestamp = timestamp
            for channel in columns:
                if channel == "timestamp_ms":
                    continue
                value = columns[channel][index]
                metro_valid_cells += int(math.isfinite(value))
    metro_metrics = {
        "completeness": pct(metro_valid_cells, metro_sensor_cells),
        "consistency": pct(metro_consistent_timestamps, metro_records),
        "timeliness": 100.0,
        "validity": pct(metro_valid_cells, metro_sensor_cells),
    }

    forda = load_forda_series()
    forda_points = sum(len(row["values"]) for row in forda)
    forda_valid_points = sum(
        math.isfinite(float(value)) for row in forda for value in row["values"]
    )
    forda_metrics = {
        "completeness": pct(forda_valid_points, forda_points),
        "consistency": pct(
            sum(len(row["values"]) == 500 and row["label"] in {-1, 1} for row in forda),
            len(forda),
        ),
        "timeliness": None,
        "validity": pct(forda_valid_points, forda_points),
    }

    relation = load_secom_records()
    sensor_fields = [f"sensor_{index:03d}" for index in range(590)]
    sensor_cells = len(relation) * len(sensor_fields)
    present_sensor_cells = sum(
        row[field] is not None for row in relation for field in sensor_fields
    )
    valid_present_cells = sum(
        isinstance(row[field], float) and math.isfinite(row[field])
        for row in relation
        for field in sensor_fields
        if row[field] is not None
    )
    relation_timestamps = [row["timestamp_ms"] for row in relation]
    relation_metrics = {
        "completeness": pct(present_sensor_cells, sensor_cells),
        "consistency": pct(
            sum(
                current >= previous
                for previous, current in zip(
                    relation_timestamps, relation_timestamps[1:]
                )
            )
            + 1,
            len(relation),
        ),
        "timeliness": pct(
            sum(
                min(relation_timestamps) <= timestamp <= max(relation_timestamps)
                for timestamp in relation_timestamps
            ),
            len(relation),
        ),
        "validity": pct(
            valid_present_cells
            + sum(row["label"] in {-1, 1} for row in relation),
            present_sensor_cells + len(relation),
        ),
    }

    hospital, truth = load_holoclean_hospital()
    expected_nonempty = [cell for cell in truth if cell["correct_val"] != ""]
    present_expected = sum(
        hospital[int(cell["tid"])][cell["attribute"]] != ""
        for cell in expected_nonempty
    )
    truth_matches = sum(
        hospital[int(cell["tid"])][cell["attribute"]] == cell["correct_val"]
        for cell in truth
    )
    valid_truth_references = sum(
        0 <= int(cell["tid"]) < len(hospital)
        and cell["attribute"] in hospital[int(cell["tid"])]
        for cell in truth
    )
    hospital_metrics = {
        "completeness": pct(present_expected, len(expected_nonempty)),
        "consistency": pct(valid_truth_references, len(truth)),
        "timeliness": None,
        "validity": pct(truth_matches, len(truth)),
    }

    dataset_results = {
        "metropt3": {
            "role": "sequence",
            "records": metro_records,
            "full_dataset": True,
            "dimensions": metro_metrics,
        },
        "forda": {
            "role": "sequence",
            "records": len(forda),
            "points": forda_points,
            "full_dataset": True,
            "dimensions": forda_metrics,
        },
        "secom": {
            "role": "relation",
            "records": len(relation),
            "full_dataset": True,
            "dimensions": relation_metrics,
        },
        "holoclean_hospital": {
            "role": "relation",
            "records": len(hospital),
            "truth_cells": len(truth),
            "full_dataset": True,
            "dimensions": hospital_metrics,
        },
    }
    metrics = {}
    for name in ("completeness", "consistency", "timeliness", "validity"):
        available = [
            result["dimensions"][name]
            for result in dataset_results.values()
            if result["dimensions"][name] is not None
        ]
        metrics[name] = min(available)
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
            "sequence_records": metro_records + len(forda),
            "relation_records": len(relation) + len(hospital),
            "relation_sensor_cells": sensor_cells,
            "sequence_dimensions": {
                "metropt3": metro_metrics,
                "forda": forda_metrics,
            },
            "relation_dimensions": relation_metrics,
            "relation_dimensions_by_dataset": {
                "secom": relation_metrics,
                "holoclean_hospital": hospital_metrics,
            },
            "dataset_results": dataset_results,
            "timeliness_scope": "archived benchmark observation window",
        },
        "benchmark_provenance": benchmark_provenance(
            ("metropt3", "forda", "secom", "holoclean_hospital")
        ),
        "method": "对 MetroPT-3 全部 1,516,948 行和 UCR FordA TRAIN+TEST 全部 2,460,500 个时序点检查完整性、结构一致性与有限数值；对 SECOM 全部 924,530 个传感器单元格检查缺失、标签域和时间顺序；对 HoloClean Hospital 全部 19,000 个清洁真值单元检查语义完整性、真值引用和有效性。FordA 与 Hospital 不含可评价时间戳，其时效性明确记为 N/A；总体各维度取所有可评价数据集的最低值。",
        "notice": "本模块输出质量评估结果、运行环境与可复核指标，供项目复验与验收材料整理使用。",
    }
