# -*- coding: utf-8 -*-
"""卡片网格布局预设（SPEC §6）。

按窗口断点自适应 1/2/3/4 列的等宽卡片网格：

- ``xs``：1 列；
- ``sm``：2 列；
- ``md``：3 列；
- ``lg`` / ``xl``：4 列。

**API 驱动，无内置假数据**：卡片内容由调用方通过 ``items`` 传入，
每项为 ``(标题, 描述, 色块令牌键)`` 三元组或 ``QWidget``；不传
``items`` 时显示优雅的空占位（「在此放置内容」）。

``resizeEvent`` 中按 ``Breakpoint.from_width`` 重排 ``QGridLayout``，
内容整体置于 ``QScrollArea`` 内，窄窗口可滚动查看。

示例::

    from InstructionX_UIKit.layouts.card_grid import create_card_grid
    win = create_card_grid(items=[
        ("数据看板", "汇总关键指标。", "color.primary.subtle"),
        ("任务中心", "展示待办与进度。", "color.success.subtle"),
    ])
    win.show()
"""

from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QLabel,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ..theme import T
from ..tokens import Breakpoint
from .helpers import TokenColorChip, apply_token_font, empty_placeholder

__all__ = ["CardGrid", "create_card_grid"]

#: 各断点对应的列数（SPEC §6：1/2/3/4 列）
_COLUMNS = {"xs": 1, "sm": 2, "md": 3, "lg": 4, "xl": 4}


class CardGrid(QWidget):
    """卡片网格：按断点 1/2/3/4 列重排的卡片集合。

    参数:
        items: 卡片内容列表。每项为 ``(标题, 描述, 色块令牌键)`` 三元组
            （由布局代为构建卡片）或 ``QWidget``（直接使用）；``None``
            或空列表时显示空占位。
        parent: 父控件。

    ``resizeEvent`` 中检测断点变化并重排网格；窄断点下列数减少，
    整体由滚动区承载。运行期可调用 :meth:`set_items` 更换内容。
    """

    def __init__(self, items=None, parent=None):
        super().__init__(parent)
        self._cols = 0
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        root.addWidget(self._scroll)

        self._content = QWidget()
        self._grid = QGridLayout(self._content)
        margin = T("space.4")
        self._grid.setContentsMargins(margin, margin, margin, margin)
        self._grid.setSpacing(T("space.4"))
        self._scroll.setWidget(self._content)

        self._placeholder = empty_placeholder()
        self._cards = []
        self.set_items(items)
        # 初始按宽屏列数摆放，首次 resize 时再按实际宽度修正
        self._relayout(_COLUMNS["lg"])

    # -- 内容 ------------------------------------------------------------
    def set_items(self, items):
        """设置卡片内容（三元组或 QWidget 列表；空则显示空占位）。"""
        for card in self._cards:
            card.setParent(None)
            card.deleteLater()
        self._cards = [
            item if isinstance(item, QWidget) else self._make_card(*item)
            for item in (items or [])
        ]
        self._sync_cards()

    def _sync_cards(self):
        """按当前内容刷新网格（有内容排卡片，无内容显示空占位）。"""
        while self._grid.count():
            self._grid.takeAt(0)
        if self._cards:
            cols = max(self._cols, 1)
            for i, card in enumerate(self._cards):
                self._grid.addWidget(card, i // cols, i % cols)
            self._placeholder.hide()
        else:
            self._grid.addWidget(self._placeholder, 0, 0, 1, max(self._cols, 1))
            self._placeholder.show()

    # -- 卡片 ------------------------------------------------------------
    def _make_card(self, title, desc, chip_key):
        """构造内容卡片：色块 + 标题 + 描述（颜色全部主题感知）。"""
        card = QFrame()
        card.setFrameShape(QFrame.StyledPanel)
        lay = QVBoxLayout(card)
        lay.setContentsMargins(T("space.4"), T("space.4"), T("space.4"), T("space.4"))
        lay.setSpacing(T("space.2"))
        chip = TokenColorChip(chip_key, "radius.md")
        chip.setFixedHeight(T("space.16") + T("space.6"))
        lay.addWidget(chip)
        head = QLabel(title)
        apply_token_font(head, "font.title.sm", "font.weight.semibold")
        lay.addWidget(head)
        body = QLabel(desc)
        body.setProperty("role", "secondary")
        body.setWordWrap(True)
        lay.addWidget(body)
        lay.addStretch(1)
        return card

    # -- 响应式 ----------------------------------------------------------
    def resizeEvent(self, event):
        super().resizeEvent(event)
        cols = _COLUMNS[Breakpoint.from_width(self.width())]
        if cols != self._cols:
            self._relayout(cols)

    def _relayout(self, cols):
        """按列数重排网格（控件保持父子关系，仅改变网格位置）。"""
        self._cols = cols
        self._sync_cards()
        for c in range(4):
            self._grid.setColumnStretch(c, 1 if c < cols else 0)


def create_card_grid(items=None, parent=None) -> QWidget:
    """创建卡片网格布局部件。

    参数:
        items: 卡片内容列表，每项为 ``(标题, 描述, 色块令牌键)`` 或
            ``QWidget``；不传时显示空占位。
        parent: 父控件，默认 ``None``（作为独立窗口使用）。
    """
    return CardGrid(items=items, parent=parent)
