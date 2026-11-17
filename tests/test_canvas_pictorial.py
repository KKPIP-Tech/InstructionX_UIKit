# -*- coding: utf-8 -*-
"""Canvas pictorialBar 象形柱回归。"""

import os
from pathlib import Path
import sys
import time
import traceback

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests" / "perf"))
os.environ.pop("QT_QPA_PLATFORM", None)
os.environ["UIKIT_CHART_BACKEND"] = "canvas"
os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")

import numpy as np
from PySide6.QtCore import QCoreApplication, QEvent, QPoint, QPointF, Qt, QTimer
from PySide6.QtGui import QImage, QMouseEvent, QPainter
from PySide6.QtWidgets import QApplication
from InstructionX_UIKit.charts import ChartWidget
from InstructionX_UIKit.charts.canvas_series import CanvasPictorialChartViewport
from InstructionX_UIKit.theme import ThemeManager
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
    viewport = chart._viewport
    assert isinstance(viewport, CanvasPictorialChartViewport)
    chart.activateWindow()
    viewport._sync_now()
    return viewport


def grab(viewport):
    result = {}

    def captured(image):
        result["image"] = image.copy()
        app.exit(0)

    QTimer.singleShot(0, lambda: viewport.grab_canvas(captured))
    QTimer.singleShot(6000, lambda: app.exit(2))
    if app.exec() != 0 or result.get("image") is None:
        raise RuntimeError("象形柱回读失败")
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
    destination = ROOT / "temp" / "canvas_pictorial"
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


@check("象形柱符号、重复、水平方向、动画与 tooltip")
def _():
    ThemeManager.instance().apply(app)
    for name, symbol, repeat in (("rect", "rect", True), ("circle", "circle", 2), ("pin", "pin", False)):
        chart = ChartWidget()
        chart.set_option({
            "animation": True, "xAxis": {"type": "category", "data": ["一", "二", "三"]},
            "yAxis": {"type": "value"},
            "series": [{"type": "pictorialBar", "name": name, "symbol": symbol,
                        "symbolRepeat": repeat, "symbolSize": [6, 8], "data": [10, 5, 3]}],
        })
        chart.resize(800, 500)
        viewport = make_view(chart)
        try:
            chart.anim.stop()
            chart.anim.set_progress(0.5)
            viewport._sync_now()
            model = viewport._line_views[0]
            assert model._anim_t == 0.5
            chart.anim.set_progress(1.0)
            viewport._sync_now()
            assert len(model._areas) >= 3
            if repeat is True:
                assert len(model._areas) > 3
            else:
                assert len(model._areas) == 6 if repeat == 2 else 3
            assert_matches(viewport, chart, name)
            hover(viewport, chart.series_renderers[0]._bars[0]["rect"].center())
            assert chart.tooltip.active and viewport._tooltip_scene is not None
        finally:
            viewport.close()
            chart.close()
    horizontal = ChartWidget()
    horizontal.set_option({
        "animation": False, "xAxis": {"type": "value"},
        "yAxis": {"type": "category", "data": ["甲", "乙", "丙"]},
        "series": [{"type": "pictorialBar", "name": "水平", "symbol": "pin",
                    "symbolRepeat": 2, "symbolSize": [6, 8], "data": [3, -1, 2]}],
    })
    horizontal.anim.stop()
    horizontal.anim.set_progress(1.0)
    horizontal.resize(800, 500)
    viewport = make_view(horizontal)
    try:
        viewport._sync_now()
        assert horizontal.series_renderers[0]._horizontal
        assert len(viewport._line_views[0]._areas) == 6
        assert_matches(viewport, horizontal, "horizontal")
    finally:
        viewport.close()
        horizontal.close()
        pump(100)


if __name__ == "__main__":
    app.quit()
    raise SystemExit(1 if _FAILURES else 0)
