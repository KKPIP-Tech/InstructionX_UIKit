# -*- coding: utf-8 -*-
"""BlueprintCanvas 的共享 QCanvasPainterItem Scene Graph 视口。"""

import time

from PySide6.QtCore import QCoreApplication, QEvent, QPointF, Qt
from PySide6.QtGui import QColor, QMouseEvent, QWheelEvent
from PySide6.QtWidgets import QApplication

from ..charts.canvas_item_viewport import CanvasItemLineChartViewport
from .canvas_scene import (
    blueprint_flow_key,
    blueprint_scene_key,
    build_blueprint_flow,
    build_blueprint_scenes,
)
from .node_widget import NodeWidget, PinHandle
from .viewport import _ViewportMixin

__all__ = ["CanvasBlueprintViewport"]


class _FlowView:
    def __init__(self, scene):
        self._scene = scene
        self._renderer = None
        self._coord = None
        self._plot = None
        self._points = ()
        self._screen_geometry = None
        self._paths = ()
        self._areas = ()
        self._outlines = ()
        self._ripples = ()
        self._dashes = ()
        self._color = QColor(Qt.transparent)
        self._symbol_fill = QColor(Qt.transparent)
        self._symbol_setting = False
        self._symbol_size = 6.0
        self._line_width = 2.0
        self._anim_t = 1.0
        self._visible = True

    def _draw(self, painter, scale=None):
        if self._visible:
            self._scene.draw(painter)

    def close(self):
        pass

    def deleteLater(self):  # noqa: N802
        pass


class CanvasBlueprintViewport(CanvasItemLineChartViewport):
    supports_node_proxy = True

    def __init__(self, canvas, parent=None):
        self._mouse_target = None
        super().__init__(canvas, parent)
        self._scene_key = None
        self._flow_key = None

    def _init_viewport(self, canvas):
        _ViewportMixin._init_viewport(self, canvas)
        self._chart = canvas

    def _sync_now(self):
        if not self._canvas._ui_active or not self.isVisible() or self._item is None:
            return
        self._sync_timer.stop()
        self._sync_dirty = False
        self._waiting_for_frame = True
        started = time.perf_counter()
        key = blueprint_scene_key(self._canvas)
        if key != self._scene_key:
            static, component, overlay, key = build_blueprint_scenes(self._canvas)
            self._static_scene = static
            self._component_scene = component
            self._overlay_scene = overlay
            self._scene_key = key
        flow_key = blueprint_flow_key(self._canvas)
        if flow_key != self._flow_key:
            for model in self._line_views:
                model.close()
                model.deleteLater()
            scene = build_blueprint_flow(self._canvas)
            self._line_views = () if scene is None else (_FlowView(scene),)
            self._flow_key = flow_key
        self._item.set_views(self._line_views, self._static_scene, self._overlay_scene,
                             component_scene=self._component_scene)
        for widget in self._canvas._node_widgets.values():
            widget.raise_()
        self.sync_times.append((time.perf_counter() - started) * 1000)
        del self.sync_times[:-120]

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

    def _mouse_event(self, target, position, event):
        local = target.mapFrom(self, position.toPoint())
        return QMouseEvent(event.type(), QPointF(local), event.globalPosition(),
                           event.button(), event.buttons(), event.modifiers())

    def _send_mouse(self, event):
        position = QPointF(self.mapFromGlobal(event.globalPosition().toPoint()))
        if event.type() == QEvent.Type.MouseButtonPress:
            self._mouse_target = self._target_at(position)
        target = self._mouse_target or self._target_at(position)
        if event.type() == QEvent.Type.MouseButtonPress:
            if (isinstance(target, (NodeWidget, PinHandle))
                    or target.focusPolicy() == Qt.NoFocus):
                self._canvas.setFocus(Qt.MouseFocusReason)
            else:
                target.setFocus(Qt.MouseFocusReason)
        QCoreApplication.sendEvent(target, self._mouse_event(target, position, event))
        if event.type() == QEvent.Type.MouseButtonRelease:
            self._mouse_target = None
        self._canvas.update()
        event.accept()
        return True

    def _send_wheel(self, event):
        local = QPointF(self.mapFromGlobal(event.globalPosition().toPoint()))
        translated = QWheelEvent(
            QPointF(local), event.globalPosition(), event.pixelDelta(), event.angleDelta(),
            event.buttons(), event.modifiers(), event.phase(), event.inverted(), event.source())
        accepted = QCoreApplication.sendEvent(self._canvas, translated)
        self._canvas.update()
        event.accept()
        return accepted

    def _forward_scene_input(self, event):
        if event.type() in (QEvent.Type.MouseButtonPress, QEvent.Type.MouseMove,
                            QEvent.Type.MouseButtonRelease, QEvent.Type.MouseButtonDblClick):
            return self._send_mouse(event)
        if event.type() == QEvent.Type.Wheel:
            return self._send_wheel(event)
        return False

    def keyPressEvent(self, event):  # noqa: N802
        self._canvas.keyPressEvent(event)

    def keyReleaseEvent(self, event):  # noqa: N802
        self._canvas.keyReleaseEvent(event)

    def _on_window_state(self, state):
        if state & Qt.WindowMinimized:
            self._canvas.on_ui_deactivated()
        else:
            self._canvas.on_ui_activated()
        self._sync_timer.start(0)
