"""Acceptance tests for indicator 3.3 structured-data parsing."""

from __future__ import annotations

import unittest

from _support import assert_benchmark_contract
from governance.indicator_3_3 import benchmark, parse_records, strict_json_loads
from governance.public_benchmarks import benchmark_file


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
        self.assertEqual(
            set(metrics["dataset_results"]),
            {"metropt3", "forda", "secom", "holoclean_hospital"},
        )
        self.assertEqual(metrics["dataset_results"]["metropt3"]["records"], 1_516_948)
        self.assertEqual(metrics["dataset_results"]["forda"]["points"], 2_460_500)
        self.assertTrue(metrics["dataset_results"]["forda"]["matched"])

    def test_excessive_json_nesting_is_rejected_cleanly(self) -> None:
        payload = "[" * 5000 + "0" + "]" * 5000
        with self.assertRaises(ValueError):
            strict_json_loads(payload)

    def test_public_csv_files_have_expected_records(self) -> None:
        metro = parse_records(
            benchmark_file("metropt3", "metropt3_benchmark.csv").read_text(encoding="utf-8"),
            "csv",
        )
        hospital = parse_records(
            benchmark_file("holoclean_hospital", "hospital.csv").read_text(encoding="utf-8"),
            "csv",
        )
        self.assertEqual(len(metro["records"]), 63823)
        self.assertEqual(len(hospital["records"]), 1000)

    def test_malformed_and_non_object_records_are_rejected(self) -> None:
        for payload, declared_format in (("id,id\n1,2", "csv"), ("[1,2]", "json"), ("{}\n[]", "jsonl")):
            with self.subTest(declared_format=declared_format), self.assertRaises(ValueError):
                parse_records(payload, declared_format)


if __name__ == "__main__":
    unittest.main(verbosity=2)
