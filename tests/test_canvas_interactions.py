# -*- coding: utf-8 -*-
"""Canvas dataZoom、brush、timeline 与 toolbox 的交互回归。"""

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
from PySide6.QtGui import QImage, QMouseEvent, QPainter
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from InstructionX_UIKit.charts import ChartWidget
from InstructionX_UIKit.charts.canvas_map import CanvasComponentsChartViewport
from InstructionX_UIKit.theme import ThemeManager
from run_canvas_line_features import series_ink_bbox

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
    viewport = CanvasComponentsChartViewport(chart, parent=chart)
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
        raise RuntimeError("交互组件 RHI 回读失败")
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


def center_rgb(image, point):
    dpr = image.devicePixelRatioF()
    pixels = np.frombuffer(image.constBits(), dtype=np.uint8).reshape(
        image.height(), image.width(), 4)
    x, y = round(point.x() * dpr), round(point.y() * dpr)
    return pixels[y - 1:y + 2, x - 1:x + 2, :3].mean(axis=(0, 1))


def assert_matches(viewport, chart, name, points=()):
    actual = grab(viewport)
    expected = reference(chart, viewport.devicePixelRatioF())
    destination = ROOT / "temp" / "canvas_interactions"
    destination.mkdir(parents=True, exist_ok=True)
    actual.save(str(destination / f"{name}.png"))
    expected.save(str(destination / f"{name}_reference.png"))
    actual_bbox, expected_bbox = series_ink_bbox(actual), series_ink_bbox(expected)
    assert actual_bbox is not None and expected_bbox is not None, name
    assert all(abs(a - b) <= 2 for a, b in zip(actual_bbox, expected_bbox)), (
        name, actual_bbox, expected_bbox)
    for point in points:
        delta = np.abs(center_rgb(actual, point).astype(int)
                       - center_rgb(expected, point).astype(int))
        assert int(delta.max()) <= 2, (name, point, delta)


def hover(viewport, pos):
    global_pos = viewport.mapToGlobal(QPoint(round(pos.x()), round(pos.y())))
    event = QMouseEvent(QEvent.MouseMove, QPointF(pos), QPointF(pos),
                        QPointF(global_pos), Qt.NoButton, Qt.NoButton, Qt.NoModifier)
    QCoreApplication.sendEvent(viewport, event)
    viewport._sync_now()


def point(rect):
    return QPoint(round(rect.center().x()), round(rect.center().y()))


def sync(viewport):
    app.processEvents()
    viewport._sync_now()


@check("dataZoom 滑块拖动、把手与恢复")
def _():
    ThemeManager.instance().apply(app)
    chart = ChartWidget()
    chart.set_option({
        "animation": False,
        "xAxis": {"type": "category", "data": list("一二三四五六七八九十")},
        "yAxis": {"type": "value", "min": 0, "max": 10},
        "dataZoom": [{"type": "slider", "start": 20, "end": 60}],
        "series": [{"type": "line", "name": "窗口", "data": [2, 4, 3, 7, 5, 8, 4, 6, 3, 9]}],
    })
    chart.resize(900, 600)
    viewport = make_view(chart)
    try:
        sync(viewport)
        component = chart.components[0]
        assert component.has_slider and not component._track.isNull()
        assert_matches(viewport, chart, "datazoom_slider")
        old_scene = viewport._component_scene
        QTest.mousePress(viewport, Qt.LeftButton, Qt.NoModifier, point(component._h_end))
        QTest.mouseMove(viewport, QPoint(round(component._x_of(80)),
                                       round(component._track.center().y())))
        QTest.mouseRelease(viewport, Qt.LeftButton, Qt.NoModifier,
                           QPoint(round(component._x_of(80)),
                                  round(component._track.center().y())))
        sync(viewport)
        assert component.end > 75, (component.start, component.end)
        assert viewport._component_scene is not old_scene
        assert_matches(viewport, chart, "datazoom_drag")
        component.restore()
        sync(viewport)
        assert (component.start, component.end) == (20, 60)
        assert_matches(viewport, chart, "datazoom_restored")
        ThemeManager.instance().set_mode("dark")
        sync(viewport)
        assert_matches(viewport, chart, "datazoom_dark")
    finally:
        viewport.close()
        chart.close()
        ThemeManager.instance().set_mode("light")
        pump(100)


@check("brush 鼠标框选、信号、遮罩与高亮")
def _():
    ThemeManager.instance().apply(app)
    chart = ChartWidget()
    chart.set_option({
        "animation": False,
        "xAxis": {"type": "category", "data": ["一", "二", "三", "四"]},
        "yAxis": {"type": "value", "min": 0, "max": 10},
        "brush": {"outOfBrush": {"opacity": 0.4}},
        "series": [{"type": "line", "name": "刷选", "data": [2, 5, 4, 8]}],
    })
    chart.resize(900, 600)
    viewport = make_view(chart)
    try:
        sync(viewport)
        component = chart.components[0]
        selected = []
        component.selected.connect(selected.extend)
        plot = chart.primary_coord().plot
        start = QPoint(round(plot.left() + 20), round(plot.top() + 20))
        end = QPoint(round(plot.right() - 20), round(plot.bottom() - 20))
        QTest.mousePress(viewport, Qt.LeftButton, Qt.NoModifier, start)
        QTest.mouseMove(viewport, end)
        sync(viewport)
        assert component._rect is not None
        assert_matches(viewport, chart, "brush_drag")
        QTest.mouseRelease(viewport, Qt.LeftButton, Qt.NoModifier, end)
        sync(viewport)
        assert len(component.selected_items) == 4 and len(selected) == 4, selected
        assert component._rect is not None
        assert any(command[0] == "stroke_pen" and command[3] == 1.8
                   for command in viewport._component_scene.commands)
        assert_matches(viewport, chart, "brush_selected")
        ThemeManager.instance().set_mode("dark")
        sync(viewport)
        assert_matches(viewport, chart, "brush_dark")
    finally:
        viewport.close()
        chart.close()
        ThemeManager.instance().set_mode("light")
        pump(100)


@check("timeline 切帧、播放暂停与定时器清理")
def _():
    ThemeManager.instance().apply(app)
    chart = ChartWidget()
    chart.set_option({
        "animation": False,
        "xAxis": {"type": "category", "data": ["一", "二", "三"]},
        "yAxis": {"type": "value", "min": 0, "max": 10},
        "timeline": {"data": ["2024", "2025", "2026"], "autoPlay": False,
                     "playInterval": 1000},
        "options": [
            {"series": [{"type": "line", "name": "年度", "data": [1, 2, 3]}]},
            {"series": [{"type": "line", "name": "年度", "data": [3, 5, 4]}]},
            {"series": [{"type": "line", "name": "年度", "data": [6, 4, 8]}]},
        ],
        "series": [{"type": "line", "name": "年度", "data": [1, 2, 3]}],
    })
    chart.resize(900, 600)
    viewport = make_view(chart)
    try:
        sync(viewport)
        component = next(comp for comp in chart.components if comp.option_key == "timeline")
        assert not component.playing and component.current == 0
        assert_matches(viewport, chart, "timeline_2024")
        timer = component._timer
        previous_scene = viewport._component_scene
        component.goto(1)
        sync(viewport)
        component = next(comp for comp in chart.components if comp.option_key == "timeline")
        assert component.current == 1 and timer is not component._timer
        assert not timer.isActive()
        assert viewport._component_scene is not previous_scene
        assert chart.series_renderers[0]._points[1].y() < chart.primary_coord().plot.center().y()
        assert_matches(viewport, chart, "timeline_2025")
        QTest.mouseClick(viewport, Qt.LeftButton, Qt.NoModifier, point(component._play_rect))
        sync(viewport)
        assert component.playing and component._timer.isActive()
        component.toggle_play()
        sync(viewport)
        assert not component.playing and not component._timer.isActive()
        component._timer.stop()
    finally:
        for component in chart.components:
            if component.option_key == "timeline":
                component._timer.stop()
        viewport.close()
        chart.close()
        pump(100)


@check("toolbox 真实点击、动作回调、缩放开关与恢复")
def _():
    ThemeManager.instance().apply(app)
    chart = ChartWidget()
    chart.set_option({
        "animation": False,
        "xAxis": {"type": "category", "data": list("一二三四五六")},
        "yAxis": {"type": "value", "min": 0, "max": 10},
        "dataZoom": [{"type": "inside", "start": 0, "end": 100}],
        "toolbox": {"feature": ["restore", "dataZoom"]},
        "series": [{"type": "line", "name": "工具", "data": [2, 5, 4, 7, 3, 8]}],
    })
    chart.resize(900, 600)
    viewport = make_view(chart)
    try:
        sync(viewport)
        toolbox = next(comp for comp in chart.components if comp.option_key == "toolbox")
        zoom = next(comp for comp in chart.components if comp.option_key == "dataZoom")
        actions = []
        toolbox.on_action = actions.append
        assert_matches(viewport, chart, "toolbox")
        zoom.start, zoom.end = 20, 60
        zoom.apply()
        chart.set_series_visible("工具", False)
        sync(viewport)
        QTest.mouseClick(viewport, Qt.LeftButton, Qt.NoModifier,
                         point(toolbox.button_rect("dataZoom")))
        sync(viewport)
        assert actions == ["dataZoom"] and not chart.datazoom_enabled
        assert_matches(viewport, chart, "toolbox_disabled")
        QTest.mouseClick(viewport, Qt.LeftButton, Qt.NoModifier,
                         point(toolbox.button_rect("restore")))
        sync(viewport)
        assert actions == ["dataZoom", "restore"]
        assert chart.series_renderers[0].visible
        assert (zoom.start, zoom.end) == (0, 100)
        assert_matches(viewport, chart, "toolbox_restored")
        ThemeManager.instance().set_mode("dark")
        sync(viewport)
        assert_matches(viewport, chart, "toolbox_dark")
    finally:
        viewport.close()
        chart.close()
        ThemeManager.instance().set_mode("light")
        pump(100)


if __name__ == "__main__":
    app.quit()
    raise SystemExit(1 if _FAILURES else 0)
