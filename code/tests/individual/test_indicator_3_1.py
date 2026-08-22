"""Acceptance tests for indicator 3.1 storage and compression."""

from __future__ import annotations

import gzip
import tempfile
import unittest
from pathlib import Path

from _support import assert_benchmark_contract
from governance.indicator_3_1 import SequenceRelationStore, benchmark


class Indicator31Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.result = benchmark()

    def test_benchmark_meets_storage_target(self) -> None:
        assert_benchmark_contract(self, self.result, "3.1")
        metrics = self.result["metrics"]
        self.assertTrue(metrics["sequence_round_trip"])
        self.assertTrue(metrics["relation_round_trip"])
        self.assertTrue(metrics["relation_backup_round_trip"])
        self.assertGreater(metrics["sequence_gzip_ratio"], 1.0)

    def test_sequence_and_relation_round_trip(self) -> None:
        sequence = [{"timestamp_ms": 1, "equipment_id": "CNC-01", "value": 42.5}]
        relations = [{'sensor"name': "temperature", "work_order": "WO-001"}]
        with tempfile.TemporaryDirectory() as directory:
            store = SequenceRelationStore(Path(directory))
            sequence_result = store.store_sequence("sensor", sequence)
            relation_result = store.store_relations("orders", relations)
            self.assertEqual(store.read_sequence("sensor"), sequence)
            self.assertEqual(
                store.read_relations("orders"),
                [{'sensor"name': "temperature", "work_order": "WO-001"}],
            )
            backup = Path(relation_result["compressed_backup"])
            self.assertEqual(gzip.decompress(backup.read_bytes()), store.database_path.read_bytes())
            self.assertGreater(sequence_result["raw_bytes"], 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
