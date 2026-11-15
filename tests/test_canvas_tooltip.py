# -*- coding: utf-8 -*-
"""Canvas item/axis tooltip 与标记回归（真实 RHI + 独立脚本）。"""

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
from PySide6.QtCore import QCoreApplication, QEvent, QPoint, QPointF, Qt, QTimer
from PySide6.QtGui import QColor, QImage, QMouseEvent, QPainter
from PySide6.QtWidgets import QApplication
from InstructionX_UIKit.charts import ChartWidget
from InstructionX_UIKit.charts.canvas_item_viewport import CanvasItemLineChartViewport
from InstructionX_UIKit.theme import T, ThemeManager

_FAILURES = []
app = QApplication.instance() or QApplication(sys.argv)


def pump(milliseconds=300):
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


def grab(viewport):
    result = {}

    def captured(image):
        result["image"] = image.copy()
        app.exit(0)

    QTimer.singleShot(0, lambda: viewport.grab_canvas(captured))
    QTimer.singleShot(6000, lambda: app.exit(2))
    if app.exec() != 0 or result.get("image") is None:
        raise RuntimeError("tooltip 回读失败")
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


def hover(viewport, pos):
    global_pos = viewport.mapToGlobal(QPoint(round(pos.x()), round(pos.y())))
    event = QMouseEvent(QEvent.MouseMove, QPointF(pos), QPointF(pos),
                        QPointF(global_pos), Qt.NoButton, Qt.NoButton, Qt.NoModifier)
    QCoreApplication.sendEvent(viewport, event)


def leave(viewport):
    QCoreApplication.sendEvent(viewport, QEvent(QEvent.Leave))


def color_count(image, color, rect=None):
    pixels = np.frombuffer(image.constBits(), dtype=np.uint8).reshape(
        image.height(), image.width(), 4)
    if rect is not None:
        dpr = image.devicePixelRatioF()
        pixels = pixels[round(rect.top() * dpr):round(rect.bottom() * dpr),
                        round(rect.left() * dpr):round(rect.right() * dpr)]
    return int(np.count_nonzero(np.all(pixels == np.array(color, dtype=np.uint8), axis=2)))


@check("item 浮层、axis 标题与标记、空白隐藏")
def _():
    previous = ThemeManager.instance().mode
    ThemeManager.instance().apply(app)
    chart = ChartWidget()
    chart.set_option({
        "animation": False,
        "xAxis": {"type": "category", "data": ["一", "二", "三", "四", "五", "六", "日"]},
        "yAxis": {"type": "value", "min": -2, "max": 2},
        "tooltip": {"show": True, "trigger": "item"},
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
    chart.show()
    viewport = CanvasItemLineChartViewport(chart, parent=chart)
    old = chart._viewport
    chart._viewport = viewport
    old.close()
    old.deleteLater()
    viewport.show()
    destination = ROOT / "temp" / "canvas_tooltip"
    destination.mkdir(parents=True, exist_ok=True)
    try:
        pump()
        viewport._sync_now()
        cached = viewport._static_scene
        point = chart.series_renderers[0]._points[-1]
        hover(viewport, point)
        pump(50)
        viewport._sync_now()
        assert chart.tooltip.active
        scene = viewport._tooltip_scene
        assert scene is not None
        assert viewport._static_scene is cached
        assert scene.box.right() <= chart.tooltip._pos.x() - 13
        texts = {command[1] for command in scene.commands if command[0] == "text"}
        assert any(text.startswith("输入:") for text in texts)
        actual = grab(viewport)
        expected = reference(chart, viewport.devicePixelRatioF())
        actual.save(str(destination / "item.png"))
        expected.save(str(destination / "item_reference.png"))
        assert actual.size() == expected.size()
        assert color_count(actual, QColor(T("color.bg.elevated")).getRgb(), scene.box) > 0
        assert color_count(actual, QColor(T("color.text.primary")).getRgb(), scene.box) > 0
        hover(viewport, QPoint(1, 1))
        pump(50)
        viewport._sync_now()
        assert not chart.tooltip.active
        assert viewport._tooltip_scene is None
        chart.update_option({"tooltip": {"trigger": "axis", "show": True}})
        chart.anim.stop()
        chart.anim.set_progress(1.0)
        viewport._sync_now()
        center = chart.primary_coord().plot.center()
        hover(viewport, center)
        pump(50)
        viewport._sync_now()
        assert chart.tooltip.active and chart.tooltip.trigger == "axis"
        assert len(chart.tooltip._lines) >= 2
        scene = viewport._tooltip_scene
        assert scene is not None
        assert any(command[0] == "fill" for command in scene.commands)
        texts = {command[1] for command in scene.commands if command[0] == "text"}
        assert "四" in texts
        assert scene.box.left() >= 4 and scene.box.right() <= chart.width() - 4
        axis_image = grab(viewport)
        axis_image.save(str(destination / "axis.png"))
        assert color_count(axis_image, QColor(T("color.bg.elevated")).getRgb(), scene.box) > 0
        assert color_count(axis_image, QColor(T("color.text.primary")).getRgb(), scene.box) > 0
        hover(viewport, center)
        pump(50)
        viewport._sync_now()
        assert chart.tooltip.active
        light_scene = viewport._tooltip_scene
        ThemeManager.instance().set_mode("dark")
        viewport._sync_now()
        scene = viewport._tooltip_scene
        assert scene is not light_scene
        dark = grab(viewport)
        dark.save(str(destination / "dark.png"))
        assert color_count(dark, QColor(T("color.bg.elevated")).getRgb(), scene.box) > 0
        assert color_count(dark, QColor(T("color.text.primary")).getRgb(), scene.box) > 0
        leave(viewport)
        pump(50)
        viewport._sync_now()
        assert not chart.tooltip.active and viewport._tooltip_scene is None
    finally:
        viewport.close()
        chart.close()
        ThemeManager.instance().set_mode(previous)
        pump(100)


if __name__ == "__main__":
    app.quit()
    raise SystemExit(1 if _FAILURES else 0)
