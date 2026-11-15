# -*- coding: utf-8 -*-
"""顶层窗口共享 QCanvasPainterItem Scene Graph 的折线视口。"""

import time
import weakref

from shiboken6 import isValid as _shiboken_is_valid
from PySide6.QtCanvasPainter import QCanvasPainterItem, QCanvasPainterItemRenderer
from PySide6.QtCore import QEvent, QObject, QPoint, QPointF, QRect, QRectF, QSizeF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QImage, QPixmap
from PySide6.QtQuick import QQuickView
from PySide6.QtWidgets import QWidget

from .axes import GridCoord
from .canvas_viewport import CanvasLineChartViewport, CanvasLineViewport
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
        self._dashes = tuple(model._dashes)
        self._color = QColor(model._color)
        self._symbol_fill = QColor(model._symbol_fill)
        self._symbol_setting = model._symbol_setting
        self._symbol_size = model._symbol_size
        self._line_width = model._line_width
        self._anim_t = model._anim_t
        self._last_symbol_count = 0


class _CanvasItemRenderer(QCanvasPainterItemRenderer):
    def __init__(self):
        super().__init__()
        self._views = ()
        self.symbol_counts = ()
        self.paint_times = []

    def synchronizeData(self, item):  # noqa: N802
        self._views = tuple(_CanvasPaintModel(model) for model in item._line_views)

    def paint(self, painter):
        started = time.perf_counter()
        for model in self._views:
            model._draw(painter, scale=1.0)
        self.symbol_counts = tuple(model._last_symbol_count for model in self._views)
        self.paint_times.append((time.perf_counter() - started) * 1000)
        del self.paint_times[:-120]


class _CanvasItem(QCanvasPainterItem):
    def __init__(self):
        super().__init__()
        self._line_views = ()
        self._renderer = None
        self.setFillColor(QColor(Qt.transparent))

    def createItemRenderer(self):  # noqa: N802
        self._renderer = _CanvasItemRenderer()
        return self._renderer

    def set_views(self, views):
        self._line_views = tuple(views)
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
                viewport.frameSubmitted.emit()

    def _sync_all(self):
        if self._container is not None and _shiboken_is_valid(self._container):
            self._container.setGeometry(self._window.rect())
        for viewport in tuple(self._viewports):
            viewport._sync_item_geometry()

    def eventFilter(self, obj, event):  # noqa: N802
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

    frameSubmitted = Signal()

    def __init__(self, chart, parent=None):
        super().__init__(parent)
        self._init_viewport(chart)
        self._ready = True
        self._renderer = None
        self._renderer_ids = ()
        self._line_views = []
        self._host = None
        self._view = None
        self._item = None
        self.sync_times = []
        self._sync_timer = QTimer(self)
        self._sync_timer.setSingleShot(True)
        self._sync_timer.timeout.connect(self._sync_now)
        self.setGeometry(chart.rect())

    layout_line = CanvasLineChartViewport.layout_line
    _line_models = staticmethod(CanvasLineChartViewport._line_models)
    _sync_structure = CanvasLineChartViewport._sync_structure

    @property
    def paint_times(self):
        renderer = self._item._renderer if self._item is not None else None
        return renderer.paint_times if renderer is not None else []

    def symbol_count(self, index):
        renderer = self._item._renderer if self._item is not None else None
        counts = renderer.symbol_counts if renderer is not None else ()
        return counts[index] if index < len(counts) else 0

    def _attach(self):
        if not self._ready:
            return
        if self._host is None:
            self._host = _scene_host(self.window())
        self._host._ensure_view()
        self._view = self._host._view
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
        if self._item is not None:
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
        if self._host is None or self._item is None:
            return
        position = self.mapTo(self._host._window, QPoint(0, 0))
        self._item.setPosition(QPointF(position))
        self._item.setSize(QSizeF(self.size()))

    def setGeometry(self, rect):  # noqa: N802
        super().setGeometry(rect)
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
        if self._ready and self._chart._ui_active and self.isVisible():
            self._sync_timer.start(0)

    def _sync_now(self):
        if not self._chart._ui_active or not self.isVisible() or self._item is None:
            return
        started = time.perf_counter()
        self._sync_structure()
        self._chart._layout_all()
        for model in self._line_views:
            model._plot = QRectF(model._coord.plot) if isinstance(model._coord, GridCoord) else None
            geometry = model._renderer._gpu_geometry
            if geometry is not None:
                if model._screen_geometry is not geometry:
                    model.set_arrays(geometry)
            elif model._source_points is not model._renderer._points:
                model.set_paths(model._renderer._points)
        self._item.set_views(self._line_views)
        self.sync_times.append((time.perf_counter() - started) * 1000)
        del self.sync_times[:-120]

    def api(self):
        return self._view.graphicsApi() if self._view is not None else None

    def rhi_api(self):
        return getattr(self.api(), "name", str(self.api()))

    def active_backend(self):
        return "canvas-item-shared"

    def _grab_image(self):
        if self._host is None or self._item is None:
            return QImage()
        image = self._host._view.grabWindow()
        dpr = image.devicePixelRatioF()
        position = self._item.position()
        rect = QRect(round(position.x() * dpr), round(position.y() * dpr),
                     round(self.width() * dpr), round(self.height() * dpr))
        return image.copy(rect)

    def grab_canvas(self, callback):
        self._sync_now()
        QTimer.singleShot(0, lambda: callback(self._grab_image()))

    def grab(self):
        if self._host is None:
            return super().grab()
        return QPixmap.fromImage(self._grab_image())

    def grabFramebuffer(self):  # noqa: N802
        return self._grab_image()
