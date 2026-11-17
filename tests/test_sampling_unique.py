# -*- coding: utf-8 -*-
"""采样极值下标去重保持语义，避免高成本通用 unique 管线。"""

import os
from pathlib import Path
import sys
import traceback

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
from InstructionX_UIKit.charts.sampling import sample_indices

_FAILURES = []


def check(name):
    def decorate(function):
        try:
            function()
            print(f"  [通过] {name}")
        except Exception:
            _FAILURES.append(name)
            print(f"  [失败] {name}")
            traceback.print_exc()
    return decorate


@check("极值下标与通用 unique 一致但不调用高成本接口")
def _():
    rng = np.random.default_rng(20261116)
    values = np.sin(np.arange(20000) / 700) + rng.normal(0, 0.015, 20000)
    buckets = 127
    expected = sample_indices(values, buckets)
    original_unique, original_union = np.unique, np.union1d

    def forbidden_unique(*args, **kwargs):
        if args[0].ndim > 1:
            raise AssertionError("采样去重不应调用 np.unique")
        return original_unique(*args, **kwargs)

    def forbidden_union(*args, **kwargs):
        raise AssertionError("端点合并不应调用 np.union1d")

    np.unique = forbidden_unique
    np.union1d = forbidden_union
    try:
        actual = sample_indices(values, buckets)
    finally:
        np.unique, np.union1d = original_unique, original_union
    assert np.array_equal(actual, expected), (actual[:20], expected[:20])


@check("首尾端点按原始顺序保留且下标严格递增")
def _():
    values = np.zeros(64, dtype=np.float64)
    values[1::4] = -10.0
    values[2::4] = 10.0
    actual = sample_indices(values, 4)
    assert actual[0] == 0, f"首点被放到了错误位置: {actual.tolist()}"
    assert actual[-1] == len(values) - 1, f"末点未保留: {actual.tolist()}"
    assert np.all(actual[1:] > actual[:-1]), f"采样下标不是严格递增: {actual.tolist()}"
    expected = np.array([0, 1, 2, 17, 18, 33, 34], dtype=np.int64)
    assert np.array_equal(actual[:7], expected), actual[:7]


@check("相同数据形状复用采样索引计划且逐项一致")
def _():
    from InstructionX_UIKit.charts import sampling
    cache = getattr(sampling, "_SAMPLE_PLAN_CACHE", None)
    if cache is not None:
        cache.clear()
    values = np.sin(np.arange(777) / 31)
    expected = sample_indices(values, 77)
    original_arange = np.arange
    calls = []

    def counted(*args, **kwargs):
        calls.append(args)
        return original_arange(*args, **kwargs)

    np.arange = counted
    try:
        actual = sample_indices(values, 77)
    finally:
        np.arange = original_arange
    assert not calls, f"相同形状仍重建索引计划: {len(calls)} 次 arange"
    assert np.array_equal(actual, expected)


if __name__ == "__main__":
    raise SystemExit(1 if _FAILURES else 0)
