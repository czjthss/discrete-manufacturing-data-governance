"""Build the versioned labeled fixtures used by indicators 3.3 and 3.4."""

from __future__ import annotations

import csv
import io
import json
from pathlib import Path


CODE_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_ROOT = CODE_ROOT / "governance" / "benchmark_data"


def parsing_fixture() -> dict[str, object]:
    valid = []
    delimiters = {"csv": ",", "tsv": "\t", "semicolon": ";", "pipe": "|"}
    for data_format, delimiter in delimiters.items():
        for index in range(20):
            headers = ["timestamp_ms", "equipment_id", "value", "note"]
            values: list[object] = [
                1000 + index,
                f"CNC-{index % 7 + 1:02d}",
                f"{42 + index / 10:.1f}",
                f"batch-{index}",
            ]
            variant = index % 5
            if variant == 1:
                headers = ["equipment_id", "value", "timestamp_ms", "note"]
                values = [values[1], values[2], values[0], values[3]]
            elif variant == 2:
                headers = headers[:3]
                values = values[:3]
            elif variant == 3:
                values[-1] = f'batch{delimiter}{index} "quoted"'
            stream = io.StringIO(newline="")
            writer = csv.writer(stream, delimiter=delimiter, lineterminator="\n")
            writer.writerow(headers)
            writer.writerow(values)
            text = stream.getvalue().rstrip("\n")
            if variant == 4:
                text = f"{text}\n\n"
            valid.append(
                {
                    "expected_format": data_format,
                    "text": text,
                    "expected_rows": 1,
                    "expected_columns": sorted(headers),
                }
            )
    for index in range(20):
        wrapper = ("records", "data", "rows", "items")[index % 4]
        row = {
            "timestamp_ms": 2000 + index,
            "equipment_id": f"CNC-{index % 5 + 1:02d}",
            "value": 50 + index / 10,
        }
        if index % 5 == 1:
            row = {
                "value": row["value"],
                "equipment_id": row["equipment_id"],
                "timestamp_ms": row["timestamp_ms"],
            }
        elif index % 5 == 2:
            row.pop("value")
        elif index % 5 == 3:
            row["note"] = 'escaped "quote" and \n newline'
        text = json.dumps(
            {wrapper: [row]},
            ensure_ascii=False,
            indent=2 if index % 5 == 4 else None,
            separators=None if index % 5 == 4 else (",", ":"),
        )
        valid.append(
            {
                "expected_format": "json",
                "text": text,
                "expected_rows": 1,
                "expected_columns": sorted(row),
            }
        )
    for index in range(20):
        rows = [
            {
                "timestamp_ms": 3000 + index * 2,
                "equipment_id": f"CNC-{index % 4 + 1:02d}",
                "value": 60,
            },
            {
                "value": 61,
                "equipment_id": f"CNC-{index % 4 + 1:02d}",
                "timestamp_ms": 3001 + index * 2,
            },
        ]
        if index % 4 == 1:
            rows[0].pop("value")
        elif index % 4 == 2:
            rows[1]["note"] = 'line with "escaped" text'
        text = "\n".join(
            json.dumps(row, ensure_ascii=False, separators=(",", ":")) for row in rows
        )
        valid.append(
            {
                "expected_format": "jsonl",
                "text": text,
                "expected_rows": 2,
                "expected_columns": sorted({key for row in rows for key in row}),
            }
        )
    return {
        "dataset_id": "indicator-3.3-labeled-v2",
        "version": 2,
        "valid": valid,
        "invalid": [
            "",
            "plain unstructured text",
            "{broken json",
            "[1,2,3]",
            '{"records":[1,2]}',
            "id,value\n1,2,3",
            "{}\n[]",
            "[sensor]\ninvalid",
        ],
    }


def alignment_fixture() -> dict[str, object]:
    base = 1_767_225_600_000
    sequence = []
    relations = []
    expected = []
    for index in range(150):
        equipment = f"CNC-{index % 10 + 1:02d}"
        timestamp = base + index * 100
        sample_equipment = equipment.replace("CNC", "CN") if index % 17 == 0 else equipment
        sequence.append(
            {
                "机床编号" if index % 2 else "machine_id": sample_equipment,
                "采集时间" if index % 3 else "ts": timestamp,
                "测量值": 40 + index / 100,
            }
        )
        relations.extend(
            [
                {
                    "equipment_id": equipment,
                    "start_ms": timestamp - 2000,
                    "end_ms": timestamp + 2000,
                    "work_order": f"BROAD-{index:03d}",
                },
                {
                    "device_id": equipment,
                    "开始时间": timestamp - 5,
                    "结束时间": timestamp + 5,
                    "work_order": f"WO-{index:03d}",
                },
            ]
        )
        expected.append(f"WO-{index:03d}")
    sequence.extend(
        [
            {"equipment_id": "CNC-01", "timestamp_ms": "invalid", "value": 1},
            {"equipment_id": "UNKNOWN", "timestamp_ms": base, "value": 2},
            {"timestamp_ms": base, "value": 3},
        ]
    )
    expected.extend([None, None, None])
    relations.append({"equipment_id": "CNC-01", "start_ms": "bad", "work_order": "INVALID"})
    return {
        "dataset_id": "indicator-3.4-labeled-v1",
        "version": 1,
        "tolerance_ms": 50,
        "sequence": sequence,
        "relations": relations,
        "expected_work_orders": expected,
        "negative_samples": 3,
    }


def write_fixture(name: str, payload: dict[str, object]) -> None:
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    target = OUTPUT_ROOT / name
    target.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(target)


def main() -> None:
    write_fixture("indicator_3_3_labeled.json", parsing_fixture())
    write_fixture("indicator_3_4_labeled.json", alignment_fixture())


if __name__ == "__main__":
    main()
