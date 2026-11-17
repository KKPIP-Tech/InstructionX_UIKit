# -*- coding: utf-8 -*-
"""描述列表组件（SPEC §5.2 descriptions）。

以「标签：值」网格展示只读信息，列数可固定也可随宽度自适应；
可选描边样式（标签区底色区分）。

对齐要点（本轨重点）：

- **标签列宽全局共享**：标签列宽由全部条目里最宽的「标签：」决定，
  所有单元格的标签左缘、冒号右缘、值左缘因此落在同一条竖线上。早前每格
  各自算标签宽（``max(96, …)``），同一行里「值」的左缘一格深一格浅，
  正是描述列表看着「散的」的根因。
- **整块自绘，不用 N 个单元格子控件**：网格线、标签底色、文本都在一个
  控件里画，外框 1px 只画一次、内部 1px 分隔线按列 / 行补齐（既不会双线
  加粗，也不用布局间距去凑分隔线），同时把子控件数量从 N+1 降到 1。
- 行高固定（``space.7`` = 28px，与表格数据行同高），标签与值在同一行内
  以同一条垂直中线绘制，基线自然对齐。
"""

import math

from PySide6.QtCore import QRect, QSize, Qt
from PySide6.QtGui import QColor, QFontMetrics, QPainter, QPen
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from InstructionX_UIKit.theme import T, ThemeManager, set_font, set_property

__all__ = ["Descriptions"]

#: 行高（px）= space.7，与 Table 数据行 / ListWidget 项高同档
_ROW_H = T("space.7")
#: 单元格内文字左右内边距（与表格单元格、列表项共享同一条左缘基准）
_PAD_X = T("layout.inset.pad_x")
#: 值列最小宽度：3 × space.12 = 144px（约 11 个正文宽），低于此值不再分列
_VALUE_MIN_W = T("space.12") * 3
#: 自适应模式下的列数上限
_MAX_COLS = 6


class _DescGrid(QWidget):
    """描述列表内容区：单控件自绘，保证行列网格严格对齐。"""

    def __init__(self, bordered: bool = False, parent=None):
        super().__init__(parent)
        self._items = []                       # [(标签, 值)]
        self._cols = 1
        self._label_w = _PAD_X
        self._bordered = bool(bordered)
        set_font(self, "md")
        ThemeManager.instance().theme_changed.connect(self.update)

    # ------------------------------------------------------------------ 数据
    def set_items(self, items) -> None:
        self._items = [(str(k), str(v)) for k, v in items]
        self._measure()
        self._fit_height()
        self.update()

    def items(self):
        return list(self._items)

    def set_cols(self, cols: int) -> None:
        cols = max(1, int(cols))
        if cols != self._cols:
            self._cols = cols
            self._fit_height()
            self.update()

    # ------------------------------------------------------------------ 度量
    def _used_rows(self) -> int:
        """实际用到的行数（0 条目时按 1 行留白，避免高度塌成 0 被裁切）。"""
        if not self._items:
            return 1
        return math.ceil(len(self._items) / self._cols)

    def _frame(self) -> int:
        """描边模式下外框占用的像素（1px 边框，其余 0）。"""
        return 1 if self._bordered else 0

    def _measure(self) -> None:
        """量出共享标签列宽：所有「标签：」左缘 / 值左缘共用一条竖线。"""
        fm = QFontMetrics(self.font())
        widest = max((fm.horizontalAdvance(f"{label}：")
                      for label, _ in self._items), default=0)
        self._label_w = widest + _PAD_X

    def cell_min_w(self) -> int:
        """单列最小宽度 = 标签列 + 值列最小宽。"""
        return self._label_w + _VALUE_MIN_W

    def _fit_height(self) -> None:
        """高度贴合内容：描边外框必须紧贴行列，不能浮在内容上方留空。"""
        self.setFixedHeight(self._used_rows() * _ROW_H + self._frame() * 2)

    def sizeHint(self) -> QSize:
        return QSize(max(1, self._cols) * self.cell_min_w(),
                     self._used_rows() * _ROW_H)

    def minimumSizeHint(self) -> QSize:
        return QSize(self.cell_min_w(), _ROW_H)

    # ------------------------------------------------------------------ 绘制
    def paintEvent(self, event) -> None:  # noqa: N802 - Qt 回调
        painter = QPainter(self)
        # 网格线是 1px 直角线：关掉抗锯齿，避免线被摊到两个像素上发灰
        painter.setRenderHint(QPainter.Antialiasing, False)
        rect = self.rect()
        frame = self._frame()
        left = rect.left() + frame
        top = rect.top() + frame
        inner_w = max(1, rect.width() - frame * 2)
        cell_w = inner_w // self._cols
        used_rows = self._used_rows()
        content_h = used_rows * _ROW_H

        if self._bordered:
            painter.fillRect(rect, QColor(T("color.bg.base")))
            painter.setPen(QPen(QColor(T("color.border"))))
            # 外框只画一次；内部 1px 分隔线按列 / 行补齐，不叠成双线
            painter.drawRect(rect.adjusted(0, 0, -1, -1))
            for c in range(1, self._cols):
                x = left + c * cell_w - 1
                painter.drawLine(x, top, x, top + content_h - 1)
            for r in range(1, used_rows):
                y = top + r * _ROW_H - 1
                painter.drawLine(left, y, left + self._cols * cell_w - 1, y)

        fm = painter.fontMetrics()
        text_h = fm.height()
        for index, (label, value) in enumerate(self._items):
            r, c = divmod(index, self._cols)
            x = left + c * cell_w
            y = top + r * _ROW_H
            if self._bordered:
                painter.fillRect(x, y, self._label_w, _ROW_H,
                                 QColor(T("color.bg.subtle")))
            painter.setPen(QColor(T("color.text.secondary")))
            painter.drawText(QRect(x + _PAD_X, y, self._label_w - _PAD_X, _ROW_H),
                             Qt.AlignVCenter | Qt.AlignLeft, f"{label}：")
            painter.setPen(QColor(T("color.text.primary")))
            value_x = x + self._label_w + _PAD_X
            value_w = max(_PAD_X, x + cell_w - value_x - _PAD_X)
            painter.drawText(QRect(value_x, y, value_w, _ROW_H),
                             Qt.AlignVCenter | Qt.AlignLeft,
                             fm.elidedText(value, Qt.ElideRight, value_w))
        painter.end()


class Descriptions(QWidget):
    """描述列表。

    参数:
        title: 顶部标题（可选）。
        column: 固定列数；``0`` 表示随宽度自适应（默认）。
        bordered: 描边样式（标签区带底色）。
        parent: 父控件。

    示例::

        desc = Descriptions("用户信息", bordered=True)
        desc.set_items([("姓名", "张三"), ("城市", "上海")])
        desc.add_item("邮箱", "zhang@example.com")
    """

    def __init__(self, title: str = "", column: int = 0,
                 bordered: bool = False, parent=None):
        super().__init__(parent)
        self._items = []  # [(label, value)]
        self._column = max(0, int(column))
        self._bordered = bool(bordered)
        self._cols = 1
        # 透明底：让宿主的表面色透上来，描边模式下的白底由 _DescGrid 自己铺
        set_property(self, "role", "plain")

        self._root = QVBoxLayout(self)
        self._root.setContentsMargins(0, 0, 0, 0)
        self._root.setSpacing(T("layout.card.gap"))
        self._title_label = QLabel(title, self)
        # 走实例级 QSS（set_font）而非 setFont：全局 QWidget { font-size }
        # 优先级更高，setFont 设的字号会被静默覆盖（契约 §6）。
        set_font(self._title_label, "title.sm", "semibold")
        self._title_label.setVisible(bool(title))
        self._root.addWidget(self._title_label)

        self._grid = _DescGrid(bordered, self)
        self._root.addWidget(self._grid, 0, Qt.AlignTop)
        self._grid.set_cols(self._effective_cols())

    # ------------------------------------------------------------------ 数据
    def set_title(self, title: str) -> None:
        """设置标题；空串隐藏。"""
        self._title_label.setText(title)
        self._title_label.setVisible(bool(title))

    def set_items(self, items) -> None:
        """整体替换条目，``items`` 为 ``[(标签, 值), ...]``。"""
        self._items = [(str(k), str(v)) for k, v in items]
        self._grid.set_items(self._items)
        self.set_cols(self._effective_cols())

    def add_item(self, label: str, value: str) -> None:
        """追加一个条目。"""
        self._items.append((str(label), str(value)))
        self._grid.set_items(self._items)
        self.set_cols(self._effective_cols())

    def clear(self) -> None:
        """清空全部条目。"""
        self._items.clear()
        self._grid.set_items(self._items)

    def items(self):
        return list(self._items)

    # ------------------------------------------------------------------ 布局
    def _effective_cols(self) -> int:
        """列数：固定列数优先，否则按「标签列 + 值列最小宽」自适应。"""
        if self._column > 0:
            return self._column
        width = max(1, self.width())
        return max(1, min(_MAX_COLS, width // self._grid.cell_min_w()))

    def set_cols(self, cols: int) -> None:
        self._cols = max(1, int(cols))
        self._grid.set_cols(self._cols)

    def cols(self) -> int:
        """当前列数。"""
        return self._cols

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt 回调
        super().resizeEvent(event)
        if self._column <= 0 and self._items:
            self.set_cols(self._effective_cols())