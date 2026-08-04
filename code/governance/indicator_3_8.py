"""Indicator 3.8: extensible industrial data normalization test framework."""

from __future__ import annotations

import configparser
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import Any, Callable

from .indicator_3_3 import parse_records


ID = "3.8"
TITLE = "工业异构数据规范化测试框架"
MILESTONE_TARGET = "搭建工业异构数据规范化测试框架"


@dataclass
class Adapter:
    name: str
    extensions: tuple[str, ...]
    parser: Callable[[str], list[dict[str, Any]]]


class NormalizationRegistry:
    def __init__(self) -> None:
        self.adapters: dict[str, Adapter] = {}
        self._register_defaults()

    def register(self, adapter: Adapter) -> None:
        if not adapter.name or not callable(adapter.parser):
            raise ValueError("适配器名称和解析函数不能为空")
        self.adapters[adapter.name] = adapter

    def normalize(self, text: str, format_name: str = "auto") -> dict[str, Any]:
        if format_name == "auto":
            result = parse_records(text)
            return {
                "format": result["format"],
                "records": result["records"],
                "columns": result["columns"],
                "normalized": True,
            }
        if format_name not in self.adapters:
            raise ValueError(f"未注册适配器: {format_name}")
        records = self.adapters[format_name].parser(text)
        if not records or not all(isinstance(row, dict) for row in records):
            raise ValueError("规范化结果必须是非空对象数组")
        if any(not all(isinstance(key, str) and key for key in row) for row in records):
            raise ValueError("规范化结果包含无效字段名")
        columns = sorted({key for row in records for key in row})
        return {
            "format": format_name,
            "records": records,
            "columns": columns,
            "normalized": True,
        }

    def _register_defaults(self) -> None:
        for name in ("csv", "tsv", "semicolon", "pipe", "json", "jsonl"):
            self.register(
                Adapter(
                    name=name,
                    extensions=(f".{name}",),
                    parser=lambda text, fmt=name: parse_records(text, fmt)["records"],
                )
            )
        self.register(Adapter("xml", (".xml",), self._parse_xml))
        self.register(Adapter("ini", (".ini", ".cfg"), self._parse_ini))

    @staticmethod
    def _parse_xml(text: str) -> list[dict[str, Any]]:
        if "<!DOCTYPE" in text.upper() or "<!ENTITY" in text.upper():
            raise ValueError("XML 不允许声明外部实体")
        root = ET.fromstring(text)
        if sum(1 for _ in root.iter()) > 100_000:
            raise ValueError("XML 节点数超过上限")
        nodes = list(root)
        if not nodes:
            return [{root.tag: root.text or ""}]
        return [
            {child.tag: child.text or "" for child in node}
            if list(node)
            else {"tag": node.tag, "value": node.text or ""}
            for node in nodes
        ]

    @staticmethod
    def _parse_ini(text: str) -> list[dict[str, Any]]:
        parser = configparser.ConfigParser()
        parser.read_string(text)
        records = [
            {"section": section, **dict(parser[section])}
            for section in parser.sections()
        ]
        if not records:
            raise ValueError("INI 不包含有效配置节")
        return records


def benchmark() -> dict[str, Any]:
    registry = NormalizationRegistry()
    fixtures = {
        "csv": ("id,value\n1,42", {"id": "1", "value": "42"}),
        "tsv": ("id\tvalue\n1\t42", {"id": "1", "value": "42"}),
        "semicolon": ("id;value\n1;42", {"id": "1", "value": "42"}),
        "pipe": ("id|value\n1|42", {"id": "1", "value": "42"}),
        "json": ('[{"id":1,"value":42}]', {"id": 1, "value": 42}),
        "jsonl": ('{"id":1,"value":42}', {"id": 1, "value": 42}),
        "xml": (
            "<records><record><id>1</id><value>42</value></record></records>",
            {"id": "1", "value": "42"},
        ),
        "ini": ("[sensor]\nid=1\nvalue=42", {"section": "sensor", "id": "1", "value": "42"}),
    }
    invalid_fixtures = {
        "csv": "id,value\n1,2,3",
        "json": "[1,2,3]",
        "jsonl": "{}\n[]",
        "xml": "<!DOCTYPE x [<!ENTITY e SYSTEM 'file:///etc/passwd'>]><x>&e;</x>",
        "ini": "key=value",
    }
    passed_formats = []
    failures = {}
    for name, (text, expected) in fixtures.items():
        try:
            result = registry.normalize(text, name)
            if result["records"] == [expected]:
                passed_formats.append(name)
            else:
                failures[name] = "规范化结果与标注值不一致"
        except Exception as exc:  # Returned as test evidence.
            failures[name] = str(exc)
    rejected_invalid = 0
    for name, text in invalid_fixtures.items():
        try:
            registry.normalize(text, name)
        except (ValueError, configparser.Error, ET.ParseError):
            rejected_invalid += 1
    passed = len(passed_formats) == len(fixtures) and rejected_invalid == len(invalid_fixtures)
    return {
        "indicator": ID,
        "title": TITLE,
        "target": MILESTONE_TARGET,
        "passed": passed,
        "metrics": {
            "registered_adapters": len(registry.adapters),
            "tested_formats": len(fixtures),
            "passed_formats": passed_formats,
            "failed_formats": failures,
            "invalid_fixtures": len(invalid_fixtures),
            "rejected_invalid_fixtures": rejected_invalid,
        },
        "method": "适配器注册表将异构输入统一为 records+columns 中间表示，并按标注值校验结果及拒绝异常输入。",
    }
