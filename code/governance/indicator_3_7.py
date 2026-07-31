"""Indicator 3.7: on-demand fusion of sequence and relational data."""

from __future__ import annotations

import time
from typing import Any

from .common import synthetic_relations, synthetic_sequence
from .indicator_3_4 import align_records


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
    sequence = synthetic_sequence(5000)
    relations = synthetic_relations()
    started = time.perf_counter()
    result = fuse(sequence, relations, tolerance_ms=1200)
    elapsed = max(time.perf_counter() - started, 1e-9)
    matched = sum(row["aligned"] for row in result)
    return {
        "indicator": ID,
        "title": TITLE,
        "target": MILESTONE_TARGET,
        "passed": len(result) == len(sequence) and matched > 0,
        "metrics": {
            "sequence_rows": len(sequence),
            "relation_rows": len(relations),
            "fused_rows": len(result),
            "matched_rows": matched,
            "elapsed_seconds": round(elapsed, 6),
            "rows_per_second": round(len(result) / elapsed, 2),
        },
        "preview": result[:3],
        "method": "按设备实体和有效时间窗进行按需左融合，保留未命中序列记录和对齐证据。",
    }

