"""Render traceable result figures from the committed indicator report."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
from matplotlib import font_manager
from matplotlib.ticker import FuncFormatter, FixedLocator
from PIL import Image, ImageDraw, ImageFont
from PIL.PngImagePlugin import PngInfo


CODE_ROOT = Path(__file__).resolve().parents[1]
REPORT_PATH = CODE_ROOT / "deliverables" / "指标3.1-3.9测试结果.json"
OUTPUT_ROOT = CODE_ROOT / "deliverables" / "result_figures"
FONT_PATH = Path("/System/Library/Fonts/Hiragino Sans GB.ttc")

BLUE = "#0072B2"
SKY = "#56B4E9"
GREEN = "#009E73"
ORANGE = "#E69F00"
RED = "#D55E00"
PINK = "#CC79A7"
INK = "#172B3A"
MUTED = "#5F6B76"
GRID = "#D9E1E8"
PALE = "#F3F6F8"


def configure_style() -> None:
    family = "DejaVu Sans"
    if FONT_PATH.is_file():
        font_manager.fontManager.addfont(str(FONT_PATH))
        family = font_manager.FontProperties(fname=str(FONT_PATH)).get_name()
    plt.rcParams.update(
        {
            "font.family": [family, "DejaVu Sans"],
            "font.size": 12,
            "axes.titlesize": 18,
            "axes.titleweight": "bold",
            "axes.labelsize": 12,
            "axes.edgecolor": GRID,
            "axes.linewidth": 0.8,
            "axes.unicode_minus": False,
            "figure.facecolor": "white",
            "savefig.facecolor": "white",
            "svg.fonttype": "none",
        }
    )


def load_report() -> tuple[dict[str, object], str]:
    payload = REPORT_PATH.read_bytes()
    report = json.loads(payload)
    if report.get("passed") is not True:
        raise ValueError("测试报告未通过，不生成成果图")
    return report, hashlib.sha256(payload).hexdigest()


def metric(report: dict[str, object], indicator: str) -> dict[str, object]:
    return report["benchmarks"][indicator]["metrics"]


def footer(fig: plt.Figure, report: dict[str, object], report_sha256: str) -> None:
    source = report["source"]
    environment = report["environment"]
    generated = str(report["generated_at"]).replace("T", " ").replace("+00:00", " UTC")
    text = (
        f"数据源：指标3.1-3.9测试结果.json  |  生成时间：{generated}  |  "
        f"{environment['platform']} / Python {environment['python']}  |  "
        f"commit {str(source['git_commit'])[:7]}  |  report SHA-256 {report_sha256[:12]}…"
    )
    fig.text(0.035, 0.018, text, color=MUTED, fontsize=8.5, ha="left", va="bottom")


def save_figure(
    fig: plt.Figure,
    name: str,
    report: dict[str, object],
    report_sha256: str,
) -> Path:
    footer(fig, report, report_sha256)
    output = OUTPUT_ROOT / f"{name}.png"
    metadata = {
        "Title": name,
        "Source": str(REPORT_PATH.relative_to(CODE_ROOT)),
        "ReportSHA256": report_sha256,
        "GitCommit": str(report["source"]["git_commit"]),
    }
    fig.savefig(output, dpi=150, metadata=metadata)
    plt.close(fig)
    png_info = PngInfo()
    for key, value in metadata.items():
        png_info.add_text(key, value)
    with Image.open(output) as rendered:
        rendered.convert("RGB").save(
            output,
            dpi=(150, 150),
            optimize=True,
            pnginfo=png_info,
        )
    return output


def result_overview(report: dict[str, object], report_sha256: str) -> Path:
    m32 = metric(report, "3.2")
    m33 = metric(report, "3.3")
    m34 = metric(report, "3.4")
    m35 = metric(report, "3.5")
    m36 = metric(report, "3.6")
    m39 = metric(report, "3.9")

    fig = plt.figure(figsize=(16, 9), layout="constrained")
    grid = fig.add_gridspec(3, 5, height_ratios=[0.75, 1.7, 1.1])
    title_ax = fig.add_subplot(grid[0, :])
    title_ax.axis("off")
    title_ax.text(
        0,
        0.78,
        "面向离散制造垂域模型的自动化数据治理系统",
        fontsize=28,
        fontweight="bold",
        color=INK,
        ha="left",
        va="center",
    )
    title_ax.text(
        0,
        0.25,
        "3.1–3.9 指标实测成果总览",
        fontsize=17,
        color=BLUE,
        ha="left",
        va="center",
    )
    title_ax.text(
        1,
        0.52,
        "9 / 9\n全部通过",
        fontsize=24,
        fontweight="bold",
        color=GREEN,
        ha="right",
        va="center",
        linespacing=1.25,
    )

    minimum_compression_ratio = min(
        m32["minimum_chunk_compression_ratio"],
        m32["minimum_channel_compression_ratio"],
    )
    highlights = [
        (
            f"{minimum_compression_ratio:.2f}:1",
            "完整数据最差压缩比",
            f"总体 {m32['compression_ratio']:.2f}:1，目标 ≥ 9:1",
            BLUE,
        ),
        (
            f"{m33['parsing_accuracy_percent']:.0f}%",
            "结构化数据解析准确率",
            f"{m33['correctly_parsed']} / {m33['fixtures']} 个公开判定项",
            GREEN,
        ),
        (
            f"{m34['alignment_accuracy_percent']:.0f}%",
            "语义时序对齐准确率",
            f"{m34['correct_alignments']:,} / {m34['samples']:,} 条真实样本",
            ORANGE,
        ),
        (
            f"{m35['minimum_samples_per_second'] / 1_000_000:.2f}M/s",
            "最低软件接收吞吐",
            f"{m35['repeats']} 次测量，目标 ≥ 1.1k/s",
            PINK,
        ),
        (
            f"{m36['minimum_dimension']:.2f}%",
            "四维质量最低得分",
            f"{m36['sequence_records']:,} 条序列 + {m36['relation_records']:,} 条关系",
            RED,
        ),
    ]
    for column, (value, label, detail, color) in enumerate(highlights):
        ax = fig.add_subplot(grid[1, column])
        ax.set_facecolor(PALE)
        for spine in ax.spines.values():
            spine.set_visible(False)
        ax.set_xticks([])
        ax.set_yticks([])
        ax.text(0.08, 0.72, value, transform=ax.transAxes, fontsize=27, fontweight="bold", color=color)
        ax.text(0.08, 0.43, label, transform=ax.transAxes, fontsize=12.5, fontweight="bold", color=INK)
        ax.text(0.08, 0.18, detail, transform=ax.transAxes, fontsize=10.5, color=MUTED)

    strip_ax = fig.add_subplot(grid[2, :])
    strip_ax.set_xlim(0.4, 9.6)
    strip_ax.set_ylim(0, 1)
    strip_ax.axis("off")
    ids = list(report["selected_indicators"])
    for index, indicator in enumerate(ids, start=1):
        strip_ax.scatter(index, 0.62, s=620, marker="o", color=GREEN, edgecolor="white", linewidth=2)
        strip_ax.text(index, 0.62, indicator, ha="center", va="center", color="white", fontsize=11, fontweight="bold")
        strip_ax.text(index, 0.22, "通过", ha="center", va="center", color=INK, fontsize=10)
    strip_ax.text(
        0.005,
        0.96,
        f"3.9 综合质量评分 {m39['overall_score']:.2f}%  |  "
        f"3.6 质量平均值 {m36['overall_average']:.2f}%  |  "
        f"3.5 丢失样本 {m35['lost_samples']}",
        transform=strip_ax.transAxes,
        fontsize=12,
        color=MUTED,
        ha="left",
        va="top",
    )
    return save_figure(fig, "candidate_1_overview", report, report_sha256)


def compression_results(report: dict[str, object], report_sha256: str) -> Path:
    metrics = metric(report, "3.2")
    fig = plt.figure(figsize=(16, 9))
    grid = fig.add_gridspec(
        2,
        2,
        height_ratios=[1, 0.2],
        left=0.055,
        right=0.985,
        bottom=0.075,
        top=0.88,
        wspace=0.13,
        hspace=0.18,
    )
    left = fig.add_subplot(grid[0, 0])
    right = fig.add_subplot(grid[0, 1])
    left_note = fig.add_subplot(grid[1, 0])
    right_note = fig.add_subplot(grid[1, 1])
    left_note.axis("off")
    right_note.axis("off")
    fig.suptitle("3.2 工业时序压缩成果", fontsize=26, fontweight="bold", color=INK)

    labels = ["总体", "最差数据块", "最差通道"]
    values = [
        metrics["compression_ratio"],
        metrics["minimum_chunk_compression_ratio"],
        metrics["minimum_channel_compression_ratio"],
    ]
    bars = left.bar(labels, values, color=[GREEN, BLUE, ORANGE], width=0.62)
    left.axhline(9, color=RED, linestyle="--", linewidth=2, label="指标目标 9:1")
    left.set_ylabel("压缩比（原始字节 / 压缩字节）")
    left.set_ylim(0, max(values) * 1.22)
    left.set_title("完整数据的总体与最差结果", loc="left")
    left.grid(axis="y", color=GRID, linewidth=0.8)
    left.set_axisbelow(True)
    left.legend(frameon=False, loc="upper left")
    for bar, value in zip(bars, values):
        left.text(bar.get_x() + bar.get_width() / 2, value + 0.25, f"{value:.2f}:1", ha="center", fontweight="bold")
    left_note.text(
        0,
        0.08,
        f"MetroPT-3 官方完整 {metrics['records']:,} 行 × {metrics['sensor_channels']} 通道，"
        f"共核验 {metrics['processed_sensor_values']:,} 个值\n"
        f"原始载荷 {metrics['raw_bytes']:,} B；压缩载荷 {metrics['compressed_bytes']:,} B；"
        f"{metrics['chunks']} 个数据块全部解码核验",
        transform=left_note.transAxes,
        color=MUTED,
        fontsize=10.5,
        va="bottom",
    )

    channel_results = metrics["per_channel_results"]
    names = list(channel_results)
    ratios = [channel_results[name]["compression_ratio"] for name in names]
    colors = [
        BLUE if channel_results[name]["mode"] == "bounded_error" else GREEN
        for name in names
    ]
    positions = list(range(len(names)))
    bars = right.barh(positions, ratios, color=colors, height=0.68)
    right.axvline(9, color=RED, linestyle="--", linewidth=2, label="指标目标 9:1")
    right.set_xscale("log")
    right.set_xlabel("压缩比（对数坐标）")
    right.set_yticks(positions, labels=names)
    right.invert_yaxis()
    right.set_title("全部 15 个传感器通道", loc="left")
    right.grid(axis="x", color=GRID, linewidth=0.8)
    right.set_axisbelow(True)
    right.legend(frameon=False, loc="lower right")
    for bar, value in zip(bars, ratios):
        right.text(
            value * 1.04,
            bar.get_y() + bar.get_height() / 2,
            f"{value:.2f}:1",
            ha="left",
            va="center",
            fontsize=8.5,
        )
    right_note.text(
        0,
        0.08,
        "蓝色为七个固定误差界模拟量通道，绿色为八个无损数字量通道。\n"
        "图中完整列出所有通道；通过判据同时约束最差数据块和最差通道。",
        transform=right_note.transAxes,
        color=MUTED,
        fontsize=10,
        va="bottom",
    )
    return save_figure(fig, "candidate_2_compression", report, report_sha256)


def quality_results(report: dict[str, object], report_sha256: str) -> Path:
    m33 = metric(report, "3.3")
    m34 = metric(report, "3.4")
    m36 = metric(report, "3.6")
    m39 = metric(report, "3.9")
    fig = plt.figure(figsize=(16, 9))
    grid = fig.add_gridspec(
        2,
        2,
        height_ratios=[1, 0.18],
        left=0.085,
        right=0.985,
        bottom=0.075,
        top=0.87,
        wspace=0.18,
        hspace=0.16,
    )
    left = fig.add_subplot(grid[0, 0])
    right = fig.add_subplot(grid[0, 1])
    left_note = fig.add_subplot(grid[1, 0])
    right_note = fig.add_subplot(grid[1, 1])
    left_note.axis("off")
    right_note.axis("off")
    fig.suptitle("智能解析、语义对齐与数据质量实测", fontsize=25, fontweight="bold", color=INK)

    names = ["3.3 智能解析\nn=128", "3.4 语义时序对齐\nn=153"]
    estimates = np.array([m33["parsing_accuracy_percent"], m34["alignment_accuracy_percent"]])
    intervals = np.array([m33["accuracy_wilson_95_percent"], m34["accuracy_wilson_95_percent"]])
    y = np.arange(2)
    errors = np.vstack((estimates - intervals[:, 0], intervals[:, 1] - estimates))
    left.errorbar(
        estimates,
        y,
        xerr=errors,
        fmt="o",
        markersize=12,
        color=BLUE,
        ecolor=SKY,
        elinewidth=4,
        capsize=7,
        markeredgecolor="white",
        markeredgewidth=1.5,
    )
    left.axvline(95, color=GREEN, linestyle="--", linewidth=2, label="3.3 目标 95%")
    left.axvline(90, color=ORANGE, linestyle=":", linewidth=2, label="3.4 目标 90%")
    left.set_xlim(89, 100.7)
    left.set_yticks(y, names)
    left.invert_yaxis()
    left.set_xlabel("正确率（%），局部放大坐标")
    left.set_title("固定标注样例集上全部正确", loc="left")
    left.grid(axis="x", color=GRID)
    left.legend(frameon=False, loc="center left", bbox_to_anchor=(0.01, 0.48))
    for yi, estimate, interval in zip(y, estimates, intervals):
        left.text(
            90.35,
            yi,
            f"{estimate:.1f}%  |  Wilson 95%: {interval[0]:.2f}–{interval[1]:.2f}%",
            ha="left",
            va="center",
            fontsize=9.5,
            color=MUTED,
        )
    left_note.text(
        0,
        0.08,
        "区间仅描述当前固定样例集，不推断未抽样业务数据的总体准确率。",
        transform=left_note.transAxes,
        color=MUTED,
        fontsize=9.5,
        va="bottom",
    )

    labels = ["完整性", "一致性", "时效性", "有效性", "唯一性", "参照完整性", "真值单元准确率", "可追溯性"]
    keys = [
        "completeness",
        "consistency",
        "timeliness",
        "validity",
        "uniqueness",
        "referential_integrity",
        "truth_cell_accuracy",
        "traceability",
    ]
    y = np.arange(len(labels))
    values39 = np.array([m39["dimensions"][key] for key in keys])
    right.scatter(values39, y, s=110, color=GREEN, marker="s", label="3.9 综合质量")
    values36 = np.array([m36[key] for key in keys[:4]])
    right.scatter(values36, y[:4], s=100, color=ORANGE, marker="o", label="3.6 四维质量")
    right.axvline(95, color=RED, linestyle="--", linewidth=2, label="通过线 95%")
    right.set_xlim(94.8, 100.2)
    right.set_yticks(y, labels)
    right.invert_yaxis()
    right.set_xlabel("质量得分（%），局部放大坐标")
    right.set_title("质量维度均高于 95% 通过线", loc="left")
    right.grid(axis="x", color=GRID)
    right.legend(frameon=False, loc="center left", bbox_to_anchor=(0.01, 0.43))
    right_note.text(
        1,
        0.08,
        f"3.6 最低维度 {m36['minimum_dimension']:.2f}%  |  "
        f"3.9 最低维度 {m39['minimum_dimension']:.2f}%  |  "
        f"3.9 综合分 {m39['overall_score']:.2f}%",
        transform=right_note.transAxes,
        ha="right",
        color=MUTED,
        fontsize=10,
        va="bottom",
    )
    return save_figure(fig, "candidate_3_quality", report, report_sha256)


def throughput_results(report: dict[str, object], report_sha256: str) -> Path:
    metrics = metric(report, "3.5")
    rates = np.array(metrics["run_samples_per_second"], dtype=float)
    runs = np.arange(1, len(rates) + 1)
    target = float(metrics["target_samples_per_second"])
    median = float(metrics["ingestion_samples_per_second"])

    fig = plt.figure(figsize=(16, 9))
    grid = fig.add_gridspec(
        2,
        1,
        height_ratios=[1, 0.13],
        left=0.065,
        right=0.985,
        bottom=0.075,
        top=0.87,
        hspace=0.06,
    )
    ax = fig.add_subplot(grid[0, 0])
    note_ax = fig.add_subplot(grid[1, 0])
    note_ax.axis("off")
    fig.suptitle("3.5 1.1 kHz 时序数据软件接收能力实测", fontsize=26, fontweight="bold", color=INK)
    ax.plot(runs, rates, color=BLUE, linewidth=2.5, marker="o", markersize=10, label="7 次实测")
    ax.axhline(median, color=GREEN, linewidth=2, linestyle="--", label=f"中位数 {median / 1e6:.3f} M/s")
    ax.axhline(target, color=RED, linewidth=2.5, linestyle=":", label="指标目标 1.1 k/s")
    ax.set_yscale("log")
    ax.set_xlim(0.6, 7.4)
    ax.set_ylim(700, 3_000_000)
    ax.set_xticks(runs, [f"第 {run} 次" for run in runs])
    ax.yaxis.set_major_locator(FixedLocator([1_000, 10_000, 100_000, 1_000_000, 3_000_000]))
    ax.yaxis.set_major_formatter(
        FuncFormatter(lambda value, _: f"{value / 1e6:g} M/s" if value >= 1e6 else f"{value / 1e3:g} k/s")
    )
    ax.set_ylabel("软件接收吞吐（样本/秒，对数坐标）")
    ax.set_title(
        f"1 次预热后重复 {metrics['repeats']} 次；每次 {metrics['samples']:,} 条，批大小 {metrics['batch_size']}",
        loc="left",
    )
    ax.grid(which="major", axis="y", color=GRID, linewidth=0.9)
    ax.legend(frameon=False, loc="lower right")
    for run, rate in zip(runs, rates):
        ax.annotate(f"{rate / 1e6:.3f} M/s", (run, rate), xytext=(0, 12), textcoords="offset points", ha="center", fontsize=10, color=INK)
    note_ax.text(
        0,
        0.92,
        f"最低 {metrics['minimum_samples_per_second'] / 1e6:.3f} M/s  |  "
        f"最高 {metrics['maximum_samples_per_second'] / 1e6:.3f} M/s  |  "
        f"变异系数 {metrics['throughput_coefficient_of_variation'] * 100:.2f}%  |  "
        f"丢失样本 {metrics['lost_samples']}",
        transform=note_ax.transAxes,
        color=MUTED,
        fontsize=11,
        va="top",
    )
    note_ax.text(
        0,
        0.42,
        "口径：同一 Python 进程内的环形缓冲区批量写入速率，不等同于采集卡至存储系统的端到端吞吐。",
        transform=note_ax.transAxes,
        color=MUTED,
        fontsize=9.5,
        va="top",
    )
    return save_figure(fig, "candidate_4_throughput", report, report_sha256)


def contact_sheet(paths: list[Path]) -> Path:
    canvas = Image.new("RGB", (2400, 1440), "white")
    draw = ImageDraw.Draw(canvas)
    title_font = ImageFont.truetype(str(FONT_PATH), 48, index=0) if FONT_PATH.is_file() else ImageFont.load_default()
    label_font = ImageFont.truetype(str(FONT_PATH), 28, index=0) if FONT_PATH.is_file() else ImageFont.load_default()
    draw.text((70, 35), "真实成果图候选总览", fill=INK, font=title_font)
    labels = ["候选 1：总体成果总览", "候选 2：时序压缩成果", "候选 3：解析对齐与质量", "候选 4：1.1 kHz 吞吐实测"]
    placements = [(55, 125), (1215, 125), (55, 785), (1215, 785)]
    for path, label, (x, y) in zip(paths, labels, placements):
        with Image.open(path) as source:
            image = source.convert("RGB")
        image.thumbnail((1130, 635), Image.Resampling.LANCZOS)
        canvas.paste(image, (x, y + 38))
        draw.text((x, y), label, fill=INK, font=label_font)
    output = OUTPUT_ROOT / "candidate_contact_sheet.png"
    canvas.save(output, dpi=(150, 150), optimize=True)
    return output


def write_manifest(paths: list[Path], report: dict[str, object], report_sha256: str) -> None:
    figures = {}
    for path in paths:
        with Image.open(path) as image:
            pixels = list(image.size)
        figures[path.name] = {
            "bytes": path.stat().st_size,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "pixels": pixels,
        }
    manifest = {
        "source_report": str(REPORT_PATH.relative_to(CODE_ROOT)),
        "source_report_sha256": report_sha256,
        "source_git_commit": report["source"]["git_commit"],
        "figures": figures,
    }
    (OUTPUT_ROOT / "figure_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def main() -> None:
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    configure_style()
    report, report_sha256 = load_report()
    figures = [
        result_overview(report, report_sha256),
        compression_results(report, report_sha256),
        quality_results(report, report_sha256),
        throughput_results(report, report_sha256),
    ]
    overview = contact_sheet(figures)
    write_manifest([*figures, overview], report, report_sha256)
    for path in [*figures, overview]:
        print(path)


if __name__ == "__main__":
    main()
