# -*- coding: utf-8 -*-
"""流式原子提交、轴降频与生命周期回归（直接运行）。"""

import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import numpy as np
from PySide6.QtWidgets import QApplication

from InstructionX_UIKit.charts import ChartWidget
from InstructionX_UIKit.theme import ThemeManager
import InstructionX_UIKit.charts.stream as stream_module

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


def make_stream(auto_scale=True, fixed=False):
    chart = ChartWidget()
    chart.resize(800, 400)
    y_axis = {"type": "value"}
    if fixed:
        y_axis.update({"min": -5, "max": 5})
    chart.set_option({
        "xAxis": {"type": "category", "data": []},
        "yAxis": y_axis,
        "series": [{"type": "line", "name": "信号", "data": []}],
    })
    session = chart.stream(series="信号", auto_scale=auto_scale)
    session._timer.stop()
    return chart, session


@check("auto-scale 不经过全量 rebuild 或 update_option")
def _():
    chart, session = make_stream()
    chart.update_option = lambda _option: (_ for _ in ()).throw(
        AssertionError("禁止 update_option"))
    chart._rebuild = lambda: (_ for _ in ()).throw(
        AssertionError("禁止全量 rebuild"))
    values = np.linspace(-1, 1, 20000)
    for _ in range(10):
        session._apply(values)
    assert not chart.anim.is_running()
    renderer = chart.series_renderers[0]
    assert renderer.opt["data"] is chart._option["series"][0]["data"]
    assert len(chart.option()["series"][0]["data"]) == 20000
    chart._layout_all(force=True)
    points = [point for point in renderer._points if point is not None]
    plot = chart.primary_coord().plot
    span = max(point.x() for point in points) - min(point.x() for point in points)
    assert span >= plot.width() * 0.8, (span, plot.width())
    session.close()
    chart.close()


@check("auto 轴范围最多按 8 Hz 更新")
def _():
    chart, session = make_stream()
    ranges = []
    original = chart._apply_stream_data

    def record(values, series=0, y_range=None, refresh_axes=None):
        if y_range is not None:
            ranges.append(y_range)
        return original(values, series, y_range, refresh_axes)

    chart._apply_stream_data = record
    current = [0.0]
    original_clock = stream_module.time.monotonic
    try:
        stream_module.time.monotonic = lambda: current[0]
        for index in range(10):
            current[0] = index * 0.01
            session._apply(np.linspace(-1, 1 + index, 20000))
        current[0] = 0.06
        session._apply(np.linspace(-1, 2, 20000))
        current[0] = 0.13
        session._apply(np.linspace(-1, 3, 20000))
    finally:
        stream_module.time.monotonic = original_clock
    assert len(ranges) == 2, ranges
    session.close()
    chart.close()


@check("固定 y 轴不计算数据范围")
def _():
    chart, session = make_stream(fixed=True)
    session._auto_axis_range = lambda _values: (_ for _ in ()).throw(
        AssertionError("固定轴不应扫描 min/max"))
    calls = []
    original = chart._apply_stream_data

    def record(values, series=0, y_range=None, refresh_axes=None):
        calls.append(y_range)
        return original(values, series, y_range, refresh_axes)

    chart._apply_stream_data = record
    session._apply(np.linspace(-100, 100, 20000))
    assert calls == [None], calls
    session.close()
    chart.close()


@check("隐藏时停更且恢复只提交最新窗口")
def _():
    chart, session = make_stream()
    updates = []
    original_update = chart.update

    def counted_update(*args):
        updates.append(args)
        return original_update(*args)

    chart.update = counted_update
    session.set_active(False)
    session.write([1, 2, 3])
    session._on_tick()
    assert not updates
    assert session.coalescer.pending_points == 0
    session.write([4, 5])
    session._on_tick()
    assert not updates
    session.set_active(True)
    session._on_tick()
    assert len(updates) == 1
    assert list(chart.series_renderers[0].data_view()) == [1, 2, 3, 4, 5]
    session.close()
    assert not session.alive and not session._timer.isActive()
    chart.close()


@check("公共 set_stream_data 同长度也同步 option 且不重建")
def _():
    chart, _session = make_stream(auto_scale=False)
    rebuilds = []
    original = chart._rebuild

    def counted():
        rebuilds.append(1)
        return original()

    chart._rebuild = counted
    assert chart.set_stream_data([1, 2, 3])
    assert chart.set_stream_data([4, 5, 6])
    assert chart.option()["series"][0]["data"] == [4, 5, 6]
    assert not rebuilds
    chart.close()


if __name__ == "__main__":
    app.quit()
    raise SystemExit(1 if _FAILURES else 0)
