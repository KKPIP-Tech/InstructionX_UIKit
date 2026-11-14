# -*- coding: utf-8 -*-
"""QQuickView 原生嵌入的 Blueprint RHI 视口与节点事件路由。"""

import time
from pathlib import Path

from shiboken6 import isValid as _shiboken_is_valid

from PySide6.QtCore import QCoreApplication, QEvent, QPointF, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QHelpEvent, QKeyEvent, QMouseEvent, QPixmap, QWheelEvent
from PySide6.QtQml import qmlRegisterType
from PySide6.QtQuick import QQuickView
from PySide6.QtWidgets import QApplication, QWidget

from .node_widget import NodeWidget, PinHandle
from .scene_item import BlueprintSceneItem
from .viewport import _ViewportMixin

_REGISTERED = False


class _RhiViewport(_ViewportMixin, QWidget):
    supports_node_proxy = True
    frameSwapped = Signal()

    def __init__(self, canvas):
        super().__init__(canvas)
        global _REGISTERED
        self._init_viewport(canvas)
        self._mouse_target = None
        self._key_dispatching = False
        if not _REGISTERED:
            qmlRegisterType(BlueprintSceneItem, "InstructionX.Blueprint", 1, 0,
                            "BlueprintSceneItem")
            _REGISTERED = True
        self._view = QQuickView()
        self._view.setColor(Qt.transparent)
        self._view.setResizeMode(QQuickView.SizeRootObjectToView)
        self._view.setSource(QUrl.fromLocalFile(
            str(Path(__file__).with_name("rhi_scene.qml"))))
        if self._view.status() == QQuickView.Error:
            raise RuntimeError(f"RHI 蓝图场景加载失败: {self._view.errors()}")
        self._scene = self._view.rootObject().findChild(BlueprintSceneItem)
        if self._scene is None:
            raise RuntimeError("RHI 蓝图场景缺少 BlueprintSceneItem")
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
        self.setGeometry(canvas.rect())

    def _scene_valid(self):
        return self._scene is not None and _shiboken_is_valid(self._scene)

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
        self._bind_host_state()
        self._container.show()
        self._view.show()
        self._sync_timer.start(0)

    def hideEvent(self, event):  # noqa: N802
        self._sync_timer.stop()
        if self._scene_valid():
            self._scene.clear()
        self._container.hide()
        super().hideEvent(event)

    def closeEvent(self, event):  # noqa: N802
        self._sync_timer.stop()
        self._mouse_target = None
        if self._state_handle is not None:
            try:
                self._state_handle.windowStateChanged.disconnect(self._on_window_state)
            except (RuntimeError, TypeError):
                pass
            self._state_handle = None
        if self._scene_valid():
            self._scene.clear()
        self._view.close()
        super().closeEvent(event)

    def _bind_host_state(self):
        window = self._canvas.window()
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
            self._canvas.on_ui_deactivated()
            self._view.hide()
            return
        if self.isVisible():
            self._view.show()
            self._canvas.on_ui_activated()
            self._sync_timer.start(0)

    def _sync_now(self):
        if not self._canvas._ui_active or not self.isVisible() or not self._scene_valid():
            return
        started = time.perf_counter()
        self._scene.sync(self._canvas, self.devicePixelRatioF())
        self._sync_times.append(time.perf_counter() - started)
        del self._sync_times[:-120]

    def mean_sync_ms(self, window=60):
        samples = self._sync_times[-window:]
        return sum(samples) / len(samples) * 1000 if samples else 0.0

    def update(self, *_args):
        if self._canvas._ui_active and self.isVisible():
            self._sync_timer.start(0)

    def _target_at(self, position):
        for widget in reversed(list(self._canvas._node_widgets.values())):
            if not widget.isVisible():
                continue
            local = widget.mapFrom(self, position.toPoint())
            if not widget.rect().contains(local):
                continue
            child = widget.childAt(local)
            if isinstance(child, PinHandle):
                return child
            body = widget._body
            if (body is not None and body.isVisible()
                    and not body.testAttribute(Qt.WA_TransparentForMouseEvents)):
                body_local = body.mapFrom(self, position.toPoint())
                if body.rect().contains(body_local):
                    return body.childAt(body_local) or body
            return widget
        return self._canvas

    def _mouse_event(self, target, event):
        view_position = event.position().toPoint()
        local = target.mapFrom(self, view_position)
        global_position = self._container.mapToGlobal(view_position)
        return QMouseEvent(event.type(), QPointF(local), QPointF(global_position),
                           event.button(), event.buttons(), event.modifiers())

    def _send_mouse(self, event):
        if event.type() == QEvent.Type.MouseButtonPress:
            self._mouse_target = self._target_at(event.position())
        target = self._mouse_target or self._target_at(event.position())
        if not _shiboken_is_valid(target):
            target = self._canvas
        if event.type() == QEvent.Type.MouseButtonPress:
            if (isinstance(target, (NodeWidget, PinHandle))
                    or target.focusPolicy() == Qt.NoFocus):
                self._canvas.setFocus(Qt.MouseFocusReason)
            else:
                target.setFocus(Qt.MouseFocusReason)
        translated = self._mouse_event(target, event)
        accepted = QCoreApplication.sendEvent(target, translated)
        if event.type() == QEvent.Type.MouseButtonRelease:
            self._mouse_target = None
        self._canvas.update()
        event.accept()
        return True

    def _send_wheel(self, event):
        local = event.position()
        global_position = self._container.mapToGlobal(local.toPoint())
        translated = QWheelEvent(
            local, QPointF(global_position), event.pixelDelta(), event.angleDelta(),
            event.buttons(), event.modifiers(), event.phase(), event.inverted())
        accepted = QCoreApplication.sendEvent(self._canvas, translated)
        self._canvas.update()
        return accepted

    def _send_key(self, event):
        target = QApplication.focusWidget()
        if (target in (self, self._container)
                or target is None or not self.isAncestorOf(target)):
            target = self._canvas
        translated = QKeyEvent(event.type(), event.key(), event.modifiers(), event.text(),
                               event.isAutoRepeat(), event.count())
        self._key_dispatching = True
        try:
            accepted = QCoreApplication.sendEvent(target, translated)
        finally:
            self._key_dispatching = False
        self._canvas.update()
        return accepted

    def _send_tooltip(self, event):
        target = self._target_at(event.position())
        local = target.mapFrom(self, event.position().toPoint())
        global_position = self._container.mapToGlobal(event.position().toPoint())
        return QCoreApplication.sendEvent(
            target, QHelpEvent(event.type(), local, global_position))

    def eventFilter(self, obj, event):  # noqa: N802
        if obj not in (self._container, self._view):
            return super().eventFilter(obj, event)
        if event.type() in (
                QEvent.Type.MouseButtonPress, QEvent.Type.MouseMove,
                QEvent.Type.MouseButtonRelease, QEvent.Type.MouseButtonDblClick):
            return self._send_mouse(event)
        if event.type() == QEvent.Type.Wheel:
            return self._send_wheel(event)
        if event.type() in (QEvent.Type.KeyPress, QEvent.Type.KeyRelease):
            if self._key_dispatching:
                event.accept()
                return True
            return self._send_key(event)
        if event.type() == QEvent.Type.ToolTip:
            return self._send_tooltip(event)
        return False

    def grab(self):
        return QPixmap.fromImage(self._view.grabWindow())

    def grabFramebuffer(self):
        return self._view.grabWindow()


def create_rhi_viewport(canvas):
    return _RhiViewport(canvas)
