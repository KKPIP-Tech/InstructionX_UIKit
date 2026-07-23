# -*- coding: utf-8 -*-
"""列表视图组件（SPEC §5.2 list_view）。

统一项高、hover / 选中样式（由全局 QSS 提供），并附带
``ListItemDelegate`` 辅助代理以控制行高与内边距。
"""

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QListWidget, QListWidgetItem, QStyledItemDelegate

from InstructionX_UIKit.theme import set_property

__all__ = ["ListWidget", "ListItemDelegate"]


class ListItemDelegate(QStyledItemDelegate):
    """列表项代理：统一行高与水平内边距。

    参数:
        item_height: 行高（px），默认 36。
        h_padding: 文本左侧额外内边距（px），默认 8。

    示例::

        delegate = ListItemDelegate(40)
        list_widget.setItemDelegate(delegate)
    """

    def __init__(self, item_height: int = 36, h_padding: int = 8, parent=None):
        super().__init__(parent)
        self._item_height = int(item_height)
        self._h_padding = int(h_padding)

    def sizeHint(self, option, index):
        size = super().sizeHint(option, index)
        return QSize(size.width(), self._item_height)

    def paint(self, painter, option, index):
        option.rect.adjust(self._h_padding, 0, 0, 0)
        super().paint(painter, option, index)


class ListWidget(QListWidget):
    """统一行高的列表组件。

    参数:
        item_height: 行高（px），默认 36。
        parent: 父控件。

    示例::

        lw = ListWidget()
        lw.add_item("第一项")
        lw.add_items(["第二项", "第三项"])
    """

    def __init__(self, item_height: int = 36, parent=None):
        super().__init__(parent)
        self._delegate = ListItemDelegate(item_height, parent=self)
        self.setItemDelegate(self._delegate)
        self.setUniformItemSizes(True)
        self.setProperty("uik", "list")
        set_property(self, "variant", "list")

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
        self._delegate._item_height = int(height)
        self.viewport().update()
