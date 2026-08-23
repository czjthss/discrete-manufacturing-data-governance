"""Load and verify the pinned public datasets used by indicator benchmarks."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import os
import zipfile
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable


BENCHMARK_ROOT = Path(__file__).with_name("benchmark_data") / "public"
MANIFEST_PATH = BENCHMARK_ROOT / "benchmark_manifest.json"
METRO_ANALOG_CHANNELS = (
    "TP2",
    "TP3",
    "H1",
    "DV_pressure",
    "Reservoirs",
    "Oil_temperature",
    "Motor_current",
)
METRO_DIGITAL_CHANNELS = (
    "COMP",
    "DV_eletric",
    "Towers",
    "MPG",
    "LPS",
    "Pressure_switch",
    "Oil_level",
    "Caudal_impulses",
)
METRO_SENSOR_CHANNELS = METRO_ANALOG_CHANNELS + METRO_DIGITAL_CHANNELS
DEFAULT_FULL_BENCHMARK_ROOT = Path(__file__).resolve().parents[1] / "data" / "benchmark_cache"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


@lru_cache(maxsize=1)
def benchmark_manifest() -> dict[str, Any]:
    payload = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    if payload.get("schema_version") != 1:
        raise ValueError("公开基准清单版本不受支持")
    return payload


@lru_cache(maxsize=None)
def benchmark_file(dataset_id: str, filename: str) -> Path:
    dataset = benchmark_manifest()["datasets"].get(dataset_id)
    if not dataset:
        raise KeyError(f"公开基准不存在: {dataset_id}")
    entry = next(
        (item for item in dataset["files"] if Path(item["path"]).name == filename),
        None,
    )
    if entry is None:
        raise KeyError(f"公开基准文件未登记: {dataset_id}/{filename}")
    path = (BENCHMARK_ROOT / entry["path"]).resolve()
    try:
        path.relative_to(BENCHMARK_ROOT.resolve())
    except ValueError as exc:
        raise ValueError("公开基准文件路径超出数据目录") from exc
    if not path.is_file():
        raise FileNotFoundError(f"公开基准文件缺失: {path}")
    if path.stat().st_size != entry["bytes"] or _sha256(path) != entry["sha256"]:
        raise ValueError(f"公开基准文件完整性校验失败: {path.name}")
    return path


def benchmark_provenance(dataset_ids: Iterable[str]) -> list[dict[str, Any]]:
    manifest = benchmark_manifest()["datasets"]
    result = []
    for dataset_id in dataset_ids:
        dataset = manifest[dataset_id]
        result.append(
            {
                "dataset_id": dataset_id,
                "title": dataset["title"],
                "publisher": dataset.get("publisher"),
                "doi": dataset.get("doi"),
                "repository": dataset.get("repository"),
                "commit": dataset.get("commit"),
                "license": dataset.get("license"),
                "full_archive": dataset.get("full_archive"),
                "files": [
                    {
                        "path": item["path"],
                        "sha256": item["sha256"],
                        "records": item.get("records"),
                    }
                    for item in dataset["files"]
                ],
            }
        )
    return result


def metropt_full_archive() -> Path:
    dataset = benchmark_manifest()["datasets"]["metropt3"]
    specification = dataset["full_archive"]
    configured = os.environ.get("METROPT3_ARCHIVE")
    path = (
        Path(configured).expanduser()
        if configured
        else DEFAULT_FULL_BENCHMARK_ROOT / specification["cache_name"]
    )
    if not path.is_file():
        raise FileNotFoundError(
            "MetroPT-3 完整归档缺失；先运行 python3 tools/fetch_full_benchmarks.py"
        )
    if _sha256(path) != specification["sha256"]:
        raise ValueError("MetroPT-3 完整归档 SHA-256 校验失败")
    return path


def iter_metropt_full_batches(
    batch_size: int = 65_536,
) -> Iterable[tuple[int, dict[str, list[float]]]]:
    if not isinstance(batch_size, int) or isinstance(batch_size, bool) or batch_size <= 0:
        raise ValueError("批大小必须为正整数")
    specification = benchmark_manifest()["datasets"]["metropt3"]["full_archive"]
    expected_records = int(specification["records"])
    archive = metropt_full_archive()
    total = 0
    with zipfile.ZipFile(archive) as bundle:
        member = specification["member"]
        if member not in bundle.namelist():
            raise ValueError("MetroPT-3 完整归档缺少登记的数据文件")
        with bundle.open(member) as raw:
            stream = io.TextIOWrapper(raw, encoding="utf-8", newline="")
            reader = csv.DictReader(stream)
            if reader.fieldnames is None or any(
                channel not in reader.fieldnames for channel in METRO_SENSOR_CHANNELS
            ):
                raise ValueError("MetroPT-3 完整数据缺少登记的传感器通道")
            batch = {
                "timestamp_ms": [],
                **{channel: [] for channel in METRO_SENSOR_CHANNELS},
            }
            batch_start = 0
            for row_index, row in enumerate(reader):
                timestamp_ms = iso_timestamp_ms(row["timestamp"])
                if timestamp_ms <= 0:
                    raise ValueError(
                        f"MetroPT-3 第 {row_index} 行时间戳无效"
                    )
                batch["timestamp_ms"].append(float(timestamp_ms))
                for channel in METRO_ANALOG_CHANNELS:
                    value = float(row[channel])
                    if not math.isfinite(value):
                        raise ValueError(
                            f"MetroPT-3 第 {row_index} 行 {channel} 不是有限数值"
                        )
                    batch[channel].append(value)
                for channel in METRO_DIGITAL_CHANNELS:
                    value = float(row[channel])
                    if value not in (0.0, 1.0):
                        raise ValueError(
                            f"MetroPT-3 第 {row_index} 行 {channel} 不是二值数据"
                        )
                    batch[channel].append(value)
                total += 1
                if len(batch[METRO_ANALOG_CHANNELS[0]]) == batch_size:
                    yield batch_start, batch
                    batch_start = total
                    batch = {
                        "timestamp_ms": [],
                        **{channel: [] for channel in METRO_SENSOR_CHANNELS},
                    }
            if batch[METRO_ANALOG_CHANNELS[0]]:
                yield batch_start, batch
    if total != expected_records:
        raise ValueError(
            f"MetroPT-3 完整数据应为 {expected_records} 行，实际为 {total} 行"
        )


def iter_metropt_full_sequence_batches(
    batch_size: int = 65_536,
) -> Iterable[list[dict[str, Any]]]:
    """Yield the complete MetroPT-3 archive as bounded sequence-record batches."""
    for start_row, columns in iter_metropt_full_batches(batch_size=batch_size):
        yield [
            {
                "source_row": start_row + offset,
                "timestamp_ms": int(columns["timestamp_ms"][offset]),
                "equipment_id": "MetroPT3-APU",
                "value": columns["Motor_current"][offset],
            }
            for offset in range(len(columns["Motor_current"]))
        ]


def iso_timestamp_ms(value: str) -> int:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return round(parsed.timestamp() * 1000)


@lru_cache(maxsize=1)
def load_metropt_rows() -> tuple[dict[str, Any], ...]:
    path = benchmark_file("metropt3", "metropt3_benchmark.csv")
    rows = []
    with path.open(newline="", encoding="utf-8") as stream:
        for raw in csv.DictReader(stream):
            row: dict[str, Any] = {
                **raw,
                "source_row": int(raw["source_row"]),
                "timestamp_ms": iso_timestamp_ms(raw["timestamp"]),
                "equipment_id": "MetroPT3-APU",
            }
            for channel in METRO_ANALOG_CHANNELS:
                row[channel] = float(raw[channel])
            rows.append(row)
    expected = next(
        item["records"]
        for item in benchmark_manifest()["datasets"]["metropt3"]["files"]
        if Path(item["path"]).name == path.name
    )
    if len(rows) != expected:
        raise ValueError("MetroPT-3 基准记录数与清单不一致")
    return tuple(rows)


def metropt_compression_blocks() -> dict[str, dict[str, list[float]]]:
    blocks: dict[str, dict[str, list[float]]] = {}
    for row in load_metropt_rows():
        roles = str(row["selection_role"]).split("+")
        compression_role = next((role for role in roles if role.startswith("compression_")), None)
        if compression_role is None:
            continue
        channels = blocks.setdefault(
            compression_role,
            {channel: [] for channel in METRO_ANALOG_CHANNELS},
        )
        for channel in METRO_ANALOG_CHANNELS:
            channels[channel].append(float(row[channel]))
    if len(blocks) != 5 or any(
        len(values) != 12_000 for block in blocks.values() for values in block.values()
    ):
        raise ValueError("MetroPT-3 压缩窗口不完整")
    return dict(sorted(blocks.items()))


def metropt_alignment_sequence() -> list[dict[str, Any]]:
    sequence = []
    for row in load_metropt_rows():
        if "alignment" not in str(row["selection_role"]).split("+"):
            continue
        sequence.append(
            {
                "equipment_id": row["equipment_id"],
                "timestamp_ms": row["timestamp_ms"],
                "value": row["Motor_current"],
                "source_row": row["source_row"],
            }
        )
    expected = benchmark_manifest()["datasets"]["metropt3"]["selection"][
        "alignment_records"
    ]
    if len(sequence) != expected or len(
        {row["timestamp_ms"] // 60_000 for row in sequence}
    ) != expected:
        raise ValueError("MetroPT-3 对齐子集不是预先声明的唯一分钟记录")
    return sequence


@lru_cache(maxsize=1)
def load_metropt_failures() -> tuple[dict[str, Any], ...]:
    path = benchmark_file("metropt3", "metropt3_failures.csv")
    records = []
    with path.open(newline="", encoding="utf-8") as stream:
        for row in csv.DictReader(stream):
            records.append(
                {
                    **row,
                    "work_order": row["failure_id"],
                    "start_ms": iso_timestamp_ms(row["start_time"]),
                    "end_ms": iso_timestamp_ms(row["end_time"]),
                }
            )
    return tuple(records)


@lru_cache(maxsize=1)
def load_secom_records() -> tuple[dict[str, Any], ...]:
    data_path = benchmark_file("secom", "secom.data")
    label_path = benchmark_file("secom", "secom_labels.data")
    data_lines = data_path.read_text(encoding="utf-8").splitlines()
    label_lines = label_path.read_text(encoding="utf-8").splitlines()
    if len(data_lines) != 1567 or len(label_lines) != len(data_lines):
        raise ValueError("SECOM 数据文件与标签文件记录数不一致")
    records = []
    for row_id, (data_line, label_line) in enumerate(zip(data_lines, label_lines)):
        values = data_line.split()
        if len(values) != 590:
            raise ValueError(f"SECOM 第 {row_id} 行字段数不是 590")
        label, quoted_timestamp = label_line.split(maxsplit=1)
        timestamp = quoted_timestamp.strip('"')
        record: dict[str, Any] = {
            "wafer_id": row_id,
            "label": int(label),
            "timestamp": timestamp,
            "timestamp_ms": round(
                datetime.strptime(timestamp, "%d/%m/%Y %H:%M:%S")
                .replace(tzinfo=timezone.utc)
                .timestamp()
                * 1000
            ),
        }
        for column, value in enumerate(values):
            record[f"sensor_{column:03d}"] = None if value == "NaN" else float(value)
        records.append(record)
    return tuple(records)


@lru_cache(maxsize=1)
def load_ims_records() -> tuple[dict[str, Any], ...]:
    path = benchmark_file("ims_bearings", "ims_2004.02.12.10.32.39.tsv")
    records = []
    with path.open(encoding="ascii") as stream:
        for index, line in enumerate(stream):
            values = [float(value) for value in line.split()]
            if len(values) != 4 or not all(math.isfinite(value) for value in values):
                raise ValueError(f"IMS 第 {index} 行不是 4 通道有限数值")
            records.append(
                {
                    "sample_index": index,
                    "timestamp_ns": index * 50_000,
                    "equipment_id": "IMS-BEARING-SET-2",
                    "bearing_1": values[0],
                    "bearing_2": values[1],
                    "bearing_3": values[2],
                    "bearing_4": values[3],
                }
            )
    if len(records) != 20_480:
        raise ValueError("IMS 基准文件必须包含 20,480 个原始样本")
    return tuple(records)


@lru_cache(maxsize=1)
def load_forda_series() -> tuple[dict[str, Any], ...]:
    records = []
    expected_by_split = {"TRAIN": 3601, "TEST": 1320}
    for split, expected_records in expected_by_split.items():
        path = benchmark_file("forda", f"FordA_{split}.ts")
        split_records = 0
        in_data = False
        with path.open(encoding="utf-8") as stream:
            for line_number, raw_line in enumerate(stream, start=1):
                line = raw_line.strip()
                if not line or line.startswith("#"):
                    continue
                if line.lower() == "@data":
                    in_data = True
                    continue
                if not in_data:
                    continue
                values_text, separator, label_text = line.rpartition(":")
                if not separator:
                    raise ValueError(f"FordA {split} 第 {line_number} 行缺少类别标签")
                values = tuple(float(value) for value in values_text.split(","))
                if len(values) != 500 or not all(math.isfinite(value) for value in values):
                    raise ValueError(
                        f"FordA {split} 第 {line_number} 行序列长度或数值无效"
                    )
                label = int(label_text)
                if label not in {-1, 1}:
                    raise ValueError(f"FordA {split} 第 {line_number} 行类别标签无效")
                records.append(
                    {
                        "series_id": len(records),
                        "source_split": split,
                        "source_row": split_records,
                        "equipment_id": f"FordA-{len(records) + 1:04d}",
                        "label": label,
                        "values": values,
                    }
                )
                split_records += 1
        if split_records != expected_records:
            raise ValueError(
                f"FordA {split} 应包含 {expected_records:,} 条完整序列，实际为 {split_records:,}"
            )
    if len(records) != 4921:
        raise ValueError("FordA TRAIN+TEST 必须包含 4,921 条完整序列")
    return tuple(records)


def load_holoclean_hospital() -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    dirty_path = benchmark_file("holoclean_hospital", "hospital.csv")
    clean_path = benchmark_file("holoclean_hospital", "hospital_clean.csv")
    with dirty_path.open(newline="", encoding="utf-8") as stream:
        dirty = list(csv.DictReader(stream))
    with clean_path.open(newline="", encoding="utf-8") as stream:
        clean = list(csv.DictReader(stream))
    if len(dirty) != 1000 or len(clean) != 19000:
        raise ValueError("HoloClean Hospital 基准记录数与固定版本不一致")
    return dirty, clean


def iter_json_conformance_cases() -> Iterable[tuple[str, bytes, bool]]:
    path = benchmark_file("json_test_suite", "json_test_suite.zip")
    with zipfile.ZipFile(path) as bundle:
        for name in sorted(bundle.namelist()):
            filename = Path(name).name
            if not filename.endswith(".json") or not filename.startswith(("y_", "n_")):
                continue
            yield filename, bundle.read(name), filename.startswith("y_")


def load_xml_conformance_suite() -> tuple[bytes, dict[str, bytes]]:
    path = benchmark_file("w3c_xml_conformance", "w3c_xmlconf_xmltest.zip")
    with zipfile.ZipFile(path) as bundle:
        files = {name: bundle.read(name) for name in bundle.namelist()}
    catalog_name = "xmlconf/xmltest/xmltest.xml"
    if catalog_name not in files:
        raise ValueError("W3C XML 测试目录缺少 xmltest.xml")
    return files[catalog_name], files
