# -*- coding: utf-8 -*-
"""QCanvasPainterWidget 实线视口（GPU 渲染实施计划 Task 1）。"""

import time

from PySide6.QtCanvasPainter import (
    QCanvasLinearGradient,
    QCanvasOffscreenCanvas,
    QCanvasPainter,
    QCanvasPainterWidget,
)
from PySide6.QtCore import QPointF, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QPainterPath, QTransform

from .axes import GridCoord
from .canvas_paths import line_paths, path_from_qpainter
from .series_cartesian import _to_float, _with_alpha

__all__ = ["CanvasLineViewport"]


class CanvasLineViewport(QCanvasPainterWidget):
    """以原有颜色、线宽、圆角、点序和裁剪绘制单条折线系列。"""

    def __init__(self, renderer, coord, parent=None):
        super().__init__(parent)
        self._renderer = renderer
        self._coord = coord
        self._plot = QRectF(coord.plot)
        self._areas = []
        self._paths = []
        line_style = renderer.opt.get("lineStyle") or {}
        self._line_width = _to_float(line_style.get("width"), 2.0)
        color = renderer.color()
        if isinstance(line_style.get("color"), str) and line_style["color"]:
            color = QColor(line_style["color"])
        self._color = QColor(color)
        self._rebuild_paths(renderer._points)
        self._canvas = None
        self._canvas_signature = None
        self._canvas_dirty = True
        self.paint_times = []
        self.setMouseTracking(True)
        self.setFillColor(QColor(Qt.transparent))

    def _rebuild_paths(self, points):
        polar = getattr(self._coord, "kind", "") == "polar"
        self._areas = []
        if not self._renderer._line_needs_path(polar):
            self._paths = line_paths(points)
            return
        self._paths = []
        segments = []
        segment = []
        for point in points:
            if point is None:
                if segment:
                    segments.append(segment)
                    segment = []
            else:
                segment.append(point)
        if segment:
            segments.append(segment)
        area = self._renderer.opt.get("areaStyle")
        opacity = _to_float(area.get("opacity"), 0.22) if isinstance(area, dict) else 0.22
        base_y = self._renderer._baseline_y(self._coord)
        for segment in segments:
            if len(segment) < 2:
                continue
            path, spine = self._renderer._line_path(segment)
            if polar:
                path.closeSubpath()
            self._paths.append(path_from_qpainter(path, close=polar))
            if not area:
                continue
            fill = QPainterPath(path)
            if polar:
                brush = _with_alpha(self._color, 255 * opacity)
            elif base_y is not None:
                fill.lineTo(QPointF(spine[-1].x(), base_y))
                fill.lineTo(QPointF(spine[0].x(), base_y))
                fill.closeSubpath()
                top = min(point.y() for point in spine)
                brush = QCanvasLinearGradient(QPointF(0, top), QPointF(0, base_y))
                brush.setStartColor(_with_alpha(self._color, 255 * opacity))
                brush.setEndColor(_with_alpha(self._color, 0))
            else:
                continue
            self._areas.append((path_from_qpainter(fill, close=True), brush))

    def set_paths(self, points):
        self._rebuild_paths(points)
        self._canvas_dirty = True
        self.update()

    def _draw(self, painter):
        if not any(path.commandsSize() >= 2 for path in self._paths):
            return
        painter.save()
        try:
            painter.setTransform(QTransform())
            painter.scale(self.devicePixelRatioF())
            if isinstance(self._coord, GridCoord):
                painter.setClipRect(self._plot)
            else:
                painter.resetClipping()
            painter.setAntialias(1.0)
            painter.setStrokeStyle(self._color)
            painter.setLineWidth(self._line_width)
            painter.setLineCap(QCanvasPainter.LineCap.Round)
            painter.setLineJoin(QCanvasPainter.LineJoin.Round)
            for path, brush in self._areas:
                painter.setFillStyle(brush)
                painter.fill(path)
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
