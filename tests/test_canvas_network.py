# -*- coding: utf-8 -*-
"""Canvas graph 与 lines 的几何、动画和生命周期回归。"""

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
    from InstructionX_UIKit.charts.canvas_network import CanvasNetworkChartViewport
    chart.show()
    viewport = CanvasNetworkChartViewport(chart, parent=chart)
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
        raise RuntimeError("网络系列 RHI 回读失败")
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
    destination = ROOT / "temp" / "canvas_network"
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


@check("关系图力导向展开、节点命中与环形布局")
def _():
    ThemeManager.instance().apply(app)
    chart = ChartWidget()
    nodes = [{"name": f"n{index}", "symbolSize": 14 + (index % 3) * 6}
             for index in range(8)]
    links = [{"source": index, "target": (index + 1) % 6} for index in range(6)]
    links += [{"source": 0, "target": 6}, {"source": 6, "target": 7},
              {"source": 7, "target": 2}]
    chart.set_option({"animation": True, "title": {"text": "关系图"},
                      "series": [{"type": "graph", "name": "关系", "layout": "force",
                                  "force": {"seed": 42, "iterations": 80},
                                  "data": nodes, "links": links}]})
    chart.resize(900, 600)
    viewport = make_view(chart)
    try:
        chart.anim.stop()
        chart.anim.set_progress(0.5)
        viewport._sync_now()
        renderer = chart.series_renderers[0]
        model = viewport._line_views[0]
        assert len(model._dots) == len(renderer._nodes) == 8
        assert len(model._edge_paths) == len(renderer._edges) == 9
        center = QPointF(sum(node["pos"].x() for node in renderer._nodes) / 8,
                         sum(node["pos"].y() for node in renderer._nodes) / 8)
        point = renderer._nodes[0]["pos"]
        expected = QPointF(center.x() + (point.x() - center.x()) * 0.5,
                           center.y() + (point.y() - center.y()) * 0.5)
        assert model._animated_positions[0] == expected
        assert_matches(viewport, chart, "graph_force_half")
        chart.anim.set_progress(1.0)
        viewport._sync_now()
        points = [node["pos"] for node in renderer._nodes]
        for node, point in zip(renderer._nodes, points):
            hit = renderer.hit_test(point)
            assert hit is not None and hit["name"] == node["name"]
        assert_matches(viewport, chart, "graph_force", points)
        hover(viewport, points[0])
        assert chart.tooltip.active and viewport._tooltip_scene is not None
        chart.update_option({"series": [{"type": "graph", "name": "关系", "layout": "circular",
                                          "data": [{"name": "甲"}, {"name": "乙"}, {"name": "丙"}],
                                          "links": [{"source": "甲", "target": "乙"},
                                                    {"source": "乙", "target": "丙"}]}]})
        chart.anim.stop()
        chart.anim.set_progress(1.0)
        viewport._sync_now()
        model = viewport._line_views[0]
        assert model._source_nodes is chart.series_renderers[0]._nodes
        assert len(model._dots) == 3 and len(model._edge_paths) == 2
        assert_matches(viewport, chart, "graph_circular")
        ThemeManager.instance().set_mode("dark")
        viewport._sync_now()
        assert_matches(viewport, chart, "graph_dark")
        chart.set_option({"animation": False,
                          "series": [{"type": "graph", "name": "空关系", "data": []},
                                     {"type": "lines", "name": "空航线", "data": []}]})
        chart.anim.stop()
        chart.anim.set_progress(1.0)
        viewport._sync_now()
        assert len(viewport._line_views) == 2
        assert all(not model._scene.commands for model in viewport._line_views)
        assert_matches(viewport, chart, "network_empty")
    finally:
        viewport.close()
        chart.close()
        ThemeManager.instance().set_mode("light")
        pump(100)


@check("线图曲率、拖尾相位同步、显隐与定时器生命周期")
def _():
    ThemeManager.instance().apply(app)
    chart = ChartWidget()
    data = [{"name": "L1", "coords": [[10, 10], [90, 80]], "value": 1},
            {"name": "L2", "coords": [[15, 85], [85, 15]], "value": 2},
            {"name": "L3", "coords": [[95, 5], [95, 60]], "value": 3}]
    chart.set_option({
        "animation": True, "title": {"text": "航线"},
        "xAxis": {"type": "value", "min": 0, "max": 100},
        "yAxis": {"type": "value", "min": 0, "max": 100},
        "series": [{"type": "lines", "name": "航线",
                    "lineStyle": {"width": 2, "curveness": 0.2},
                    "trailEffect": {"show": True, "period": 2, "symbolSize": 6},
                    "data": data}],
    })
    chart.resize(900, 600)
    viewport = make_view(chart)
    try:
        renderer = chart.series_renderers[0]
        assert renderer._timer is not None
        renderer._timer.stop()
        chart.anim.stop()
        chart.anim.set_progress(0.75)
        renderer._phase = 0.25
        viewport._sync_now()
        model = viewport._line_views[0]
        assert len(model._segment_paths) == len(renderer._segments) == 3
        assert len(model._trails) == 3
        assert model._phase == 0.25
        coord = chart.primary_coord()
        assert (coord.x_axis.vmin, coord.x_axis.vmax) == (0, 100)
        points = [point for segment in renderer._segments
                  for point in (segment["p0"], segment["p1"])]
        xs, ys = [point.x() for point in points], [point.y() for point in points]
        assert all(coord.plot.contains(point) for point in points), points
        assert max(xs) - min(xs) > coord.plot.width() * 0.5, (min(xs), max(xs))
        assert max(ys) - min(ys) > coord.plot.height() * 0.5, (min(ys), max(ys))
        trails = [renderer._curve_path(segment["p0"], segment["p1"], 0.2).pointAtPercent(
            (0.25 + index / 3) % 1.0)
            for index, segment in enumerate(renderer._segments)]
        assert all(path.commandsSize() == 2 for path in model._segment_paths)
        assert {color.alpha() for _path, color, _width in model._outlines} == {165}
        assert_matches(viewport, chart, "lines_effect", points + trails)
        renderer._phase = 0.5
        viewport._sync_now()
        assert viewport._line_views[0]._phase == 0.5
        assert_matches(viewport, chart, "lines_effect_next")
        chart.anim.set_progress(1.0)
        viewport._sync_now()
        for segment in renderer._segments:
            hit = renderer.hit_test(segment["p0"])
            assert hit is not None and hit["name"] == segment["name"]
        assert_matches(viewport, chart, "lines")
        hover(viewport, renderer._segments[0]["p0"])
        assert chart.tooltip.active and viewport._tooltip_scene is not None
        previous = renderer
        previous_timer = renderer._timer
        chart.update_option({"series": [{"type": "lines", "name": "航线",
                                          "lineStyle": {"width": 3, "curveness": 0.0},
                                          "effect": {"show": True, "period": 1,
                                                     "symbolSize": 8},
                                          "data": data}]})
        previous._on_tick()
        assert previous._timer is None and not previous_timer.isActive()
        renderer = chart.series_renderers[0]
        assert renderer._timer is not None
        renderer._timer.stop()
        chart.anim.stop()
        chart.anim.set_progress(1.0)
        renderer._phase = 0.3
        viewport._sync_now()
        model = viewport._line_views[0]
        assert model._source_segments is renderer._segments
        assert model._phase == 0.3
        assert_matches(viewport, chart, "lines_effect_alias")
        chart.set_series_visible("航线", False)
        renderer._on_tick()
        viewport._sync_now()
        assert not model._visible and not renderer._timer.isActive()
        chart.set_series_visible("航线", True)
        viewport._sync_now()
        assert model._visible and renderer._timer.isActive()
        renderer._timer.stop()
        assert_matches(viewport, chart, "lines_restored")
        ThemeManager.instance().set_mode("dark")
        viewport._sync_now()
        assert_matches(viewport, chart, "lines_dark")
    finally:
        if chart.series_renderers and chart.series_renderers[0]._timer is not None:
            chart.series_renderers[0]._timer.stop()
        viewport.close()
        chart.close()
        ThemeManager.instance().set_mode("light")
        pump(100)


if __name__ == "__main__":
    app.quit()
    raise SystemExit(1 if _FAILURES else 0)
