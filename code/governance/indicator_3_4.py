"""Indicator 3.4: semantic and temporal alignment for heterogeneous records."""

from __future__ import annotations

from typing import Any

from .common import pct


ID = "3.4"
TITLE = "异构数据语义时序对齐"
MILESTONE_TARGET = "序列、关系数据对齐准确率不低于 90%"

ALIASES = {
    "equipment_id": {"equipment_id", "machine_id", "device_id", "设备编号", "机床编号"},
    "timestamp_ms": {"timestamp_ms", "time", "ts", "采集时间", "时间戳"},
    "value": {"value", "reading", "sensor_value", "测量值", "数值"},
}
ALIAS_TO_CANONICAL = {
    alias.lower(): canonical
    for canonical, aliases in ALIASES.items()
    for alias in aliases
}


def canonical_key(key: str) -> str:
    lowered = key.strip().lower()
    return ALIAS_TO_CANONICAL.get(lowered, lowered)


def normalize_schema(record: dict[str, Any]) -> dict[str, Any]:
    return {canonical_key(key): value for key, value in record.items()}


def align_records(
    sequence: list[dict[str, Any]],
    relations: list[dict[str, Any]],
    tolerance_ms: float = 1200.0,
) -> list[dict[str, Any]]:
    normalized_relations = [normalize_schema(row) for row in relations]
    relations_by_equipment: dict[str, list[dict[str, Any]]] = {}
    for relation in normalized_relations:
        equipment_id = str(relation.get("equipment_id", ""))
        relations_by_equipment.setdefault(equipment_id, []).append(relation)

    aligned = []
    for raw_sample in sequence:
        sample = normalize_schema(raw_sample)
        equipment_id = str(sample.get("equipment_id", ""))
        timestamp = float(sample.get("timestamp_ms", 0))
        candidates = relations_by_equipment.get(equipment_id, ())
        matched = None
        best_distance = float("inf")
        for relation in candidates:
            start = float(relation.get("start_ms", relation.get("timestamp_ms", 0)))
            end = float(relation.get("end_ms", start))
            distance = 0.0 if start <= timestamp <= end else min(abs(timestamp - start), abs(timestamp - end))
            if distance < best_distance and distance <= tolerance_ms:
                matched, best_distance = relation, distance
        aligned.append(
            {
                **sample,
                "aligned": matched is not None,
                "alignment_distance_ms": None if matched is None else round(best_distance, 3),
                "relation": matched,
            }
        )
    return aligned


def benchmark() -> dict[str, Any]:
    base = 1_767_225_600_000
    sequence = []
    relations = []
    expected = []
    for index in range(120):
        equipment = f"CNC-{index % 6 + 1:02d}"
        timestamp = base + index * 20
        sequence.append(
            {
                "机床编号" if index % 2 else "machine_id": equipment,
                "采集时间" if index % 3 else "ts": timestamp,
                "测量值": 40 + index / 100,
            }
        )
        relations.append(
            {
                "equipment_id": equipment,
                "start_ms": timestamp - 5,
                "end_ms": timestamp + 5,
                "work_order": f"WO-{index:03d}",
            }
        )
        expected.append(f"WO-{index:03d}")
    results = align_records(sequence, relations, tolerance_ms=50)
    correct = sum(
        result["relation"] is not None
        and result["relation"].get("work_order") == work_order
        for result, work_order in zip(results, expected)
    )
    accuracy = pct(correct, len(expected))
    return {
        "indicator": ID,
        "title": TITLE,
        "target": MILESTONE_TARGET,
        "passed": accuracy >= 90.0,
        "metrics": {
            "samples": len(expected),
            "correct_alignments": correct,
            "alignment_accuracy_percent": accuracy,
            "time_tolerance_ms": 50,
        },
        "method": "字段别名统一表征 + 设备实体约束 + 最近时间窗匹配。",
    }
