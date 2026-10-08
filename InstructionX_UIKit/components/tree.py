# -*- coding: utf-8 -*-
"""树组件（SPEC §5.2 tree）。

在全局 QSS 分支箭头基础上叠加自绘缩进参考线，支持复选框模式；
缩进线颜色取边框令牌，主题实时感知。缩进线在视口自身的事件过滤器
``QEvent.Paint`` 中「先铺参考线、后走默认绘制」，与视口重绘同生命周期，
展开 / 收起、主题切换后不会残缺；只遍历视口可视区节点（O(可视行)）。

对齐要点（数据展示轨的重点）：

- **行高**由代理锁定到密度刻度（默认 28px = md 档），与 Table 数据行、
  ListWidget 项同高；不锁的话 Qt 按字体算行高，同一页面里树比表格矮一截。
- **缩进参考线**画在 Qt 自己的分支列中心上（``indent * depth + indent // 2``），
  线与展开箭头 / 复选框同一条纵向网格；早前按 ``base_x = 4`` 估算，
  比 Qt 实际的分支中心右偏 4px，参考线与箭头脱开。
- 参考线**垫在内容之下**绘制（先铺线再走默认绘制路径），不会被箭头穿过。
"""

from PySide6.QtCore import QEvent, QPoint, Qt, QSize
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (
    QStyledItemDelegate,
    QTreeWidget,
    QTreeWidgetItem,
    QTreeWidgetItemIterator,
)

from InstructionX_UIKit.theme import T, ThemeManager

__all__ = ["Tree"]


class _RowDelegate(QStyledItemDelegate):
    """统一行高代理：把每一行拉到同一高度，宽度取整行宽。"""

    def __init__(self, row_height: int = 28, parent=None):
        super().__init__(parent)
        self._row_height = row_height

    def sizeHint(self, option, index):
        size = super().sizeHint(option, index)
        return QSize(max(size.width(), option.rect.width()), self._row_height)


class Tree(QTreeWidget):
    """带缩进参考线的树形控件。

    参数:
        checkable: 节点是否带复选框（含父子联动三态），默认 False。
        indent_lines: 是否绘制缩进参考线，默认 True。
        row_height: 行高（px），默认 28。
        parent: 父控件。

    示例::

        tree = Tree(checkable=True)
        tree.set_data([("水果", [("苹果", []), ("香蕉", [])])])
        tree.expand_all()
    """

    def __init__(self, checkable: bool = False, indent_lines: bool = True,
                 row_height: int = 28, parent=None):
        super().__init__(parent)
        self._checkable = bool(checkable)
        self._indent_lines = bool(indent_lines)
        self._row_height = max(16, int(row_height))
        self.setHeaderHidden(True)
        # 缩进步长：令牌推导（layout.icon.gap × 2 + space.2 = 20px），
        # 与 body 字号 13px 成 20 : 26 的视觉节奏；写成魔数时树的层级线
        # 与列表 / 表格的 8px 内边距基线就对不上了。
        self.setIndentation(T("layout.icon.gap") * 2 + T("space.2"))
        self.setUniformRowHeights(True)
        self._delegate = _RowDelegate(self._row_height, self)
        self.setItemDelegate(self._delegate)
        # 拦截视口绘制：先铺缩进参考线，再走基类默认路径绘制树内容，
        # 二者与视口重绘同生命周期（QAbstractScrollArea 的内部过滤器在
        # 默认路径中把树内容画进视口，直接调用基类 paintEvent 复现同一
        # 路径，然后拦截事件防止双绘）。
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

    def set_row_height(self, height: int) -> None:
        """设置统一行高（px）。"""
        self._row_height = max(16, int(height))
        self._delegate._row_height = self._row_height
        self.scheduleDelayedItemsLayout()
        self.viewport().update()

    def row_height(self) -> int:
        return self._row_height

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

    def _branch_x(self, depth: int) -> int:
        """深度 ``depth`` 节点的分支（展开箭头 / 复选框）中心 x。

        与 Qt 自身的分支列计算一致：第 d 层的分支槽从 ``indent * d`` 开始、
        宽 ``indent``，因此中心即 ``indent * d + indent // 2``。
        """
        indent = self.indentation()
        return indent * depth + indent // 2

    def eventFilter(self, watched, event) -> bool:
        if watched is self.viewport() and event.type() == QEvent.Paint:
            if self._indent_lines and self.topLevelItemCount() > 0:
                # 垫底绘制：参考线在下、箭头与文字在上，线不会横穿图标
                self._paint_indent_lines()
            QTreeWidget.paintEvent(self, event)
            return True
        return super().eventFilter(watched, event)

    def _paint_indent_lines(self) -> None:
        """在视口上绘制可视区节点的缩进参考线（O(可视行数)）。"""
        viewport = self.viewport()
        painter = QPainter(viewport)
        # 1px 参考线走非抗锯齿：抗锯齿下 1px 线会被摊到相邻两个像素上，
        # 看起来是一根发灰的「2px 淡线」，反而比表格分隔线更弱。
        painter.setRenderHint(QPainter.Antialiasing, False)
        pen = QPen(QColor(T("color.border")))
        pen.setWidth(1)
        painter.setPen(pen)

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
                    # 父节点分支向下的竖线 + 指向自身的横线（横线终点就是
                    # 自身分支列中心，因此与展开箭头 / 复选框严格对齐）
                    if parent is not None:
                        prect = self.visualRect(self.indexFromItem(parent))
                        x = self._branch_x(depth - 1)
                        y0 = prect.y() + prect.height() // 2
                        painter.drawLine(x, y0, x, y_mid)
                        painter.drawLine(x, y_mid, self._branch_x(depth), y_mid)
                    # 祖先层级的延续竖线（祖先还有后续兄弟时）
                    ancestor = parent
                    while ancestor is not None:
                        if self._depth(ancestor) >= 1 \
                                and self._has_next_sibling(ancestor):
                            x = self._branch_x(self._depth(ancestor) - 1)
                            painter.drawLine(x, rect.y(), x,
                                             rect.y() + rect.height())
                        ancestor = ancestor.parent()
            if item is end_item:
                break
            item = self.itemBelow(item)
        painter.end()