# -*- coding: utf-8 -*-
"""Canvas 柱状系列的堆叠、圆角、水平条、动画与交互回归。"""

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
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from InstructionX_UIKit.charts import ChartWidget
from InstructionX_UIKit.charts.canvas_series import CanvasBarChartViewport
from InstructionX_UIKit.theme import T, ThemeManager
from run_canvas_line_features import series_clip_ok, series_color_count, series_ink_bbox

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


def make_view(chart):
    chart.show()
    viewport = CanvasBarChartViewport(chart, parent=chart)
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
        raise RuntimeError("柱状图回读失败")
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


def hover(viewport, pos):
    global_pos = viewport.mapToGlobal(QPoint(int(round(pos.x())), int(round(pos.y()))))
    event = QMouseEvent(QEvent.MouseMove, QPointF(pos), QPointF(pos),
                        QPointF(global_pos), Qt.NoButton, Qt.NoButton, Qt.NoModifier)
    QCoreApplication.sendEvent(viewport, event)
    viewport._sync_now()


@check("柱状堆叠、水平圆角、动画、tooltip 与显隐")
def _():
    previous = ThemeManager.instance().mode
    ThemeManager.instance().apply(app)
    chart = ChartWidget()
    chart.set_option({
        "animation": True,
        "xAxis": {"type": "category", "data": ["一", "二", "三"]},
        "yAxis": {"type": "value"},
        "series": [
            {"type": "bar", "name": "输入", "stack": "总量", "data": [3, -1, 2],
             "barWidth": 0.55, "barBorderRadius": 4},
            {"type": "bar", "name": "输出", "stack": "总量", "data": [2, -2, 1],
             "barWidth": 0.55, "barBorderRadius": 4},
        ],
    })
    chart.resize(800, 500)
    viewport = make_view(chart)
    destination = ROOT / "temp" / "canvas_bar"
    destination.mkdir(parents=True, exist_ok=True)
    try:
        chart.anim.stop()
        chart.anim.set_progress(0.5)
        viewport._sync_now()
        model = viewport._line_views[0]
        assert model._anim_t == 0.5
        assert len(model._areas) == 3
        assert len(viewport._line_views[1]._areas) == 3
        chart.anim.set_progress(1.0)
        viewport._sync_now()
        actual = grab(viewport)
        expected = reference(chart, viewport.devicePixelRatioF())
        actual.save(str(destination / "stacked.png"))
        expected.save(str(destination / "stacked_reference.png"))
        assert actual.size() == expected.size()
        actual_bbox, expected_bbox = series_ink_bbox(actual), series_ink_bbox(expected)
        assert actual_bbox is not None and expected_bbox is not None
        assert all(abs(a - b) <= 2 for a, b in zip(actual_bbox, expected_bbox)), (
            actual_bbox, expected_bbox)
        colors = [tuple(renderer.color().getRgb()) for renderer in chart.series_renderers]
        assert all(series_color_count(actual, color) > 0 for color in colors)
        outer = chart.primary_coord().plot.adjusted(-8, -8, 8, 8)
        assert series_clip_ok(actual, colors, outer, chart.legend._item_rects,
                              viewport.devicePixelRatioF())
        first = chart.series_renderers[0]._bars[0]["rect"].center()
        hover(viewport, first)
        assert chart.tooltip.active and viewport._tooltip_scene is not None
        center = chart.legend._item_rects[1].center()
        QTest.mouseClick(viewport, Qt.LeftButton, Qt.NoModifier,
                         QPoint(round(center.x()), round(center.y())))
        viewport._sync_now()
        assert not chart.series_renderers[1].visible
        disabled = grab(viewport)
        disabled.save(str(destination / "disabled.png"))
        assert series_color_count(disabled, colors[1]) == 0
        QTest.mouseClick(viewport, Qt.LeftButton, Qt.NoModifier,
                         QPoint(round(center.x()), round(center.y())))
        viewport._sync_now()
        assert chart.series_renderers[1].visible
        ThemeManager.instance().set_mode("dark")
        viewport._sync_now()
        dark = grab(viewport)
        dark.save(str(destination / "dark.png"))
        dark_colors = [tuple(renderer.color().getRgb()) for renderer in chart.series_renderers]
        assert dark_colors != colors
        assert all(series_color_count(dark, color) > 0 for color in dark_colors)
        horizontal = ChartWidget()
        horizontal.set_option({
            "animation": False,
            "xAxis": {"type": "value"},
            "yAxis": {"type": "category", "data": ["甲", "乙", "丙"]},
            "series": [{"type": "bar", "name": "水平", "data": [3, -1, 2],
                        "barBorderRadius": 3}],
        })
        horizontal.resize(800, 500)
        horizontal_view = make_view(horizontal)
        try:
            pump(100)
            assert horizontal.series_renderers[0]._horizontal
            assert len(horizontal_view._line_views[0]._areas) == 3
            actual = grab(horizontal_view)
            expected = reference(horizontal, horizontal_view.devicePixelRatioF())
            actual.save(str(destination / "horizontal.png"))
            expected.save(str(destination / "horizontal_reference.png"))
            actual_bbox, expected_bbox = series_ink_bbox(actual), series_ink_bbox(expected)
            assert all(abs(a - b) <= 2 for a, b in zip(actual_bbox, expected_bbox))
        finally:
            horizontal_view.close()
            horizontal.close()
    finally:
        viewport.close()
        chart.close()
        ThemeManager.instance().set_mode(previous)
        pump(100)


if __name__ == "__main__":
    app.quit()
    raise SystemExit(1 if _FAILURES else 0)
