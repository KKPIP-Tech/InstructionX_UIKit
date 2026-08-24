# -*- coding: utf-8 -*-
"""树组件（SPEC §5.2 tree）。

在全局 QSS 分支箭头基础上叠加自绘缩进参考线，支持复选框模式；
缩进线颜色取边框令牌，主题实时感知。缩进线在视口自身的事件过滤器
QEvent.Paint 中「先默认绘制、后叠加自绘」，与视口重绘同生命周期，
展开/收起、主题切换后不会残缺；只遍历视口可视区节点（O(可视行)）。
"""

from PySide6.QtCore import QEvent, QPoint, Qt
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
        # 拦截视口绘制：先完成默认绘制再叠加缩进线（QAbstractScrollArea
        # 的内部过滤器在默认路径中把树内容画进视口，这里直接调用基类
        # paintEvent 复现同一路径，然后自绘缩进线并拦截事件防止双绘）。
        self.viewport().installEventFilter(self)
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

    def _has_next_sibling(self, item) -> bool:
        parent = item.parent()
        if parent is None:
            index = self.indexOfTopLevelItem(item)
            return 0 <= index < self.topLevelItemCount() - 1
        index = parent.indexOfChild(item)
        return 0 <= index < parent.childCount() - 1

    def eventFilter(self, watched, event) -> bool:
        if watched is self.viewport() and event.type() == QEvent.Paint:
            if not self._indent_lines or self.topLevelItemCount() == 0:
                return super().eventFilter(watched, event)
            # 先默认：直接调用基类 paintEvent（即内部过滤器默认路径的
            # 树内容绘制），再叠加缩进线，并拦截事件避免内部过滤器双绘。
            QTreeWidget.paintEvent(self, event)
            self._paint_indent_lines()
            return True
        return super().eventFilter(watched, event)

    def _paint_indent_lines(self) -> None:
        """在视口上绘制可视区节点的缩进参考线（O(可视行数)）。"""
        viewport = self.viewport()
        painter = QPainter(viewport)
        painter.setRenderHint(QPainter.Antialiasing, False)
        pen = QPen(QColor(T("color.border")))
        pen.setWidth(1)
        painter.setPen(pen)

        indent = self.indentation()
        base_x = 4  # 视口左边距（边框 + 内边距）

        def arrow_x(depth: int) -> int:
            # 深度 depth 节点的展开箭头中心 x
            return base_x + depth * indent + indent // 2

        # 可视区范围：indexAt 取视口左上与右下所在行，itemBelow 沿
        # 可视顺序下移（自动跳过折叠子树），只遍历可见行。
        first = self.indexAt(QPoint(1, 0))
        if not first.isValid():
            painter.end()
            return
        last = self.indexAt(QPoint(1, viewport.height() - 1))
        end_item = self.itemFromIndex(last) if last.isValid() else None
        item = self.itemFromIndex(first)
        while item is not None:
            rect = self.visualRect(self.indexFromItem(item))
            if rect.isValid():
                depth = self._depth(item)
                if depth >= 1:
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
                        if self._depth(ancestor) >= 1 \
                                and self._has_next_sibling(ancestor):
                            x = arrow_x(self._depth(ancestor) - 1)
                            painter.drawLine(x, rect.y(), x,
                                             rect.y() + rect.height())
                        ancestor = ancestor.parent()
            if item is end_item:
                break
            item = self.itemBelow(item)
        painter.end()
