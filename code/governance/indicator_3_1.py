"""Indicator 3.1: storage and compression for sequence and relational data."""

from __future__ import annotations

import gzip
import hashlib
import json
import sqlite3
import zipfile
from contextlib import closing
from pathlib import Path
from typing import Any, Iterable

from .common import (
    ROOT,
    STORAGE_DIR,
    artifact_write_scope,
    atomic_write_bytes,
    atomic_write_text,
    ensure_directories,
    json_bytes,
    new_run_id,
    now_iso,
    path_lock,
    prune_retained_artifacts,
    retention_grace_seconds,
    retention_limit,
)
from .public_benchmarks import (
    benchmark_file,
    benchmark_manifest,
    benchmark_provenance,
    load_holoclean_hospital,
    load_secom_records,
    metropt_full_archive,
)


ID = "3.1"
TITLE = "序列、关系数据存储与压缩"
MILESTONE_TARGET = "支持序列数据和关系数据的存储与压缩"
STORAGE_RUN_COMPLETED_MARKER = ".completed"


def _report_path(path: str | Path) -> str:
    resolved = Path(path).resolve()
    try:
        return resolved.relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        return resolved.name


def mark_storage_run_completed(run_directory: Path) -> Path:
    marker = run_directory / STORAGE_RUN_COMPLETED_MARKER
    atomic_write_text(marker, now_iso())
    return marker


def prune_storage_runs(root: Path, protected: tuple[Path, ...] = ()) -> list[Path]:
    return prune_retained_artifacts(
        root,
        limit=retention_limit("storage_runs"),
        directories=True,
        protected=protected,
        minimum_age_seconds=retention_grace_seconds(),
        completion_marker=STORAGE_RUN_COMPLETED_MARKER,
    )


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
        with artifact_write_scope(target):
            atomic_write_bytes(target, gzip.compress(raw, compresslevel=9, mtime=0))
            if safe_name.startswith("analysis-"):
                prune_retained_artifacts(
                    self.root,
                    limit=retention_limit("analysis_sequences"),
                    pattern="analysis-*.sequence.json.gz",
                    protected=(target,),
                    minimum_age_seconds=retention_grace_seconds(),
                )
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
            "raw_bytes": self.database_path.stat().st_size,
            "stored_bytes": compressed.stat().st_size,
            "compression_ratio": round(
                self.database_path.stat().st_size / max(compressed.stat().st_size, 1),
                2,
            ),
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


def _store_streamed_sequence(
    target: Path, chunks: Any, *, records: int
) -> dict[str, Any]:
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.tmp")
    raw_digest = hashlib.sha256()
    raw_bytes = 0
    try:
        with temporary.open("wb") as output, gzip.GzipFile(
            filename="", mode="wb", fileobj=output, compresslevel=9, mtime=0
        ) as compressed:
            for chunk in chunks:
                raw_digest.update(chunk)
                raw_bytes += len(chunk)
                compressed.write(chunk)
        temporary.replace(target)
    finally:
        if temporary.exists():
            temporary.unlink()
    restored_digest = hashlib.sha256()
    restored_bytes = 0
    with gzip.open(target, "rb") as restored:
        while chunk := restored.read(1024 * 1024):
            restored_digest.update(chunk)
            restored_bytes += len(chunk)
    stored_bytes = target.stat().st_size
    return {
        "data_type": "sequence",
        "records": records,
        "round_trip": restored_bytes == raw_bytes
        and restored_digest.digest() == raw_digest.digest(),
        "backup_round_trip": None,
        "raw_bytes": raw_bytes,
        "stored_bytes": stored_bytes,
        "compression_ratio": round(raw_bytes / max(stored_bytes, 1), 2),
        "path": _report_path(target),
    }


def _iter_file_chunks(paths: list[Path]) -> Iterable[bytes]:
    for path in paths:
        with path.open("rb") as source:
            while chunk := source.read(1024 * 1024):
                yield chunk


def benchmark() -> dict[str, Any]:
    run_id = new_run_id("storage")
    run_root = STORAGE_DIR / "runs" / run_id
    secom_relations = list(load_secom_records())
    hospital_relations, _ = load_holoclean_hospital()
    dataset_results: dict[str, dict[str, Any]] = {}
    artifacts: list[str] = []
    with artifact_write_scope(run_root):
        manifest = benchmark_manifest()["datasets"]
        metro_spec = manifest["metropt3"]["full_archive"]
        with zipfile.ZipFile(metropt_full_archive()) as bundle, bundle.open(
            metro_spec["member"]
        ) as source:
            dataset_results["metropt3"] = _store_streamed_sequence(
                run_root / "metropt3" / "metropt3.sequence.csv.gz",
                iter(lambda: source.read(1024 * 1024), b""),
                records=int(metro_spec["records"]),
            )
        forda_paths = [
            benchmark_file("forda", "FordA_TRAIN.ts"),
            benchmark_file("forda", "FordA_TEST.ts"),
        ]
        dataset_results["forda"] = _store_streamed_sequence(
            run_root / "forda" / "forda.sequence.ts.gz",
            _iter_file_chunks(forda_paths),
            records=int(manifest["forda"]["series"]),
        )
        artifacts.extend(
            [dataset_results["metropt3"]["path"], dataset_results["forda"]["path"]]
        )
        for dataset_id, records in (
            ("secom", secom_relations),
            ("holoclean_hospital", hospital_relations),
        ):
            store = SequenceRelationStore(run_root / dataset_id)
            storage = store.store_relations("records", records)
            round_trip = store.read_relations("records") == [
                {key: str(value) for key, value in row.items()} for row in records
            ]
            backup_round_trip = gzip.decompress(
                Path(storage["compressed_backup"]).read_bytes()
            ) == store.database_path.read_bytes()
            artifacts.extend(
                [
                    _report_path(storage["path"]),
                    _report_path(storage["compressed_backup"]),
                ]
            )
            dataset_results[dataset_id] = {
                "data_type": "relation",
                "records": len(records),
                "round_trip": round_trip,
                "backup_round_trip": backup_round_trip,
                "raw_bytes": storage["raw_bytes"],
                "stored_bytes": storage["stored_bytes"],
                "compression_ratio": storage["compression_ratio"],
            }
        mark_storage_run_completed(run_root)
    prune_storage_runs(run_root.parent, protected=(run_root,))
    passed = all(
        result["round_trip"]
        and result["compression_ratio"] > 1.0
        and result["backup_round_trip"] is not False
        for result in dataset_results.values()
    )
    return {
        "indicator": ID,
        "title": TITLE,
        "target": MILESTONE_TARGET,
        "passed": passed,
        "metrics": {
            "sequence_records": dataset_results["metropt3"]["records"]
            + dataset_results["forda"]["records"],
            "relation_records": len(secom_relations),
            "sequence_round_trip": dataset_results["metropt3"]["round_trip"],
            "relation_round_trip": dataset_results["secom"]["round_trip"],
            "relation_backup_round_trip": dataset_results["secom"]["backup_round_trip"],
            "sequence_gzip_ratio": dataset_results["metropt3"]["compression_ratio"],
            "dataset_results": dataset_results,
        },
        "run_id": run_id,
        "artifacts": artifacts,
        "benchmark_provenance": benchmark_provenance(
            ("metropt3", "forda", "secom", "holoclean_hospital")
        ),
        "method": "对 MetroPT-3 官方完整归档全部 1,516,948 行CSV和UCR FordA TRAIN+TEST全部4,921条序列执行流式Gzip无损存储、SHA-256往返校验；对SECOM全部1,567条与HoloClean Hospital全部1,000条关系记录执行独立SQLite存储、逐行回读及压缩备份校验，并按数据集报告原始文件或数据库字节口径压缩比。",
    }
