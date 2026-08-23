from __future__ import annotations

import argparse
import copy
import heapq
import json
import mimetypes
import re
import threading
import time
import traceback
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from governance import INDICATORS, INTEGRATION_REGISTRY
from governance.common import (
    ROOT,
    environment_metadata,
    new_run_id,
    now_iso,
    write_json_report,
)
from governance.indicator_3_1 import SequenceRelationStore
from governance.indicator_3_7 import benchmark as fusion_benchmark
from governance.indicator_3_8 import NormalizationRegistry
from governance.pipeline import govern_records, validate_rules


STATIC_DIR = ROOT / "static"
MAX_REQUEST_BYTES = 12 * 1024 * 1024
_BENCHMARK_CONDITION = threading.Condition()
_BENCHMARK_RUNNING = False
_BENCHMARK_CACHE: list[dict[str, Any]] | None = None
_BENCHMARK_CACHE_TIME = 0.0
_BENCHMARK_CACHE_SECONDS = 5.0


def indicator_catalog() -> list[dict[str, Any]]:
    matrix = {
        item["indicator"]: item
        for item in INTEGRATION_REGISTRY.integrations_payload()["indicator_matrix"]
    }
    items = []
    for indicator_id, module in INDICATORS.items():
        profile = matrix[indicator_id]
        items.append(
            {
                "id": indicator_id,
                "title": module.TITLE,
                "target": module.MILESTONE_TARGET,
                "scope": "milestone_2_core" if indicator_id in {
                    "3.1", "3.2", "3.3", "3.4", "3.5", "3.6", "3.7"
                } else "later_stage_research",
                "scope_label": "里程碑2核心" if indicator_id in {
                    "3.1", "3.2", "3.3", "3.4", "3.5", "3.6", "3.7"
                } else "后续阶段预研",
                "current_methods": [
                    item["method"] for item in profile["current_methods"]
                ],
                "planned_integrations": [
                    item["name"] for item in profile["planned_integrations"]
                ],
            }
        )
    return items


def reference_catalog() -> dict[str, Any]:
    return INTEGRATION_REGISTRY.references_payload()


def integration_catalog() -> dict[str, Any]:
    return INTEGRATION_REGISTRY.integrations_payload()


def recent_report_paths(report_root: Path, limit: int = 100) -> list[Path]:
    if limit < 1 or not report_root.exists():
        return []

    def candidates():
        for report in report_root.rglob("*.json"):
            try:
                stat = report.stat()
            except (FileNotFoundError, OSError):
                continue
            yield stat.st_mtime_ns, report.as_posix(), report

    return [item[2] for item in heapq.nlargest(limit, candidates())]


def run_indicator(indicator_id: str) -> dict[str, Any]:
    if indicator_id not in INDICATORS:
        raise KeyError(f"未知指标: {indicator_id}")
    result = INDICATORS[indicator_id].benchmark()
    result["tested_at"] = now_iso()
    return result


def _run_all_indicators() -> list[dict[str, Any]]:
    global _BENCHMARK_RUNNING, _BENCHMARK_CACHE, _BENCHMARK_CACHE_TIME
    with _BENCHMARK_CONDITION:
        cache_age = time.monotonic() - _BENCHMARK_CACHE_TIME
        if _BENCHMARK_CACHE is not None and cache_age <= _BENCHMARK_CACHE_SECONDS:
            return copy.deepcopy(_BENCHMARK_CACHE)
        if _BENCHMARK_RUNNING:
            while _BENCHMARK_RUNNING:
                _BENCHMARK_CONDITION.wait()
            if _BENCHMARK_CACHE is None:
                raise RuntimeError("并发指标测试未生成结果")
            return copy.deepcopy(_BENCHMARK_CACHE)
        _BENCHMARK_RUNNING = True
        _BENCHMARK_CACHE = None

    try:
        results = [run_indicator(indicator_id) for indicator_id in INDICATORS]
    except BaseException:
        with _BENCHMARK_CONDITION:
            _BENCHMARK_RUNNING = False
            _BENCHMARK_CACHE = None
            _BENCHMARK_CONDITION.notify_all()
        raise
    with _BENCHMARK_CONDITION:
        _BENCHMARK_CACHE = copy.deepcopy(results)
        _BENCHMARK_CACHE_TIME = time.monotonic()
        _BENCHMARK_RUNNING = False
        _BENCHMARK_CONDITION.notify_all()
    return results


def run_all() -> dict[str, Any]:
    run_id = new_run_id("selftest")
    results = _run_all_indicators()
    report = {
        "run_id": run_id,
        "system": "面向离散制造垂域模型的自动化数据治理系统",
        "milestone": "项目里程碑2",
        "generated_at": now_iso(),
        "passed": all(result["passed"] for result in results),
        "summary": {
            "total": len(results),
            "passed": sum(result["passed"] for result in results),
            "failed": sum(not result["passed"] for result in results),
        },
        "results": results,
        "environment": environment_metadata(),
        "statement": (
            "本报告记录软件自测的运行环境、测量过程和结果，"
            "用于项目复验与验收材料整理。"
        ),
        "artifacts": {
            "run_report": f"data/reports/runs/{run_id}.json",
            "latest_report": "data/reports/latest-self-test.json",
        },
    }
    run_path = write_json_report(f"runs/{run_id}.json", report)
    latest_path = write_json_report("latest-self-test.json", report)
    report["report_path"] = str(latest_path)
    report["run_report_path"] = str(run_path)
    return report


class GovernanceHandler(BaseHTTPRequestHandler):
    server_version = "DGov/0.1"

    def log_message(self, fmt: str, *args: Any) -> None:
        print(f"[web] {self.address_string()} - {fmt % args}")

    def _send_json(self, payload: Any, status: int = HTTPStatus.OK) -> None:
        body = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _send_file(self, path: Path, download_name: str | None = None) -> None:
        if not path.exists() or not path.is_file():
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        data = path.read_bytes()
        content_type, _ = mimetypes.guess_type(path.name)
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type or "application/octet-stream")
        self.send_header("Content-Length", str(len(data)))
        if download_name:
            self.send_header("Content-Disposition", f'attachment; filename="{download_name}"')
        self.end_headers()
        self.wfile.write(data)

    def _read_json(self) -> dict[str, Any]:
        raw_length = self.headers.get("Content-Length", "0")
        try:
            length = int(raw_length)
        except (TypeError, ValueError) as exc:
            raise ValueError("无效的 Content-Length") from exc
        if length < 0:
            raise ValueError("Content-Length 不能为负数")
        if length > MAX_REQUEST_BYTES:
            raise ValueError("请求体超过 12MB 限制")
        raw = self.rfile.read(length)
        payload = json.loads(raw or b"{}")
        if not isinstance(payload, dict):
            raise ValueError("请求体顶层必须是 JSON 对象")
        return payload

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/":
            self._send_file(STATIC_DIR / "index.html")
            return
        if path == "/api/health":
            integration_summary = integration_catalog()["summary"]
            healthy = (
                integration_summary["active"]
                == integration_summary["runtime_available"]
            )
            self._send_json(
                {
                    "status": "ok" if healthy else "degraded",
                    "service": "discrete-manufacturing-data-governance",
                    "time": now_iso(),
                    "algorithms": {
                        "active": integration_summary["active"],
                        "runtime_available": integration_summary[
                            "runtime_available"
                        ],
                    },
                }
            )
            return
        if path == "/api/indicators":
            self._send_json({"items": indicator_catalog()})
            return
        if path == "/api/references":
            self._send_json(reference_catalog())
            return
        if path == "/api/integrations":
            self._send_json(integration_catalog())
            return
        if path == "/api/report/latest":
            report = ROOT / "data" / "reports" / "latest-self-test.json"
            if report.exists():
                self._send_json(json.loads(report.read_text(encoding="utf-8")))
            else:
                self._send_json({"message": "尚未生成自测报告"}, HTTPStatus.NOT_FOUND)
            return
        if path == "/api/reports":
            report_root = ROOT / "data" / "reports"
            items = []
            if report_root.exists():
                for report in recent_report_paths(report_root):
                    try:
                        size_bytes = report.stat().st_size
                    except (FileNotFoundError, OSError):
                        continue
                    relative = report.relative_to(report_root).as_posix()
                    items.append(
                        {
                            "name": report.name,
                            "category": report.parent.name,
                            "relative_path": relative,
                            "size_bytes": size_bytes,
                            "download_url": f"/api/reports/download/{relative}",
                        }
                    )
            self._send_json({"items": items})
            return
        if path.startswith("/api/reports/download/"):
            relative_name = path.removeprefix("/api/reports/download/")
            if (
                not re.fullmatch(
                    r"(?:[A-Za-z0-9._-]+/)*[A-Za-z0-9._-]{1,180}\.json",
                    relative_name,
                )
                or ".." in Path(relative_name).parts
            ):
                self.send_error(HTTPStatus.BAD_REQUEST)
                return
            report_root = (ROOT / "data" / "reports").resolve()
            report = (report_root / relative_name).resolve()
            if report_root not in report.parents or not report.is_file():
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            self._send_file(report, download_name=report.name)
            return
        if path.startswith("/static/"):
            relative = Path(path.removeprefix("/static/"))
            target = (STATIC_DIR / relative).resolve()
            if STATIC_DIR.resolve() not in target.parents:
                self.send_error(HTTPStatus.FORBIDDEN)
            else:
                self._send_file(target)
            return
        self.send_error(HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        try:
            payload = self._read_json()
            if path == "/api/benchmark/all":
                self._send_json(run_all())
                return
            if path.startswith("/api/benchmark/"):
                indicator_id = path.removeprefix("/api/benchmark/")
                self._send_json(run_indicator(indicator_id))
                return
            if path == "/api/analyze":
                self._send_json(self._analyze(payload))
                return
            if path == "/api/rules/validate":
                self._send_json({"rules": validate_rules(payload.get("rules"))})
                return
            if path == "/api/fusion/demo":
                self._send_json(fusion_benchmark())
                return
            self.send_error(HTTPStatus.NOT_FOUND)
        except KeyError as exc:
            self._send_json({"error": str(exc)}, HTTPStatus.NOT_FOUND)
        except (ValueError, json.JSONDecodeError) as exc:
            self._send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
        except Exception as exc:
            traceback.print_exc()
            self._send_json(
                {"error": f"服务器处理失败: {exc}"},
                HTTPStatus.INTERNAL_SERVER_ERROR,
            )

    @staticmethod
    def _analyze(payload: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise ValueError("请求体顶层必须是 JSON 对象")
        content = payload.get("content", "")
        if not isinstance(content, str):
            raise ValueError("content 必须是字符串")
        if not content.strip():
            raise ValueError("请输入或导入待治理数据")
        declared_format = payload.get("format", "auto")
        if not isinstance(declared_format, str):
            raise ValueError("format 必须是字符串")
        normalized = NormalizationRegistry().normalize(content, declared_format)
        records = normalized["records"]
        raw_reference_data = payload.get("reference_data")
        reference_data = None
        if raw_reference_data is not None:
            if not isinstance(raw_reference_data, dict) or not all(
                isinstance(values, list) for values in raw_reference_data.values()
            ):
                raise ValueError("主数据必须是字段到值数组的 JSON 对象")
            reference_data = {
                str(field): {str(value) for value in values}
                for field, values in raw_reference_data.items()
            }
        governed = govern_records(
            records,
            rules=payload.get("rules"),
            reference_data=reference_data,
        )
        quality = governed["quality_after"]
        request_id = new_run_id("analysis")
        storage = SequenceRelationStore().store_sequence(request_id, governed["records"])
        return {
            "request_id": request_id,
            "governance_run_id": governed["run_id"],
            "analyzed_at": now_iso(),
            "source": {
                "format": normalized["format"],
                "records": len(records),
                "columns": normalized["columns"],
            },
            "quality": quality,
            "quality_before": governed["quality_before"],
            "governance": governed["summary"],
            "rules": governed["rules"],
            "storage": storage,
            "report_path": governed["report_path"],
            "report_download_url": (
                "/api/reports/download/governance/"
                f"{Path(governed['report_path']).name}"
            ),
            "preview": governed["records"][:8],
            "quarantine_preview": governed["quarantine"][:8],
            "lineage_preview": governed["lineage"][:20],
        }


def main() -> None:
    parser = argparse.ArgumentParser(description="离散制造自动化数据治理系统")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    server = ThreadingHTTPServer((args.host, args.port), GovernanceHandler)
    print(f"数据治理系统已启动: http://{args.host}:{args.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n正在关闭服务")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
