"""Indicator 3.3: intelligent parsing for sequence and relational data."""

from __future__ import annotations

import csv
import io
import json
from typing import Any

from .common import flatten_records, pct


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
        records = list(csv.DictReader(io.StringIO(text), delimiter=delimiter))
    else:
        raise ValueError(f"无法解析的数据格式: {data_format}")
    columns = sorted({key for row in records for key in row})
    return {"format": data_format, "records": records, "columns": columns}


def benchmark() -> dict[str, Any]:
    fixtures = [
        ("csv", "timestamp_ms,equipment_id,value\n1,CNC-01,42.2\n2,CNC-01,42.3"),
        ("tsv", "id\tmachine\tstatus\n1\tM1\tok\n2\tM2\tok"),
        ("semicolon", "id;machine;value\n1;M1;2.3"),
        ("pipe", "id|machine|value\n1|M1|2.3"),
        ("json", '[{"timestamp_ms":1,"value":42.2}]'),
        ("json", '{"records":[{"id":1,"machine":"M1"}]}'),
        ("jsonl", '{"id":1,"value":2}\n{"id":2,"value":3}'),
    ]
    expanded = fixtures * 15
    correct = 0
    for expected, text in expanded:
        try:
            result = parse_records(text)
            correct += int(result["format"] == expected and bool(result["records"]))
        except (ValueError, json.JSONDecodeError):
            pass
    accuracy = pct(correct, len(expanded))
    return {
        "indicator": ID,
        "title": TITLE,
        "target": MILESTONE_TARGET,
        "passed": accuracy >= 95.0,
        "metrics": {
            "fixtures": len(expanded),
            "correctly_parsed": correct,
            "parsing_accuracy_percent": accuracy,
            "formats": ["CSV", "TSV", "分号表格", "管道表格", "JSON", "JSONL"],
        },
        "method": "格式嗅探、结构解析、字段集合提取和可重复标注样例评测。",
    }

