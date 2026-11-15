# -*- coding: utf-8 -*-
"""Canvas Item 渲染线程数据隔离回归（直接运行，不使用 pytest）。"""

import os
from pathlib import Path
import sys
import traceback

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")

from types import SimpleNamespace
from PySide6.QtWidgets import QApplication, QWidget
from InstructionX_UIKit.charts import ChartWidget
from InstructionX_UIKit.charts.canvas_viewport import CanvasLineViewport
from InstructionX_UIKit.charts.canvas_item_viewport import _CanvasItemRenderer

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


@check("同步结果是独立普通数据而非可变 QWidget")
def _():
    chart = ChartWidget()
    chart.set_option({"animation": False,
                      "series": [{"type": "line", "data": [1, 3, 2], "showSymbol": True}]})
    chart.resize(800, 500)
    chart._layout_all(force=True)
    source = CanvasLineViewport(chart.series_renderers[0], chart.primary_coord())
    renderer = _CanvasItemRenderer()
    renderer.synchronizeData(SimpleNamespace(_line_views=[source], _static_scene=None))
    try:
        assert len(renderer._views) == 1
        snapshot = renderer._views[0]
        assert snapshot is not source and not isinstance(snapshot, QWidget)
        assert snapshot._coord is None
        assert snapshot._plot == source._plot
        assert snapshot._points == tuple(source._points)
        assert snapshot._color.getRgb() == source._color.getRgb()
        assert [path.commandsSize() for path in snapshot._paths] == [3]
        source.set_paths([])
        assert len(snapshot._points) == 3
        assert snapshot._paths[0].commandsSize() == 3
    finally:
        source.close()
        chart.close()


if __name__ == "__main__":
    app.quit()
    raise SystemExit(1 if _FAILURES else 0)
