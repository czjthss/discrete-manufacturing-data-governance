"""Prepare pinned public benchmark assets used by the acceptance tests."""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import shutil
import tarfile
import zipfile
from datetime import datetime, timedelta
from pathlib import Path
from typing import BinaryIO, Iterable


CODE_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_ROOT = CODE_ROOT / "governance" / "benchmark_data" / "public"
SOURCE_ROOT = OUTPUT_ROOT / "sources"

METRO_COMPRESSION_WINDOWS = (0, 300_000, 600_000, 900_000, 1_200_000)
METRO_WINDOW_ROWS = 12_000
METRO_EXPECTED_RECORDS = 63_823
METRO_ALIGNMENT_RECORDS = 5_167
METRO_FULL_ARCHIVE_URL = "https://archive.ics.uci.edu/static/public/791/metropt+3+dataset.zip"
METRO_FULL_ARCHIVE_SHA256 = "aab991a970e58210de853bb8078ce0e63abb4d9412fdc5c79792dae3d8e1721a"
METRO_FULL_RECORDS = 1_516_948
METRO_FULL_MEMBER = "MetroPT3(AirCompressor).csv"
METRO_FAILURES = (
    ("F1", "2020-04-18 00:00:00", "2020-04-18 23:59:00", "Air leak", "High stress"),
    ("F2", "2020-05-29 23:30:00", "2020-05-30 06:00:00", "Air leak", "High stress"),
    ("F3", "2020-06-05 10:00:00", "2020-06-07 14:30:00", "Air leak", "High stress"),
    ("F4", "2020-07-15 14:30:00", "2020-07-15 19:00:00", "Air leak", "High stress"),
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_if_changed(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.read_bytes() == payload:
        return
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_bytes(payload)
    temporary.replace(path)


def copy_if_changed(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() and sha256(source) == sha256(target):
        return
    temporary = target.with_name(f".{target.name}.tmp")
    shutil.copyfile(source, temporary)
    temporary.replace(target)


def prepare_forda(train_source: Path, test_source: Path) -> list[Path]:
    outputs = [OUTPUT_ROOT / "FordA_TRAIN.ts", OUTPUT_ROOT / "FordA_TEST.ts"]
    copy_if_changed(train_source, outputs[0])
    copy_if_changed(test_source, outputs[1])
    return outputs


def prepare_secom(archive: Path) -> list[Path]:
    outputs = []
    with zipfile.ZipFile(archive) as bundle:
        for name in ("secom.data", "secom_labels.data", "secom.names"):
            target = SOURCE_ROOT / name
            write_if_changed(target, bundle.read(name))
            outputs.append(target)
    return outputs


def _failure_windows() -> list[tuple[datetime, datetime]]:
    margin = timedelta(minutes=30)
    return [
        (
            datetime.fromisoformat(start) - margin,
            datetime.fromisoformat(end) + margin,
        )
        for _, start, end, _, _ in METRO_FAILURES
    ]


def prepare_metropt(archive: Path) -> list[Path]:
    output = SOURCE_ROOT / "metropt3_benchmark.csv"
    failures_output = SOURCE_ROOT / "metropt3_failures.csv"
    selected: dict[int, tuple[str, dict[str, str]]] = {}
    selected_alignment_minutes: set[datetime] = set()
    with zipfile.ZipFile(archive) as bundle:
        member = next(name for name in bundle.namelist() if name.endswith("AirCompressor).csv"))
        with bundle.open(member) as raw:
            text = io.TextIOWrapper(raw, encoding="utf-8", newline="")
            reader = csv.DictReader(text)
            if reader.fieldnames is None:
                raise ValueError("MetroPT-3 CSV 缺少表头")
            failure_windows = _failure_windows()
            for row_index, row in enumerate(reader):
                role = None
                for window_index, start in enumerate(METRO_COMPRESSION_WINDOWS):
                    if start <= row_index < start + METRO_WINDOW_ROWS:
                        role = f"compression_{window_index}"
                        break
                timestamp = datetime.fromisoformat(row["timestamp"])
                if any(start <= timestamp <= end for start, end in failure_windows):
                    minute = timestamp.replace(second=0, microsecond=0)
                    if minute not in selected_alignment_minutes:
                        selected_alignment_minutes.add(minute)
                        role = f"{role}+alignment" if role else "alignment"
                if role:
                    selected[row_index] = (role, row)

    alignment_records = sum(
        "alignment" in role.split("+") for role, _ in selected.values()
    )
    if len(selected) != METRO_EXPECTED_RECORDS:
        raise ValueError(
            f"MetroPT-3 固定子集应为 {METRO_EXPECTED_RECORDS} 条，实际为 {len(selected)} 条"
        )
    if alignment_records != METRO_ALIGNMENT_RECORDS:
        raise ValueError(
            f"MetroPT-3 对齐子集应为 {METRO_ALIGNMENT_RECORDS} 条，实际为 {alignment_records} 条"
        )

    source_fieldnames = [field for field in reader.fieldnames if field]
    fieldnames = ["source_row", "selection_role", *source_fieldnames]
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=fieldnames, lineterminator="\n")
    writer.writeheader()
    for row_index, (role, row) in sorted(selected.items()):
        writer.writerow(
            {
                "source_row": row_index,
                "selection_role": role,
                **{field: row[field] for field in source_fieldnames},
            }
        )
    write_if_changed(output, stream.getvalue().encode("utf-8"))

    failure_stream = io.StringIO(newline="")
    failure_fields = ("failure_id", "equipment_id", "start_time", "end_time", "failure", "severity")
    failure_writer = csv.DictWriter(
        failure_stream, fieldnames=failure_fields, lineterminator="\n"
    )
    failure_writer.writeheader()
    for failure_id, start, end, failure, severity in METRO_FAILURES:
        failure_writer.writerow(
            {
                "failure_id": failure_id,
                "equipment_id": "MetroPT3-APU",
                "start_time": start,
                "end_time": end,
                "failure": failure,
                "severity": severity,
            }
        )
    write_if_changed(failures_output, failure_stream.getvalue().encode("utf-8"))
    return [output, failures_output]


def _write_benchmark_zip(
    output: Path,
    members: Iterable[tuple[str, BinaryIO]],
) -> None:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as bundle:
        for name, source in members:
            info = zipfile.ZipInfo(name, date_time=(2020, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            bundle.writestr(info, source.read())
    write_if_changed(output, buffer.getvalue())


def prepare_json_suite(archive: Path) -> Path:
    output = SOURCE_ROOT / "json_test_suite.zip"
    with tarfile.open(archive, "r:gz") as bundle:
        candidates = [
            member
            for member in bundle.getmembers()
            if member.isfile()
            and ("/test_parsing/" in member.name or member.name.endswith("/LICENSE"))
        ]
        members = []
        for member in sorted(candidates, key=lambda item: item.name):
            source = bundle.extractfile(member)
            if source is None:
                continue
            relative = member.name.split("/", 1)[1]
            members.append((relative, source))
        _write_benchmark_zip(output, members)
    return output


def prepare_xml_suite(archive: Path) -> Path:
    output = SOURCE_ROOT / "w3c_xmlconf_xmltest.zip"
    with zipfile.ZipFile(archive) as bundle:
        names = sorted(
            name
            for name in bundle.namelist()
            if name.startswith("xmlconf/xmltest/") and not name.endswith("/")
        )
        members = [(name, bundle.open(name)) for name in names]
        _write_benchmark_zip(output, members)
    return output


def prepare_ims(source: Path) -> Path:
    output = SOURCE_ROOT / "ims_2004.02.12.10.32.39.tsv"
    copy_if_changed(source, output)
    return output


def prepare_holoclean(dirty_source: Path, clean_source: Path) -> list[Path]:
    outputs = [
        SOURCE_ROOT / "hospital.csv",
        SOURCE_ROOT / "hospital_clean.csv",
    ]
    copy_if_changed(dirty_source, outputs[0])
    copy_if_changed(clean_source, outputs[1])
    return outputs


def source_entry(path: Path, *, records: int | None = None) -> dict[str, object]:
    entry: dict[str, object] = {
        "path": path.relative_to(OUTPUT_ROOT).as_posix(),
        "bytes": path.stat().st_size,
        "sha256": sha256(path),
    }
    if records is not None:
        entry["records"] = records
    return entry


def line_count(path: Path, *, header: bool = False) -> int:
    with path.open("rb") as stream:
        count = sum(1 for _ in stream)
    return max(0, count - int(header))


def write_manifest(files: list[Path], source_archives: dict[str, Path]) -> Path:
    indexed = {path.name: path for path in files}
    manifest = {
        "schema_version": 1,
        "policy": "Only public, externally published benchmark records contribute to acceptance metrics.",
        "datasets": {
            "metropt3": {
                "title": "MetroPT-3 Dataset",
                "publisher": "UCI Machine Learning Repository",
                "doi": "10.24432/C5VW3R",
                "license": "CC BY 4.0",
                "landing_page": "https://archive.ics.uci.edu/dataset/791/metropt+3+dataset",
                "source_archive_sha256": sha256(source_archives["metropt3"]),
                "full_archive": {
                    "url": METRO_FULL_ARCHIVE_URL,
                    "cache_name": "metropt3-uci-791.zip",
                    "sha256": METRO_FULL_ARCHIVE_SHA256,
                    "records": METRO_FULL_RECORDS,
                    "member": METRO_FULL_MEMBER,
                    "sensor_channels": 15,
                },
                "selection": {
                    "compression_source_rows": [
                        [start, start + METRO_WINDOW_ROWS - 1]
                        for start in METRO_COMPRESSION_WINDOWS
                    ],
                    "alignment_rule": "one source reading per minute within each published failure interval plus 30 minutes",
                    "alignment_records": METRO_ALIGNMENT_RECORDS,
                },
                "files": [
                    source_entry(indexed["metropt3_benchmark.csv"], records=METRO_EXPECTED_RECORDS),
                    source_entry(indexed["metropt3_failures.csv"], records=4),
                ],
            },
            "secom": {
                "title": "SECOM",
                "publisher": "UCI Machine Learning Repository",
                "doi": "10.24432/C54305",
                "license": "CC BY 4.0",
                "landing_page": "https://archive.ics.uci.edu/dataset/179/secom",
                "source_archive_sha256": sha256(source_archives["secom"]),
                "files": [
                    source_entry(indexed["secom.data"], records=1567),
                    source_entry(indexed["secom_labels.data"], records=1567),
                    source_entry(indexed["secom.names"]),
                ],
            },
            "ims_bearings": {
                "title": "IMS Bearings, second test, first measurement file",
                "publisher": "NASA Prognostics Center of Excellence / University of Cincinnati IMS Center",
                "license": "United States Government Work",
                "landing_page": "https://data.nasa.gov/dataset/ims-bearings",
                "native_sampling_hz": 20000,
                "outer_archive_bytes": 1061902801,
                "outer_archive_etag": "57b2e74587d73b5485fe0d55731e1331",
                "outer_member": "IMS/2nd_test.rar",
                "inner_member": "2nd_test/2004.02.12.10.32.39",
                "files": [source_entry(indexed["ims_2004.02.12.10.32.39.tsv"], records=20480)],
            },
            "forda": {
                "title": "UCR FordA",
                "publisher": "UCR Time Series Classification Archive",
                "doi": "10.5281/zenodo.11191164",
                "landing_page": "https://zenodo.org/records/11191164",
                "split": "TRAIN+TEST",
                "series": 4921,
                "points_per_series": 500,
                "files": [
                    source_entry(indexed["FordA_TRAIN.ts"], records=3601),
                    source_entry(indexed["FordA_TEST.ts"], records=1320),
                ],
            },
            "holoclean_hospital": {
                "title": "HoloClean Hospital dirty/clean benchmark",
                "publisher": "HoloClean project",
                "repository": "https://github.com/HoloClean/holoclean",
                "commit": "d4f5929a8e4d92d4f41eb058c04c96cdcb0af767",
                "license": "Apache-2.0",
                "files": [
                    source_entry(indexed["hospital.csv"], records=1000),
                    source_entry(indexed["hospital_clean.csv"], records=19000),
                ],
            },
            "json_test_suite": {
                "title": "JSONTestSuite",
                "repository": "https://github.com/nst/JSONTestSuite",
                "commit": "1ef36fa01286573e846ac449e8683f8833c5b26a",
                "license": "MIT",
                "source_archive_sha256": sha256(source_archives["json"]),
                "files": [source_entry(indexed["json_test_suite.zip"])],
            },
            "w3c_xml_conformance": {
                "title": "XML W3C Conformance Test Suite 20130923",
                "publisher": "W3C XML Core Working Group",
                "landing_page": "https://www.w3.org/XML/Test/",
                "source_archive_sha256": sha256(source_archives["xml"]),
                "files": [source_entry(indexed["w3c_xmlconf_xmltest.zip"])],
            },
        },
    }
    output = OUTPUT_ROOT / "benchmark_manifest.json"
    write_if_changed(output, json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8") + b"\n")
    return output


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Prepare pinned public benchmark files")
    parser.add_argument("--secom-archive", type=Path, required=True)
    parser.add_argument("--metropt-archive", type=Path, required=True)
    parser.add_argument("--json-suite-archive", type=Path, required=True)
    parser.add_argument("--xml-suite-archive", type=Path, required=True)
    parser.add_argument("--ims-file", type=Path, required=True)
    parser.add_argument("--forda-train", type=Path, required=True)
    parser.add_argument("--forda-test", type=Path, required=True)
    parser.add_argument("--holoclean-dirty", type=Path, required=True)
    parser.add_argument("--holoclean-clean", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    SOURCE_ROOT.mkdir(parents=True, exist_ok=True)
    files = [
        *prepare_secom(args.secom_archive),
        *prepare_metropt(args.metropt_archive),
        prepare_json_suite(args.json_suite_archive),
        prepare_xml_suite(args.xml_suite_archive),
        prepare_ims(args.ims_file),
        *prepare_forda(args.forda_train, args.forda_test),
        *prepare_holoclean(args.holoclean_dirty, args.holoclean_clean),
    ]
    missing = [str(path) for path in files if not path.is_file()]
    if missing:
        raise FileNotFoundError(f"Missing benchmark files: {missing}")
    manifest = write_manifest(
        files,
        {
            "secom": args.secom_archive,
            "metropt3": args.metropt_archive,
            "json": args.json_suite_archive,
            "xml": args.xml_suite_archive,
        },
    )
    print(manifest)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
