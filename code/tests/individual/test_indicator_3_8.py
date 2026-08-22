"""Acceptance tests for indicator 3.8 normalization adapters."""

from __future__ import annotations

import unittest

from _support import assert_benchmark_contract
from governance.indicator_3_8 import Adapter, NormalizationRegistry, benchmark


class Indicator38Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.result = benchmark()

    def test_benchmark_covers_all_registered_formats(self) -> None:
        assert_benchmark_contract(self, self.result, "3.8")
        metrics = self.result["metrics"]
        self.assertEqual(metrics["tested_formats"], 8)
        self.assertEqual(len(metrics["passed_formats"]), 8)
        self.assertEqual(metrics["failed_formats"], {})
        self.assertEqual(metrics["rejected_invalid_fixtures"], metrics["invalid_fixtures"])

    def test_xml_ini_and_custom_adapter_normalize_to_common_shape(self) -> None:
        registry = NormalizationRegistry()
        xml = registry.normalize("<records><record><id>1</id></record></records>", "xml")
        ini = registry.normalize("[sensor]\nid=1", "ini")
        registry.register(Adapter("fixed", (".fixed",), lambda text: [{"payload": text}]))
        custom = registry.normalize("abc", "fixed")
        for result in (xml, ini, custom):
            self.assertTrue(result["normalized"])
            self.assertTrue(result["records"])
            self.assertTrue(result["columns"])

    def test_external_entity_xml_is_rejected(self) -> None:
        payload = "<!DOCTYPE x [<!ENTITY e SYSTEM 'file:///etc/passwd'>]><x>&e;</x>"
        with self.assertRaises(ValueError):
            NormalizationRegistry().normalize(payload, "xml")


if __name__ == "__main__":
    unittest.main(verbosity=2)
