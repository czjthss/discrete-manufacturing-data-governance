"""Indicator 3.7: on-demand fusion of sequence and relational data."""

from __future__ import annotations

import time
from typing import Any

from .common import pct
from .indicator_3_4 import align_records
from .public_benchmarks import (
    benchmark_manifest,
    benchmark_provenance,
    iter_metropt_full_sequence_batches,
    load_metropt_failures,
)


ID = "3.7"
TITLE = "序列、关系数据融合"
MILESTONE_TARGET = "序列、关系数据可进行融合"


def fuse(
    sequence: list[dict[str, Any]],
    relations: list[dict[str, Any]],
    tolerance_ms: float = 1000.0,
) -> list[dict[str, Any]]:
    aligned = align_records(sequence, relations, tolerance_ms=tolerance_ms)
    fused = []
    for item in aligned:
        relation = item.pop("relation", None) or {}
        fused.append(
            {
                **item,
                **{f"relation_{key}": value for key, value in relation.items()},
            }
        )
    return fused


def benchmark() -> dict[str, Any]:
    relations = list(load_metropt_failures())
    started = time.perf_counter()
    total = 0
    matched = 0
    correct = 0
    preserved = 0
    positive = 0
    negative = 0
    for sequence in iter_metropt_full_sequence_batches():
        result = fuse(sequence, relations, tolerance_ms=0)
        expected = []
        for row in sequence:
            relations_at_time = [
                relation
                for relation in relations
                if relation["start_ms"] <= row["timestamp_ms"] <= relation["end_ms"]
            ]
            if len(relations_at_time) > 1:
                raise ValueError("MetroPT-3 维护真值时间窗发生重叠")
            expected.append(
                relations_at_time[0]["work_order"] if relations_at_time else None
            )
        predicted = [row.get("relation_work_order") for row in result]
        total += len(sequence)
        matched += sum(row["aligned"] for row in result)
        correct += sum(actual == target for actual, target in zip(predicted, expected))
        positive += sum(target is not None for target in expected)
        negative += sum(target is None for target in expected)
        preserved += sum(
            fused["source_row"] == source["source_row"]
            and fused["timestamp_ms"] == source["timestamp_ms"]
            and fused["value"] == source["value"]
            for source, fused in zip(sequence, result)
        )
    elapsed = max(time.perf_counter() - started, 1e-9)
    expected_records = int(
        benchmark_manifest()["datasets"]["metropt3"]["full_archive"]["records"]
    )
    if total != expected_records:
        raise ValueError("MetroPT-3 全量融合记录数与公开清单不一致")
    return {
        "indicator": ID,
        "title": TITLE,
        "target": MILESTONE_TARGET,
        "passed": (
            total == expected_records
            and matched > 0
            and correct == total
            and preserved == total
        ),
        "metrics": {
            "sequence_rows": total,
            "expected_sequence_rows": expected_records,
            "full_dataset": True,
            "relation_rows": len(relations),
            "fused_rows": total,
            "matched_rows": matched,
            "unmatched_rows": total - matched,
            "positive_rows": positive,
            "negative_rows": negative,
            "fusion_accuracy_percent": pct(correct, total),
            "source_rows_preserved": preserved,
            "source_preservation_percent": pct(preserved, total),
            "elapsed_seconds": round(elapsed, 6),
            "rows_per_second": round(total / elapsed, 2),
            "dataset_results": {
                "metropt3": {
                    "fused_rows": total,
                    "full_dataset": True,
                    "fusion_accuracy_percent": pct(correct, total),
                    "source_preservation_percent": pct(preserved, total),
                }
            },
        },
        "benchmark_provenance": benchmark_provenance(("metropt3",)),
        "method": "流式读取 MetroPT-3 官方完整归档的全部 1,516,948 行，将真实传感器序列与其公开维护报告按设备和零容差时间窗左融合；逐行核对故障编号真值，并验证全部命中与未命中记录的 source_row、时间和值均被保留，只报告全数据总体结果。",
    }
