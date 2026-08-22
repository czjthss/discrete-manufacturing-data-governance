"""Run one or all indicator acceptance tests and write reproducible JSON evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import subprocess
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path

from governance import INDICATORS
from governance.common import atomic_write_text, new_run_id


CODE_ROOT = Path(__file__).resolve().parent
REPOSITORY_ROOT = CODE_ROOT.parent
TEST_ROOT = CODE_ROOT / "tests" / "individual"
DEFAULT_REPORT_ROOT = CODE_ROOT / "data" / "reports" / "indicator-tests"
INDICATOR_IDS = tuple(INDICATORS)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="逐项运行 3.1-3.9 指标测试")
    parser.add_argument(
        "indicator",
        nargs="?",
        default="all",
        choices=("all", *INDICATOR_IDS),
        help="指标编号；省略或使用 all 时运行全部指标",
    )
    parser.add_argument(
        "--report-dir",
        type=Path,
        default=DEFAULT_REPORT_ROOT,
        help="JSON 报告输出目录",
    )
    parser.add_argument("--no-report", action="store_true", help="不写入 JSON 报告")
    return parser.parse_args()


def run_test_file(indicator: str) -> dict[str, object]:
    test_file = TEST_ROOT / f"test_indicator_{indicator.replace('.', '_')}.py"
    started = time.perf_counter()
    try:
        completed = subprocess.run(
            [sys.executable, str(test_file)],
            cwd=REPOSITORY_ROOT,
            text=True,
            capture_output=True,
            check=False,
            timeout=600,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        elapsed = time.perf_counter() - started
        print(f"测试进程启动或执行失败: {exc}", file=sys.stderr)
        return {
            "indicator": indicator,
            "test_file": str(test_file.relative_to(REPOSITORY_ROOT)),
            "passed": False,
            "return_code": None,
            "elapsed_seconds": round(elapsed, 6),
            "error": {"type": type(exc).__name__, "message": str(exc)},
        }
    elapsed = time.perf_counter() - started
    if completed.stdout:
        print(completed.stdout, end="")
    if completed.stderr:
        print(completed.stderr, end="", file=sys.stderr)
    result: dict[str, object] = {
        "indicator": indicator,
        "test_file": str(test_file.relative_to(REPOSITORY_ROOT)),
        "passed": completed.returncode == 0,
        "return_code": completed.returncode,
        "elapsed_seconds": round(elapsed, 6),
    }
    if completed.returncode != 0:
        result["stdout"] = completed.stdout[-20_000:]
        result["stderr"] = completed.stderr[-20_000:]
    return result


def source_state() -> dict[str, object]:
    manifest_path = CODE_ROOT / "algorithm_manifest.json"
    manifest_bytes = manifest_path.read_bytes() if manifest_path.exists() else None
    state: dict[str, object] = {
        "algorithm_manifest_sha256": (
            hashlib.sha256(manifest_bytes).hexdigest() if manifest_bytes else None
        ),
        "git_commit": None,
        "git_dirty": None,
        "git_status_scope": "tracked_files_only",
    }
    if manifest_bytes:
        manifest = json.loads(manifest_bytes)
        source_paths = {Path("code/algorithm_manifest.json"), Path("code/run_indicator_tests.py")}
        for value in manifest.get("support_files", []):
            source_paths.add(Path("code") / value)
        for spec in manifest.get("indicators", {}).values():
            for field in ("algorithm_files", "native_reference_files", "test_data_files"):
                for value in spec.get(field, []):
                    source_paths.add(Path("code") / value)
            if spec.get("test_file"):
                source_paths.add(Path("code") / spec["test_file"])
        file_hashes: dict[str, str] = {}
        for relative_path in sorted(source_paths, key=str):
            resolved = (REPOSITORY_ROOT / relative_path).resolve()
            try:
                resolved.relative_to(REPOSITORY_ROOT.resolve())
            except ValueError as exc:
                raise ValueError(f"源码清单路径超出项目目录: {relative_path}") from exc
            if not resolved.is_file():
                raise FileNotFoundError(f"源码清单文件不存在: {relative_path}")
            normalized_path = resolved.relative_to(REPOSITORY_ROOT.resolve()).as_posix()
            file_hashes[normalized_path] = hashlib.sha256(resolved.read_bytes()).hexdigest()
        combined = hashlib.sha256()
        for path, digest in sorted(file_hashes.items()):
            combined.update(path.encode("utf-8"))
            combined.update(b"\0")
            combined.update(digest.encode("ascii"))
            combined.update(b"\n")
        state["source_tree_sha256"] = combined.hexdigest()
        state["source_file_count"] = len(file_hashes)
        state["source_file_sha256"] = file_hashes
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=REPOSITORY_ROOT,
            text=True,
            capture_output=True,
            check=False,
            timeout=10,
        )
        status = subprocess.run(
            ["git", "status", "--porcelain", "--untracked-files=no"],
            cwd=REPOSITORY_ROOT,
            text=True,
            capture_output=True,
            check=False,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        state["git_error"] = f"{type(exc).__name__}: {exc}"
        return state
    if commit.returncode == 0:
        state["git_commit"] = commit.stdout.strip()
        state["git_dirty"] = status.returncode == 0 and bool(status.stdout.strip())
    else:
        state["git_error"] = commit.stderr.strip() or "Git commit 不可用"
    return state


def main() -> int:
    args = parse_args()
    selected = INDICATOR_IDS if args.indicator == "all" else (args.indicator,)
    run_id = new_run_id("indicator-tests")
    tests = []
    benchmarks = {}
    for indicator in selected:
        print(f"\n[{indicator}] 运行独立测试", flush=True)
        test_result = run_test_file(indicator)
        tests.append(test_result)
        try:
            benchmarks[indicator] = INDICATORS[indicator].benchmark()
        except Exception as exc:
            benchmarks[indicator] = {
                "indicator": indicator,
                "passed": False,
                "error": {
                    "type": type(exc).__name__,
                    "message": str(exc),
                    "traceback": traceback.format_exc(limit=12),
                },
            }

    try:
        source = source_state()
        source_ok = True
    except Exception as exc:
        source = {
            "error": {
                "type": type(exc).__name__,
                "message": str(exc),
                "traceback": traceback.format_exc(limit=12),
            }
        }
        source_ok = False
    passed = source_ok and all(item["passed"] for item in tests) and all(
        result["passed"] for result in benchmarks.values()
    ) and len(benchmarks) == len(selected)
    report = {
        "run_id": run_id,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "selected_indicators": list(selected),
        "passed": passed,
        "environment": {
            "python": platform.python_version(),
            "implementation": platform.python_implementation(),
            "platform": platform.platform(),
            "processor": platform.processor() or "not-reported",
        },
        "source": source,
        "tests": tests,
        "benchmarks": benchmarks,
    }
    if not args.no_report:
        report_path = args.report_dir.resolve() / f"{run_id}.json"
        atomic_write_text(report_path, json.dumps(report, ensure_ascii=False, indent=2))
        print(f"\n报告: {report_path}")
    print(f"结果: {'通过' if passed else '未通过'}")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
