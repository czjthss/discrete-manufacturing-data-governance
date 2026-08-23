"""Indicator 3.5: high-frequency industrial time-series ingestion."""

from __future__ import annotations

import time
import statistics
from collections import deque
from itertools import islice
from threading import Lock
from typing import Any, Iterable

from .public_benchmarks import (
    benchmark_provenance,
    iter_metropt_full_sequence_batches,
    load_forda_series,
)


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


def benchmark_ingestion_source(
    source: tuple[dict[str, Any], ...], *, batch_size: int, repeats: int, warmup_runs: int
) -> dict[str, Any]:
    count = len(source)
    throughputs: list[float] = []
    elapsed_runs: list[float] = []

    def ingest_once() -> tuple[float, float, int]:
        buffer = HighFrequencyBuffer(capacity=count)
        start = time.perf_counter_ns()
        for offset in range(0, count, batch_size):
            buffer.ingest_batch(source[offset : offset + batch_size])
        elapsed = max((time.perf_counter_ns() - start) / 1_000_000_000, 1e-9)
        snapshot = buffer.snapshot(count)
        lost = count - len(snapshot)
        if (
            buffer.total_ingested != count
            or lost
            or snapshot[0] != source[0]
            or snapshot[-1] != source[-1]
        ):
            raise AssertionError("采集缓冲区发生记录丢失")
        return elapsed, count / elapsed, lost

    for _ in range(warmup_runs):
        ingest_once()
    lost_samples = 0
    for _ in range(repeats):
        elapsed, throughput, lost = ingest_once()
        elapsed_runs.append(elapsed)
        throughputs.append(throughput)
        lost_samples += lost

    median_throughput = statistics.median(throughputs)
    minimum_throughput = min(throughputs)
    maximum_throughput = max(throughputs)
    throughput_cv = (
        statistics.stdev(throughputs) / statistics.mean(throughputs)
        if len(throughputs) > 1
        else 0.0
    )
    return {
        "samples": count,
        "repeats": repeats,
        "warmup_runs": warmup_runs,
        "batch_size": batch_size,
        "median_elapsed_seconds": round(statistics.median(elapsed_runs), 6),
        "ingestion_samples_per_second": round(median_throughput, 2),
        "minimum_samples_per_second": round(minimum_throughput, 2),
        "maximum_samples_per_second": round(maximum_throughput, 2),
        "throughput_coefficient_of_variation": round(throughput_cv, 6),
        "run_samples_per_second": [round(rate, 2) for rate in throughputs],
        "equivalent_frequency_khz": round(median_throughput / 1000.0, 2),
        "target_samples_per_second": 1100,
        "lost_samples": lost_samples,
        "software_throughput_passed": minimum_throughput >= 1100.0
        and lost_samples == 0,
    }


def benchmark_ingestion_batches(
    source_factory: Any,
    *,
    expected_samples: int,
    batch_size: int,
    repeats: int,
    warmup_runs: int,
) -> dict[str, Any]:
    throughputs: list[float] = []
    elapsed_runs: list[float] = []

    def ingest_once(*, stop_after_first_source_batch: bool = False) -> tuple[float, int]:
        elapsed_ns = 0
        ingested = 0
        for source_batch in source_factory():
            for offset in range(0, len(source_batch), batch_size):
                batch = source_batch[offset : offset + batch_size]
                buffer = HighFrequencyBuffer(
                    capacity=max(len(batch), 1), max_batch_size=batch_size
                )
                started = time.perf_counter_ns()
                buffer.ingest_batch(batch)
                elapsed_ns += time.perf_counter_ns() - started
                snapshot = buffer.snapshot(len(batch))
                if snapshot != batch or buffer.total_ingested != len(batch):
                    raise AssertionError("采集批次在下游排空前发生记录丢失")
                ingested += len(batch)
            if stop_after_first_source_batch:
                break
        return max(elapsed_ns / 1_000_000_000, 1e-9), ingested

    for _ in range(warmup_runs):
        ingest_once(stop_after_first_source_batch=True)
    for _ in range(repeats):
        elapsed, ingested = ingest_once()
        if ingested != expected_samples:
            raise AssertionError("完整数据重放记录数与公开清单不一致")
        elapsed_runs.append(elapsed)
        throughputs.append(ingested / elapsed)

    median_throughput = statistics.median(throughputs)
    minimum_throughput = min(throughputs)
    maximum_throughput = max(throughputs)
    throughput_cv = (
        statistics.stdev(throughputs) / statistics.mean(throughputs)
        if len(throughputs) > 1
        else 0.0
    )
    return {
        "samples": expected_samples,
        "full_dataset": True,
        "repeats": repeats,
        "warmup_runs": warmup_runs,
        "batch_size": batch_size,
        "median_elapsed_seconds": round(statistics.median(elapsed_runs), 6),
        "ingestion_samples_per_second": round(median_throughput, 2),
        "minimum_samples_per_second": round(minimum_throughput, 2),
        "maximum_samples_per_second": round(maximum_throughput, 2),
        "throughput_coefficient_of_variation": round(throughput_cv, 6),
        "run_samples_per_second": [round(rate, 2) for rate in throughputs],
        "equivalent_frequency_khz": round(median_throughput / 1000.0, 2),
        "target_samples_per_second": 1100,
        "lost_samples": 0,
        "software_throughput_passed": minimum_throughput >= 1100.0,
    }


def benchmark() -> dict[str, Any]:
    batch_size = 1024
    repeats = 7
    warmup_runs = 1
    metro_result = benchmark_ingestion_batches(
        iter_metropt_full_sequence_batches,
        expected_samples=1_516_948,
        batch_size=batch_size,
        repeats=repeats,
        warmup_runs=warmup_runs,
    )
    forda_result = benchmark_ingestion_source(
        load_forda_series(),
        batch_size=batch_size,
        repeats=repeats,
        warmup_runs=warmup_runs,
    )
    dataset_results = {
        "metropt3": {
            **metro_result,
            "channels": 15,
            "native_sampling_hz": 1,
        },
        "forda": {
            **forda_result,
            "full_dataset": True,
            "channels": 1,
            "points_per_series": 500,
            "native_sampling_hz": None,
        },
    }
    return {
        "indicator": ID,
        "title": TITLE,
        "target": MILESTONE_TARGET,
        "passed": (
            metro_result["software_throughput_passed"]
            and forda_result["software_throughput_passed"]
            and metro_result["lost_samples"] == 0
            and forda_result["lost_samples"] == 0
        ),
        "metrics": {
            "dataset": "MetroPT-3 and UCR FordA TRAIN+TEST",
            "samples": metro_result["samples"] + forda_result["samples"],
            "repeats": repeats,
            "warmup_runs": warmup_runs,
            "batch_size": batch_size,
            "clock": "time.perf_counter_ns",
            "minimum_samples_per_second": min(
                metro_result["minimum_samples_per_second"],
                forda_result["minimum_samples_per_second"],
            ),
            "target_samples_per_second": 1100,
            "lost_samples": metro_result["lost_samples"] + forda_result["lost_samples"],
            "dataset_results": dataset_results,
        },
        "benchmark_provenance": benchmark_provenance(("metropt3", "forda")),
        "method": "在同一锁保护批量接收边界上完整流式重放 MetroPT-3 全部 1,516,948 条记录，并完整重放 UCR FordA TRAIN+TEST 全部 4,921 条序列；预热后各重复七次，逐次记录纯内存接收吞吐并逐批排空校验零丢失。1.1 kHz 判据表示软件接收能力，不等同于数据集原生传感器采样率。",
    }
