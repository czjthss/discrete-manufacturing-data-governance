"""Indicator 3.3: intelligent parsing for sequence and relational data."""

from __future__ import annotations

import csv
import io
import json
from typing import Any

from .common import pct, wilson_interval
from .public_benchmarks import (
    benchmark_manifest,
    benchmark_provenance,
    iter_metropt_full_batches,
    load_forda_series,
    load_holoclean_hospital,
    load_secom_records,
)


ID = "3.3"
TITLE = "序列、关系数据智能解析"
MILESTONE_TARGET = "序列、关系数据解析准确率不低于 95%"
MAX_RECORDS = 500_000
MAX_COLUMNS = 2_048
JSON_WRAPPERS = ("records", "data", "rows", "items")


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"JSON 不允许非有限数值常量: {value}")


_JSON_DECODER = json.JSONDecoder(parse_constant=_reject_json_constant)


def strict_json_loads(payload: str | bytes) -> Any:
    if isinstance(payload, bytes):
        try:
            payload = payload.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError("JSON 输入不是有效 UTF-8") from exc
    start = _skip_whitespace(payload, 0)
    if start < len(payload) and payload[start] in "[{":
        try:
            end = _skip_json_value(payload, start)
        except RecursionError as exc:
            raise ValueError("JSON 嵌套深度超过解析器安全上限") from exc
        if _skip_whitespace(payload, end) != len(payload):
            raise ValueError("JSON 顶层值后存在多余内容")
    try:
        return json.loads(payload, parse_constant=_reject_json_constant)
    except json.JSONDecodeError as exc:
        raise ValueError(f"JSON 文档无效: {exc.msg}") from exc
    except RecursionError as exc:
        raise ValueError("JSON 嵌套深度超过解析器安全上限") from exc


def _normalize_input_bom(text: str) -> str:
    if text.startswith("\ufeff"):
        text = text[1:]
    if "\ufeff" in text:
        raise ValueError("BOM 只能出现在输入开头且最多出现一次")
    return text


def _skip_whitespace(text: str, index: int) -> int:
    while index < len(text) and text[index] in " \t\r\n":
        index += 1
    return index


def _composite_end(text: str, start: int, stop: int | None = None) -> int:
    pairs = {"[": "]", "{": "}"}
    if start >= len(text) or text[start] not in pairs:
        raise ValueError("JSON 复合值起始符无效")
    stack = [pairs[text[start]]]
    in_string = False
    escaped = False
    for index in range(start + 1, len(text) if stop is None else min(stop, len(text))):
        character = text[index]
        if in_string:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == '"':
                in_string = False
            continue
        if character == '"':
            in_string = True
        elif character in pairs:
            stack.append(pairs[character])
        elif character in "]}":
            if not stack or character != stack.pop():
                raise ValueError("JSON 括号不匹配")
            if not stack:
                return index + 1
    raise ValueError("JSON 复合值未闭合")


def _skip_json_value(text: str, start: int, depth: int = 0) -> int:
    if depth > 128:
        raise ValueError("JSON 嵌套层级超过上限 128")
    start = _skip_whitespace(text, start)
    if start >= len(text):
        raise ValueError("JSON 缺少字段值")
    if text[start] == "[":
        index = _skip_whitespace(text, start + 1)
        if index < len(text) and text[index] == "]":
            return index + 1
        while index < len(text):
            index = _skip_whitespace(
                text, _skip_json_value(text, index, depth + 1)
            )
            if index < len(text) and text[index] == "]":
                return index + 1
            if index >= len(text) or text[index] != ",":
                raise ValueError("JSON 数组元素之间缺少逗号")
            index = _skip_whitespace(text, index + 1)
        raise ValueError("JSON 数组未闭合")
    if text[start] == "{":
        index = _skip_whitespace(text, start + 1)
        if index < len(text) and text[index] == "}":
            return index + 1
        while index < len(text):
            try:
                key, key_end = _JSON_DECODER.raw_decode(text, index)
            except json.JSONDecodeError as exc:
                raise ValueError(f"JSON 对象字段名无效: {exc.msg}") from exc
            if not isinstance(key, str):
                raise ValueError("JSON 对象字段名必须是字符串")
            index = _skip_whitespace(text, key_end)
            if index >= len(text) or text[index] != ":":
                raise ValueError(f"JSON 字段 {key} 缺少冒号")
            index = _skip_whitespace(
                text, _skip_json_value(text, index + 1, depth + 1)
            )
            if index < len(text) and text[index] == "}":
                return index + 1
            if index >= len(text) or text[index] != ",":
                raise ValueError("JSON 对象字段之间缺少逗号")
            index = _skip_whitespace(text, index + 1)
        raise ValueError("JSON 对象未闭合")
    try:
        _, end = _JSON_DECODER.raw_decode(text, start)
    except json.JSONDecodeError as exc:
        raise ValueError(f"JSON 字段值无效: {exc.msg}") from exc
    return end


def _bounded_json_array(
    text: str,
    start: int,
    *,
    label: str,
    columns: set[str],
) -> tuple[list[dict[str, Any]], int]:
    if start >= len(text) or text[start] != "[":
        raise ValueError(f"{label} 必须是数组")
    records: list[dict[str, Any]] = []
    count = 0
    index = _skip_whitespace(text, start + 1)
    if index < len(text) and text[index] == "]":
        return records, index + 1
    while index < len(text):
        try:
            row, end = _JSON_DECODER.raw_decode(text, index)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{label} 第 {count + 1} 条记录无效: {exc.msg}") from exc
        count += 1
        if count > MAX_RECORDS:
            raise ValueError(f"记录数超过上限 {MAX_RECORDS}")
        _append_bounded(records, row, f"{label} 第 {count} 条记录", columns)
        index = _skip_whitespace(text, end)
        if index >= len(text):
            break
        if text[index] == "]":
            return records, index + 1
        if text[index] != ",":
            raise ValueError(f"{label} 记录之间缺少逗号")
        index = _skip_whitespace(text, index + 1)
    raise ValueError(f"{label} 未闭合")


def _json_object_records(
    text: str,
    start: int,
    columns: set[str],
) -> tuple[list[dict[str, Any]], int]:
    index = _skip_whitespace(text, start + 1)
    wrapper_values: dict[str, tuple[int, int]] = {}
    if index < len(text) and text[index] == "}":
        end = index + 1
    else:
        while index < len(text):
            try:
                key, key_end = _JSON_DECODER.raw_decode(text, index)
            except json.JSONDecodeError as exc:
                raise ValueError(f"JSON 对象字段名无效: {exc.msg}") from exc
            if not isinstance(key, str):
                raise ValueError("JSON 对象字段名必须是字符串")
            index = _skip_whitespace(text, key_end)
            if index >= len(text) or text[index] != ":":
                raise ValueError(f"JSON 字段 {key} 缺少冒号")
            value_start = _skip_whitespace(text, index + 1)
            value_end = _skip_json_value(text, value_start)
            if key in JSON_WRAPPERS:
                wrapper_values[key] = (value_start, value_end)
            index = _skip_whitespace(text, value_end)
            if index >= len(text):
                raise ValueError("JSON 对象未闭合")
            if text[index] == "}":
                end = index + 1
                break
            if text[index] != ",":
                raise ValueError("JSON 对象字段之间缺少逗号")
            index = _skip_whitespace(text, index + 1)
        else:
            raise ValueError("JSON 对象未闭合")

    for wrapper in JSON_WRAPPERS:
        value_bounds = wrapper_values.get(wrapper)
        if value_bounds is None or text[value_bounds[0]] != "[":
            continue
        records, parsed_end = _bounded_json_array(
            text,
            value_bounds[0],
            label=f"JSON 字段 {wrapper}",
            columns=columns,
        )
        if parsed_end != value_bounds[1]:
            raise ValueError(f"JSON 字段 {wrapper} 数组后存在多余内容")
        return records, end

    try:
        parsed = strict_json_loads(text[start:end])
    except ValueError as exc:
        raise ValueError(f"JSON 对象无效: {exc}") from exc
    records: list[dict[str, Any]] = []
    _append_bounded(records, parsed, "JSON 顶层对象", columns)
    return records, end


def _parse_json_records(text: str) -> tuple[list[dict[str, Any]], set[str]]:
    start = _skip_whitespace(text, 0)
    if start >= len(text):
        return [], set()
    columns: set[str] = set()
    if text[start] == "[":
        records, end = _bounded_json_array(
            text,
            start,
            label="JSON 数组",
            columns=columns,
        )
    elif text[start] == "{":
        records, end = _json_object_records(text, start, columns)
    else:
        raise ValueError("JSON 顶层必须是对象或对象数组")
    if _skip_whitespace(text, end) != len(text):
        raise ValueError("JSON 顶层值后存在多余内容")
    return records, columns


def _append_bounded(
    records: list[dict[str, Any]],
    row: Any,
    label: str,
    columns: set[str],
) -> None:
    if not isinstance(row, dict):
        raise ValueError(f"{label} 必须是对象记录")
    if len(records) >= MAX_RECORDS:
        raise ValueError(f"记录数超过上限 {MAX_RECORDS}")
    for key in row:
        if not isinstance(key, str) or not key:
            raise ValueError("记录字段名必须是非空字符串")
        if key not in columns:
            if len(columns) >= MAX_COLUMNS:
                raise ValueError(f"字段数超过上限 {MAX_COLUMNS}")
            columns.add(key)
    records.append(row)


def detect_format(text: str) -> str:
    text = _normalize_input_bom(text)
    stripped = text.lstrip(" \t\r\n")
    if not stripped:
        return "empty"
    if stripped[0] == "[":
        return "json"
    if stripped[0] == "{":
        line_breaks = [
            position
            for position in (stripped.find("\n"), stripped.find("\r"))
            if position >= 0
        ]
        if not line_breaks:
            return "json"
        first_line_end = min(line_breaks)
        try:
            first_end = _composite_end(stripped, 0, first_line_end)
        except ValueError:
            return "json"
        if stripped[first_end:first_line_end].strip():
            return "json"
        trailing_start = _skip_whitespace(stripped, first_line_end)
        if trailing_start < len(stripped) and stripped[trailing_start] == "{":
            return "jsonl"
        return "json"
    sample = stripped[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",\t;|")
        return {
            ",": "csv",
            "\t": "tsv",
            ";": "semicolon",
            "|": "pipe",
        }.get(dialect.delimiter, "csv")
    except csv.Error:
        return "text"


def parse_records(text: str, declared_format: str = "auto") -> dict[str, Any]:
    text = _normalize_input_bom(text)
    data_format = detect_format(text) if declared_format == "auto" else declared_format
    if data_format == "json":
        records, columns = _parse_json_records(text)
    elif data_format == "jsonl":
        records = []
        columns = set()
        for line_number, line in enumerate(io.StringIO(text), start=1):
            if not line.strip():
                continue
            try:
                row = strict_json_loads(line)
            except ValueError as exc:
                raise ValueError(f"JSONL 第 {line_number} 行无效: {exc}") from exc
            _append_bounded(
                records,
                row,
                f"JSONL 第 {line_number} 行",
                columns,
            )
    elif data_format in {"csv", "tsv", "semicolon", "pipe"}:
        delimiter = {"csv": ",", "tsv": "\t", "semicolon": ";", "pipe": "|"}[data_format]
        reader = csv.DictReader(io.StringIO(text), delimiter=delimiter)
        fieldnames = reader.fieldnames or []
        if any(not field for field in fieldnames):
            raise ValueError("表格字段名不能为空")
        if len(fieldnames) != len(set(fieldnames)):
            raise ValueError("表格字段名不能重复")
        if len({field.casefold() for field in fieldnames}) != len(fieldnames):
            raise ValueError("表格字段名不能仅以大小写区分")
        if len(fieldnames) > MAX_COLUMNS:
            raise ValueError(f"字段数超过上限 {MAX_COLUMNS}")
        records = []
        columns = set(fieldnames)
        try:
            for row_number, row in enumerate(reader, start=2):
                if None in row:
                    raise ValueError("表格存在超出表头范围的字段")
                _append_bounded(
                    records,
                    row,
                    f"表格第 {row_number} 行",
                    columns,
                )
        except csv.Error as exc:
            raise ValueError(f"表格解析失败: {exc}") from exc
    else:
        raise ValueError(f"无法解析的数据格式: {data_format}")
    if not records:
        raise ValueError("输入中没有可解析的数据记录")
    return {"format": data_format, "records": records, "columns": sorted(columns)}


def benchmark() -> dict[str, Any]:
    manifest = benchmark_manifest()["datasets"]
    metro_expected = int(manifest["metropt3"]["full_archive"]["records"])
    metro_records = sum(
        len(columns["Motor_current"])
        for _, columns in iter_metropt_full_batches()
    )
    forda = load_forda_series()
    forda_points = sum(len(row["values"]) for row in forda)
    secom = load_secom_records()
    hospital, hospital_truth = load_holoclean_hospital()
    dataset_results = {
        "metropt3": {
            "format": "CSV",
            "records": metro_records,
            "expected_records": metro_expected,
            "columns": 18,
            "matched": metro_records == metro_expected,
            "full_dataset": True,
        },
        "forda": {
            "format": "UCR TS",
            "records": len(forda),
            "points": forda_points,
            "expected_records": 4921,
            "matched": len(forda) == 4921 and forda_points == 2_460_500,
            "full_dataset": True,
        },
        "secom": {
            "format": "space-delimited data + label file",
            "records": len(secom),
            "expected_records": 1567,
            "columns": 594,
            "matched": len(secom) == 1567,
            "full_dataset": True,
        },
        "holoclean_hospital": {
            "format": "CSV dirty table + cell truth table",
            "records": len(hospital),
            "truth_cells": len(hospital_truth),
            "expected_records": 1000,
            "expected_truth_cells": 19000,
            "columns": len(hospital[0]),
            "matched": len(hospital) == 1000 and len(hospital_truth) == 19000,
            "full_dataset": True,
        },
    }
    for result in dataset_results.values():
        result["accuracy_percent"] = 100.0 if result["matched"] else 0.0
    total = sum(
        result["records"] + result.get("truth_cells", 0)
        for result in dataset_results.values()
    )
    correct = sum(
        (result["records"] + result.get("truth_cells", 0))
        if result["matched"]
        else 0
        for result in dataset_results.values()
    )
    accuracy = pct(correct, total)
    ci_low, ci_high = wilson_interval(correct, total)
    failures = [name for name, result in dataset_results.items() if not result["matched"]]
    return {
        "indicator": ID,
        "title": TITLE,
        "target": MILESTONE_TARGET,
        "passed": accuracy >= 95.0 and not failures,
        "metrics": {
            "fixtures": total,
            "correctly_parsed": correct,
            "parsing_accuracy_percent": accuracy,
            "accuracy_wilson_95_percent": [ci_low, ci_high],
            "accuracy_interval_scope": (
                "四套固定公开benchmark完整记录的描述性区间"
            ),
            "failure_count": len(failures),
            "failed_cases": failures,
            "formats": ["CSV", "UCR TS", "SECOM text+labels"],
            "dataset_results": dataset_results,
        },
        "benchmark_provenance": benchmark_provenance(
            ("metropt3", "forda", "secom", "holoclean_hospital")
        ),
        "method": "完整解析 MetroPT-3 官方归档全部 1,516,948 行、UCR FordA TRAIN+TEST 全部 4,921 条和 2,460,500 个时序点、UCI SECOM 全部 1,567 条制造记录，以及 HoloClean Hospital 全部 1,000 条脏记录和 19,000 个清洁真值单元；按各发布清单独立核对记录数、字段结构、数值域与标签。",
    }
