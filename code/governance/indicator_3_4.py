"""Indicator 3.4: semantic and temporal alignment for heterogeneous records."""

from __future__ import annotations

import math
import re
import hashlib
import json
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

from .common import pct, wilson_interval


ID = "3.4"
TITLE = "异构数据语义时序对齐"
MILESTONE_TARGET = "序列、关系数据对齐准确率不低于 90%"

ALIASES = {
    "equipment_id": {"equipment_id", "machine_id", "device_id", "设备编号", "机床编号"},
    "timestamp_ms": {"timestamp_ms", "time", "ts", "采集时间", "时间戳"},
    "start_ms": {"start_ms", "start_time", "开始时间"},
    "end_ms": {"end_ms", "end_time", "结束时间"},
    "value": {"value", "reading", "sensor_value", "测量值", "数值"},
}
ALIAS_TO_CANONICAL = {
    alias.lower(): canonical
    for canonical, aliases in ALIASES.items()
    for alias in aliases
}
BENCHMARK_DATA_PATH = Path(__file__).with_name("benchmark_data") / "indicator_3_4_labeled.json"
BENCHMARK_DATA_SHA256 = "e5f7719a2a0c1ae01a0dc549b793e05aaa764f0bf6eaa8236f81b9a6f9587b6d"


def canonical_key(key: str) -> str:
    lowered = str(key).strip().lower()
    return ALIAS_TO_CANONICAL.get(lowered, lowered)


def normalize_schema(record: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(record, dict):
        raise ValueError("待对齐记录必须是对象")
    return {canonical_key(key): value for key, value in record.items()}


def _entity_token(value: Any) -> str:
    return re.sub(r"[^a-z0-9]", "", str(value).strip().lower())


def _finite_number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _candidate_entities(
    token: str,
    available: tuple[str, ...],
    fuzzy_threshold: float,
) -> tuple[list[str], str]:
    if token in available:
        return [token], "exact"
    scored = [
        (SequenceMatcher(None, token, candidate).ratio(), candidate)
        for candidate in available
        if token and candidate
    ]
    if not scored:
        return [], "none"
    best_score = max(score for score, _ in scored)
    if best_score < fuzzy_threshold:
        return [], "none"
    best = sorted(candidate for score, candidate in scored if score == best_score)
    return best, "fuzzy"


def align_records(
    sequence: list[dict[str, Any]],
    relations: list[dict[str, Any]],
    tolerance_ms: float = 1200.0,
    fuzzy_threshold: float = 0.88,
) -> list[dict[str, Any]]:
    tolerance = _finite_number(tolerance_ms)
    if tolerance is None or tolerance < 0:
        raise ValueError("时间容差必须是有限非负数")
    threshold = _finite_number(fuzzy_threshold)
    if threshold is None or not 0 <= threshold <= 1:
        raise ValueError("实体模糊匹配阈值必须在 0 到 1 之间")
    if not isinstance(sequence, list) or not isinstance(relations, list):
        raise ValueError("序列数据和关系数据必须是数组")

    relations_by_equipment: dict[str, list[dict[str, Any]]] = {}
    invalid_relation_count = 0
    for raw_relation in relations:
        try:
            relation = normalize_schema(raw_relation)
        except ValueError:
            invalid_relation_count += 1
            continue
        equipment_token = _entity_token(relation.get("equipment_id", ""))
        start = _finite_number(relation.get("start_ms", relation.get("timestamp_ms")))
        end = _finite_number(relation.get("end_ms", start))
        if not equipment_token or start is None or end is None or end < start:
            invalid_relation_count += 1
            continue
        prepared = {**relation, "_start_ms": start, "_end_ms": end}
        relations_by_equipment.setdefault(equipment_token, []).append(prepared)

    available_entities = tuple(sorted(relations_by_equipment))
    aligned = []
    for raw_sample in sequence:
        try:
            sample = normalize_schema(raw_sample)
        except ValueError as exc:
            aligned.append(
                {
                    "raw": raw_sample,
                    "aligned": False,
                    "alignment_distance_ms": None,
                    "alignment_reason": str(exc),
                    "entity_match": "none",
                    "relation": None,
                    "invalid_relation_count": invalid_relation_count,
                }
            )
            continue
        equipment_token = _entity_token(sample.get("equipment_id", ""))
        timestamp = _finite_number(sample.get("timestamp_ms"))
        if not equipment_token:
            reason = "缺少有效设备标识"
            entity_keys: list[str] = []
            match_kind = "none"
        elif timestamp is None:
            reason = "时间戳不是有限数值"
            entity_keys = []
            match_kind = "none"
        else:
            entity_keys, match_kind = _candidate_entities(
                equipment_token, available_entities, threshold
            )
            reason = "未找到设备实体" if not entity_keys else "超出时间容差"

        ranked: list[tuple[tuple[float, float, float, str], dict[str, Any]]] = []
        if timestamp is not None:
            for entity_key in entity_keys:
                for relation in relations_by_equipment[entity_key]:
                    start = relation["_start_ms"]
                    end = relation["_end_ms"]
                    distance = (
                        0.0
                        if start <= timestamp <= end
                        else min(abs(timestamp - start), abs(timestamp - end))
                    )
                    if distance <= tolerance:
                        width = end - start
                        center_distance = abs(timestamp - (start + end) / 2.0)
                        stable_key = str(relation.get("work_order", relation))
                        ranked.append(
                            ((distance, width, center_distance, stable_key), relation)
                        )
        matched = min(ranked, key=lambda item: item[0]) if ranked else None
        if matched:
            rank, relation = matched
            public_relation = {
                key: value for key, value in relation.items() if not key.startswith("_")
            }
            reason = "时间窗命中"
            distance = round(rank[0], 3)
        else:
            public_relation = None
            distance = None
        aligned.append(
            {
                **sample,
                "aligned": public_relation is not None,
                "alignment_distance_ms": distance,
                "alignment_reason": reason,
                "entity_match": match_kind,
                "relation": public_relation,
                "invalid_relation_count": invalid_relation_count,
            }
        )
    return aligned


def benchmark() -> dict[str, Any]:
    dataset_bytes = BENCHMARK_DATA_PATH.read_bytes()
    dataset_sha256 = hashlib.sha256(dataset_bytes).hexdigest()
    if dataset_sha256 != BENCHMARK_DATA_SHA256:
        raise ValueError("3.4 标注数据与固定版本哈希不一致")
    dataset = json.loads(dataset_bytes)
    sequence = dataset["sequence"]
    relations = dataset["relations"]
    expected = dataset["expected_work_orders"]
    tolerance_ms = dataset["tolerance_ms"]
    results = align_records(sequence, relations, tolerance_ms=tolerance_ms)
    predicted = [
        result["relation"].get("work_order") if result["relation"] else None
        for result in results
    ]
    correct = sum(actual == label for actual, label in zip(predicted, expected))
    accuracy = pct(correct, len(expected))
    ci_low, ci_high = wilson_interval(correct, len(expected))
    return {
        "indicator": ID,
        "title": TITLE,
        "target": MILESTONE_TARGET,
        "passed": accuracy >= 90.0,
        "metrics": {
            "samples": len(expected),
            "correct_alignments": correct,
            "alignment_accuracy_percent": accuracy,
            "accuracy_wilson_95_percent": [ci_low, ci_high],
            "accuracy_interval_scope": (
                "固定标注样例集合的描述性二项区间，不用于推断未抽样业务数据的总体准确率"
            ),
            "negative_samples": dataset["negative_samples"],
            "fuzzy_entity_samples": sum(row["entity_match"] == "fuzzy" for row in results),
            "time_tolerance_ms": tolerance_ms,
            "labeled_dataset_id": dataset["dataset_id"],
            "labeled_dataset_version": dataset["version"],
            "labeled_dataset_sha256": dataset_sha256,
        },
        "method": "字段别名归一、设备实体约束、受控模糊匹配，并按距离、时间窗宽度和中心距离排序。",
    }
