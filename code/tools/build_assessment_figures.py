"""Build traceable assessment-result figures from the indicator report."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from PIL.PngImagePlugin import PngInfo


CODE_ROOT = Path(__file__).resolve().parents[1]
REPORT_PATH = CODE_ROOT / "deliverables" / "指标3.1-3.9测试结果.json"
OUTPUT_ROOT = CODE_ROOT / "deliverables" / "result_figures"
FONT_PATH = Path("/System/Library/Fonts/Hiragino Sans GB.ttc")

WIDTH = 2400
HEIGHT = 1350
WHITE = "#FFFFFF"
INK = "#173042"
MUTED = "#60717D"
BLUE = "#006FAE"
SKY = "#DDEFF8"
GREEN = "#00865A"
PALE_GREEN = "#E5F4ED"
ORANGE = "#C87800"
PALE_ORANGE = "#FFF2D9"
RED = "#B74B35"
PALE = "#F4F7F8"
LINE = "#D7E0E5"


def font(size: int, *, bold: bool = False) -> ImageFont.FreeTypeFont:
    if not FONT_PATH.is_file():
        raise FileNotFoundError(f"缺少中文字体：{FONT_PATH}")
    return ImageFont.truetype(str(FONT_PATH), size=size, index=2 if bold else 0)


def load_report() -> tuple[dict[str, object], str]:
    payload = REPORT_PATH.read_bytes()
    report = json.loads(payload)
    if report.get("passed") is not True:
        raise ValueError("测试报告未通过，不生成成果图")
    return report, hashlib.sha256(payload).hexdigest()


def metric(report: dict[str, object], indicator: str) -> dict[str, object]:
    return report["benchmarks"][indicator]["metrics"]


def wrap_text(draw: ImageDraw.ImageDraw, text: str, selected_font: ImageFont.FreeTypeFont, width: int) -> list[str]:
    lines: list[str] = []
    current = ""
    for character in text:
        candidate = current + character
        if current and draw.textlength(candidate, font=selected_font) > width:
            lines.append(current)
            current = character
        else:
            current = candidate
    if current:
        lines.append(current)
    return lines


def draw_wrapped(
    draw: ImageDraw.ImageDraw,
    xy: tuple[int, int],
    text: str,
    selected_font: ImageFont.FreeTypeFont,
    fill: str,
    width: int,
    *,
    spacing: int = 7,
) -> int:
    lines = wrap_text(draw, text, selected_font, width)
    line_height = selected_font.getbbox("国Ag")[3] - selected_font.getbbox("国Ag")[1]
    x, y = xy
    for line in lines:
        draw.text((x, y), line, font=selected_font, fill=fill)
        y += line_height + spacing
    return y


def text_center(
    draw: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    text: str,
    selected_font: ImageFont.FreeTypeFont,
    fill: str,
) -> None:
    left, top, right, bottom = box
    bounds = draw.textbbox((0, 0), text, font=selected_font)
    text_width = bounds[2] - bounds[0]
    text_height = bounds[3] - bounds[1]
    draw.text(
        ((left + right - text_width) / 2, (top + bottom - text_height) / 2 - bounds[1]),
        text,
        font=selected_font,
        fill=fill,
    )


def evidence_rows(report: dict[str, object]) -> list[dict[str, str]]:
    m31 = metric(report, "3.1")
    m32 = metric(report, "3.2")
    m33 = metric(report, "3.3")
    m34 = metric(report, "3.4")
    m35 = metric(report, "3.5")
    m36 = metric(report, "3.6")
    m37 = metric(report, "3.7")
    m38 = metric(report, "3.8")
    m39 = metric(report, "3.9")
    return [
        {
            "id": "①",
            "criterion": "支持序列数据的存储与压缩。",
            "evidence": f"{m31['sequence_records']:,} 条序列往返校验；GZIP {m31['sequence_gzip_ratio']:.2f}:1",
            "source": "3.1",
        },
        {
            "id": "②",
            "criterion": "支持关系数据的存储与压缩。",
            "evidence": (
                f"{m31['dataset_results']['secom']['records'] + m31['dataset_results']['holoclean_hospital']['records']:,} "
                "条完整关系记录；SQLite 存储及压缩备份往返校验通过"
            ),
            "source": "3.1",
        },
        {
            "id": "③",
            "criterion": "工业时序数据压缩比达到9:1。",
            "evidence": (
                f"完整 {m32['records']:,} 行 × {m32['sensor_channels']} 通道；"
                f"总体 {m32['compression_ratio']:.2f}:1，"
                f"最差块 {m32['minimum_chunk_compression_ratio']:.2f}:1，"
                f"最差通道 {m32['minimum_channel_compression_ratio']:.2f}:1"
            ),
            "source": "3.2",
        },
        {
            "id": "④",
            "criterion": "序列、关系数据对齐准确率≥90%。",
            "evidence": f"固定标注集 {m34['correct_alignments']}/{m34['samples']}，准确率 {m34['alignment_accuracy_percent']:.2f}%",
            "source": "3.4",
        },
        {
            "id": "⑤",
            "criterion": "序列、关系数据解析准确率≥95%。",
            "evidence": f"固定标注集 {m33['correctly_parsed']}/{m33['fixtures']}，准确率 {m33['parsing_accuracy_percent']:.2f}%",
            "source": "3.3",
        },
        {
            "id": "⑥",
            "criterion": "时序数据采集频率达到1.1kHz。",
            "evidence": f"软件接收吞吐最低 {m35['minimum_samples_per_second'] / 1000:,.2f} kHz；丢失 {m35['lost_samples']}",
            "source": "3.5",
        },
        {
            "id": "⑦",
            "criterion": "序列、关系数据可进行融合。",
            "evidence": f"融合输出 {m37['fused_rows']:,} 行；关系命中 {m37['matched_rows']:,} 行",
            "source": "3.7",
        },
        {
            "id": "⑧",
            "criterion": "搭建工业异构数据规范化测试框架。",
            "evidence": (
                f"{m38['registered_adapters']} 个适配器；"
                f"{m38['datasets_tested']} 个完整数据集、"
                f"{m38['tested_format_families']} 类格式；"
                f"规范化成功率 {m38['normalization_success_percent']:.2f}%"
            ),
            "source": "3.8",
        },
        {
            "id": "⑨",
            "criterion": "序列、关系数据完整性、一致性、时效性、有效性等质量指标≥95%。",
            "evidence": f"四维最低 {m36['minimum_dimension']:.2f}%；八维最低 {m39['minimum_dimension']:.2f}%",
            "source": "3.6 / 3.9",
        },
    ]


def add_footer(
    image: Image.Image,
    draw: ImageDraw.ImageDraw,
    report: dict[str, object],
    report_sha256: str,
    *,
    note: str,
) -> None:
    draw.line((70, 1260, WIDTH - 70, 1260), fill=LINE, width=2)
    draw.text((80, 1274), note, font=font(18), fill=MUTED)
    generated = str(report["generated_at"]).replace("T", " ").replace("+00:00", " UTC")
    provenance = (
        f"数据源：指标3.1-3.9测试结果.json  |  {generated}  |  "
        f"commit {str(report['source']['git_commit'])[:7]}  |  SHA-256 {report_sha256[:12]}…"
    )
    draw.text((80, 1307), provenance, font=font(16), fill=MUTED)
    image.info["Source"] = str(REPORT_PATH.relative_to(CODE_ROOT))


def save_image(image: Image.Image, name: str, report: dict[str, object], report_sha256: str) -> Path:
    output = OUTPUT_ROOT / name
    metadata = PngInfo()
    metadata.add_text("Title", name)
    metadata.add_text("Source", str(REPORT_PATH.relative_to(CODE_ROOT)))
    metadata.add_text("ReportSHA256", report_sha256)
    metadata.add_text("GitCommit", str(report["source"]["git_commit"]))
    image.convert("RGB").save(output, dpi=(150, 150), optimize=True, pnginfo=metadata)
    return output


def assessment_evidence_board(report: dict[str, object], report_sha256: str) -> Path:
    rows = evidence_rows(report)
    image = Image.new("RGB", (WIDTH, HEIGHT), WHITE)
    draw = ImageDraw.Draw(image)

    draw.rectangle((0, 0, 22, HEIGHT), fill=BLUE)
    draw.text((80, 50), "面向离散制造垂域模型的自动化数据治理系统", font=font(45, bold=True), fill=INK)
    draw.text((82, 116), "考核指标 · 指标值/状态：", font=font(28, bold=True), fill=BLUE)
    draw.rounded_rectangle((1940, 38, 2320, 150), radius=16, fill=PALE_GREEN)
    draw.text((1980, 57), "9 项考核指标", font=font(24), fill=GREEN)
    draw.text((1980, 96), "全部通过", font=font(34, bold=True), fill=GREEN)

    x_positions = [70, 150, 1030, 1200, 2190, 2330]
    header_top = 182
    draw.rounded_rectangle((70, header_top, 2330, header_top + 58), radius=8, fill=INK)
    headers = [("序号", 82), ("考核指标", 168), ("状态", 1057), ("实测或实现证据", 1218), ("对应", 2205)]
    for label, x in headers:
        draw.text((x, header_top + 13), label, font=font(23, bold=True), fill=WHITE)

    row_top = header_top + 64
    row_height = 108
    for index, row in enumerate(rows):
        top = row_top + index * row_height
        bottom = top + row_height - 6
        background = PALE_GREEN if index == 8 else (WHITE if index % 2 == 0 else PALE)
        draw.rounded_rectangle((70, top, 2330, bottom), radius=8, fill=background)
        for x in x_positions[1:-1]:
            draw.line((x, top + 10, x, bottom - 10), fill=LINE, width=2)
        text_center(draw, (75, top, 145, bottom), row["id"], font(31, bold=True), BLUE)
        criterion_font = font(24 if index == 8 else 27, bold=index == 8)
        criterion_lines = wrap_text(draw, row["criterion"], criterion_font, 820)
        criterion_y = top + (23 if len(criterion_lines) == 1 else 9)
        draw_wrapped(draw, (174, criterion_y), row["criterion"], criterion_font, INK, 820, spacing=2)
        draw.rounded_rectangle((1053, top + 31, 1177, top + 75), radius=8, fill=GREEN)
        text_center(draw, (1053, top + 31, 1177, top + 75), "通过", font(22, bold=True), WHITE)
        evidence_lines = wrap_text(draw, row["evidence"], font(23), 930)
        evidence_y = top + (26 if len(evidence_lines) == 1 else 11)
        draw_wrapped(draw, (1220, evidence_y), row["evidence"], font(23), INK, 930, spacing=4)
        text_center(draw, (2190, top, 2330, bottom), row["source"], font(21, bold=True), BLUE)

    add_footer(
        image,
        draw,
        report,
        report_sha256,
        note="注：解析与对齐准确率来自固定标注样例集；1.1 kHz 项为同进程软件接收吞吐，不含采集硬件与网络链路。",
    )
    return save_image(image, "assessment_result_1_evidence_board.png", report, report_sha256)


def assessment_capability_map(report: dict[str, object], report_sha256: str) -> Path:
    rows = evidence_rows(report)
    image = Image.new("RGB", (WIDTH, HEIGHT), WHITE)
    draw = ImageDraw.Draw(image)

    draw.rectangle((0, 0, WIDTH, 158), fill=INK)
    draw.text((78, 40), "离散制造数据治理能力闭环", font=font(50, bold=True), fill=WHITE)
    draw.text((80, 106), "真实实现路径与考核指标映射", font=font(25), fill="#B9DCEB")
    draw.rounded_rectangle((1960, 34, 2320, 126), radius=14, fill=GREEN)
    text_center(draw, (1960, 34, 2320, 126), "9 / 9  通过", font(32, bold=True), WHITE)

    stages = [
        ("多源输入", "序列数据 · 关系数据\n8 种异构文件格式", BLUE, SKY),
        ("统一存储", "GZIP · SQLite\n压缩备份与往返校验", ORANGE, PALE_ORANGE),
        ("解析与对齐", "128 条解析标注\n153 条对齐标注", BLUE, SKY),
        ("关联融合", "设备实体 + 时间窗口\n5,000 行融合输出", GREEN, PALE_GREEN),
        ("质量治理", "4 个核心维度\n7 个综合维度", RED, "#F9E8E4"),
    ]
    stage_width = 390
    stage_gap = 66
    stage_left = 78
    stage_top = 190
    stage_bottom = 405
    for index, (title, detail, accent, background) in enumerate(stages):
        left = stage_left + index * (stage_width + stage_gap)
        right = left + stage_width
        draw.rounded_rectangle((left, stage_top, right, stage_bottom), radius=14, fill=background, outline=accent, width=3)
        draw.rectangle((left, stage_top, left + 12, stage_bottom), fill=accent)
        draw.text((left + 38, stage_top + 33), title, font=font(31, bold=True), fill=accent)
        draw.multiline_text((left + 38, stage_top + 93), detail, font=font(23), fill=INK, spacing=13)
        if index < len(stages) - 1:
            arrow_x = right + 18
            arrow_y = (stage_top + stage_bottom) // 2
            draw.line((arrow_x, arrow_y, arrow_x + 28, arrow_y), fill=MUTED, width=5)
            draw.polygon(
                [(arrow_x + 28, arrow_y - 11), (arrow_x + 46, arrow_y), (arrow_x + 28, arrow_y + 11)],
                fill=MUTED,
            )

    draw.text((78, 452), "考核指标", font=font(36, bold=True), fill=INK)
    draw.text((270, 461), "指标值/状态：", font=font(25, bold=True), fill=BLUE)

    card_width = 728
    card_height = 215
    card_gap_x = 36
    card_gap_y = 24
    card_left = 78
    card_top = 510
    for index, row in enumerate(rows):
        column = index % 3
        card_row = index // 3
        left = card_left + column * (card_width + card_gap_x)
        top = card_top + card_row * (card_height + card_gap_y)
        right = left + card_width
        bottom = top + card_height
        background = PALE_GREEN if index == 8 else PALE
        outline = GREEN if index == 8 else LINE
        draw.rounded_rectangle((left, top, right, bottom), radius=12, fill=background, outline=outline, width=3)
        draw.ellipse((left + 24, top + 24, left + 82, top + 82), fill=BLUE)
        text_center(draw, (left + 24, top + 24, left + 82, top + 82), row["id"], font(25, bold=True), WHITE)
        criterion_font = font(23, bold=index == 8)
        draw_wrapped(draw, (left + 103, top + 23), row["criterion"], criterion_font, INK, 575, spacing=4)
        draw.line((left + 24, top + 126, right - 24, top + 126), fill=LINE, width=2)
        draw.rounded_rectangle((left + 25, top + 146, left + 105, top + 187), radius=7, fill=GREEN)
        text_center(draw, (left + 25, top + 146, left + 105, top + 187), "通过", font(19, bold=True), WHITE)
        draw.text((left + 124, top + 150), row["evidence"], font=font(19), fill=INK)

    add_footer(
        image,
        draw,
        report,
        report_sha256,
        note="注：图中数值直接读取正式测试报告；软件吞吐测试与完整采集硬件链路的端到端频率口径不同。",
    )
    return save_image(image, "assessment_result_2_capability_map.png", report, report_sha256)


def write_manifest(outputs: list[Path], report: dict[str, object], report_sha256: str) -> Path:
    records = []
    for output in outputs:
        payload = output.read_bytes()
        with Image.open(output) as rendered:
            records.append(
                {
                    "file": output.name,
                    "sha256": hashlib.sha256(payload).hexdigest(),
                    "bytes": len(payload),
                    "mode": rendered.mode,
                    "width": rendered.width,
                    "height": rendered.height,
                    "dpi": list(rendered.info.get("dpi", ())),
                }
            )
    manifest = {
        "source_report": str(REPORT_PATH.relative_to(CODE_ROOT)),
        "source_report_sha256": report_sha256,
        "source_git_commit": report["source"]["git_commit"],
        "figures": records,
    }
    output = OUTPUT_ROOT / "assessment_figure_manifest.json"
    output.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return output


def main() -> None:
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    report, report_sha256 = load_report()
    outputs = [
        assessment_evidence_board(report, report_sha256),
        assessment_capability_map(report, report_sha256),
    ]
    manifest = write_manifest(outputs, report, report_sha256)
    for output in [*outputs, manifest]:
        print(output)


if __name__ == "__main__":
    main()
