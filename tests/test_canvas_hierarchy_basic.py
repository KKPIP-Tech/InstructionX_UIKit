# -*- coding: utf-8 -*-
"""Canvas 饼图、雷达图与仪表盘的真实 RHI 回归。"""

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
from PySide6.QtCore import QCoreApplication, QEvent, QPoint, QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QImage, QMouseEvent, QPainter
from PySide6.QtWidgets import QApplication
from InstructionX_UIKit.charts import ChartWidget
from InstructionX_UIKit.theme import ThemeManager
from run_canvas_line_features import series_ink_bbox

_FAILURES = []
app = QApplication.instance() or QApplication(sys.argv)
PIE_DATA = [{"name": "直接访问", "value": 335}, {"name": "邮件营销", "value": 310},
            {"name": "联盟广告", "value": 234}, {"name": "视频广告", "value": 135},
            {"name": "搜索引擎", "value": 548}]


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
    from InstructionX_UIKit.charts.canvas_hierarchy import CanvasHierarchyChartViewport
    chart.show()
    viewport = CanvasHierarchyChartViewport(chart, parent=chart)
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
        raise RuntimeError("层级系列 RHI 回读失败")
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
    destination = ROOT / "temp" / "canvas_hierarchy_basic"
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
    return actual, expected


def hover(viewport, pos):
    global_pos = viewport.mapToGlobal(QPoint(round(pos.x()), round(pos.y())))
    event = QMouseEvent(QEvent.MouseMove, QPointF(pos), QPointF(pos),
                        QPointF(global_pos), Qt.NoButton, Qt.NoButton, Qt.NoModifier)
    QCoreApplication.sendEvent(viewport, event)
    viewport._sync_now()


@check("饼图扇区、环形玫瑰、中心总计与更新动画")
def _():
    ThemeManager.instance().apply(app)
    chart = ChartWidget()
    chart.set_option({"animation": True, "title": {"text": "访问来源"},
                      "series": [{"type": "pie", "name": "来源", "data": PIE_DATA,
                                  "label": {"show": True, "position": "outside"}}]})
    chart.resize(900, 600)
    viewport = make_view(chart)
    try:
        chart.anim.stop()
        chart.anim.set_progress(0.5)
        viewport._sync_now()
        renderer = chart.series_renderers[0]
        model = viewport._line_views[0]
        assert len(model._areas) == 5 and len(model._outlines) == 5
        assert model._anim_t == 0.5
        assert all(path.commandsSize() > 3 for path, _color in model._areas)
        chart.anim.set_progress(1.0)
        viewport._sync_now()
        points = []
        for sector in renderer._sectors:
            angle = (sector["a0"] + sector["a1"]) / 2
            radius = sector["r0"] + (sector["r1"] - sector["r0"]) * 0.25
            points.append(renderer._pt(angle, radius))
            hit = renderer.hit_test(points[-1])
            assert hit is not None and hit["name"] == sector["name"]
        assert_matches(viewport, chart, "pie", points)
        hover(viewport, points[0])
        assert chart.tooltip.active and viewport._tooltip_scene is not None
        updated = [{"name": item["name"], "value": item["value"] + 30}
                   for item in PIE_DATA]
        chart.update_option({"series": [{"type": "pie", "name": "来源", "data": updated,
                                          "radius": ["40%", "70%"], "roseType": "radius",
                                          "label": {"show": True, "position": "inside"},
                                          "totalLabel": {"show": True, "text": "总计"}}]})
        chart.anim.stop()
        chart.anim.set_progress(0.5)
        viewport._sync_now()
        renderer = chart.series_renderers[0]
        model = viewport._line_views[0]
        assert renderer.prev_data and renderer._r_in > 1
        assert len(model._areas) == 5
        expected = renderer._animated_sectors(0.5)
        assert model._animated[0]["a0"] == expected[0]["a0"]
        assert model._animated[0]["a1"] == expected[0]["a1"]
        assert model._animated[0]["r1"] == expected[0]["r1"]
        assert_matches(viewport, chart, "pie_donut_half")
        chart.anim.set_progress(1.0)
        viewport._sync_now()
        labels = {command[1] for command in model._scene.commands if command[0] == "text"}
        assert "总计" in labels
        assert any(label.endswith("%") for label in labels)
        points = []
        for sector in renderer._sectors:
            angle = (sector["a0"] + sector["a1"]) / 2
            points.append(renderer._pt(angle, sector["r0"] + 2))
            assert renderer.hit_test(points[-1]) is not None
        assert renderer.hit_test(renderer._center) is None
        assert_matches(viewport, chart, "pie_donut", points)
        ThemeManager.instance().set_mode("dark")
        viewport._sync_now()
        assert_matches(viewport, chart, "pie_dark")
    finally:
        viewport.close()
        chart.close()
        ThemeManager.instance().set_mode("light")
        pump(100)


@check("雷达蛛网、面积、多边形命中与圆形模式")
def _():
    ThemeManager.instance().apply(app)
    chart = ChartWidget()
    chart.set_option({
        "animation": True, "title": {"text": "能力雷达"},
        "series": [{"type": "radar", "name": "能力", "splitNumber": 5,
                    "indicator": [{"name": name, "max": 100} for name in
                                  ("速度", "力量", "防御", "敏捷", "智慧", "运气")],
                    "areaStyle": {"opacity": 0.25},
                    "data": [{"name": "甲", "value": [80, 70, 90, 65, 75, 85]},
                             {"name": "乙", "value": [60, 85, 55, 70, 88, 60]}]}],
    })
    chart.resize(900, 600)
    viewport = make_view(chart)
    try:
        chart.anim.stop()
        chart.anim.set_progress(0.5)
        viewport._sync_now()
        renderer = chart.series_renderers[0]
        model = viewport._line_views[0]
        assert len(model._rings) == 5 and len(model._areas) == 2
        assert len(model._poly_paths) == 2
        assert {color.alpha() for _path, color in model._areas} == {63}
        labels = {command[1] for command in model._scene.commands if command[0] == "text"}
        assert {"速度", "力量", "防御", "敏捷", "智慧", "运气"} <= labels
        chart.anim.set_progress(1.0)
        viewport._sync_now()
        assert renderer.hit_test(renderer._center) is not None
        assert_matches(viewport, chart, "radar", [renderer._center])
        chart.update_option({"series": [{"type": "radar", "name": "能力", "shape": "circle",
                                          "splitNumber": 3,
                                          "indicator": [{"name": "甲"}, {"name": "乙"},
                                                        {"name": "丙"}],
                                          "areaStyle": {"opacity": 0.25},
                                          "data": [[3, 5, 4], [4, 2, 5]]}]})
        chart.anim.stop()
        chart.anim.set_progress(1.0)
        viewport._sync_now()
        model = viewport._line_views[0]
        assert len(model._rings) == 3 and len(model._poly_paths) == 2
        assert_matches(viewport, chart, "radar_circle")
        ThemeManager.instance().set_mode("dark")
        viewport._sync_now()
        assert_matches(viewport, chart, "radar_dark")
    finally:
        viewport.close()
        chart.close()
        ThemeManager.instance().set_mode("light")
        pump(100)


@check("仪表盘分段弧、指针插值、进度与数值更新")
def _():
    ThemeManager.instance().apply(app)
    chart = ChartWidget()
    chart.set_option({
        "animation": True,
        "series": [{"type": "gauge", "name": "完成率", "min": 0, "max": 100,
                    "progress": {"show": True, "width": 10},
                    "axisLine": {"lineStyle": {"width": 14, "color": [
                        [0.3, "#67C23A"], [0.7, "#E6A23C"], [1, "#F56C6C"]]}},
                    "pointer": {"show": True, "length": "65%", "width": 5},
                    "anchor": {"show": True, "size": 12},
                    "detail": {"show": True, "fontSize": 20},
                    "title": {"show": True}, "data": [{"name": "完成率", "value": 66}]}],
    })
    chart.resize(900, 600)
    viewport = make_view(chart)
    try:
        chart.anim.stop()
        chart.anim.set_progress(0.5)
        viewport._sync_now()
        renderer = chart.series_renderers[0]
        model = viewport._line_views[0]
        assert model._cur_value == 33
        assert model._pointer_angle == renderer._value_angle(33)
        assert len(model._arcs) == 4
        assert model._arcs[0][0] == -225 and model._arcs[2][1] == 45
        assert model._arcs[-1][1] == model._pointer_angle
        labels = {command[1] for command in model._scene.commands if command[0] == "text"}
        assert {"33", "完成率"} <= labels
        points = []
        for start, end, radius, _width, _color in model._arcs:
            points.append(renderer._pt((start + end) / 2, radius))
        assert_matches(viewport, chart, "gauge_half", points)
        chart.anim.set_progress(1.0)
        viewport._sync_now()
        points = [renderer._pt((start + end) / 2, radius)
                  for start, end, radius, _width, _color in model._arcs]
        assert_matches(viewport, chart, "gauge", points)
        assert renderer.hit_test(renderer._center) is not None
        hover(viewport, renderer._center)
        assert chart.tooltip.active and viewport._tooltip_scene is not None
        chart.update_option({"series": [{"data": [{"name": "完成率", "value": 30}]}]})
        chart.anim.stop()
        chart.anim.set_progress(0.5)
        viewport._sync_now()
        renderer = chart.series_renderers[0]
        model = viewport._line_views[0]
        assert renderer.prev_data[0]["value"] == 66
        assert model._cur_value == 48
        assert model._pointer_angle == renderer._value_angle(48)
        assert_matches(viewport, chart, "gauge_update_half")
        chart.anim.set_progress(1.0)
        viewport._sync_now()
        assert model._cur_value == 30
        assert_matches(viewport, chart, "gauge_update")
        ThemeManager.instance().set_mode("dark")
        viewport._sync_now()
        assert_matches(viewport, chart, "gauge_dark")
    finally:
        viewport.close()
        chart.close()
        ThemeManager.instance().set_mode("light")
        pump(100)


if __name__ == "__main__":
    app.quit()
    raise SystemExit(1 if _FAILURES else 0)
