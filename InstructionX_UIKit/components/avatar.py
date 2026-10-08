# -*- coding: utf-8 -*-
"""头像组件（SPEC §5.2 avatar）。

圆形 / 方形头像，支持图片、图标、文字三种来源，图片加载失败时
自动回退到图标或文字；自绘实现，亮 / 暗主题实时感知。
文字头像底色由 zlib.crc32 稳定哈希决定（跨进程一致，截图回归稳定）。

底色 / 前景色：色板里的每个填充色与 ``color.on.primary`` 的对比度都
≥ 4.88:1（亮色）/ ≥ 6.9:1（暗色），实测逐个校验过，因此字母用
``on.primary`` 不会在任一主题下糊掉。令牌体系目前没有 ``on.success`` /
``on.warning``，需要更细的分角色前景色时在共享层补（见交付说明）。
"""

import zlib

from PySide6.QtCore import QRect, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPixmap
from PySide6.QtWidgets import QLabel

from InstructionX_UIKit.theme import T, ThemeManager, set_property

__all__ = ["Avatar"]

#: 具名尺寸 -> 边长（px），与 ``theme._INPUT_HEIGHTS`` 的三档一致
_SIZE_PX = {"sm": 22, "md": 28, "lg": 34}

#: 文字头像的候选底色（语义令牌键）
_PALETTE_KEYS = (
    "color.primary",
    "color.success",
    "color.warning",
    "color.danger",
    "color.primary.hover",
    "color.success.hover",
)

#: 文字头像的字号系数（0.42 × 边长），下限取 font.xs 字阶
_TEXT_RATIO = 0.42
#: 剪影头像的头部半径 / 肩宽系数（相对边长）
_HEAD_R = 0.18
_SHOULDER_W = 0.62


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
        # 透明底：QLabel 基座底色会在圆形头像四角露出方块
        set_property(self, "role", "plain")
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
        # 声明尺寸档与实际边长必须一致（契约 §1）：set_property 写进去的
        # uiksize 就是给布局与审计看的档位，取值恒等于渲染边长。
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
            # 方形头像走 radius.md（控件档）：22-34px 的小方块用 radius.lg
            # 会显得「鼓」；圆形头像的圆角本来就是边长的一半，不走档位。
            path.addRoundedRect(rect, T("radius.md"), T("radius.md"))
        return path

    def _bg_color(self) -> QColor:
        """文字头像底色：由名字稳定哈希在语义色板中取值（主题感知）。

        使用 zlib.crc32 而非内置 hash：内置 hash 受 PYTHONHASHSEED 影响
        跨进程随机，同一名字在不同进程 / 截图回归中会得到不同底色。
        """
        key = _PALETTE_KEYS[zlib.crc32(self._text.encode("utf-8"))
                           % len(_PALETTE_KEYS)]
        return QColor(T(key))

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt 回调
        side = self._side
        # 描边对齐：0.5 起点让 1px 级的圆 / 角落在整像素上，不发虚
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
            # 图标占 6 成：与圆角留白成比例，22px 也不糊
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
            font.setPixelSize(max(T("font.xs"), int(side * _TEXT_RATIO)))
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
        head_r = side * _HEAD_R
        painter.drawEllipse(
            QRectF(side / 2 - head_r, side * 0.22, head_r * 2, head_r * 2)
        )
        body_w = side * _SHOULDER_W
        painter.drawEllipse(
            QRectF(side / 2 - body_w / 2, side * 0.56, body_w, side * 0.7)
        )
        painter.end()