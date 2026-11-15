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
from PySide6.QtGui import QColor, QPainterPath, QPainterPathStroker, QTransform
from shiboken6 import isValid as _shiboken_is_valid

from ..theme import T, ThemeManager
from .axes import GridCoord
from .canvas_paths import line_paths, path_from_qpainter
from .series_cartesian import _to_float, _with_alpha

__all__ = ["CanvasLineViewport"]


class CanvasLineViewport(QCanvasPainterWidget):
    """以原有颜色、线宽、圆角、点序和裁剪绘制单条折线系列。"""

    def __init__(self, renderer, coord=None, parent=None):
        super().__init__(parent)
        self._renderer = renderer
        self._coord = coord if coord is not None else renderer.chart.coord_for(renderer.opt)
        self._plot = QRectF(self._coord.plot) if isinstance(self._coord, GridCoord) else QRectF()
        self._points = []
        self._areas = []
        self._paths = []
        self._dashes = []
        self._anim_t = 1.0
        self._last_symbol_count = 0
        line_style = renderer.opt.get("lineStyle") or {}
        self._line_width = _to_float(line_style.get("width"), 2.0)
        self._sync_color()
        self._rebuild_paths(renderer._points)
        self._canvas = None
        self._canvas_signature = None
        self._canvas_dirty = True
        self.paint_times = []
        self.setMouseTracking(True)
        self.setFillColor(QColor(Qt.transparent))
        ThemeManager.instance().theme_changed.connect(self._on_theme_changed)
        self.destroyed.connect(self._disconnect_theme)

    def _sync_color(self):
        color = self._renderer.color()
        line_style = self._renderer.opt.get("lineStyle") or {}
        if isinstance(line_style.get("color"), str) and line_style["color"]:
            color = QColor(line_style["color"])
        self._color = QColor(color)

    def _on_theme_changed(self):
        if not _shiboken_is_valid(self):
            return
        self._sync_color()
        self._rebuild_paths(self._points)
        self._canvas_dirty = True
        self.update()

    def _disconnect_theme(self):
        try:
            ThemeManager.instance().theme_changed.disconnect(self._on_theme_changed)
        except (RuntimeError, TypeError):
            pass

    def _rebuild_paths(self, points):
        polar = getattr(self._coord, "kind", "") == "polar"
        self._points = list(points)
        self._areas = []
        self._dashes = []
        line_type = str((self._renderer.opt.get("lineStyle") or {}).get("type") or "solid")
        dashed = line_type in ("dashed", "dash", "dotted", "dot")
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
        if not self._renderer._line_needs_path(polar):
            self._paths = [] if dashed else line_paths(points)
            if dashed:
                for segment in segments:
                    if len(segment) >= 2:
                        path, _ = self._renderer._line_path(segment)
                        self._dashes.append(self._dash_path(path, line_type))
            return
        self._paths = []
        area = self._renderer.opt.get("areaStyle")
        opacity = _to_float(area.get("opacity"), 0.22) if isinstance(area, dict) else 0.22
        base_y = self._renderer._baseline_y(self._coord)
        for segment in segments:
            if len(segment) < 2:
                continue
            path, spine = self._renderer._line_path(segment)
            if polar:
                path.closeSubpath()
            if dashed:
                self._dashes.append(self._dash_path(path, line_type))
            else:
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

    def _dash_path(self, path, line_type):
        stroker = QPainterPathStroker()
        stroker.setWidth(self._line_width)
        stroker.setCapStyle(Qt.RoundCap)
        stroker.setJoinStyle(Qt.RoundJoin)
        stroker.setMiterLimit(4.0)
        stroker.setDashPattern(Qt.DashLine if line_type in ("dashed", "dash") else Qt.DotLine)
        return path_from_qpainter(stroker.createStroke(path))

    def set_paths(self, points):
        self._rebuild_paths(points)
        self._canvas_dirty = True
        self.update()

    def set_animation_progress(self, value):
        self._anim_t = float(value)
        self.set_paths(self._renderer._animated_points(self._anim_t))

    def _draw_symbols(self, painter):
        self._last_symbol_count = 0
        setting = self._renderer.opt.get("showSymbol", True)
        valid = [point for point in self._points if point is not None]
        enabled = len(valid) <= 512 if setting == "auto" else bool(setting)
        if not enabled:
            return
        radius = max(1.0, _to_float(self._renderer.opt.get("symbolSize"), 6.0) / 2)
        radius *= max(0.2, self._anim_t)
        painter.setStrokeStyle(self._color)
        painter.setLineWidth(1.5)
        painter.setFillStyle(QColor(T("color.bg.elevated")))
        for point in valid:
            painter.beginPath()
            painter.circle(point, radius)
            painter.fill()
            painter.stroke()
            self._last_symbol_count += 1

    def _draw(self, painter):
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
            if self._dashes:
                painter.setFillStyle(self._color)
                for path in self._dashes:
                    painter.fill(path)
            else:
                for path in self._paths:
                    if path.commandsSize() >= 2:
                        painter.stroke(path)
            self._draw_symbols(painter)
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
        self._disconnect_theme()
        self._canvas = None
        self._canvas_signature = None
        self._canvas_dirty = True
        super().closeEvent(event)
