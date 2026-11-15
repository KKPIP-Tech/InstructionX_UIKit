# -*- coding: utf-8 -*-
"""QCanvasPainterWidget 实线视口（GPU 渲染实施计划 Task 1）。"""

import time

from PySide6.QtCanvasPainter import (
    QCanvasOffscreenCanvas,
    QCanvasPainter,
    QCanvasPainterWidget,
)
from PySide6.QtCore import QRectF, QSize, Qt
from PySide6.QtGui import QColor, QTransform

from .canvas_paths import line_paths
from .series_cartesian import _to_float

__all__ = ["CanvasLineViewport"]


class CanvasLineViewport(QCanvasPainterWidget):
    """以原有颜色、线宽、圆角、点序和裁剪绘制单条折线系列。"""

    def __init__(self, renderer, coord, parent=None):
        super().__init__(parent)
        self._renderer = renderer
        self._plot = QRectF(coord.plot)
        self._paths = line_paths(renderer._points)
        line_style = renderer.opt.get("lineStyle") or {}
        self._line_width = _to_float(line_style.get("width"), 2.0)
        color = renderer.color()
        if isinstance(line_style.get("color"), str) and line_style["color"]:
            color = QColor(line_style["color"])
        self._color = QColor(color)
        self._canvas = None
        self._canvas_signature = None
        self._canvas_dirty = True
        self.paint_times = []
        self.setMouseTracking(True)
        self.setFillColor(QColor(Qt.transparent))

    def set_paths(self, points):
        self._paths = line_paths(points)
        self._canvas_dirty = True
        self.update()

    def _draw(self, painter):
        if not any(path.commandsSize() >= 2 for path in self._paths):
            return
        painter.save()
        try:
            painter.setTransform(QTransform())
            painter.scale(self.devicePixelRatioF())
            painter.setClipRect(self._plot)
            painter.setAntialias(1.0)
            painter.setStrokeStyle(self._color)
            painter.setLineWidth(self._line_width)
            painter.setLineCap(QCanvasPainter.LineCap.Round)
            painter.setLineJoin(QCanvasPainter.LineJoin.Round)
            for path in self._paths:
                if path.commandsSize() >= 2:
                    painter.stroke(path)
        finally:
            painter.restore()

    def prePaint(self, painter):  # noqa: N802
        dpr = self.devicePixelRatioF()
        signature = (round(self.width() * dpr), round(self.height() * dpr), dpr)
        if signature[0] <= 0 or signature[1] <= 0:
            return
        if self._canvas is None or self._canvas_signature != signature:
            self._canvas = painter.createCanvas(
                QSize(signature[0], signature[1]), 1,
                QCanvasOffscreenCanvas.Flag.PreserveContents)
            if self._canvas.isNull():
                raise RuntimeError("无法创建 Canvas 离屏画布")
            self._canvas.setFillColor(QColor(Qt.transparent))
            self._canvas_signature = signature
            self._canvas_dirty = True
        if self._canvas_dirty:
            self.beginCanvasPainting(self._canvas)
            painter.resetTransform()
            painter.resetClipping()
            painter.clearRect(QRectF(0, 0, signature[0], signature[1]))
            self._draw(painter)
            self.endCanvasPainting()
            self._canvas_dirty = False

    def paint(self, painter):
        started = time.perf_counter()
        self._draw(painter)
        self.paint_times.append((time.perf_counter() - started) * 1000)
        del self.paint_times[:-120]

    def grab_canvas(self, callback):
        if self._canvas is None:
            raise RuntimeError("Canvas 离屏画布尚未初始化")
        self.grabCanvas(self._canvas, lambda image: callback(image.copy()))

    def resizeEvent(self, event):  # noqa: N802
        self._canvas_dirty = True
        super().resizeEvent(event)

    def hideEvent(self, event):  # noqa: N802
        self._canvas = None
        self._canvas_signature = None
        self._canvas_dirty = True
        super().hideEvent(event)

    def graphicsResourcesInvalidated(self):  # noqa: N802
        self._canvas = None
        self._canvas_signature = None
        self._canvas_dirty = True

    def closeEvent(self, event):  # noqa: N802
        self._canvas = None
        self._canvas_signature = None
        self._canvas_dirty = True
        super().closeEvent(event)
