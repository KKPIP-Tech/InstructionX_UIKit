# -*- coding: utf-8 -*-
"""QCanvasPainterWidget 实线视口（GPU 渲染实施计划 Task 1）。"""

import time

from PySide6.QtCanvasPainter import (
    QCanvasLinearGradient,
    QCanvasOffscreenCanvas,
    QCanvasPainter,
    QCanvasPainterWidget,
)
from PySide6.QtCore import QPointF, QRectF, QSize, Qt, QTimer
from PySide6.QtGui import QColor, QPainterPath, QPainterPathStroker, QTransform
from shiboken6 import isValid as _shiboken_is_valid

from ..theme import T, ThemeManager
from .axes import GridCoord
from .canvas_paths import line_path_arrays, line_paths, path_from_qpainter
from .series_cartesian import LineSeriesRenderer, _to_float, _with_alpha
from .viewport import _ViewportMixin

__all__ = ["CanvasLineViewport", "CanvasLineChartViewport", "create_canvas_viewport"]


class CanvasLineViewport(QCanvasPainterWidget):
    """以原有颜色、线宽、圆角、点序和裁剪绘制单条折线系列。"""

    def __init__(self, renderer, coord=None, parent=None):
        super().__init__(parent)
        self._renderer = renderer
        self._coord = coord if coord is not None else (
            renderer.chart.coord_for(renderer.opt) if renderer is not None else None)
        self._plot = QRectF(self._coord.plot) if isinstance(self._coord, GridCoord) else None
        self._points = []
        self._screen_geometry = None
        self._areas = []
        self._paths = []
        self._dashes = []
        self._anim_t = 1.0
        self._last_symbol_count = 0
        line_style = (renderer.opt.get("lineStyle") or {}) if renderer is not None else {}
        self._line_width = _to_float(line_style.get("width"), 2.0)
        self._sync_color()
        self._rebuild_paths(renderer._points if renderer is not None else [])
        self._source_points = renderer._points if renderer is not None else None
        self._canvas = None
        self._canvas_signature = None
        self._canvas_dirty = True
        self._capture_requested = False
        self._capture_callbacks = []
        self.paint_times = []
        self.setMouseTracking(True)
        self.setFillColor(QColor(Qt.transparent))
        ThemeManager.instance().theme_changed.connect(self._on_theme_changed)
        self.destroyed.connect(self._disconnect_theme)

    def _sync_color(self):
        if self._renderer is None:
            self._color = QColor(T("color.text.primary"))
            self._symbol_setting = False
            self._symbol_size = 6.0
        else:
            color = self._renderer.color()
            line_style = self._renderer.opt.get("lineStyle") or {}
            if isinstance(line_style.get("color"), str) and line_style["color"]:
                color = QColor(line_style["color"])
            self._color = QColor(color)
            self._symbol_setting = self._renderer.opt.get("showSymbol", True)
            self._symbol_size = _to_float(self._renderer.opt.get("symbolSize"), 6.0)
        self._symbol_fill = QColor(T("color.bg.elevated"))

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
        self._screen_geometry = None
        if self._renderer is None:
            self._points = list(points)
            self._paths = []
            self._areas = []
            self._dashes = []
            return
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
            if area:
                fill = QPainterPath(path)
                if polar:
                    fill.lineTo(self._coord.center)
                    fill.closeSubpath()
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
                    fill = None
                if fill is not None:
                    self._areas.append((path_from_qpainter(fill, close=True), brush))
            if polar:
                path.closeSubpath()
            if dashed:
                self._dashes.append(self._dash_path(path, line_type))
            else:
                self._paths.append(path_from_qpainter(path, close=polar))

    def _dash_path(self, path, line_type):
        stroker = QPainterPathStroker()
        stroker.setWidth(self._line_width)
        stroker.setCapStyle(Qt.RoundCap)
        stroker.setJoinStyle(Qt.RoundJoin)
        stroker.setMiterLimit(4.0)
        stroker.setDashPattern(Qt.DashLine if line_type in ("dashed", "dash") else Qt.DotLine)
        return path_from_qpainter(stroker.createStroke(path))

    def set_arrays(self, geometry):
        self._screen_geometry = geometry
        self._points = []
        self._areas = []
        self._dashes = []
        self._paths = [line_path_arrays(*geometry)]
        self._canvas_dirty = True
        self.update()

    def set_paths(self, points):
        self._rebuild_paths(points)
        self._source_points = points
        self._canvas_dirty = True
        self.update()

    def set_animation_progress(self, value):
        self._anim_t = float(value)
        if self._renderer is not None:
            self.set_paths(self._renderer._animated_points(self._anim_t))

    def _draw_symbols(self, painter):
        self._last_symbol_count = 0
        valid = [point for point in self._points if point is not None]
        enabled = len(valid) <= 512 if self._symbol_setting == "auto" \
            else bool(self._symbol_setting)
        if not enabled:
            return
        radius = max(1.0, self._symbol_size / 2)
        radius *= max(0.2, self._anim_t)
        painter.setStrokeStyle(self._color)
        painter.setLineWidth(1.5)
        painter.setFillStyle(self._symbol_fill)
        for point in valid:
            painter.beginPath()
            painter.circle(point, radius)
            painter.fill()
            painter.stroke()
            self._last_symbol_count += 1

    def _draw(self, painter, scale=None):
        painter.save()
        try:
            painter.setTransform(QTransform())
            painter.scale(self.devicePixelRatioF() if scale is None else scale)
            if self._plot is not None:
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
        if not self._capture_requested:
            return
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
        self._capture_requested = False
        QTimer.singleShot(0, self._flush_capture_callbacks)

    def _flush_capture_callbacks(self):
        if self._canvas is None:
            return
        callbacks, self._capture_callbacks = self._capture_callbacks, []
        for callback in callbacks:
            self.grabCanvas(self._canvas,
                            lambda image, callback=callback: callback(image.copy()))

    def paint(self, painter):
        started = time.perf_counter()
        self._draw(painter)
        self.paint_times.append((time.perf_counter() - started) * 1000)
        del self.paint_times[:-120]

    def grab_canvas(self, callback):
        self._capture_callbacks.append(callback)
        self._capture_requested = True
        self._canvas_dirty = True
        self.update()

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


class CanvasLineChartViewport(_ViewportMixin, CanvasLineViewport):
    """仅由 line 系列组成的 ChartWidget 原生 Canvas 视口。"""

    def __init__(self, chart, parent=None):
        renderers = self._line_models(chart.series_renderers)
        first = renderers[0] if renderers else None
        coord = chart.coord_for(first.opt) if first is not None else chart.primary_coord()
        super().__init__(first, coord, parent)
        self._init_viewport(chart)
        self._renderer_ids = tuple(renderers)
        self._line_views = [CanvasLineViewport(
            renderer, chart.coord_for(renderer.opt), self) for renderer in renderers]
        self.sync_times = []
        self._sync_timer = QTimer(self)
        self._sync_timer.setSingleShot(True)
        self._sync_timer.timeout.connect(self._sync_now)

    @staticmethod
    def _line_models(renderers):
        if any(not isinstance(renderer, LineSeriesRenderer) for renderer in renderers):
            raise NotImplementedError("CanvasLineChartViewport 当前仅支持 line 系列")
        return list(renderers)

    def _sync_structure(self):
        renderers = self._line_models(self._chart.series_renderers)
        current = tuple(renderers)
        if current == self._renderer_ids:
            return
        for model in self._line_views:
            model.close()
            model.deleteLater()
        self._line_views = [CanvasLineViewport(
            renderer, self._chart.coord_for(renderer.opt), self)
            for renderer in current]
        self._renderer_ids = current
        self._renderer = current[0] if current else None

    def layout_line(self, renderer, rect):
        if self._chart.anim.is_running() or renderer.opt.get("showSymbol") is not False:
            return False
        line_style = renderer.opt.get("lineStyle") or {}
        if str(line_style.get("type") or "solid") not in ("solid", ""):
            return False
        if renderer._line_needs_path(False):
            return False
        arrays = renderer._numeric_arrays(self._chart.coord_for(renderer.opt), rect)
        if arrays is None:
            return False
        indices, values, geometry = arrays
        renderer._gpu_geometry = geometry
        renderer._gpu_entries = (indices, values)
        return True

    def _sync_now(self):
        if not self._chart._ui_active or not self.isVisible():
            return
        started = time.perf_counter()
        self._sync_structure()
        self._chart._layout_all()
        for model in self._line_views:
            model._plot = QRectF(model._coord.plot) \
                if isinstance(model._coord, GridCoord) else None
            geometry = model._renderer._gpu_geometry
            if geometry is not None:
                if model._screen_geometry is not geometry:
                    model.set_arrays(geometry)
            elif model._source_points is not model._renderer._points:
                model.set_paths(model._renderer._points)
        self._canvas_dirty = True
        self.sync_times.append((time.perf_counter() - started) * 1000)
        del self.sync_times[:-120]

    def update(self, *args):
        if not self._chart._ui_active or not self.isVisible():
            return
        self._sync_timer.start(0)
        super().update(*args)

    def _draw(self, painter):
        for model in self._line_views:
            model._draw(painter)

    def set_paths(self, points):
        if self._line_views:
            self._line_views[0].set_paths(points)
        self._canvas_dirty = True
        self.update()

    def set_animation_progress(self, value):
        self._anim_t = float(value)
        for model in self._line_views:
            model.set_animation_progress(value)
        self._canvas_dirty = True
        self.update()

    def _on_theme_changed(self):
        if not _shiboken_is_valid(self):
            return
        for model in self._line_views:
            model._on_theme_changed()
        self._canvas_dirty = True
        self.update()

    def showEvent(self, event):  # noqa: N802
        self._chart.on_ui_activated()
        self.winId()
        self._sync_timer.start(0)
        super().showEvent(event)

    def hideEvent(self, event):  # noqa: N802
        self._sync_timer.stop()
        self._chart.on_ui_deactivated()
        super().hideEvent(event)

    def closeEvent(self, event):  # noqa: N802
        self._sync_timer.stop()
        for model in self._line_views:
            model.close()
            model.deleteLater()
        self._line_views.clear()
        super().closeEvent(event)

    def rhi_api(self):
        return getattr(self.api(), "name", str(self.api()))

    def active_backend(self):
        return "canvas"


def create_canvas_viewport(chart):
    """创建仅含 line 系列的 Canvas 视口，不静默丢弃其他系列。"""
    CanvasLineChartViewport._line_models(chart.series_renderers)
    return CanvasLineChartViewport(chart, parent=chart)
