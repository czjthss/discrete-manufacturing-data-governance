import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from governance import INDICATORS
from governance.integration_registry import (
    AlgorithmSpec,
    IntegrationRegistry,
    ResearchReference,
    build_default_registry,
)
from governance.indicator_3_1 import SequenceRelationStore
from governance.indicator_3_2 import PiecewiseLinearCodec
from governance.indicator_3_3 import parse_records
from governance.indicator_3_8 import NormalizationRegistry
from governance.indicator_3_9 import assess
from app import GovernanceHandler, indicator_catalog, integration_catalog, reference_catalog


class IndicatorTests(unittest.TestCase):
    def test_all_benchmarks_pass(self):
        failures = {}
        for indicator_id, module in INDICATORS.items():
            result = module.benchmark()
            if not result["passed"]:
                failures[indicator_id] = result
        self.assertEqual(failures, {})

    def test_sequence_storage_round_trip(self):
        records = [{"timestamp_ms": 1, "equipment_id": "M1", "value": 42.0}]
        with tempfile.TemporaryDirectory() as directory:
            store = SequenceRelationStore(Path(directory))
            store.store_sequence("test", records)
            self.assertEqual(store.read_sequence("test"), records)

    def test_parser_accepts_json_and_csv(self):
        self.assertEqual(parse_records('[{"id": 1}]')["format"], "json")
        self.assertEqual(parse_records("id,value\n1,42")["format"], "csv")

    def test_piecewise_codec_handles_edge_cases(self):
        codec = PiecewiseLinearCodec()
        self.assertEqual(codec.decompress(codec.compress([]))[0], [])
        self.assertEqual(codec.decompress(codec.compress([42.0]))[0], [42.0])

    def test_piecewise_codec_preserves_error_bound(self):
        codec = PiecewiseLinearCodec()
        values = [40.0, 40.03, 40.07, 40.09, 40.12, 40.15]
        restored, tolerance = codec.decompress(codec.compress(values, tolerance=0.05))
        self.assertLessEqual(
            max(abs(source - target) for source, target in zip(values, restored)),
            tolerance + 1e-9,
        )

    def test_registry_is_extensible(self):
        registry = NormalizationRegistry()
        self.assertGreaterEqual(len(registry.adapters), 8)
        self.assertEqual(registry.normalize("id,value\n1,42", "csv")["records"][0]["id"], "1")

    def test_quality_has_more_than_five_dimensions(self):
        result = assess(
            [
                {"timestamp_ms": 1, "equipment_id": "M1", "value": 42.0},
                {"timestamp_ms": 2, "equipment_id": "M1", "value": 42.1},
            ]
        )
        self.assertGreaterEqual(len(result["dimensions"]), 6)

    def test_integration_registry_maps_every_indicator(self):
        payload = integration_catalog()
        self.assertEqual(len(payload["indicator_matrix"]), 9)
        self.assertEqual(payload["summary"]["active"], 9)
        self.assertEqual(payload["summary"]["planned"], 4)
        for row in payload["indicator_matrix"]:
            self.assertTrue(row["current_methods"], row["indicator"])

    def test_reference_api_metadata_is_auditable(self):
        payload = reference_catalog()
        reference_ids = {item["id"] for item in payload["items"]}
        self.assertEqual(
            reference_ids,
            {
                "compress-iotdb-pvldb-2025",
                "apache-tsfile",
                "tsquality-vldb-2023",
                "matchmaker-icml-2025",
            },
        )
        for item in payload["items"]:
            self.assertIn(item["license_status"], {"confirmed", "pending"})
            self.assertIn(item["commit_status"], {"pinned", "pending"})
            self.assertTrue(item["paper_url"].startswith("https://"))

    def test_indicator_api_includes_current_and_planned_methods(self):
        items = indicator_catalog()
        self.assertEqual([item["id"] for item in items], list(INDICATORS))
        for item in items:
            self.assertTrue(item["current_methods"])
            self.assertIn("planned_integrations", item)

    def test_registry_resolves_active_entrypoint_and_blocks_planned(self):
        registry = build_default_registry(discover_external=False)
        resolved = registry.resolve("builtin.error-bounded-pla")
        self.assertIs(resolved, PiecewiseLinearCodec)
        with self.assertRaises(RuntimeError):
            registry.resolve("planned.compress-iotdb")

    def test_external_manifest_can_register_reference_and_algorithm(self):
        manifest = {
            "references": [
                {
                    "id": "paper.example",
                    "title": "Example",
                    "venue": "Test 2026",
                    "year": 2026,
                    "paper_url": "https://example.org/paper",
                    "repository_url": None,
                    "indicator_ids": ["3.8"],
                    "concepts": ["schema matching"],
                }
            ],
            "algorithms": [
                {
                    "id": "planned.example",
                    "name": "Example Matcher",
                    "capability": "schema_matching",
                    "indicator_ids": ["3.8"],
                    "status": "planned",
                    "provider": "test",
                    "implementation_kind": "external",
                    "method": "test method",
                    "reference_ids": ["paper.example"],
                    "license": "待确认",
                    "license_status": "pending",
                    "commit_status": "pending",
                }
            ],
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "manifest.json"
            path.write_text(json.dumps(manifest), encoding="utf-8")
            registry = IntegrationRegistry()
            counts = registry.load_manifest(path)
        self.assertEqual(counts, {"references": 1, "algorithms": 1})
        self.assertIn("planned.example", registry.algorithms)

    def test_registry_rejects_unknown_indicator(self):
        registry = IntegrationRegistry()
        with self.assertRaises(ValueError):
            registry.register_reference(
                ResearchReference(
                    id="bad",
                    title="Bad",
                    venue="Test",
                    year=2026,
                    paper_url="https://example.org",
                    repository_url=None,
                    indicator_ids=("4.1",),
                    concepts=("invalid",),
                )
            )

    def test_bad_json_manifest_is_isolated_and_reported(self):
        with tempfile.TemporaryDirectory() as directory:
            manifest_dir = Path(directory) / "broken"
            manifest_dir.mkdir()
            (manifest_dir / "manifest.json").write_text("{bad json", encoding="utf-8")
            registry = build_default_registry(discover_external=False)
            loaded = registry.discover_manifests(Path(directory))
        self.assertEqual(loaded, [])
        self.assertEqual(len(registry.load_errors), 1)
        self.assertEqual(registry.load_errors[0]["error_type"], "JSONDecodeError")
        self.assertEqual(
            registry.integrations_payload()["summary"]["runnable"],
            9,
        )
        self.assertEqual(registry.integrations_payload()["summary"]["manifest_errors"], 1)

    def test_missing_manifest_fields_roll_back_the_whole_file(self):
        manifest = {
            "references": [
                {
                    "id": "paper.valid-before-rollback",
                    "title": "Valid Reference",
                    "venue": "Test 2026",
                    "year": 2026,
                    "paper_url": "https://example.org/paper",
                    "repository_url": None,
                    "indicator_ids": ["3.8"],
                    "concepts": ["schema matching"],
                }
            ],
            "algorithms": [{"id": "missing-required-fields"}],
        }
        with tempfile.TemporaryDirectory() as directory:
            manifest_dir = Path(directory) / "missing"
            manifest_dir.mkdir()
            (manifest_dir / "manifest.json").write_text(
                json.dumps(manifest),
                encoding="utf-8",
            )
            registry = IntegrationRegistry()
            registry.discover_manifests(Path(directory))
        self.assertEqual(len(registry.load_errors), 1)
        self.assertNotIn("paper.valid-before-rollback", registry.references)
        self.assertEqual(registry.algorithms, {})

    def test_external_active_algorithm_requires_confirmed_license_and_commit(self):
        registry = IntegrationRegistry()
        registry.register_reference(
            ResearchReference(
                id="paper.pending",
                title="Pending Paper",
                venue="Test 2026",
                year=2026,
                paper_url="https://example.org/paper",
                repository_url="https://github.com/example/project",
                indicator_ids=("3.4",),
                concepts=("schema matching",),
            )
        )
        with self.assertRaises(ValueError):
            registry.register_algorithm(
                AlgorithmSpec(
                    id="external.unsafe-active",
                    name="Unsafe Active",
                    capability="schema_matching",
                    indicator_ids=("3.4",),
                    status="active",
                    provider="external",
                    implementation_kind="external",
                    method="unsafe",
                    entrypoint="integrations.example.adapter:Matcher",
                    reference_ids=("paper.pending",),
                    license="待确认",
                    license_status="pending",
                    commit_sha=None,
                    commit_status="pending",
                )
            )

    def test_registry_rejects_entrypoint_outside_allowlist(self):
        registry = IntegrationRegistry()
        registry.register_reference(
            ResearchReference(
                id="paper.entrypoint",
                title="Entrypoint Paper",
                venue="Test 2026",
                year=2026,
                paper_url="https://example.org/paper",
                repository_url="https://github.com/example/project",
                indicator_ids=("3.8",),
                concepts=("schema matching",),
            )
        )
        with self.assertRaises(ValueError):
            registry.register_algorithm(
                AlgorithmSpec(
                    id="planned.invalid-entrypoint",
                    name="Invalid Entrypoint",
                    capability="schema_matching",
                    indicator_ids=("3.8",),
                    status="planned",
                    provider="external",
                    implementation_kind="external",
                    method="unsafe import",
                    entrypoint="os:system",
                    reference_ids=("paper.entrypoint",),
                    license="待确认",
                    license_status="pending",
                    commit_status="pending",
                )
            )

    def test_manifest_cannot_claim_builtin_algorithm_kind(self):
        manifest = {
            "references": [],
            "algorithms": [
                {
                    "id": "spoofed.builtin",
                    "name": "Spoofed Builtin",
                    "capability": "compression",
                    "indicator_ids": ["3.2"],
                    "status": "active",
                    "provider": "external",
                    "implementation_kind": "builtin",
                    "method": "bypass attempt",
                    "entrypoint": "governance.indicator_3_2:PiecewiseLinearCodec",
                    "reference_ids": [],
                    "license": "项目自有",
                    "license_status": "confirmed",
                    "commit_status": "local",
                }
            ],
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "manifest.json"
            path.write_text(json.dumps(manifest), encoding="utf-8")
            registry = IntegrationRegistry()
            with self.assertRaises(ValueError):
                registry.load_manifest(path)
        self.assertEqual(registry.algorithms, {})

    def test_empty_relation_table_can_be_stored(self):
        with tempfile.TemporaryDirectory() as directory:
            store = SequenceRelationStore(Path(directory))
            result = store.store_relations("empty_records", [])
            with sqlite3.connect(store.database_path) as connection:
                columns = connection.execute(
                    'PRAGMA table_info("empty_records")'
                ).fetchall()
                count = connection.execute(
                    'SELECT COUNT(*) FROM "empty_records"'
                ).fetchone()[0]
        self.assertTrue(result["empty"])
        self.assertEqual(result["records"], 0)
        self.assertEqual(result["columns"], [])
        self.assertEqual(result["storage_columns"], ["_empty"])
        self.assertEqual([column[1] for column in columns], ["_empty"])
        self.assertEqual(count, 0)

    def test_analyze_invalid_timestamp_returns_quality_failure_not_error(self):
        result = GovernanceHandler._analyze(
            {
                "format": "csv",
                "content": (
                    "timestamp_ms,equipment_id,value\n"
                    "not-a-time,CNC-01,42.1\n"
                    "1767225600001,CNC-01,42.2"
                ),
            }
        )
        self.assertEqual(result["source"]["records"], 2)
        self.assertLess(result["quality"]["dimensions"]["validity"], 100.0)
        self.assertLess(result["quality"]["dimensions"]["timeliness"], 100.0)

    def test_reference_schema_rejects_invalid_url_year_and_concepts(self):
        registry = IntegrationRegistry()
        invalid_items = (
            {"paper_url": "file:///tmp/paper.pdf"},
            {"year": "2026"},
            {"concepts": ("valid", 42)},
        )
        for overrides in invalid_items:
            values = {
                "id": f"bad-{len(registry.references)}-{len(str(overrides))}",
                "title": "Bad Reference",
                "venue": "Test",
                "year": 2026,
                "paper_url": "https://example.org/paper",
                "repository_url": None,
                "indicator_ids": ("3.8",),
                "concepts": ("schema",),
                **overrides,
            }
            with self.subTest(overrides=overrides), self.assertRaises(ValueError):
                registry.register_reference(ResearchReference(**values))


if __name__ == "__main__":
    unittest.main()
