"""Indicator 3.1: storage and compression for sequence and relational data."""

from __future__ import annotations

import gzip
import json
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any

from .common import STORAGE_DIR, ensure_directories, json_bytes, synthetic_relations, synthetic_sequence


ID = "3.1"
TITLE = "序列、关系数据存储与压缩"
MILESTONE_TARGET = "支持序列数据和关系数据的存储与压缩"


class SequenceRelationStore:
    def __init__(self, root: Path | None = None) -> None:
        ensure_directories()
        self.root = root or STORAGE_DIR
        self.root.mkdir(parents=True, exist_ok=True)
        self.database_path = self.root / "relations.sqlite3"

    def store_sequence(self, name: str, records: list[dict[str, Any]]) -> dict[str, Any]:
        raw = json_bytes(records)
        target = self.root / f"{name}.sequence.json.gz"
        with gzip.open(target, "wb", compresslevel=9) as stream:
            stream.write(raw)
        stored_bytes = target.stat().st_size
        return {
            "kind": "sequence",
            "path": str(target),
            "records": len(records),
            "raw_bytes": len(raw),
            "stored_bytes": stored_bytes,
            "compression_ratio": round(len(raw) / max(stored_bytes, 1), 2),
        }

    def read_sequence(self, name: str) -> list[dict[str, Any]]:
        target = self.root / f"{name}.sequence.json.gz"
        with gzip.open(target, "rt", encoding="utf-8") as stream:
            return json.load(stream)

    def store_relations(self, table: str, records: list[dict[str, Any]]) -> dict[str, Any]:
        safe_table = "".join(ch for ch in table if ch.isalnum() or ch == "_") or "records"
        columns = sorted({key for row in records for key in row})
        storage_columns = columns or ["_empty"]
        with closing(sqlite3.connect(self.database_path)) as connection:
            connection.execute(f'DROP TABLE IF EXISTS "{safe_table}"')
            schema = ", ".join(f'"{column}" TEXT' for column in storage_columns)
            connection.execute(f'CREATE TABLE "{safe_table}" ({schema})')
            if records:
                placeholders = ", ".join("?" for _ in columns)
                quoted_columns = ", ".join(f'"{column}"' for column in columns)
                connection.executemany(
                    f'INSERT INTO "{safe_table}" ({quoted_columns}) VALUES ({placeholders})',
                    ([str(row.get(column, "")) for column in columns] for row in records),
                )
            connection.commit()
        compressed = self.root / "relations.sqlite3.gz"
        with self.database_path.open("rb") as source, gzip.open(compressed, "wb", 9) as target:
            target.write(source.read())
        return {
            "kind": "relation",
            "path": str(self.database_path),
            "compressed_backup": str(compressed),
            "table": safe_table,
            "records": len(records),
            "columns": columns,
            "storage_columns": storage_columns,
            "empty": not records,
        }


def benchmark() -> dict[str, Any]:
    store = SequenceRelationStore()
    sequence = synthetic_sequence(2000)
    relations = synthetic_relations()
    sequence_result = store.store_sequence("benchmark", sequence)
    relation_result = store.store_relations("work_orders", relations)
    round_trip_ok = store.read_sequence("benchmark") == sequence
    passed = round_trip_ok and relation_result["records"] == len(relations)
    return {
        "indicator": ID,
        "title": TITLE,
        "target": MILESTONE_TARGET,
        "passed": passed,
        "metrics": {
            "sequence_records": len(sequence),
            "relation_records": len(relations),
            "sequence_round_trip": round_trip_ok,
            "sequence_gzip_ratio": sequence_result["compression_ratio"],
        },
        "artifacts": [sequence_result["path"], relation_result["path"]],
        "method": "序列数据采用 JSON+Gzip 持久化；关系数据采用 SQLite，并生成压缩备份。",
    }
