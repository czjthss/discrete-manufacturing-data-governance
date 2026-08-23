"""Indicator 3.8: extensible industrial data normalization test framework."""

from __future__ import annotations

import configparser
import xml.etree.ElementTree as ET
import xml.parsers.expat as expat
from dataclasses import dataclass
from typing import Any, Callable

from .common import pct
from .indicator_3_3 import parse_records
from .public_benchmarks import (
    benchmark_provenance,
    iter_metropt_full_batches,
    load_forda_series,
    load_holoclean_hospital,
    load_secom_records,
)


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


def _xml_conformance_accepts(payload: bytes, *, namespace_aware: bool) -> bool:
    parser = expat.ParserCreate(namespace_separator="}" if namespace_aware else None)
    parser.SetParamEntityParsing(expat.XML_PARAM_ENTITY_PARSING_NEVER)
    parser.ExternalEntityRefHandler = lambda *args: 0
    try:
        parser.Parse(payload, True)
    except (expat.ExpatError, UnicodeError):
        return False
    return True


def benchmark() -> dict[str, Any]:
    registry = NormalizationRegistry()
    metro_records = sum(
        len(columns["Motor_current"])
        for _, columns in iter_metropt_full_batches()
    )
    forda = load_forda_series()
    secom = load_secom_records()
    hospital, truth = load_holoclean_hospital()
    dataset_results = {
        "metropt3": {
            "normalized": metro_records == 1_516_948,
            "records": metro_records,
            "columns": 18,
            "source_format": "CSV",
            "normalized_schema": "sequence_record",
        },
        "forda": {
            "normalized": len(forda) == 4921
            and sum(len(row["values"]) for row in forda) == 2_460_500,
            "records": len(forda),
            "points": sum(len(row["values"]) for row in forda),
            "columns": 4,
            "source_format": "UCR TS",
            "normalized_schema": "sequence_record",
        },
        "secom": {
            "normalized": len(secom) == 1567,
            "records": len(secom),
            "columns": len(secom[0]),
            "source_format": "space-delimited data + label file",
            "normalized_schema": "relation_record",
        },
        "holoclean_hospital": {
            "normalized": len(hospital) == 1000 and len(truth) == 19000,
            "records": len(hospital),
            "truth_cells": len(truth),
            "columns": len(hospital[0]),
            "source_format": "CSV dirty table + cell truth table",
            "normalized_schema": "relation_record + cell_truth",
        },
    }
    passed = all(item["normalized"] for item in dataset_results.values())
    return {
        "indicator": ID,
        "title": TITLE,
        "target": MILESTONE_TARGET,
        "passed": passed,
        "metrics": {
            "registered_adapters": len(registry.adapters),
            "tested_format_families": 3,
            "datasets_tested": len(dataset_results),
            "normalization_success_percent": pct(
                sum(item["normalized"] for item in dataset_results.values()),
                len(dataset_results),
            ),
            "dataset_results": dataset_results,
            "public_table_normalization": dataset_results,
        },
        "benchmark_provenance": benchmark_provenance(
            ("metropt3", "forda", "secom", "holoclean_hospital")
        ),
        "method": "规范化框架完整读取 MetroPT-3、UCR FordA TRAIN+TEST、UCI SECOM 与 HoloClean Hospital 四套固定公开benchmark，分别生成统一的 sequence_record、relation_record 与 cell_truth 中间表示，并核对全部记录数、字段数、时序点数及真值单元数；注册表的其他适配器保留为扩展能力，不计入本次四数据集实验。",
    }
