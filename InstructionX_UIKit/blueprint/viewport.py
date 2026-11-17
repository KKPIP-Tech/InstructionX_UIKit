# -*- coding: utf-8 -*-
"""BlueprintCanvas 的 RHI 视口与离屏软件验证视口。"""

import logging
import os

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication, QPainter
from PySide6.QtWidgets import QWidget

logger = logging.getLogger(__name__)

__all__ = ["create_viewport"]

_SOFTWARE_PLATFORMS = ("offscreen", "minimal", "minimalegl")


class _ViewportMixin:
    def _init_viewport(self, canvas) -> None:
        self._canvas = canvas
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setAutoFillBackground(False)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        self._canvas.mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        self._canvas.mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        self._canvas.mouseReleaseEvent(event)

    def wheelEvent(self, event) -> None:  # noqa: N802
        self._canvas.wheelEvent(event)

    def keyPressEvent(self, event) -> None:  # noqa: N802
        self._canvas.keyPressEvent(event)

    def keyReleaseEvent(self, event) -> None:  # noqa: N802
        self._canvas.keyReleaseEvent(event)


class _RasterViewport(_ViewportMixin, QWidget):
    """无窗口平台的软件视口，保留真实节点自绘用于基线比较。"""

    supports_node_proxy = False

    def __init__(self, canvas) -> None:
        super().__init__(canvas)
        self._init_viewport(canvas)
        self.setAttribute(Qt.WA_OpaquePaintEvent, True)

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        try:
            snapshot = self._canvas._resize_preview.snapshot
            if snapshot is not None:
                painter.setRenderHint(QPainter.SmoothPixmapTransform)
                painter.drawPixmap(self.rect(), snapshot, snapshot.rect())
                return
            painter.setRenderHint(QPainter.Antialiasing)
            self._canvas._paint_contents(painter, event.rect())
        finally:
            painter.end()


def create_viewport(canvas) -> QWidget:
    """默认创建直接 Canvas 视口；显式选择时使用完整 RHI 快照路径。"""
    app = QGuiApplication.instance()
    if app is not None and app.platformName() in _SOFTWARE_PLATFORMS:
        return _RasterViewport(canvas)
    requested = os.environ.get("UIKIT_BLUEPRINT_BACKEND", "canvas").strip().lower()
    if requested == "raster":
        return _RasterViewport(canvas)
    if requested == "canvas":
        from .canvas_viewport import CanvasBlueprintViewport
        return CanvasBlueprintViewport(canvas, parent=canvas)
    try:
        from .rhi_viewport import create_rhi_viewport
        return create_rhi_viewport(canvas)
    except Exception as exc:
        logger.warning("RHI 蓝图画布创建失败，使用软件绘制: %s", exc)
        return _RasterViewport(canvas)
