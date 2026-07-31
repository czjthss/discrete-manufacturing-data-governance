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
        root = ET.fromstring(text)
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
        return [{"section": section, **dict(parser[section])} for section in parser.sections()]


def benchmark() -> dict[str, Any]:
    registry = NormalizationRegistry()
    fixtures = {
        "csv": "id,value\n1,42",
        "tsv": "id\tvalue\n1\t42",
        "semicolon": "id;value\n1;42",
        "pipe": "id|value\n1|42",
        "json": '[{"id":1,"value":42}]',
        "jsonl": '{"id":1,"value":42}',
        "xml": "<records><record><id>1</id><value>42</value></record></records>",
        "ini": "[sensor]\nid=1\nvalue=42",
    }
    passed_formats = []
    failures = {}
    for name, text in fixtures.items():
        try:
            result = registry.normalize(text, name)
            if result["records"]:
                passed_formats.append(name)
        except Exception as exc:  # Returned as test evidence.
            failures[name] = str(exc)
    passed = len(passed_formats) == len(fixtures)
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
        },
        "method": "适配器注册表将异构输入统一为 records+columns 中间表示，可继续挂载论文代码或协议解析器。",
    }
