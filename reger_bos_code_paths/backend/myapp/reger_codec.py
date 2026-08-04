"""REGER block reordering codec used by the benchmark.

This implementation keeps the REGER idea explicit: a block is encoded as
``(time, value)`` rows, candidate row orders are scored by the encoded byte
cost, and decompression restores the original row order by sorting the decoded
time stream inside each block.  The value streams use block-level residual minima plus RLE-coded
per-segment bit widths, matching the important storage shape of the reference
REGER test without carrying its experiment-only Java scaffolding.
"""

from __future__ import annotations

import bisect
import math
import multiprocessing
import os
import struct
import time
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from typing import Iterable, Sequence

from .benchmark_loss import accumulate_double_list_loss, accumulate_long_list_loss


U64_MASK = (1 << 64) - 1
I64_MIN = -(1 << 63)
I64_MAX = (1 << 63) - 1

MULTI_MAGIC = b"REGER3"
LEGACY_MAGIC = b"REGER1"

RAW_SERIES = 0
CONST_SERIES = 1
FOR_SERIES = 2
DELTA_SERIES = 3
TIME_LINEAR_SERIES = 4
PREV_LINEAR_SERIES = 5

ORDER_PERMUTED_FLAG = 1
TIME_STREAM_FLAG = 2

MULTI_HEADER_STRUCT = struct.Struct("<6sIHHHI")
BLOCK_HEADER_STRUCT = struct.Struct("<HBI")
SERIES_HEADER_STRUCT = struct.Struct("<BI")


@dataclass(frozen=True)
class _SeriesPayload:
    mode: int
    payload: bytes


@dataclass(frozen=True)
class _BlockPayload:
    flags: int
    payload: bytes


class _CandidateTooLarge(Exception):
    pass


def _default_block_size() -> int:
    raw = os.environ.get("WEB_COMPRESSION_REGER_BLOCK_SIZE", "").strip()
    try:
        n = int(raw)
        return n if n > 0 else 513
    except ValueError:
        return 513


def _reger_profile() -> str:
    raw = os.environ.get("WEB_COMPRESSION_REGER_PROFILE", "").strip().lower()
    return "fast" if raw == "fast" else "balanced"


def _fast_profile() -> bool:
    return _reger_profile() == "fast"


def _default_segment_size() -> int:
    raw = os.environ.get("WEB_COMPRESSION_REGER_SEGMENT_SIZE", "").strip()
    try:
        n = int(raw)
        return n if n > 0 else 16
    except ValueError:
        return 16


def _default_reorder_iterations(column_count: int = 1) -> int:
    raw = os.environ.get("WEB_COMPRESSION_REGER_REORDER_ITERS", "").strip()
    try:
        n = int(raw)
        return max(0, min(n, 20))
    except ValueError:
        if _fast_profile():
            return 0
        return 4 if column_count == 1 else 0


def _default_workers(block_count: int) -> int:
    raw = os.environ.get("WEB_COMPRESSION_REGER_WORKERS", "").strip()
    try:
        workers = int(raw) if raw else 1
    except ValueError:
        workers = 1
    return max(1, min(workers, block_count, os.cpu_count() or 1))


def _to_u64(value: int) -> int:
    return int(value) & U64_MASK


def _to_i64(value: int) -> int:
    u = int(value) & U64_MASK
    return u - (1 << 64) if u >= (1 << 63) else u


def _validate_i64(value: int) -> int:
    v = int(value)
    if v < I64_MIN or v > I64_MAX:
        raise OverflowError("REGER int64 value out of range")
    return v


def _double_to_i64(value: float) -> int:
    bits = struct.unpack("<Q", struct.pack("<d", float(value)))[0]
    return _to_i64(bits)


def _i64_to_double(value: int) -> float:
    return struct.unpack("<d", struct.pack("<Q", _to_u64(value)))[0]


def _ceil_log2(n: int) -> int:
    return max(0, int(n - 1).bit_length())


def _pack_u64_values(values: Sequence[int], width: int) -> bytes:
    if not values or width <= 0:
        return b""
    if width >= 64:
        return b"".join(struct.pack("<Q", _to_u64(v)) for v in values)
    total_bits = len(values) * width
    acc = 0
    mask = (1 << width) - 1
    for raw in values:
        acc = (acc << width) | (int(raw) & mask)
    acc <<= (-total_bits) & 7
    return acc.to_bytes((total_bits + 7) // 8, "big")


def _pack_u64_values_range(values: Sequence[int], start: int, end: int, width: int) -> bytes:
    if start >= end or width <= 0:
        return b""
    if width >= 64:
        return b"".join(struct.pack("<Q", _to_u64(values[i])) for i in range(start, end))
    total_bits = (end - start) * width
    mask = (1 << width) - 1
    acc = 0
    for i in range(start, end):
        acc = (acc << width) | (values[i] & mask)
    acc <<= (-total_bits) & 7
    return acc.to_bytes((total_bits + 7) // 8, "big")


def _unpack_u64_values(data: bytes, count: int, width: int) -> list[int]:
    if width <= 0:
        return [0] * count
    if width >= 64:
        return [struct.unpack_from("<Q", data, i * 8)[0] for i in range(count)]
    total_bits = count * width
    acc = int.from_bytes(data, "big") >> ((-total_bits) & 7)
    mask = (1 << width) - 1
    out = [0] * count
    for idx in range(count - 1, -1, -1):
        out[idx] = acc & mask
        acc >>= width
    return out


def _rle_widths(widths: Sequence[int]) -> bytes:
    runs: list[tuple[int, int]] = []
    for width in widths:
        w = int(width)
        if not runs or runs[-1][1] != w or runs[-1][0] == 255:
            runs.append((1, w))
        else:
            runs[-1] = (runs[-1][0] + 1, w)
    out = bytearray(struct.pack("<H", len(runs)))
    for count, width in runs:
        out.extend(struct.pack("<BB", count, width))
    return bytes(out)


def _read_rle_widths(payload: bytes, pos: int) -> tuple[list[int], int]:
    run_count = struct.unpack_from("<H", payload, pos)[0]
    pos += 2
    widths: list[int] = []
    for _ in range(run_count):
        count, width = struct.unpack_from("<BB", payload, pos)
        pos += 2
        widths.extend([width] * count)
    return widths, pos


def _encode_segmented_diffs(diffs: Sequence[int], segment_size: int) -> bytes:
    widths: list[int] = []
    for start in range(0, len(diffs), segment_size):
        end = min(len(diffs), start + segment_size)
        max_value = 0
        for i in range(start, end):
            value = int(diffs[i])
            if value > max_value:
                max_value = value
        widths.append(max_value.bit_length())
    out = bytearray(_rle_widths(widths))
    for segment_index, start in enumerate(range(0, len(diffs), segment_size)):
        end = min(len(diffs), start + segment_size)
        out.extend(_pack_u64_values_range(diffs, start, end, widths[segment_index]))
    return bytes(out)


def _decode_segmented_diffs(
    payload: bytes,
    pos: int,
    count: int,
    segment_size: int,
) -> tuple[list[int], int]:
    widths, pos = _read_rle_widths(payload, pos)
    out: list[int] = []
    for width in widths:
        if len(out) >= count:
            break
        n = min(segment_size, count - len(out))
        body_len = (n * width + 7) // 8 if width > 0 else 0
        body = payload[pos : pos + body_len]
        pos += body_len
        out.extend(_unpack_u64_values(body, n, width))
    if len(out) != count:
        raise ValueError("REGER segmented payload length mismatch")
    return out, pos


def _fit_linear(xs: Sequence[int], ys: Sequence[int]) -> tuple[float, float]:
    n = len(xs)
    if n == 0:
        return 0.0, 0.0
    sx = math.fsum(float(x) for x in xs)
    sy = math.fsum(float(y) for y in ys)
    sxx = math.fsum(float(x) * float(x) for x in xs)
    sxy = math.fsum(float(x) * float(y) for x, y in zip(xs, ys))
    denom = float(n) * sxx - sx * sx
    if abs(denom) <= 1e-12:
        theta0, theta1 = sy / float(n), 0.0
    else:
        theta1 = (float(n) * sxy - sx * sy) / denom
        theta0 = (sy - theta1 * sx) / float(n)
    if not math.isfinite(theta0) or not math.isfinite(theta1):
        raise OverflowError("REGER regression produced non-finite coefficients")
    theta0 = struct.unpack("<f", struct.pack("<f", theta0))[0]
    theta1 = struct.unpack("<f", struct.pack("<f", theta1))[0]
    if not math.isfinite(theta0) or not math.isfinite(theta1):
        raise OverflowError("REGER regression coefficients overflowed float32")
    return theta0, theta1


def _predict(theta0: float, theta1: float, x: int) -> int:
    raw = theta0 + theta1 * float(x)
    if not math.isfinite(raw):
        raise OverflowError("REGER prediction is non-finite")
    if raw <= float(I64_MIN):
        return I64_MIN
    if raw >= float(I64_MAX):
        return I64_MAX
    return int(raw)


def _residual_diffs(values: Sequence[int], minimum: int) -> list[int]:
    out: list[int] = []
    min_value = minimum
    append = out.append
    for value in values:
        diff = value - min_value
        if diff < 0 or diff > U64_MASK:
            raise OverflowError("REGER residual range exceeds uint64")
        append(diff)
    return out


def _series_wire(payload: _SeriesPayload) -> bytes:
    return SERIES_HEADER_STRUCT.pack(payload.mode, len(payload.payload)) + payload.payload


def _encode_raw_series(values: Sequence[int]) -> _SeriesPayload:
    return _SeriesPayload(
        RAW_SERIES,
        b"".join(struct.pack("<q", v) for v in values),
    )


def _encode_const_series(values: Sequence[int]) -> _SeriesPayload | None:
    if not values:
        return _SeriesPayload(CONST_SERIES, b"")
    first = values[0]
    if any(v != first for v in values):
        return None
    return _SeriesPayload(CONST_SERIES, struct.pack("<q", first))


def _encode_for_series(values: Sequence[int], segment_size: int) -> _SeriesPayload:
    minimum = min(values) if values else 0
    diffs = _residual_diffs(values, minimum)
    payload = struct.pack("<q", _validate_i64(minimum)) + _encode_segmented_diffs(
        diffs, segment_size
    )
    return _SeriesPayload(FOR_SERIES, payload)


def _encode_delta_series(values: Sequence[int], segment_size: int) -> _SeriesPayload | None:
    if len(values) <= 1:
        return None
    deltas = []
    append_delta = deltas.append
    prev = values[0]
    for cur in values[1:]:
        append_delta(_validate_i64(cur - prev))
        prev = cur
    minimum = min(deltas)
    diffs = _residual_diffs(deltas, minimum)
    payload = (
        struct.pack("<qq", _validate_i64(values[0]), _validate_i64(minimum))
        + _encode_segmented_diffs(diffs, segment_size)
    )
    return _SeriesPayload(DELTA_SERIES, payload)


def _encode_time_linear_series(
    values: Sequence[int],
    times: Sequence[int],
    segment_size: int,
) -> _SeriesPayload | None:
    if len(values) != len(times) or not values:
        return None
    t0 = times[0]
    xs = [t - t0 for t in times]
    theta0, theta1 = _fit_linear(xs, values)
    residuals = [
        _validate_i64(v - _predict(theta0, theta1, x))
        for x, v in zip(xs, values)
    ]
    minimum = min(residuals) if residuals else 0
    diffs = _residual_diffs(residuals, minimum)
    payload = (
        struct.pack("<ffq", theta0, theta1, _validate_i64(minimum))
        + _encode_segmented_diffs(diffs, segment_size)
    )
    return _SeriesPayload(TIME_LINEAR_SERIES, payload)


def _encode_prev_linear_series(values: Sequence[int], segment_size: int) -> _SeriesPayload | None:
    if len(values) <= 1:
        return None
    prev_values = values[:-1]
    cur_values = values[1:]
    theta0, theta1 = _fit_linear(prev_values, cur_values)
    residuals = [
        _validate_i64(cur - _predict(theta0, theta1, prev))
        for prev, cur in zip(prev_values, cur_values)
    ]
    minimum = min(residuals) if residuals else 0
    diffs = _residual_diffs(residuals, minimum)
    payload = (
        struct.pack("<qffq", _validate_i64(values[0]), theta0, theta1, _validate_i64(minimum))
        + _encode_segmented_diffs(diffs, segment_size)
    )
    return _SeriesPayload(PREV_LINEAR_SERIES, payload)


def _best_series_payload(
    values: Sequence[int],
    segment_size: int,
    *,
    times: Sequence[int] | None = None,
) -> _SeriesPayload:
    vals = list(values)
    best: _SeriesPayload | None = None
    best_cost = len(vals) * 8 + SERIES_HEADER_STRUCT.size

    def consider(candidate: _SeriesPayload | None) -> None:
        nonlocal best, best_cost
        if candidate is None:
            return
        cost = len(candidate.payload) + SERIES_HEADER_STRUCT.size
        if cost < best_cost:
            best = candidate
            best_cost = cost

    const = _encode_const_series(vals)
    consider(const)
    builds = [
        lambda: _encode_for_series(vals, segment_size) if vals else None,
        lambda: _encode_delta_series(vals, segment_size),
    ]
    if not _fast_profile():
        builds.append(lambda: _encode_prev_linear_series(vals, segment_size))
    for build in builds:
        try:
            candidate = build()
        except (OverflowError, ValueError, struct.error):
            candidate = None
        consider(candidate)
    if times is not None:
        try:
            time_linear = _encode_time_linear_series(vals, times, segment_size)
            consider(time_linear)
        except (OverflowError, ValueError, struct.error):
            pass
    return best if best is not None else _encode_raw_series(vals)


def _decode_series_payload(
    blob: bytes,
    pos: int,
    count: int,
    segment_size: int,
    *,
    times: Sequence[int] | None = None,
) -> tuple[list[int], int]:
    mode, payload_len = SERIES_HEADER_STRUCT.unpack_from(blob, pos)
    pos += SERIES_HEADER_STRUCT.size
    payload = blob[pos : pos + payload_len]
    pos += payload_len

    if mode == RAW_SERIES:
        expected = count * 8
        if len(payload) < expected:
            raise ValueError("REGER raw stream truncated")
        return [struct.unpack_from("<q", payload, i * 8)[0] for i in range(count)], pos
    if mode == CONST_SERIES:
        value = struct.unpack_from("<q", payload, 0)[0] if count else 0
        return [value] * count, pos
    if mode == FOR_SERIES:
        minimum = struct.unpack_from("<q", payload, 0)[0]
        diffs, _ = _decode_segmented_diffs(payload, 8, count, segment_size)
        return [_validate_i64(minimum + int(diff)) for diff in diffs], pos
    if mode == DELTA_SERIES:
        if count == 0:
            return [], pos
        first, minimum = struct.unpack_from("<qq", payload, 0)
        diffs, _ = _decode_segmented_diffs(payload, 16, count - 1, segment_size)
        out = [first]
        cur = first
        for diff in diffs:
            cur = _validate_i64(cur + minimum + int(diff))
            out.append(cur)
        return out, pos
    if mode == TIME_LINEAR_SERIES:
        if times is None or len(times) != count:
            raise ValueError("REGER time-linear stream missing time column")
        theta0, theta1, minimum = struct.unpack_from("<ffq", payload, 0)
        diffs, _ = _decode_segmented_diffs(payload, struct.calcsize("<ffq"), count, segment_size)
        t0 = int(times[0]) if times else 0
        out = []
        for t, diff in zip(times, diffs):
            x = int(t) - t0
            out.append(_validate_i64(_predict(theta0, theta1, x) + minimum + int(diff)))
        return out, pos
    if mode == PREV_LINEAR_SERIES:
        if count == 0:
            return [], pos
        first, theta0, theta1, minimum = struct.unpack_from("<qffq", payload, 0)
        diffs, _ = _decode_segmented_diffs(payload, struct.calcsize("<qffq"), count - 1, segment_size)
        out = [first]
        for diff in diffs:
            prev = out[-1]
            out.append(_validate_i64(_predict(theta0, theta1, prev) + minimum + int(diff)))
        return out, pos
    raise ValueError("invalid REGER stream mode")


def _common_row_count(columns: Sequence[Sequence[int]]) -> int:
    if not columns:
        return 0
    return min(len(col) for col in columns)


def _normalize_times(times: Sequence[int] | None, row_count: int) -> list[int]:
    if times is None:
        return list(range(row_count))
    if len(times) < row_count:
        raise ValueError("REGER time column shorter than value columns")
    return [_validate_i64(times[i]) for i in range(row_count)]


def _identity_order(n: int) -> list[int]:
    return list(range(n))


def _is_identity_order(order: Sequence[int]) -> bool:
    return all(int(v) == i for i, v in enumerate(order))


def _append_unique_order(candidates: list[list[int]], seen: set[tuple[int, ...]], order: list[int]) -> None:
    key = tuple(order)
    if key not in seen:
        seen.add(key)
        candidates.append(order)


def _partition_order(values: Sequence[int], times: Sequence[int], base: list[int]) -> list[int] | None:
    if len(base) < 8:
        return None
    sorted_vals = sorted(int(values[i]) for i in base)
    thresholds = [
        sorted_vals[len(sorted_vals) // 4],
        sorted_vals[len(sorted_vals) // 2],
        sorted_vals[(len(sorted_vals) * 3) // 4],
    ]
    if len(set(thresholds)) <= 1:
        return None
    return sorted(
        base,
        key=lambda i: (
            bisect.bisect_right(thresholds, int(values[i])),
            int(times[i]),
            i,
        ),
    )


def _row_order_candidates(block_columns: Sequence[Sequence[int]], block_times: Sequence[int]) -> list[list[int]]:
    n = _common_row_count(block_columns)
    if n <= 0:
        return []
    base = _identity_order(n)
    candidates = [base]
    seen = {tuple(base)}
    time_order = sorted(base, key=lambda i: (int(block_times[i]), i))
    _append_unique_order(candidates, seen, time_order)
    if _fast_profile():
        return candidates
    for col in block_columns:
        value_order = sorted(base, key=lambda i, c=col: (int(c[i]), int(block_times[i]), i))
        _append_unique_order(candidates, seen, value_order)
        partition = _partition_order(col, block_times, base)
        if partition is not None:
            _append_unique_order(candidates, seen, partition)
    if len(block_columns) > 1:
        lex_order = sorted(
            base,
            key=lambda i: tuple(int(col[i]) for col in block_columns) + (int(block_times[i]), i),
        )
        _append_unique_order(candidates, seen, lex_order)
    return candidates


def _encode_order(order: Sequence[int]) -> bytes:
    n = len(order)
    if _is_identity_order(order):
        return b""
    return _pack_u64_values(order, _ceil_log2(n))


def _column_cost_priority(payload: _BlockPayload, row_count: int, column_count: int) -> list[int]:
    pos = 0
    if payload.flags & ORDER_PERMUTED_FLAG:
        width = _ceil_log2(row_count)
        pos += (row_count * width + 7) // 8 if width > 0 else 0
    if payload.flags & TIME_STREAM_FLAG:
        _mode, payload_len = SERIES_HEADER_STRUCT.unpack_from(payload.payload, pos)
        pos += SERIES_HEADER_STRUCT.size + payload_len
    costs: list[int] = []
    for _ in range(column_count):
        _mode, payload_len = SERIES_HEADER_STRUCT.unpack_from(payload.payload, pos)
        wire_len = SERIES_HEADER_STRUCT.size + payload_len
        costs.append(wire_len)
        pos += wire_len
    return sorted(range(column_count), key=costs.__getitem__, reverse=True)


def _decode_order(blob: bytes, pos: int, n: int, flags: int) -> tuple[list[int], int]:
    if not (flags & ORDER_PERMUTED_FLAG):
        return list(range(n)), pos
    width = _ceil_log2(n)
    body_len = (n * width + 7) // 8 if width > 0 else 0
    body = blob[pos : pos + body_len]
    pos += body_len
    return [int(v) for v in _unpack_u64_values(body, n, width)], pos


def _encode_block_candidate(
    block_columns: Sequence[Sequence[int]],
    block_times: Sequence[int],
    order: Sequence[int],
    segment_size: int,
    *,
    include_time_stream: bool,
    cutoff_len: int | None = None,
    column_priority: Sequence[int] | None = None,
) -> _BlockPayload:
    n = len(order)
    flags = 0
    out = bytearray()
    if not include_time_stream and not _is_identity_order(order):
        flags |= ORDER_PERMUTED_FLAG
        out.extend(_encode_order(order))
    value_times = None
    if include_time_stream:
        ordered_times = [block_times[i] for i in order]
        value_times = ordered_times
        flags |= TIME_STREAM_FLAG
        out.extend(_series_wire(_best_series_payload(ordered_times, segment_size)))
        if cutoff_len is not None and len(out) >= cutoff_len:
            raise _CandidateTooLarge
    defer_columns = column_priority is not None and cutoff_len is not None
    column_wires = [b""] * len(block_columns) if defer_columns else None
    column_order = column_priority if defer_columns else range(len(block_columns))
    column_bytes = 0
    for col_idx in column_order:
        col = block_columns[col_idx]
        values = [col[i] for i in order]
        wire = _series_wire(
            _best_series_payload(
                values,
                segment_size,
                times=value_times,
            )
        )
        if column_wires is None:
            out.extend(wire)
        else:
            column_wires[col_idx] = wire
            column_bytes += len(wire)
        if cutoff_len is not None and len(out) + column_bytes >= cutoff_len:
            raise _CandidateTooLarge
    if column_wires is not None:
        for wire in column_wires:
            out.extend(wire)
    return _BlockPayload(flags, bytes(out))


def _encoded_block_cost(
    block_columns: Sequence[Sequence[int]],
    block_times: Sequence[int],
    order: Sequence[int],
    segment_size: int,
    cutoff_len: int | None = None,
    column_priority: Sequence[int] | None = None,
) -> _BlockPayload:
    candidates: list[_BlockPayload] = []
    if _is_identity_order(order):
        try:
            candidates.append(
                _encode_block_candidate(
                    block_columns,
                    block_times,
                    order,
                    segment_size,
                    include_time_stream=False,
                    cutoff_len=cutoff_len,
                    column_priority=column_priority,
                )
            )
        except _CandidateTooLarge:
            pass
    try:
        candidates.append(
            _encode_block_candidate(
                block_columns,
                block_times,
                order,
                segment_size,
                include_time_stream=True,
                cutoff_len=cutoff_len,
                column_priority=column_priority,
            )
        )
    except (OverflowError, ValueError, struct.error):
        pass
    except _CandidateTooLarge:
        pass
    if not candidates:
        if cutoff_len is not None:
            raise _CandidateTooLarge
        candidates.append(
            _encode_block_candidate(
                block_columns,
                block_times,
                order,
                segment_size,
                include_time_stream=False,
            )
        )
    return min(candidates, key=lambda item: len(item.payload) + BLOCK_HEADER_STRUCT.size)


def _legacy_encoded_block_cost(
    block_columns: Sequence[Sequence[int]],
    block_times: Sequence[int],
    order: Sequence[int],
    segment_size: int,
) -> _BlockPayload:
    candidates = [
        _encode_block_candidate(
            block_columns,
            block_times,
            order,
            segment_size,
            include_time_stream=False,
        )
    ]
    try:
        candidates.append(
            _encode_block_candidate(
                block_columns,
                block_times,
                order,
                segment_size,
                include_time_stream=True,
            )
        )
    except (OverflowError, ValueError, struct.error):
        pass
    return min(candidates, key=lambda item: len(item.payload) + BLOCK_HEADER_STRUCT.size)


def _move_order(order: Sequence[int], src: int, dst: int) -> list[int]:
    if src == dst:
        return list(order)
    out = list(order)
    value = out.pop(src)
    if dst > src:
        dst -= 1
    out.insert(max(0, min(dst, len(out))), value)
    return out


def _outlier_positions(
    order: Sequence[int],
    block_columns: Sequence[Sequence[int]],
    block_times: Sequence[int],
) -> list[int]:
    n = len(order)
    if n <= 2:
        return list(range(n))
    scores: list[tuple[int, int]] = []
    series = [block_times, *block_columns]
    for pos in range(1, n - 1):
        prev_i = order[pos - 1]
        cur_i = order[pos]
        next_i = order[pos + 1]
        score = 0
        for values in series:
            score += abs(int(values[prev_i]) - 2 * int(values[cur_i]) + int(values[next_i]))
        scores.append((score, pos))
    scores.sort(reverse=True)
    positions = [pos for _score, pos in scores[:8]]
    return sorted(set([0, n - 1, *positions]))


def _improve_order(
    order: Sequence[int],
    block_columns: Sequence[Sequence[int]],
    block_times: Sequence[int],
    segment_size: int,
    initial_payload: _BlockPayload | None = None,
    column_priority: Sequence[int] | None = None,
) -> tuple[list[int], _BlockPayload]:
    best_order = list(order)
    payload_cache: dict[tuple[int, ...], _BlockPayload] = {}

    def cached_cost(candidate_order: Sequence[int], cutoff_len: int | None = None) -> _BlockPayload | None:
        key = tuple(candidate_order)
        payload = payload_cache.get(key)
        if payload is None:
            try:
                payload = _encoded_block_cost(
                    block_columns,
                    block_times,
                    candidate_order,
                    segment_size,
                    cutoff_len=cutoff_len,
                    column_priority=column_priority,
                )
            except _CandidateTooLarge:
                return None
            payload_cache[key] = payload
        return payload

    best_key = tuple(best_order)
    if initial_payload is None:
        best_payload = cached_cost(best_order)
        if best_payload is None:
            best_payload = _encoded_block_cost(block_columns, block_times, best_order, segment_size)
    else:
        best_payload = initial_payload
        payload_cache[best_key] = initial_payload
    max_iter = min(_default_reorder_iterations(len(block_columns)), max(0, len(best_order) // 2))
    if max_iter <= 0:
        return best_order, best_payload
    for _ in range(max_iter):
        improved = False
        trial_best_order = best_order
        trial_best_payload = best_payload
        targets = {
            0,
            len(best_order) - 1,
            len(best_order) // 4,
            len(best_order) // 2,
            (len(best_order) * 3) // 4,
        }
        for src in _outlier_positions(best_order, block_columns, block_times):
            local_targets = set(targets)
            local_targets.add(max(0, src - 1))
            local_targets.add(min(len(best_order) - 1, src + 1))
            for dst in sorted(local_targets):
                if src == dst:
                    continue
                candidate_order = _move_order(best_order, src, dst)
                candidate_payload = cached_cost(candidate_order, len(trial_best_payload.payload))
                if candidate_payload is None:
                    continue
                if len(candidate_payload.payload) < len(trial_best_payload.payload):
                    trial_best_order = candidate_order
                    trial_best_payload = candidate_payload
                    improved = True
        if not improved:
            break
        best_order = trial_best_order
        best_payload = trial_best_payload
    return best_order, best_payload


def _best_block_payload(
    block_columns: Sequence[Sequence[int]],
    block_times: Sequence[int],
    segment_size: int,
) -> _BlockPayload:
    best_payload: _BlockPayload | None = None
    best_order: list[int] | None = None
    column_priority: list[int] | None = None
    for order in _row_order_candidates(block_columns, block_times):
        try:
            payload = _encoded_block_cost(
                block_columns,
                block_times,
                order,
                segment_size,
                cutoff_len=len(best_payload.payload) if best_payload is not None else None,
                column_priority=column_priority,
            )
        except (OverflowError, ValueError, struct.error):
            continue
        except _CandidateTooLarge:
            continue
        if best_payload is None or len(payload.payload) < len(best_payload.payload):
            best_payload = payload
            best_order = list(order)
        if column_priority is None:
            column_priority = _column_cost_priority(payload, len(order), len(block_columns))
    if best_payload is None or best_order is None:
        best_order = list(range(_common_row_count(block_columns)))
        best_payload = _encoded_block_cost(block_columns, block_times, best_order, segment_size)
    _improved_order, improved_payload = _improve_order(
        best_order,
        block_columns,
        block_times,
        segment_size,
        best_payload,
        column_priority,
    )
    if len(improved_payload.payload) < len(best_payload.payload):
        return improved_payload
    return best_payload


def _encode_block_task(
    args: tuple[list[list[int]], list[int], int],
) -> tuple[int, int, bytes]:
    block_columns, block_times, segment_size = args
    payload = _best_block_payload(block_columns, block_times, segment_size)
    return len(block_times), payload.flags, payload.payload


def _encode_i64_columns(columns: Sequence[Sequence[int]], times: Sequence[int] | None = None) -> bytes:
    prepared = [[_validate_i64(v) for v in col] for col in columns]
    row_count = _common_row_count(prepared)
    col_count = len(prepared)
    block_size = _default_block_size()
    segment_size = _default_segment_size()
    block_count = (row_count + block_size - 1) // block_size if row_count else 0
    row_times = _normalize_times(times, row_count)
    out = bytearray(
        MULTI_HEADER_STRUCT.pack(MULTI_MAGIC, row_count, col_count, block_size, segment_size, block_count)
    )
    if row_count == 0 or col_count == 0:
        return bytes(out)
    workers = _default_workers(block_count)
    if workers > 1:
        tasks = []
        for start in range(0, row_count, block_size):
            end = min(start + block_size, row_count)
            tasks.append(
                (
                    [col[start:end] for col in prepared],
                    row_times[start:end],
                    segment_size,
                )
            )
        context = (
            multiprocessing.get_context("fork")
            if "fork" in multiprocessing.get_all_start_methods()
            else None
        )
        with ProcessPoolExecutor(max_workers=workers, mp_context=context) as executor:
            for n, flags, payload in executor.map(_encode_block_task, tasks, chunksize=1):
                out.extend(BLOCK_HEADER_STRUCT.pack(n, flags, len(payload)))
                out.extend(payload)
        return bytes(out)
    for start in range(0, row_count, block_size):
        end = min(start + block_size, row_count)
        block_columns = [col[start:end] for col in prepared]
        block_times = row_times[start:end]
        payload = _best_block_payload(block_columns, block_times, segment_size)
        out.extend(BLOCK_HEADER_STRUCT.pack(end - start, payload.flags, len(payload.payload)))
        out.extend(payload.payload)
    return bytes(out)


def _decode_i64_columns(blob: bytes) -> list[list[int]]:
    if blob[:6] == LEGACY_MAGIC:
        raise ValueError("legacy REGER1 payloads are not used by benchmark reports")
    magic, row_count, col_count, _block_size, segment_size, block_count = MULTI_HEADER_STRUCT.unpack_from(
        blob, 0
    )
    if magic != MULTI_MAGIC:
        raise ValueError("invalid REGER multi-column payload")
    columns = [[0] * row_count for _ in range(col_count)]
    pos = MULTI_HEADER_STRUCT.size
    block_start = 0
    for _ in range(block_count):
        n, flags, payload_len = BLOCK_HEADER_STRUCT.unpack_from(blob, pos)
        pos += BLOCK_HEADER_STRUCT.size
        payload = blob[pos : pos + payload_len]
        pos += payload_len
        payload_pos = 0
        order, payload_pos = _decode_order(payload, payload_pos, n, flags)
        ordered_times: list[int] | None = None
        if flags & TIME_STREAM_FLAG:
            ordered_times, payload_pos = _decode_series_payload(
                payload,
                payload_pos,
                n,
                segment_size,
            )
        decoded_block_cols: list[list[int]] = []
        for _col in range(col_count):
            seq, payload_pos = _decode_series_payload(
                payload,
                payload_pos,
                n,
                segment_size,
                times=ordered_times,
            )
            decoded_block_cols.append(seq)
        if ordered_times is not None and not (flags & ORDER_PERMUTED_FLAG):
            restore_pairs = [
                (ordered_idx, local_row)
                for local_row, ordered_idx in enumerate(
                    sorted(range(n), key=lambda idx: (int(ordered_times[idx]), idx))
                )
            ]
        else:
            restore_pairs = list(enumerate(order))
        for ordered_idx, local_row in restore_pairs:
            if local_row < 0 or local_row >= n:
                raise ValueError("REGER decoded row index out of range")
            row_idx = block_start + int(local_row)
            for col_idx, seq in enumerate(decoded_block_cols):
                columns[col_idx][row_idx] = seq[ordered_idx]
        block_start += n
    return columns


def encode_int_column(values: Sequence[int]) -> bytes:
    return _encode_i64_columns([values])


def decode_int_column(blob: bytes) -> list[int]:
    columns = _decode_i64_columns(blob)
    return columns[0] if columns else []


def encode_float_column(values: Sequence[float]) -> bytes:
    return _encode_i64_columns([[_double_to_i64(v) for v in values]])


def decode_float_column(blob: bytes) -> list[float]:
    columns = _decode_i64_columns(blob)
    return [_i64_to_double(v) for v in columns[0]] if columns else []


def encode_int_columns(columns: Sequence[Sequence[int]], times: Sequence[int] | None = None) -> bytes:
    return _encode_i64_columns(columns, times=times)


def decode_int_columns(blob: bytes) -> list[list[int]]:
    return _decode_i64_columns(blob)


def encode_float_columns(
    columns: Sequence[Sequence[float]],
    times: Sequence[int] | None = None,
) -> bytes:
    return _encode_i64_columns(
        [[_double_to_i64(v) for v in col] for col in columns],
        times=times,
    )


def decode_float_columns(blob: bytes) -> list[list[float]]:
    return [[_i64_to_double(v) for v in col] for col in _decode_i64_columns(blob)]


def _elapsed_ns(start: int) -> int:
    return max(0, int(time.perf_counter_ns() - start))


def bench_reger_int_columns(
    columns: Iterable[Sequence[int]],
    times: Sequence[int] | None = None,
) -> tuple[int, int, int, int, float, float]:
    source_columns = [[_validate_i64(v) for v in column] for column in columns]
    row_count = _common_row_count(source_columns)
    if row_count <= 0 or not source_columns:
        return (0, 0, 0, 0, 0.0, 0.0)
    values = [col[:row_count] for col in source_columns]
    row_times = _normalize_times(times, row_count) if times is not None else None
    loss = [0.0, 0.0]
    total_original = row_count * len(values) * 8
    start = time.perf_counter_ns()
    encoded = encode_int_columns(values, times=row_times)
    total_comp_ns = _elapsed_ns(start)
    start = time.perf_counter_ns()
    decoded = decode_int_columns(encoded)
    total_decomp_ns = _elapsed_ns(start)
    for expected, actual in zip(values, decoded):
        accumulate_long_list_loss(expected, actual, loss)
    return (
        int(total_original),
        int(len(encoded)),
        int(total_comp_ns),
        int(total_decomp_ns),
        float(loss[0]),
        float(loss[1]),
    )


def bench_reger_double_columns(
    columns: Iterable[Sequence[float]],
    times: Sequence[int] | None = None,
) -> tuple[int, int, int, int, float, float]:
    source_columns = [[float(v) for v in column] for column in columns]
    row_count = _common_row_count(source_columns)
    if row_count <= 0 or not source_columns:
        return (0, 0, 0, 0, 0.0, 0.0)
    values = [col[:row_count] for col in source_columns]
    row_times = _normalize_times(times, row_count) if times is not None else None
    loss = [0.0, 0.0]
    total_original = row_count * len(values) * 8
    start = time.perf_counter_ns()
    encoded = encode_float_columns(values, times=row_times)
    total_comp_ns = _elapsed_ns(start)
    start = time.perf_counter_ns()
    decoded = decode_float_columns(encoded)
    total_decomp_ns = _elapsed_ns(start)
    for expected, actual in zip(values, decoded):
        accumulate_double_list_loss(expected, actual, loss)
    return (
        int(total_original),
        int(len(encoded)),
        int(total_comp_ns),
        int(total_decomp_ns),
        float(loss[0]),
        float(loss[1]),
    )
