# -*- coding: utf-8 -*-
"""真实窗口共享 Canvas Scene Graph 与生命周期回归。"""

import os
from pathlib import Path
import sys
import time
import traceback

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.pop("QT_QPA_PLATFORM", None)

from PySide6.QtCore import QPointF, QSizeF, Qt
from PySide6.QtWidgets import QApplication, QHBoxLayout, QMainWindow, QWidget
from InstructionX_UIKit.charts import ChartWidget
from InstructionX_UIKit.charts.canvas_item_viewport import CanvasItemLineChartViewport

_FAILURES = []
app = QApplication.instance() or QApplication(sys.argv)


def pump(milliseconds=400):
    deadline = time.perf_counter() + milliseconds / 1000
    while time.perf_counter() < deadline:
        app.processEvents()
        time.sleep(0.005)


def replace(chart):
    viewport = CanvasItemLineChartViewport(chart, parent=chart)
    old = chart._viewport
    chart._viewport = viewport
    old.close()
    old.deleteLater()
    return viewport


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


@check("同窗口共享一个 RHI 视图并保持各自几何与生命周期")
def _():
    window = QMainWindow()
    central = QWidget(window)
    layout = QHBoxLayout(central)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(0)
    window.setCentralWidget(central)
    charts = []
    for index in range(2):
        chart = ChartWidget()
        chart.set_option({"animation": False, "xAxis": {"type": "value"},
                          "yAxis": {"type": "value"},
                          "series": [{"type": "line", "data": [1, 3 + index, 2],
                                      "showSymbol": False}]})
        layout.addWidget(chart)
        charts.append(chart)
    window.resize(1100, 600)
    window.show()
    viewports = [replace(chart) for chart in charts]
    for viewport in viewports:
        viewport.show()
    pump()
    try:
        first, second = viewports
        assert first._view is not None and first._view is second._view
        assert first._item.parentItem() is second._item.parentItem()
        for chart, viewport in zip(charts, viewports):
            assert viewport._item.size() == QSizeF(chart.size())
            expected = QPointF(chart.mapTo(window, chart.rect().topLeft()))
            assert viewport._item.position() == expected
            assert viewport.rhi_api() == "Direct3D11"
        window.showMinimized()
        pump()
        assert all(not chart._ui_active for chart in charts)
        assert not first._view.isVisible()
        window.showNormal()
        pump()
        assert all(chart._ui_active for chart in charts)
        assert first._view.isVisible()
        host = first._host
        charts[0].hide()
        pump()
        assert first._view is None
        assert second._view is host._view
        charts[0].show()
        pump()
        assert first._view is second._view
        assert first._line_views[0]._points == charts[0].series_renderers[0]._points
    finally:
        window.close()
        pump(100)


if __name__ == "__main__":
    app.quit()
    raise SystemExit(1 if _FAILURES else 0)
