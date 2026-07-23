# -*- coding: utf-8 -*-
"""头像组件（SPEC §5.2 avatar）。

圆形 / 方形头像，支持图片、图标、文字三种来源，图片加载失败时
自动回退到图标或文字；自绘实现，亮 / 暗主题实时感知。
"""

from PySide6.QtCore import QRect, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPixmap
from PySide6.QtWidgets import QLabel

from InstructionX_UIKit.theme import T, ThemeManager, set_property

__all__ = ["Avatar"]

#: 具名尺寸 -> 边长（px）
_SIZE_PX = {"sm": 24, "md": 32, "lg": 40}

#: 文字头像的候选底色（语义令牌键）
_PALETTE_KEYS = (
    "color.primary",
    "color.success",
    "color.warning",
    "color.danger",
    "color.primary.hover",
    "color.success.hover",
)


class Avatar(QLabel):
    """圆形 / 方形头像。

    参数:
        text: 文字来源（取首字符显示），图片 / 图标缺失时的回退。
        size: ``"sm"`` / ``"md"`` / ``"lg"`` 或整数边长（px）。
        shape: ``"circle"``（默认）或 ``"square"``（圆角方形）。
        parent: 父控件。

    示例::

        avatar = Avatar("张三", size="lg")
        avatar.set_image("me.png")      # 图片优先
        avatar.set_shape("square")      # 切为圆角方形
    """

    def __init__(self, text: str = "", size="md", shape: str = "circle", parent=None):
        super().__init__(parent)
        self._text = ""
        self._shape = "circle"
        self._pixmap = QPixmap()
        self._icon = QIcon()
        self._side = _SIZE_PX["md"]
        self.set_text(text)
        self.set_shape(shape)
        self.set_size(size)
        ThemeManager.instance().theme_changed.connect(self.update)

    # ------------------------------------------------------------------ 配置
    def set_size(self, size) -> None:
        """设置尺寸：具名 sm/md/lg 或整数边长（px）。"""
        if isinstance(size, str):
            if size not in _SIZE_PX:
                raise ValueError(f"未知头像尺寸: {size!r}")
            set_property(self, "size", size)
            self._side = _SIZE_PX[size]
        else:
            self._side = max(8, int(size))
        self.setFixedSize(self._side, self._side)
        self.update()

    def side(self) -> int:
        """当前边长（px）。"""
        return self._side

    def set_shape(self, shape: str) -> None:
        """设置形状：``"circle"`` 或 ``"square"``。"""
        if shape not in ("circle", "square"):
            raise ValueError(f"未知头像形状: {shape!r}")
        self._shape = shape
        self.update()

    def shape(self) -> str:
        return self._shape

    def set_text(self, text: str) -> None:
        """设置文字来源（显示首字符）。"""
        self._text = text or ""
        self.update()

    def text(self) -> str:
        return self._text

    def set_image(self, source) -> None:
        """设置图片来源：路径或 QPixmap；加载失败自动回退文字 / 图标。"""
        if isinstance(source, QPixmap):
            self._pixmap = source
        else:
            self._pixmap = QPixmap(str(source))
        self.update()

    def set_icon(self, icon: QIcon) -> None:
        """设置图标来源（图片缺失时的次级回退）。"""
        self._icon = icon
        self.update()

    # ------------------------------------------------------------------ 绘制
    def _clip_path(self, rect: QRectF) -> QPainterPath:
        path = QPainterPath()
        if self._shape == "circle":
            path.addEllipse(rect)
        else:
            path.addRoundedRect(rect, T("radius.md"), T("radius.md"))
        return path

    def _bg_color(self) -> QColor:
        """文字头像底色：由名字哈希在语义色板中取值（主题感知）。"""
        key = _PALETTE_KEYS[hash(self._text) % len(_PALETTE_KEYS)]
        return QColor(T(key))

    def paintEvent(self, event) -> None:
        side = self._side
        rect = QRectF(0.5, 0.5, side - 1.0, side - 1.0)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        path = self._clip_path(rect)

        if not self._pixmap.isNull():
            painter.setClipPath(path)
            scaled = self._pixmap.scaled(
                side, side, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation
            )
            painter.drawPixmap(
                (side - scaled.width()) // 2, (side - scaled.height()) // 2, scaled
            )
            painter.end()
            return

        if not self._icon.isNull():
            painter.fillPath(path, QColor(T("color.bg.muted")))
            edge = int(side * 0.6)
            self._icon.paint(
                painter, QRect((side - edge) // 2, (side - edge) // 2, edge, edge)
            )
            painter.end()
            return

        if self._text:
            painter.fillPath(path, self._bg_color())
            painter.setPen(QColor(T("color.on.primary")))
            font = painter.font()
            font.setPixelSize(max(10, int(side * 0.42)))
            font.setBold(True)
            painter.setFont(font)
            painter.drawText(rect, Qt.AlignCenter, self._text[0])
            painter.end()
            return

        # 空头像：默认人物剪影（头 + 肩）
        painter.fillPath(path, QColor(T("color.bg.muted")))
        painter.setClipPath(path)
        fg = QColor(T("color.text.tertiary"))
        painter.setBrush(fg)
        painter.setPen(Qt.NoPen)
        head_r = side * 0.18
        painter.drawEllipse(
            QRectF(side / 2 - head_r, side * 0.22, head_r * 2, head_r * 2)
        )
        body_w = side * 0.62
        painter.drawEllipse(
            QRectF(side / 2 - body_w / 2, side * 0.56, body_w, side * 0.7)
        )
        painter.end()
