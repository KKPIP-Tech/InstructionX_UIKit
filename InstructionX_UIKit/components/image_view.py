# -*- coding: utf-8 -*-
"""图片展示组件（SPEC §5.2 image_view）。

圆角裁切显示图片；加载失败显示几何占位插画；悬停显示
「预览」蒙层并发出 ``clicked`` 信号（供接入预览弹层）。
"""

from PySide6.QtCore import QRect, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import QLabel

from InstructionX_UIKit.theme import T, ThemeManager

__all__ = ["ImageView"]


class ImageView(QLabel):
    """圆角图片视图。

    参数:
        source: 图片路径或 QPixmap（可为空，稍后再设）。
        radius: 圆角半径（px），缺省取 ``radius.lg`` 令牌。
        parent: 父控件。

    示例::

        iv = ImageView("cover.png")
        iv.setFixedSize(200, 150)
        iv.clicked.connect(open_preview)
    """

    clicked = Signal()

    def __init__(self, source=None, radius: int = None, parent=None):
        super().__init__(parent)
        self._pixmap = QPixmap()
        self._failed = False
        self._radius = radius
        self._hovered = False
        self.setAttribute(Qt.WA_Hover)
        self.setCursor(Qt.PointingHandCursor)
        self.setMinimumSize(120, 90)
        if source is not None:
            self.set_source(source)
        ThemeManager.instance().theme_changed.connect(self.update)

    # ------------------------------------------------------------------ 配置
    def set_source(self, source) -> None:
        """设置图片来源：路径或 QPixmap；失败时显示占位插画。"""
        if isinstance(source, QPixmap):
            self._pixmap = source
        else:
            self._pixmap = QPixmap(str(source))
        self._failed = self._pixmap.isNull()
        self.update()

    def pixmap(self) -> QPixmap:  # noqa: A003 - 与 QLabel.pixmap 语义一致
        return self._pixmap

    def is_failed(self) -> bool:
        return self._failed

    def set_radius(self, radius: int) -> None:
        """设置圆角半径（px）。"""
        self._radius = int(radius)
        self.update()

    # ------------------------------------------------------------------ 事件
    def enterEvent(self, event) -> None:
        self._hovered = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._hovered = False
        self.update()
        super().leaveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.LeftButton and self.rect().contains(event.position().toPoint()):
            self.clicked.emit()
        super().mouseReleaseEvent(event)

    # ------------------------------------------------------------------ 绘制
    def _radius_px(self) -> int:
        return self._radius if self._radius is not None else T("radius.lg")

    def _draw_placeholder(self, painter: QPainter, rect: QRectF) -> None:
        """加载失败占位：几何「图片」图标 + 文案。"""
        painter.fillRect(rect, QColor(T("color.bg.muted")))
        cx, cy = rect.center().x(), rect.center().y() - 8
        w, h = 56, 42
        icon = QRectF(cx - w / 2, cy - h / 2, w, h)
        line = QColor(T("color.border.strong"))
        pen = QPen(line, 1.6)
        pen.setJoinStyle(Qt.RoundJoin)
        painter.setPen(pen)
        painter.setBrush(QColor(T("color.bg.subtle")))
        painter.drawRoundedRect(icon, 6, 6)
        # 太阳
        painter.setBrush(line)
        painter.setPen(Qt.NoPen)
        painter.drawEllipse(QRectF(cx - w / 4 - 4, cy - h / 4 - 2, 9, 9))
        # 山峰
        path = QPainterPath()
        path.moveTo(cx - w / 2 + 6, cy + h / 2 - 6)
        path.lineTo(cx - 6, cy - 2)
        path.lineTo(cx + 2, cy + 4)
        path.lineTo(cx + 10, cy - 4)
        path.lineTo(cx + w / 2 - 6, cy + h / 2 - 6)
        path.closeSubpath()
        painter.drawPath(path)
        # 文案
        painter.setPen(QColor(T("color.text.tertiary")))
        font = painter.font()
        font.setPixelSize(T("font.xs"))
        painter.setFont(font)
        painter.drawText(
            QRectF(rect.left(), cy + h / 2 + 6, rect.width(), 18),
            Qt.AlignHCenter | Qt.AlignTop,
            "加载失败",
        )

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        radius = self._radius_px()
        path = QPainterPath()
        path.addRoundedRect(rect, radius, radius)
        painter.setClipPath(path)

        if not self._failed and not self._pixmap.isNull():
            scaled = self._pixmap.scaled(
                self.size(), Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation
            )
            painter.drawPixmap(
                (self.width() - scaled.width()) // 2,
                (self.height() - scaled.height()) // 2,
                scaled,
            )
        else:
            self._draw_placeholder(painter, rect)

        # 悬停预览蒙层
        if self._hovered and not self._failed:
            overlay = QColor(T("color.overlay"))
            painter.fillRect(rect, overlay)
            painter.setPen(QColor("#FFFFFF"))
            # 放大镜图标
            cx, cy = rect.center().x(), rect.center().y() - 8
            pen = QPen(QColor("#FFFFFF"), 1.8)
            pen.setCapStyle(Qt.RoundCap)
            painter.setPen(pen)
            painter.setBrush(Qt.NoBrush)
            painter.drawEllipse(QRectF(cx - 7, cy - 7, 13, 13))
            painter.drawLine(int(cx + 4), int(cy + 4), int(cx + 9), int(cy + 9))
            font = painter.font()
            font.setPixelSize(T("font.xs"))
            painter.setFont(font)
            painter.drawText(
                QRectF(rect.left(), cy + 12, rect.width(), 16),
                Qt.AlignHCenter | Qt.AlignTop,
                "预览",
            )
        painter.end()
