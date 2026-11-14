# -*- coding: utf-8 -*-
"""QQuickView 原生嵌入的 Chart RHI 视口，不强制平台图形 API。"""

import time
from pathlib import Path

from shiboken6 import isValid as _shiboken_is_valid

from PySide6.QtCore import QCoreApplication, QEvent, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtQml import qmlRegisterType
from PySide6.QtQuick import QQuickView
from PySide6.QtWidgets import QWidget

from .scene_item import ChartSceneItem
from .viewport import _ViewportMixin

_REGISTERED = False


class _RhiViewport(_ViewportMixin, QWidget):
    frameSwapped = Signal()

    def __init__(self, chart):
        super().__init__(chart)
        global _REGISTERED
        self._ready = False
        self._init_viewport(chart)
        chart.prefer_raster_series = True
        if not _REGISTERED:
            qmlRegisterType(ChartSceneItem, "InstructionX.Charts", 1, 0,
                            "ChartSceneItem")
            _REGISTERED = True
        self._view = QQuickView()
        self._view.setColor(Qt.transparent)
        self._view.setResizeMode(QQuickView.SizeRootObjectToView)
        self._view.setSource(QUrl.fromLocalFile(
            str(Path(__file__).with_name("rhi_scene.qml"))))
        if self._view.status() == QQuickView.Error:
            raise RuntimeError(f"RHI 图表场景加载失败: {self._view.errors()}")
        self._scene = self._view.rootObject().findChild(ChartSceneItem)
        if self._scene is None:
            raise RuntimeError("RHI 图表场景缺少 ChartSceneItem")
        self._container = QWidget.createWindowContainer(self._view, self)
        self._container.setMouseTracking(True)
        self._container.setFocusPolicy(Qt.StrongFocus)
        self._container.installEventFilter(self)
        self._view.installEventFilter(self)
        self.setFocusProxy(self._container)
        self._view.frameSwapped.connect(self.frameSwapped.emit)
        self._sync_timer = QTimer(self)
        self._sync_timer.setSingleShot(True)
        self._sync_timer.timeout.connect(self._sync_now)
        self._sync_times = []
        self._state_handle = None
        self.setGeometry(chart.rect())
        self._ready = True

    def _scene_valid(self):
        scene = getattr(self, "_scene", None)
        return scene is not None and _shiboken_is_valid(scene)

    def rhi_api(self):
        if not self._view.isSceneGraphInitialized():
            return "pending"
        return getattr(self._view.graphicsApi(), "name", str(self._view.graphicsApi()))

    def active_backend(self):
        return "rhi"

    def setGeometry(self, rect):  # noqa: N802
        super().setGeometry(rect)
        if hasattr(self, "_container"):
            self._container.setGeometry(self.rect())

    def showEvent(self, event):  # noqa: N802
        super().showEvent(event)
        if not self._ready:
            return
        self._bind_host_state()
        self._container.show()
        self._view.show()
        self._sync_timer.start(0)

    def hideEvent(self, event):  # noqa: N802
        timer = getattr(self, "_sync_timer", None)
        if timer is not None:
            timer.stop()
        if self._scene_valid():
            self._scene.clear()
        container = getattr(self, "_container", None)
        if container is not None:
            container.hide()
        super().hideEvent(event)

    def closeEvent(self, event):  # noqa: N802
        timer = getattr(self, "_sync_timer", None)
        if timer is not None:
            timer.stop()
        handle = getattr(self, "_state_handle", None)
        if handle is not None:
            try:
                handle.windowStateChanged.disconnect(self._on_window_state)
            except (RuntimeError, TypeError):
                pass
            self._state_handle = None
        if self._scene_valid():
            self._scene.clear()
        view = getattr(self, "_view", None)
        if view is not None:
            view.close()
        super().closeEvent(event)

    def _bind_host_state(self):
        window = self._chart.window()
        window.winId()
        handle = window.windowHandle()
        if handle is self._state_handle:
            return
        if self._state_handle is not None:
            try:
                self._state_handle.windowStateChanged.disconnect(self._on_window_state)
            except (RuntimeError, TypeError):
                pass
        self._state_handle = handle
        if handle is not None:
            handle.windowStateChanged.connect(self._on_window_state)

    def _on_window_state(self, state):
        if state & Qt.WindowMinimized:
            self._sync_timer.stop()
            self._chart.on_ui_deactivated()
            self._view.hide()
            return
        if self.isVisible():
            self._view.show()
            self._chart.on_ui_activated()
            self._sync_timer.start(0)

    def _sync_now(self):
        if not self._chart._ui_active or not self.isVisible() or not self._scene_valid():
            return
        started = time.perf_counter()
        self._scene.sync(self._chart, self.devicePixelRatioF())
        self._sync_times.append(time.perf_counter() - started)
        del self._sync_times[:-120]

    def mean_sync_ms(self, window=60):
        samples = self._sync_times[-window:]
        return sum(samples) / len(samples) * 1000 if samples else 0.0

    def update(self, *_args):
        if not self._ready:
            return
        if self._chart._ui_active and self.isVisible():
            self._sync_timer.start(0)

    def eventFilter(self, obj, event):  # noqa: N802
        if not self._ready or obj not in (self._container, self._view):
            return super().eventFilter(obj, event)
        chart = self._chart
        if event.type() == QEvent.Type.Wheel:
            return QCoreApplication.sendEvent(chart, event)
        handlers = {
            QEvent.Type.MouseButtonPress: chart.mousePressEvent,
            QEvent.Type.MouseMove: chart.mouseMoveEvent,
            QEvent.Type.MouseButtonRelease: chart.mouseReleaseEvent,
            QEvent.Type.MouseButtonDblClick: chart.mouseDoubleClickEvent,
            QEvent.Type.KeyPress: chart.keyPressEvent,
            QEvent.Type.KeyRelease: chart.keyReleaseEvent,
            QEvent.Type.Enter: chart.enterEvent,
            QEvent.Type.Leave: chart.leaveEvent,
            QEvent.Type.ContextMenu: chart.contextMenuEvent,
        }
        handler = handlers.get(event.type())
        if handler is None:
            return False
        handler(event)
        if event.type() in (
                QEvent.Type.MouseButtonPress, QEvent.Type.MouseMove,
                QEvent.Type.MouseButtonRelease, QEvent.Type.MouseButtonDblClick,
                QEvent.Type.Enter, QEvent.Type.Leave, QEvent.Type.ContextMenu):
            event.accept()
            return True
        return bool(event.isAccepted())

    def grab(self):
        return QPixmap.fromImage(self._view.grabWindow())

    def grabFramebuffer(self):
        return self._view.grabWindow()


def create_rhi_viewport(chart):
    return _RhiViewport(chart)
