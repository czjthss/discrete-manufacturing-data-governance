"""Unified adapters for the research group's REGER and BOS codecs."""

from __future__ import annotations

import math
import struct
import sys
import zlib
from decimal import ROUND_HALF_EVEN, Decimal
from pathlib import Path
from typing import Sequence

from governance.common import bounded_zlib_decompress

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from reger_bos_code_paths.backend.myapp import reger_codec


I64_MIN = -(1 << 63)
I64_MAX = (1 << 63) - 1
U64_MASK = (1 << 64) - 1
MAX_SAMPLES = 2_000_000
REGER_HEADER = struct.Struct("<6sIHHHI")


def _validate_reger_payload(payload: bytes) -> None:
    if not isinstance(payload, bytes) or len(payload) < REGER_HEADER.size:
        raise ValueError("REGER 载荷缺少头部")
    if len(payload) > 64 * 1024 * 1024:
        raise ValueError("REGER 载荷超过资源上限")
    magic, row_count, column_count, block_size, segment_size, _ = (
        REGER_HEADER.unpack_from(payload)
    )
    if magic != b"REGER3" or column_count != 1:
        raise ValueError("REGER 载荷头部无效")
    if row_count > MAX_SAMPLES or block_size <= 0 or segment_size <= 0:
        raise ValueError("REGER 载荷声明的规模无效")


def _validate_ints(values: Sequence[int]) -> list[int]:
    if len(values) > MAX_SAMPLES:
        raise ValueError("样本数超过上限")
    normalized = []
    for value in values:
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError("整数压缩器只接受 int64 样本")
        if value < I64_MIN or value > I64_MAX:
            raise ValueError("样本超出 int64 范围")
        normalized.append(value)
    return normalized


def _validate_floats(values: Sequence[float]) -> list[float]:
    if len(values) > MAX_SAMPLES:
        raise ValueError("样本数超过上限")
    normalized = []
    for value in values:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError("浮点压缩器只接受数值样本")
        number = float(value)
        if not math.isfinite(number):
            raise ValueError("浮点压缩器不接受 NaN 或无穷值")
        normalized.append(number)
    return normalized


def _zigzag_encode(value: int) -> int:
    return ((value << 1) ^ (value >> 63)) & U64_MASK


def _zigzag_decode(value: int) -> int:
    return (value >> 1) ^ -(value & 1)


def _append_varint(target: bytearray, value: int) -> None:
    while value >= 0x80:
        target.append((value & 0x7F) | 0x80)
        value >>= 7
    target.append(value)


def _read_varint(payload: bytes, position: int) -> tuple[int, int]:
    value = 0
    for shift in range(0, 70, 7):
        if position >= len(payload):
            raise ValueError("压缩载荷被截断")
        current = payload[position]
        position += 1
        value |= (current & 0x7F) << shift
        if not current & 0x80:
            return value, position
    raise ValueError("压缩载荷包含超长 varint")


class RegerIntCodec:
    """Lossless int64 adapter backed by the research-group REGER source."""

    @staticmethod
    def compress(values: Sequence[int]) -> bytes:
        return reger_codec.encode_int_column(_validate_ints(values))

    @staticmethod
    def decompress(payload: bytes) -> list[int]:
        _validate_reger_payload(payload)
        try:
            values = reger_codec.decode_int_column(payload)
        except Exception as exc:
            raise ValueError("REGER Int64 载荷无效") from exc
        return _validate_ints(values)


class RegerFloatCodec:
    """Lossless float64 adapter backed by the research-group REGER source."""

    @staticmethod
    def compress(values: Sequence[float]) -> bytes:
        return reger_codec.encode_float_column(_validate_floats(values))

    @staticmethod
    def decompress(payload: bytes) -> list[float]:
        _validate_reger_payload(payload)
        try:
            values = reger_codec.decode_float_column(payload)
        except Exception as exc:
            raise ValueError("REGER Float64 载荷无效") from exc
        return _validate_floats(values)


class BosIntCodec:
    """Block-oriented delta and ZigZag codec for int64 time series."""

    MAGIC = b"BOS1"
    HEADER = struct.Struct(">4sII")

    @classmethod
    def compress(cls, values: Sequence[int], block_size: int = 256) -> bytes:
        data = _validate_ints(values)
        if (
            not isinstance(block_size, int)
            or isinstance(block_size, bool)
            or not 0 < block_size <= 65_535
        ):
            raise ValueError("块大小必须是 1 到 65535 的整数")
        body = bytearray(cls.HEADER.pack(cls.MAGIC, len(data), block_size))
        for offset in range(0, len(data), block_size):
            block = data[offset : offset + block_size]
            body.extend(struct.pack(">Hq", len(block), block[0]))
            previous = block[0]
            for current in block[1:]:
                delta = current - previous
                if delta < I64_MIN or delta > I64_MAX:
                    raise ValueError("相邻样本差值超出 int64 范围")
                _append_varint(body, _zigzag_encode(delta))
                previous = current
        return zlib.compress(bytes(body), level=6)

    @classmethod
    def decompress(cls, payload: bytes) -> list[int]:
        raw = bounded_zlib_decompress(
            payload,
            cls.HEADER.size + MAX_SAMPLES * 12,
        )
        if len(raw) < cls.HEADER.size:
            raise ValueError("BOS 载荷缺少头部")
        magic, count, block_size = cls.HEADER.unpack_from(raw)
        if magic != cls.MAGIC or count > MAX_SAMPLES or block_size <= 0:
            raise ValueError("BOS 载荷头部无效")
        position = cls.HEADER.size
        result: list[int] = []
        while len(result) < count:
            if position + 10 > len(raw):
                raise ValueError("BOS 块头被截断")
            block_count, first = struct.unpack_from(">Hq", raw, position)
            position += 10
            if block_count <= 0 or block_count > block_size or len(result) + block_count > count:
                raise ValueError("BOS 块长度无效")
            result.append(first)
            previous = first
            for _ in range(block_count - 1):
                encoded, position = _read_varint(raw, position)
                current = previous + _zigzag_decode(encoded)
                if current < I64_MIN or current > I64_MAX:
                    raise ValueError("BOS 解码结果超出 int64 范围")
                result.append(current)
                previous = current
        if position != len(raw):
            raise ValueError("BOS 载荷包含尾随字节")
        return result


class Ts2DiffBosIntCodec:
    """Selects the smaller result between TS_2DIFF and BOS for each series."""

    MAGIC = b"T2B1"

    @classmethod
    def compress(cls, values: Sequence[int]) -> bytes:
        data = _validate_ints(values)
        bos = BosIntCodec.compress(data)
        second_diff = cls._compress_second_diff(data)
        mode, body = min(((b"B", bos), (b"T", second_diff)), key=lambda item: len(item[1]))
        return cls.MAGIC + mode + body

    @classmethod
    def decompress(cls, payload: bytes) -> list[int]:
        if not isinstance(payload, bytes) or len(payload) < 5 or payload[:4] != cls.MAGIC:
            raise ValueError("TS_2DIFF+BOS 载荷头部无效")
        if payload[4:5] == b"B":
            return BosIntCodec.decompress(payload[5:])
        if payload[4:5] == b"T":
            return cls._decompress_second_diff(payload[5:])
        raise ValueError("TS_2DIFF+BOS 编码模式无效")

    @staticmethod
    def _compress_second_diff(values: list[int]) -> bytes:
        body = bytearray(struct.pack(">I", len(values)))
        if values:
            body.extend(struct.pack(">q", values[0]))
        if len(values) > 1:
            first_delta = values[1] - values[0]
            if first_delta < I64_MIN or first_delta > I64_MAX:
                raise ValueError("一阶差分超出 int64 范围")
            body.extend(struct.pack(">q", first_delta))
            previous_delta = first_delta
            for index in range(2, len(values)):
                delta = values[index] - values[index - 1]
                second = delta - previous_delta
                if second < I64_MIN or second > I64_MAX:
                    raise ValueError("二阶差分超出 int64 范围")
                _append_varint(body, _zigzag_encode(second))
                previous_delta = delta
        return zlib.compress(bytes(body), level=6)

    @staticmethod
    def _decompress_second_diff(payload: bytes) -> list[int]:
        raw = bounded_zlib_decompress(payload, 20 + MAX_SAMPLES * 10)
        if len(raw) < 4:
            raise ValueError("TS_2DIFF 载荷缺少头部")
        count = struct.unpack_from(">I", raw)[0]
        if count > MAX_SAMPLES:
            raise ValueError("TS_2DIFF 样本数超过上限")
        position = 4
        if count == 0:
            if position != len(raw):
                raise ValueError("空 TS_2DIFF 载荷包含尾随字节")
            return []
        if position + 8 > len(raw):
            raise ValueError("TS_2DIFF 首值被截断")
        first = struct.unpack_from(">q", raw, position)[0]
        position += 8
        result = [first]
        if count > 1:
            if position + 8 > len(raw):
                raise ValueError("TS_2DIFF 首差值被截断")
            delta = struct.unpack_from(">q", raw, position)[0]
            position += 8
            second_value = first + delta
            if second_value < I64_MIN or second_value > I64_MAX:
                raise ValueError("TS_2DIFF 解码结果超出 int64 范围")
            result.append(second_value)
            while len(result) < count:
                encoded, position = _read_varint(raw, position)
                delta += _zigzag_decode(encoded)
                current = result[-1] + delta
                if current < I64_MIN or current > I64_MAX:
                    raise ValueError("TS_2DIFF 解码结果超出 int64 范围")
                result.append(current)
        if position != len(raw):
            raise ValueError("TS_2DIFF 载荷包含尾随字节")
        return result


class Ts2DiffBosFloatCodec:
    """Decimal-preserving float adapter over TS_2DIFF+BOS int64 coding."""

    MAGIC = b"T2F1"

    @classmethod
    def compress(cls, values: Sequence[float], decimal_places: int = 6) -> bytes:
        data = _validate_floats(values)
        if not isinstance(decimal_places, int) or not 0 <= decimal_places <= 9:
            raise ValueError("小数位数必须是 0 到 9 的整数")
        scale = 10**decimal_places
        scaled = [
            int(
                (Decimal(str(value)) * scale).to_integral_value(
                    rounding=ROUND_HALF_EVEN
                )
            )
            for value in data
        ]
        body = Ts2DiffBosIntCodec.compress(scaled)
        return cls.MAGIC + bytes([decimal_places]) + body

    @classmethod
    def decompress(cls, payload: bytes) -> list[float]:
        if not isinstance(payload, bytes) or len(payload) < 5 or payload[:4] != cls.MAGIC:
            raise ValueError("浮点 TS_2DIFF+BOS 载荷头部无效")
        decimal_places = payload[4]
        if decimal_places > 9:
            raise ValueError("浮点 TS_2DIFF+BOS 小数位数无效")
        scale = 10**decimal_places
        return [value / scale for value in Ts2DiffBosIntCodec.decompress(payload[5:])]
