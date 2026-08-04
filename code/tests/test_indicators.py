import json
import multiprocessing
import os
import sqlite3
import struct
import sys
import tempfile
import unittest
import zlib
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from governance import INDICATORS
import governance.common as common
import governance.indicator_3_3 as parser_module
from governance.common import (
    artifact_write_scope,
    bounded_zlib_decompress,
    prune_retained_artifacts,
)
from governance.integration_registry import (
    AlgorithmSpec,
    IntegrationRegistry,
    ResearchReference,
    build_default_registry,
)
from governance.indicator_3_1 import (
    STORAGE_RUN_COMPLETED_MARKER,
    SequenceRelationStore,
    mark_storage_run_completed,
    prune_storage_runs,
)
from governance.indicator_3_2 import PiecewiseLinearCodec, evaluate_adapter_round_trip
from governance.indicator_3_3 import parse_records
from governance.indicator_3_4 import align_records
from governance.indicator_3_5 import HighFrequencyBuffer
from governance.indicator_3_6 import evaluate_quality
from governance.indicator_3_8 import NormalizationRegistry
from governance.indicator_3_9 import assess
from governance.pipeline import govern_records
from integrations.group_research.adapter import (
    BosIntCodec,
    RegerFloatCodec,
    RegerIntCodec,
    Ts2DiffBosFloatCodec,
    Ts2DiffBosIntCodec,
)
from app import (
    GovernanceHandler,
    indicator_catalog,
    integration_catalog,
    reference_catalog,
    recent_report_paths,
    run_all,
)


def _multiprocess_retention_worker(
    report_root: str,
    storage_root: str,
    barrier,
    results,
    worker_id: int,
) -> None:
    try:
        common.REPORT_DIR = Path(report_root)
        report_path = common.write_json_report(
            f"runs/process-{worker_id}.json", {"worker": worker_id}
        )
        shared_storage = Path(storage_root)
        analysis_store = SequenceRelationStore(shared_storage)
        analysis = analysis_store.store_sequence(
            f"analysis-process-{worker_id}", [{"worker": worker_id}]
        )
        run_directory = shared_storage / "runs" / f"process-{worker_id}"
        run_store = SequenceRelationStore(run_directory)
        run_store.store_sequence("benchmark", [{"worker": worker_id}])

        barrier.wait(timeout=20)
        if worker_id == 0:
            prune_storage_runs(shared_storage / "runs")
        barrier.wait(timeout=20)

        readable_before_completion = run_store.read_sequence("benchmark") == [
            {"worker": worker_id}
        ]
        mark_storage_run_completed(run_directory)
        barrier.wait(timeout=20)

        prune_storage_runs(shared_storage / "runs")
        barrier.wait(timeout=20)
        report_payload = json.loads(report_path.read_text(encoding="utf-8"))
        analysis_payload = analysis_store.read_sequence(f"analysis-process-{worker_id}")
        run_payload = run_store.read_sequence("benchmark")
        results.put(
            {
                "worker": worker_id,
                "readable_before_completion": readable_before_completion,
                "report_ok": report_payload == {"worker": worker_id},
                "analysis_ok": analysis_payload == [{"worker": worker_id}],
                "run_ok": run_payload == [{"worker": worker_id}],
                "analysis_path": analysis["path"],
            }
        )
    except BaseException as exc:
        results.put({"worker": worker_id, "error": repr(exc)})


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

    def test_relation_storage_quotes_field_names(self):
        records = [{'sensor"name': "temperature", "value": 42}]
        with tempfile.TemporaryDirectory() as directory:
            store = SequenceRelationStore(Path(directory))
            store.store_relations("quoted", records)
            self.assertEqual(
                store.read_relations("quoted"),
                [{'sensor"name': "temperature", "value": "42"}],
            )
            with self.assertRaises(ValueError):
                store.store_relations("ambiguous", [{"Sensor": 1, "sensor": 2}])

    def test_parser_accepts_json_and_csv(self):
        self.assertEqual(parse_records('[{"id": 1}]')["format"], "json")
        self.assertEqual(parse_records("id,value\n1,42")["format"], "csv")
        with self.assertRaises(ValueError):
            parse_records("id,id\n1,2", "csv")
        with self.assertRaises(ValueError):
            parse_records("Sensor,sensor\n1,2", "csv")
        with self.assertRaises(ValueError):
            parse_records('{"records":[{"id":1},2]}', "json")
        with self.assertRaises(ValueError):
            parse_records('{"metadata":[,],"records":[{"id":1}]}', "json")

    def test_json_wrapper_priority_and_duplicate_keys_match_json_loads(self):
        preferred = parse_records(
            '{"records":[{"id":1}],"data":[2]}',
            "json",
        )
        self.assertEqual(preferred["records"], [{"id": 1}])

        duplicate = parse_records(
            '{"records":[{"id":1}],"records":[{"id":2}]}',
            "json",
        )
        self.assertEqual(duplicate["records"], [{"id": 2}])

        fallback = parse_records(
            '{"data":[{"id":3}],"records":[{"id":1}],"records":null}',
            "json",
        )
        self.assertEqual(fallback["records"], [{"id": 3}])

    def test_parser_rejects_columns_incrementally(self):
        payloads = {
            "json": ('[{"a":1},{"b":2},{"c":3}]', "json"),
            "jsonl": ('{"a":1}\n{"b":2}\n{"c":3}', "jsonl"),
            "csv": ("a,b,c\n", "csv"),
        }
        with patch.object(parser_module, "MAX_COLUMNS", 2):
            for name, (payload, declared_format) in payloads.items():
                with self.subTest(data_format=name), self.assertRaisesRegex(
                    ValueError, "字段数超过上限 2"
                ):
                    parse_records(payload, declared_format)

    def test_parser_handles_one_leading_bom_and_rejects_middle_bom(self):
        jsonl = parse_records('\ufeff{"id":1}\n{"id":2}')
        self.assertEqual(jsonl["format"], "jsonl")
        self.assertEqual(jsonl["records"], [{"id": 1}, {"id": 2}])

        csv_result = parse_records("\ufeffid,value\n1,42")
        self.assertEqual(csv_result["format"], "csv")
        self.assertEqual(csv_result["columns"], ["id", "value"])
        with self.assertRaisesRegex(ValueError, "BOM 只能出现在输入开头"):
            parse_records('{"id":1}\n\ufeff{"id":2}', "jsonl")
        with self.assertRaisesRegex(ValueError, "BOM 只能出现在输入开头"):
            parse_records("\ufeff\ufeffid,value\n1,42", "csv")

    def test_parser_rejects_each_format_at_max_records_plus_one(self):
        table_formats = {
            "csv": ",",
            "tsv": "\t",
            "semicolon": ";",
            "pipe": "|",
        }
        payloads = {
            data_format: "id{0}value\n".format(delimiter)
            + "\n".join(f"{index}{delimiter}{index}" for index in range(4))
            for data_format, delimiter in table_formats.items()
        }
        payloads.update(
            {
                "jsonl": "\n".join(json.dumps({"id": index}) for index in range(4)),
                "json": json.dumps([{"id": index} for index in range(4)]),
                "json-wrapper": json.dumps(
                    {
                        "metadata": "bounded",
                        "records": [{"id": index} for index in range(4)],
                    }
                ),
            }
        )
        with patch.object(parser_module, "MAX_RECORDS", 3):
            for name, payload in payloads.items():
                declared = "json" if name == "json-wrapper" else name
                with self.subTest(data_format=name), self.assertRaisesRegex(
                    ValueError, "记录数超过上限 3"
                ):
                    parse_records(payload, declared)

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

    def test_piecewise_codec_rejects_invalid_parameters_and_payloads(self):
        codec = PiecewiseLinearCodec()
        for values, tolerance in (([1.0], -1.0), ([float("nan")], 0.1)):
            with self.subTest(values=values, tolerance=tolerance), self.assertRaises(ValueError):
                codec.compress(values, tolerance)
        with self.assertRaises(ValueError):
            codec.decompress(b"not-zlib")
        with self.assertRaises(ValueError):
            bounded_zlib_decompress(zlib.compress(b"x" * 65), 64)

    def test_reger_decoder_rejects_oversized_declared_count(self):
        payload = struct.pack("<6sIHHHI", b"REGER3", 2_000_001, 1, 1, 1, 0)
        with self.assertRaises(ValueError):
            RegerIntCodec.decompress(payload)

    def test_group_compression_adapters_round_trip(self):
        integers = [index * index - 20 * index for index in range(800)]
        floats = [round(index / 17.0, 6) for index in range(800)]
        for codec in (RegerIntCodec, BosIntCodec, Ts2DiffBosIntCodec):
            with self.subTest(codec=codec.__name__):
                self.assertEqual(codec.decompress(codec.compress(integers)), integers)
        self.assertEqual(
            RegerFloatCodec.decompress(RegerFloatCodec.compress(floats)), floats
        )
        restored = Ts2DiffBosFloatCodec.decompress(
            Ts2DiffBosFloatCodec.compress(floats)
        )
        self.assertLessEqual(
            max(abs(left - right) for left, right in zip(floats, restored)),
            0.0000005,
        )

    def test_float_adapter_rejects_correct_prefix_with_short_output(self):
        class PrefixOnlyFloatCodec:
            @staticmethod
            def compress(source):
                return json.dumps(source).encode("utf-8")

            @staticmethod
            def decompress(payload):
                return json.loads(payload.decode("utf-8"))[:-1]

        result = evaluate_adapter_round_trip(PrefixOnlyFloatCodec, [1.0, 2.0, 3.0])
        self.assertFalse(result["sample_count_matches"])
        self.assertFalse(result["round_trip_ok"])
        self.assertIsNone(result["max_absolute_error"])

    def test_registry_is_extensible(self):
        registry = NormalizationRegistry()
        self.assertGreaterEqual(len(registry.adapters), 8)
        self.assertEqual(registry.normalize("id,value\n1,42", "csv")["records"][0]["id"], "1")

    def test_high_frequency_buffer_limits_batch_resources(self):
        buffer = HighFrequencyBuffer(capacity=10, max_batch_size=2)
        self.assertEqual(buffer.ingest_batch([{"id": 1}, {"id": 2}]), 2)
        with self.assertRaises(ValueError):
            buffer.ingest_batch([{"id": 1}, {"id": 2}, {"id": 3}])
        with self.assertRaises(ValueError):
            buffer.snapshot(1.5)

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
        self.assertEqual(payload["summary"]["active"], 17)
        self.assertEqual(payload["summary"]["planned"], 4)
        self.assertEqual(payload["summary"]["runtime_available"], 17)
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
        with patch.object(
            sys.modules["app"].INTEGRATION_REGISTRY,
            "integrations_payload",
            wraps=sys.modules["app"].INTEGRATION_REGISTRY.integrations_payload,
        ) as payload_builder:
            items = indicator_catalog()
        self.assertEqual(payload_builder.call_count, 1)
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
            17,
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
            with closing(sqlite3.connect(store.database_path)) as connection:
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

    def test_report_and_sequence_retention_in_temporary_directories(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(
            common, "REPORT_DIR", Path(directory) / "reports"
        ), patch.dict(
            os.environ,
            {
                "DGOV_RETENTION_RUN_REPORTS": "2",
                "DGOV_RETENTION_GOVERNANCE_REPORTS": "3",
                "DGOV_RETENTION_ANALYSIS_SEQUENCES": "2",
                "DGOV_RETENTION_STORAGE_RUNS": "2",
                "DGOV_RETENTION_GRACE_SECONDS": "0",
            },
        ):
            for index in range(5):
                common.write_json_report(f"runs/run-{index}.json", {"index": index})
                common.write_json_report(
                    f"governance/governance-{index}.json", {"index": index}
                )
            self.assertEqual(
                len(list((common.REPORT_DIR / "runs").glob("*.json"))), 2
            )
            self.assertEqual(
                len(list((common.REPORT_DIR / "governance").glob("*.json"))), 3
            )

            storage_root = Path(directory) / "storage"
            store = SequenceRelationStore(storage_root)
            for index in range(5):
                store.store_sequence(f"analysis-{index}", [{"id": index}])
            self.assertEqual(
                len(list(storage_root.glob("analysis-*.sequence.json.gz"))), 2
            )

            runs_root = storage_root / "runs"
            for index in range(5):
                run_directory = runs_root / f"storage-{index}"
                run_directory.mkdir(parents=True)
                mark_storage_run_completed(run_directory)
            prune_storage_runs(runs_root)
            self.assertEqual(len([path for path in runs_root.iterdir() if path.is_dir()]), 2)

    def test_retention_protects_active_artifact_and_recent_report_selection_is_bounded(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            active = root / "active"
            active.mkdir()
            for index in range(4):
                path = root / f"old-{index}"
                path.mkdir()
            with artifact_write_scope(active):
                prune_retained_artifacts(root, limit=1, directories=True)
                self.assertTrue(active.exists())

            report_root = root / "reports"
            report_root.mkdir()
            for index in range(5):
                (report_root / f"report-{index}.json").write_text(
                    json.dumps({"index": index}), encoding="utf-8"
                )
            self.assertEqual(len(recent_report_paths(report_root, limit=2)), 2)

    def test_retention_is_safe_across_processes(self):
        if "fork" not in multiprocessing.get_all_start_methods():
            self.skipTest("跨进程保留测试需要 fork")
        context = multiprocessing.get_context("fork")
        with tempfile.TemporaryDirectory() as directory, patch.dict(
            os.environ,
            {
                "DGOV_RETENTION_RUN_REPORTS": "1",
                "DGOV_RETENTION_ANALYSIS_SEQUENCES": "1",
                "DGOV_RETENTION_STORAGE_RUNS": "1",
                "DGOV_RETENTION_GRACE_SECONDS": "60",
            },
        ):
            root = Path(directory)
            report_root = root / "reports"
            report_runs = report_root / "runs"
            storage_root = root / "storage"
            storage_runs = storage_root / "runs"
            report_runs.mkdir(parents=True)
            storage_runs.mkdir(parents=True)
            incomplete_old_run = storage_runs / "incomplete-old"
            incomplete_old_run.mkdir()
            os.utime(incomplete_old_run, (1, 1))

            for index in range(4):
                old_report = report_runs / f"old-{index}.json"
                old_report.write_text("{}", encoding="utf-8")
                os.utime(old_report, (1, 1))
                old_analysis = storage_root / f"analysis-old-{index}.sequence.json.gz"
                old_analysis.write_bytes(b"old")
                os.utime(old_analysis, (1, 1))
                old_run = storage_runs / f"old-{index}"
                old_run.mkdir()
                marker = old_run / STORAGE_RUN_COMPLETED_MARKER
                marker.write_text("completed", encoding="utf-8")
                os.utime(marker, (1, 1))

            barrier = context.Barrier(3)
            results = context.Queue()
            processes = [
                context.Process(
                    target=_multiprocess_retention_worker,
                    args=(
                        str(report_root),
                        str(storage_root),
                        barrier,
                        results,
                        worker_id,
                    ),
                )
                for worker_id in range(3)
            ]
            for process in processes:
                process.start()
            for process in processes:
                process.join(timeout=30)
                if process.is_alive():
                    process.terminate()
                    process.join(timeout=5)
                    self.fail("跨进程保留测试超时")
                self.assertEqual(process.exitcode, 0)

            payloads = [results.get(timeout=5) for _ in processes]
            results.close()
            results.join_thread()
            self.assertFalse([item for item in payloads if "error" in item], payloads)
            for payload in payloads:
                self.assertTrue(payload["readable_before_completion"])
                self.assertTrue(payload["report_ok"])
                self.assertTrue(payload["analysis_ok"])
                self.assertTrue(payload["run_ok"])
                self.assertTrue(Path(payload["analysis_path"]).is_file())
            self.assertLessEqual(len(list(report_runs.glob("old-*.json"))), 1)
            self.assertLessEqual(
                len(list(storage_root.glob("analysis-old-*.sequence.json.gz"))), 1
            )
            self.assertLessEqual(
                len([path for path in storage_runs.glob("old-*") if path.is_dir()]), 1
            )
            self.assertTrue(incomplete_old_run.is_dir())

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
        self.assertLess(result["quality_before"]["dimensions"]["validity"], 100.0)
        self.assertEqual(result["quality"]["dimensions"]["validity"], 100.0)
        self.assertLess(result["quality"]["dimensions"]["timeliness"], 100.0)
        self.assertEqual(result["governance"]["quarantined_records"], 1)

    def test_scalar_jsonl_and_top_level_payload_are_rejected(self):
        with self.assertRaises(ValueError):
            parse_records('{}\n[]', "jsonl")
        with self.assertRaises(ValueError):
            GovernanceHandler._analyze([])
        with self.assertRaises(ValueError):
            GovernanceHandler._analyze({"content": [1, 2], "format": "json"})

    def test_timeliness_uses_explicit_current_time(self):
        records = [
            {"timestamp_ms": 1, "equipment_id": "CNC-01", "value": 1},
            {"timestamp_ms": 2, "equipment_id": "CNC-01", "value": 2},
        ]
        quality = evaluate_quality(records, reference_time_ms=1_000_000)
        self.assertEqual(quality["timeliness"], 0.0)

    def test_alignment_prefers_narrow_window_and_handles_invalid_time(self):
        relations = [
            {
                "equipment_id": "CNC-01",
                "start_ms": 0,
                "end_ms": 1000,
                "work_order": "broad",
            },
            {
                "equipment_id": "CNC-01",
                "start_ms": 495,
                "end_ms": 505,
                "work_order": "precise",
            },
        ]
        results = align_records(
            [
                {"machine_id": "CNC-01", "ts": 500},
                {"machine_id": "CNC-01", "ts": "bad"},
            ],
            relations,
        )
        self.assertEqual(results[0]["relation"]["work_order"], "precise")
        self.assertFalse(results[1]["aligned"])
        self.assertIn("时间戳", results[1]["alignment_reason"])

    def test_pipeline_repairs_quarantines_and_records_lineage(self):
        records = [
            {"machine_id": " cnc-01 ", "ts": "1767225600000", "reading": "42.1"},
            {"machine_id": "CNC-01", "ts": "bad", "reading": "42.2"},
            {"machine_id": " cnc-01 ", "ts": "1767225600000", "reading": "42.1"},
        ]
        result = govern_records(records, reference_time_ms=1_767_225_700_000)
        self.assertEqual(result["summary"]["accepted_records"], 1)
        self.assertEqual(result["summary"]["quarantined_records"], 2)
        self.assertEqual(len(result["lineage"]), 3)
        self.assertTrue(result["lineage"][0]["actions"])

    def test_parallel_reports_are_independent_and_parseable(self):
        with ThreadPoolExecutor(max_workers=12) as executor:
            reports = list(executor.map(lambda _: run_all(), range(24)))
        self.assertTrue(all(report["passed"] for report in reports))
        paths = [Path(report["run_report_path"]) for report in reports]
        self.assertEqual(len(set(paths)), 24)
        for path in paths:
            payload = json.loads(path.read_text(encoding="utf-8"))
            self.assertTrue(payload["passed"])

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
