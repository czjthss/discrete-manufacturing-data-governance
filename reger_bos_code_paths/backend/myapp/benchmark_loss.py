"""Minimal benchmark error accumulation used by the REGER codec."""

from __future__ import annotations

import math
from typing import Sequence


def accumulate_long_list_loss(
    expected: Sequence[int], actual: Sequence[int], loss: list[float]
) -> None:
    _accumulate(expected, actual, loss)


def accumulate_double_list_loss(
    expected: Sequence[float], actual: Sequence[float], loss: list[float]
) -> None:
    _accumulate(expected, actual, loss)


def _accumulate(
    expected: Sequence[float], actual: Sequence[float], loss: list[float]
) -> None:
    if len(expected) != len(actual):
        raise ValueError("benchmark vectors have different lengths")
    absolute = [abs(float(left) - float(right)) for left, right in zip(expected, actual)]
    while len(loss) < 3:
        loss.append(0.0)
    loss[0] += sum(absolute)
    loss[1] += sum(value * value for value in absolute)
    loss[2] = max(loss[2], max(absolute, default=0.0))
