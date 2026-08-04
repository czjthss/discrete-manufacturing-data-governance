from __future__ import annotations

import heapq
import json
import math
import os
import platform
import random
import shutil
import tempfile
import threading
import time
import uuid
import zlib
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import fcntl


ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
REPORT_DIR = DATA_DIR / "reports"
STORAGE_DIR = DATA_DIR / "storage"

_PATH_LOCKS: dict[Path, threading.RLock] = {}
_PATH_LOCKS_GUARD = threading.Lock()
_ARTIFACTS_LOCK = threading.RLock()
_ACTIVE_ARTIFACTS: dict[Path, int] = {}

RETENTION_POLICIES = {
    "run_reports": ("DGOV_RETENTION_RUN_REPORTS", 256),
    "governance_reports": ("DGOV_RETENTION_GOVERNANCE_REPORTS", 256),
    "storage_runs": ("DGOV_RETENTION_STORAGE_RUNS", 128),
    "analysis_sequences": ("DGOV_RETENTION_ANALYSIS_SEQUENCES", 256),
}
RETENTION_GRACE_ENV = "DGOV_RETENTION_GRACE_SECONDS"
DEFAULT_RETENTION_GRACE_SECONDS = 600.0


def ensure_directories() -> None:
    for path in (DATA_DIR, REPORT_DIR, STORAGE_DIR):
        path.mkdir(parents=True, exist_ok=True)


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def new_run_id(prefix: str = "run") -> str:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    return f"{prefix}-{timestamp}-{uuid.uuid4().hex[:10]}"


def path_lock(path: Path) -> threading.RLock:
    resolved = path.resolve()
    with _PATH_LOCKS_GUARD:
        return _PATH_LOCKS.setdefault(resolved, threading.RLock())


def retention_limit(category: str) -> int:
    try:
        variable, default = RETENTION_POLICIES[category]
    except KeyError as exc:
        raise ValueError(f"未知产物保留类别: {category}") from exc
    raw = os.environ.get(variable)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return value if value >= 1 else default


def retention_grace_seconds() -> float:
    raw = os.environ.get(RETENTION_GRACE_ENV)
    if raw is None:
        return DEFAULT_RETENTION_GRACE_SECONDS
    try:
        value = float(raw)
    except ValueError:
        return DEFAULT_RETENTION_GRACE_SECONDS
    return value if math.isfinite(value) and value >= 0 else DEFAULT_RETENTION_GRACE_SECONDS


def _is_active_artifact(path: Path) -> bool:
    resolved = path.resolve()
    return any(
        resolved == active
        or resolved in active.parents
        or active in resolved.parents
        for active in _ACTIVE_ARTIFACTS
    )


@contextmanager
def artifact_write_scope(path: Path):
    resolved = path.resolve()
    with _ARTIFACTS_LOCK:
        _ACTIVE_ARTIFACTS[resolved] = _ACTIVE_ARTIFACTS.get(resolved, 0) + 1
    try:
        yield
    finally:
        with _ARTIFACTS_LOCK:
            remaining = _ACTIVE_ARTIFACTS.get(resolved, 1) - 1
            if remaining > 0:
                _ACTIVE_ARTIFACTS[resolved] = remaining
            else:
                _ACTIVE_ARTIFACTS.pop(resolved, None)


@contextmanager
def retention_process_lock(directory: Path):
    """Serialize pruning across processes that share an artifact directory."""
    directory.mkdir(parents=True, exist_ok=True)
    lock_path = directory / ".retention.lock"
    with lock_path.open("a+b") as stream:
        fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def prune_retained_artifacts(
    directory: Path,
    *,
    limit: int,
    pattern: str = "*",
    directories: bool = False,
    protected: Iterable[Path] = (),
    minimum_age_seconds: float = 0.0,
    completion_marker: str | None = None,
) -> list[Path]:
    """Keep newest eligible artifacts with process-safe, bounded-memory pruning."""
    if limit < 1:
        raise ValueError("产物保留数量必须是正整数")
    if not math.isfinite(minimum_age_seconds) or minimum_age_seconds < 0:
        raise ValueError("产物最小保留时间必须是非负有限数")
    if completion_marker is not None and not directories:
        raise ValueError("完成标记只适用于目录产物")
    if not directory.exists():
        return []
    protected_paths = {path.resolve() for path in protected}
    eligible_before_ns = time.time_ns() - int(minimum_age_seconds * 1_000_000_000)

    def candidates():
        for path in directory.glob(pattern):
            try:
                correct_kind = path.is_dir() if directories else path.is_file()
                if not correct_kind:
                    continue
                resolved = path.resolve()
                if resolved in protected_paths or _is_active_artifact(resolved):
                    continue
                eligibility_path = (
                    path / completion_marker if completion_marker is not None else path
                )
                if completion_marker is not None and not eligibility_path.is_file():
                    continue
                stat = eligibility_path.stat()
                if stat.st_mtime_ns > eligible_before_ns:
                    continue
            except (FileNotFoundError, OSError):
                continue
            yield stat.st_mtime_ns, path.name, resolved

    removed: list[Path] = []
    with _ARTIFACTS_LOCK, retention_process_lock(directory):
        retained_slots = max(0, limit - len(protected_paths))
        newest = heapq.nlargest(retained_slots, candidates())
        retained = {item[2] for item in newest} | protected_paths
        for _, _, resolved in candidates():
            if resolved in retained or _is_active_artifact(resolved):
                continue
            try:
                if directories:
                    shutil.rmtree(resolved)
                else:
                    resolved.unlink()
                removed.append(resolved)
            except FileNotFoundError:
                continue
    return removed


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


def atomic_write_bytes(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: str | None = None
    with artifact_write_scope(path), path_lock(path):
        try:
            with tempfile.NamedTemporaryFile(
                mode="wb",
                dir=path.parent,
                prefix=f".{path.name}.",
                suffix=".tmp",
                delete=False,
            ) as stream:
                temporary = stream.name
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
        finally:
            if temporary and os.path.exists(temporary):
                os.unlink(temporary)


def atomic_write_text(path: Path, text: str) -> None:
    atomic_write_bytes(path, text.encode("utf-8"))


def bounded_zlib_decompress(payload: bytes, max_output_bytes: int) -> bytes:
    if not isinstance(payload, bytes):
        raise ValueError("压缩载荷必须是 bytes")
    if not isinstance(max_output_bytes, int) or max_output_bytes <= 0:
        raise ValueError("解压输出上限必须是正整数")
    decompressor = zlib.decompressobj()
    try:
        output = decompressor.decompress(payload, max_output_bytes + 1)
    except zlib.error as exc:
        raise ValueError("压缩载荷不是有效的 zlib 数据") from exc
    if len(output) > max_output_bytes or decompressor.unconsumed_tail:
        raise ValueError("解压结果超过资源上限")
    if not decompressor.eof:
        raise ValueError("压缩载荷被截断")
    if decompressor.unused_data:
        raise ValueError("压缩载荷包含尾随数据")
    return output


def synthetic_sequence(
    count: int = 5000,
    frequency_hz: int = 1100,
    seed: int = 2030,
) -> list[dict[str, Any]]:
    generator = random.Random(seed)
    base_ms = 1_767_225_600_000
    interval_ms = 1000.0 / frequency_hz
    rows: list[dict[str, Any]] = []
    for index in range(count):
        slow = 50.0 + 6.0 * math.sin(index / 180.0)
        ripple = 0.35 * math.sin(index / 11.0)
        noise = generator.uniform(-0.015, 0.015)
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
    with artifact_write_scope(path):
        atomic_write_text(
            path,
            json.dumps(payload, ensure_ascii=False, indent=2, default=str),
        )
        category = Path(name).parts[0] if Path(name).parts else ""
        if category == "runs":
            prune_retained_artifacts(
                path.parent,
                limit=retention_limit("run_reports"),
                pattern="*.json",
                protected=(path,),
                minimum_age_seconds=retention_grace_seconds(),
            )
        elif category == "governance":
            prune_retained_artifacts(
                path.parent,
                limit=retention_limit("governance_reports"),
                pattern="*.json",
                protected=(path,),
                minimum_age_seconds=retention_grace_seconds(),
            )
    return path


def mean(values: Iterable[float]) -> float:
    values = list(values)
    return sum(values) / len(values) if values else 0.0


def wilson_interval(successes: int, total: int, z: float = 1.96) -> tuple[float, float]:
    if total <= 0:
        return 0.0, 0.0
    proportion = successes / total
    denominator = 1.0 + z * z / total
    center = (proportion + z * z / (2.0 * total)) / denominator
    margin = (
        z
        * math.sqrt(
            proportion * (1.0 - proportion) / total
            + z * z / (4.0 * total * total)
        )
        / denominator
    )
    return round(100.0 * max(0.0, center - margin), 2), round(
        100.0 * min(1.0, center + margin), 2
    )


def environment_metadata() -> dict[str, Any]:
    return {
        "python": platform.python_version(),
        "implementation": platform.python_implementation(),
        "platform": platform.platform(),
        "processor": platform.processor() or "unknown",
        "pid": os.getpid(),
    }
