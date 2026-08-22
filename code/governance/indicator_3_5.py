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
    def __init__(self, capacity: int = 250_000, max_batch_size: int = 20_000) -> None:
        if not isinstance(capacity, int) or isinstance(capacity, bool) or capacity <= 0:
            raise ValueError("缓冲区容量必须是正整数")
        if (
            not isinstance(max_batch_size, int)
            or isinstance(max_batch_size, bool)
            or max_batch_size <= 0
        ):
            raise ValueError("最大批次必须是正整数")
        self._samples: deque[dict[str, Any]] = deque(maxlen=capacity)
        self._lock = Lock()
        self.max_batch_size = max_batch_size
        self.total_ingested = 0

    def ingest_batch(self, samples: Iterable[dict[str, Any]]) -> int:
        batch = list(islice(samples, self.max_batch_size + 1))
        if len(batch) > self.max_batch_size:
            raise ValueError(f"采集批次超过上限 {self.max_batch_size}")
        if not all(isinstance(sample, dict) for sample in batch):
            raise ValueError("采集批次只能包含对象记录")
        with self._lock:
            self._samples.extend(batch)
            self.total_ingested += len(batch)
        return len(batch)

    def snapshot(self, limit: int = 1000) -> list[dict[str, Any]]:
        if not isinstance(limit, int) or isinstance(limit, bool):
            raise ValueError("快照条数必须是整数")
        with self._lock:
            if limit <= 0:
                return []
            start = max(len(self._samples) - limit, 0)
            return list(islice(self._samples, start, None))


def benchmark() -> dict[str, Any]:
    count = 120_000
    batch_size = 1000
    repeats = 7
    warmup_runs = 1
    throughputs: list[float] = []
    elapsed_runs: list[float] = []

    def ingest_once(run_index: int) -> tuple[float, int]:
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
        if buffer.total_ingested != count or len(buffer.snapshot(count)) != count:
            raise AssertionError("采集缓冲区发生记录丢失")
        return elapsed, count / elapsed

    for warmup_index in range(warmup_runs):
        ingest_once(-(warmup_index + 1))
    for run_index in range(repeats):
        elapsed, throughput = ingest_once(run_index)
        elapsed_runs.append(elapsed)
        throughputs.append(throughput)

    median_throughput = statistics.median(throughputs)
    minimum_throughput = min(throughputs)
    maximum_throughput = max(throughputs)
    throughput_cv = (
        statistics.stdev(throughputs) / statistics.mean(throughputs)
        if len(throughputs) > 1
        else 0.0
    )
    return {
        "indicator": ID,
        "title": TITLE,
        "target": MILESTONE_TARGET,
        "passed": minimum_throughput >= 1100.0,
        "metrics": {
            "samples": count,
            "repeats": repeats,
            "warmup_runs": warmup_runs,
            "batch_size": batch_size,
            "clock": "time.perf_counter_ns",
            "median_elapsed_seconds": round(statistics.median(elapsed_runs), 6),
            "ingestion_samples_per_second": round(median_throughput, 2),
            "minimum_samples_per_second": round(minimum_throughput, 2),
            "maximum_samples_per_second": round(maximum_throughput, 2),
            "throughput_coefficient_of_variation": round(throughput_cv, 6),
            "run_samples_per_second": [round(rate, 2) for rate in throughputs],
            "equivalent_frequency_khz": round(median_throughput / 1000.0, 2),
            "target_samples_per_second": 1100,
            "lost_samples": 0,
        },
        "method": "锁保护批量写入环形缓冲区；预热后在同一进程重复测量并披露每次、最低、中位、最高吞吐和变异系数。该结果衡量软件接收能力，不替代现场采集卡端到端测试。",
    }
