# -*- coding: utf-8 -*-
"""可选局部 QQuickView 图表视口；能力不足时回退完整 QWidget 后端。"""

import logging
from pathlib import Path

from shiboken6 import isValid as _shiboken_is_valid

from PySide6.QtCore import Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import qmlRegisterType
from PySide6.QtQuick import QQuickView
from PySide6.QtWidgets import QWidget

from .scene_item import ChartSceneItem
from .scene_snapshot import quick_capability
from .viewport import (
    _GLViewport,
    _NO_GL_PLATFORMS,
    _RasterViewport,
    _ViewportMixin,
    gl_available,
)

logger = logging.getLogger(__name__)
_REGISTERED = False


class _QuickViewport(_ViewportMixin, QWidget):
    frameSwapped = Signal()

    def __init__(self, chart):
        super().__init__(chart)
        global _REGISTERED
        self._init_viewport(chart)
        self._fallback = None
        if not _REGISTERED:
            qmlRegisterType(ChartSceneItem, "InstructionX.Charts", 1, 0,
                            "ChartSceneItem")
            _REGISTERED = True
        self._view = QQuickView()
        self._view.setResizeMode(QQuickView.SizeRootObjectToView)
        self._view.setSource(QUrl.fromLocalFile(
            str(Path(__file__).with_name("quick_scene.qml"))))
        if self._view.status() == QQuickView.Error:
            raise RuntimeError(f"QML 图表场景加载失败: {self._view.errors()}")
        self._scene = self._view.rootObject().findChild(ChartSceneItem)
        if self._scene is None:
            raise RuntimeError("QML 图表场景缺少 ChartSceneItem")
        self._container = QWidget.createWindowContainer(self._view, self)
        self._container.setMouseTracking(True)
        self._container.setFocusPolicy(Qt.StrongFocus)
        self._view.frameSwapped.connect(self.frameSwapped.emit)
        self._sync_timer = QTimer(self)
        self._sync_timer.setSingleShot(True)
        self._sync_timer.timeout.connect(self._sync_now)
        self._active = "quick"
        self.setGeometry(chart.rect())

    def active_backend(self):
        return self._active

    def _ensure_fallback(self):
        if self._fallback is not None:
            return
        self._fallback = (_GLViewport(self._chart) if gl_available()
                          else _RasterViewport(self._chart))
        if hasattr(self._fallback, "frameSwapped"):
            self._fallback.frameSwapped.connect(self.frameSwapped.emit)
        self._fallback.setGeometry(self.rect())

    def _discard_fallback(self):
        if self._fallback is None:
            return
        self._fallback.close()
        self._fallback.deleteLater()
        self._fallback = None

    def _refresh_backend(self):
        if quick_capability(self._chart):
            self._active = "quick"
            self._discard_fallback()
            self._container.show()
            return
        self._active = "gl" if gl_available() else "raster"
        self._container.hide()
        self._ensure_fallback()
        self._fallback.show()

    def setGeometry(self, rect):  # noqa: N802
        super().setGeometry(rect)
        if hasattr(self, "_container"):
            self._container.setGeometry(self.rect())
        if self._fallback is not None:
            self._fallback.setGeometry(self.rect())

    def showEvent(self, event):  # noqa: N802
        super().showEvent(event)
        self.update()

    def _scene_valid(self):
        return self._scene is not None and _shiboken_is_valid(self._scene)

    def hideEvent(self, event):  # noqa: N802
        self._sync_timer.stop()
        if self._scene_valid():
            self._scene.clear()
        self._container.hide()
        if self._fallback is not None:
            self._fallback.hide()
        super().hideEvent(event)

    def closeEvent(self, event):  # noqa: N802
        self._sync_timer.stop()
        if self._scene_valid():
            self._scene.clear()
        if self._fallback is not None:
            self._fallback.close()
        self._view.close()
        super().closeEvent(event)

    def _sync_now(self):
        if self._active == "quick" and self._scene_valid():
            self._scene.sync(self._chart, self.devicePixelRatioF())

    def update(self, *args):
        self._refresh_backend()
        if self._active == "quick":
            self._sync_timer.start(0)
        else:
            self._fallback.update(*args)

    def paintGL(self):  # noqa: N802
        if self._active == "quick":
            self.update()
        else:
            self._fallback.paintGL()

    def grab(self):
        if self._active == "quick":
            return self._container.grab()
        return self._fallback.grab()

    def grabFramebuffer(self):  # noqa: N802
        if self._active == "quick":
            return self._view.grabWindow()
        if hasattr(self._fallback, "grabFramebuffer"):
            return self._fallback.grabFramebuffer()
        return self._fallback.grab().toImage()

    def mean_paint_ms(self, window: int = 60) -> float:
        if self._active == "quick" or not hasattr(self._fallback, "mean_paint_ms"):
            return 0.0
        return self._fallback.mean_paint_ms(window)


def create_quick_viewport(chart):
    app = QGuiApplication.instance()
    if app is None or app.platformName() in _NO_GL_PLATFORMS:
        return None
    try:
        return _QuickViewport(chart)
    except Exception as exc:
        logger.warning("Scene Graph 图表视口创建失败，回退 QWidget: %s", exc)
        return None
