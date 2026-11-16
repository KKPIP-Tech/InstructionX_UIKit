# -*- coding: utf-8 -*-
"""Canvas Item 最终关闭与 renderer 延迟释放回归。"""

import gc
import os
from pathlib import Path
import sys
import time
import traceback
import weakref

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.pop("QT_QPA_PLATFORM", None)

from PySide6.QtWidgets import QApplication
from InstructionX_UIKit.charts import ChartWidget
from InstructionX_UIKit.charts import canvas_item_viewport as canvas_item

_FAILURES = []
app = QApplication.instance() or QApplication(sys.argv)


def pump(milliseconds=300):
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


@check("直接视口销毁后释放绘制数据与控件")
def _():
    chart = ChartWidget()
    chart.set_option({"animation": False, "series": [
        {"type": "line", "data": [1, 3, 2, 4], "showSymbol": False}]})
    chart.resize(800, 500)
    viewport = canvas_item.CanvasItemLineChartViewport(chart)
    old = chart._viewport
    chart._viewport = viewport
    old.close()
    old.deleteLater()
    viewport.show()
    pump()
    viewport._sync_now()
    assert viewport._canvas_renderer._views
    reference = weakref.ref(viewport)
    viewport.close()
    pump()
    try:
        assert viewport._view is None
        assert not viewport._canvas_renderer._views
        chart.close()
        old.close()
        pump(100)
        viewport = None
        chart = None
        old = None
        gc.collect()
        pump(100)
        assert reference() is None
    finally:
        if viewport is not None:
            viewport.close()
        if chart is not None:
            chart.close()
        pump(100)


if __name__ == "__main__":
    app.quit()
    raise SystemExit(1 if _FAILURES else 0)
