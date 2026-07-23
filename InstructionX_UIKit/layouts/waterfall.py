# -*- coding: utf-8 -*-
"""瀑布流布局预设（SPEC §6）。

2-4 列不等高卡片的瀑布流：每列一个 ``QVBoxLayout``，新卡片放入当前
累计高度最小的列，列底以 stretch 顶齐，卡片 ``setFixedHeight`` 不被
拉伸，从而形成真正参差错落的效果（区别于等高的普通网格）。

**API 驱动，无内置假数据**：卡片内容由调用方通过 ``items`` 传入，
每项为 ``(标题, 色块令牌键, 内容量档位)`` 三元组（可选第 4 元素为
元信息文本），档位 2-6 线性映射卡片总高 120-260px；也可直接传入
``QWidget``。不传 ``items`` 时显示优雅的空占位（「在此放置内容」）。

响应式（resizeEvent 中按 SPEC §2.6 断点处理）：

- ``xs`` / ``sm``：2 列；
- ``md``：3 列；
- ``lg`` / ``xl``：4 列。

整体置于 ``QScrollArea`` 内，窄窗口可滚动浏览。

示例::

    from InstructionX_UIKit.layouts.waterfall import create_waterfall
    win = create_waterfall(items=[
        ("山间晨雾", "color.primary.subtle", 3),
        ("城市夜景", "color.success.subtle", 5),
    ])
    win.show()
"""

from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ..theme import T
from ..tokens import Breakpoint
from .helpers import TokenColorChip, apply_token_font, empty_placeholder

__all__ = ["Waterfall", "create_waterfall"]

#: 各断点列数（SPEC §6：2-4 列）
_COLUMNS = {"xs": 2, "sm": 2, "md": 3, "lg": 4, "xl": 4}

#: 卡片总高区间（px）：内容量档位线性映射，形成不等高梯度
_CARD_H_MIN = 120
_CARD_H_MAX = 260
_RATIO_MIN = 2
_RATIO_MAX = 6

#: 色块最小高度（剩余空间由色块弹性填充）
_CHIP_MIN_H = 32


def _card_height(ratio: int) -> int:
    """内容量档位 -> 卡片总高（120-260px 梯度）。"""
    t = (ratio - _RATIO_MIN) / (_RATIO_MAX - _RATIO_MIN)
    return round(_CARD_H_MIN + t * (_CARD_H_MAX - _CARD_H_MIN))


class Waterfall(QWidget):
    """瀑布流：2-4 列不等高卡片，每列 QVBoxLayout，最短列优先分配。

    参数:
        items: 卡片内容列表。每项为 ``(标题, 色块令牌键, 内容量档位)``
            三元组（可选第 4 元素元信息文本）或 ``QWidget``；``None``
            或空列表时显示空占位。
        parent: 父控件。

    每张卡片固定自身高度（内容量驱动，120-260px 不等），放入当前
    累计高度最小的列；列底 stretch 使卡片顶对齐且不被拉伸。
    ``resizeEvent`` 中检测断点变化并按新列数重新分配。
    """

    def __init__(self, items=None, parent=None):
        super().__init__(parent)
        self._cols = 0
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        root.addWidget(scroll)

        self._content = QWidget()
        self._columns = QHBoxLayout(self._content)
        margin = T("space.4")
        self._columns.setContentsMargins(margin, margin, margin, margin)
        self._columns.setSpacing(T("space.4"))
        scroll.setWidget(self._content)

        self._cards = [
            item if isinstance(item, QWidget) else self._make_card(*item)
            for item in (items or [])
        ]
        # 初始按宽屏列数分配，首次 resize 时再按实际宽度修正
        self._relayout(_COLUMNS["lg"])

    # -- 卡片 ------------------------------------------------------------
    def _make_card(self, title, chip_key, ratio, meta=""):
        """构造不等高内容卡片：总高按档位固定，色块弹性填充剩余高度。"""
        card = QFrame()
        card.setFrameShape(QFrame.StyledPanel)
        lay = QVBoxLayout(card)
        lay.setContentsMargins(T("space.3"), T("space.3"), T("space.3"), T("space.3"))
        lay.setSpacing(T("space.2"))
        chip = TokenColorChip(chip_key, "radius.md")
        chip.setMinimumHeight(_CHIP_MIN_H)
        # 垂直方向弹性填充：标题/元信息保持自然高度，色块吃掉剩余空间
        chip.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)
        lay.addWidget(chip)
        head = QLabel(title)
        apply_token_font(head, "font.title.sm", "font.weight.semibold")
        lay.addWidget(head)
        if meta:
            meta_label = QLabel(meta)
            meta_label.setProperty("role", "tertiary")
            apply_token_font(meta_label, "font.sm")
            lay.addWidget(meta_label)
        height = _card_height(ratio)
        card.setFixedHeight(height)  # 列内不被拉伸的关键
        card.setProperty("card_height", height)  # 供按列分配估算
        return card

    # -- 响应式 ----------------------------------------------------------
    def resizeEvent(self, event):
        super().resizeEvent(event)
        cols = _COLUMNS[Breakpoint.from_width(self.width())]
        if cols != self._cols:
            self._relayout(cols)

    def _relayout(self, cols):
        """按列数重新分配：逐张放入累计高度最小的列（瀑布流关键逻辑）。"""
        self._cols = cols
        # 清空旧列：卡片仅从布局移出（仍为 _content 子控件），随后重新分配
        while self._columns.count():
            item = self._columns.takeAt(0)
            lay = item.layout()
            if lay is not None:
                while lay.count():
                    lay.takeAt(0)
                lay.deleteLater()
        col_layouts = []
        for _ in range(cols):
            col = QVBoxLayout()
            col.setContentsMargins(0, 0, 0, 0)
            col.setSpacing(T("space.4"))
            self._columns.addLayout(col, 1)  # 各列等宽
            col_layouts.append(col)
        if not self._cards:
            # 空内容：首列放置优雅空占位
            col_layouts[0].addWidget(empty_placeholder())
        heights = [0] * cols  # 各列累计高度（估算值）
        for card in self._cards:
            idx = heights.index(min(heights))
            col_layouts[idx].addWidget(card)
            heights[idx] += (card.property("card_height") or 160) + T("space.4")
        for col in col_layouts:
            col.addStretch(1)  # 列底 stretch：卡片顶对齐、高度不被拉伸

    # -- 测试 / 调试辅助 ---------------------------------------------------
    def column_cards(self):
        """返回按列分组的卡片列表 ``[[card, ...], ...]``（布局顺序）。"""
        groups = []
        for i in range(self._columns.count()):
            item = self._columns.itemAt(i)
            lay = item.layout() if item is not None else None
            cards = []
            if lay is not None:
                for j in range(lay.count()):
                    w = lay.itemAt(j).widget()
                    if w is not None:
                        cards.append(w)
            groups.append(cards)
        return groups


def create_waterfall(items=None, parent=None) -> QWidget:
    """创建瀑布流布局部件。

    参数:
        items: 卡片内容列表，每项为 ``(标题, 色块令牌键, 档位[, 元信息])``
            或 ``QWidget``；不传时显示空占位。
        parent: 父控件，默认 ``None``（作为独立窗口使用）。
    """
    return Waterfall(items=items, parent=parent)
