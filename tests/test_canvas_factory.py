# -*- coding: utf-8 -*-
"""Canvas 生产工厂、全系列覆盖、能力回退与输入兼容回归。"""

import os
from pathlib import Path
import sys
import time
import traceback

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.pop("QT_QPA_PLATFORM", None)
os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from InstructionX_UIKit.charts import ChartWidget
from InstructionX_UIKit.charts.core import (
    COMPONENT_REGISTRY,
    SERIES_REGISTRY,
    SeriesRenderer,
    register_component,
    register_series,
)
from InstructionX_UIKit.charts.canvas_map import CanvasComponentsChartViewport
from InstructionX_UIKit.charts.rhi_viewport import _RhiViewport
from InstructionX_UIKit.charts.viewport import _RasterViewport
from InstructionX_UIKit.theme import ThemeManager

_FAILURES = []
app = QApplication.instance() or QApplication(sys.argv)
ThemeManager.instance().apply(app)


def pump(milliseconds=40):
    deadline = time.perf_counter() + milliseconds / 1000
    while time.perf_counter() < deadline:
        app.processEvents()
        time.sleep(0.005)


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


def backend(name):
    if name is None:
        os.environ.pop("UIKIT_CHART_BACKEND", None)
    else:
        os.environ["UIKIT_CHART_BACKEND"] = name


def grid():
    return {"xAxis": {"type": "value", "min": 0, "max": 100},
            "yAxis": {"type": "value", "min": 0, "max": 100}}


def category():
    return {"xAxis": {"type": "category", "data": ["一", "二", "三"]},
            "yAxis": {"type": "value", "min": 0, "max": 10}}


def options():
    hierarchy = [{"name": "根", "children": [{"name": "叶", "value": 3}]}]
    named = [{"name": "甲", "value": 3}, {"name": "乙", "value": 5}]
    return [
        ("bar", dict(category(), series=[{"type": "bar", "data": [1, 3, 2]}])),
        ("pictorialBar", dict(category(), series=[{"type": "pictorialBar", "data": [1, 3, 2]}])),
        ("line", dict(category(), series=[{"type": "line", "data": [1, 3, 2]}])),
        ("scatter", dict(grid(), series=[{"type": "scatter", "data": [[10, 20], [50, 60]]}])),
        ("effectScatter", dict(grid(), series=[{"type": "effectScatter", "data": [[10, 20], [50, 60]]}])),
        ("candlestick", dict(category(), series=[{"type": "candlestick", "data": [[2, 4, 1, 5]]}])),
        ("boxplot", dict(category(), series=[{"type": "boxplot", "data": [[1, 2, 3, 4, 5]]}])),
        ("heatmap", {"xAxis": {"type": "category", "data": ["一", "二"]},
                     "yAxis": {"type": "category", "data": ["上", "下"]},
                     "series": [{"type": "heatmap", "data": [[0, 0, 3], [1, 1, 6]]}]}),
        ("parallel", {"parallelAxis": ["甲", "乙"],
                      "series": [{"type": "parallel", "data": [[1, 3], [2, 4]]}]}),
        ("themeRiver", {"series": [{"type": "themeRiver", "data": [
            ["2026-01", 3, "甲"], ["2026-02", 5, "甲"]]}]}),
        ("pie", {"series": [{"type": "pie", "data": named}]}),
        ("radar", {"series": [{"type": "radar", "indicator": [{"name": "甲"}, {"name": "乙"}],
                                "data": [[2, 4]]}]}),
        ("gauge", {"series": [{"type": "gauge", "data": named[:1]}]}),
        ("funnel", {"series": [{"type": "funnel", "data": named}]}),
        ("sunburst", {"series": [{"type": "sunburst", "data": hierarchy}]}),
        ("treemap", {"series": [{"type": "treemap", "data": hierarchy}]}),
        ("tree", {"series": [{"type": "tree", "data": hierarchy}]}),
        ("sankey", {"series": [{"type": "sankey", "data": [{"name": "甲"}, {"name": "乙"}],
                                 "links": [{"source": "甲", "target": "乙", "value": 3}]}]}),
        ("graph", {"series": [{"type": "graph", "data": [{"name": "甲"}, {"name": "乙"}],
                                "links": [{"source": "甲", "target": "乙"}]}]}),
        ("lines", dict(grid(), series=[{"type": "lines", "data": [
            {"coords": [[10, 20], [80, 70]]}]}])),
        ("map", {"series": [{"type": "map", "data": [{"name": "华北", "value": 3}]}]}),
    ]


class UnsupportedRenderer(SeriesRenderer):
    def layout(self, rect):
        self._points = []

    def paint(self, painter, anim_t):
        pass


class UnsupportedComponent:
    option_key = "canvasUnsupported"

    def __init__(self, chart, opt):
        self.chart = chart

    def paint(self, painter, anim_t=1.0):
        pass


class KeyChart(ChartWidget):
    def __init__(self):
        super().__init__()
        self.keys = []

    def keyPressEvent(self, event):  # noqa: N802
        self.keys.append(event.key())
        super().keyPressEvent(event)


@check("全部注册系列可由生产工厂创建 Canvas")
def _():
    backend("canvas")
    try:
        for name, option in options():
            chart = ChartWidget()
            chart.resize(640, 400)
            chart.set_option(dict(option, animation=False))
            chart.show()
            pump()
            try:
                viewport = chart._viewport
                assert isinstance(viewport, CanvasComponentsChartViewport), (name, type(viewport))
                viewport._sync_now()
                assert len(viewport._line_views) == len(chart.series_renderers), name
                assert all(model._visible for model in viewport._line_views), name
                assert viewport.active_backend() == "canvas-item-shared"
                assert "direct" in viewport.rhi_api().lower(), (name, viewport.rhi_api())
            finally:
                chart.close()
                pump()
    finally:
        backend(None)


@check("默认、raster 与不支持能力的完整 RHI 回退")
def _():
    register_series("canvasUnsupported", UnsupportedRenderer)
    register_component("canvasUnsupported", UnsupportedComponent)
    try:
        backend("raster")
        chart = ChartWidget()
        assert isinstance(chart._viewport, _RasterViewport)
        chart.close()
        backend(None)
        chart = ChartWidget()
        assert isinstance(chart._viewport, _RhiViewport)
        chart.close()
        backend("canvas")
        chart = ChartWidget()
        chart.set_option({"series": [{"type": "canvasUnsupported", "data": [1, 2]}]})
        assert isinstance(chart._viewport, _RhiViewport)
        assert getattr(chart, "_backend_fallback_reason", None)
        chart.close()
        chart = ChartWidget()
        chart.set_option({"canvasUnsupported": {}, "series": [{"type": "line", "data": [1, 2]}]})
        assert isinstance(chart._viewport, _RhiViewport)
        assert getattr(chart, "_backend_fallback_reason", None)
        chart.close()
    finally:
        SERIES_REGISTRY.pop("canvasUnsupported", None)
        COMPONENT_REGISTRY.pop("canvasUnsupported", None)
        backend(None)


@check("运行中遇到未知系列时安全回退且不泄漏旧视口")
def _():
    backend("canvas")
    register_series("canvasUnsupported", UnsupportedRenderer)
    chart = ChartWidget()
    try:
        chart.resize(640, 400)
        chart.set_option({"animation": False, "series": [{"type": "line", "data": [1, 2, 3]}]})
        chart.show()
        pump()
        old = chart._viewport
        assert isinstance(old, CanvasComponentsChartViewport)
        chart.update_option({"series": [{"type": "canvasUnsupported", "data": [1, 2]}]})
        old._sync_now()
        assert chart._viewport is not old
        assert isinstance(chart._viewport, _RhiViewport)
        assert chart._viewport.active_backend() == "rhi"
        assert chart._viewport.isVisible()
        assert getattr(chart, "_backend_fallback_reason", None)
    finally:
        SERIES_REGISTRY.pop("canvasUnsupported", None)
        chart.close()
        backend(None)
        pump()


@check("旧信号、同步耗时与真实键盘输入兼容")
def _():
    backend("canvas")
    chart = KeyChart()
    try:
        chart.resize(640, 400)
        chart.set_option({"animation": False, "series": [{"type": "line", "data": [1, 2, 3]}]})
        chart.show()
        pump()
        viewport = chart._viewport
        viewport._sync_now()
        assert viewport.mean_sync_ms() >= 0
        assert hasattr(viewport, "frameSwapped")
        viewport._view.requestActivate()
        viewport._view.contentItem().setFocus(True)
        QTest.keyClick(viewport._view, Qt.Key_A)
        pump()
        assert Qt.Key_A in chart.keys, chart.keys
    finally:
        chart.close()
        backend(None)
        pump()


if __name__ == "__main__":
    app.quit()
    raise SystemExit(1 if _FAILURES else 0)
