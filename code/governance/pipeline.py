"""Deterministic governance pipeline with repair, quarantine and lineage evidence."""

from __future__ import annotations

import math
from datetime import datetime
from typing import Any

from .common import new_run_id, now_iso, write_json_report
from .indicator_3_4 import normalize_schema
from .indicator_3_9 import DEFAULT_MASTER_DATA, assess


DEFAULT_RULES = {
    "trim_strings": True,
    "normalize_equipment_id": True,
    "coerce_numeric_fields": True,
    "remove_duplicates": True,
    "enforce_equipment_master": False,
}


def validate_rules(rules: dict[str, Any] | None) -> dict[str, bool]:
    if rules is None:
        return dict(DEFAULT_RULES)
    if not isinstance(rules, dict):
        raise ValueError("治理规则必须是 JSON 对象")
    unknown = sorted(set(rules) - set(DEFAULT_RULES))
    if unknown:
        raise ValueError(f"未知治理规则: {', '.join(unknown)}")
    normalized = dict(DEFAULT_RULES)
    for key, value in rules.items():
        if not isinstance(value, bool):
            raise ValueError(f"治理规则 {key} 必须是布尔值")
        normalized[key] = value
    return normalized


def _number(value: Any, field_name: str) -> float:
    if field_name == "timestamp_ms" and isinstance(value, str):
        stripped = value.strip()
        try:
            parsed = datetime.fromisoformat(stripped.replace("Z", "+00:00"))
            return parsed.timestamp() * 1000.0
        except ValueError:
            pass
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} 不是可解析数值") from exc
    if not math.isfinite(number):
        raise ValueError(f"{field_name} 不是有限数值")
    return number


def govern_records(
    records: list[dict[str, Any]],
    *,
    rules: dict[str, Any] | None = None,
    reference_data: dict[str, set[str]] | None = None,
    reference_time_ms: float | None = None,
) -> dict[str, Any]:
    if not isinstance(records, list) or not all(isinstance(row, dict) for row in records):
        raise ValueError("治理输入必须是对象数组")
    active_rules = validate_rules(rules)
    references = DEFAULT_MASTER_DATA if reference_data is None else reference_data
    allowed_equipment = {str(value) for value in references.get("equipment_id", set())}
    run_id = new_run_id("governance")
    accepted: list[dict[str, Any]] = []
    quarantined: list[dict[str, Any]] = []
    lineage: list[dict[str, Any]] = []
    signatures: set[tuple[str, str, str]] = set()

    for source_index, raw in enumerate(records):
        current = normalize_schema(raw)
        actions: list[dict[str, Any]] = []
        reasons: list[str] = []
        if active_rules["trim_strings"]:
            for key, value in list(current.items()):
                if isinstance(value, str) and value != value.strip():
                    current[key] = value.strip()
                    actions.append({"rule": "trim_strings", "field": key})
        if active_rules["normalize_equipment_id"] and "equipment_id" in current:
            original = str(current["equipment_id"])
            normalized = original.strip().upper()
            if normalized != original:
                current["equipment_id"] = normalized
                actions.append({"rule": "normalize_equipment_id", "field": "equipment_id"})
        if active_rules["coerce_numeric_fields"]:
            for field_name in ("timestamp_ms", "value"):
                if field_name not in current or current[field_name] in (None, ""):
                    continue
                try:
                    normalized_number = _number(current[field_name], field_name)
                    if current[field_name] != normalized_number:
                        current[field_name] = normalized_number
                        actions.append({"rule": "coerce_numeric_fields", "field": field_name})
                except (TypeError, ValueError) as exc:
                    reasons.append(str(exc))
        for field_name in ("timestamp_ms", "equipment_id", "value"):
            if current.get(field_name) in (None, ""):
                reasons.append(f"缺少必填字段 {field_name}")
        if (
            active_rules["enforce_equipment_master"]
            and str(current.get("equipment_id", "")) not in allowed_equipment
        ):
            reasons.append("设备标识未在主数据中登记")
        signature = (
            str(current.get("equipment_id")),
            str(current.get("timestamp_ms")),
            str(current.get("value")),
        )
        if active_rules["remove_duplicates"] and signature in signatures:
            reasons.append("重复记录")
        signatures.add(signature)

        event = {
            "source_index": source_index,
            "actions": actions,
            "status": "quarantined" if reasons else "accepted",
            "reasons": sorted(set(reasons)),
        }
        lineage.append(event)
        if reasons:
            quarantined.append({"source_index": source_index, "record": current, "reasons": event["reasons"]})
        else:
            accepted.append(current)

    before_quality = assess(
        [normalize_schema(row) for row in records],
        reference_data=references,
        reference_time_ms=reference_time_ms,
    )
    after_quality = assess(
        accepted,
        reference_data=references,
        reference_time_ms=reference_time_ms,
    )
    result = {
        "run_id": run_id,
        "governed_at": now_iso(),
        "rules": active_rules,
        "summary": {
            "input_records": len(records),
            "accepted_records": len(accepted),
            "quarantined_records": len(quarantined),
            "repaired_records": sum(
                bool(event["actions"]) and event["status"] == "accepted"
                for event in lineage
            ),
            "repair_actions": sum(len(event["actions"]) for event in lineage),
        },
        "quality_before": before_quality,
        "quality_after": after_quality,
        "records": accepted,
        "quarantine": quarantined,
        "lineage": lineage,
    }
    report_path = write_json_report(f"governance/{run_id}.json", result)
    result["report_path"] = str(report_path)
    return result
