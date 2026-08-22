"""Build a deterministic, self-verifying algorithm and test delivery archive."""

from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path


CODE_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = CODE_ROOT.parent
MANIFEST_PATH = CODE_ROOT / "algorithm_manifest.json"
OUTPUT_PATH = CODE_ROOT / "deliverables" / "课题三指标3.1-3.9算法及测试材料.zip"
REPORT_PATH = CODE_ROOT / "deliverables" / "指标3.1-3.9测试结果.json"
FIXED_ZIP_TIME = (2026, 1, 1, 0, 0, 0)


def delivery_files() -> list[Path]:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    relative_paths = {
        Path("code/README.md"),
        Path("code/REFERENCES.md"),
        Path("code/requirements.txt"),
        Path("code/algorithm_manifest.json"),
        Path("code/run_indicator_tests.py"),
        Path("code/integrations/README.md"),
        Path("code/integrations/manifest.example.json"),
        Path("code/integrations/research_methods/__init__.py"),
        Path("code/integrations/research_methods/adapter.py"),
        Path("code/tests/test_indicator_runner.py"),
        Path("code/tools/build_benchmark_fixtures.py"),
        Path("code/tools/build_delivery_package.py"),
        Path("code/tools/build_test_guide_docx.py"),
        Path("code/docs/课题三指标3.1-3.9算法测试大纲与运行说明.md"),
        Path("code/docs/课题三指标3.1-3.9算法测试大纲与运行说明.docx"),
        Path("code/deliverables/指标3.1-3.9测试结果.json"),
    }
    for value in manifest.get("support_files", []):
        relative_paths.add(Path("code") / value)
    for spec in manifest["indicators"].values():
        for field in ("algorithm_files", "native_reference_files", "test_data_files"):
            for value in spec.get(field, []):
                relative_paths.add(Path("code") / value)
        relative_paths.add(Path("code") / spec["test_file"])

    resolved_files = []
    for relative_path in sorted(relative_paths, key=str):
        resolved = (REPOSITORY_ROOT / relative_path).resolve()
        try:
            resolved.relative_to(REPOSITORY_ROOT.resolve())
        except ValueError as exc:
            raise ValueError(f"交付文件超出项目目录: {relative_path}") from exc
        if not resolved.is_file():
            raise FileNotFoundError(f"交付文件不存在: {relative_path}")
        resolved_files.append(resolved)
    return resolved_files


def package_manifest(files: list[Path]) -> bytes:
    entries = {}
    for path in files:
        archive_name = path.relative_to(REPOSITORY_ROOT).as_posix()
        payload = path.read_bytes()
        entries[archive_name] = {
            "bytes": len(payload),
            "sha256": hashlib.sha256(payload).hexdigest(),
        }
    manifest = {
        "format_version": 1,
        "project": "面向离散制造垂域模型的自动化数据治理系统",
        "entry_count": len(entries),
        "entries": entries,
    }
    return (json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode(
        "utf-8"
    )


def validate_report_source(files: list[Path], report_path: Path = REPORT_PATH) -> None:
    report = json.loads(report_path.read_text(encoding="utf-8"))
    if report.get("passed") is not True:
        raise ValueError("测试报告未通过，拒绝构建交付包")
    source = report.get("source")
    if not isinstance(source, dict) or source.get("error"):
        raise ValueError("测试报告缺少可用的源码证据")
    expected_hashes = source.get("source_file_sha256")
    if not isinstance(expected_hashes, dict) or not expected_hashes:
        raise ValueError("测试报告缺少逐文件源码哈希")

    packaged_paths = {path.relative_to(REPOSITORY_ROOT).as_posix() for path in files}
    combined = hashlib.sha256()
    for relative_path, expected_digest in sorted(expected_hashes.items()):
        if relative_path not in packaged_paths:
            raise ValueError(f"源码证据文件未纳入交付包: {relative_path}")
        resolved = (REPOSITORY_ROOT / relative_path).resolve()
        try:
            resolved.relative_to(REPOSITORY_ROOT.resolve())
        except ValueError as exc:
            raise ValueError(f"源码证据路径超出项目目录: {relative_path}") from exc
        actual_digest = hashlib.sha256(resolved.read_bytes()).hexdigest()
        if actual_digest != expected_digest:
            raise ValueError(f"测试报告与当前源码不一致: {relative_path}")
        combined.update(relative_path.encode("utf-8"))
        combined.update(b"\0")
        combined.update(actual_digest.encode("ascii"))
        combined.update(b"\n")
    if combined.hexdigest() != source.get("source_tree_sha256"):
        raise ValueError("测试报告的组合源码哈希无效")
    manifest_digest = hashlib.sha256(MANIFEST_PATH.read_bytes()).hexdigest()
    if manifest_digest != source.get("algorithm_manifest_sha256"):
        raise ValueError("测试报告与当前算法清单不一致")


def write_entry(archive: zipfile.ZipFile, name: str, payload: bytes) -> None:
    info = zipfile.ZipInfo(name, date_time=FIXED_ZIP_TIME)
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = 0o100644 << 16
    info.create_system = 3
    archive.writestr(info, payload, compresslevel=9)


def build_package(output_path: Path = OUTPUT_PATH, *, validate_evidence: bool = True) -> Path:
    files = delivery_files()
    if validate_evidence:
        validate_report_source(files)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_path.with_suffix(output_path.suffix + ".tmp")
    with zipfile.ZipFile(temporary, "w") as archive:
        for path in files:
            write_entry(
                archive,
                path.relative_to(REPOSITORY_ROOT).as_posix(),
                path.read_bytes(),
            )
        write_entry(archive, "PACKAGE_MANIFEST.json", package_manifest(files))
    temporary.replace(output_path)
    return output_path


def main() -> None:
    output = build_package()
    print(output)
    print(hashlib.sha256(output.read_bytes()).hexdigest())


if __name__ == "__main__":
    main()
