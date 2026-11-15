# -*- coding: utf-8 -*-
"""Canvas heatmap、日历与 visualMap 的真实 RHI 回归。"""

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
from PySide6.QtWidgets import QApplication
from InstructionX_UIKit.charts import ChartWidget
from InstructionX_UIKit.theme import T, ThemeManager
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
    from InstructionX_UIKit.charts.canvas_series import CanvasHeatmapChartViewport
    chart.show()
    viewport = CanvasHeatmapChartViewport(chart, parent=chart)
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
        raise RuntimeError("热力图 RHI 回读失败")
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


def pixels(image):
    return np.frombuffer(image.constBits(), dtype=np.uint8).reshape(
        image.height(), image.width(), 4)


def center_rgb(image, point):
    dpr = image.devicePixelRatioF()
    return pixels(image)[round(point.y() * dpr), round(point.x() * dpr), :3]


def ink_bbox(image, rect):
    dpr = image.devicePixelRatioF()
    cropped = image.copy(round(rect.left() * dpr), round(rect.top() * dpr),
                         max(1, round(rect.width() * dpr)),
                         max(1, round(rect.height() * dpr)))
    return series_ink_bbox(cropped)


def assert_matches(viewport, chart, name):
    actual = grab(viewport)
    expected = reference(chart, viewport.devicePixelRatioF())
    destination = ROOT / "temp" / "canvas_heatmap"
    destination.mkdir(parents=True, exist_ok=True)
    actual.save(str(destination / f"{name}.png"))
    expected.save(str(destination / f"{name}_reference.png"))
    renderer = chart.series_renderers[0]
    assert len(renderer._cells) == len(viewport._line_views[0]._areas)
    bounds = None
    for index, cell in enumerate(renderer._cells):
        rect = cell["rect"].adjusted(-1, -1, 1, 1)
        bounds = rect if bounds is None else bounds.united(rect)
        actual_bbox = ink_bbox(actual, rect)
        expected_bbox = ink_bbox(expected, rect)
        assert actual_bbox is not None and expected_bbox is not None, (name, index)
        assert all(abs(a - b) <= 2 for a, b in zip(actual_bbox, expected_bbox)), (
            name, index, actual_bbox, expected_bbox)
        actual_center = center_rgb(actual, cell["rect"].center())
        expected_center = center_rgb(expected, cell["rect"].center())
        assert np.max(np.abs(actual_center.astype(int) - expected_center.astype(int))) <= 2, (
            name, index, actual_center, expected_center)
    if bounds is not None:
        actual_bbox = ink_bbox(actual, bounds)
        expected_bbox = ink_bbox(expected, bounds)
        assert actual_bbox is not None and expected_bbox is not None
        assert all(abs(a - b) <= 2 for a, b in zip(actual_bbox, expected_bbox)), (
            name, actual_bbox, expected_bbox)
    for component in chart.components:
        if component.option_key != "visualMap":
            continue
        bar = component._bar
        for fraction in (0.15, 0.5, 0.85):
            point = bar.center() if component.orient == "vertical" else None
            if point is None:
                point = bar.center()
                point.setX(bar.left() + bar.width() * fraction)
            else:
                point.setY(bar.top() + bar.height() * fraction)
            delta = np.abs(center_rgb(actual, point).astype(int)
                           - center_rgb(expected, point).astype(int))
            assert int(delta.max()) <= 2, (name, "visualMap", fraction, delta)


def hover(viewport, pos):
    global_pos = viewport.mapToGlobal(QPoint(round(pos.x()), round(pos.y())))
    event = QMouseEvent(QEvent.MouseMove, QPointF(pos), QPointF(pos),
                        QPointF(global_pos), Qt.NoButton, Qt.NoButton, Qt.NoModifier)
    QCoreApplication.sendEvent(viewport, event)
    viewport._sync_now()


def gradient_command(viewport):
    assert viewport._component_scene is not None
    commands = [command for command in viewport._component_scene.commands
                if command[0] == "gradient_path"]
    assert len(commands) == 1
    return commands[0]


@check("直角热力格、动画、visualMap 与更新")
def _():
    from InstructionX_UIKit.charts.canvas_series import CanvasHeatmapChartViewport
    ThemeManager.instance().apply(app)
    chart = ChartWidget()
    chart.set_option({
        "animation": True,
        "xAxis": {"type": "category", "data": ["一", "二", "三"]},
        "yAxis": {"type": "category", "data": ["上", "下"]},
        "visualMap": {"min": 0, "max": 10,
                      "inRange": {"colors": ["#EBEFF5", "#3F5E8C"]}},
        "series": [{"type": "heatmap", "name": "热度",
                    "data": [[0, 0, 0], [1, 0, 9], [2, 0, 2],
                             [0, 1, 3], [1, 1, 10], [2, 1, 8]]}],
    })
    chart.resize(800, 500)
    viewport = make_view(chart)
    try:
        chart.anim.stop()
        chart.anim.set_progress(0.5)
        viewport._sync_now()
        renderer = chart.series_renderers[0]
        model = viewport._line_views[0]
        assert isinstance(viewport, CanvasHeatmapChartViewport)
        assert len(model._areas) == 6
        for (_path, color), cell in zip(model._areas, renderer._cells):
            expected = cell["color"]
            expected.setAlpha(127)
            assert color.getRgb() == expected.getRgb(), (color.getRgb(), expected.getRgb())
        component = next(comp for comp in chart.components
                         if comp.option_key == "visualMap")
        command = gradient_command(viewport)
        assert command[1] == component._bar
        assert command[3].startColor().name() == "#3f5e8c"
        assert command[3].endColor().name() == "#ebeff5"
        assert "direct" in viewport.rhi_api().lower(), viewport.rhi_api()
        assert_matches(viewport, chart, "grid_half")
        chart.anim.set_progress(1.0)
        viewport._sync_now()
        assert_matches(viewport, chart, "grid")
        cached = viewport._static_scene
        first = renderer._cells[0]
        hover(viewport, first["rect"].center())
        assert chart.tooltip.active and viewport._tooltip_scene is not None
        assert viewport._static_scene is cached
        assert any(command[0] == "text" and command[1] == "热度: 0"
                   for command in viewport._tooltip_scene.commands), chart.tooltip._lines
        assert_matches(viewport, chart, "grid_tooltip")
        chart.update_option({
            "visualMap": {"min": 0, "max": 20,
                          "inRange": {"colors": ["#fff7bc", "#d95f0e"]}},
            "series": [{"type": "heatmap", "name": "热度",
                        "data": [[0, 0, 0], [1, 0, 20], [2, 0, 4],
                                 [0, 1, 6], [1, 1, 15], [2, 1, 8]]}],
        })
        chart.anim.stop()
        chart.anim.set_progress(1.0)
        viewport._sync_now()
        renderer = chart.series_renderers[0]
        model = viewport._line_views[0]
        assert model._source_cells is renderer._cells
        assert len(model._areas) == 6
        command = gradient_command(viewport)
        assert command[3].startColor().name() == "#d95f0e"
        assert command[3].endColor().name() == "#fff7bc"
        component = next(comp for comp in chart.components
                         if comp.option_key == "visualMap")
        assert component.max == 20 and any(command[0] == "text" and command[1] == "20"
                                            for command in viewport._component_scene.commands)
        assert_matches(viewport, chart, "grid_update")
        chart.set_series_visible("热度", False)
        viewport._sync_now()
        assert not model._visible
        hidden = grab(viewport)
        hidden.save(str(ROOT / "temp" / "canvas_heatmap" / "grid_hidden.png"))
        for cell in renderer._cells:
            color = np.array(cell["color"].getRgb(), dtype=np.uint8)
            assert int(np.count_nonzero(np.all(pixels(hidden) == color, axis=2))) == 0
    finally:
        viewport.close()
        chart.close()
        pump(100)


@check("日历中文标签、日期标记、水平色带与主题")
def _():
    previous = ThemeManager.instance().mode
    ThemeManager.instance().apply(app)
    chart = ChartWidget()
    chart.set_option({
        "animation": False,
        "title": {"text": "提交热力"},
        "calendar": {"year": 2026, "cellSize": "auto"},
        "visualMap": {"min": 0, "max": 10, "orient": "horizontal",
                      "inRange": {"colors": ["#ebedf0", "#216e39"]}},
        "tooltip": {"show": True, "trigger": "item"},
        "series": [{"type": "heatmap", "name": "提交", "coordinateSystem": "calendar",
                    "data": [["2026-01-05", 3], ["2026-02-14", 8],
                             ["2026-04-22", 5], ["2026-07-09", 9],
                             ["2026-10-01", 2], ["2026-12-31", 6]]}],
    })
    chart.resize(900, 400)
    viewport = make_view(chart)
    try:
        chart.anim.stop()
        chart.anim.set_progress(1.0)
        viewport._sync_now()
        coord = chart.primary_coord()
        renderer = chart.series_renderers[0]
        model = viewport._line_views[0]
        assert model._calendar and len(model._areas) == 6
        texts = {command[1] for command in viewport._static_scene.commands
                 if command[0] == "text"}
        assert {"周一", "周三", "周五", "1月", "2月", "12月", "提交热力"} <= texts
        component = next(comp for comp in chart.components
                         if comp.option_key == "visualMap")
        command = gradient_command(viewport)
        assert component.orient == "horizontal" and command[1] == component._bar
        assert command[3].startPosition().x() == component._bar.left()
        assert command[3].endPosition().x() == component._bar.right()
        assert_matches(viewport, chart, "calendar")
        cell = renderer._cells[1]
        hover(viewport, cell["rect"].center())
        assert chart.tooltip.active
        assert coord.date_at(cell["rect"].center()).isoformat() == "2026-02-14"
        assert any(command[0] == "text" and command[1] == "提交: 8"
                   for command in viewport._tooltip_scene.commands), chart.tooltip._lines
        day_rect = coord.cell_rect("2026-02-14").adjusted(0.5, 0.5, -0.5, -0.5)
        assert any(command[0] == "stroke" and command[3] == 1.4
                   for command in viewport._tooltip_scene.commands)
        assert day_rect.width() == coord.cell_size() - 1
        assert_matches(viewport, chart, "calendar_tooltip")
        ThemeManager.instance().set_mode("dark")
        viewport._sync_now()
        assert_matches(viewport, chart, "calendar_dark")
        assert gradient_command(viewport)[3].startColor().name() == "#ebedf0"
        chart.resize(700, 280)
        viewport._sync_now()
        assert model._source_cells is renderer._cells
        assert_matches(viewport, chart, "calendar_resize")
        hover(viewport, QPointF(2, 2))
        assert not chart.tooltip.active and viewport._tooltip_scene is None
    finally:
        viewport.close()
        chart.close()
        ThemeManager.instance().set_mode(previous)
        pump(100)


if __name__ == "__main__":
    app.quit()
    raise SystemExit(1 if _FAILURES else 0)
