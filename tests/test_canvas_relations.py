# -*- coding: utf-8 -*-
"""Canvas 树图与桑基图的真实 RHI 回归。"""

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
TREE_DATA = [{"name": "root", "children": [
    {"name": "分支A", "children": [{"name": "叶A1"}, {"name": "叶A2"}]},
    {"name": "分支B", "children": [{"name": "叶B1"}]}]}]


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
    from InstructionX_UIKit.charts.canvas_relations import CanvasRelationsChartViewport
    chart.show()
    viewport = CanvasRelationsChartViewport(chart, parent=chart)
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
        raise RuntimeError("关系系列 RHI 回读失败")
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
    destination = ROOT / "temp" / "canvas_relations"
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


@check("树图 LR 折线、TB 曲线、节点标签与命中")
def _():
    ThemeManager.instance().apply(app)
    chart = ChartWidget()
    chart.set_option({"animation": True, "title": {"text": "树图"},
                      "series": [{"type": "tree", "name": "组织", "orient": "LR",
                                  "edge": "polyline", "data": TREE_DATA}]})
    chart.resize(900, 600)
    viewport = make_view(chart)
    try:
        chart.anim.stop()
        chart.anim.set_progress(0.5)
        viewport._sync_now()
        renderer = chart.series_renderers[0]
        model = viewport._line_views[0]
        assert len(model._edge_paths) == len(renderer._edges) == 5
        assert len(model._dots) == len(renderer._nodes) == 6
        assert all(path.commandsSize() == 3 for path in model._edge_paths)
        assert_matches(viewport, chart, "tree_lr_half")
        chart.anim.set_progress(1.0)
        viewport._sync_now()
        points = [point for _node, point in renderer._nodes]
        for (node, point) in renderer._nodes:
            hit = renderer.hit_test(point)
            assert hit is not None and hit["name"] == node.name
        assert_matches(viewport, chart, "tree_lr", points)
        hover(viewport, points[0])
        assert chart.tooltip.active and viewport._tooltip_scene is not None
        chart.update_option({"series": [{"type": "tree", "name": "组织", "orient": "TB",
                                          "edge": "curve", "symbolSize": 10,
                                          "data": TREE_DATA}]})
        chart.anim.stop()
        chart.anim.set_progress(0.5)
        viewport._sync_now()
        model = viewport._line_views[0]
        assert len(model._edge_paths) == 5
        assert all(path.commandsSize() == 2 for path in model._edge_paths)
        assert_matches(viewport, chart, "tree_tb_half")
        chart.anim.set_progress(1.0)
        viewport._sync_now()
        assert_matches(viewport, chart, "tree_tb")
        ThemeManager.instance().set_mode("dark")
        viewport._sync_now()
        assert_matches(viewport, chart, "tree_dark")
    finally:
        viewport.close()
        chart.close()
        ThemeManager.instance().set_mode("light")
        pump(100)


@check("桑基流带透明度、贝塞尔命中、节点与布局更新")
def _():
    ThemeManager.instance().apply(app)
    nodes = [{"name": name} for name in ("源甲", "源乙", "处理甲", "处理乙", "结果甲", "结果乙")]
    links = [
        {"source": "源甲", "target": "处理甲", "value": 6},
        {"source": "源甲", "target": "处理乙", "value": 4},
        {"source": "源乙", "target": "处理甲", "value": 3},
        {"source": "源乙", "target": "处理乙", "value": 7},
        {"source": "处理甲", "target": "结果甲", "value": 5},
        {"source": "处理甲", "target": "结果乙", "value": 4},
        {"source": "处理乙", "target": "结果甲", "value": 6},
        {"source": "处理乙", "target": "结果乙", "value": 5},
    ]
    chart = ChartWidget()
    chart.set_option({"animation": True, "title": {"text": "桑基图"},
                      "series": [{"type": "sankey", "name": "流量", "data": nodes,
                                  "links": links, "nodeWidth": 14, "nodeGap": 12,
                                  "layoutIterations": 6}]})
    chart.resize(900, 600)
    viewport = make_view(chart)
    try:
        chart.anim.stop()
        chart.anim.set_progress(0.5)
        viewport._sync_now()
        renderer = chart.series_renderers[0]
        model = viewport._line_views[0]
        assert len(model._bands) == len(renderer._bands) == 8
        assert len(model._nodes) == len(renderer._nodes) == 6
        assert {color.alpha() for _path, color in model._bands} == {35}
        assert {color.alpha() for _path, color in model._nodes} == {127}
        assert all(path.commandsSize() == 5 for path, _color in model._bands)
        assert_matches(viewport, chart, "sankey_half")
        chart.anim.set_progress(1.0)
        viewport._sync_now()
        points = [node["rect"].center() for node in renderer._nodes]
        for node, point in zip(renderer._nodes, points):
            hit = renderer.hit_test(point)
            assert hit is not None and hit["name"] == node["name"]
        for band in renderer._bands:
            source = band["path"]
            start, target, bottom = (source.elementAt(index) for index in (0, 3, 4))
            point = QPointF((start.x + target.x) / 2,
                            (start.y + 2 * target.y + bottom.y) / 4)
            assert band["path"].contains(point)
            assert not any(node["rect"].contains(point) for node in renderer._nodes)
            expected = next(candidate for candidate in renderer._bands
                            if candidate["path"].contains(point))
            hit = renderer.hit_test(point)
            assert hit is not None and hit.get("source") == expected["source"] \
                and hit.get("target") == expected["target"], (band, hit)
        assert_matches(viewport, chart, "sankey", points)
        hover(viewport, points[0])
        assert chart.tooltip.active and viewport._tooltip_scene is not None
        chart.update_option({"series": [{"type": "sankey", "name": "流量", "data": nodes,
                                          "links": links, "nodeWidth": 18, "nodeGap": 18,
                                          "layoutIterations": 8}]})
        chart.anim.stop()
        chart.anim.set_progress(1.0)
        viewport._sync_now()
        renderer = chart.series_renderers[0]
        model = viewport._line_views[0]
        assert model._source_nodes is renderer._nodes
        assert model._source_bands is renderer._bands
        assert {color.alpha() for _path, color in model._bands} == {70}
        assert_matches(viewport, chart, "sankey_update")
        ThemeManager.instance().set_mode("dark")
        viewport._sync_now()
        assert_matches(viewport, chart, "sankey_dark")
    finally:
        viewport.close()
        chart.close()
        ThemeManager.instance().set_mode("light")
        pump(100)


if __name__ == "__main__":
    app.quit()
    raise SystemExit(1 if _FAILURES else 0)
