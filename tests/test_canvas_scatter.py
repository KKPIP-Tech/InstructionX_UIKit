# -*- coding: utf-8 -*-
"""Canvas 散点、聚合与 effectScatter 涟漪回归。"""

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
from InstructionX_UIKit.charts.canvas_series import CanvasScatterChartViewport
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
    assert isinstance(viewport, CanvasScatterChartViewport)
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
        raise RuntimeError("散点回读失败")
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
    destination = ROOT / "temp" / "canvas_scatter"
    destination.mkdir(parents=True, exist_ok=True)
    actual.save(str(destination / f"{name}.png"))
    expected.save(str(destination / f"{name}_reference.png"))
    assert actual.size() == expected.size()
    actual_bbox, expected_bbox = series_ink_bbox(actual), series_ink_bbox(expected)
    assert actual_bbox is not None and expected_bbox is not None
    assert all(abs(a - b) <= 2 for a, b in zip(actual_bbox, expected_bbox)), (
        actual_bbox, expected_bbox)
    color = tuple(chart.series_renderers[0].color().getRgb())
    assert series_color_count(actual, color) > 0
    return actual


def hover(viewport, pos):
    global_pos = viewport.mapToGlobal(QPoint(round(pos.x()), round(pos.y())))
    event = QMouseEvent(QEvent.MouseMove, QPointF(pos), QPointF(pos),
                        QPointF(global_pos), Qt.NoButton, Qt.NoButton, Qt.NoModifier)
    QCoreApplication.sendEvent(viewport, event)
    viewport._sync_now()


@check("散点点径、large 聚合、tooltip、极坐标与涟漪生命周期")
def _():
    ThemeManager.instance().apply(app)
    chart = ChartWidget()
    chart.set_option({
        "animation": False,
        "xAxis": {"type": "value"}, "yAxis": {"type": "value"},
        "series": [{"type": "scatter", "name": "样本", "symbolSize": [6, 24],
                    "data": [[0, 1, 2], [1, 3, 8], [2, 2, 16], [3, 4, 24]]}],
    })
    chart.anim.stop()
    chart.anim.set_progress(1.0)
    chart.resize(800, 500)
    viewport = make_view(chart)
    try:
        viewport._sync_now()
        model = viewport._line_views[0]
        assert len(model._areas) == 4 and len(model._outlines) == 4
        assert model._areas[0][1].alpha() == 190
        assert model._outlines[0][1].alpha() == 230
        assert_matches(viewport, chart, "sizes")
        hover(viewport, chart.series_renderers[0]._dots[0]["pt"])
        assert chart.tooltip.active and viewport._tooltip_scene is not None
        chart.set_series_visible("样本", False)
        viewport._sync_now()
        assert not model._visible
        chart.set_series_visible("样本", True)
        viewport._sync_now()
        assert model._visible
        large = ChartWidget()
        large.set_option({"animation": False, "xAxis": {"type": "value"},
                          "yAxis": {"type": "value"},
                          "series": [{"type": "scatter", "name": "密度", "large": True,
                                      "data": np.sin(np.arange(20000) / 100)}]})
        large.anim.stop()
        large.anim.set_progress(1.0)
        large.resize(800, 500)
        large_view = make_view(large)
        try:
            large_view._sync_now()
            renderer = large.series_renderers[0]
            model = large_view._line_views[0]
            assert renderer._aggregated and model._aggregated
            assert 0 < len(model._areas) == len(renderer._dots) < 20000
            assert_matches(large_view, large, "large")
        finally:
            large_view.close()
            large.close()
        effect = ChartWidget()
        effect.set_option({
            "animation": False, "xAxis": {"type": "value"}, "yAxis": {"type": "value"},
            "series": [{"type": "effectScatter", "name": "涟漪",
                        "rippleEffect": {"period": 0.2, "scale": 2.6},
                        "data": [[0, 1], [1, 2], [2, 0]]}],
        })
        effect.anim.stop()
        effect.anim.set_progress(1.0)
        effect.resize(800, 500)
        effect_view = make_view(effect)
        try:
            effect_view._sync_now()
            renderer = effect.series_renderers[0]
            model = effect_view._line_views[0]
            assert len(model._ripples) == 3
            assert model._ripples[0][1].alpha() == 140
            assert model._ripples[0][2] == 1.6
            renderer._tick()
            effect_view._sync_now()
            assert model._phase == renderer._phase
            assert model._ripples[0][1].alpha() < 140
            effect.set_series_visible("涟漪", False)
            deadline = time.perf_counter() + 1.0
            while renderer._timer.isActive() and time.perf_counter() < deadline:
                pump(10)
            assert not renderer._timer.isActive()
            effect.set_series_visible("涟漪", True)
            effect_view._sync_now()
            assert renderer._timer.isActive()
            old_renderer = renderer
            effect.update_option({"series": [{"data": [[0, 2], [1, 1], [2, 3]]}]})
            effect_view._sync_now()
            assert effect_view._line_views[0]._renderer is effect.series_renderers[0]
            assert effect_view._line_views[0]._renderer is not old_renderer
            assert_matches(effect_view, effect, "effect")
        finally:
            effect_view.close()
            effect.close()
        polar = ChartWidget()
        polar.set_option({
            "animation": False, "polar": {"shape": "polygon"},
            "angleAxis": {"type": "category", "data": ["速", "力", "防"]},
            "radiusAxis": {"type": "value"},
            "series": [{"type": "scatter", "coordinateSystem": "polar",
                        "data": [["速", 80], ["力", 60], ["防", 70]]}],
        })
        polar.anim.stop()
        polar.anim.set_progress(1.0)
        polar.resize(800, 500)
        polar_view = make_view(polar)
        try:
            polar_view._sync_now()
            assert len(polar_view._line_views[0]._areas) == 3
            assert_matches(polar_view, polar, "polar")
        finally:
            polar_view.close()
            polar.close()
    finally:
        viewport.close()
        chart.close()
        pump(100)


if __name__ == "__main__":
    app.quit()
    raise SystemExit(1 if _FAILURES else 0)
