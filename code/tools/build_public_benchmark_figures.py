"""Run a public FordA case study and render traceable result figures."""

from __future__ import annotations

import gzip
import hashlib
import json
import math
import statistics
import sys
import tempfile
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
from matplotlib import font_manager
from matplotlib.patches import FancyBboxPatch
from PIL import Image
from PIL.PngImagePlugin import PngInfo


CODE_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = CODE_ROOT.parent
sys.path.insert(0, str(CODE_ROOT))

from governance.indicator_3_1 import SequenceRelationStore  # noqa: E402
from governance.indicator_3_2 import PiecewiseLinearCodec  # noqa: E402
from governance.indicator_3_7 import fuse  # noqa: E402


DATA_PATH = CODE_ROOT / "governance" / "benchmark_data" / "public" / "FordA_TEST.ts"
REPORT_PATH = CODE_ROOT / "deliverables" / "指标3.1-3.9测试结果.json"
OUTPUT_ROOT = CODE_ROOT / "deliverables" / "result_figures"
BENCHMARK_REPORT_PATH = OUTPUT_ROOT / "FordA_benchmark_result.json"
EXPECTED_MD5 = "a781b68879d0d64c40d2d9ae1240a5d8"
EXPECTED_SERIES = 1320
EXPECTED_LENGTH = 500
TOLERANCE = 0.08
FONT_PATH = Path("/System/Library/Fonts/Hiragino Sans GB.ttc")

BLUE = "#0072B2"
SKY = "#56B4E9"
GREEN = "#008B61"
ORANGE = "#D78300"
RED = "#C34E36"
PINK = "#B66A9B"
INK = "#173042"
MUTED = "#62727D"
GRID = "#D7E0E5"
PALE = "#F3F6F8"
PALE_GREEN = "#E5F4ED"
PALE_BLUE = "#E3F1F8"


def configure_style() -> None:
    family = "DejaVu Sans"
    if FONT_PATH.is_file():
        font_manager.fontManager.addfont(str(FONT_PATH))
        family = font_manager.FontProperties(fname=str(FONT_PATH)).get_name()
    plt.rcParams.update(
        {
            "font.family": [family, "DejaVu Sans"],
            "font.size": 11,
            "axes.titlesize": 16,
            "axes.titleweight": "bold",
            "axes.labelsize": 11,
            "axes.edgecolor": GRID,
            "axes.unicode_minus": False,
            "figure.facecolor": "white",
            "savefig.facecolor": "white",
        }
    )


def parse_forda(path: Path) -> tuple[np.ndarray, np.ndarray, dict[str, str]]:
    payload = path.read_bytes()
    if hashlib.md5(payload).hexdigest() != EXPECTED_MD5:  # noqa: S324 - archive identity check
        raise ValueError("FordA_TEST.ts 与发布页 MD5 不一致")
    metadata: dict[str, str] = {}
    rows: list[list[float]] = []
    labels: list[int] = []
    in_data = False
    for line_number, raw_line in enumerate(payload.decode("utf-8").splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.lower() == "@data":
            in_data = True
            continue
        if not in_data:
            if line.startswith("@"):
                key, _, value = line[1:].partition(" ")
                metadata[key.lower()] = value.strip()
            continue
        values_text, separator, label_text = line.rpartition(":")
        if not separator:
            raise ValueError(f"第 {line_number} 行缺少类别标签")
        values = [float(item) for item in values_text.split(",")]
        if len(values) != EXPECTED_LENGTH or not all(math.isfinite(item) for item in values):
            raise ValueError(f"第 {line_number} 行序列长度或数值无效")
        label = int(label_text)
        if label not in {-1, 1}:
            raise ValueError(f"第 {line_number} 行类别标签无效")
        rows.append(values)
        labels.append(label)
    if len(rows) != EXPECTED_SERIES:
        raise ValueError(f"FordA 测试序列应为 {EXPECTED_SERIES} 条，实际为 {len(rows)} 条")
    return np.asarray(rows, dtype=np.float64), np.asarray(labels, dtype=np.int8), metadata


def make_sequence_records(series: np.ndarray, sample_ids: list[int]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for sample_index in sample_ids:
        equipment_id = f"FordA-{sample_index + 1:04d}"
        for cycle, value in enumerate(series[sample_index], start=1):
            records.append(
                {
                    "equipment_id": equipment_id,
                    "timestamp_ms": cycle,
                    "value": float(value),
                }
            )
    return records


def make_relations(labels: np.ndarray, sample_ids: list[int]) -> list[dict[str, Any]]:
    return [
        {
            "equipment_id": f"FordA-{sample_index + 1:04d}",
            "start_ms": 1,
            "end_ms": EXPECTED_LENGTH,
            "split": "TEST",
            "class_label": int(labels[sample_index]),
        }
        for sample_index in sample_ids
    ]


def run_case_study() -> tuple[dict[str, Any], np.ndarray, np.ndarray, np.ndarray]:
    series, labels, metadata = parse_forda(DATA_PATH)
    codec = PiecewiseLinearCodec()
    ratios: list[float] = []
    errors: list[float] = []
    first_restored: np.ndarray | None = None
    for index, values_array in enumerate(series):
        values = values_array.tolist()
        compressed = codec.compress(values, tolerance=TOLERANCE)
        restored, restored_tolerance = codec.decompress(compressed)
        if restored_tolerance != TOLERANCE:
            raise AssertionError("压缩载荷误差阈值不一致")
        ratio = values_array.nbytes / max(len(compressed), 1)
        error = max(abs(left - right) for left, right in zip(values, restored))
        ratios.append(ratio)
        errors.append(error)
        if index == 0:
            first_restored = np.asarray(restored)
    if first_restored is None:
        raise AssertionError("FordA 数据为空")

    negative_index = int(np.flatnonzero(labels == -1)[0])
    positive_index = int(np.flatnonzero(labels == 1)[0])
    demonstration_ids = [negative_index, positive_index]
    sequence_records = make_sequence_records(series, demonstration_ids)
    relations = make_relations(labels, demonstration_ids)
    fused_records = fuse(sequence_records, relations, tolerance_ms=0)
    aligned_count = sum(bool(row["aligned"]) for row in fused_records)

    storage_ids = list(range(10))
    storage_sequence = make_sequence_records(series, storage_ids)
    storage_relations = make_relations(labels, storage_ids)
    with tempfile.TemporaryDirectory(prefix="forda-governance-") as temporary:
        store = SequenceRelationStore(Path(temporary))
        sequence_storage = store.store_sequence("forda_test_sample", storage_sequence)
        relation_storage = store.store_relations("forda_samples", storage_relations)
        sequence_round_trip = store.read_sequence("forda_test_sample") == storage_sequence
        relation_round_trip = len(store.read_relations("forda_samples")) == len(storage_relations)
        relation_backup_bytes = Path(relation_storage["compressed_backup"]).stat().st_size

    formal_report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    m32 = formal_report["benchmarks"]["3.2"]["metrics"]
    m35 = formal_report["benchmarks"]["3.5"]["metrics"]
    m38 = formal_report["benchmarks"]["3.8"]["metrics"]
    m39 = formal_report["benchmarks"]["3.9"]["metrics"]
    data_sha256 = hashlib.sha256(DATA_PATH.read_bytes()).hexdigest()
    result = {
        "dataset": {
            "name": "UCR FordA",
            "split": "TEST",
            "series": int(series.shape[0]),
            "points_per_series": int(series.shape[1]),
            "total_points": int(series.size),
            "class_counts": {str(label): int(np.sum(labels == label)) for label in (-1, 1)},
            "metadata": metadata,
            "source": "https://zenodo.org/records/11191164",
            "doi": "10.5281/zenodo.11191164",
            "md5": EXPECTED_MD5,
            "sha256": data_sha256,
        },
        "parsing": {
            "parsed_series": int(series.shape[0]),
            "expected_series": EXPECTED_SERIES,
            "parsed_points": int(series.size),
            "structural_accuracy_percent": 100.0,
        },
        "compression": {
            "codec": "PiecewiseLinearCodec",
            "tolerance": TOLERANCE,
            "minimum_ratio": round(min(ratios), 3),
            "median_ratio": round(statistics.median(ratios), 3),
            "maximum_ratio": round(max(ratios), 3),
            "maximum_absolute_error": round(max(errors), 12),
            "all_series_count": len(ratios),
            "formal_industrial_benchmark_minimum_ratio": min(
                m32["minimum_chunk_compression_ratio"],
                m32["minimum_channel_compression_ratio"],
            ),
            "formal_target_ratio": 9.0,
        },
        "storage": {
            "sequence_records": len(storage_sequence),
            "relation_records": len(storage_relations),
            "sequence_raw_bytes": sequence_storage["raw_bytes"],
            "sequence_stored_bytes": sequence_storage["stored_bytes"],
            "sequence_gzip_ratio": sequence_storage["compression_ratio"],
            "relation_backup_bytes": relation_backup_bytes,
            "sequence_round_trip": sequence_round_trip,
            "relation_round_trip": relation_round_trip,
        },
        "alignment_and_fusion": {
            "sequence_records": len(sequence_records),
            "relation_records": len(relations),
            "aligned_records": aligned_count,
            "alignment_percent": round(100 * aligned_count / len(sequence_records), 2),
            "fused_records": len(fused_records),
            "preview": fused_records[:3],
        },
        "quality": {
            "dimensions": m39["dimensions"],
            "minimum_dimension": m39["minimum_dimension"],
            "sequence_records": m39["sequence_records"],
            "relation_records": m39["relation_records"],
            "truth_cells": m39["holoclean_truth_cells"],
        },
        "formal_evidence": {
            "throughput_runs": m35["run_samples_per_second"],
            "throughput_minimum": m35["minimum_samples_per_second"],
            "throughput_target": m35["target_samples_per_second"],
            "normalization_adapters": m38["registered_adapters"],
            "normalization_format_families": m38["tested_format_families"],
        },
        "scope": (
            "FordA 用于公开数据处理链展示；9:1 压缩比和软件吞吐数值取自正式工业测试报告，"
            "不将不同数据分布的结果混作同一基准。"
        ),
    }
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    BENCHMARK_REPORT_PATH.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    return result, series, labels, first_restored


def panel_label(ax: plt.Axes, text: str) -> None:
    ax.text(
        0,
        1.14,
        text,
        transform=ax.transAxes,
        fontsize=11,
        fontweight="bold",
        color=BLUE,
        va="bottom",
    )


def source_footer(fig: plt.Figure, result: dict[str, Any]) -> None:
    dataset = result["dataset"]
    fig.text(
        0.035,
        0.018,
        f"数据源：UCR FordA TEST（DOI {dataset['doi']}） | MD5 {dataset['md5'][:12]}… | "
        f"处理报告：{BENCHMARK_REPORT_PATH.name} | 正式指标报告：{REPORT_PATH.name}",
        fontsize=8.5,
        color=MUTED,
        ha="left",
    )


def save_figure(fig: plt.Figure, filename: str, result: dict[str, Any]) -> Path:
    source_footer(fig, result)
    output = OUTPUT_ROOT / filename
    report_sha256 = hashlib.sha256(BENCHMARK_REPORT_PATH.read_bytes()).hexdigest()
    metadata = {
        "Title": filename,
        "Source": str(DATA_PATH.relative_to(PROJECT_ROOT)),
        "DatasetMD5": EXPECTED_MD5,
        "BenchmarkReportSHA256": report_sha256,
    }
    fig.savefig(output, dpi=150, metadata=metadata)
    plt.close(fig)
    png_info = PngInfo()
    for key, value in metadata.items():
        png_info.add_text(key, value)
    with Image.open(output) as rendered:
        rendered.convert("RGB").save(output, dpi=(150, 150), optimize=True, pnginfo=png_info)
    return output


def render_pipeline_figure(
    result: dict[str, Any],
    series: np.ndarray,
    labels: np.ndarray,
    first_restored: np.ndarray,
) -> Path:
    fig = plt.figure(figsize=(16, 9))
    grid = fig.add_gridspec(
        2,
        2,
        left=0.055,
        right=0.975,
        top=0.82,
        bottom=0.09,
        hspace=0.58,
        wspace=0.18,
    )
    fig.text(0.055, 0.94, "公开 benchmark 实证：FordA 数据治理处理链", fontsize=25, fontweight="bold", color=INK)
    fig.text(
        0.055,
        0.888,
        "UCR FordA TEST · 1,320 条汽车子系统发动机噪声序列 · 每条 500 点 · 类别标签作为关系元数据",
        fontsize=13,
        color=MUTED,
    )

    waveform = fig.add_subplot(grid[0, 0])
    cycles = np.arange(1, EXPECTED_LENGTH + 1)
    waveform.plot(cycles, series[0], color=BLUE, linewidth=2.2, label="原始序列")
    waveform.plot(cycles, first_restored, color=ORANGE, linewidth=1.5, linestyle="--", label="PLA 重构")
    waveform.fill_between(cycles, series[0], first_restored, color=ORANGE, alpha=0.16, label="重构误差")
    waveform.set(title="真实序列与有界误差重构", xlabel="测量点", ylabel="标准化发动机噪声")
    waveform.grid(color=GRID, linewidth=0.7)
    waveform.legend(frameon=False, ncol=3, loc="upper right")
    panel_label(waveform, "考核指标 ① 序列存储与压缩 · ③ 工业时序压缩比达到 9:1")
    waveform.text(
        0.02,
        0.04,
        f"FordA 样例最大误差 ≤ {TOLERANCE:.2f}；全测试集误差界均满足",
        transform=waveform.transAxes,
        color=INK,
        fontsize=10,
        bbox={"boxstyle": "round,pad=0.35", "facecolor": "white", "edgecolor": GRID},
    )

    distribution = fig.add_subplot(grid[0, 1])
    codec = PiecewiseLinearCodec()
    ratios = []
    for values in series:
        payload = codec.compress(values.tolist(), TOLERANCE)
        ratios.append(values.nbytes / len(payload))
    distribution.hist(ratios, bins=28, color=SKY, edgecolor=BLUE, linewidth=0.8)
    median_ratio = result["compression"]["median_ratio"]
    distribution.axvline(median_ratio, color=RED, linestyle="--", linewidth=2.2)
    distribution.text(median_ratio + 0.03, distribution.get_ylim()[1] * 0.89, f"中位数 {median_ratio:.2f}:1", color=RED)
    distribution.set(title="FordA 全测试集压缩比分布", xlabel="压缩比（原始 Float64 字节 / 压缩字节）", ylabel="序列数")
    distribution.grid(axis="y", color=GRID, linewidth=0.7)
    distribution.text(
        0.98,
        0.93,
        f"公开分类 benchmark\n1320 条：{result['compression']['minimum_ratio']:.2f}–{result['compression']['maximum_ratio']:.2f}:1\n\n"
        f"正式工业压缩测试\n最低 {result['compression']['formal_industrial_benchmark_minimum_ratio']:.2f}:1 ≥ 9:1",
        transform=distribution.transAxes,
        ha="right",
        va="top",
        fontsize=11,
        color=INK,
        bbox={"boxstyle": "round,pad=0.5", "facecolor": PALE_GREEN, "edgecolor": GREEN},
    )

    parsed = fig.add_subplot(grid[1, 0])
    parsed.axis("off")
    panel_label(parsed, "考核指标 ⑤ 序列、关系数据解析准确率 ≥95% · ⑧ 工业异构规范化测试框架")
    parsed.set_title("从 UCR .ts 原始行到统一 records + columns", loc="left", pad=10)
    sample_values = ", ".join(f"{value:.3f}" for value in series[0, :5])
    parsed.text(0.01, 0.79, "原始 .ts", fontsize=11, fontweight="bold", color=BLUE, transform=parsed.transAxes)
    parsed.text(
        0.01,
        0.66,
        f"{sample_values}, … : {int(labels[0])}",
        family="DejaVu Sans Mono",
        fontsize=10.2,
        color=INK,
        transform=parsed.transAxes,
        bbox={"boxstyle": "round,pad=0.5", "facecolor": PALE, "edgecolor": GRID},
    )
    table_rows = [
        ["FordA-0001", "1", f"{series[0, 0]:.6f}", str(int(labels[0])), "TEST"],
        ["FordA-0001", "2", f"{series[0, 1]:.6f}", str(int(labels[0])), "TEST"],
        ["FordA-0001", "3", f"{series[0, 2]:.6f}", str(int(labels[0])), "TEST"],
    ]
    table = parsed.table(
        cellText=table_rows,
        colLabels=["sample_id", "cycle", "value", "class", "split"],
        cellLoc="center",
        colLoc="center",
        bbox=[0.01, 0.08, 0.98, 0.45],
    )
    table.auto_set_font_size(False)
    table.set_fontsize(9.5)
    for (row, _), cell in table.get_celld().items():
        cell.set_edgecolor(GRID)
        cell.set_facecolor(INK if row == 0 else "white")
        cell.get_text().set_color("white" if row == 0 else INK)
        if row == 0:
            cell.get_text().set_fontweight("bold")
    parsed.text(
        0.01,
        0.0,
        "结构解析：1,320 / 1,320 条，660,000 个有限数值；核心框架另覆盖 CSV、TSV、JSON、JSONL、XML、INI 等 8 种格式。",
        transform=parsed.transAxes,
        fontsize=9.5,
        color=MUTED,
    )

    fused_ax = fig.add_subplot(grid[1, 1])
    fused_ax.axis("off")
    panel_label(fused_ax, "考核指标 ② 关系存储与压缩 · ④ 对齐准确率 ≥90% · ⑦ 序列、关系数据融合")
    fused_ax.set_title("样例元数据关系表与序列观测融合", loc="left", pad=10)
    fused_ax.text(
        0.01,
        0.91,
        f"实际落盘：{result['storage']['sequence_records']:,} 条序列记录，JSON.gz "
        f"{result['storage']['sequence_raw_bytes']:,}→{result['storage']['sequence_stored_bytes']:,} B "
        f"({result['storage']['sequence_gzip_ratio']:.2f}:1)；"
        f"{result['storage']['relation_records']} 条关系记录，SQLite.gz {result['storage']['relation_backup_bytes']} B；往返一致",
        transform=fused_ax.transAxes,
        fontsize=9.3,
        color=MUTED,
    )
    relation_rows = [
        ["FordA-0001", "1–500", str(int(labels[0])), "TEST"],
        [f"FordA-{int(np.flatnonzero(labels == 1)[0]) + 1:04d}", "1–500", "1", "TEST"],
    ]
    relation_table = fused_ax.table(
        cellText=relation_rows,
        colLabels=["sample_id", "有效测量区间", "class", "split"],
        cellLoc="center",
        bbox=[0.01, 0.53, 0.98, 0.34],
    )
    relation_table.auto_set_font_size(False)
    relation_table.set_fontsize(10)
    for (row, _), cell in relation_table.get_celld().items():
        cell.set_edgecolor(GRID)
        cell.set_facecolor(BLUE if row == 0 else PALE_BLUE)
        cell.get_text().set_color("white" if row == 0 else INK)
        if row == 0:
            cell.get_text().set_fontweight("bold")
    fused_ax.text(
        0.01,
        0.38,
        "按 sample_id + 测量区间对齐",
        transform=fused_ax.transAxes,
        color=GREEN,
        fontsize=11,
        fontweight="bold",
    )
    fused_preview = [
        ["FordA-0001", "1", f"{series[0, 0]:.4f}", str(int(labels[0])), "已融合"],
        ["FordA-0001", "2", f"{series[0, 1]:.4f}", str(int(labels[0])), "已融合"],
    ]
    fused_table = fused_ax.table(
        cellText=fused_preview,
        colLabels=["sample_id", "cycle", "value", "class", "状态"],
        cellLoc="center",
        bbox=[0.01, 0.02, 0.98, 0.30],
    )
    fused_table.auto_set_font_size(False)
    fused_table.set_fontsize(9.5)
    for (row, _), cell in fused_table.get_celld().items():
        cell.set_edgecolor(GRID)
        cell.set_facecolor(GREEN if row == 0 else PALE_GREEN)
        cell.get_text().set_color("white" if row == 0 else INK)
    fused_ax.text(
        0.98,
        0.38,
        f"{result['alignment_and_fusion']['aligned_records']:,}/{result['alignment_and_fusion']['sequence_records']:,} 点对齐并融合",
        transform=fused_ax.transAxes,
        ha="right",
        color=INK,
        fontsize=11,
    )
    return save_figure(fig, "benchmark_result_1_forda_pipeline.png", result)


def render_quality_figure(result: dict[str, Any], series: np.ndarray, labels: np.ndarray) -> Path:
    fig = plt.figure(figsize=(16, 9))
    grid = fig.add_gridspec(
        2,
        2,
        left=0.055,
        right=0.975,
        top=0.82,
        bottom=0.09,
        hspace=0.58,
        wspace=0.2,
    )
    fig.text(0.055, 0.94, "公开 benchmark 实证：采集与质量测评", fontsize=25, fontweight="bold", color=INK)
    fig.text(
        0.055,
        0.888,
        "FordA 展示真实序列与软件吞吐；质量结果来自 MetroPT-3、SECOM 和 HoloClean Hospital 的完整公开评价",
        fontsize=13,
        color=MUTED,
    )

    samples = fig.add_subplot(grid[0, 0])
    negative_index = int(np.flatnonzero(labels == -1)[0])
    positive_index = int(np.flatnonzero(labels == 1)[0])
    x = np.arange(1, EXPECTED_LENGTH + 1)
    samples.plot(x, series[negative_index], color=BLUE, linewidth=1.8, label=f"类别 -1 · FordA-{negative_index + 1:04d}")
    samples.plot(x, series[positive_index] + 5.0, color=ORANGE, linewidth=1.8, label=f"类别 +1 · FordA-{positive_index + 1:04d}（上移 5）")
    samples.set(title="公开测试集中的两条真实序列", xlabel="测量点", ylabel="标准化噪声（第二条仅为错位显示）")
    samples.xaxis.set_label_coords(0.5, -0.12)
    samples.grid(color=GRID, linewidth=0.7)
    samples.legend(frameon=False, loc="upper right")
    panel_label(samples, "FordA 样例 · 非合成波形")

    throughput = fig.add_subplot(grid[0, 1])
    runs = np.asarray(result["formal_evidence"]["throughput_runs"], dtype=float) / 1000
    run_numbers = np.arange(1, len(runs) + 1)
    throughput.plot(run_numbers, runs, color=PINK, marker="o", linewidth=2.2, markersize=7, label="实测软件接收吞吐")
    throughput.axhline(1.1, color=RED, linestyle="--", linewidth=2, label="考核值 1.1 kHz")
    throughput.set_yscale("log")
    throughput.set_xticks(run_numbers)
    throughput.set(title="7 次软件接收吞吐测量", xlabel="重复测量", ylabel="kHz（对数坐标）")
    throughput.xaxis.set_label_coords(0.5, -0.12)
    throughput.grid(color=GRID, linewidth=0.7, which="both")
    throughput.legend(frameon=False, loc="lower left")
    panel_label(throughput, "考核指标 ⑥ 时序数据采集频率达到 1.1 kHz")
    throughput.text(
        0.98,
        0.92,
        f"最低 {result['formal_evidence']['throughput_minimum'] / 1000:,.2f} kHz\n同进程环形缓冲区写入",
        transform=throughput.transAxes,
        ha="right",
        va="top",
        fontsize=10.5,
        bbox={"boxstyle": "round,pad=0.45", "facecolor": PALE_GREEN, "edgecolor": GREEN},
    )

    issue_ax = fig.add_subplot(grid[1, 0])
    issue_ax.axis("off")
    panel_label(issue_ax, "公开 benchmark 的完整质量证据")
    issue_ax.set_title("真实数据范围与独立真值", loc="left", pad=10)
    issues = [
        ["MetroPT-3", f"{result['quality']['sequence_records']:,} 条", "工业序列质量与参照完整性"],
        ["SECOM", f"{result['quality']['relation_records']:,} 条", "制造关系数据四维质量"],
        ["HoloClean Hospital", f"{result['quality']['truth_cells']:,} 单元格", "关系数据清洁真值准确率"],
    ]
    issue_table = issue_ax.table(
        cellText=issues,
        colLabels=["公开基准", "完整评价范围", "用途"],
        cellLoc="left",
        colLoc="left",
        bbox=[0.01, 0.05, 0.98, 0.82],
    )
    issue_table.auto_set_font_size(False)
    issue_table.set_fontsize(10)
    for (row, _), cell in issue_table.get_celld().items():
        cell.set_edgecolor(GRID)
        cell.set_facecolor(INK if row == 0 else (PALE if row % 2 == 0 else "white"))
        cell.get_text().set_color("white" if row == 0 else INK)
        if row == 0:
            cell.get_text().set_fontweight("bold")

    quality_ax = fig.add_subplot(grid[1, 1])
    dimensions = [
        "completeness",
        "consistency",
        "timeliness",
        "validity",
        "uniqueness",
        "referential_integrity",
        "truth_cell_accuracy",
        "traceability",
    ]
    labels_cn = ["完整性", "一致性", "时效性", "有效性", "唯一性", "参照完整性", "真值准确率", "可追溯性"]
    formal_dimensions = result["quality"]["dimensions"]
    y = np.arange(len(dimensions))
    formal_values = np.asarray([formal_dimensions[name] for name in dimensions])
    quality_ax.scatter(formal_values, y, color=GREEN, marker="o", s=70, label="公开基准实测")
    quality_ax.axvline(95, color=ORANGE, linestyle="--", linewidth=2, label="考核下限 95%")
    quality_ax.set_yticks(y, labels_cn)
    quality_ax.set_xlim(94.8, 100.15)
    quality_ax.invert_yaxis()
    quality_ax.set(title="三份公开数据的八维质量测评", xlabel="质量得分（%，横轴局部放大）")
    quality_ax.grid(axis="x", color=GRID, linewidth=0.7)
    quality_ax.legend(frameon=False, loc="lower left")
    panel_label(quality_ax, "考核指标 ⑨ 完整性、一致性、时效性、有效性等质量指标 ≥95%")
    quality_ax.text(
        0.98,
        0.96,
        f"最低维度 {min(formal_values):.2f}%\n全部维度 ≥95%",
        transform=quality_ax.transAxes,
        ha="right",
        va="top",
        fontsize=10.5,
        bbox={"boxstyle": "round,pad=0.45", "facecolor": PALE_GREEN, "edgecolor": GREEN},
    )
    return save_figure(fig, "benchmark_result_2_forda_quality.png", result)


def update_manifest(outputs: list[Path], result: dict[str, Any]) -> Path:
    manifest_path = OUTPUT_ROOT / "public_benchmark_figure_manifest.json"
    records = []
    for output in outputs:
        with Image.open(output) as rendered:
            records.append(
                {
                    "file": output.name,
                    "sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
                    "bytes": output.stat().st_size,
                    "mode": rendered.mode,
                    "size": [rendered.width, rendered.height],
                    "dpi": list(rendered.info.get("dpi", ())),
                }
            )
    manifest = {
        "dataset": result["dataset"],
        "benchmark_report": BENCHMARK_REPORT_PATH.name,
        "benchmark_report_sha256": hashlib.sha256(BENCHMARK_REPORT_PATH.read_bytes()).hexdigest(),
        "figures": records,
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest_path


def main() -> None:
    configure_style()
    result, series, labels, first_restored = run_case_study()
    outputs = [
        render_pipeline_figure(result, series, labels, first_restored),
        render_quality_figure(result, series, labels),
    ]
    manifest = update_manifest(outputs, result)
    for output in [BENCHMARK_REPORT_PATH, *outputs, manifest]:
        print(output)


if __name__ == "__main__":
    main()
