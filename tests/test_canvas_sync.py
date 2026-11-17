# -*- coding: utf-8 -*-
"""多系列 Canvas 数据同步回归（直接运行，不使用 pytest）。"""

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


@check("点列地址复用后仍同步最新流式几何")
def _():
    chart = ChartWidget()
    chart.set_option({"animation": False, "xAxis": {"type": "value"},
                      "yAxis": {"type": "value", "min": -2, "max": 2},
                      "series": [{"type": "line", "data": np.arange(20000, dtype=float),
                                  "showSymbol": False}]})
    chart.resize(1268, 850)
    viewport = CanvasLineChartViewport(chart, parent=chart)
    try:
        for tick in range(3):
            assert chart.set_stream_data(np.arange(20000, dtype=float) + tick)
            viewport._sync_now()
            model = viewport._line_views[0]
            renderer = chart.series_renderers[0]
            assert model._points == renderer._points
            assert [path.commandsSize() for path in model._paths] == [len(renderer._points)]
    finally:
        viewport.close()
        chart.close()


if __name__ == "__main__":
    app.quit()
    raise SystemExit(1 if _FAILURES else 0)
