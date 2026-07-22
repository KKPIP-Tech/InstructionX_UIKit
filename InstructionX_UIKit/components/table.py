# -*- coding: utf-8 -*-
"""表格组件（SPEC §5.2 table）。

斑马纹、紧凑行高、列排序；无数据时在视口中央绘制空状态占位文本。
"""

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QAbstractItemView, QHeaderView, QTableWidget, QTableWidgetItem

from InstructionX_UIKit.theme import T, ThemeManager

__all__ = ["Table"]

_ROW_H = 32


class Table(QTableWidget):
    """数据表格。

    参数:
        rows / columns: 初始行列数。
        sortable: 是否允许点击表头排序，默认 True。
        parent: 父控件。

    示例::

        table = Table()
        table.set_data(["姓名", "年龄"], [["张三", 28], ["李四", 35]])
        table.set_empty_text("还没有数据")
    """

    def __init__(self, rows: int = 0, columns: int = 0, sortable: bool = True, parent=None):
        super().__init__(rows, columns, parent)
        self._empty_text = "暂无数据"
        self.setAlternatingRowColors(True)
        self.verticalHeader().setVisible(False)
        self.verticalHeader().setDefaultSectionSize(_ROW_H)
        self.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.horizontalHeader().setHighlightSections(False)
        self.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.setShowGrid(False)
        self.setSortingEnabled(sortable)
        ThemeManager.instance().theme_changed.connect(self.viewport().update)

    # ------------------------------------------------------------------ 数据
    def set_data(self, headers, rows) -> None:
        """整体设置表头与数据。

        参数:
            headers: 列标题列表。
            rows: 二维数据（按行），元素会被转为字符串。
        """
        sorting = self.isSortingEnabled()
        self.setSortingEnabled(False)
        self.clear()
        headers = [str(h) for h in headers]
        self.setColumnCount(len(headers))
        self.setHorizontalHeaderLabels(headers)
        self.setRowCount(len(rows))
        for r, row in enumerate(rows):
            for c, value in enumerate(row):
                if c >= len(headers):
                    break
                item = QTableWidgetItem(str(value))
                # 数值右对齐更利于比较
                if isinstance(value, (int, float)):
                    item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                    item.setData(Qt.EditRole, value)
                self.setItem(r, c, item)
        self.setSortingEnabled(sorting)

    def set_empty_text(self, text: str) -> None:
        """设置空状态占位文本。"""
        self._empty_text = text
        self.viewport().update()

    def empty_text(self) -> str:
        return self._empty_text

    def set_compact(self, compact: bool) -> None:
        """紧凑（28px）/ 常规（32px）行高切换。"""
        self.verticalHeader().setDefaultSectionSize(28 if compact else _ROW_H)

    # ------------------------------------------------------------------ 绘制
    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        if self.rowCount() > 0:
            return
        painter = QPainter(self.viewport())
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(QColor(T("color.text.tertiary")))
        font = painter.font()
        font.setPixelSize(T("font.md"))
        painter.setFont(font)
        painter.drawText(self.viewport().rect(), Qt.AlignCenter, self._empty_text)
        painter.end()
