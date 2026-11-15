# -*- coding: utf-8 -*-
"""Canvas K 线与箱线图回归。"""

import os
from pathlib import Path
import sys
import time
import traceback

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests" / "perf"))
os.environ.pop("QT_QPA_PLATFORM", None)
os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")

import numpy as np
from PySide6.QtCore import QCoreApplication, QEvent, QPoint, QPointF, Qt, QTimer
from PySide6.QtGui import QColor, QImage, QMouseEvent, QPainter
from PySide6.QtWidgets import QApplication
from InstructionX_UIKit.charts import ChartWidget
from InstructionX_UIKit.charts.canvas_series import CanvasFinancialChartViewport
from InstructionX_UIKit.theme import T, ThemeManager
from run_canvas_line_features import series_color_count, series_ink_bbox

_FAILURES = []
app = QApplication.instance() or QApplication(sys.argv)


def pump(milliseconds=250):
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


def make_view(chart):
    chart.show()
    viewport = CanvasFinancialChartViewport(chart, parent=chart)
    old = chart._viewport
    chart._viewport = viewport
    old.close()
    old.deleteLater()
    viewport.show()
    return viewport


def grab(viewport):
    result = {}

    def captured(image):
        result["image"] = image.copy()
        app.exit(0)

    QTimer.singleShot(0, lambda: viewport.grab_canvas(captured))
    QTimer.singleShot(6000, lambda: app.exit(2))
    if app.exec() != 0 or result.get("image") is None:
        raise RuntimeError("金融图回读失败")
    return result["image"].convertToFormat(QImage.Format_RGBA8888)


def reference(chart, dpr):
    image = QImage(round(chart.width() * dpr), round(chart.height() * dpr),
                   QImage.Format_ARGB32_Premultiplied)
    image.setDevicePixelRatio(dpr)
    image.fill(Qt.transparent)
    chart._static_pixmap_cache = None
    chart._series_pixmap_cache = None
    painter = QPainter(image)
    painter.setRenderHint(QPainter.Antialiasing)
    chart._paint_contents(painter)
    painter.end()
    return image.convertToFormat(QImage.Format_RGBA8888)


def assert_matches(viewport, chart, name):
    actual = grab(viewport)
    expected = reference(chart, viewport.devicePixelRatioF())
    destination = ROOT / "temp" / "canvas_financial"
    destination.mkdir(parents=True, exist_ok=True)
    actual.save(str(destination / f"{name}.png"))
    expected.save(str(destination / f"{name}_reference.png"))
    actual_bbox, expected_bbox = series_ink_bbox(actual), series_ink_bbox(expected)
    assert actual_bbox is not None and expected_bbox is not None
    assert all(abs(a - b) <= 2 for a, b in zip(actual_bbox, expected_bbox)), (
        actual_bbox, expected_bbox)
    color = tuple(chart.series_renderers[0].color().getRgb())
    assert series_color_count(actual, color) > 0


def hover(viewport, pos):
    global_pos = viewport.mapToGlobal(QPoint(round(pos.x()), round(pos.y())))
    event = QMouseEvent(QEvent.MouseMove, QPointF(pos), QPointF(pos),
                        QPointF(global_pos), Qt.NoButton, Qt.NoButton, Qt.NoModifier)
    QCoreApplication.sendEvent(viewport, event)
    viewport._sync_now()


@check("K 线涨跌与插值、箱线图和 tooltip")
def _():
    ThemeManager.instance().apply(app)
    chart = ChartWidget()
    chart.set_option({
        "animation": True, "xAxis": {"type": "category", "data": ["一", "二", "三"]},
        "yAxis": {"type": "value"},
        "series": [{"type": "candlestick", "name": "价格", "barWidth": 12,
                    "data": [[2, 4, 1, 5], [4, 3, 2, 5], [3, 3, 2, 6]]}],
    })
    chart.resize(800, 500)
    viewport = make_view(chart)
    try:
        chart.anim.stop()
        chart.anim.set_progress(0.5)
        viewport._sync_now()
        model = viewport._line_views[0]
        assert model._anim_t == 0.5
        assert len(model._areas) == 3 and len(model._outlines) == 3
        assert model._outlines[0][2] == 1.2
        chart.anim.set_progress(1.0)
        viewport._sync_now()
        assert_matches(viewport, chart, "candlestick")
        rising = QColor(T("color.danger")).getRgb()
        falling = QColor(T("color.success")).getRgb()
        assert model._areas[0][1].getRgb() == rising
        assert model._areas[1][1].getRgb() == falling
        first = chart.series_renderers[0]._items[0]
        point = QPointF(first["cx"], chart.primary_coord().y_axis.map(
            first["close"], chart.primary_coord().plot.bottom(), chart.primary_coord().plot.top()))
        hover(viewport, point)
        assert chart.tooltip.active and viewport._tooltip_scene is not None
        chart.update_option({"series": [{"type": "candlestick", "name": "价格",
                                          "data": [[3, 5, 2, 6], [5, 4, 3, 6], [4, 4, 3, 7]]}]})
        chart.anim.stop()
        chart.anim.set_progress(0.5)
        viewport._sync_now()
        model = viewport._line_views[0]
        assert model._anim_t == 0.5
        assert model._source_items[0]["prev"] is not None
        chart.anim.set_progress(1.0)
        viewport._sync_now()
        assert_matches(viewport, chart, "candlestick_update")
        box = ChartWidget()
        box.set_option({
            "animation": True, "xAxis": {"type": "category", "data": ["甲", "乙"]},
            "yAxis": {"type": "value"},
            "series": [{"type": "boxplot", "name": "分布",
                        "data": [[1, 2, 3, 4, 5], [0, 2.5, 3.5, 4.5, 6]]}],
        })
        box.resize(800, 500)
        box_view = make_view(box)
        try:
            box.anim.stop()
            box.anim.set_progress(0.5)
            box_view._sync_now()
            model = box_view._line_views[0]
            assert len(model._areas) == 2 and len(model._outlines) == 10
            assert model._areas[0][1].alpha() == 60
            assert {item[2] for item in model._outlines} == {1.2, 1.4, 2.0}
            box.anim.set_progress(1.0)
            box_view._sync_now()
            assert_matches(box_view, box, "boxplot")
            first = box.series_renderers[0]._items[0]
            hover(box_view, QPointF(first["cx"], box.primary_coord().y_axis.map(
                first["vals"][2], box.primary_coord().plot.bottom(),
                box.primary_coord().plot.top())))
            assert box.tooltip.active and box_view._tooltip_scene is not None
        finally:
            box_view.close()
            box.close()
    finally:
        viewport.close()
        chart.close()
        pump(100)


if __name__ == "__main__":
    app.quit()
    raise SystemExit(1 if _FAILURES else 0)
