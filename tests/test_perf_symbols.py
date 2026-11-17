# -*- coding: utf-8 -*-
"""普通实线批量绘制与显式符号预算回归（直接运行）。"""

import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PySide6.QtGui import QImage, QPainter
from PySide6.QtWidgets import QApplication

from InstructionX_UIKit.charts import ChartWidget
from InstructionX_UIKit.theme import ThemeManager

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


class RecordingPainter(QPainter):
    def __init__(self, image):
        super().__init__(image)
        self.polylines = 0
        self.paths = 0
        self.ellipses = 0

    def drawPolyline(self, *args):
        self.polylines += 1
        return super().drawPolyline(*args)

    def drawPath(self, *args):
        self.paths += 1
        return super().drawPath(*args)

    def drawEllipse(self, *args):
        self.ellipses += 1
        return super().drawEllipse(*args)


def make_series(data, extra=None, polar=False):
    chart = ChartWidget()
    chart.resize(480, 320)
    option = {"series": [dict({"type": "line", "data": data}, **(extra or {}))]}
    if polar:
        option["polar"] = {}
        option["series"][0]["coordinateSystem"] = "polar"
    else:
        option["xAxis"] = {"type": "value"}
        option["yAxis"] = {"type": "value"}
    chart.set_option(option)
    chart.anim.stop()
    chart.anim.set_progress(1.0)
    chart._layout_all(force=True)
    return chart, chart.series_renderers[0]


@check("普通实线使用批量 drawPolyline")
def _():
    chart, renderer = make_series([1, 2, 3, 4], {"showSymbol": False})
    image = QImage(480, 320, QImage.Format_ARGB32_Premultiplied)
    painter = RecordingPainter(image)
    renderer.paint(painter, 1.0)
    painter.end()
    assert painter.polylines == 1, painter.polylines
    assert painter.paths == 0, painter.paths
    chart.close()


@check("smooth、step、area 和 polar 保留原路径")
def _():
    for extra in ({"smooth": True}, {"step": "middle"},
                  {"areaStyle": {"opacity": 0.22}}):
        chart, renderer = make_series([1, 2, 3, 4], extra)
        image = QImage(480, 320, QImage.Format_ARGB32_Premultiplied)
        painter = RecordingPainter(image)
        renderer.paint(painter, 1.0)
        painter.end()
        assert painter.polylines == 0, (extra, painter.polylines)
        assert painter.paths > 0, (extra, painter.paths)
        chart.close()
    chart, renderer = make_series([1, 2, 3, 4], polar=True)
    image = QImage(480, 320, QImage.Format_ARGB32_Premultiplied)
    painter = RecordingPainter(image)
    renderer.paint(painter, 1.0)
    painter.end()
    assert painter.polylines == 0
    assert painter.paths > 0
    chart.close()


@check("showSymbol auto 仅显式启用预算，默认语义不变")
def _():
    for setting, count, expected in (
            ("auto", 4, 4), ("auto", 600, 0),
            (None, 600, 600), (True, 600, 600), (False, 600, 0)):
        extra = {} if setting is None else {"showSymbol": setting}
        chart, renderer = make_series(list(range(count)), extra)
        image = QImage(480, 320, QImage.Format_ARGB32_Premultiplied)
        painter = RecordingPainter(image)
        renderer.paint(painter, 1.0)
        painter.end()
        assert painter.ellipses == expected, (setting, count, painter.ellipses)
        assert renderer._last_symbol_count == expected, renderer._last_symbol_count
        chart.close()


if __name__ == "__main__":
    app.quit()
    raise SystemExit(1 if _FAILURES else 0)
