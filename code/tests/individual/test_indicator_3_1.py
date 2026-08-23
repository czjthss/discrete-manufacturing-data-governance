"""Acceptance tests for indicator 3.1 storage and compression."""

from __future__ import annotations

import gzip
import tempfile
import unittest
from pathlib import Path

from _support import assert_benchmark_contract
from governance.indicator_3_1 import SequenceRelationStore, benchmark
from governance.public_benchmarks import load_metropt_rows, load_secom_records


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
        self.assertEqual(
            set(metrics["dataset_results"]),
            {"metropt3", "forda", "secom", "holoclean_hospital"},
        )
        for dataset, result in metrics["dataset_results"].items():
            with self.subTest(dataset=dataset):
                self.assertTrue(result["round_trip"])
                self.assertIsNot(result["backup_round_trip"], False)
                self.assertGreater(result["compression_ratio"], 1.0)
                self.assertGreater(result["raw_bytes"], result["stored_bytes"])
        reported_paths = [
            *self.result["artifacts"],
            metrics["dataset_results"]["metropt3"]["path"],
            metrics["dataset_results"]["forda"]["path"],
        ]
        for reported_path in reported_paths:
            with self.subTest(reported_path=reported_path):
                self.assertFalse(Path(reported_path).is_absolute())

    def test_sequence_and_relation_round_trip(self) -> None:
        metro = load_metropt_rows()[0]
        wafer = load_secom_records()[0]
        sequence = [{
            "timestamp_ms": metro["timestamp_ms"],
            "equipment_id": metro["equipment_id"],
            "value": metro["Motor_current"],
        }]
        relations = [{
            "wafer_id": wafer["wafer_id"],
            "label": wafer["label"],
            "timestamp": wafer["timestamp"],
        }]
        with tempfile.TemporaryDirectory() as directory:
            store = SequenceRelationStore(Path(directory))
            sequence_result = store.store_sequence("sensor", sequence)
            relation_result = store.store_relations("orders", relations)
            self.assertEqual(store.read_sequence("sensor"), sequence)
            self.assertEqual(
                store.read_relations("orders"),
                [{key: str(value) for key, value in relations[0].items()}],
            )
            backup = Path(relation_result["compressed_backup"])
            self.assertEqual(gzip.decompress(backup.read_bytes()), store.database_path.read_bytes())
            self.assertGreater(sequence_result["raw_bytes"], 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
