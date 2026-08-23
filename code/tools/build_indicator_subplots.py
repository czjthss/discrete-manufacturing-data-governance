"""Render three concise figures covering indicators 3.1 through 3.9."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
from matplotlib import font_manager
from PIL import Image
from PIL.PngImagePlugin import PngInfo


CODE_ROOT = Path(__file__).resolve().parents[1]
REPORT_PATH = CODE_ROOT / "deliverables" / "指标3.1-3.9测试结果.json"
OUTPUT_ROOT = CODE_ROOT / "deliverables" / "result_figures"
FONT_PATH = Path("/System/Library/Fonts/Hiragino Sans GB.ttc")

INK = "#172B3A"
MUTED = "#62717D"
GRID = "#D9E1E7"
BLUE = "#0072B2"
GREEN = "#009E73"
ORANGE = "#E69F00"
RED = "#D55E00"
SKY = "#56B4E9"


def metric(report: dict[str, Any], indicator: str) -> dict[str, Any]:
    return report["benchmarks"][indicator]["metrics"]


def configure_style() -> None:
    if FONT_PATH.is_file():
        font_manager.fontManager.addfont(str(FONT_PATH))
        family = font_manager.FontProperties(fname=str(FONT_PATH)).get_name()
    else:
        family = "Arial Unicode MS"
    plt.rcParams.update(
        {
            "font.family": family,
            "font.size": 11,
            "axes.titlesize": 15,
            "axes.titleweight": "bold",
            "axes.labelcolor": INK,
            "axes.edgecolor": GRID,
            "axes.linewidth": 0.8,
            "xtick.color": INK,
            "ytick.color": INK,
            "text.color": INK,
            "figure.facecolor": "white",
            "axes.facecolor": "white",
            "axes.unicode_minus": False,
            "savefig.facecolor": "white",
        }
    )


def clean_axis(axis: plt.Axes, *, grid_axis: str = "y") -> None:
    axis.grid(axis=grid_axis, color=GRID, linewidth=0.8)
    axis.set_axisbelow(True)
    axis.spines[["top", "right"]].set_visible(False)


def title(axis: plt.Axes, text: str, *, fontsize: float | None = None) -> None:
    axis.set_title(text, loc="left", pad=14, fontsize=fontsize)


def percent_bars(
    axis: plt.Axes,
    labels: list[str],
    values: list[float],
    *,
    target: float | None = None,
    colors: list[str] | None = None,
) -> None:
    positions = np.arange(len(labels))
    palette = colors or [BLUE, GREEN, ORANGE, SKY]
    bars = axis.bar(positions, values, color=palette[: len(labels)], width=0.62)
    axis.set_xticks(positions, labels)
    axis.set_ylim(0, 108)
    axis.set_ylabel("%")
    if target is not None:
        axis.axhline(target, color=RED, linestyle="--", linewidth=1.8)
    for bar, value in zip(bars, values):
        axis.text(
            bar.get_x() + bar.get_width() / 2,
            value + 1.5,
            f"{value:.2f}%" if value % 1 else f"{value:.0f}%",
            ha="center",
            va="bottom",
            fontsize=10,
        )
    clean_axis(axis)


def benchmark_boxplots(
    axis: plt.Axes,
    labels: list[str],
    samples: list[list[float]],
    *,
    target: float,
    colors: list[str] | None = None,
) -> None:
    palette = colors or [BLUE, GREEN, ORANGE]
    for position, (values, color) in enumerate(zip(samples, palette), start=1):
        result = axis.boxplot(
            [values],
            positions=[position],
            widths=0.5,
            patch_artist=True,
            showfliers=False,
            medianprops={"color": INK, "linewidth": 1.8},
            whiskerprops={"color": MUTED},
            capprops={"color": MUTED},
        )
        result["boxes"][0].set(facecolor=color, alpha=0.28, edgecolor=color)
        offsets = np.linspace(-0.16, 0.16, len(values)) if len(values) > 1 else [0]
        point_size = 9 if len(values) > 100 else 26
        point_alpha = 0.32 if len(values) > 100 else 0.9
        axis.scatter(
            np.asarray(offsets) + position,
            values,
            color=color,
            s=point_size,
            alpha=point_alpha,
            zorder=3,
        )
    axis.axhline(target, color=RED, linestyle="--", linewidth=1.8)
    axis.set_xticks(range(1, len(labels) + 1), labels)
    clean_axis(axis)


def quality_heatmap(
    axis: plt.Axes,
    row_labels: list[str],
    column_labels: list[str],
    values: list[list[float | None]],
) -> None:
    data = np.asarray(
        [[np.nan if value is None else value for value in row] for row in values],
        dtype=float,
    )
    color_map = plt.get_cmap("viridis").copy()
    color_map.set_bad("#EDF1F3")
    axis.imshow(data, cmap=color_map, vmin=95, vmax=100, aspect="auto")
    axis.set_xticks(range(len(column_labels)), column_labels)
    axis.set_yticks(range(len(row_labels)), row_labels)
    for row_index, row in enumerate(values):
        for column_index, value in enumerate(row):
            label = "N/A" if value is None else f"{value:.1f}"
            color = MUTED if value is None else ("white" if value < 98 else INK)
            axis.text(
                column_index,
                row_index,
                label,
                ha="center",
                va="center",
                color=color,
                fontsize=9,
            )
    axis.tick_params(length=0)
    axis.spines[:].set_visible(False)


def save(fig: plt.Figure, filename: str, report_sha256: str) -> Path:
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    output = OUTPUT_ROOT / filename
    metadata = {
        "Title": filename.removesuffix(".png"),
        "Source": str(REPORT_PATH.relative_to(CODE_ROOT)),
        "ReportSHA256": report_sha256,
    }
    fig.savefig(output, dpi=180, metadata=metadata)
    plt.close(fig)
    info = PngInfo()
    for key, value in metadata.items():
        info.add_text(key, value)
    with Image.open(output) as image:
        image.convert("RGB").save(output, dpi=(180, 180), optimize=True, pnginfo=info)
    return output


def figure_1(report: dict[str, Any], report_sha256: str) -> Path:
    m31 = metric(report, "3.1")
    m32 = metric(report, "3.2")
    fig, axes = plt.subplots(1, 3, figsize=(16, 5.6), layout="constrained")

    storage = m31["dataset_results"]
    title(axes[0], "①支持序列数据的存储与压缩。")
    sequence_labels = ["MetroPT-3", "UCR FordA"]
    sequence_results = [storage["metropt3"], storage["forda"]]
    sequence_bars = axes[0].bar(
        sequence_labels,
        [item["compression_ratio"] for item in sequence_results],
        color=[BLUE, SKY],
        width=0.58,
    )
    axes[0].set_ylabel("文件级Gzip无损压缩比")
    for bar, result in zip(sequence_bars, sequence_results):
        axes[0].text(
            bar.get_x() + bar.get_width() / 2,
            bar.get_height() + 0.25,
            f"{bar.get_height():.2f}:1\n{result['records']:,} 条",
            ha="center",
            fontsize=9,
        )
    axes[0].set_ylim(0, max(item["compression_ratio"] for item in sequence_results) * 1.28)
    clean_axis(axes[0])

    title(axes[1], "②支持关系数据的存储与压缩。")
    relation_labels = ["UCI SECOM", "HoloClean\nHospital"]
    relation_results = [storage["secom"], storage["holoclean_hospital"]]
    relation_bars = axes[1].bar(
        relation_labels,
        [item["compression_ratio"] for item in relation_results],
        color=[GREEN, ORANGE],
        width=0.58,
    )
    axes[1].set_ylabel("SQLite 备份压缩比")
    for bar, result in zip(relation_bars, relation_results):
        axes[1].text(
            bar.get_x() + bar.get_width() / 2,
            bar.get_height() + 0.1,
            f"{bar.get_height():.2f}:1\n{result['records']:,} 条",
            ha="center",
            fontsize=9,
        )
    axes[1].set_ylim(0, max(item["compression_ratio"] for item in relation_results) * 1.3)
    clean_axis(axes[1])

    title(axes[2], "③工业时序数据压缩比达到9:1。")
    compression = m32["dataset_results"]
    compression_samples = [
        compression["metropt3"]["chunk_compression_ratios"],
        [item["compression_ratio"] for item in compression["forda"]["unit_results"]],
    ]
    benchmark_boxplots(
        axes[2],
        ["MetroPT-3", "UCR FordA"],
        compression_samples,
        target=9,
        colors=[GREEN, SKY],
    )
    axes[2].scatter(
        range(1, 3),
        [compression[key]["compression_ratio"] for key in ("metropt3", "forda")],
        marker="D",
        s=55,
        color=INK,
        zorder=4,
    )
    axes[2].set_ylim(8, max(max(values) for values in compression_samples) * 1.1)
    axes[2].set_ylabel("数值载荷误差有界压缩比")
    return save(fig, "indicator_panels_1_3.png", report_sha256)


def figure_2(report: dict[str, Any], report_sha256: str) -> Path:
    m33 = metric(report, "3.3")
    m34 = metric(report, "3.4")
    m35 = metric(report, "3.5")
    fig, axes = plt.subplots(1, 3, figsize=(17, 5.6), layout="constrained")

    title(axes[0], "④序列、关系数据对齐准确率≥90%。")
    alignment = m34["dataset_results"]["metropt3"]
    alignment_value = alignment["accuracy_percent"]
    interval = alignment["wilson_95_percent"]
    axes[0].bar(
        [0],
        [alignment_value],
        color=[BLUE],
        width=0.5,
        yerr=[[alignment_value - interval[0]], [interval[1] - alignment_value]],
        capsize=5,
    )
    axes[0].set_xticks([0], ["MetroPT-3"])
    axes[0].axhline(90, color=RED, linestyle="--", linewidth=1.8)
    axes[0].set_ylim(88, 101.5)
    axes[0].set_ylabel("对齐准确率（%）")
    axes[0].text(
        0,
        100.35,
        f"n={alignment['samples']:,}",
        ha="center",
        fontsize=9,
    )
    clean_axis(axes[0])

    title(axes[1], "⑤序列、关系数据解析准确率≥95%。")
    parsing = m33["dataset_results"]
    parsing_keys = ["metropt3", "forda", "secom", "holoclean_hospital"]
    parsing_labels = ["MetroPT-3", "UCR FordA", "UCI SECOM", "HoloClean\nHospital"]
    percent_bars(
        axes[1],
        parsing_labels,
        [parsing[key]["accuracy_percent"] for key in parsing_keys],
        target=95,
        colors=[BLUE, SKY, GREEN, ORANGE],
    )
    axes[1].set_ylabel("解析准确率（%）")
    axes[1].tick_params(axis="x", labelsize=9)
    parsing_counts = [
        parsing["metropt3"]["records"],
        parsing["forda"]["records"],
        parsing["secom"]["records"],
        parsing["holoclean_hospital"]["records"],
    ]
    for position, count in enumerate(parsing_counts):
        axes[1].text(
            position,
            50,
            f"n={count:,}",
            ha="center",
            va="center",
            color="white",
            fontsize=9,
            fontweight="bold",
        )

    title(axes[2], "⑥时序数据采集频率达到1.1kHz。")
    throughput = m35["dataset_results"]
    throughput_samples = [
        [value / 1000 for value in throughput["metropt3"]["run_samples_per_second"]],
        [value / 1000 for value in throughput["forda"]["run_samples_per_second"]],
    ]
    benchmark_boxplots(
        axes[2],
        ["MetroPT-3", "UCR FordA"],
        throughput_samples,
        target=1.1,
        colors=[BLUE, GREEN],
    )
    axes[2].set_yscale("log")
    axes[2].set_ylabel("kHz（对数坐标）")
    return save(fig, "indicator_panels_4_6.png", report_sha256)


def figure_3(report: dict[str, Any], report_sha256: str) -> Path:
    m37 = metric(report, "3.7")
    m38 = metric(report, "3.8")
    m39 = metric(report, "3.9")
    fig, axes = plt.subplots(1, 3, figsize=(18, 5.8), layout="constrained")

    title(axes[0], "⑦序列、关系数据可进行融合。")
    fusion = m37["dataset_results"]["metropt3"]
    fusion_values = [
        fusion["fusion_accuracy_percent"],
        fusion["source_preservation_percent"],
    ]
    fusion_bars = axes[0].bar(
        [0, 1], fusion_values, color=[GREEN, SKY], width=0.58
    )
    axes[0].set_xticks([0, 1], ["MetroPT-3\n融合准确率", "MetroPT-3\n源记录保留率"])
    axes[0].set_ylim(0, 108)
    axes[0].set_ylabel("总体结果（%）")
    for bar, value in zip(fusion_bars, fusion_values):
        axes[0].text(
            bar.get_x() + bar.get_width() / 2,
            value + 1.3,
            f"{value:.0f}%\nn={fusion['fused_rows']:,}",
            ha="center",
            fontsize=9,
        )
    clean_axis(axes[0])

    title(axes[1], "⑧搭建工业异构数据规范化测试框架。")
    normalization = m38["dataset_results"]
    normalization_values = [
        100.0 if normalization["metropt3"]["normalized"] else 0.0,
        100.0 if normalization["forda"]["normalized"] else 0.0,
        100.0 if normalization["secom"]["normalized"] else 0.0,
        100.0 if normalization["holoclean_hospital"]["normalized"] else 0.0,
    ]
    normalization_labels = [
        "MetroPT-3",
        "UCR FordA",
        "UCI SECOM",
        "HoloClean\nHospital",
    ]
    percent_bars(
        axes[1],
        normalization_labels,
        normalization_values,
        colors=[BLUE, SKY, GREEN, ORANGE],
    )
    axes[1].set_ylabel("规范化/符合性结果（%）")
    axes[1].tick_params(axis="x", labelsize=9)
    normalization_counts = [
        normalization["metropt3"]["records"],
        normalization["forda"]["records"],
        normalization["secom"]["records"],
        normalization["holoclean_hospital"]["records"],
    ]
    for position, count in enumerate(normalization_counts):
        axes[1].text(
            position,
            50,
            f"n={count:,}",
            ha="center",
            va="center",
            color="white",
            fontsize=9,
            fontweight="bold",
        )

    title(
        axes[2],
        "⑨序列、关系数据完整性、一致性、时效性、有效性等质量指标≥95%。",
        fontsize=10,
    )
    quality = m39["dataset_results"]
    quality_keys = [
        "completeness",
        "consistency",
        "timeliness",
        "validity",
        "uniqueness",
        "referential_integrity",
        "truth_cell_accuracy",
        "traceability",
    ]
    quality_heatmap(
        axes[2],
        ["MetroPT-3", "UCR FordA", "UCI SECOM", "HoloClean"],
        ["完整", "一致", "时效", "有效", "唯一", "参照", "真值", "追溯"],
        [
            [quality[dataset]["dimensions"].get(key) for key in quality_keys]
            for dataset in ("metropt3", "forda", "secom", "holoclean_hospital")
        ],
    )
    return save(fig, "indicator_panels_7_9.png", report_sha256)


def main() -> int:
    configure_style()
    payload = REPORT_PATH.read_bytes()
    report = json.loads(payload)
    report_sha256 = hashlib.sha256(payload).hexdigest()
    outputs = [
        figure_1(report, report_sha256),
        figure_2(report, report_sha256),
        figure_3(report, report_sha256),
    ]
    manifest = {
        "report": str(REPORT_PATH.relative_to(CODE_ROOT)),
        "report_sha256": report_sha256,
        "figures": [
            {
                "path": str(path.relative_to(CODE_ROOT)),
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "bytes": path.stat().st_size,
            }
            for path in outputs
        ],
    }
    manifest_path = OUTPUT_ROOT / "indicator_panels_manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    for output in outputs:
        print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
