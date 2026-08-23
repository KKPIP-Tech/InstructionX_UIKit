# -*- coding: utf-8 -*-
"""时间轴组件（SPEC §5.2 timeline）。

竖向时间轴，节点可自定义颜色 / 图标，尾部支持 pending
（虚线 + 空心节点）。完全自绘，亮 / 暗主题实时感知。
绘制参数（轴线侧、线宽线型、节点半径、行距、字号）均可公开调节。
"""

from PySide6.QtCore import QRect, QSize, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPen
from PySide6.QtWidgets import QWidget

from InstructionX_UIKit.theme import T, ThemeManager

__all__ = ["Timeline"]

_DOT_X = 16      # 节点圆心 x（轴线在左）
_TEXT_X = 36     # 文本起始 x（轴线在左）
_PAD_Y = 10      # 上下内边距
_DOT_R = 5       # 节点半径
_AXIS_SIDES = ("left", "right")


class Timeline(QWidget):
    """竖向时间轴。

    参数:
        pending: 尾部 pending 文本；``None`` 不显示，默认 None。
        parent: 父控件。

    示例::

        tl = Timeline(pending="进行中")
        tl.add_item("创建订单", time="09:30")
        tl.add_item("支付成功", time="09:32", color="success")
        tl.set_axis_side("right")
        tl.set_dot(6)
    """

    def __init__(self, pending: str = None, parent=None):
        super().__init__(parent)
        self._items = []  # [{"text","time","color","icon"}]
        self._pending = pending
        # 绘制参数（均可经公开 setter 调节）
        self._axis_side = "left"
        self._line_width = 1.0
        self._line_style = Qt.SolidLine
        self._dot_radius = _DOT_R
        self._extra_spacing = 0
        self._title_font_size = None
        self._time_font_size = None
        ThemeManager.instance().theme_changed.connect(self.update)

    # ------------------------------------------------------------------ 数据
    def add_item(self, text: str, time: str = "", color: str = None, icon: QIcon = None) -> None:
        """追加节点。

        参数:
            text: 主文本。
            time: 次级时间文本（可选）。
            color: 语义色名（primary/success/warning/danger）或 QColor；
                   缺省为 primary。
            icon: 自定义节点图标（替代圆点）。
        """
        self._items.append({"text": str(text), "time": str(time),
                            "color": color, "icon": icon})
        self.updateGeometry()
        self.update()

    def clear(self) -> None:
        """清空全部节点。"""
        self._items.clear()
        self.updateGeometry()
        self.update()

    def items(self):
        return list(self._items)

    def set_pending(self, text: str = None) -> None:
        """设置 / 清除尾部 pending 文本。"""
        self._pending = text
        self.updateGeometry()
        self.update()

    def pending(self):
        return self._pending

    # -------------------------------------------------------------- 绘制参数
    def set_axis_side(self, side: str) -> None:
        """设置轴线位置：``"left"``（默认）或 ``"right"``。"""
        if side not in _AXIS_SIDES:
            raise ValueError(
                f"未知轴线位置: {side!r}，应为 {_AXIS_SIDES} 之一")
        self._axis_side = side
        self.update()

    def set_line(self, width: float = 1.0, style=Qt.SolidLine) -> None:
        """设置节点间连接线宽度与线型。"""
        self._line_width = float(width)
        self._line_style = style
        self.update()

    def set_dot(self, radius: int) -> None:
        """设置节点圆点半径（px）。"""
        if radius <= 0:
            raise ValueError(f"节点半径必须为正: {radius!r}")
        self._dot_radius = int(radius)
        self.update()

    def set_row_spacing(self, px: int) -> None:
        """设置每行附加间距（px，追加到行高之上）。"""
        self._extra_spacing = int(px)
        self.updateGeometry()
        self.update()

    def set_fonts(self, title_size: int = None, time_size: int = None) -> None:
        """设置主文本 / 时间文本字号（px）；``None`` 保持令牌默认。"""
        if title_size is not None:
            self._title_font_size = int(title_size)
        if time_size is not None:
            self._time_font_size = int(time_size)
        self.update()

    # ------------------------------------------------------------------ 几何
    def _row_height(self, item) -> int:
        base = 46 if item["time"] else 30
        return base + self._extra_spacing

    def _content_height(self) -> int:
        h = sum(self._row_height(it) for it in self._items)
        if self._pending:
            h += 48
        return h + _PAD_Y * 2

    def sizeHint(self) -> QSize:
        return QSize(280, self._content_height())

    def minimumSizeHint(self) -> QSize:
        return QSize(160, self._content_height())

    # ------------------------------------------------------------------ 绘制
    def _color_of(self, item) -> QColor:
        color = item["color"]
        if isinstance(color, QColor):
            return color
        key = f"color.{color}" if color else "color.primary"
        try:
            return QColor(T(key))
        except KeyError:
            return QColor(T("color.primary"))

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        line_color = QColor(T("color.border"))
        text_primary = QColor(T("color.text.primary"))
        text_tertiary = QColor(T("color.text.tertiary"))

        font_text = painter.font()
        font_text.setPixelSize(self._title_font_size or T("font.md"))
        font_time = painter.font()
        font_time.setPixelSize(self._time_font_size or T("font.xs"))

        right = self._axis_side == "right"
        w = self.width()
        dot_x = w - _DOT_X if right else _DOT_X
        r = self._dot_radius
        align = (Qt.AlignVCenter | Qt.AlignRight) if right \
            else (Qt.AlignVCenter | Qt.AlignLeft)

        def text_rect(y, h):
            if right:
                return QRect(8, y, dot_x - 20, h)
            return QRect(_TEXT_X, y, w - _TEXT_X - 8, h)

        y = _PAD_Y
        prev_dot_y = None
        for item in self._items:
            row_h = self._row_height(item)
            dot_y = y + 11
            # 与上一节点的连接线
            if prev_dot_y is not None:
                painter.setPen(QPen(line_color, self._line_width,
                                    self._line_style))
                painter.drawLine(dot_x, prev_dot_y, dot_x, dot_y)
            # 节点
            icon = item["icon"]
            if isinstance(icon, QIcon) and not icon.isNull():
                painter.fillRect(QRect(dot_x - 7, dot_y - 7, 14, 14),
                                 QColor(T("color.bg.base")))
                icon.paint(painter, QRect(dot_x - 7, dot_y - 7, 14, 14))
            else:
                painter.setPen(Qt.NoPen)
                painter.setBrush(self._color_of(item))
                painter.drawEllipse(dot_x - r, dot_y - r, r * 2, r * 2)
            # 文本
            painter.setFont(font_text)
            painter.setPen(text_primary)
            painter.drawText(text_rect(y, 22), align, item["text"])
            if item["time"]:
                painter.setFont(font_time)
                painter.setPen(text_tertiary)
                painter.drawText(text_rect(y + 22, 16), align, item["time"])
            prev_dot_y = dot_y
            y += row_h

        # 尾部 pending：虚线 + 空心节点
        if self._pending:
            dot_y = y + 30
            painter.setPen(QPen(line_color, self._line_width, Qt.DashLine))
            start_y = prev_dot_y if prev_dot_y is not None else y
            painter.drawLine(dot_x, start_y, dot_x, dot_y)
            painter.setPen(QPen(QColor(T("color.primary")), 1.5))
            painter.setBrush(QColor(T("color.bg.base")))
            painter.drawEllipse(dot_x - r, dot_y - r, r * 2, r * 2)
            painter.setFont(font_text)
            painter.setPen(text_tertiary)
            painter.drawText(text_rect(dot_y - 11, 22), align,
                             str(self._pending))
        painter.end()
