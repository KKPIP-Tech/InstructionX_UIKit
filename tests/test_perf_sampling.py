# -*- coding: utf-8 -*-
"""采样与 category 批量映射逐点参考对照（直接运行）。"""

import math
import sys
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


if __name__ == "__main__":
    app.quit()
    raise SystemExit(1 if _FAILURES else 0)
