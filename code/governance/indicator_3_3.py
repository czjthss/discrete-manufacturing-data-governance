"""Indicator 3.3: intelligent parsing for sequence and relational data."""

from __future__ import annotations

import csv
import hashlib
import io
import json
from pathlib import Path
from typing import Any

from .common import pct, wilson_interval


ID = "3.3"
TITLE = "序列、关系数据智能解析"
MILESTONE_TARGET = "序列、关系数据解析准确率不低于 95%"
MAX_RECORDS = 500_000
MAX_COLUMNS = 2_048
JSON_WRAPPERS = ("records", "data", "rows", "items")
_JSON_DECODER = json.JSONDecoder()
BENCHMARK_DATA_PATH = Path(__file__).with_name("benchmark_data") / "indicator_3_3_labeled.json"
BENCHMARK_DATA_SHA256 = "9bf14e23241ecc6c1d02f5cebe117ce9e22da0e2a1658785a2973079557fa44a"


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
        parsed = json.loads(text[start:end])
    except json.JSONDecodeError as exc:
        raise ValueError(f"JSON 对象无效: {exc.msg}") from exc
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
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"JSONL 第 {line_number} 行无效: {exc.msg}") from exc
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
    dataset_bytes = BENCHMARK_DATA_PATH.read_bytes()
    dataset_sha256 = hashlib.sha256(dataset_bytes).hexdigest()
    if dataset_sha256 != BENCHMARK_DATA_SHA256:
        raise ValueError("3.3 标注数据与固定版本哈希不一致")
    dataset = json.loads(dataset_bytes)
    fixtures = dataset["valid"]
    invalid_fixtures = dataset["invalid"]
    correct = 0
    failures: list[str] = []
    for fixture in fixtures:
        expected = fixture["expected_format"]
        try:
            result = parse_records(fixture["text"])
            matched = (
                result["format"] == expected
                and len(result["records"]) == fixture["expected_rows"]
                and result["columns"] == fixture["expected_columns"]
            )
            correct += int(matched)
            if not matched:
                failures.append(expected)
        except (TypeError, ValueError, json.JSONDecodeError, csv.Error) as exc:
            failures.append(f"{expected}: {exc}")
    rejected = 0
    for text in invalid_fixtures:
        try:
            parse_records(text)
        except (TypeError, ValueError, json.JSONDecodeError, csv.Error):
            rejected += 1
    total = len(fixtures) + len(invalid_fixtures)
    correct_total = correct + rejected
    accuracy = pct(correct_total, total)
    ci_low, ci_high = wilson_interval(correct_total, total)
    fingerprint = dataset_sha256
    return {
        "indicator": ID,
        "title": TITLE,
        "target": MILESTONE_TARGET,
        "passed": accuracy >= 95.0 and not failures,
        "metrics": {
            "fixtures": total,
            "valid_fixtures": len(fixtures),
            "invalid_fixtures": len(invalid_fixtures),
            "correctly_parsed": correct_total,
            "parsing_accuracy_percent": accuracy,
            "accuracy_wilson_95_percent": [ci_low, ci_high],
            "accuracy_interval_scope": (
                "固定标注样例集合的描述性二项区间，不用于推断未抽样业务数据的总体准确率"
            ),
            "unique_fixture_fingerprint_sha256": fingerprint,
            "labeled_dataset_id": dataset["dataset_id"],
            "labeled_dataset_version": dataset["version"],
            "failure_count": len(failures),
            "formats": ["CSV", "TSV", "分号表格", "管道表格", "JSON", "JSONL"],
        },
        "method": "格式嗅探、结构解析、字段集合提取和版本化标注数据集评测。",
    }
