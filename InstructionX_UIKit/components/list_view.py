# -*- coding: utf-8 -*-
"""列表视图组件（SPEC §5.2 list_view）。

统一项高、hover / 选中样式（由全局 QSS 提供），并附带
``ListItemDelegate`` 辅助代理以控制行高与水平内边距。
"""

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QListWidget, QListWidgetItem, QStyledItemDelegate

from InstructionX_UIKit.theme import T

__all__ = ["ListWidget", "ListItemDelegate"]

#: 默认项高（px）：与 ``theme._INPUT_HEIGHTS`` 的 md 档一致，和 Table 数据行
#: 同高——同一页面里表格行与列表项并排时不会一高一矮。
_ITEM_H = 28


class ListItemDelegate(QStyledItemDelegate):
    """列表项代理：统一行高与水平内边距。

    参数:
        item_height: 行高（px），默认 28。
        h_padding: 文本左侧额外内边距（px），默认 **0**。默认不给额外缩进是
            有意的：全局 QSS 已为 ``QTableView / QTreeView / QListView::item``
            统一给了 ``padding-left: 8px``（``layout.inset.pad_x``），代理再
            加一层缩进会让**列表文字左缘比表格 / 树同行左缘右移**，一列并排
            时对不齐。需要额外缩进的调用方显式传值即可。

    示例::

        delegate = ListItemDelegate(40)
        list_widget.setItemDelegate(delegate)
    """

    def __init__(self, item_height: int = _ITEM_H, h_padding: int = 0, parent=None):
        super().__init__(parent)
        self._item_height = int(item_height)
        self._h_padding = max(0, int(h_padding))

    def sizeHint(self, option, index):
        size = super().sizeHint(option, index)
        # 宽度取整行宽：否则纯文本项的 sizeHint 只有文字宽度，会凭空多出
        # 一条水平滚动条（列表与表格 / 树的行宽行为必须一致）。
        return QSize(max(size.width(), option.rect.width()), self._item_height)

    def paint(self, painter, option, index):
        if self._h_padding:
            option.rect.adjust(self._h_padding, 0, 0, 0)
        super().paint(painter, option, index)


class ListWidget(QListWidget):
    """统一行高的列表组件。

    参数:
        item_height: 行高（px），默认 28。
        parent: 父控件。

    示例::

        lw = ListWidget()
        lw.add_item("第一项")
        lw.add_items(["第二项", "第三项"])
    """

    def __init__(self, item_height: int = _ITEM_H, parent=None):
        super().__init__(parent)
        self._delegate = ListItemDelegate(item_height, parent=self)
        self.setItemDelegate(self._delegate)
        self.setUniformItemSizes(True)
        # 文本省略而非撑宽：长条目与表格单元格一样右端对齐省略号
        self.setTextElideMode(Qt.ElideRight)

    # ------------------------------------------------------------------ 便捷
    def add_item(self, text: str, icon: QIcon = None, data=None) -> QListWidgetItem:
        """追加一项，返回创建的 ``QListWidgetItem``。"""
        item = QListWidgetItem(text)
        if icon is not None:
            item.setIcon(icon)
        if data is not None:
            item.setData(Qt.UserRole, data)
        self.addItem(item)
        return item

    def add_items(self, texts) -> None:
        """批量追加纯文本项。"""
        for text in texts:
            self.add_item(str(text))

    def set_item_height(self, height: int) -> None:
        """调整统一行高。"""
        self._delegate._item_height = max(16, int(height))
        self.scheduleDelayedItemsLayout()
        self.viewport().update()

    def item_height(self) -> int:
        """当前统一行高（px）。"""
        return self._delegate._item_height

    # ------------------------------------------------------------------ 度量
    def text_inset(self) -> int:
        """文字左缘相对列表边框的内缩（px）。

        由全局 QSS 的 ``layout.inset.pad_x`` 决定，与 Table 单元格、
        Tree 节点文字共享同一条左缘基准线。
        """
        return T("layout.inset.pad_x")