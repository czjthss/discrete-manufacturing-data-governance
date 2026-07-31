from __future__ import annotations

import json
import math
import random
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
REPORT_DIR = DATA_DIR / "reports"
STORAGE_DIR = DATA_DIR / "storage"


def ensure_directories() -> None:
    for path in (DATA_DIR, REPORT_DIR, STORAGE_DIR):
        path.mkdir(parents=True, exist_ok=True)


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, value))


def pct(numerator: float, denominator: float) -> float:
    if denominator == 0:
        return 100.0
    return round(100.0 * numerator / denominator, 2)


def json_bytes(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, separators=(",", ":"), default=str
    ).encode("utf-8")


def synthetic_sequence(
    count: int = 5000,
    frequency_hz: int = 1100,
    seed: int = 2030,
) -> list[dict[str, Any]]:
    random.seed(seed)
    base_ms = 1_767_225_600_000
    interval_ms = 1000.0 / frequency_hz
    rows: list[dict[str, Any]] = []
    for index in range(count):
        slow = 50.0 + 6.0 * math.sin(index / 180.0)
        ripple = 0.35 * math.sin(index / 11.0)
        noise = random.uniform(-0.015, 0.015)
        rows.append(
            {
                "timestamp_ms": round(base_ms + index * interval_ms, 6),
                "equipment_id": f"CNC-{1 + (index // 1000) % 3:02d}",
                "value": round(slow + ripple + noise, 6),
                "quality": "good",
            }
        )
    return rows


def synthetic_relations() -> list[dict[str, Any]]:
    base_ms = 1_767_225_600_000
    return [
        {
            "work_order": f"WO-{index + 1:03d}",
            "equipment_id": f"CNC-{index + 1:02d}",
            "start_ms": base_ms + index * 900,
            "end_ms": base_ms + (index + 1) * 1100,
            "product": f"SHAFT-{chr(65 + index)}",
            "process": "精加工",
        }
        for index in range(3)
    ]


def flatten_records(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return [row for row in value if isinstance(row, dict)]
    if isinstance(value, dict):
        for key in ("records", "data", "rows", "items"):
            if isinstance(value.get(key), list):
                return [row for row in value[key] if isinstance(row, dict)]
        return [value]
    return []


def write_json_report(name: str, payload: dict[str, Any]) -> Path:
    ensure_directories()
    path = REPORT_DIR / name
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    return path


def mean(values: Iterable[float]) -> float:
    values = list(values)
    return sum(values) / len(values) if values else 0.0

