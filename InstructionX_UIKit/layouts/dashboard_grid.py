# -*- coding: utf-8 -*-
"""仪表盘网格布局预设（SPEC §6）。

12 列网格的仪表盘：卡片按传入顺序依次占据 3/3/3/3（统计卡行）、
8/4（主图 + 侧栏）、6/6（半宽）、12（通栏）跨度——对应 SPEC §6 的
3/4/6/12 跨度。少于 9 张卡片时按顺序填充前面槽位。

**API 驱动，无内置假数据**：卡片为调用方传入的 ``QWidget`` 列表；
不传 ``cards`` 时显示优雅的空占位（「在此放置内容」）。构建带标题
的卡片外框可使用 :func:`InstructionX_UIKit.layouts.helpers.titled_card`。

响应式（resizeEvent 中按 SPEC §2.6 断点处理跨度重排）：

- ``lg`` / ``xl``：4 + 8/4 + 6/6 + 12 的多行排布；
- ``md``：统计卡两两一行（各跨 6），其余保持层次；
- ``xs`` / ``sm``：所有卡片跨满 12 列纵向堆叠。

整体置于 ``QScrollArea`` 内，窄窗口可滚动查看。

示例::

    from InstructionX_UIKit.layouts.dashboard_grid import create_dashboard_grid
    from InstructionX_UIKit.layouts.helpers import titled_card
    card, lay = titled_card("总用户数")
    win = create_dashboard_grid(cards=[card])
    win.show()
"""

from PySide6.QtWidgets import QGridLayout, QScrollArea, QVBoxLayout, QWidget

from ..theme import T
from ..tokens import Breakpoint
from .helpers import empty_placeholder

__all__ = ["DashboardGrid", "create_dashboard_grid"]

#: 网格列数（SPEC §6：12 列网格）
_GRID_COLUMNS = 12


class DashboardGrid(QWidget):
    """仪表盘网格：12 列网格，卡片跨 3/4/6/12 列，按断点重排。

    参数:
        cards: 卡片控件列表（``QWidget``），按传入顺序对应跨度槽位
            （前 4 张各跨 3、第 5 张跨 8、第 6 张跨 4、第 7/8 张各跨 6、
            第 9 张跨 12）；``None`` 或空列表时显示空占位。
        parent: 父控件。

    ``resizeEvent`` 中检测断点变化并重新计算各卡跨度。运行期可调用
    :meth:`set_cards` 更换卡片。
    """

    def __init__(self, cards=None, parent=None):
        super().__init__(parent)
        self._bp = ""
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        root.addWidget(scroll)

        self._content = QWidget()
        self._grid = QGridLayout(self._content)
        margin = T("space.4")
        self._grid.setContentsMargins(margin, margin, margin, margin)
        self._grid.setSpacing(T("space.4"))
        for col in range(_GRID_COLUMNS):
            self._grid.setColumnStretch(col, 1)
        scroll.setWidget(self._content)

        self._placeholder = empty_placeholder()
        self._cards = []
        self.set_cards(cards)
        # 初始按宽屏断点摆放，首次 resize 时再按实际宽度修正
        self._relayout("lg")

    # -- 内容 ------------------------------------------------------------
    def set_cards(self, cards):
        """设置卡片控件列表（QWidget；空则显示空占位）。"""
        for old in self._cards:
            old.hide()
            old.setParent(None)
        self._cards = list(cards or [])
        for card in self._cards:
            card.setParent(self._content)
            card.show()
        self._sync_cards()

    def _sync_cards(self):
        """按当前断点跨度表把卡片放入网格（或显示空占位）。"""
        while self._grid.count():
            self._grid.takeAt(0)
        if self._cards:
            for card, (row, col, span) in zip(self._cards, self._placements(self._bp or "lg")):
                self._grid.addWidget(card, row, col, 1, span)
            self._placeholder.hide()
        else:
            self._grid.addWidget(self._placeholder, 0, 0, 1, _GRID_COLUMNS)
            self._placeholder.show()

    # -- 跨度表 ----------------------------------------------------------
    @staticmethod
    def _placements(bp):
        """按断点返回各槽位的 (行, 列, 跨度) 排布表（最多 9 张卡片）。"""
        if bp in ("lg", "xl"):
            return [
                (0, 0, 3), (0, 3, 3), (0, 6, 3), (0, 9, 3),   # 统计卡 ×4
                (1, 0, 8), (1, 8, 4),                          # 主图 + 动态
                (2, 0, 6), (2, 6, 6),                          # 半宽 ×2
                (3, 0, 12),                                    # 通栏公告
            ]
        if bp == "md":
            return [
                (0, 0, 6), (0, 6, 6), (1, 0, 6), (1, 6, 6),   # 统计卡 2×2
                (2, 0, 8), (2, 8, 4),                          # 主图 + 动态
                (3, 0, 6), (3, 6, 6),                          # 半宽 ×2
                (4, 0, 12),                                    # 通栏公告
            ]
        # xs / sm：全部通栏堆叠
        return [(row, 0, 12) for row in range(9)]

    # -- 响应式 ----------------------------------------------------------
    def resizeEvent(self, event):
        super().resizeEvent(event)
        bp = Breakpoint.from_width(self.width())
        if bp != self._bp:
            self._relayout(bp)

    def _relayout(self, bp):
        """按断点跨度表重排网格（控件保持父子关系，仅改变网格位置）。"""
        self._bp = bp
        self._sync_cards()


def create_dashboard_grid(cards=None, parent=None) -> QWidget:
    """创建仪表盘网格布局部件。

    参数:
        cards: 卡片控件列表（``QWidget``）；不传时显示空占位。
        parent: 父控件，默认 ``None``（作为独立窗口使用）。
    """
    return DashboardGrid(cards=cards, parent=parent)
