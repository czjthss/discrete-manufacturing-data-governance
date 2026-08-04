"""Indicator 3.1: storage and compression for sequence and relational data."""

from __future__ import annotations

import gzip
import json
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any

from .common import (
    STORAGE_DIR,
    atomic_write_bytes,
    ensure_directories,
    json_bytes,
    new_run_id,
    path_lock,
    synthetic_relations,
    synthetic_sequence,
)


ID = "3.1"
TITLE = "序列、关系数据存储与压缩"
MILESTONE_TARGET = "支持序列数据和关系数据的存储与压缩"


class SequenceRelationStore:
    def __init__(self, root: Path | None = None) -> None:
        ensure_directories()
        self.root = root or STORAGE_DIR
        self.root.mkdir(parents=True, exist_ok=True)
        self.database_path = self.root / "relations.sqlite3"

    @staticmethod
    def _safe_component(value: str, fallback: str) -> str:
        safe = "".join(ch for ch in str(value) if ch.isalnum() or ch in {"-", "_"})
        return safe or fallback

    @staticmethod
    def _quote_identifier(value: str) -> str:
        return f'"{value.replace(chr(34), chr(34) * 2)}"'

    def store_sequence(self, name: str, records: list[dict[str, Any]]) -> dict[str, Any]:
        raw = json_bytes(records)
        safe_name = self._safe_component(name, "sequence")
        target = self.root / f"{safe_name}.sequence.json.gz"
        atomic_write_bytes(target, gzip.compress(raw, compresslevel=9, mtime=0))
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
        safe_name = self._safe_component(name, "sequence")
        target = self.root / f"{safe_name}.sequence.json.gz"
        with gzip.open(target, "rt", encoding="utf-8") as stream:
            payload = json.load(stream)
        if not isinstance(payload, list) or not all(
            isinstance(row, dict) for row in payload
        ):
            raise ValueError("序列存储内容必须是对象数组")
        return payload

    def store_relations(self, table: str, records: list[dict[str, Any]]) -> dict[str, Any]:
        safe_table = self._safe_component(table, "records")
        if not all(isinstance(row, dict) for row in records):
            raise ValueError("关系数据必须是对象数组")
        if any(not isinstance(key, str) for row in records for key in row):
            raise ValueError("关系数据字段名必须是字符串")
        columns = sorted({key for row in records for key in row})
        if any("\x00" in column for column in columns):
            raise ValueError("关系数据字段名不能包含空字符")
        folded_columns = [column.casefold() for column in columns]
        if len(folded_columns) != len(set(folded_columns)):
            raise ValueError("关系数据字段名不能仅以大小写区分")
        storage_columns = columns or ["_empty"]
        quoted_table = self._quote_identifier(safe_table)
        with path_lock(self.database_path):
            with closing(
                sqlite3.connect(self.database_path, timeout=30.0)
            ) as connection:
                connection.execute("PRAGMA busy_timeout=30000")
                connection.execute("BEGIN IMMEDIATE")
                connection.execute(f"DROP TABLE IF EXISTS {quoted_table}")
                schema = ", ".join(
                    f"{self._quote_identifier(column)} TEXT"
                    for column in storage_columns
                )
                connection.execute(f"CREATE TABLE {quoted_table} ({schema})")
                if records:
                    placeholders = ", ".join("?" for _ in columns)
                    quoted_columns = ", ".join(
                        self._quote_identifier(column) for column in columns
                    )
                    connection.executemany(
                        f"INSERT INTO {quoted_table} ({quoted_columns}) "
                        f"VALUES ({placeholders})",
                        (
                            [str(row.get(column, "")) for column in columns]
                            for row in records
                        ),
                    )
                connection.commit()
            compressed = self.root / "relations.sqlite3.gz"
            atomic_write_bytes(
                compressed,
                gzip.compress(self.database_path.read_bytes(), compresslevel=9, mtime=0),
            )
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

    def read_relations(self, table: str) -> list[dict[str, str]]:
        safe_table = self._safe_component(table, "records")
        quoted_table = self._quote_identifier(safe_table)
        with path_lock(self.database_path), closing(
            sqlite3.connect(self.database_path, timeout=30.0)
        ) as connection:
            cursor = connection.execute(f"SELECT * FROM {quoted_table}")
            columns = [item[0] for item in cursor.description or ()]
            return [dict(zip(columns, row)) for row in cursor.fetchall()]


def benchmark() -> dict[str, Any]:
    run_id = new_run_id("storage")
    store = SequenceRelationStore(STORAGE_DIR / "runs" / run_id)
    sequence = synthetic_sequence(2000)
    relations = synthetic_relations()
    sequence_result = store.store_sequence("benchmark", sequence)
    relation_result = store.store_relations("work_orders", relations)
    round_trip_ok = store.read_sequence("benchmark") == sequence
    relation_rows = store.read_relations("work_orders")
    relation_round_trip_ok = relation_rows == [
        {key: str(value) for key, value in row.items()} for row in relations
    ]
    backup_round_trip_ok = gzip.decompress(
        Path(relation_result["compressed_backup"]).read_bytes()
    ) == store.database_path.read_bytes()
    passed = round_trip_ok and relation_round_trip_ok and backup_round_trip_ok
    return {
        "indicator": ID,
        "title": TITLE,
        "target": MILESTONE_TARGET,
        "passed": passed,
        "metrics": {
            "sequence_records": len(sequence),
            "relation_records": len(relations),
            "sequence_round_trip": round_trip_ok,
            "relation_round_trip": relation_round_trip_ok,
            "relation_backup_round_trip": backup_round_trip_ok,
            "sequence_gzip_ratio": sequence_result["compression_ratio"],
        },
        "run_id": run_id,
        "artifacts": [
            sequence_result["path"],
            relation_result["path"],
            relation_result["compressed_backup"],
        ],
        "method": "序列数据采用 JSON+Gzip 持久化；关系数据采用 SQLite，并生成压缩备份。",
    }
