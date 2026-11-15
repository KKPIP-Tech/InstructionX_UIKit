# -*- coding: utf-8 -*-
"""Canvas 数值屏幕坐标与兼容几何回归（直接运行，不使用 pytest）。"""

import os
from pathlib import Path
import sys
import traceback

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")

import numpy as np
from PySide6.QtWidgets import QApplication
from InstructionX_UIKit.charts import ChartWidget
from InstructionX_UIKit.charts.canvas_viewport import CanvasLineChartViewport

_FAILURES = []
app = QApplication.instance() or QApplication(sys.argv)


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


@check("数组直供路径与按需兼容几何逐点一致")
def _():
    values = np.sin(np.arange(20000) / 700)
    values[0] = 0.01
    chart = ChartWidget()
    chart.set_option({"animation": False, "xAxis": {"type": "value"},
                      "yAxis": {"type": "value", "min": -2, "max": 2},
                      "series": [{"type": "line", "data": values, "showSymbol": False}]})
    chart.resize(1268, 850)
    chart.show()
    viewport = CanvasLineChartViewport(chart, parent=chart)
    old = chart._viewport
    chart._viewport = viewport
    old.close()
    old.deleteLater()
    viewport.show()
    try:
        for tick in range(3):
            assert chart.set_stream_data(np.roll(values, tick * 17))
            viewport._sync_now()
            renderer = chart.series_renderers[0]
            model = viewport._line_views[0]
            geometry = renderer._gpu_geometry
            assert geometry is not None and model._screen_geometry is geometry
            plot = chart.primary_coord().plot
            assert abs(geometry[0][0] - plot.left()) < 1e-9, geometry[0][0]
            assert abs(geometry[0][-1] - plot.right()) < 1e-9, geometry[0][-1]
            assert np.all(geometry[0][1:] >= geometry[0][:-1]), "屏幕折线不得回连左边界"
            assert [path.commandsSize() for path in model._paths] == [len(geometry[0])]
            renderer._points = []
            assert chart._perf_snapshot()["screen_points"] == len(geometry[0])
            renderer._ensure_legacy_geometry()
            assert all(abs(point.x() - x) < 1e-9 and abs(point.y() - y) < 1e-9
                       for point, x, y in zip(renderer._points, *geometry))
            assert renderer.hit_test(renderer._points[len(renderer._points) // 2]) is not None
            assert renderer._gpu_geometry is None
            viewport._sync_now()
            assert all(model._points == renderer._points for model in viewport._line_views)
    finally:
        viewport.close()
        chart.close()


if __name__ == "__main__":
    app.quit()
    raise SystemExit(1 if _FAILURES else 0)
