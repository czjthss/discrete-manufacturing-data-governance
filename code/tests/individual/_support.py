"""Shared helpers for directly executable indicator tests."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any


CODE_ROOT = Path(__file__).resolve().parents[2]
REPOSITORY_ROOT = CODE_ROOT.parent
for path in (CODE_ROOT, REPOSITORY_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))


def assert_benchmark_contract(test_case: Any, result: dict[str, Any], indicator: str) -> None:
    """Check the common evidence contract returned by every benchmark."""
    test_case.assertEqual(result["indicator"], indicator)
    test_case.assertIs(result["passed"], True, result)
    test_case.assertIsInstance(result["metrics"], dict)
    test_case.assertTrue(result["metrics"])
    test_case.assertTrue(result["target"])
    test_case.assertTrue(result["method"])
