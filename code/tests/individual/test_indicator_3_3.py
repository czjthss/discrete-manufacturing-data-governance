"""Acceptance tests for indicator 3.3 structured-data parsing."""

from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from _support import CODE_ROOT, assert_benchmark_contract
from governance.indicator_3_3 import benchmark, parse_records


class Indicator33Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.result = benchmark()

    def test_benchmark_meets_accuracy_target(self) -> None:
        assert_benchmark_contract(self, self.result, "3.3")
        metrics = self.result["metrics"]
        self.assertGreaterEqual(metrics["parsing_accuracy_percent"], 95.0)
        self.assertEqual(metrics["failure_count"], 0)
        self.assertEqual(metrics["fixtures"], metrics["correctly_parsed"])
        self.assertEqual(len(metrics["unique_fixture_fingerprint_sha256"]), 64)
        self.assertEqual(metrics["labeled_dataset_id"], "indicator-3.3-labeled-v2")
        self.assertEqual(metrics["labeled_dataset_version"], 2)
        self.assertIn("不用于推断", metrics["accuracy_interval_scope"])

    def test_labeled_dataset_hash_is_enforced(self) -> None:
        with (
            patch("governance.indicator_3_3.BENCHMARK_DATA_SHA256", "0" * 64),
            self.assertRaisesRegex(ValueError, "哈希不一致"),
        ):
            benchmark()

    def test_versioned_labeled_dataset_meets_accuracy_target(self) -> None:
        dataset = json.loads(
            (CODE_ROOT / "governance" / "benchmark_data" / "indicator_3_3_labeled.json")
            .read_text(encoding="utf-8")
        )
        correct = 0
        total = len(dataset["valid"]) + len(dataset["invalid"])
        for fixture in dataset["valid"]:
            parsed = parse_records(fixture["text"])
            correct += int(
                parsed["format"] == fixture["expected_format"]
                and len(parsed["records"]) == fixture["expected_rows"]
                and parsed["columns"] == fixture["expected_columns"]
            )
        for payload in dataset["invalid"]:
            try:
                parse_records(payload)
            except ValueError:
                correct += 1
        self.assertGreaterEqual(100.0 * correct / total, 95.0)

    def test_supported_formats_have_expected_records(self) -> None:
        fixtures = (
            ("id,value\n1,42", "csv"),
            ("id\tvalue\n1\t42", "tsv"),
            ("id;value\n1;42", "semicolon"),
            ("id|value\n1|42", "pipe"),
            ('[{"id":1,"value":42}]', "json"),
            ('{"id":1,"value":42}', "jsonl"),
        )
        for payload, expected_format in fixtures:
            with self.subTest(expected_format=expected_format):
                parsed = parse_records(payload, expected_format)
                self.assertEqual(parsed["format"], expected_format)
                self.assertEqual(len(parsed["records"]), 1)
                self.assertEqual(set(parsed["columns"]), {"id", "value"})

    def test_malformed_and_non_object_records_are_rejected(self) -> None:
        for payload, declared_format in (("id,id\n1,2", "csv"), ("[1,2]", "json"), ("{}\n[]", "jsonl")):
            with self.subTest(declared_format=declared_format), self.assertRaises(ValueError):
                parse_records(payload, declared_format)


if __name__ == "__main__":
    unittest.main(verbosity=2)
