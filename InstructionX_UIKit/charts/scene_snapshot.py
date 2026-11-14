# -*- coding: utf-8 -*-
"""ChartWidget 的不可变 RHI 帧快照，所有 Qt 绘制均在 UI 线程完成。"""

from dataclasses import dataclass

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QImage, QPainter


@dataclass(frozen=True)
class SceneSnapshot:
    image: QImage
    width: int
    height: int
    dpr: float
    version: int


_VERSION = 0


def build_scene_snapshot(chart, dpr: float) -> SceneSnapshot:
    """冻结一张完整最终帧，包含既有系列、组件、主题和 tooltip。"""
    global _VERSION
    dpr = max(1.0, float(dpr))
    width, height = max(1, chart.width()), max(1, chart.height())
    image = QImage(round(width * dpr), round(height * dpr), QImage.Format_RGBA8888)
    image.setDevicePixelRatio(dpr)
    image.fill(Qt.transparent)
    painter = QPainter(image)
    try:
        preview = chart._resize_preview.snapshot
        if preview is not None:
            painter.setRenderHint(QPainter.SmoothPixmapTransform)
            painter.drawPixmap(QRectF(0, 0, width, height), preview, QRectF(preview.rect()))
        else:
            chart._paint_contents(painter)
    finally:
        painter.end()
    _VERSION += 1
    return SceneSnapshot(image=image, width=width, height=height,
                         dpr=dpr, version=_VERSION)
