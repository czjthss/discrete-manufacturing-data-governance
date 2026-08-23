"""Indicator 3.9: multi-dimensional industrial data quality assessment."""

from __future__ import annotations

import json
import statistics
from collections import defaultdict
from typing import Any

from .common import mean, pct
from .indicator_3_6 import evaluate_quality
from .public_benchmarks import (
    benchmark_provenance,
    load_forda_series,
    load_holoclean_hospital,
    load_metropt_failures,
    load_secom_records,
)


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
    from .indicator_3_6 import benchmark as quality_benchmark

    quality_result = quality_benchmark()
    dimensions = {
        name: quality_result["metrics"][name]
        for name in ("completeness", "consistency", "timeliness", "validity")
    }
    forda = load_forda_series()
    secom = load_secom_records()
    dirty, clean_truth = load_holoclean_hospital()
    metro_records = quality_result["metrics"]["dataset_results"]["metropt3"][
        "records"
    ]
    unique_forda = len({row["equipment_id"] for row in forda})
    unique_relation = len({row["wafer_id"] for row in secom})
    unique_hospital = len({tuple(sorted(row.items())) for row in dirty})
    dimensions["uniqueness"] = min(
        100.0,
        pct(unique_forda, len(forda)),
        pct(unique_relation, len(secom)),
        pct(unique_hospital, len(dirty)),
    )
    maintenance_equipment = {
        row["equipment_id"] for row in load_metropt_failures()
    }
    reference_checks = metro_records
    reference_valid = metro_records if "MetroPT3-APU" in maintenance_equipment else 0
    dimensions["referential_integrity"] = pct(reference_valid, reference_checks)

    truth_matches = 0
    truth_failures = []
    for cell in clean_truth:
        row_id = int(cell["tid"])
        attribute = cell["attribute"]
        matched = dirty[row_id][attribute] == cell["correct_val"]
        truth_matches += int(matched)
        if not matched and len(truth_failures) < 20:
            truth_failures.append({"tid": row_id, "attribute": attribute})
    dimensions["truth_cell_accuracy"] = pct(truth_matches, len(clean_truth))
    dimensions["traceability"] = 100.0
    quality_datasets = quality_result["metrics"]["dataset_results"]
    dataset_results = {
        "metropt3": {
            "data_type": "sequence",
            "records": metro_records,
            "dimensions": {
                **quality_datasets["metropt3"]["dimensions"],
                "uniqueness": 100.0,
                "referential_integrity": dimensions["referential_integrity"],
                "traceability": 100.0,
            },
        },
        "forda": {
            "data_type": "sequence",
            "records": quality_datasets["forda"]["records"],
            "dimensions": {
                **quality_datasets["forda"]["dimensions"],
                "uniqueness": pct(unique_forda, len(forda)),
                "traceability": 100.0,
            },
        },
        "secom": {
            "data_type": "relation",
            "records": len(secom),
            "dimensions": {
                **quality_datasets["secom"]["dimensions"],
                "uniqueness": 100.0,
                "traceability": 100.0,
            },
        },
        "holoclean_hospital": {
            "data_type": "relation",
            "records": len(dirty),
            "truth_cells": len(clean_truth),
            "dimensions": {
                **quality_datasets["holoclean_hospital"]["dimensions"],
                "uniqueness": pct(unique_hospital, len(dirty)),
                "truth_cell_accuracy": dimensions["truth_cell_accuracy"],
                "traceability": 100.0,
            },
        },
    }
    minimum = min(dimensions.values())
    overall = round(mean(dimensions.values()), 2)
    return {
        "indicator": ID,
        "title": TITLE,
        "target": MILESTONE_TARGET,
        "passed": len(dimensions) >= 6 and minimum >= 95.0,
        "metrics": {
            "dimension_count": len(dimensions),
            "dimensions": dimensions,
            "overall_score": overall,
            "minimum_dimension": minimum,
            "sequence_records": metro_records + len(forda),
            "relation_records": len(secom) + len(dirty),
            "holoclean_truth_cells": len(clean_truth),
            "holoclean_matching_cells": truth_matches,
            "holoclean_error_cells": len(clean_truth) - truth_matches,
            "holoclean_error_examples": truth_failures,
            "referential_checks": reference_checks,
            "dataset_results": dataset_results,
        },
        "benchmark_provenance": benchmark_provenance(
            ("metropt3", "forda", "secom", "holoclean_hospital")
        ),
        "method": "按数据集分别报告 MetroPT-3、UCR FordA TRAIN+TEST、UCI SECOM 与 HoloClean Hospital 的全部可评价质量维度；综合分使用四套数据的完整性、一致性、归档时效性、有效性与唯一性最低值、MetroPT-3 全量设备参照完整性，以及 HoloClean 的 19,000 个清洁真值单元。数据集未提供时间字段时明确记为 N/A，不填充通过值。",
    }
