# -*- coding: utf-8 -*-
"""图表的 RHI 视口与离屏软件验证视口。

真实窗口默认使用 ``QQuickView + Scene Graph``，由 Qt 按平台选择
Direct3D 11、Metal、Vulkan 或 OpenGL，不在本库强制图形 API。
离屏平台没有可呈现窗口，使用同一绘制体的软件视口验证像素和交互。
"""

import logging
import os

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication, QPainter
from PySide6.QtWidgets import QWidget

from ..theme import T

logger = logging.getLogger(__name__)

__all__ = ["create_viewport"]

_SOFTWARE_PLATFORMS = ("offscreen", "minimal", "minimalegl")


class _ViewportMixin:
    """把内部视口的事件交给既有 ChartWidget 处理器。"""

    def _init_viewport(self, chart) -> None:
        self._chart = chart
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setAutoFillBackground(False)
        self.setMinimumSize(0, 0)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        self._chart.mousePressEvent(event)
        event.accept()

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        self._chart.mouseMoveEvent(event)
        event.accept()

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        self._chart.mouseReleaseEvent(event)
        event.accept()

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802
        self._chart.mouseDoubleClickEvent(event)
        event.accept()

    def wheelEvent(self, event) -> None:  # noqa: N802
        self._chart.wheelEvent(event)
        event.accept()

    def leaveEvent(self, event) -> None:  # noqa: N802
        self._chart.leaveEvent(event)
        event.accept()

    def enterEvent(self, event) -> None:  # noqa: N802
        self._chart.enterEvent(event)
        event.accept()

    def contextMenuEvent(self, event) -> None:  # noqa: N802
        self._chart.contextMenuEvent(event)
        event.accept()


class _RasterViewport(_ViewportMixin, QWidget):
    """仅供无窗口平台使用的软件视口，不是旧 OpenGL 回退实现。"""

    def __init__(self, chart) -> None:
        super().__init__(chart)
        self._init_viewport(chart)
        self.setAttribute(Qt.WA_OpaquePaintEvent, True)

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        try:
            chart = self._chart
            snapshot = chart._resize_preview.snapshot
            if snapshot is not None:
                painter.setRenderHint(QPainter.SmoothPixmapTransform)
                painter.drawPixmap(self.rect(), snapshot, snapshot.rect())
                return
            if chart.static_layer_valid(painter):
                painter.setRenderHint(QPainter.Antialiasing)
                painter.drawPixmap(0, 0, chart._static_pixmap_cache)
                chart._paint_dynamic(painter)
            else:
                chart._paint_contents(painter)
        finally:
            painter.end()


def create_viewport(chart) -> QWidget:
    """默认创建 RHI 视口；仅在无窗口平台或初始化失败时使用软件绘制。"""
    app = QGuiApplication.instance()
    platform = app.platformName() if app is not None else ""
    requested = os.environ.get("UIKIT_CHART_BACKEND", "").strip().lower()
    if platform in _SOFTWARE_PLATFORMS or requested == "raster":
        return _RasterViewport(chart)
    try:
        from .rhi_viewport import create_rhi_viewport
        return create_rhi_viewport(chart)
    except Exception as exc:
        logger.warning("RHI 图表视口创建失败，使用软件绘制: %s", exc)
        return _RasterViewport(chart)
