# -*- coding: utf-8 -*-
"""Canvas 漏斗、旭日图与矩形树图的真实 RHI 回归。"""

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
HIERARCHY = [{"name": "水果", "children": [
    {"name": "苹果", "children": [{"name": "红富士", "value": 3},
                                  {"name": "青苹果", "value": 2}]},
    {"name": "香蕉", "value": 4}]},
    {"name": "饮料", "children": [{"name": "咖啡", "value": 6},
                                  {"name": "茶", "value": 3}]}]


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
    from InstructionX_UIKit.charts.canvas_blocks import CanvasBlocksChartViewport
    chart.show()
    viewport = chart._viewport
    assert isinstance(viewport, CanvasBlocksChartViewport)
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
        raise RuntimeError("层级块图 RHI 回读失败")
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
    return pixels[round(point.y() * dpr), round(point.x() * dpr), :3]


def assert_matches(viewport, chart, name, points=()):
    actual = grab(viewport)
    expected = reference(chart, viewport.devicePixelRatioF())
    destination = ROOT / "temp" / "canvas_blocks"
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


def rotated_label_bbox(image, renderer, node, commands):
    command = next(command for command in commands
                   if command[0] == "text" and command[1] == node.name)
    rect = command[2]
    r0, r1 = renderer._ring(node.level)
    center = renderer._pt((node.a0 + node.a1) / 2, (r0 + r1) / 2)
    radius = max(rect.width(), rect.height()) * 0.75 + 4
    dpr = image.devicePixelRatioF()
    cropped = image.copy(round((center.x() - radius) * dpr),
                         round((center.y() - radius) * dpr),
                         round(radius * 2 * dpr), round(radius * 2 * dpr))
    pixels = np.frombuffer(cropped.constBits(), dtype=np.uint8).reshape(
        cropped.height(), cropped.width(), 4)
    ys, xs = np.where(np.all(pixels[:, :, :3] > 200, axis=2))
    assert len(xs), node.name
    return [int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())]


def hover(viewport, pos):
    global_pos = viewport.mapToGlobal(QPoint(round(pos.x()), round(pos.y())))
    event = QMouseEvent(QEvent.MouseMove, QPointF(pos), QPointF(pos),
                        QPointF(global_pos), Qt.NoButton, Qt.NoButton, Qt.NoModifier)
    QCoreApplication.sendEvent(viewport, event)
    viewport._sync_now()


@check("漏斗逐层展开、排序、内外标签与命中")
def _():
    ThemeManager.instance().apply(app)
    chart = ChartWidget()
    data = [{"name": name, "value": value} for name, value in
            (("官网", 100), ("广告", 80), ("邮件", 60), ("搜索", 40))]
    chart.set_option({"animation": True, "title": {"text": "访问漏斗"},
                      "series": [{"type": "funnel", "name": "访问", "data": data,
                                  "sort": "descending", "gap": 3,
                                  "label": {"show": True, "position": "outer"}}]})
    chart.resize(900, 600)
    viewport = make_view(chart)
    try:
        chart.anim.stop()
        chart.anim.set_progress(0.5)
        viewport._sync_now()
        renderer = chart.series_renderers[0]
        model = viewport._line_views[0]
        assert len(model._areas) == 2
        assert model._anim_t == 0.5
        assert_matches(viewport, chart, "funnel_half")
        chart.anim.set_progress(1.0)
        viewport._sync_now()
        assert len(model._areas) == 4
        points = [layer["poly"].boundingRect().center() for layer in renderer._layers]
        for layer, point in zip(renderer._layers, points):
            hit = renderer.hit_test(point)
            assert hit is not None and hit["name"] == layer["name"]
        assert_matches(viewport, chart, "funnel", points)
        hover(viewport, points[0])
        assert chart.tooltip.active and viewport._tooltip_scene is not None
        chart.update_option({"series": [{"type": "funnel", "name": "访问", "data": data,
                                          "sort": "ascending", "gap": 3,
                                          "label": {"show": True, "position": "inside"}}]})
        chart.anim.stop()
        chart.anim.set_progress(1.0)
        viewport._sync_now()
        renderer = chart.series_renderers[0]
        model = viewport._line_views[0]
        assert model._source_layers is renderer._layers
        assert [layer["name"] for layer in renderer._layers] == ["搜索", "邮件", "广告", "官网"]
        labels = {command[1] for command in model._scene.commands if command[0] == "text"}
        assert "搜索 40" in labels
        assert_matches(viewport, chart, "funnel_inside")
        ThemeManager.instance().set_mode("dark")
        viewport._sync_now()
        assert_matches(viewport, chart, "funnel_dark")
    finally:
        viewport.close()
        chart.close()
        ThemeManager.instance().set_mode("light")
        pump(100)


@check("旭日层级环、旋转标签与深层命中")
def _():
    ThemeManager.instance().apply(app)
    chart = ChartWidget()
    chart.set_option({"animation": True, "title": {"text": "层级分布"},
                      "series": [{"type": "sunburst", "name": "分布", "data": HIERARCHY,
                                  "label": {"show": True, "minAngle": 8}}]})
    chart.resize(900, 600)
    viewport = make_view(chart)
    try:
        chart.anim.stop()
        chart.anim.set_progress(0.5)
        viewport._sync_now()
        renderer = chart.series_renderers[0]
        model = viewport._line_views[0]
        assert len(model._areas) == len(renderer._nodes) == 8
        assert any(command[0] == "rotate" for command in model._scene.commands)
        assert_matches(viewport, chart, "sunburst_half")
        chart.anim.set_progress(1.0)
        viewport._sync_now()
        points = []
        for node in renderer._nodes:
            if node.level == 0:
                continue
            r0, r1 = renderer._ring(node.level)
            point = renderer._pt((node.a0 + node.a1) / 2, r0 + (r1 - r0) * 0.25)
            hit = renderer.hit_test(point)
            assert hit is not None and hit["depth"] == node.level
            points.append(point)
        actual, expected = grab(viewport), reference(chart, viewport.devicePixelRatioF())
        for node in renderer._nodes:
            if not node.name:
                continue
            actual_label = rotated_label_bbox(actual, renderer, node, model._scene.commands)
            expected_label = rotated_label_bbox(expected, renderer, node, model._scene.commands)
            assert all(abs(a - b) <= 2 for a, b in zip(actual_label, expected_label)), (
                node.name, actual_label, expected_label)
        assert_matches(viewport, chart, "sunburst", points)
        hover(viewport, points[0])
        assert chart.tooltip.active and viewport._tooltip_scene is not None
        chart.update_option({"series": [{"type": "sunburst", "name": "分布", "data": HIERARCHY,
                                          "radius": ["10%", "85%"],
                                          "label": {"show": True, "minAngle": 5}}]})
        chart.anim.stop()
        chart.anim.set_progress(1.0)
        viewport._sync_now()
        model = viewport._line_views[0]
        assert model._source_nodes is chart.series_renderers[0]._nodes
        assert len(model._areas) == 8
        assert_matches(viewport, chart, "sunburst_update")
        ThemeManager.instance().set_mode("dark")
        viewport._sync_now()
        assert_matches(viewport, chart, "sunburst_dark")
    finally:
        viewport.close()
        chart.close()
        ThemeManager.instance().set_mode("light")
        pump(100)


@check("矩形树图透明度、层级命中、面包屑与间隙更新")
def _():
    ThemeManager.instance().apply(app)
    chart = ChartWidget()
    chart.set_option({"animation": True, "title": {"text": "矩形树图"},
                      "series": [{"type": "treemap", "name": "库存", "data": HIERARCHY,
                                  "breadcrumb": {"show": True}, "gapWidth": 1,
                                  "label": {"show": True}}]})
    chart.resize(900, 600)
    viewport = make_view(chart)
    try:
        chart.anim.stop()
        chart.anim.set_progress(0.5)
        viewport._sync_now()
        renderer = chart.series_renderers[0]
        model = viewport._line_views[0]
        assert len(model._areas) == len(renderer._nodes) == 8
        assert {color.alpha() for _path, color in model._areas} == {157}
        labels = {command[1] for command in model._scene.commands if command[0] == "text"}
        assert "水果 / 饮料" in labels
        assert_matches(viewport, chart, "treemap_half")
        chart.anim.set_progress(1.0)
        viewport._sync_now()
        points = []
        for node in renderer._nodes:
            if node.children:
                continue
            point = node.rect.center()
            hit = renderer.hit_test(point)
            assert hit is not None and hit["name"] == node.name and hit["depth"] == node.depth
            points.append(point)
        assert_matches(viewport, chart, "treemap", points)
        hover(viewport, points[0])
        assert chart.tooltip.active and viewport._tooltip_scene is not None
        updated = [{"name": "水果", "children": [
            {"name": "苹果", "children": [{"name": "红富士", "value": 5},
                                          {"name": "青苹果", "value": 1}]},
            {"name": "香蕉", "value": 4}]},
            {"name": "饮料", "children": [{"name": "咖啡", "value": 6},
                                          {"name": "茶", "value": 3}]}]
        chart.update_option({"series": [{"type": "treemap", "name": "库存", "data": updated,
                                          "breadcrumb": {"show": True}, "gapWidth": 4,
                                          "label": {"show": True}}]})
        chart.anim.stop()
        chart.anim.set_progress(1.0)
        viewport._sync_now()
        renderer = chart.series_renderers[0]
        model = viewport._line_views[0]
        assert model._source_nodes is renderer._nodes
        assert {color.alpha() for _path, color in model._areas} == {255}
        assert_matches(viewport, chart, "treemap_update")
        ThemeManager.instance().set_mode("dark")
        viewport._sync_now()
        assert_matches(viewport, chart, "treemap_dark")
    finally:
        viewport.close()
        chart.close()
        ThemeManager.instance().set_mode("light")
        pump(100)


if __name__ == "__main__":
    app.quit()
    raise SystemExit(1 if _FAILURES else 0)
