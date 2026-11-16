# -*- coding: utf-8 -*-
"""BlueprintCanvas 的直接 QCanvasPainterWidget RHI 视口。"""

import time

from PySide6.QtCanvasPainter import QCanvasPainterWidget
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor

from ..charts.canvas_item_viewport import CanvasItemLineChartViewport
from .canvas_scene import (
    blueprint_flow_key,
    blueprint_scene_key,
    build_blueprint_flow,
    build_blueprint_scenes,
)
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
    _continuous_sync = False

    def __init__(self, canvas, parent=None):
        super().__init__(canvas, parent)
        self._scene_key = None
        self._flow_key = None

    def _init_viewport(self, canvas):
        _ViewportMixin._init_viewport(self, canvas)
        self._chart = canvas

    def _sync_now(self):
        if not self._canvas._ui_active or not self.isVisible() or self._view is None:
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
        QCanvasPainterWidget.update(self)
        for widget in self._canvas._node_widgets.values():
            widget.raise_()
        self.sync_times.append((time.perf_counter() - started) * 1000)
        del self.sync_times[:-120]
