# -*- coding: utf-8 -*-
"""Canvas parallel 与 themeRiver 的几何、交互和真实 RHI 回归。"""

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
    from InstructionX_UIKit.charts.canvas_series import CanvasFlowChartViewport
    chart.show()
    viewport = CanvasFlowChartViewport(chart, parent=chart)
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
        raise RuntimeError("平行坐标 / 主题河回读失败")
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


def bbox(image, rect):
    dpr = image.devicePixelRatioF()
    return series_ink_bbox(image.copy(round(rect.left() * dpr), round(rect.top() * dpr),
                                      max(1, round(rect.width() * dpr)),
                                      max(1, round(rect.height() * dpr))))


def center_rgb(image, point):
    dpr = image.devicePixelRatioF()
    pixels = np.frombuffer(image.constBits(), dtype=np.uint8).reshape(
        image.height(), image.width(), 4)
    return pixels[round(point.y() * dpr), round(point.x() * dpr), :3]


def assert_matches(viewport, chart, name):
    actual = grab(viewport)
    expected = reference(chart, viewport.devicePixelRatioF())
    destination = ROOT / "temp" / "canvas_parallel_river"
    destination.mkdir(parents=True, exist_ok=True)
    actual.save(str(destination / f"{name}.png"))
    expected.save(str(destination / f"{name}_reference.png"))
    area = chart.series_renderers[0]._area
    for rect in (area, area.adjusted(-30, -36, 30, 32)):
        actual_bbox, expected_bbox = bbox(actual, rect), bbox(expected, rect)
        assert actual_bbox is not None and expected_bbox is not None, name
        assert all(abs(a - b) <= 2 for a, b in zip(actual_bbox, expected_bbox)), (
            name, actual_bbox, expected_bbox)
    return actual, expected


def hover(viewport, pos):
    global_pos = viewport.mapToGlobal(QPoint(round(pos.x()), round(pos.y())))
    event = QMouseEvent(QEvent.MouseMove, QPointF(pos), QPointF(pos),
                        QPointF(global_pos), Qt.NoButton, Qt.NoButton, Qt.NoModifier)
    QCoreApplication.sendEvent(viewport, event)
    viewport._sync_now()


@check("平行坐标逐步揭示、轴标签、首行维度与命中")
def _():
    ThemeManager.instance().apply(app)
    chart = ChartWidget()
    chart.set_option({
        "animation": True, "title": {"text": "成绩"},
        "parallelAxis": [{"name": "语文", "min": 0, "max": 100},
                         {"name": "数学", "min": 0, "max": 100},
                         {"name": "英语", "min": 0, "max": 100}],
        "series": [{"type": "parallel", "name": "成绩",
                    "data": [[80, 90, 70], [60, 75, 88], [90, 85, 95]]}],
    })
    chart.resize(900, 550)
    viewport = make_view(chart)
    try:
        chart.anim.stop()
        chart.anim.set_progress(0.5)
        viewport._sync_now()
        renderer = chart.series_renderers[0]
        model = viewport._line_views[0]
        assert len(model._outlines) == len(renderer._rows) + len(renderer._axes)
        rows = model._outlines[:len(renderer._rows)]
        assert all(path.commandsSize() == 2 for path, _color, _width in rows)
        assert all(color.alpha() == 110 and width == 1.6
                   for _path, color, width in rows)
        assert all(width == 1.0 for _path, _color, width in model._outlines[len(rows):])
        labels = {command[1] for command in model._label_commands if command[0] == "text"}
        assert {"语文", "数学", "英语", "0", "100"} <= labels
        assert_matches(viewport, chart, "parallel_half")
        chart.anim.set_progress(1.0)
        viewport._sync_now()
        assert all(path.commandsSize() == 3 for path, _color, _width in rows)
        assert_matches(viewport, chart, "parallel")
        hover(viewport, renderer._rows[0]["pts"][0])
        assert chart.tooltip.active and viewport._tooltip_scene is not None
        assert_matches(viewport, chart, "parallel_tooltip")
        chart.update_option({"series": [{"type": "parallel", "name": "成绩",
                                          "data": [["速度", "力量", "耐力"],
                                                   [7, 8, 6], [5, 9, 8]]}]})
        chart.anim.stop()
        chart.anim.set_progress(1.0)
        viewport._sync_now()
        renderer = chart.series_renderers[0]
        model = viewport._line_views[0]
        assert model._source_rows is renderer._rows
        assert [axis["name"] for axis in renderer._axes] == ["速度", "力量", "耐力"]
        assert len(model._outlines) == len(renderer._rows) + len(renderer._axes)
        assert_matches(viewport, chart, "parallel_header")
        ThemeManager.instance().set_mode("dark")
        viewport._sync_now()
        assert_matches(viewport, chart, "parallel_dark")
    finally:
        viewport.close()
        chart.close()
        ThemeManager.instance().set_mode("light")
        pump(100)


@check("主题河平滑闭合、生长动画、时间标签与调色板更新")
def _():
    ThemeManager.instance().apply(app)
    times = ["2026-01", "2026-02", "2026-03", "2026-04", "2026-05", "2026-06"]
    data = []
    for index, label in enumerate(times):
        data += [[label, 10 + index * 2, "甲"],
                 [label, 20 - index, "乙"], [label, 5 + index, "丙"]]
    chart = ChartWidget()
    chart.set_option({"animation": True, "title": {"text": "主题河"},
                      "series": [{"type": "themeRiver", "name": "河", "data": data}]})
    chart.resize(900, 550)
    viewport = make_view(chart)
    try:
        chart.anim.stop()
        chart.anim.set_progress(0.5)
        viewport._sync_now()
        renderer = chart.series_renderers[0]
        model = viewport._line_views[0]
        assert len(model._areas) == 3 and len(model._outlines) == 3
        assert all(path.commandsSize() == 13 for path, _color in model._areas)
        assert {color.alpha() for _path, color in model._areas} == {150}
        assert {color.alpha() for _path, _color, _width in model._outlines} == {200}
        labels = {command[1] for command in model._label_commands if command[0] == "text"}
        assert labels <= set(times) and len(labels) == 5
        assert_matches(viewport, chart, "river_half")
        chart.anim.set_progress(1.0)
        viewport._sync_now()
        for index in range(len(times)):
            y0 = renderer._streams[0]["top"][index].y()
            y1 = renderer._streams[-1]["bot"][index].y()
            assert abs((y0 + y1) / 2 - renderer._area.center().y()) < 1.0
        actual, expected = assert_matches(viewport, chart, "river")
        for stream in renderer._streams:
            point = stream["top"][3]
            point.setY((point.y() + stream["bot"][3].y()) / 2)
            delta = np.abs(center_rgb(actual, point).astype(int)
                           - center_rgb(expected, point).astype(int))
            assert int(delta.max()) <= 2, (stream["name"], delta)
            hit = renderer.hit_test(point)
            assert hit is not None and hit["name"] == stream["name"]
        hover(viewport, point)
        assert chart.tooltip.active and viewport._tooltip_scene is not None
        chart.update_option({"color": ["#845ec2", "#d65db1", "#ff6f91"],
                             "series": [{"type": "themeRiver", "name": "河", "data": data}]})
        chart.anim.stop()
        chart.anim.set_progress(1.0)
        viewport._sync_now()
        model = viewport._line_views[0]
        assert model._source_streams is chart.series_renderers[0]._streams
        assert model._areas[0][1].red() == 132 and model._areas[0][1].alpha() == 150
        assert_matches(viewport, chart, "river_palette")
        ThemeManager.instance().set_mode("dark")
        viewport._sync_now()
        assert_matches(viewport, chart, "river_dark")
    finally:
        viewport.close()
        chart.close()
        ThemeManager.instance().set_mode("light")
        pump(100)


if __name__ == "__main__":
    app.quit()
    raise SystemExit(1 if _FAILURES else 0)
