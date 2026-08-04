"""Indicator 3.3: intelligent parsing for sequence and relational data."""

from __future__ import annotations

import csv
import hashlib
import io
import json
from typing import Any

from .common import flatten_records, pct, wilson_interval


ID = "3.3"
TITLE = "序列、关系数据智能解析"
MILESTONE_TARGET = "序列、关系数据解析准确率不低于 95%"


def detect_format(text: str) -> str:
    stripped = text.lstrip("\ufeff \t\r\n")
    if not stripped:
        return "empty"
    if stripped[0] in "[{":
        try:
            json.loads(stripped)
            return "json"
        except json.JSONDecodeError:
            if all(line.lstrip().startswith("{") for line in stripped.splitlines() if line.strip()):
                return "jsonl"
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
    data_format = detect_format(text) if declared_format == "auto" else declared_format
    if data_format == "json":
        records = flatten_records(json.loads(text))
    elif data_format == "jsonl":
        records = [json.loads(line) for line in text.splitlines() if line.strip()]
    elif data_format in {"csv", "tsv", "semicolon", "pipe"}:
        delimiter = {"csv": ",", "tsv": "\t", "semicolon": ";", "pipe": "|"}[data_format]
        try:
            reader = csv.DictReader(io.StringIO(text), delimiter=delimiter)
            records = list(reader)
        except csv.Error as exc:
            raise ValueError(f"表格解析失败: {exc}") from exc
        fieldnames = reader.fieldnames or []
        if any(not field for field in fieldnames):
            raise ValueError("表格字段名不能为空")
        if len(fieldnames) != len(set(fieldnames)):
            raise ValueError("表格字段名不能重复")
    else:
        raise ValueError(f"无法解析的数据格式: {data_format}")
    if not records:
        raise ValueError("输入中没有可解析的数据记录")
    if not all(isinstance(row, dict) for row in records):
        raise ValueError("解析结果必须是对象记录数组")
    if any(None in row for row in records):
        raise ValueError("表格存在超出表头范围的字段")
    if any(not all(isinstance(key, str) and key for key in row) for row in records):
        raise ValueError("记录字段名必须是非空字符串")
    columns = sorted({key for row in records for key in row})
    return {"format": data_format, "records": records, "columns": columns}


def benchmark() -> dict[str, Any]:
    fixtures: list[tuple[str, str, int, set[str]]] = []
    delimiters = {
        "csv": ",",
        "tsv": "\t",
        "semicolon": ";",
        "pipe": "|",
    }
    for data_format, delimiter in delimiters.items():
        for index in range(20):
            text = (
                f"timestamp_ms{delimiter}equipment_id{delimiter}value{delimiter}note\n"
                f"{1000 + index}{delimiter}CNC-{index % 7 + 1:02d}{delimiter}"
                f"{42 + index / 10:.1f}{delimiter}batch-{index}"
            )
            fixtures.append(
                (
                    data_format,
                    text,
                    1,
                    {"timestamp_ms", "equipment_id", "value", "note"},
                )
            )
    for index in range(20):
        wrapper = ("records", "data", "rows", "items")[index % 4]
        text = json.dumps(
            {
                wrapper: [
                    {
                        "timestamp_ms": 2000 + index,
                        "equipment_id": f"CNC-{index % 5 + 1:02d}",
                        "value": 50 + index / 10,
                    }
                ]
            },
            ensure_ascii=False,
        )
        fixtures.append(
            (
                "json",
                text,
                1,
                {"timestamp_ms", "equipment_id", "value"},
            )
        )
    for index in range(20):
        text = "\n".join(
            json.dumps(
                {
                    "timestamp_ms": 3000 + index * 2 + offset,
                    "equipment_id": f"CNC-{index % 4 + 1:02d}",
                    "value": 60 + offset,
                }
            )
            for offset in range(2)
        )
        fixtures.append(
            (
                "jsonl",
                text,
                2,
                {"timestamp_ms", "equipment_id", "value"},
            )
        )
    invalid_fixtures = [
        "",
        "plain unstructured text",
        "{broken json",
        "[1,2,3]",
        '{"records":[1,2]}',
        "id,value\n1,2,3",
        "{}\n[]",
        "[sensor]\ninvalid",
    ]
    correct = 0
    failures: list[str] = []
    for expected, text, expected_rows, expected_columns in fixtures:
        try:
            result = parse_records(text)
            matched = (
                result["format"] == expected
                and len(result["records"]) == expected_rows
                and set(result["columns"]) == expected_columns
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
    fingerprint = hashlib.sha256(
        "\n---\n".join(text for _, text, _, _ in fixtures).encode("utf-8")
    ).hexdigest()
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
            "unique_fixture_fingerprint_sha256": fingerprint,
            "failure_count": len(failures),
            "formats": ["CSV", "TSV", "分号表格", "管道表格", "JSON", "JSONL"],
        },
        "method": "格式嗅探、结构解析、字段集合提取和可重复标注样例评测。",
    }
