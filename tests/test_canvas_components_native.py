# -*- coding: utf-8 -*-
"""Canvas 标注、Graphic 与地图的真实 RHI 回归。"""

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
    from InstructionX_UIKit.charts.canvas_map import CanvasComponentsChartViewport
    chart.show()
    viewport = chart._viewport
    assert isinstance(viewport, CanvasComponentsChartViewport)
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
        raise RuntimeError("原生组件 RHI 回读失败")
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
    destination = ROOT / "temp" / "canvas_components_native"
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


@check("标注、虚线、标域与四类 Graphic 元素")
def _():
    ThemeManager.instance().apply(app)
    chart = ChartWidget()
    chart.set_option({
        "animation": False,
        "xAxis": {"type": "category", "data": ["一", "二", "三", "四"]},
        "yAxis": {"type": "value", "min": 0, "max": 10},
        "graphic": [
            {"type": "circle", "left": 80, "top": 80,
             "shape": {"r": 18}, "style": {"fill": "#845ec2", "stroke": "#202020"}},
            {"type": "rect", "left": 120, "top": 40,
             "shape": {"width": 70, "height": 30, "r": 4},
             "style": {"fill": "#ff6f91", "stroke": "#202020"}},
            {"type": "text", "left": 12, "top": 8,
             "style": {"text": "原生标注", "fill": "#3F5E8C", "fontSize": 14}},
            {"type": "line", "left": 30, "top": 120,
             "shape": {"x2": 90, "y2": 30},
             "style": {"stroke": "#d65db1", "lineWidth": 2}},
        ],
        "series": [{"type": "line", "name": "趋势", "data": [3, 7, 4, 9],
                    "markPoint": {"data": [{"type": "max", "name": "峰值"},
                                            {"coord": ["二", 7], "name": "指定"}]},
                    "markLine": {"data": [{"type": "average"}, {"yAxis": 6},
                                           {"xAxis": "二", "name": "竖线"}]},
                    "markArea": {"data": [[{"xAxis": "一"}, {"xAxis": "三"}],
                                           [{"yAxis": 2}, {"yAxis": 6}]]}}],
    })
    chart.resize(900, 600)
    viewport = make_view(chart)
    try:
        chart.anim.stop()
        chart.anim.set_progress(1.0)
        viewport._sync_now()
        scene = viewport._component_scene
        assert scene is not None
        texts = {command[1] for command in scene.commands if command[0] == "text"}
        assert {"峰值", "指定", "平均值 5.75", "竖线 二", "原生标注"} <= texts, texts
        components = {component.option_key: component for component in chart.components}
        assert len(components["markPoint"]._marks) == 2
        assert len(components["markLine"]._lines) == 3
        assert len(components["markArea"]._areas) == 2
        assert any(command[0] == "fill" for command in scene.commands)
        mark = components["markPoint"]._marks[0]
        hit = components["markPoint"].hit_test(mark["pos"])
        assert hit is not None and hit["name"] == "峰值"
        hover(viewport, mark["pos"])
        assert chart.tooltip.active and viewport._tooltip_scene is not None
        assert_matches(viewport, chart, "marks_graphic",
                       [QPointF(80, 80), QPointF(155, 55)])
        previous = scene
        chart.update_option({
            "graphic": [{"type": "text", "left": 12, "top": 8,
                         "style": {"text": "更新标注", "fill": "#3F5E8C", "fontSize": 14}}],
            "series": [{"type": "line", "name": "趋势", "data": [2, 8, 3, 6],
                        "markPoint": {"data": [{"type": "max", "name": "新峰值"}]},
                        "markLine": {"data": [{"type": "average"}]},
                        "markArea": {"data": [[{"yAxis": 1}, {"yAxis": 4}]]}}],
        })
        chart.anim.stop()
        chart.anim.set_progress(1.0)
        viewport._sync_now()
        assert viewport._component_scene is not previous
        texts = {command[1] for command in viewport._component_scene.commands
                 if command[0] == "text"}
        assert {"新峰值", "更新标注", "平均值 4.75"} <= texts, texts
        assert_matches(viewport, chart, "marks_update")
        chart.set_series_visible("趋势", False)
        viewport._sync_now()
        assert not any(command[0] == "text" and command[1] == "新峰值"
                       for command in viewport._component_scene.commands)
        ThemeManager.instance().set_mode("dark")
        viewport._sync_now()
        assert_matches(viewport, chart, "marks_dark")
    finally:
        viewport.close()
        chart.close()
        ThemeManager.instance().set_mode("light")
        pump(100)


@check("示意地图、区域命中、visualMap 与自定义地理数据")
def _():
    ThemeManager.instance().apply(app)
    chart = ChartWidget()
    chart.set_option({
        "animation": False,
        "visualMap": {"min": 0, "max": 100,
                      "inRange": {"colors": ["#EBEFF5", "#3F5E8C"]}},
        "series": [{"type": "map", "name": "区域", "map": "demo",
                    "data": [{"name": "华北", "value": 10}, {"name": "东北", "value": 50},
                             {"name": "华东", "value": 100}]}],
    })
    chart.resize(900, 600)
    viewport = make_view(chart)
    try:
        chart.anim.stop()
        chart.anim.set_progress(1.0)
        viewport._sync_now()
        renderer = chart.series_renderers[0]
        model = viewport._line_views[0]
        assert len(model._areas) == len(renderer._polys) == 7
        assert any(color.lightness() >= 130 for _path, color in model._areas)
        assert viewport._component_scene is not None
        points = []
        for name, polygon in renderer._polys:
            center = polygon.boundingRect().center()
            vertex = polygon[0]
            point = QPointF(vertex.x() * 0.85 + center.x() * 0.15,
                            vertex.y() * 0.85 + center.y() * 0.15)
            if polygon.containsPoint(point, Qt.OddEvenFill):
                hit = renderer.hit_test(point)
                assert hit is not None and hit["name"] == name, (name, hit)
                points.append(point)
        assert points
        assert_matches(viewport, chart, "map_demo", points)
        hover(viewport, points[0])
        assert chart.tooltip.active and viewport._tooltip_scene is not None
        chart.update_option({
            "geo": {"regions": {"甲区": [[0, 0], [10, 0], [10, 8], [0, 8]],
                                  "乙区": [[12, 0], [22, 0], [22, 8], [12, 8]]}},
            "visualMap": {"min": 0, "max": 10,
                          "inRange": {"colors": ["#fff7bc", "#d95f0e"]}},
            "series": [{"type": "map", "name": "区域", "map": "custom",
                        "data": [{"name": "甲区", "value": 1}, {"name": "乙区", "value": 9}]}],
        })
        chart.anim.stop()
        chart.anim.set_progress(1.0)
        viewport._sync_now()
        renderer = chart.series_renderers[0]
        model = viewport._line_views[0]
        assert model._source_polys is renderer._polys
        assert len(model._areas) == 2
        texts = {command[1] for command in model._scene.commands if command[0] == "text"}
        assert {"甲区", "乙区"} <= texts
        assert_matches(viewport, chart, "map_custom")
        ThemeManager.instance().set_mode("dark")
        viewport._sync_now()
        assert_matches(viewport, chart, "map_dark")
    finally:
        viewport.close()
        chart.close()
        ThemeManager.instance().set_mode("light")
        pump(100)


if __name__ == "__main__":
    app.quit()
    raise SystemExit(1 if _FAILURES else 0)
