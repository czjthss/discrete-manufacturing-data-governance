"""Acceptance tests for indicator 3.8 normalization adapters."""

from __future__ import annotations

import unittest

from _support import assert_benchmark_contract
from governance.indicator_3_8 import NormalizationRegistry, benchmark
from governance.public_benchmarks import benchmark_file


class Indicator38Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.result = benchmark()

    def test_benchmark_covers_all_registered_formats(self) -> None:
        assert_benchmark_contract(self, self.result, "3.8")
        metrics = self.result["metrics"]
        self.assertEqual(metrics["registered_adapters"], 8)
        self.assertEqual(metrics["tested_format_families"], 3)
        self.assertEqual(metrics["datasets_tested"], 4)
        self.assertEqual(metrics["normalization_success_percent"], 100.0)
        self.assertEqual(
            set(metrics["dataset_results"]),
            {"metropt3", "forda", "secom", "holoclean_hospital"},
        )
        self.assertTrue(
            all(item["normalized"] for item in metrics["public_table_normalization"].values())
        )

    def test_public_csv_normalizes_to_common_shape(self) -> None:
        registry = NormalizationRegistry()
        source = benchmark_file("holoclean_hospital", "hospital.csv")
        result = registry.normalize(source.read_text(encoding="utf-8"), "csv")
        self.assertTrue(result["normalized"])
        self.assertEqual(len(result["records"]), 1000)
        self.assertEqual(len(result["columns"]), 19)

    def test_external_entity_xml_is_rejected(self) -> None:
        payload = "<!DOCTYPE x [<!ENTITY e SYSTEM 'file:///etc/passwd'>]><x>&e;</x>"
        with self.assertRaises(ValueError):
            NormalizationRegistry().normalize(payload, "xml")


if __name__ == "__main__":
    unittest.main(verbosity=2)
