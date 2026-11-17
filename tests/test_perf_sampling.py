# -*- coding: utf-8 -*-
"""采样与 category 批量映射逐点参考对照（直接运行）。"""

import math
import sys
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import numpy as np
from PySide6.QtWidgets import QApplication

from InstructionX_UIKit.charts import ChartWidget
from InstructionX_UIKit.charts.data import to_buffer
from InstructionX_UIKit.charts.sampling import _bucket_bounds, bucket_sample
from InstructionX_UIKit.theme import ThemeManager
import InstructionX_UIKit.charts.sampling as sampling

_FAILURES = []
app = QApplication.instance() or QApplication(sys.argv)
ThemeManager.instance().apply(app)


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


def same_number(actual, expected):
    if math.isnan(actual) and math.isnan(expected):
        return True
    return actual == expected


def assert_entries(actual, expected):
    assert actual is not None
    assert len(actual) == len(expected), (len(actual), len(expected))
    for (ax, ay), (ex, ey) in zip(actual, expected):
        assert same_number(ax, ex), (ax, ex)
        assert same_number(ay, ey), (ay, ey)


def reference(values, threshold, x_values=None):
    array = values.raw if hasattr(values, "raw") else values
    array = np.asarray(array, dtype=np.float64)
    x = None if x_values is None else np.asarray(x_values, dtype=np.float64)
    output = []
    for start, end in _bucket_bounds(len(array), threshold):
        segment = array[start:end]
        low = start + int(np.argmin(segment))
        high = start + int(np.argmax(segment))
        indices = (low,) if low == high else ((low, high) if low < high else (high, low))
        for index in indices:
            output.append((index if x is None else float(x[index]), float(array[index])))
    return output


@check("桶边界与 list、ndarray、NumericBuffer 输出逐项一致")
def _():
    values = [0.0, float("nan"), 2.0, -float("inf"), float("inf"),
              None, 8.0, 7.0, 6.0, 5.0, 4.0, 3.0, 2.0, 1.0]
    assert _bucket_bounds(len(values), 4) == [(0, 4), (4, 7), (7, 11), (11, 14)]
    x_values = np.array([100, 200, 400, 800, 1600, 3200, 6400,
                         12800, 25600, 51200, 102400, 204800, 409600,
                         819200], dtype=np.float64)
    for candidate in (values, np.asarray(values, dtype=object)):
        actual, _ = bucket_sample(candidate, 4, x_values=x_values)
        assert_entries(actual, reference(candidate, 4, x_values))
    compact = to_buffer(np.arange(300, dtype=np.float64))
    assert compact is not None
    actual, _ = bucket_sample(compact, 7)
    assert_entries(actual, reference(compact, 7))
    invalid, count = bucket_sample([1, "bad", 3], 2)
    assert invalid is None and count == 0


@check("纯 Python 回退输出逐项一致")
def _():
    values = [float("nan"), 1.0, 3.0, -2.0, 8.0, 4.0, 6.0, 2.0]
    original = sampling._np
    try:
        sampling._np = None
        actual, _ = bucket_sample(values, 3)
    finally:
        sampling._np = original
    assert_entries(actual, reference(values, 3))


def make_category(categories, data):
    chart = ChartWidget()
    chart.resize(640, 360)
    chart.set_option({
        "xAxis": {"type": "category", "data": categories},
        "yAxis": {"type": "value"},
        "series": [{"type": "line", "data": data}],
    })
    chart.anim.stop()
    chart.anim.set_progress(1.0)
    chart._layout_all(force=True)
    return chart, chart.series_renderers[0]


def assert_fast_map_matches(chart, renderer, xs, ys):
    coord = chart.coord_for(renderer.opt)
    points = renderer._map_sampled_fast(coord, xs, ys)
    assert points is not None, "category 快路径未启用"
    assert not renderer._fast_map_disabled
    for index, (x, y) in enumerate(zip(xs, ys)):
        expected = coord.map_point(x, y)
        assert abs(points[index].x() - expected.x()) <= 1e-9
        assert abs(points[index].y() - expected.y()) <= 1e-9


@check("非空 category 与数值轴逐点映射一致")
def _():
    chart, renderer = make_category(["甲", "乙", "丙", "丁"], [1, 2, 3, 4])
    assert_fast_map_matches(chart, renderer, [0, 1, 2, 3], [1, 2, 3, 4])
    chart.close()


@check("空 category 的隐式下标 band 逐点一致")
def _():
    values = list(range(20))
    chart, renderer = make_category([], values)
    assert_fast_map_matches(chart, renderer, values, values)
    chart.close()


@check("category 窗口偏移与负下标保持 AxisModel 语义")
def _():
    chart, renderer = make_category(["a", "b", "c", "d", "e"], [1, 2, 3, 4, 5])
    coord = chart.coord_for(renderer.opt)
    coord.x_axis.categories = ["c", "d"]
    xs = [-2, 0, 2, 3, 4]
    ys = [1, 2, 3, 4, 5]
    assert_fast_map_matches(chart, renderer, xs, ys)
    assert renderer._map_sampled_fast(coord, [0, float("nan"), 2], [1, 2, 3]) is None
    chart.close()


def _reference_blocked_extrema(values, bounds, block=64):
    output = []
    for offset in range(0, len(bounds), block):
        part = bounds[offset:offset + block]
        extrema = [None] * len(part)
        valid_rows = []
        width = max(end - start for start, end in part)
        lows = np.full((len(part), width), np.inf)
        highs = np.full((len(part), width), -np.inf)
        for row, (start, end) in enumerate(part):
            segment = values[start:end]
            if np.isnan(segment).any():
                extrema[row] = (start + int(np.argmin(segment)),
                                start + int(np.argmax(segment)))
                continue
            lows[row, :end - start] = segment
            highs[row, :end - start] = segment
            valid_rows.append(row)
        for row in valid_rows:
            start, _ = part[row]
            extrema[row] = (start + int(np.argmin(lows[row])),
                            start + int(np.argmax(highs[row])))
        output.extend(extrema)
    return output


@check("极值索引逐项一致且降低分块成本")
def _():
    rng = np.random.default_rng(20261115)
    for n, threshold in ((3, 2), (17, 4), (100, 7), (1000, 31),
                         (20000, 1196), (20000, 4096), (1000, 999)):
        for index in range(8):
            values = rng.normal(size=n)
            if index % 3 == 0:
                values[index % n] = np.nan
            if index % 4 == 0:
                values[(index * 7) % n] = np.inf
            if index % 5 == 0:
                values[(index * 11) % n] = -np.inf
            values[0] = -0.0
            if n > 1:
                values[1] = 0.0
            bounds = _bucket_bounds(n, threshold)
            expected = _reference_blocked_extrema(values, bounds)
            actual = sampling._blocked_numpy_extrema(values, bounds)
            assert actual == expected, (n, threshold, actual[:8], expected[:8])
    values = rng.normal(size=20000)
    values[17] = np.nan
    bounds = _bucket_bounds(len(values), 1196)
    started = time.perf_counter()
    for _ in range(25):
        _reference_blocked_extrema(values, bounds)
    reference_ms = (time.perf_counter() - started) * 1000
    started = time.perf_counter()
    for _ in range(25):
        sampling._blocked_numpy_extrema(values, bounds)
    vector_ms = (time.perf_counter() - started) * 1000
    assert vector_ms < reference_ms / 2, (reference_ms, vector_ms)


def _expanded_extrema(values, bounds):
    starts = np.asarray([start for start, _end in bounds], dtype=np.int64)
    ends = np.asarray([end for _start, end in bounds], dtype=np.int64)
    indices = np.arange(len(values))
    min_values = np.minimum.reduceat(values, starts)
    expanded_min = np.repeat(min_values, ends - starts)
    min_indices = np.minimum.reduceat(
        np.where(values == expanded_min, indices, len(values)), starts)
    max_values = np.maximum.reduceat(values, starts)
    expanded_max = np.repeat(max_values, ends - starts)
    max_indices = -np.maximum.reduceat(
        np.where(values == expanded_max, -indices, -len(values)), starts)
    nan_indices = np.minimum.reduceat(
        np.where(np.isnan(values), indices, len(values)), starts)
    has_nan = nan_indices < ends
    min_indices = np.where(has_nan, nan_indices, min_indices)
    max_indices = np.where(has_nan, nan_indices, max_indices)
    return list(zip(min_indices.tolist(), max_indices.tolist()))


@check("极值分桶保持首命中并降低扩展数组成本")
def _():
    for n, threshold in ((17, 4), (100, 7), (1000, 31), (20000, 1196)):
        bounds = _bucket_bounds(n, threshold)
        for values in (np.resize([0.0, -0.0, 4.0, 4.0, -2.0, -2.0], n),
                       np.resize([np.nan, np.nan, 0.0, np.inf, -np.inf], n)):
            assert sampling._blocked_numpy_extrema(values, bounds) == \
                _reference_blocked_extrema(values, bounds)
    values = np.random.default_rng(20261115).normal(size=20000)
    values[17] = np.nan
    bounds = _bucket_bounds(len(values), 1196)
    timings = {}
    for name, function in (("expanded", _expanded_extrema),
                           ("current", sampling._blocked_numpy_extrema)):
        for _ in range(3):
            function(values, bounds)
        samples = []
        for _ in range(7):
            started = time.perf_counter()
            for _ in range(20):
                function(values, bounds)
            samples.append((time.perf_counter() - started) * 1000 / 20)
        timings[name] = min(samples)
    assert timings["current"] < timings["expanded"] * 0.85, timings


if __name__ == "__main__":
    app.quit()
    raise SystemExit(1 if _FAILURES else 0)
