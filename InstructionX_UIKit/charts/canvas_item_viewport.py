# -*- coding: utf-8 -*-
"""顶层窗口共享 QCanvasPainterItem Scene Graph 的折线视口。"""

import time
import weakref

from shiboken6 import isValid as _shiboken_is_valid
from PySide6.QtCanvasPainter import QCanvasPainterItem, QCanvasPainterItemRenderer
from PySide6.QtCore import QCoreApplication, QEvent, QObject, QPoint, QPointF, QRect, QRectF, QSizeF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QContextMenuEvent, QImage, QMouseEvent, QPixmap, QWheelEvent
from PySide6.QtQuick import QQuickView
from PySide6.QtWidgets import QApplication, QWidget

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


class _CanvasItemRenderer(QCanvasPainterItemRenderer):
    def __init__(self):
        super().__init__()
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


_OVERLAY_UNSET = object()


class _CanvasItem(QCanvasPainterItem):
    def __init__(self):
        super().__init__()
        self._line_views = ()
        self._static_scene = None
        self._component_scene = None
        self._overlay_scene = None
        self._renderer = None
        self.setFillColor(QColor(Qt.transparent))

    def createItemRenderer(self):  # noqa: N802
        self._renderer = _CanvasItemRenderer()
        return self._renderer

    def set_views(self, views, static_scene=None, overlay_scene=_OVERLAY_UNSET,
                  component_scene=_OVERLAY_UNSET):
        self._line_views = tuple(views)
        if static_scene is not None:
            self._static_scene = static_scene
        if overlay_scene is not _OVERLAY_UNSET:
            self._overlay_scene = overlay_scene
        if component_scene is not _OVERLAY_UNSET:
            self._component_scene = component_scene
        self.update()


_RETIREMENTS = set()


class _RendererRetirement:
    def __init__(self, renderer, view):
        self.renderer = renderer
        _RETIREMENTS.add(self)
        view.destroyed.connect(self.release)

    def release(self, *_args):
        self.renderer = None
        _RETIREMENTS.discard(self)


class _CanvasSceneHost(QObject):
    def __init__(self, window):
        super().__init__(window)
        self._window_ref = weakref.ref(window)
        self._viewports = []
        self._view = None
        self._container = None
        self._ensure_view()
        window.installEventFilter(self)
        window.destroyed.connect(self._window_destroyed)

    @property
    def _window(self):
        return self._window_ref()

    def _ensure_view(self):
        if self._view is not None and _shiboken_is_valid(self._view):
            return
        self._view = QQuickView()
        self._view.setColor(Qt.transparent)
        self._view.setResizeMode(QQuickView.SizeRootObjectToView)
        self._view.frameSwapped.connect(self._emit_frames)
        self._view.installEventFilter(self)
        self._container = QWidget.createWindowContainer(self._view, self._window)
        self._container.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self._container.setGeometry(self._window.rect())
        self._container.show()

    def _release_view(self):
        view = self._view
        if view is not None and _shiboken_is_valid(view):
            view.hide()
        for viewport in tuple(self._viewports):
            viewport._dispose_item()
            viewport._view = None
        self._viewports.clear()
        self._view = None
        if view is not None and _shiboken_is_valid(view):
            view.setParent(None)
            view.close()
        container, self._container = self._container, None
        if container is not None and _shiboken_is_valid(container):
            container.hide()
            container.deleteLater()

    def register(self, viewport):
        self._ensure_view()
        if viewport not in self._viewports:
            self._viewports.append(viewport)
        self._container.setGeometry(self._window.rect())
        self._container.show()
        self._container.raise_()
        viewport.raise_()
        if self._window.windowState() & Qt.WindowMinimized:
            viewport._suspend()
        else:
            self._view.show()
            viewport._sync_timer.start(0)

    def unregister(self, viewport):
        if viewport in self._viewports:
            self._viewports.remove(viewport)
        if not self._viewports:
            if getattr(viewport, "_closing", False):
                self._release_view()
            elif self._view is not None:
                self._view.hide()
                self._container.hide()

    def _emit_frames(self):
        for viewport in tuple(self._viewports):
            if viewport.isVisible() and viewport._chart._ui_active:
                animation = getattr(viewport._chart, "anim", None)
                animating = animation is not None and animation.is_running()
                if viewport._sync_dirty or viewport._continuous_sync or animating:
                    viewport._waiting_for_frame = False
                    viewport._sync_timer.start(0)
                viewport.frameSubmitted.emit()
                viewport.frameSwapped.emit()

    def _sync_all(self):
        if self._container is not None and _shiboken_is_valid(self._container):
            self._container.setGeometry(self._window.rect())
        for viewport in tuple(self._viewports):
            viewport._sync_item_geometry()

    def _input_target(self, global_pos):
        target = QApplication.widgetAt(global_pos)
        if target is None or target is self._container:
            target = self._window.childAt(self._window.mapFromGlobal(global_pos))
        if target is None or target is self._container:
            for viewport in self._viewports:
                if viewport.isVisible() and viewport.rect().contains(
                        viewport.mapFromGlobal(global_pos)):
                    target = viewport
                    break
        return target

    def _forward_input(self, event):
        if event.type() not in (QEvent.Type.KeyPress, QEvent.Type.KeyRelease):
            global_pos = event.globalPosition().toPoint()
            for viewport in tuple(self._viewports):
                handler = getattr(viewport, "_forward_scene_input", None)
                if handler is not None and viewport.isVisible() \
                        and viewport.rect().contains(viewport.mapFromGlobal(global_pos)) \
                        and handler(event):
                    event.accept()
                    return True
        if event.type() in (QEvent.Type.KeyPress, QEvent.Type.KeyRelease):
            target = QApplication.focusWidget()
            if target is None or target in (self._container, self._view):
                target = self._viewports[0] if self._viewports else None
            if hasattr(target, "_chart"):
                target = target._chart
            if target is None:
                return False
            QCoreApplication.sendEvent(target, event)
            event.accept()
            return True
        if isinstance(event, QContextMenuEvent):
            global_pos = event.globalPos()
        else:
            global_pos = event.globalPosition().toPoint()
        target = self._input_target(global_pos)
        if target is None:
            return False
        local_pos = target.mapFromGlobal(global_pos)
        if isinstance(event, QContextMenuEvent):
            forwarded = QContextMenuEvent(event.reason(), local_pos, global_pos)
        elif isinstance(event, QWheelEvent):
            forwarded = QWheelEvent(
                QPointF(local_pos), QPointF(global_pos), event.pixelDelta(),
                event.angleDelta(), event.buttons(), event.modifiers(), event.phase(),
                event.inverted(), event.source())
        else:
            forwarded = QMouseEvent(
                event.type(), QPointF(local_pos), QPointF(local_pos),
                QPointF(global_pos), event.button(), event.buttons(), event.modifiers())
        QCoreApplication.sendEvent(target, forwarded)
        event.accept()
        return True

    def eventFilter(self, obj, event):  # noqa: N802
        if obj is self._view and event.type() in (
                QEvent.Type.MouseButtonPress, QEvent.Type.MouseMove,
                QEvent.Type.MouseButtonRelease, QEvent.Type.MouseButtonDblClick,
                QEvent.Type.Wheel, QEvent.Type.ContextMenu,
                QEvent.Type.KeyPress, QEvent.Type.KeyRelease):
            return self._forward_input(event)
        if obj is not self._window:
            return super().eventFilter(obj, event)
        if event.type() == QEvent.Type.Resize:
            self._sync_all()
            QTimer.singleShot(0, self._sync_all)
        elif event.type() == QEvent.Type.WindowStateChange:
            if self._window.windowState() & Qt.WindowMinimized:
                for viewport in tuple(self._viewports):
                    viewport._suspend()
                if self._view is not None:
                    self._view.hide()
            else:
                if self._viewports and self._view is not None:
                    self._view.show()
                for viewport in tuple(self._viewports):
                    viewport._restore()
        elif event.type() == QEvent.Type.Close:
            self._release_view()
        return super().eventFilter(obj, event)

    def _window_destroyed(self, *_args):
        window = self._window
        if window is not None:
            _HOSTS.pop(window, None)
        self._release_view()


_HOSTS = weakref.WeakKeyDictionary()


def _scene_host(window):
    host = _HOSTS.get(window)
    if host is None:
        host = _CanvasSceneHost(window)
        _HOSTS[window] = host
    return host


class CanvasItemLineChartViewport(_ViewportMixin, QWidget):
    """保持 ChartWidget 公共接口的共享 Scene Graph 内部视口。"""

    _continuous_sync = False

    frameSubmitted = Signal()
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
        self._tooltip_scene = None
        self._host = None
        self._view = None
        self._item = None
        self.sync_times = []
        self._sync_dirty = True
        self._waiting_for_frame = False
        self._sync_timer = QTimer(self)
        self._sync_timer.setSingleShot(True)
        self._sync_timer.timeout.connect(self._sync_now)
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
        renderer = self._item._renderer if self._item is not None \
            and _shiboken_is_valid(self._item) else None
        return renderer.paint_times if renderer is not None else []

    def symbol_count(self, index):
        renderer = self._item._renderer if self._item is not None \
            and _shiboken_is_valid(self._item) else None
        counts = renderer.symbol_counts if renderer is not None else ()
        return counts[index] if index < len(counts) else 0

    def _attach(self):
        if not self._ready:
            return
        if self._host is None:
            self._host = _scene_host(self.window())
        self._host._ensure_view()
        self._view = self._host._view
        if self._item is not None and not _shiboken_is_valid(self._item):
            self._item = None
        if self._item is None:
            self._item = _CanvasItem()
        if self._item.parentItem() is not self._view.contentItem():
            self._item.setParentItem(self._view.contentItem())
        self._item.setVisible(True)
        self._host.register(self)
        self._sync_item_geometry()
        self._item.set_views(self._line_views)
        self._sync_timer.start(0)

    def _detach(self):
        if self._host is None:
            return
        host = self._host
        self._host = None
        self._view = None
        if self._item is not None:
            self._item.set_views(())
            self._item.setVisible(False)
        host.unregister(self)

    def _dispose_item(self):
        if self._item is not None and not _shiboken_is_valid(self._item):
            self._item = None
        if self._item is not None:
            renderer = self._item._renderer
            if renderer is not None and self._view is not None \
                    and _shiboken_is_valid(self._view):
                _RendererRetirement(renderer, self._view)
            self._item.setVisible(False)
            self._item.setParentItem(None)
            self._item = None

    def _suspend(self):
        self._sync_timer.stop()
        self._chart.on_ui_deactivated()
        if self._item is not None and _shiboken_is_valid(self._item):
            self._item.setVisible(False)

    def _restore(self):
        if not self.isVisible():
            return
        if self._item is None or self._view is None:
            self._attach()
        if self._item is not None:
            self._item.setVisible(True)
        self._chart.on_ui_activated()
        self._sync_item_geometry()
        self._sync_timer.start(0)

    def _sync_item_geometry(self):
        if self._host is None or self._item is None or not _shiboken_is_valid(self._item):
            return
        position = self.mapTo(self._host._window, QPoint(0, 0))
        self._item.setPosition(QPointF(position))
        self._item.setSize(QSizeF(self.size()))

    def setGeometry(self, rect):  # noqa: N802
        super().setGeometry(rect)
        self._sync_dirty = True
        self._sync_item_geometry()

    def resizeEvent(self, event):  # noqa: N802
        self._sync_item_geometry()
        super().resizeEvent(event)

    def showEvent(self, event):  # noqa: N802
        super().showEvent(event)
        if not self._ready:
            return
        self._attach()
        self.raise_()
        self._chart.on_ui_activated()
        self._sync_timer.start(0)

    def hideEvent(self, event):  # noqa: N802
        if not self._ready:
            return
        self._sync_timer.stop()
        self._chart.on_ui_deactivated()
        self._detach()
        super().hideEvent(event)

    def closeEvent(self, event):  # noqa: N802
        self._closing = True
        self._sync_timer.stop()
        self._dispose_item()
        self._detach()
        for model in self._line_views:
            model.close()
        super().closeEvent(event)
        self._ready = False

    def update(self, *_args):
        if not self._ready:
            return
        self._sync_dirty = True
        if self._chart._ui_active and self.isVisible():
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
        if not self._chart._ui_active or not self.isVisible() or self._item is None \
                or not _shiboken_is_valid(self._item):
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
        self._item.set_views(self._line_views, self._static_scene, self._tooltip_scene,
                             component_scene=self._component_scene)
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

    def api(self):
        return self._view.graphicsApi() if self._view is not None else None

    def rhi_api(self):
        return getattr(self.api(), "name", str(self.api()))

    def active_backend(self):
        return "canvas-item-shared"

    def _grab_image(self):
        if self._host is None or self._item is None or not _shiboken_is_valid(self._item):
            return QImage()
        image = self._host._view.grabWindow()
        dpr = image.devicePixelRatioF()
        position = self._item.position()
        rect = QRect(round(position.x() * dpr), round(position.y() * dpr),
                     round(self.width() * dpr), round(self.height() * dpr))
        return image.copy(rect)

    def grab_canvas(self, callback):
        self._sync_now()
        if self._host is None:
            QTimer.singleShot(0, lambda: callback(self._grab_image()))
            return

        def captured():
            try:
                self.frameSwapped.disconnect(captured)
            except (RuntimeError, TypeError):
                pass
            callback(self._grab_image())

        self.frameSwapped.connect(captured)

    def grab(self):
        if self._host is None:
            return super().grab()
        return QPixmap.fromImage(self._grab_image())

    def grabFramebuffer(self):  # noqa: N802
        return self._grab_image()
