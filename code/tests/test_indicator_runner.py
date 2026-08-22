"""Tests for the standalone indicator test runner."""

from __future__ import annotations

import json
import hashlib
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


CODE_ROOT = Path(__file__).resolve().parents[1]
if str(CODE_ROOT) not in sys.path:
    sys.path.insert(0, str(CODE_ROOT))
if str(CODE_ROOT / "tools") not in sys.path:
    sys.path.insert(0, str(CODE_ROOT / "tools"))

import build_delivery_package
import run_indicator_tests as runner


class IndicatorRunnerTests(unittest.TestCase):
    def test_benchmark_exception_is_reported_and_returns_failure(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with (
                patch.object(
                    sys,
                    "argv",
                    ["run_indicator_tests.py", "3.1", "--report-dir", directory],
                ),
                patch.object(
                    runner,
                    "run_test_file",
                    return_value={"indicator": "3.1", "passed": True, "return_code": 0},
                ),
                patch.object(
                    runner.INDICATORS["3.1"],
                    "benchmark",
                    side_effect=RuntimeError("expected failure"),
                ),
            ):
                self.assertEqual(runner.main(), 1)
            reports = list(Path(directory).glob("*.json"))
            self.assertEqual(len(reports), 1)
            report = json.loads(reports[0].read_text(encoding="utf-8"))
            self.assertFalse(report["passed"])
            self.assertEqual(report["benchmarks"]["3.1"]["error"]["type"], "RuntimeError")

    def test_source_state_contains_manifest_hash(self) -> None:
        state = runner.source_state()
        self.assertEqual(len(state["algorithm_manifest_sha256"]), 64)
        self.assertEqual(len(state["source_tree_sha256"]), 64)
        self.assertEqual(state["source_file_count"], len(state["source_file_sha256"]))
        self.assertIn("code/run_indicator_tests.py", state["source_file_sha256"])
        self.assertEqual(state["git_status_scope"], "tracked_files_only")

    def test_source_state_keeps_stable_git_fields_outside_repository(self) -> None:
        unavailable = SimpleNamespace(returncode=128, stdout="", stderr="not a repository")
        with patch.object(runner.subprocess, "run", return_value=unavailable):
            state = runner.source_state()
        self.assertIsNone(state["git_commit"])
        self.assertIsNone(state["git_dirty"])
        self.assertEqual(state["git_status_scope"], "tracked_files_only")
        self.assertEqual(state["git_error"], "not a repository")

    def test_source_evidence_failure_is_reported(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with (
                patch.object(
                    sys,
                    "argv",
                    ["run_indicator_tests.py", "3.1", "--report-dir", directory],
                ),
                patch.object(
                    runner,
                    "run_test_file",
                    return_value={"indicator": "3.1", "passed": True, "return_code": 0},
                ),
                patch.object(
                    runner.INDICATORS["3.1"],
                    "benchmark",
                    return_value={"indicator": "3.1", "passed": True},
                ),
                patch.object(runner, "source_state", side_effect=ValueError("bad manifest")),
            ):
                self.assertEqual(runner.main(), 1)
            reports = list(Path(directory).glob("*.json"))
            self.assertEqual(len(reports), 1)
            report = json.loads(reports[0].read_text(encoding="utf-8"))
            self.assertFalse(report["passed"])
            self.assertEqual(report["source"]["error"]["type"], "ValueError")

    def test_delivery_package_is_deterministic_and_self_verifying(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            first = Path(directory) / "first.zip"
            second = Path(directory) / "second.zip"
            build_delivery_package.build_package(first, validate_evidence=False)
            build_delivery_package.build_package(second, validate_evidence=False)
            self.assertEqual(first.read_bytes(), second.read_bytes())
            with zipfile.ZipFile(first) as archive:
                self.assertIsNone(archive.testzip())
                package_manifest = json.loads(
                    archive.read("PACKAGE_MANIFEST.json").decode("utf-8")
                )
                self.assertEqual(
                    package_manifest["entry_count"],
                    len(package_manifest["entries"]),
                )
                for name, evidence in package_manifest["entries"].items():
                    payload = archive.read(name)
                    self.assertEqual(len(payload), evidence["bytes"])
                    self.assertEqual(hashlib.sha256(payload).hexdigest(), evidence["sha256"])

    def test_delivery_package_rejects_stale_report(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            report = Path(directory) / "stale.json"
            report.write_text(
                json.dumps(
                    {
                        "passed": True,
                        "source": {
                            "source_file_sha256": {"code/run_indicator_tests.py": "0" * 64},
                            "source_tree_sha256": "0" * 64,
                            "algorithm_manifest_sha256": "0" * 64,
                        },
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "不一致"):
                build_delivery_package.validate_report_source(
                    build_delivery_package.delivery_files(), report
                )


if __name__ == "__main__":
    unittest.main(verbosity=2)
