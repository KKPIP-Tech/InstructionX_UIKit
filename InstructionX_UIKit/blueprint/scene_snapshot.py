# -*- coding: utf-8 -*-
"""BlueprintCanvas 的不可变 RHI 帧快照，包含节点与自定义体。"""

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QImage, QPainter

from .._rhi_texture import SceneSnapshot

_VERSION = 0


def build_scene_snapshot(canvas, dpr: float) -> SceneSnapshot:
    global _VERSION
    dpr = max(1.0, float(dpr))
    width, height = max(1, canvas.width()), max(1, canvas.height())
    image = QImage(round(width * dpr), round(height * dpr), QImage.Format_RGBA8888)
    image.setDevicePixelRatio(dpr)
    image.fill(Qt.transparent)
    painter = QPainter(image)
    try:
        preview = canvas._resize_preview.snapshot
        if preview is not None:
            painter.setRenderHint(QPainter.SmoothPixmapTransform)
            painter.drawPixmap(QRectF(0, 0, width, height), preview, QRectF(preview.rect()))
        else:
            painter.setRenderHint(QPainter.Antialiasing)
            canvas._paint_contents(painter, None)
            painter.setRenderHint(QPainter.SmoothPixmapTransform)
            zoom = canvas._zoom
            for widget in canvas._node_widgets.values():
                if not widget.isVisible():
                    continue
                position = canvas.scene_to_view(widget.node.pos)
                if position.x() > width or position.y() > height:
                    continue
                pixmap = widget.cache_pixmap() if widget.uses_proxy() else widget.grab()
                if widget.uses_proxy() and abs(widget._cache_scale - zoom) > 1e-3:
                    rect = QRectF(position.x(), position.y(),
                                  widget.node.size.width() * zoom,
                                  widget.node.size.height() * zoom)
                    painter.drawPixmap(rect, pixmap, QRectF(pixmap.rect()))
                else:
                    painter.drawPixmap(position, pixmap)
    finally:
        painter.end()
    _VERSION += 1
    return SceneSnapshot(image=image, width=width, height=height,
                         dpr=dpr, version=_VERSION)
