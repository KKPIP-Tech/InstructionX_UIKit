# -*- coding: utf-8 -*-
"""步骤条 Steps（SPEC §5.3 steps.py）。

水平 / 垂直两种方向，节点状态 wait / process / finish / error，
连接线与节点全部自绘，paintEvent 实时读取主题令牌。

几何契约（本组件的自检要点）：

1. **共线**：节点圆心、连接线中线、标题+描述整块文本的视觉中心，三者
   落在同一条水平线上（垂直方向为竖线），画的时候以 ``cy`` 为唯一基准；
2. **递进**：``sm`` / ``md`` / ``lg`` 三档，节点直径 16 / 20 / 24px、
   连接线 1 / 2 / 3px、标题字号 12 / 13 / 14px，等比递进而非随手取值；
3. **不越界**：每段文本宽度被裁到「段宽 - 节点直径 - 间距」，超长省略，
   文字不会压到下一个节点上。

状态配色与 Tabs / NavMenu / Pagination 共用同一套语义：
``process`` = 当前（primary + 半粗），``finish`` = 已完成，
``wait`` = 未到达（tertiary），``error`` = 出错（danger）。
"""

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPen
from PySide6.QtWidgets import QWidget

from ..theme import T, ThemeManager, set_property
from shiboken6 import isValid as _shiboken_is_valid


def _connect_theme(widget, slot) -> None:
    """连接主题切换信号；组件销毁时断开连接（shiboken 守卫双保险）。"""
    manager = ThemeManager.instance()
    receiver = lambda *_: slot() if _shiboken_is_valid(widget) else None
    manager.theme_changed.connect(receiver)

    def _cleanup(_obj=None):
        try:
            manager.theme_changed.disconnect(receiver)
        except (RuntimeError, TypeError):
            pass

    widget.destroyed.connect(_cleanup)

__all__ = ["Steps"]

#: 尺寸档 -> (节点直径, 连接线宽, 标题字号, 描述字号, 每段最小宽)
#: 三档等比递进：直径 16→20→24、线宽 1→2→3、字号 12→13→14。
_SIZE_SPEC = {
    "sm": {"d": 16, "link": 1, "title": 12, "desc": 11, "seg": 96},
    "md": {"d": 20, "link": 2, "title": 13, "desc": 12, "seg": 128},
    "lg": {"d": 24, "link": 3, "title": 14, "desc": 13, "seg": 160},
}
#: 节点与文字之间的间距
_TEXT_GAP = 6
#: 标题与描述之间的行距（2px 基网格）
_DESC_GAP = 4
#: 内容区上下留白
_PAD_V = 8
#: 垂直方向：节点中心线左侧的留白
_PAD_H = 12


class Steps(QWidget):
    """步骤条：展示任务流转进度。

    参数:
        orientation: ``Qt.Horizontal``（默认）或 ``Qt.Vertical``。
        parent: 父控件。

    示例::

        st = Steps()
        st.set_size("sm")
        st.set_steps([("填写信息", ""), ("确认订单", ""), ("完成", "")])
        st.set_current(1)
    """

    #: 合法节点状态
    STATUSES = ("wait", "process", "finish", "error")
    #: 合法尺寸档
    SIZES = tuple(_SIZE_SPEC)

    def __init__(self, orientation=Qt.Horizontal, parent: QWidget = None):
        super().__init__(parent)
        self._orientation = orientation
        self._steps = []      # [{"title", "desc", "status"|None}]
        self._current = 0
        self._size = "md"
        # 绘制参数（均可经公开 setter 调节）。注意：尺寸档存为普通属性而
        # **不**写 ``uiksize`` 动态属性——Steps 是容器，它的高度由内容与
        # 方向决定（契约 §1 的 22/28/34 是输入控件刻度），挂 uiksize 会让
        # 审计按「输入控件」口径误判高度。
        spec = _SIZE_SPEC[self._size]
        self._node_r = spec["d"] // 2
        self._link_width = float(spec["link"])
        self._link_style = Qt.SolidLine
        self._title_font_size = None
        self._desc_font_size = None
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

    def steps(self) -> list:
        """返回步骤列表的归一化副本（``[{"title", "desc", "status"}]``）。"""
        return [dict(st) for st in self._steps]

    def orientation(self):
        """返回当前方向（Qt.Horizontal / Qt.Vertical）。"""
        return self._orientation

    # -------------------------------------------------------------- 绘制参数
    def set_size(self, size: str) -> None:
        """设置尺寸档 ``"sm"`` / ``"md"`` / ``"lg"``（默认 ``"md"``）。

        切档会同时重算节点直径、连接线粗细与字号——三者必须成套变化，
        单独改其中一项就会出现「圆点变大但线还是 1px」的比例失衡。
        ``set_node`` / ``set_link`` 的显式调用仍可覆盖档位默认值。
        """
        if size not in _SIZE_SPEC:
            raise ValueError(
                f"未知步骤尺寸: {size!r}，应为 {self.SIZES} 之一")
        if size == self._size:
            return
        self._size = size
        spec = _SIZE_SPEC[size]
        self._node_r = spec["d"] // 2
        self._link_width = float(spec["link"])
        # 尺寸档用独立属性名暴露，不占用 uiksize（原因见 __init__ 注释）
        set_property(self, "stepsize", size)
        self._refresh_minimum()
        self.update()

    def size_name(self) -> str:
        """返回当前尺寸档。"""
        return self._size

    def set_node(self, radius: int) -> None:
        """设置节点圆点半径（px，默认随尺寸档为 10）。"""
        if radius <= 0:
            raise ValueError(f"节点半径必须为正: {radius!r}")
        self._node_r = int(radius)
        self._refresh_minimum()
        self.update()

    def set_link(self, width: float = 2.0, style=Qt.SolidLine) -> None:
        """设置连接线宽度与线型。"""
        self._link_width = float(width)
        self._link_style = style
        self.update()

    def set_fonts(self, title_size: int = None, desc_size: int = None) -> None:
        """设置标题 / 描述字号（px）；``None`` 保持尺寸档默认。"""
        if title_size is not None:
            self._title_font_size = int(title_size)
        if desc_size is not None:
            self._desc_font_size = int(desc_size)
        self._refresh_minimum()
        self.update()

    def set_status(self, index: int, status: str) -> None:
        """显式设置某一步状态（覆盖按 current 推导的状态）。"""
        if status not in self.STATUSES:
            raise ValueError(
                f"未知步骤状态: {status!r}，应为 {self.STATUSES} 之一")
        self._steps[index]["status"] = status
        self.update()

    def clear_status(self, index: int) -> None:
        """清除某一步的显式状态（恢复按 current 推导）。"""
        self._steps[index]["status"] = None
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

    # ------------------------------------------------------------ 尺寸计算
    def _spec(self) -> dict:
        return _SIZE_SPEC[self._size]

    def _title_font(self) -> QFont:
        font = QFont(self.font())
        font.setPixelSize(self._title_font_size or self._spec()["title"])
        font.setWeight(QFont.DemiBold)
        return font

    def _desc_font(self) -> QFont:
        font = QFont(self.font())
        font.setPixelSize(self._desc_font_size or self._spec()["desc"])
        return font

    def _text_block_h(self) -> int:
        """标题 + 描述整块的高度（无描述时退化为标题高）。"""
        title_h = QFontMetrics(self._title_font()).height()
        if not any(st["desc"] for st in self._steps):
            return title_h
        desc_h = QFontMetrics(self._desc_font()).height()
        return title_h + _DESC_GAP + desc_h

    def _content_h(self) -> int:
        """一「行」步骤所需的高度（节点与文本块取大者 + 上下留白）。"""
        return max(2 * self._node_r, self._text_block_h()) + 2 * _PAD_V

    def sizeHint(self):
        spec = self._spec()
        n = max(1, len(self._steps))
        hint = super().sizeHint()
        if self._orientation == Qt.Horizontal:
            hint.setHeight(self._content_h())
            hint.setWidth(max(spec["seg"] * 2, n * spec["seg"]))
        else:
            hint.setWidth(T("layout.sidebar.w") // 2)
            hint.setHeight(max(self._content_h(), n * self._content_h()))
        return hint

    def _refresh_minimum(self) -> None:
        n = max(1, len(self._steps))
        h = self._content_h()
        if self._orientation == Qt.Horizontal:
            self.setMinimumWidth(self._spec()["seg"])
            self.setMinimumHeight(h)
        else:
            self.setMinimumWidth(self._spec()["seg"])
            self.setMinimumHeight(max(h, n * h))

    # -- 绘制 -------------------------------------------------------------
    def _colors(self, status: str):
        c = lambda k: QColor(T(f"color.{k}"))  # noqa: E731
        primary = c("primary")
        weight = QFont.DemiBold
        mapping = {
            # fill, border, glyph, title
            "process": (primary, primary, c("on.primary"), c("primary")),
            "finish": (c("bg.elevated"), primary, primary, c("text.primary")),
            "wait": (c("bg.elevated"), c("border.strong"),
                     c("text.tertiary"), c("text.tertiary")),
            "error": (c("bg.elevated"), c("danger"), c("danger"), c("danger")),
        }
        fill, border, glyph, title = mapping[status]
        return fill, border, glyph, title, weight

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        if self._orientation == Qt.Horizontal:
            self._paint_horizontal(painter)
        else:
            self._paint_vertical(painter)
        painter.end()

    # -- 水平 -------------------------------------------------------------
    def _paint_horizontal(self, p: QPainter) -> None:
        n = len(self._steps)
        if n == 0:
            return
        r = self._node_r
        d = 2 * r
        title_font, desc_font = self._title_font(), self._desc_font()
        tfm, dfm = QFontMetrics(title_font), QFontMetrics(desc_font)
        title_h, desc_h = tfm.height(), dfm.height()
        seg = self.width() / n
        # 唯一基准线：节点圆心与文本块中心共用 cy，连接线也画在 cy 上。
        # cy 取控件高度的中线：控件高度本身就是 max(节点直径, 文本块高) + 2×_PAD_V，
        # 所以节点与文本块同时居中，上下留白各为 _PAD_V。
        # （原式 (h - max(d, text_h))/2 + d/2 在「文本块高于节点」时会把文本块
        #  顶到上边界之外——带描述文案时 block_top 为负，标题顶部被裁。）
        cy = self.height() / 2.0

        for i, st in enumerate(self._steps):
            status = self.status_of(i)
            x0 = i * seg
            cx = x0 + d / 2.0
            # 文本可用宽度 = 段宽 - 节点 - 两个间距，超长省略，绝不越段
            text_w = max(10.0, seg - d - 2 * _TEXT_GAP - T("space.2"))
            title_w = tfm.horizontalAdvance(st["title"])
            block_w = title_w
            if st["desc"]:
                block_w = max(block_w, dfm.horizontalAdvance(st["desc"]))

            if i < n - 1:
                x_start = cx + r + min(block_w, text_w) + _TEXT_GAP
                x_end = (i + 1) * seg + d / 2.0 - _TEXT_GAP
                if x_end - x_start >= T("space.1"):
                    self._draw_link(p, x_start, cy, x_end, cy,
                                    status == "finish" or status == "process")
            self._draw_node(p, cx, cy, status, i, r)
            block_top = cy - self._text_block_h() / 2.0
            self._draw_texts(p, st, status, cx + r + _TEXT_GAP, block_top,
                             text_w, title_h, desc_h,
                             tfm, dfm, title_font, desc_font)

    # -- 垂直 -------------------------------------------------------------
    def _paint_vertical(self, p: QPainter) -> None:
        n = len(self._steps)
        if n == 0:
            return
        r = self._node_r
        d = 2 * r
        title_font, desc_font = self._title_font(), self._desc_font()
        tfm, dfm = QFontMetrics(title_font), QFontMetrics(desc_font)
        title_h, desc_h = tfm.height(), dfm.height()
        row = self.height() / n
        cx = _PAD_H + d / 2.0
        text_x = cx + r + _TEXT_GAP
        text_w = max(10.0, self.width() - text_x - _PAD_H)

        for i, st in enumerate(self._steps):
            status = self.status_of(i)
            row_top = i * row
            node_top = row_top + (_PAD_V if row > self._content_h()
                                 else (row - d) / 2.0)
            cy = node_top + r
            if i < n - 1:
                y_start = node_top + d + _TEXT_GAP
                y_end = (i + 1) * row - _TEXT_GAP
                if y_end - y_start >= T("space.1"):
                    self._draw_link(p, cx, y_start, cx, y_end,
                                    status == "finish" or status == "process")
            self._draw_node(p, cx, cy, status, i, r)
            # 单行文本与节点居中对齐，多行文本与节点顶端对齐——
            # 与 Alert / Popconfirm 的图标对齐规则同一套语义
            if st["desc"]:
                block_top = node_top
            else:
                block_top = cy - title_h / 2.0
            self._draw_texts(p, st, status, text_x, block_top,
                             text_w, title_h, desc_h,
                             tfm, dfm, title_font, desc_font)

    # -- 图元 -------------------------------------------------------------
    def _draw_link(self, p: QPainter, x1: float, y1: float,
                   x2: float, y2: float, active: bool) -> None:
        color = T("color.primary") if active else T("color.border.strong")
        pen = QPen(QColor(color))
        pen.setWidthF(self._link_width)
        pen.setStyle(self._link_style)
        p.setPen(pen)
        p.drawLine(QPointF(x1, y1), QPointF(x2, y2))

    def _draw_node(self, p: QPainter, cx: float, cy: float, status: str,
                   index: int, r: int) -> None:
        fill, border, glyph, _title, _w = self._colors(status)
        rect = QRectF(cx - r, cy - r, r * 2, r * 2)
        p.setBrush(fill)
        pen = QPen(border)
        pen.setWidthF(1.6)
        p.setPen(pen)
        p.drawEllipse(rect)
        # 字形按默认直径 20 设计，随半径缩放
        scale = r / 10.0
        if status == "finish":
            pen = QPen(glyph)
            pen.setWidthF(1.8 * scale)
            pen.setCapStyle(Qt.RoundCap)
            pen.setJoinStyle(Qt.RoundJoin)
            p.setPen(pen)
            p.drawPolyline([
                QPointF(cx - 5.0 * scale, cy + 0.5 * scale),
                QPointF(cx - 1.5 * scale, cy + 4.0 * scale),
                QPointF(cx + 5.5 * scale, cy - 3.5 * scale),
            ])
        elif status == "error":
            pen = QPen(glyph)
            pen.setWidthF(1.8 * scale)
            pen.setCapStyle(Qt.RoundCap)
            p.setPen(pen)
            p.drawLine(QPointF(cx - 3.5 * scale, cy - 3.5 * scale),
                       QPointF(cx + 3.5 * scale, cy + 3.5 * scale))
            p.drawLine(QPointF(cx + 3.5 * scale, cy - 3.5 * scale),
                       QPointF(cx - 3.5 * scale, cy + 3.5 * scale))
        else:
            font = QFont(self.font())
            font.setPixelSize(self._spec()["desc"])
            font.setWeight(QFont.DemiBold)
            p.setFont(font)
            p.setPen(glyph)
            p.drawText(rect, Qt.AlignCenter, str(index + 1))

    def _draw_texts(self, p: QPainter, st: dict, status: str, x: float,
                    block_top: float, text_w: float, title_h: int,
                    desc_h: int, tfm: QFontMetrics, dfm: QFontMetrics,
                    title_font: QFont, desc_font: QFont) -> None:
        """绘制标题 + 描述；``block_top`` 已由调用方按共线规则算好。"""
        _f, _b, _g, title_color, weight = self._colors(status)
        p.setFont(title_font)
        p.setPen(title_color)
        if status == "process":
            # 「当前」态：字重随之加粗，与 Tabs / NavMenu 的选中态一致
            tf = QFont(title_font)
            tf.setWeight(weight)
            p.setFont(tf)
        # 超长标题省略，避免压到下一个节点
        p.drawText(QRectF(x, block_top, text_w, title_h),
                   Qt.AlignLeft | Qt.AlignVCenter,
                   tfm.elidedText(st["title"], Qt.ElideRight, int(text_w)))
        if st["desc"]:
            p.setFont(desc_font)
            p.setPen(QColor(T("color.text.tertiary")))
            p.drawText(QRectF(x, block_top + title_h + _DESC_GAP, text_w,
                              desc_h),
                       Qt.AlignLeft | Qt.AlignVCenter,
                       dfm.elidedText(st["desc"], Qt.ElideRight,
                                      int(text_w)))