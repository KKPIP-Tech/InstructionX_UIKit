# -*- coding: utf-8 -*-
"""步骤条 Steps（SPEC §5.3 steps.py）。

水平 / 垂直两种方向，节点状态 wait / process / finish / error，
连接线与节点全部自绘，paintEvent 实时读取主题令牌。
"""

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPen
from PySide6.QtWidgets import QWidget

from ..theme import T, ThemeManager
from shiboken6 import isValid as _shiboken_is_valid


def _connect_theme(widget, slot) -> None:
    """连接主题切换信号；控件销毁后自动忽略回调。"""
    ThemeManager.instance().theme_changed.connect(
        lambda *_: slot() if _shiboken_is_valid(widget) else None)

__all__ = ["Steps"]

_NODE_R = 12          # 节点半径
_NODE_D = _NODE_R * 2


class Steps(QWidget):
    """步骤条：展示任务流转进度。

    参数:
        orientation: ``Qt.Horizontal``（默认）或 ``Qt.Vertical``。
        parent: 父控件。

    示例::

        st = Steps()
        st.set_steps([("填写信息", ""), ("确认订单", ""), ("完成", "")])
        st.set_current(1)
    """

    #: 合法节点状态
    STATUSES = ("wait", "process", "finish", "error")

    def __init__(self, orientation=Qt.Horizontal, parent: QWidget = None):
        super().__init__(parent)
        self._orientation = orientation
        self._steps = []      # [{"title", "desc", "status"|None}]
        self._current = 0
        _connect_theme(self, self.update)
        self._refresh_minimum()

    # -- 公开 API ---------------------------------------------------------
    def set_steps(self, items) -> None:
        """设置步骤列表。

        每项可为 ``"标题"``、``("标题", "描述")`` 或
        ``{"title": ..., "description": ..., "status": ...}``。
        """
        self._steps = []
        for it in items:
            if isinstance(it, dict):
                self.add_step(it.get("title", ""),
                              it.get("description", ""),
                              it.get("status"))
            elif isinstance(it, (tuple, list)):
                self.add_step(it[0], it[1] if len(it) > 1 else "")
            else:
                self.add_step(str(it), "")
        self.set_current(self._current)

    def add_step(self, title: str, description: str = "",
                 status: str = None) -> None:
        """追加一个步骤；``status`` 为显式状态（可选）。"""
        if status is not None and status not in self.STATUSES:
            raise ValueError(f"未知步骤状态: {status!r}")
        self._steps.append({"title": str(title), "desc": str(description),
                            "status": status})
        self._refresh_minimum()
        self.update()

    def set_current(self, index: int) -> None:
        """设置当前步骤索引：之前为 finish，当前为 process，之后为 wait。"""
        if not self._steps:
            self._current = 0
            return
        self._current = max(0, min(int(index), len(self._steps) - 1))
        self.update()

    def current(self) -> int:
        return self._current

    def set_status(self, index: int, status: str) -> None:
        """显式设置某一步状态（覆盖按 current 推导的状态）。"""
        if status not in self.STATUSES:
            raise ValueError(
                f"未知步骤状态: {status!r}，应为 {self.STATUSES} 之一")
        self._steps[index]["status"] = status
        self.update()

    def status_of(self, index: int) -> str:
        """返回某一步的实际状态（显式优先，否则按 current 推导）。"""
        explicit = self._steps[index]["status"]
        if explicit:
            return explicit
        if index < self._current:
            return "finish"
        if index == self._current:
            return "process"
        return "wait"

    def sizeHint(self):
        hint = super().sizeHint()
        if self._orientation == Qt.Horizontal:
            hint.setHeight(80)
            hint.setWidth(max(320, len(self._steps) * 160))
        else:
            hint.setWidth(280)
            hint.setHeight(max(120, len(self._steps) * 64))
        return hint

    # -- 绘制 -------------------------------------------------------------
    def _refresh_minimum(self) -> None:
        if self._orientation == Qt.Horizontal:
            self.setMinimumHeight(80)
        else:
            self.setMinimumHeight(max(80, len(self._steps) * 64))

    def _colors(self, status: str):
        c = lambda k: QColor(T(f"color.{k}"))  # noqa: E731
        primary = c("primary")
        mapping = {
            "process": (primary, primary, c("on.primary"), c("text.primary")),
            "finish": (c("bg.elevated"), primary, primary, c("text.primary")),
            "wait": (c("bg.elevated"), c("border.strong"),
                     c("text.tertiary"), c("text.tertiary")),
            "error": (c("bg.elevated"), c("danger"), c("danger"), c("danger")),
        }
        return mapping[status]  # fill, border, glyph, title

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        if self._orientation == Qt.Horizontal:
            self._paint_horizontal(painter)
        else:
            self._paint_vertical(painter)
        painter.end()

    def _fonts(self):
        title_font = QFont(self.font())
        title_font.setPixelSize(T("font.md"))
        title_font.setWeight(QFont.DemiBold)
        desc_font = QFont(self.font())
        desc_font.setPixelSize(T("font.sm"))
        return title_font, desc_font

    def _paint_horizontal(self, p: QPainter) -> None:
        n = len(self._steps)
        if n == 0:
            return
        title_font, desc_font = self._fonts()
        seg = self.width() / n
        cy = 26.0
        for i, st in enumerate(self._steps):
            status = self.status_of(i)
            x0 = i * seg
            cx = x0 + _NODE_R + 4
            fm = QFontMetrics(title_font)
            title_w = fm.horizontalAdvance(st["title"])
            text_x = cx + _NODE_R + 8
            # 连接线（指向下一节点）
            if i < n - 1:
                x_start = text_x + title_w + 10
                x_end = (i + 1) * seg + 2
                if x_end > x_start:
                    color = T("color.primary") if status == "finish" \
                        else T("color.border")
                    pen = QPen(QColor(color))
                    pen.setWidthF(2.0)
                    p.setPen(pen)
                    p.drawLine(QPointF(x_start, cy), QPointF(x_end, cy))
            self._draw_node(p, cx, cy, status, i)
            self._draw_texts(p, st, status, text_x, cy, title_font, desc_font,
                             align_top=False)

    def _paint_vertical(self, p: QPainter) -> None:
        n = len(self._steps)
        if n == 0:
            return
        title_font, desc_font = self._fonts()
        row = max(56.0, self.height() / max(n, 1))
        cx = 20.0
        for i, st in enumerate(self._steps):
            status = self.status_of(i)
            cy = i * row + _NODE_R + 6
            if i < n - 1:
                y_start = cy + _NODE_R + 4
                y_end = (i + 1) * row + 6 - 4
                if y_end > y_start:
                    color = T("color.primary") if status == "finish" \
                        else T("color.border")
                    pen = QPen(QColor(color))
                    pen.setWidthF(2.0)
                    p.setPen(pen)
                    p.drawLine(QPointF(cx, y_start), QPointF(cx, y_end))
            self._draw_node(p, cx, cy, status, i)
            self._draw_texts(p, st, status, cx + _NODE_R + 10, cy,
                             title_font, desc_font, align_top=False)

    def _draw_node(self, p: QPainter, cx: float, cy: float,
                   status: str, index: int) -> None:
        fill, border, glyph, _title = self._colors(status)
        rect = QRectF(cx - _NODE_R, cy - _NODE_R, _NODE_D, _NODE_D)
        p.setBrush(fill)
        pen = QPen(border)
        pen.setWidthF(1.6)
        p.setPen(pen)
        p.drawEllipse(rect)
        if status == "finish":
            pen = QPen(glyph)
            pen.setWidthF(1.8)
            pen.setCapStyle(Qt.RoundCap)
            pen.setJoinStyle(Qt.RoundJoin)
            p.setPen(pen)
            p.drawPolyline([
                QPointF(cx - 5.0, cy + 0.5),
                QPointF(cx - 1.5, cy + 4.0),
                QPointF(cx + 5.5, cy - 3.5),
            ])
        elif status == "error":
            pen = QPen(glyph)
            pen.setWidthF(1.8)
            pen.setCapStyle(Qt.RoundCap)
            p.setPen(pen)
            p.drawLine(QPointF(cx - 3.5, cy - 3.5), QPointF(cx + 3.5, cy + 3.5))
            p.drawLine(QPointF(cx + 3.5, cy - 3.5), QPointF(cx - 3.5, cy + 3.5))
        else:
            font = QFont(self.font())
            font.setPixelSize(T("font.sm"))
            font.setWeight(QFont.DemiBold)
            p.setFont(font)
            p.setPen(glyph)
            p.drawText(rect, Qt.AlignCenter, str(index + 1))

    def _draw_texts(self, p: QPainter, st: dict, status: str, x: float,
                    cy: float, title_font: QFont, desc_font: QFont,
                    align_top: bool = False) -> None:
        _fill, _border, _glyph, title_color = self._colors(status)
        fm = QFontMetrics(title_font)
        title_h = fm.height()
        # 标题
        p.setFont(title_font)
        p.setPen(title_color)
        title_rect = QRectF(x, cy - title_h / 2, max(10, self.width() - x - 4),
                            title_h)
        p.drawText(title_rect, Qt.AlignLeft | Qt.AlignVCenter, st["title"])
        # 描述
        if st["desc"]:
            p.setFont(desc_font)
            p.setPen(QColor(T("color.text.tertiary")))
            dy = cy + title_h / 2 + 3
            desc_rect = QRectF(x, dy, max(10, self.width() - x - 4),
                               QFontMetrics(desc_font).height())
            p.drawText(desc_rect, Qt.AlignLeft | Qt.AlignVCenter, st["desc"])
