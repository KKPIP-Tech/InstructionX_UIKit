# -*- coding: utf-8 -*-
"""Canvas 静态轴、标题、图例与显隐回归（真实 RHI + 独立脚本）。"""

import os
from pathlib import Path
import sys
import time
import traceback

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.pop("QT_QPA_PLATFORM", None)
os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")

import numpy as np
from PySide6.QtCore import QPoint, Qt, QTimer
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from InstructionX_UIKit.charts import ChartWidget
from InstructionX_UIKit.charts.canvas_item_viewport import CanvasItemLineChartViewport
from InstructionX_UIKit.charts.canvas_static import build_static_scene, static_scene_key
from InstructionX_UIKit.theme import T, ThemeManager

_FAILURES = []
app = QApplication.instance() or QApplication(sys.argv)


def pump(milliseconds=350):
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


def make_chart():
    chart = ChartWidget()
    chart.set_option({
        "animation": False,
        "title": {"text": "运行状态", "subtext": "实时曲线", "left": "center"},
        "xAxis": {"type": "value", "name": "时间"},
        "yAxis": {"type": "value", "name": "幅值", "min": -2, "max": 2},
        "legend": {"show": True},
        "series": [
            {"type": "line", "name": "输入", "data": [0, 1, 0, -1, 0.5, 1, 0],
             "showSymbol": False},
            {"type": "line", "name": "输出", "data": [1, 0, -1, 0, -0.5, 0.5, 1],
             "showSymbol": False},
        ],
    })
    chart.anim.stop()
    chart.anim.set_progress(1.0)
    chart.resize(900, 600)
    return chart


def replace_viewport(chart):
    chart.show()
    viewport = CanvasItemLineChartViewport(chart, parent=chart)
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
        raise RuntimeError("静态 Canvas 回读失败")
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


def ink_bbox(image, rect=None):
    pixels = np.frombuffer(image.constBits(), dtype=np.uint8).reshape(
        image.height(), image.width(), 4)
    dpr = image.devicePixelRatioF()
    if rect is not None:
        pixels = pixels[round(rect.top() * dpr):round(rect.bottom() * dpr),
                        round(rect.left() * dpr):round(rect.right() * dpr)]
    background = np.array(QColor(T("color.bg.base")).getRgb()[:3], dtype=np.uint8)
    ys, xs = np.where(np.any(pixels[:, :, :3] != background, axis=2))
    if not len(xs):
        return None
    return [int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())]


def color_count(image, color):
    pixels = np.frombuffer(image.constBits(), dtype=np.uint8).reshape(
        image.height(), image.width(), 4)
    return int(np.count_nonzero(np.all(pixels == np.array(color, dtype=np.uint8), axis=2)))


@check("静态文本、缓存、图例显隐和暗色主题")
def _():
    ThemeManager.instance().apply(app)
    previous = ThemeManager.instance().mode
    chart = make_chart()
    scene = build_static_scene(chart)
    texts = {command[1] for command in scene.commands if command[0] == "text"}
    assert {"运行状态", "实时曲线", "时间", "幅值", "输入", "输出"} <= texts
    assert scene.key == static_scene_key(chart)
    chart._layout_all(force=True)
    viewport = replace_viewport(chart)
    destination = ROOT / "temp" / "canvas_static"
    destination.mkdir(parents=True, exist_ok=True)
    try:
        pump()
        actual = grab(viewport)
        expected = reference(chart, viewport.devicePixelRatioF())
        actual.save(str(destination / "actual.png"))
        expected.save(str(destination / "reference.png"))
        assert actual.size() == expected.size()
        title_rect = chart.title.height()
        from PySide6.QtCore import QRectF
        title_rect = QRectF(0, 0, chart.width(), title_rect)
        actual_title = ink_bbox(actual, title_rect)
        expected_title = ink_bbox(expected, title_rect)
        assert actual_title is not None and expected_title is not None
        assert all(abs(a - b) <= 3 for a, b in zip(actual_title, expected_title)), (
            actual_title, expected_title)
        assert ink_bbox(actual) is not None and ink_bbox(expected) is not None
        assert chart.set_stream_data([0.2, 0.8, 0.3, -0.6, 0.4, 0.9, 0.1], series=0)
        viewport._sync_now()
        cached = viewport._static_scene
        assert chart.set_stream_data([0.1, 0.7, 0.4, -0.5, 0.6, 0.8, 0.2], series=0)
        viewport._sync_now()
        assert viewport._static_scene is cached, (cached.key, viewport._static_scene.key)
        second_color = list(chart.series_renderers[1].color().getRgb())
        assert color_count(actual, second_color) > 0
        center = chart.legend._item_rects[1].center()
        QTest.mouseClick(viewport, Qt.LeftButton, Qt.NoModifier,
                         QPoint(round(center.x()), round(center.y())))
        viewport._sync_now()
        assert not chart.series_renderers[1].visible
        disabled = grab(viewport)
        disabled.save(str(destination / "disabled.png"))
        assert color_count(disabled, second_color) == 0
        assert viewport._static_scene is not cached
        QTest.mouseClick(viewport, Qt.LeftButton, Qt.NoModifier,
                         QPoint(round(center.x()), round(center.y())))
        viewport._sync_now()
        assert chart.series_renderers[1].visible
        assert color_count(grab(viewport), second_color) > 0
        ThemeManager.instance().set_mode("dark")
        viewport._sync_now()
        assert viewport._static_scene is not cached
        dark = grab(viewport)
        dark.save(str(destination / "dark.png"))
        assert color_count(dark, second_color) > 0
        expected_dark = reference(chart, viewport.devicePixelRatioF())
        assert actual.size() == expected_dark.size()
        assert ink_bbox(dark, title_rect) is not None
        assert ink_bbox(expected_dark, title_rect) is not None
    finally:
        viewport.close()
        chart.close()
        ThemeManager.instance().set_mode(previous)
        pump(100)


if __name__ == "__main__":
    app.quit()
    raise SystemExit(1 if _FAILURES else 0)
