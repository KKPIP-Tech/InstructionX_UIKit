# -*- coding: utf-8 -*-
"""时间轴组件（SPEC §5.2 timeline）。

竖向时间轴，节点可自定义颜色 / 图标，尾部支持 pending
（虚线 + 空心节点）。完全自绘，亮 / 暗主题实时感知。
绘制参数（轴线侧、线宽线型、节点半径、行距、字号）均可公开调节。

共线要点（本轨重点）：

- **节点圆点 / 连接线 / 首行文字共用一条中线**：节点圆心取首行文字行的
  垂直中线（``y + title_line_h // 2``），连接线又从上一个圆心连到下一个
  圆心，三者天然在同一条水平中线上。行高是算出来的（按字号度量取下限）
  而不是写死的魔数，改字号时圆点不会相对文字漂移。
- **1px 连接线关掉抗锯齿**：抗锯齿下 1px 线会被摊到相邻两个像素、各占
  一半，看起来是一根发灰的淡线；关掉后是干净的 1px，与表格分隔线同级。
- 全部横向位置（轴线 x、文本 x、右轴镜像、右内边距）取自令牌，右轴模式
  与左轴模式的文本留白完全对称。
"""

from PySide6.QtCore import QRect, QSize, Qt
from PySide6.QtGui import QColor, QFont, QFontMetrics, QIcon, QPainter, QPen
from PySide6.QtWidgets import QWidget

from InstructionX_UIKit.theme import T, ThemeManager

__all__ = ["Timeline"]

#: 轴线 / 节点圆心 x（space.4 = 16px）
_AXIS_X = T("space.4")
#: 文本起始 x = 轴线 + space.5（16 + 20 = 36px），与轴线保持一格留白
_TEXT_X = _AXIS_X + T("space.5")
#: 控件左右内边距（space.2）
_PAD_X = T("space.2")
#: 上下内边距（space.2）
_PAD_Y = T("space.2")
#: 单行文字行高下限（space.6 = 24px）与时间行下限（space.4 = 16px）
_LINE_TITLE = T("space.6")
_LINE_TIME = T("space.4")
#: 节点半径（px）：直径 10px ≈ 一行正文字高，圆点与首行文字视觉等重
_DOT_R = 5
#: 节点图标边长（px）
_ICON = 14
#: 最小宽度 / 建议宽度（令牌推导）
_MIN_W = T("space.16") * 2 + T("space.8")
_HINT_W = _MIN_W + T("space.16")
_AXIS_SIDES = ("left", "right")


def _even(value: int) -> int:
    """向上取偶数：行高落回 2px 基网格（契约 §2）。"""
    return value + value % 2


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
        self.updateGeometry()
        self.update()

    # ------------------------------------------------------------------ 字体
    def _title_font(self) -> QFont:
        font = QFont(self.font())
        font.setPixelSize(self._title_font_size or T("font.md"))
        return font

    def _time_font(self) -> QFont:
        font = QFont(self.font())
        font.setPixelSize(self._time_font_size or T("font.xs"))
        return font

    # ------------------------------------------------------------------ 几何
    def _line_heights(self) -> tuple:
        """（标题行高, 时间行高）——按字号度量，随字号变化失效后重算。

        缓存的原因：``_dot_center`` / ``_row_height`` 每个节点都会问到行高，
        不缓存的话一次重绘要构造 2×N 个 QFontMetrics（长时间轴直接可见）。
        """
        key = (self._title_font_size, self._time_font_size)
        if getattr(self, "_line_h_key", None) != key:
            self._line_h_key = key
            self._line_h = (
                self._compute_line_h(self._title_font_size, T("font.md"), _LINE_TITLE),
                self._compute_line_h(self._time_font_size, T("font.xs"), _LINE_TIME),
            )
        return self._line_h

    def _compute_line_h(self, font_size, default: int, floor: int) -> int:
        font = QFont(self.font())
        font.setPixelSize(font_size or default)
        need = QFontMetrics(font).height() + T("space.05")
        return _even(max(floor, need))

    def _line_title_h(self) -> int:
        """首行文字行高：令牌下限与实际字号度量取大，再取偶。"""
        return self._line_heights()[0]

    def _line_time_h(self) -> int:
        return self._line_heights()[1]

    def _row_height(self, item) -> int:
        h = self._line_title_h()
        if item["time"]:
            h += self._line_time_h()
        return h + self._extra_spacing

    def _content_height(self) -> int:
        h = sum(self._row_height(it) for it in self._items)
        if self._pending:
            h += self._line_title_h()
        return h + _PAD_Y * 2

    def sizeHint(self) -> QSize:
        return QSize(_HINT_W, self._content_height())

    def minimumSizeHint(self) -> QSize:
        return QSize(_MIN_W, self._content_height())

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

    def _dot_center(self, y: int) -> int:
        """节点圆心 y = 首行文字行的垂直中线（与文字共用一条中线）。"""
        return y + self._line_title_h() // 2

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt 回调
        painter = QPainter(self)
        line_color = QColor(T("color.border"))
        text_primary = QColor(T("color.text.primary"))
        text_tertiary = QColor(T("color.text.tertiary"))

        font_title = self._title_font()
        font_time = self._time_font()
        title_h = self._line_title_h()
        time_h = self._line_time_h()

        right = self._axis_side == "right"
        w = self.width()
        dot_x = w - _AXIS_X if right else _AXIS_X
        r = self._dot_radius
        align = (Qt.AlignVCenter | Qt.AlignRight) if right \
            else (Qt.AlignVCenter | Qt.AlignLeft)

        def text_rect(y, h):
            """文本行矩形：左右轴镜像，留白完全对称。

            文字起点必须让开节点圆点：圆点横跨 ``[_AXIS_X - r, _AXIS_X + r]``，
            文字从 ``_TEXT_X``（= ``_AXIS_X + space.5``）起，留出 space.5 的净空。
            右轴镜像：文字右缘落在 ``w - _TEXT_X``，与左轴同一条基准线。
            """
            if right:
                return QRect(0, y, max(0, w - _TEXT_X), h)
            return QRect(_TEXT_X, y, max(0, w - _TEXT_X - _PAD_X), h)

        # ---- 连接线（1px 直角线，不开抗锯齿）----
        painter.setRenderHint(QPainter.Antialiasing, False)
        y = _PAD_Y
        prev_dot_y = None
        dots = []  # 收集圆心，文本在第二遍统一绘制，避免线压住文字
        for item in self._items:
            dot_y = self._dot_center(y)
            if prev_dot_y is not None:
                painter.setPen(QPen(line_color, self._line_width,
                                    self._line_style))
                painter.drawLine(dot_x, prev_dot_y, dot_x, dot_y)
            dots.append((item, y, dot_y))
            prev_dot_y = dot_y
            y += self._row_height(item)

        pending_y = None
        if self._pending:
            pending_y = self._dot_center(y)
            painter.setPen(QPen(line_color, self._line_width, Qt.DashLine))
            start_y = prev_dot_y if prev_dot_y is not None else y
            painter.drawLine(dot_x, start_y, dot_x, pending_y)

        # ---- 节点 ----
        painter.setRenderHint(QPainter.Antialiasing, True)
        for item, _row_y, dot_y in dots:
            icon = item["icon"]
            if isinstance(icon, QIcon) and not icon.isNull():
                box = QRect(dot_x - _ICON // 2, dot_y - _ICON // 2, _ICON, _ICON)
                painter.fillRect(box, QColor(T("color.bg.base")))
                icon.paint(painter, box)
            else:
                painter.setPen(Qt.NoPen)
                painter.setBrush(self._color_of(item))
                painter.drawEllipse(dot_x - r, dot_y - r, r * 2, r * 2)
        if pending_y is not None:
            painter.setPen(QPen(QColor(T("color.primary")), 1.5))
            painter.setBrush(QColor(T("color.bg.base")))
            painter.drawEllipse(dot_x - r, pending_y - r, r * 2, r * 2)

        # ---- 文本 ----
        for item, row_y, _dot_y in dots:
            painter.setFont(font_title)
            painter.setPen(text_primary)
            painter.drawText(text_rect(row_y, title_h), align, item["text"])
            if item["time"]:
                painter.setFont(font_time)
                painter.setPen(text_tertiary)
                painter.drawText(text_rect(row_y + title_h, time_h), align,
                                 item["time"])
        if pending_y is not None:
            painter.setFont(font_title)
            painter.setPen(text_tertiary)
            painter.drawText(text_rect(pending_y - title_h // 2, title_h), align,
                             str(self._pending))
        painter.end()