# -*- coding: utf-8 -*-
"""图片展示组件（SPEC §5.2 image_view）。

圆角裁切显示图片；加载失败显示几何占位插画；悬停显示「预览」蒙层
并发出 ``clicked`` 信号（供接入预览弹层）。

占位与蒙层都是「图标 + 文案」一组，按整组居中而不是把图标单独上移
固定像素——后者在窄图上会让整组偏上，图标与文案的间距也会随尺寸变形。
"""

from PySide6.QtCore import QRect, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import QLabel

from InstructionX_UIKit.theme import T, ThemeManager, set_property

__all__ = ["ImageView"]

#: 占位插画尺寸（px，字形尺寸而非版面度量）
_ICON_W = 56
_ICON_H = 42
#: 图标与文案之间的间距（令牌）
_ICON_TEXT_GAP = T("space.1")
#: 占位插画圆角
_ICON_R = 6
#: 蒙层放大镜直径 / 描边
_LENS_D = 14
_LENS_W = 1.8
#: 蒙层文案高度
_TEXT_H = 16
#: 最小尺寸：容得下「图标 + 文案」整组（图标高 + 间距 + 文案高 + 上下留白）
_MIN_W = T("space.12") + T("space.10")
_MIN_H = _ICON_H + _ICON_TEXT_GAP + _TEXT_H + T("space.3")


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
        self._scaled = QPixmap()      # 缩放结果缓存（按 (宽, 高, DPR) 为键）
        self._scaled_key = None
        set_property(self, "role", "plain")
        self.setAttribute(Qt.WA_Hover)
        self.setCursor(Qt.PointingHandCursor)
        self.setMinimumSize(_MIN_W, _MIN_H)
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
        self._scaled_key = None  # 源图变化，缩放缓存失效
        self.update()

    def pixmap(self) -> QPixmap:  # noqa: A003 - 与 QLabel.pixmap 语义一致
        return self._pixmap

    def is_failed(self) -> bool:
        return self._failed

    def set_radius(self, radius: int) -> None:
        """设置圆角半径（px）。"""
        self._radius = int(radius)
        self.update()

    def radius(self) -> int:
        """当前圆角半径（px）。"""
        return self._radius_px()

    # ------------------------------------------------------------------ 事件
    def enterEvent(self, event) -> None:  # noqa: N802 - Qt 回调
        self._hovered = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802 - Qt 回调
        self._hovered = False
        self.update()
        super().leaveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802 - Qt 回调
        if event.button() == Qt.LeftButton and self.rect().contains(event.position().toPoint()):
            self.clicked.emit()
        super().mouseReleaseEvent(event)

    # ------------------------------------------------------------------ 绘制
    def _radius_px(self) -> int:
        return self._radius if self._radius is not None else T("radius.lg")

    def _group_top(self, rect: QRectF, icon_h: int, font_h: int) -> float:
        """「图标 + 文案」整组的顶边：按整组居中，间距走令牌。"""
        group_h = icon_h + _ICON_TEXT_GAP + font_h
        return rect.center().y() - group_h / 2

    def _draw_placeholder(self, painter: QPainter, rect: QRectF) -> None:
        """加载失败占位：几何「图片」图标 + 文案。"""
        painter.fillRect(rect, QColor(T("color.bg.muted")))
        font = painter.font()
        font.setPixelSize(T("font.xs"))
        painter.setFont(font)
        top = self._group_top(rect, _ICON_H, _TEXT_H)
        cx = rect.center().x()
        icon = QRectF(cx - _ICON_W / 2, top, _ICON_W, _ICON_H)
        line = QColor(T("color.border.strong"))
        pen = QPen(line, 1.6)
        pen.setJoinStyle(Qt.RoundJoin)
        painter.setPen(pen)
        painter.setBrush(QColor(T("color.bg.subtle")))
        painter.drawRoundedRect(icon, _ICON_R, _ICON_R)
        # 太阳
        painter.setBrush(line)
        painter.setPen(Qt.NoPen)
        painter.drawEllipse(QRectF(icon.left() + _ICON_W / 4 - 4,
                                   icon.top() + _ICON_H / 4 - 2, 9, 9))
        # 山峰
        mid_y = top + _ICON_H / 2
        path = QPainterPath()
        path.moveTo(icon.left() + 6, icon.top() + _ICON_H - 6)
        path.lineTo(cx - 6, mid_y - 2)
        path.lineTo(cx + 2, mid_y + 4)
        path.lineTo(cx + 10, mid_y - 4)
        path.lineTo(icon.right() - 6, icon.top() + _ICON_H - 6)
        path.closeSubpath()
        painter.drawPath(path)
        # 文案
        painter.setPen(QColor(T("color.text.tertiary")))
        painter.drawText(QRectF(rect.left(), icon.bottom() + _ICON_TEXT_GAP,
                                rect.width(), _TEXT_H),
                         Qt.AlignHCenter | Qt.AlignVCenter, "加载失败")

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt 回调
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        radius = self._radius_px()
        path = QPainterPath()
        path.addRoundedRect(rect, radius, radius)
        painter.setClipPath(path)

        if not self._failed and not self._pixmap.isNull():
            # 按 (宽, 高, DPR) 缓存缩放结果：悬停 / 重绘不重复做全图
            # SmoothTransformation 缩放（大图下开销显著）
            key = (self.width(), self.height(), self.devicePixelRatioF())
            if self._scaled_key != key:
                self._scaled = self._pixmap.scaled(
                    self.size(), Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation
                )
                self._scaled_key = key
            scaled = self._scaled
            painter.drawPixmap(
                (self.width() - scaled.width()) // 2,
                (self.height() - scaled.height()) // 2,
                scaled,
            )
        else:
            self._draw_placeholder(painter, rect)

        # 悬停预览蒙层
        if self._hovered and not self._failed:
            painter.fillRect(rect, QColor(T("color.overlay")))
            # 蒙层前景：overlay 在亮 / 暗主题下均使画面变暗，前景需保持浅色。
            # 令牌体系没有 on.overlay 前景令牌：亮色取 on.primary（#FFFFFF，
            # 与历史渲染一致）；暗色 on.primary 为深色（#101319，压在黑色
            # 遮罩上不可见），改取 text.primary（暗色主文字即浅色）。
            fg = QColor(T("color.on.primary")
                        if ThemeManager.instance().mode != "dark"
                        else T("color.text.primary"))
            font = painter.font()
            font.setPixelSize(T("font.xs"))
            painter.setFont(font)
            top = self._group_top(rect, _LENS_D, _TEXT_H)
            cx, cy = rect.center().x(), top + _LENS_D / 2
            pen = QPen(fg, _LENS_W)
            pen.setCapStyle(Qt.RoundCap)
            painter.setPen(pen)
            painter.setBrush(Qt.NoBrush)
            painter.drawEllipse(QRectF(cx - _LENS_D / 2 + 1, cy - _LENS_D / 2 + 1,
                                       _LENS_D - 2, _LENS_D - 2))
            handle = _LENS_D / 2 - 2
            painter.drawLine(int(cx + handle), int(cy + handle),
                             int(cx + handle + _ICON_TEXT_GAP),
                             int(cy + handle + _ICON_TEXT_GAP))
            painter.drawText(QRectF(rect.left(), cy + _LENS_D / 2 + _ICON_TEXT_GAP,
                                    rect.width(), _TEXT_H),
                             Qt.AlignHCenter | Qt.AlignVCenter, "预览")
        painter.end()