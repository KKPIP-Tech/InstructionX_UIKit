# -*- coding: utf-8 -*-
"""Chart / Blueprint 的局部 QCanvasPainterWidget RHI 绘制视口。"""

import time
import weakref

from PySide6.QtCanvasPainter import QCanvasPainterWidget
from PySide6.QtCore import QEvent, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QImage, QPixmap

from ..theme import T, ThemeManager
from .axes import GridCoord
from .canvas_components import build_tooltip_scene
from .canvas_static import build_static_scene, static_scene_key
from .canvas_viewport import CanvasLineChartViewport, CanvasLineViewport
from .canvas_visuals import build_component_scene, component_scene_key
from .viewport import _ViewportMixin

__all__ = ["CanvasItemLineChartViewport"]


class _CanvasPaintModel:
    _draw = CanvasLineViewport._draw
    _draw_symbols = CanvasLineViewport._draw_symbols

    def __init__(self, model):
        self._coord = None
        self._plot = QRectF(model._plot) if model._plot is not None else None
        self._points = tuple(model._points)
        self._screen_geometry = model._screen_geometry
        self._paths = tuple(model._paths)
        self._areas = tuple(model._areas)
        self._outlines = tuple(getattr(model, "_outlines", ()))
        self._ripples = tuple(getattr(model, "_ripples", ()))
        self._dashes = tuple(model._dashes)
        self._color = QColor(model._color)
        self._symbol_fill = QColor(model._symbol_fill)
        self._symbol_setting = model._symbol_setting
        self._symbol_size = model._symbol_size
        self._line_width = model._line_width
        self._anim_t = model._anim_t
        background = getattr(model, "_background", None)
        self._background = QRectF(background) if background is not None else None
        self._background_color = QColor(getattr(model, "_background_color", model._color))
        self._label_commands = tuple(getattr(model, "_label_commands", ()))
        self._scene = getattr(model, "_scene", None)
        self._visible = model._visible
        self._last_symbol_count = 0
        self._draw = getattr(type(model), "_draw").__get__(self, _CanvasPaintModel)


class _CanvasItemRenderer:
    def __init__(self):
        self._views = ()
        self._static_scene = None
        self._component_scene = None
        self._overlay_scene = None
        self._grid_cache = {}
        self.symbol_counts = ()
        self.paint_times = []

    def synchronizeData(self, item):  # noqa: N802
        self._views = tuple(_CanvasPaintModel(model) for model in item._line_views)
        self._static_scene = item._static_scene
        self._component_scene = getattr(item, "_component_scene", None)
        self._overlay_scene = item._overlay_scene
        if self._static_scene is not None:
            self._static_scene.grid_renderer = self

    def grid_pattern(self, rect, path, ox, oy, step, color, painter):
        """以有界 path group 复用点阵几何，不生成纹理。"""
        key = (step, color.rgba())
        cached = self._grid_cache.get(key)
        if cached is not None and cached[1:] == (ox, oy):
            group = cached[0]
        else:
            if cached is not None:
                painter.removePathGroup(cached[0])
            elif len(self._grid_cache) >= 8:
                _key, oldest = self._grid_cache.pop(next(iter(self._grid_cache)))
                painter.removePathGroup(oldest[0])
            group = len(self._grid_cache) + 1
            self._grid_cache[key] = (group, ox, oy)
        painter.setFillStyle(color)
        painter.fill(path, group)

    def paint(self, painter):
        started = time.perf_counter()
        if self._static_scene is not None:
            self._static_scene.draw(painter)
        for model in self._views:
            model._draw(painter, scale=1.0)
        if self._component_scene is not None:
            self._component_scene.draw(painter)
        if self._overlay_scene is not None:
            self._overlay_scene.draw(painter)
        self.symbol_counts = tuple(model._last_symbol_count for model in self._views)
        self.paint_times.append((time.perf_counter() - started) * 1000)
        del self.paint_times[:-120]


class CanvasItemLineChartViewport(_ViewportMixin, QCanvasPainterWidget):
    """保持既有 QWidget 公共接口的局部 RHI 视口。"""

    _continuous_sync = False
    supports_direct_resize = True

    frameSwapped = Signal()

    def __init__(self, chart, parent=None):
        super().__init__(parent)
        self._init_viewport(chart)
        self._ready = True
        self._renderer = None
        self._renderer_ids = ()
        self._line_views = []
        self._static_scene = None
        self._component_scene = None
        self._overlay_scene = None
        self._tooltip_scene = None
        self._canvas_renderer = _CanvasItemRenderer()
        self._window_ref = None
        self._view = self
        self.sync_times = []
        self._sync_dirty = True
        self._waiting_for_frame = False
        self._sync_timer = QTimer(self)
        self._sync_timer.setSingleShot(True)
        self._sync_timer.timeout.connect(self._sync_now)
        self.setSharedPainter(True)
        self.setFillColor(QColor(T("color.bg.base")))
        self.frameSubmitted.connect(self._emit_frames)
        ThemeManager.instance().theme_changed.connect(self._on_theme_changed)
        self.destroyed.connect(self._disconnect_theme)
        self.setGeometry(chart.rect())

    layout_line = CanvasLineChartViewport.layout_line
    _line_models = staticmethod(CanvasLineChartViewport._line_models)

    def _model_for(self, renderer, coord):
        return CanvasLineViewport(renderer, coord, self)

    def _sync_structure(self):
        current = self._line_models(self._chart.series_renderers)
        if tuple(current) == self._renderer_ids:
            return
        for model in self._line_views:
            model.close()
            model.deleteLater()
        self._line_views = [self._model_for(renderer, self._chart.coord_for(renderer.opt))
                            for renderer in current]
        self._renderer_ids = tuple(current)
        self._renderer = current[0] if current else None

    @property
    def paint_times(self):
        return self._canvas_renderer.paint_times

    def symbol_count(self, index):
        counts = self._canvas_renderer.symbol_counts
        return counts[index] if index < len(counts) else 0

    def _attach(self):
        if not self._ready:
            return
        self._view = self
        window = self.window()
        previous = self._window_ref() if self._window_ref is not None else None
        if previous is not window:
            if previous is not None:
                try:
                    previous.removeEventFilter(self)
                except RuntimeError:
                    pass
            self._window_ref = weakref.ref(window)
            window.installEventFilter(self)
        self._sync_dirty = True
        self._sync_timer.start(0)

    def _detach(self):
        self._view = None
        window = self._window_ref() if self._window_ref is not None else None
        if window is not None:
            try:
                window.removeEventFilter(self)
            except RuntimeError:
                pass
        self._window_ref = None

    def _suspend(self):
        self._sync_timer.stop()
        self._chart.on_ui_deactivated()

    def _restore(self):
        if not self.isVisible() or not self._ready:
            return
        self._attach()
        self._chart.on_ui_activated()
        self._sync_timer.start(0)

    def eventFilter(self, obj, event):  # noqa: N802
        window = self._window_ref() if self._window_ref is not None else None
        if obj is window and event.type() == QEvent.Type.WindowStateChange:
            if window.windowState() & Qt.WindowMinimized:
                self._suspend()
            else:
                QTimer.singleShot(0, self._restore)
        return super().eventFilter(obj, event)

    def _on_theme_changed(self, *_args):
        self.setFillColor(QColor(T("color.bg.base")))
        self._static_scene = None
        self._component_scene = None
        self._overlay_scene = None
        self.update()

    def _disconnect_theme(self, *_args):
        try:
            ThemeManager.instance().theme_changed.disconnect(self._on_theme_changed)
        except (RuntimeError, TypeError):
            pass

    def setGeometry(self, rect):  # noqa: N802
        super().setGeometry(rect)
        self._sync_dirty = True

    def resizeEvent(self, event):  # noqa: N802
        self._sync_dirty = True
        super().resizeEvent(event)

    def showEvent(self, event):  # noqa: N802
        super().showEvent(event)
        if not self._ready:
            return
        self._attach()
        self._chart.on_ui_activated()
        self._sync_timer.start(0)

    def hideEvent(self, event):  # noqa: N802
        if not self._ready:
            super().hideEvent(event)
            return
        self._sync_timer.stop()
        self._chart.on_ui_deactivated()
        super().hideEvent(event)

    def closeEvent(self, event):  # noqa: N802
        self._closing = True
        self._ready = False
        self._sync_timer.stop()
        self._canvas_renderer._views = ()
        self._canvas_renderer._grid_cache.clear()
        self._detach()
        for model in self._line_views:
            model.close()
        super().closeEvent(event)

    def _emit_frames(self):
        if self._view is None:
            return
        self._waiting_for_frame = False
        if self.isVisible() and self._chart._ui_active:
            animation = getattr(self._chart, "anim", None)
            animating = animation is not None and animation.is_running()
            if self._sync_dirty or self._continuous_sync or animating:
                self._sync_timer.start(0)
            self.frameSwapped.emit()

    def paint(self, painter):
        if not self._ready or self._view is None:
            return
        self._canvas_renderer.synchronizeData(self)
        self._canvas_renderer.paint(painter)

    def update(self, *_args):
        if not self._ready:
            return
        self._sync_dirty = True
        if self._chart._ui_active and self.isVisible() and not self._waiting_for_frame:
            self._sync_timer.start(0)

    def _sync_series_model(self, model):
        model._visible = model._renderer.visible
        model._plot = QRectF(model._coord.plot) if isinstance(model._coord, GridCoord) else None
        geometry = model._renderer._gpu_geometry
        if geometry is not None:
            if model._screen_geometry is not geometry:
                model.set_arrays(geometry)
        elif model._source_points is not model._renderer._points:
            model.set_paths(model._renderer._points)

    def _sync_now(self):
        if not self._chart._ui_active or not self.isVisible() or self._view is None:
            return
        self._sync_timer.stop()
        self._sync_dirty = False
        self._waiting_for_frame = True
        started = time.perf_counter()
        try:
            self._sync_structure()
            component_scene_key(self._chart)
        except NotImplementedError as exc:
            self._fallback_to_rhi(exc)
            return
        self._chart._layout_all()
        for model in self._line_views:
            self._sync_series_model(model)
        if self._static_scene is None or self._static_scene.key != static_scene_key(self._chart):
            self._static_scene = build_static_scene(self._chart)
        if self._component_scene is None \
                or self._component_scene.key != component_scene_key(self._chart):
            self._component_scene = build_component_scene(self._chart)
        tooltip_scene = build_tooltip_scene(self._chart)
        if tooltip_scene is None:
            self._tooltip_scene = None
        elif self._tooltip_scene is None or self._tooltip_scene.key != tooltip_scene.key:
            self._tooltip_scene = tooltip_scene
        self._overlay_scene = self._tooltip_scene
        super().update()
        self.sync_times.append((time.perf_counter() - started) * 1000)
        del self.sync_times[:-120]

    def _fallback_to_rhi(self, reason):
        chart = self._chart
        chart._backend_fallback_reason = str(reason)
        try:
            from .rhi_viewport import create_rhi_viewport
            viewport = create_rhi_viewport(chart)
        except Exception:
            from .viewport import _RasterViewport
            viewport = _RasterViewport(chart)
        chart._viewport = viewport
        self.close()
        self.deleteLater()
        viewport.setGeometry(chart.rect())
        viewport.show()
        viewport.raise_()

    def mean_sync_ms(self, window=60):
        samples = self.sync_times[-window:]
        return sum(samples) / len(samples) if samples else 0.0

    def rhi_api(self):
        return getattr(self.api(), "name", str(self.api()))

    def active_backend(self):
        return "canvas-widget"

    @staticmethod
    def _capture_widget(widget):
        from PySide6.QtWidgets import QWidget
        return QWidget.grab(widget).toImage().convertToFormat(
            QImage.Format_ARGB32_Premultiplied)

    def grab_canvas(self, callback):
        if self._view is None or not self.isVisible():
            QTimer.singleShot(0, lambda: callback(QImage()))
            return
        self._sync_now()
        QTimer.singleShot(0, lambda: callback(self._capture_widget(self)))

    def _grab_sync(self):
        if self._view is None or not self.isVisible():
            return QImage()
        self._sync_now()
        return self._capture_widget(self)

    def grab(self):
        if self._view is None:
            return super().grab()
        return QPixmap.fromImage(self._grab_sync())

    def grabFramebuffer(self):  # noqa: N802
        return self._grab_sync()
