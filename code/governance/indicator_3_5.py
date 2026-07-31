"""Indicator 3.5: high-frequency industrial time-series ingestion."""

from __future__ import annotations

import time
from collections import deque
from itertools import islice
from threading import Lock
from typing import Any, Iterable


ID = "3.5"
TITLE = "1.1kHz 时序采集"
MILESTONE_TARGET = "时序数据采集频率达到 1.1kHz"


class HighFrequencyBuffer:
    def __init__(self, capacity: int = 250_000) -> None:
        self._samples: deque[dict[str, Any]] = deque(maxlen=capacity)
        self._lock = Lock()
        self.total_ingested = 0

    def ingest_batch(self, samples: Iterable[dict[str, Any]]) -> int:
        batch = list(samples)
        with self._lock:
            self._samples.extend(batch)
            self.total_ingested += len(batch)
        return len(batch)

    def snapshot(self, limit: int = 1000) -> list[dict[str, Any]]:
        with self._lock:
            if limit <= 0:
                return []
            start = max(len(self._samples) - limit, 0)
            return list(islice(self._samples, start, None))


def benchmark() -> dict[str, Any]:
    buffer = HighFrequencyBuffer()
    count = 150_000
    batch_size = 1000
    start = time.perf_counter()
    for offset in range(0, count, batch_size):
        buffer.ingest_batch(
            {
                "timestamp_ns": offset + index,
                "equipment_id": "CNC-01",
                "value": 42.0 + ((offset + index) % 100) / 100,
            }
            for index in range(batch_size)
        )
    elapsed = max(time.perf_counter() - start, 1e-9)
    throughput = count / elapsed
    return {
        "indicator": ID,
        "title": TITLE,
        "target": MILESTONE_TARGET,
        "passed": throughput >= 1100.0,
        "metrics": {
            "samples": count,
            "elapsed_seconds": round(elapsed, 6),
            "ingestion_samples_per_second": round(throughput, 2),
            "equivalent_frequency_khz": round(throughput / 1000.0, 2),
            "target_samples_per_second": 1100,
        },
        "method": "锁保护批量写入环形缓冲区；该结果衡量软件接收能力，不替代现场采集卡端到端测试。",
    }
