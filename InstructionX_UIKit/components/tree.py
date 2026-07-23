# -*- coding: utf-8 -*-
"""树组件（SPEC §5.2 tree）。

在全局 QSS 分支箭头基础上叠加自绘缩进参考线，支持复选框模式；
缩进线颜色取边框令牌，主题实时感知。
"""

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QTreeWidget, QTreeWidgetItem, QTreeWidgetItemIterator

from InstructionX_UIKit.theme import T, ThemeManager

__all__ = ["Tree"]


class Tree(QTreeWidget):
    """带缩进参考线的树形控件。

    参数:
        checkable: 节点是否带复选框（含父子联动三态），默认 False。
        indent_lines: 是否绘制缩进参考线，默认 True。
        parent: 父控件。

    示例::

        tree = Tree(checkable=True)
        tree.set_data([("水果", [("苹果", []), ("香蕉", [])])])
        tree.expand_all()
    """

    def __init__(self, checkable: bool = False, indent_lines: bool = True, parent=None):
        super().__init__(parent)
        self._checkable = bool(checkable)
        self._indent_lines = bool(indent_lines)
        self.setHeaderHidden(True)
        self.setIndentation(20)
        self.setUniformRowHeights(True)
        ThemeManager.instance().theme_changed.connect(self.viewport().update)

    # ------------------------------------------------------------------ 数据
    def set_data(self, items) -> None:
        """按嵌套结构填充，``items`` 为 ``[(文本, 子项列表), ...]``。"""
        self.clear()
        for text, children in items:
            self.add_item(text, children=children)

    def add_item(self, text: str, parent: QTreeWidgetItem = None,
                 children=None) -> QTreeWidgetItem:
        """添加节点；``parent`` 为空则为顶级节点，可递归挂子节点。"""
        item = QTreeWidgetItem([str(text)])
        if parent is None:
            self.addTopLevelItem(item)
        else:
            parent.addChild(item)
        if self._checkable:
            item.setFlags(
                item.flags() | Qt.ItemIsUserCheckable | Qt.ItemIsAutoTristate
            )
            item.setCheckState(0, Qt.Unchecked)
        for child_text, grand in children or []:
            self.add_item(child_text, parent=item, children=grand)
        return item

    def set_checkable(self, checkable: bool) -> None:
        """切换复选模式（作用于已有与后续节点）。"""
        self._checkable = bool(checkable)
        it = QTreeWidgetItemIterator(self, QTreeWidgetItemIterator.All)
        while it.value():
            item = it.value()
            if self._checkable:
                item.setFlags(
                    item.flags() | Qt.ItemIsUserCheckable | Qt.ItemIsAutoTristate
                )
                item.setCheckState(0, Qt.Unchecked)
            else:
                item.setFlags(
                    item.flags() & ~(Qt.ItemIsUserCheckable | Qt.ItemIsAutoTristate)
                )
            it += 1

    def is_checkable(self) -> bool:
        return self._checkable

    def set_indent_lines(self, show: bool) -> None:
        """是否绘制缩进参考线。"""
        self._indent_lines = bool(show)
        self.viewport().update()

    def expand_all(self) -> None:
        """展开全部节点。"""
        self.expandAll()

    def collapse_all(self) -> None:
        """收起全部节点。"""
        self.collapseAll()

    # ------------------------------------------------------------------ 缩进线
    def _depth(self, item) -> int:
        depth = 0
        node = item.parent()
        while node is not None:
            depth += 1
            node = node.parent()
        return depth

    def _visible(self, item) -> bool:
        node = item
        while node is not None:
            if node.isHidden():
                return False
            node = node.parent()
        node = item.parent()
        while node is not None:
            if not node.isExpanded():
                return False
            node = node.parent()
        return True

    def _has_next_sibling(self, item) -> bool:
        parent = item.parent()
        if parent is None:
            index = self.indexOfTopLevelItem(item)
            return 0 <= index < self.topLevelItemCount() - 1
        index = parent.indexOfChild(item)
        return 0 <= index < parent.childCount() - 1

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        if not self._indent_lines or self.topLevelItemCount() == 0:
            return
        painter = QPainter(self.viewport())
        painter.setRenderHint(QPainter.Antialiasing, False)
        pen = QPen(QColor(T("color.border")))
        pen.setWidth(1)
        painter.setPen(pen)

        indent = self.indentation()
        base_x = 4  # 视口左边距（边框 + 内边距）

        def arrow_x(depth: int) -> int:
            # 深度 depth 节点的展开箭头中心 x
            return base_x + depth * indent + indent // 2

        it = QTreeWidgetItemIterator(self, QTreeWidgetItemIterator.All)
        while it.value():
            item = it.value()
            it += 1
            depth = self._depth(item)
            if depth < 1 or not self._visible(item):
                continue
            rect = self.visualRect(self.indexFromItem(item))
            if not rect.isValid():
                continue
            y_mid = rect.y() + rect.height() // 2
            parent = item.parent()
            # 父节点箭头向下的竖线 + 指向自身的横线
            if parent is not None:
                prect = self.visualRect(self.indexFromItem(parent))
                x = arrow_x(depth - 1)
                y0 = prect.y() + prect.height() // 2
                painter.drawLine(x, y0, x, y_mid)
                painter.drawLine(x, y_mid, x + indent // 2 + 3, y_mid)
            # 祖先层级的延续竖线（祖先还有后续兄弟时）
            ancestor = parent
            while ancestor is not None:
                if self._depth(ancestor) >= 1 and self._has_next_sibling(ancestor):
                    x = arrow_x(self._depth(ancestor) - 1)
                    painter.drawLine(x, rect.y(), x, rect.y() + rect.height())
                ancestor = ancestor.parent()
        painter.end()
