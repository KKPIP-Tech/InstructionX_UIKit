# -*- coding: utf-8 -*-
"""时间轴组件（SPEC §5.2 timeline）。

竖向时间轴，节点可自定义颜色 / 图标，尾部支持 pending
（虚线 + 空心节点）。完全自绘，亮 / 暗主题实时感知。
"""

from PySide6.QtCore import QRect, QSize, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPen
from PySide6.QtWidgets import QWidget

from InstructionX_UIKit.theme import T, ThemeManager

__all__ = ["Timeline"]

_DOT_X = 16      # 节点圆心 x
_TEXT_X = 36     # 文本起始 x
_PAD_Y = 10      # 上下内边距
_DOT_R = 5       # 节点半径


class Timeline(QWidget):
    """竖向时间轴。

    参数:
        pending: 尾部 pending 文本；``None`` 不显示，默认 None。
        parent: 父控件。

    示例::

        tl = Timeline(pending="进行中")
        tl.add_item("创建订单", time="09:30")
        tl.add_item("支付成功", time="09:32", color="success")
    """

    def __init__(self, pending: str = None, parent=None):
        super().__init__(parent)
        self._items = []  # [{"text","time","color","icon"}]
        self._pending = pending
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

    # ------------------------------------------------------------------ 几何
    @staticmethod
    def _row_height(item) -> int:
        return 46 if item["time"] else 30

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
        font_text.setPixelSize(T("font.md"))
        font_time = painter.font()
        font_time.setPixelSize(T("font.xs"))

        y = _PAD_Y
        prev_dot_y = None
        for item in self._items:
            row_h = self._row_height(item)
            dot_y = y + 11
            # 与上一节点的连接线
            if prev_dot_y is not None:
                painter.setPen(QPen(line_color, 1))
                painter.drawLine(_DOT_X, prev_dot_y, _DOT_X, dot_y)
            # 节点
            icon = item["icon"]
            if isinstance(icon, QIcon) and not icon.isNull():
                painter.fillRect(QRect(_DOT_X - 7, dot_y - 7, 14, 14),
                                 QColor(T("color.bg.base")))
                icon.paint(painter, QRect(_DOT_X - 7, dot_y - 7, 14, 14))
            else:
                painter.setPen(Qt.NoPen)
                painter.setBrush(self._color_of(item))
                painter.drawEllipse(_DOT_X - _DOT_R, dot_y - _DOT_R,
                                    _DOT_R * 2, _DOT_R * 2)
            # 文本
            painter.setFont(font_text)
            painter.setPen(text_primary)
            painter.drawText(QRect(_TEXT_X, y, self.width() - _TEXT_X - 8, 22),
                             Qt.AlignVCenter | Qt.AlignLeft, item["text"])
            if item["time"]:
                painter.setFont(font_time)
                painter.setPen(text_tertiary)
                painter.drawText(QRect(_TEXT_X, y + 22, self.width() - _TEXT_X - 8, 16),
                                 Qt.AlignVCenter | Qt.AlignLeft, item["time"])
            prev_dot_y = dot_y
            y += row_h

        # 尾部 pending：虚线 + 空心节点
        if self._pending:
            dot_y = y + 30
            pen = QPen(line_color, 1, Qt.DashLine)
            painter.setPen(pen)
            start_y = prev_dot_y if prev_dot_y is not None else y
            painter.drawLine(_DOT_X, start_y, _DOT_X, dot_y)
            painter.setPen(QPen(QColor(T("color.primary")), 1.5))
            painter.setBrush(QColor(T("color.bg.base")))
            painter.drawEllipse(_DOT_X - _DOT_R, dot_y - _DOT_R,
                                _DOT_R * 2, _DOT_R * 2)
            painter.setFont(font_text)
            painter.setPen(text_tertiary)
            painter.drawText(QRect(_TEXT_X, dot_y - 11, self.width() - _TEXT_X - 8, 22),
                             Qt.AlignVCenter | Qt.AlignLeft, str(self._pending))
        painter.end()
