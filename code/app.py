from __future__ import annotations

import argparse
import json
import mimetypes
import traceback
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from governance import INDICATORS, INTEGRATION_REGISTRY
from governance.common import ROOT, now_iso, write_json_report
from governance.indicator_3_1 import SequenceRelationStore
from governance.indicator_3_7 import benchmark as fusion_benchmark
from governance.indicator_3_8 import NormalizationRegistry
from governance.indicator_3_9 import assess


STATIC_DIR = ROOT / "static"
MAX_REQUEST_BYTES = 12 * 1024 * 1024


def indicator_catalog() -> list[dict[str, Any]]:
    items = []
    for indicator_id, module in INDICATORS.items():
        profile = INTEGRATION_REGISTRY.indicator_profile(indicator_id)
        items.append(
            {
                "id": indicator_id,
                "title": module.TITLE,
                "target": module.MILESTONE_TARGET,
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


def run_indicator(indicator_id: str) -> dict[str, Any]:
    if indicator_id not in INDICATORS:
        raise KeyError(f"未知指标: {indicator_id}")
    result = INDICATORS[indicator_id].benchmark()
    result["tested_at"] = now_iso()
    return result


def run_all() -> dict[str, Any]:
    results = [run_indicator(indicator_id) for indicator_id in INDICATORS]
    report = {
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
        "statement": (
            "本报告为软件自测结果。指标3.6在任务书里程碑2中要求第三方检测，"
            "本报告不能替代具有检测能力的第三方机构出具的正式测试报告。"
        ),
    }
    path = write_json_report("latest-self-test.json", report)
    report["report_path"] = str(path)
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

    def _send_file(self, path: Path) -> None:
        if not path.exists() or not path.is_file():
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        data = path.read_bytes()
        content_type, _ = mimetypes.guess_type(path.name)
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type or "application/octet-stream")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        if length > MAX_REQUEST_BYTES:
            raise ValueError("请求体超过 12MB 限制")
        raw = self.rfile.read(length)
        return json.loads(raw or b"{}")

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/":
            self._send_file(STATIC_DIR / "index.html")
            return
        if path == "/api/health":
            self._send_json(
                {
                    "status": "ok",
                    "service": "discrete-manufacturing-data-governance",
                    "time": now_iso(),
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
        content = str(payload.get("content", ""))
        if not content.strip():
            raise ValueError("请输入或导入待治理数据")
        declared_format = str(payload.get("format", "auto"))
        normalized = NormalizationRegistry().normalize(content, declared_format)
        records = normalized["records"]
        quality = assess(records)
        storage = SequenceRelationStore().store_sequence("workspace-latest", records)
        return {
            "analyzed_at": now_iso(),
            "source": {
                "format": normalized["format"],
                "records": len(records),
                "columns": normalized["columns"],
            },
            "quality": quality,
            "storage": storage,
            "preview": records[:8],
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
