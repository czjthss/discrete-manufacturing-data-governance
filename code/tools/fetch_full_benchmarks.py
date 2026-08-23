"""Fetch and verify large official benchmark archives kept outside Git."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import urllib.request
from pathlib import Path


CODE_ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = CODE_ROOT / "governance" / "benchmark_data" / "public" / "benchmark_manifest.json"
DEFAULT_CACHE_ROOT = CODE_ROOT / "data" / "benchmark_cache"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def fetch(url: str, target: Path, expected_sha256: str) -> Path:
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.is_file() and sha256(target) == expected_sha256:
        return target
    temporary = target.with_name(f".{target.name}.{os.getpid()}.part")
    request = urllib.request.Request(url, headers={"User-Agent": "data-governance-benchmark/1.0"})
    try:
        with urllib.request.urlopen(request, timeout=60) as response, temporary.open("wb") as output:
            while block := response.read(1024 * 1024):
                output.write(block)
        actual = sha256(temporary)
        if actual != expected_sha256:
            raise ValueError(
                f"下载文件 SHA-256 不匹配: expected={expected_sha256}, actual={actual}"
            )
        temporary.replace(target)
    finally:
        if temporary.exists():
            temporary.unlink()
    return target


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="下载并校验完整公开基准归档")
    parser.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE_ROOT)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    specification = manifest["datasets"]["metropt3"]["full_archive"]
    target = args.cache_dir / specification["cache_name"]
    print(fetch(specification["url"], target, specification["sha256"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
