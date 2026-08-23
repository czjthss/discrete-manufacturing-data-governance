"""Registry for built-in algorithms and future paper/code integrations."""

from __future__ import annotations

import importlib
import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse

from .common import ROOT


VALID_INDICATORS = tuple(f"3.{index}" for index in range(1, 10))
VALID_STATUSES = {"active", "planned", "blocked", "disabled"}
VALID_INTEGRATION_STATUSES = {"active", "planned", "blocked", "adopted"}
VALID_LICENSE_STATUSES = {"confirmed", "pending", "rejected"}
VALID_COMMIT_STATUSES = {"local", "pinned", "pending"}
VALID_IMPLEMENTATION_KINDS = {"builtin", "external"}
GIT_SHA_PATTERN = re.compile(r"^[0-9a-fA-F]{7,64}$")
ENTRYPOINT_PATTERN = re.compile(
    r"^(?:governance(?:\.[A-Za-z_][A-Za-z0-9_]*)+"
    r"|integrations(?:\.[A-Za-z_][A-Za-z0-9_]*)+\.adapter)"
    r":[A-Za-z_][A-Za-z0-9_]*$"
)


@dataclass(frozen=True)
class ResearchReference:
    id: str
    title: str
    venue: str
    year: int
    paper_url: str
    repository_url: str | None
    indicator_ids: tuple[str, ...]
    concepts: tuple[str, ...]
    integration_status: str = "planned"
    code_license: str = "待确认"
    license_status: str = "pending"
    commit_sha: str | None = None
    commit_status: str = "pending"
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class AlgorithmSpec:
    id: str
    name: str
    capability: str
    indicator_ids: tuple[str, ...]
    status: str
    provider: str
    implementation_kind: str
    method: str
    entrypoint: str | None = None
    reference_ids: tuple[str, ...] = ()
    interface_contract: str = ""
    license: str = "项目自有"
    license_status: str = "confirmed"
    commit_sha: str | None = None
    commit_status: str = "local"
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["runnable"] = is_algorithm_runnable(self)
        runtime_available, runtime_error = probe_algorithm_runtime(self)
        payload["runtime_available"] = runtime_available
        payload["runtime_error"] = runtime_error
        return payload


def is_algorithm_runnable(algorithm: AlgorithmSpec) -> bool:
    if (
        algorithm.status != "active"
        or not algorithm.entrypoint
        or not ENTRYPOINT_PATTERN.fullmatch(algorithm.entrypoint)
    ):
        return False
    if algorithm.implementation_kind == "external":
        return bool(
            algorithm.license_status == "confirmed"
            and algorithm.commit_status == "pinned"
            and algorithm.commit_sha
            and GIT_SHA_PATTERN.fullmatch(algorithm.commit_sha)
        )
    return algorithm.implementation_kind == "builtin"


def probe_algorithm_runtime(algorithm: AlgorithmSpec) -> tuple[bool, str | None]:
    if not is_algorithm_runnable(algorithm):
        return False, "算法未启用或发布条件未满足"
    try:
        module_name, _, attribute_name = algorithm.entrypoint.partition(":")
        resolved = getattr(importlib.import_module(module_name), attribute_name)
        if not callable(resolved):
            return False, "入口对象不可调用"
        healthcheck = getattr(resolved, "healthcheck", None)
        if callable(healthcheck) and healthcheck() is not True:
            return False, "入口自检未通过"
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}"
    return True, None


class IntegrationRegistry:
    """Tracks implementations without importing optional third-party packages."""

    def __init__(self) -> None:
        self.references: dict[str, ResearchReference] = {}
        self.algorithms: dict[str, AlgorithmSpec] = {}
        self.load_errors: list[dict[str, str]] = []
        self.loaded_manifests: list[dict[str, Any]] = []

    def register_reference(self, reference: ResearchReference) -> None:
        self._validate_reference(reference)
        self._validate_indicators(reference.indicator_ids)
        if reference.id in self.references:
            raise ValueError(f"引用 ID 重复: {reference.id}")
        self.references[reference.id] = reference

    def register_algorithm(self, algorithm: AlgorithmSpec) -> None:
        self._validate_algorithm(algorithm)
        self._validate_indicators(algorithm.indicator_ids)
        if algorithm.id in self.algorithms:
            raise ValueError(f"算法 ID 重复: {algorithm.id}")
        missing = [
            reference_id
            for reference_id in algorithm.reference_ids
            if reference_id not in self.references
        ]
        if missing:
            raise ValueError(f"算法引用尚未注册: {', '.join(missing)}")
        if algorithm.implementation_kind == "external" and algorithm.status == "active":
            if not is_algorithm_runnable(algorithm):
                raise ValueError(
                    "外部 active 算法必须确认许可证、固定 commit SHA，"
                    "并配置允许命名空间内的 entrypoint"
                )
            approved_repositories = [
                self.references[reference_id]
                for reference_id in algorithm.reference_ids
                if (
                    self.references[reference_id].repository_url
                    and self.references[reference_id].license_status == "confirmed"
                    and self.references[reference_id].commit_status == "pinned"
                    and self.references[reference_id].commit_sha
                    == algorithm.commit_sha
                )
            ]
            if not approved_repositories:
                raise ValueError(
                    "外部 active 算法必须关联已确认许可证且固定同一 commit 的仓库引用"
                )
        self.algorithms[algorithm.id] = algorithm

    def load_manifest(self, path: Path) -> dict[str, int]:
        """Load a declarative integration manifest without importing its code."""
        original_references = dict(self.references)
        original_algorithms = dict(self.algorithms)
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict):
                raise ValueError("manifest 顶层必须是 JSON 对象")
            references = payload.get("references", [])
            algorithms = payload.get("algorithms", [])
            if not isinstance(references, list) or not isinstance(algorithms, list):
                raise ValueError("references 和 algorithms 必须是数组")
            counts = {"references": 0, "algorithms": 0}
            for item in references:
                if not isinstance(item, dict):
                    raise ValueError("reference 条目必须是对象")
                self.register_reference(
                    ResearchReference(
                        **self._tuple_fields(
                            item,
                            {"indicator_ids", "concepts"},
                        )
                    )
                )
                counts["references"] += 1
            for item in algorithms:
                if not isinstance(item, dict):
                    raise ValueError("algorithm 条目必须是对象")
                algorithm = AlgorithmSpec(
                    **self._tuple_fields(
                        item,
                        {"indicator_ids", "reference_ids"},
                    )
                )
                if algorithm.implementation_kind != "external":
                    raise ValueError(
                        "外部 manifest 只能注册 implementation_kind=external 的算法"
                    )
                self.register_algorithm(
                    algorithm
                )
                counts["algorithms"] += 1
            return counts
        except Exception:
            self.references = original_references
            self.algorithms = original_algorithms
            raise

    def discover_manifests(self, root: Path | None = None) -> list[dict[str, Any]]:
        integration_root = root or ROOT / "integrations"
        loaded = []
        for path in sorted(integration_root.glob("*/manifest.json")):
            try:
                counts = self.load_manifest(path)
            except Exception as exc:
                self.load_errors.append(
                    {
                        "path": str(path),
                        "error_type": type(exc).__name__,
                        "message": str(exc),
                    }
                )
                continue
            loaded.append({"path": str(path), **counts})
        self.loaded_manifests.extend(loaded)
        return loaded

    def resolve(self, algorithm_id: str) -> Callable[..., Any] | type:
        """Resolve an active entrypoint only when the implementation is available."""
        if algorithm_id == "builtin.error-bounded-pla":
            module = importlib.import_module("governance.indicator_3_2")
            return getattr(module, "PiecewiseLinearCodec")
        if algorithm_id not in self.algorithms:
            raise KeyError(f"未知算法: {algorithm_id}")
        algorithm = self.algorithms[algorithm_id]
        if not is_algorithm_runnable(algorithm):
            raise RuntimeError(f"算法尚不可运行: {algorithm_id}")
        module_name, separator, attribute_name = algorithm.entrypoint.partition(":")
        if not separator or not module_name or not attribute_name:
            raise ValueError(f"无效入口格式: {algorithm.entrypoint}")
        module = importlib.import_module(module_name)
        resolved = getattr(module, attribute_name)
        if not callable(resolved):
            raise RuntimeError(f"算法入口不可调用: {algorithm_id}")
        return resolved

    def references_payload(self) -> dict[str, Any]:
        items = [reference.to_dict() for reference in self.references.values()]
        return {
            "summary": {
                "total": len(items),
                "planned": sum(item["integration_status"] == "planned" for item in items),
                "license_confirmed": sum(
                    item["license_status"] == "confirmed" for item in items
                ),
                "commit_pending": sum(
                    item["commit_status"] == "pending" for item in items
                ),
            },
            "items": items,
            "load_errors": list(self.load_errors),
        }

    def integrations_payload(self) -> dict[str, Any]:
        algorithms = [algorithm.to_dict() for algorithm in self.algorithms.values()]
        matrix = []
        for indicator_id in VALID_INDICATORS:
            current = [
                item
                for item in algorithms
                if indicator_id in item["indicator_ids"] and item["status"] == "active"
            ]
            planned = [
                item
                for item in algorithms
                if indicator_id in item["indicator_ids"] and item["status"] == "planned"
            ]
            matrix.append(
                {
                    "indicator": indicator_id,
                    "current_methods": current,
                    "planned_integrations": planned,
                }
            )
        return {
            "summary": {
                "total": len(algorithms),
                "active": sum(item["status"] == "active" for item in algorithms),
                "planned": sum(item["status"] == "planned" for item in algorithms),
                "runnable": sum(item["runnable"] for item in algorithms),
                "runtime_available": sum(
                    item["runtime_available"] for item in algorithms
                ),
                "manifest_errors": len(self.load_errors),
            },
            "algorithms": algorithms,
            "indicator_matrix": matrix,
            "loaded_manifests": list(self.loaded_manifests),
            "load_errors": list(self.load_errors),
        }

    def indicator_profile(self, indicator_id: str) -> dict[str, Any]:
        if indicator_id not in VALID_INDICATORS:
            raise KeyError(f"未知指标: {indicator_id}")
        payload = self.integrations_payload()
        return next(
            item for item in payload["indicator_matrix"] if item["indicator"] == indicator_id
        )

    @staticmethod
    def _validate_indicators(indicator_ids: tuple[str, ...]) -> None:
        if not isinstance(indicator_ids, tuple) or not indicator_ids:
            raise ValueError("indicator_ids 必须是非空数组")
        if not all(isinstance(item, str) for item in indicator_ids):
            raise ValueError("indicator_ids 只能包含字符串")
        invalid = [item for item in indicator_ids if item not in VALID_INDICATORS]
        if invalid:
            raise ValueError(f"无效指标编号: {', '.join(invalid)}")

    @classmethod
    def _validate_reference(cls, reference: ResearchReference) -> None:
        cls._require_text(reference.id, "reference.id")
        cls._require_text(reference.title, "reference.title")
        cls._require_text(reference.venue, "reference.venue")
        if (
            not isinstance(reference.year, int)
            or isinstance(reference.year, bool)
            or not 1900 <= reference.year <= 2100
        ):
            raise ValueError("reference.year 必须是 1900-2100 的整数")
        cls._validate_url(reference.paper_url, "reference.paper_url")
        if reference.repository_url is not None:
            cls._validate_url(reference.repository_url, "reference.repository_url")
        if (
            not isinstance(reference.concepts, tuple)
            or not reference.concepts
            or not all(isinstance(item, str) and item.strip() for item in reference.concepts)
        ):
            raise ValueError("reference.concepts 必须是非空字符串数组")
        if reference.integration_status not in VALID_INTEGRATION_STATUSES:
            raise ValueError(
                f"无效 reference.integration_status: {reference.integration_status}"
            )
        cls._validate_release_state(
            license_status=reference.license_status,
            commit_status=reference.commit_status,
            commit_sha=reference.commit_sha,
            field_prefix="reference",
        )
        if reference.license_status == "confirmed":
            if not reference.repository_url:
                raise ValueError("已确认代码许可证的引用必须提供 repository_url")
            if not reference.code_license.strip() or "待确认" in reference.code_license:
                raise ValueError("license_status=confirmed 时必须提供明确代码许可证")
        if not reference.repository_url and (
            reference.commit_status != "pending" or reference.commit_sha
        ):
            raise ValueError("无 repository_url 的引用不能标记固定 commit")

    @classmethod
    def _validate_algorithm(cls, algorithm: AlgorithmSpec) -> None:
        for value, field_name in (
            (algorithm.id, "algorithm.id"),
            (algorithm.name, "algorithm.name"),
            (algorithm.capability, "algorithm.capability"),
            (algorithm.provider, "algorithm.provider"),
            (algorithm.method, "algorithm.method"),
        ):
            cls._require_text(value, field_name)
        if algorithm.status not in VALID_STATUSES:
            raise ValueError(f"无效 algorithm.status: {algorithm.status}")
        if algorithm.implementation_kind not in VALID_IMPLEMENTATION_KINDS:
            raise ValueError(
                f"无效 algorithm.implementation_kind: {algorithm.implementation_kind}"
            )
        if not isinstance(algorithm.reference_ids, tuple) or not all(
            isinstance(item, str) and item.strip() for item in algorithm.reference_ids
        ):
            raise ValueError("algorithm.reference_ids 必须是字符串数组")
        if not isinstance(algorithm.metadata, dict):
            raise ValueError("algorithm.metadata 必须是对象")
        if algorithm.entrypoint is not None:
            if (
                not isinstance(algorithm.entrypoint, str)
                or not ENTRYPOINT_PATTERN.fullmatch(algorithm.entrypoint)
            ):
                raise ValueError(
                    "entrypoint 仅允许 governance.*:Name 或 "
                    "integrations.*.adapter:Name"
                )
        cls._validate_release_state(
            license_status=algorithm.license_status,
            commit_status=algorithm.commit_status,
            commit_sha=algorithm.commit_sha,
            field_prefix="algorithm",
        )
        if algorithm.license_status == "confirmed":
            if not algorithm.license.strip() or "待确认" in algorithm.license:
                raise ValueError("license_status=confirmed 时必须提供明确算法许可证")
        if algorithm.implementation_kind == "external":
            if algorithm.commit_status == "local":
                raise ValueError("外部算法不能使用 commit_status=local")
            if not algorithm.reference_ids:
                raise ValueError("外部算法必须关联至少一个 reference_id")

    @staticmethod
    def _validate_release_state(
        *,
        license_status: str,
        commit_status: str,
        commit_sha: str | None,
        field_prefix: str,
    ) -> None:
        if license_status not in VALID_LICENSE_STATUSES:
            raise ValueError(f"无效 {field_prefix}.license_status: {license_status}")
        if commit_status not in VALID_COMMIT_STATUSES:
            raise ValueError(f"无效 {field_prefix}.commit_status: {commit_status}")
        if commit_status == "pinned":
            if not isinstance(commit_sha, str) or not GIT_SHA_PATTERN.fullmatch(commit_sha):
                raise ValueError(
                    f"{field_prefix}.commit_status=pinned 时必须提供有效 commit_sha"
                )
        elif commit_sha is not None:
            raise ValueError(
                f"{field_prefix}.commit_sha 仅能在 commit_status=pinned 时填写"
            )

    @staticmethod
    def _validate_url(url: str, field_name: str) -> None:
        if not isinstance(url, str):
            raise ValueError(f"{field_name} 必须是 URL 字符串")
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError(f"{field_name} 必须使用 http/https 且包含主机名")

    @staticmethod
    def _require_text(value: Any, field_name: str) -> None:
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{field_name} 必须是非空字符串")

    @staticmethod
    def _tuple_fields(
        item: dict[str, Any],
        field_names: set[str],
    ) -> dict[str, Any]:
        normalized = dict(item)
        for field_name in field_names:
            if field_name in normalized:
                if not isinstance(normalized[field_name], (list, tuple)):
                    raise ValueError(f"{field_name} 必须是数组")
                normalized[field_name] = tuple(normalized[field_name])
        return normalized


def _reference_catalog() -> tuple[ResearchReference, ...]:
    return (
        ResearchReference(
            id="compress-iotdb-pvldb-2025",
            title="Improving Time Series Data Compression in Apache IoTDB",
            venue="PVLDB 2025",
            year=2025,
            paper_url="https://www.vldb.org/pvldb/vol18/p3406-tang.pdf",
            repository_url="https://github.com/yuxin370/CompressIoTDB",
            indicator_ids=("3.1", "3.2", "3.7"),
            concepts=(
                "压缩态查询",
                "CompColumn",
                "late decompression",
                "动态辅助结构",
            ),
            code_license="待仓库接入时确认",
            integration_status="adopted",
            notes="已实现项目自有压缩态过滤适配器；官方仓库代码仍待许可证和 commit 确认。",
        ),
        ResearchReference(
            id="apache-tsfile",
            title="Apache TsFile / Apache IoTDB",
            venue="Apache Software Foundation",
            year=2026,
            paper_url="https://tsfile.apache.org/",
            repository_url="https://github.com/apache/tsfile",
            indicator_ids=("3.1", "3.2", "3.5"),
            concepts=("工业时序列式存储", "GORILLA", "LZ4", "设备/时间索引"),
            code_license="Apache-2.0",
            license_status="confirmed",
            notes="计划增加可选 TsFile 适配器，首版仍保持纯标准库可运行。",
        ),
        ResearchReference(
            id="tsquality-vldb-2023",
            title="TsQuality: Measuring Time Series Data Quality in Apache IoTDB",
            venue="VLDB 2023",
            year=2023,
            paper_url="https://www.vldb.org/pvldb/vol16/p3982-song.pdf",
            repository_url="https://thssdb.github.io/TsQuality/",
            indicator_ids=("3.6", "3.9"),
            concepts=("completeness", "consistency", "timeliness", "validity"),
            code_license="待源码接入时确认",
            integration_status="adopted",
            notes="已实现项目自有窗口化四维质量适配器；未复制论文附属源码。",
        ),
        ResearchReference(
            id="matchmaker-icml-2025",
            title=(
                "Bootstrapping Self-Improvement of Language Model Programs "
                "for Zero-Shot Schema Matching"
            ),
            venue="ICML 2025",
            year=2025,
            paper_url="https://openreview.net/forum?id=clLERWKNja",
            repository_url=None,
            indicator_ids=("3.4", "3.8"),
            concepts=("候选生成", "匹配精炼", "置信度评分", "零样本自改进"),
            code_license="未发现已确认的官方代码许可证",
            integration_status="adopted",
            notes="已实现项目自有候选生成、精炼和置信度适配器；官方代码仍待确认。",
        ),
    )


def _algorithm_catalog() -> tuple[AlgorithmSpec, ...]:
    return (
        AlgorithmSpec(
            id="builtin.sequence-relation-store",
            name="序列/关系双存储",
            capability="storage",
            indicator_ids=("3.1",),
            status="active",
            provider="本项目",
            implementation_kind="builtin",
            method="JSON+Gzip 序列存储、SQLite 关系存储及压缩备份",
            entrypoint="governance.indicator_3_1:SequenceRelationStore",
            reference_ids=("apache-tsfile",),
            interface_contract="store_sequence/read_sequence/store_relations",
        ),
        AlgorithmSpec(
            id="builtin.full-dataset-timeseries-codec",
            name="完整数据时序压缩",
            capability="compression",
            indicator_ids=("3.2",),
            status="active",
            provider="本项目",
            implementation_kind="builtin",
            method="模拟量误差有界量化差分、数字量无损编码与 zlib 熵压缩",
            entrypoint="governance.indicator_3_2:QuantizedDeltaCodec",
            reference_ids=("compress-iotdb-pvldb-2025", "apache-tsfile"),
            interface_contract="compress(values, tolerance)/decompress(payload)",
        ),
        AlgorithmSpec(
            id="group.reger-int64",
            name="REGER Int64 时序压缩",
            capability="compression",
            indicator_ids=("3.2",),
            status="active",
            provider="已有成果",
            implementation_kind="builtin",
            method="分块重排、残差建模、分段位宽编码与原始顺序恢复",
            entrypoint="integrations.group_research.adapter:RegerIntCodec",
            interface_contract="compress(values)/decompress(payload)",
            metadata={"source": "reger_bos_code_paths", "numeric_type": "int64"},
        ),
        AlgorithmSpec(
            id="group.reger-float64",
            name="REGER Float64 时序压缩",
            capability="compression",
            indicator_ids=("3.2",),
            status="active",
            provider="已有成果",
            implementation_kind="builtin",
            method="浮点位模式映射、分块重排和残差编码",
            entrypoint="integrations.group_research.adapter:RegerFloatCodec",
            interface_contract="compress(values)/decompress(payload)",
            metadata={"source": "reger_bos_code_paths", "numeric_type": "float64"},
        ),
        AlgorithmSpec(
            id="group.bos-int64",
            name="BOS Int64 时序压缩",
            capability="compression",
            indicator_ids=("3.2",),
            status="active",
            provider="已有成果",
            implementation_kind="builtin",
            method="分块差分、ZigZag 变换、变长整数编码和块级压缩",
            entrypoint="integrations.group_research.adapter:BosIntCodec",
            interface_contract="compress(values, block_size)/decompress(payload)",
            metadata={"source": "reger_bos_code_paths", "numeric_type": "int64"},
        ),
        AlgorithmSpec(
            id="group.ts2diff-bos-int64",
            name="TS_2DIFF+BOS 自适应压缩",
            capability="compression",
            indicator_ids=("3.2",),
            status="active",
            provider="已有成果",
            implementation_kind="builtin",
            method="在二阶差分与 BOS 候选编码间按载荷大小自适应选择",
            entrypoint="integrations.group_research.adapter:Ts2DiffBosIntCodec",
            interface_contract="compress(values)/decompress(payload)",
            metadata={"source": "reger_bos_code_paths", "numeric_type": "int64"},
        ),
        AlgorithmSpec(
            id="group.ts2diff-bos-float",
            name="TS_2DIFF+BOS 浮点时序压缩",
            capability="compression",
            indicator_ids=("3.2",),
            status="active",
            provider="已有成果",
            implementation_kind="builtin",
            method="十进制定点映射与 TS_2DIFF/BOS 自适应编码",
            entrypoint="integrations.group_research.adapter:Ts2DiffBosFloatCodec",
            interface_contract="compress(values, decimal_places)/decompress(payload)",
            metadata={"source": "reger_bos_code_paths", "numeric_type": "float"},
        ),
        AlgorithmSpec(
            id="builtin.structure-parser",
            name="异构结构解析器",
            capability="parsing",
            indicator_ids=("3.3",),
            status="active",
            provider="本项目",
            implementation_kind="builtin",
            method="格式嗅探、结构解析和字段集合提取",
            entrypoint="governance.indicator_3_3:parse_records",
            interface_contract="parse_records(text, declared_format)",
        ),
        AlgorithmSpec(
            id="builtin.semantic-temporal-aligner",
            name="语义时序对齐器",
            capability="alignment",
            indicator_ids=("3.4",),
            status="active",
            provider="本项目",
            implementation_kind="builtin",
            method="字段别名统一、设备实体约束和最近时间窗匹配",
            entrypoint="governance.indicator_3_4:align_records",
            reference_ids=("matchmaker-icml-2025",),
            interface_contract="align_records(sequence, relations, tolerance_ms)",
        ),
        AlgorithmSpec(
            id="builtin.matchmaker-method-adapter",
            name="Schema Matching 方法适配器",
            capability="schema_matching",
            indicator_ids=("3.4", "3.8"),
            status="active",
            provider="本项目",
            implementation_kind="builtin",
            method="候选生成、别名精炼、置信度评分与拒绝阈值",
            entrypoint="integrations.research_methods.adapter:SchemaMatcherAdapter",
            reference_ids=("matchmaker-icml-2025",),
            interface_contract="match(source_schema, target_schema)",
            metadata={"implementation_scope": "项目自有实现，未复制官方代码"},
        ),
        AlgorithmSpec(
            id="builtin.high-frequency-buffer",
            name="高频批量环形缓冲",
            capability="ingestion",
            indicator_ids=("3.5",),
            status="active",
            provider="本项目",
            implementation_kind="builtin",
            method="锁保护的批量写入环形缓冲区",
            entrypoint="governance.indicator_3_5:HighFrequencyBuffer",
            reference_ids=("apache-tsfile",),
            interface_contract="ingest_batch(samples)/snapshot(limit)",
        ),
        AlgorithmSpec(
            id="builtin.four-dimension-quality",
            name="四维数据质量稳控",
            capability="quality",
            indicator_ids=("3.6",),
            status="active",
            provider="本项目",
            implementation_kind="builtin",
            method="完整性、一致性、时效性、有效性逐记录测评",
            entrypoint="governance.indicator_3_6:evaluate_quality",
            reference_ids=("tsquality-vldb-2023",),
            interface_contract="evaluate_quality(records)",
        ),
        AlgorithmSpec(
            id="builtin.tsquality-window-adapter",
            name="窗口化四维质量适配器",
            capability="quality_window",
            indicator_ids=("3.6", "3.9"),
            status="active",
            provider="本项目",
            implementation_kind="builtin",
            method="按事件时间窗口测量完整性、一致性、时效性和有效性",
            entrypoint="integrations.research_methods.adapter:WindowQualityAdapter",
            reference_ids=("tsquality-vldb-2023",),
            interface_contract="evaluate_windows(records, window_ms)",
            metadata={"implementation_scope": "项目自有实现，未复制论文附属源码"},
        ),
        AlgorithmSpec(
            id="builtin.temporal-fusion",
            name="序列/关系按需融合",
            capability="fusion",
            indicator_ids=("3.7",),
            status="active",
            provider="本项目",
            implementation_kind="builtin",
            method="基于设备实体和有效时间窗的左融合",
            entrypoint="governance.indicator_3_7:fuse",
            reference_ids=("compress-iotdb-pvldb-2025",),
            interface_contract="fuse(sequence, relations, tolerance_ms)",
        ),
        AlgorithmSpec(
            id="builtin.compressed-query-adapter",
            name="压缩态范围查询适配器",
            capability="compressed_query",
            indicator_ids=("3.1", "3.2", "3.7"),
            status="active",
            provider="本项目",
            implementation_kind="builtin",
            method="块级最值裁剪、候选块延迟解压和范围过滤",
            entrypoint="integrations.research_methods.adapter:CompressedQueryAdapter",
            reference_ids=("compress-iotdb-pvldb-2025",),
            interface_contract="compress(values, block_size, tolerance)/range_filter(data, lower, upper)",
            metadata={"implementation_scope": "项目自有实现，未复制外部仓库代码"},
        ),
        AlgorithmSpec(
            id="builtin.normalization-registry",
            name="异构规范化适配器注册表",
            capability="normalization",
            indicator_ids=("3.8",),
            status="active",
            provider="本项目",
            implementation_kind="builtin",
            method="可扩展格式适配器与统一 records/columns 中间表示",
            entrypoint="governance.indicator_3_8:NormalizationRegistry",
            reference_ids=("matchmaker-icml-2025",),
            interface_contract="register(adapter)/normalize(text, format_name)",
        ),
        AlgorithmSpec(
            id="builtin.seven-dimension-assessment",
            name="七维工业数据质量测评",
            capability="quality_assessment",
            indicator_ids=("3.9",),
            status="active",
            provider="本项目",
            implementation_kind="builtin",
            method="四维基础质量加唯一性、参照完整性和稳定性",
            entrypoint="governance.indicator_3_9:assess",
            reference_ids=("tsquality-vldb-2023",),
            interface_contract="assess(records)",
        ),
        AlgorithmSpec(
            id="planned.compress-iotdb",
            name="CompressIoTDB 压缩态查询适配器",
            capability="compressed_query",
            indicator_ids=("3.1", "3.2", "3.7"),
            status="planned",
            provider="外部论文实现",
            implementation_kind="external",
            method="CompColumn、压缩态算子与 late decompression",
            reference_ids=("compress-iotdb-pvldb-2025",),
            interface_contract="compress/query_compressed/decompress_late",
            license="待确认",
            license_status="pending",
            commit_status="pending",
        ),
        AlgorithmSpec(
            id="planned.apache-tsfile",
            name="Apache TsFile 存储适配器",
            capability="timeseries_storage",
            indicator_ids=("3.1", "3.2", "3.5"),
            status="planned",
            provider="Apache",
            implementation_kind="external",
            method="TsFile 列式存储、GORILLA 编码和 LZ4 压缩",
            reference_ids=("apache-tsfile",),
            interface_contract="write_tsfile/read_tsfile/benchmark_ingestion",
            license="Apache-2.0",
            license_status="confirmed",
            commit_status="pending",
        ),
        AlgorithmSpec(
            id="planned.tsquality",
            name="TsQuality 窗口质量计算适配器",
            capability="quality_udf",
            indicator_ids=("3.6", "3.9"),
            status="planned",
            provider="外部论文实现",
            implementation_kind="external",
            method="IoTDB UDF/窗口化四维质量计算",
            reference_ids=("tsquality-vldb-2023",),
            interface_contract="evaluate_windows(records, dimensions, window)",
            license="待确认",
            license_status="pending",
            commit_status="pending",
        ),
        AlgorithmSpec(
            id="planned.matchmaker",
            name="Matchmaker 零样本 Schema Matcher",
            capability="schema_matching",
            indicator_ids=("3.4", "3.8"),
            status="planned",
            provider="外部论文实现",
            implementation_kind="external",
            method="候选生成、匹配精炼、置信度评分与自改进",
            reference_ids=("matchmaker-icml-2025",),
            interface_contract="match(source_schema, target_schema, context)",
            license="待确认",
            license_status="pending",
            commit_status="pending",
        ),
    )


def build_default_registry(discover_external: bool = True) -> IntegrationRegistry:
    registry = IntegrationRegistry()
    for reference in _reference_catalog():
        registry.register_reference(reference)
    for algorithm in _algorithm_catalog():
        registry.register_algorithm(algorithm)
    if discover_external:
        registry.discover_manifests()
    return registry


INTEGRATION_REGISTRY = build_default_registry()
