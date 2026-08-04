"""Indicator 3.5: high-frequency industrial time-series ingestion."""

from __future__ import annotations

import time
import statistics
from collections import deque
from itertools import islice
from threading import Lock
from typing import Any, Iterable


ID = "3.5"
TITLE = "1.1kHz 时序采集"
MILESTONE_TARGET = "时序数据采集频率达到 1.1kHz"


class HighFrequencyBuffer:
    def __init__(self, capacity: int = 250_000) -> None:
        if not isinstance(capacity, int) or isinstance(capacity, bool) or capacity <= 0:
            raise ValueError("缓冲区容量必须是正整数")
        self._samples: deque[dict[str, Any]] = deque(maxlen=capacity)
        self._lock = Lock()
        self.total_ingested = 0

    def ingest_batch(self, samples: Iterable[dict[str, Any]]) -> int:
        batch = list(samples)
        if not all(isinstance(sample, dict) for sample in batch):
            raise ValueError("采集批次只能包含对象记录")
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
    count = 120_000
    batch_size = 1000
    repeats = 7
    throughputs: list[float] = []
    elapsed_runs: list[float] = []
    for run_index in range(repeats):
        buffer = HighFrequencyBuffer(capacity=count)
        start = time.perf_counter_ns()
        for offset in range(0, count, batch_size):
            buffer.ingest_batch(
                {
                    "timestamp_ns": run_index * count + offset + index,
                    "equipment_id": f"CNC-{(offset // batch_size) % 8 + 1:02d}",
                    "value": 42.0 + ((offset + index) % 100) / 100,
                }
                for index in range(batch_size)
            )
        elapsed = max((time.perf_counter_ns() - start) / 1_000_000_000, 1e-9)
        elapsed_runs.append(elapsed)
        throughputs.append(count / elapsed)
        if buffer.total_ingested != count or len(buffer.snapshot(count)) != count:
            raise AssertionError("采集缓冲区发生记录丢失")
    sorted_rates = sorted(throughputs)
    median_throughput = statistics.median(throughputs)
    minimum_throughput = min(throughputs)
    return {
        "indicator": ID,
        "title": TITLE,
        "target": MILESTONE_TARGET,
        "passed": minimum_throughput >= 1100.0,
        "metrics": {
            "samples": count,
            "repeats": repeats,
            "median_elapsed_seconds": round(statistics.median(elapsed_runs), 6),
            "ingestion_samples_per_second": round(median_throughput, 2),
            "minimum_samples_per_second": round(minimum_throughput, 2),
            "p95_samples_per_second": round(sorted_rates[int(0.95 * (repeats - 1))], 2),
            "equivalent_frequency_khz": round(median_throughput / 1000.0, 2),
            "target_samples_per_second": 1100,
            "lost_samples": 0,
        },
        "method": "锁保护批量写入环形缓冲区，重复测量并报告最低与中位吞吐；该结果衡量软件接收能力，不替代现场采集卡端到端测试。",
    }
