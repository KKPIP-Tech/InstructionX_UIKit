# -*- coding: utf-8 -*-
"""表格组件（SPEC §5.2 table）。

斑马纹、统一行高、按列语义对齐（文本列左对齐 / 数值列右对齐，表头随列
同步），无数据时以**视口子控件**显示空状态占位文本。

关于「空状态覆盖导致的重叠」——这是**有意的浮层覆盖**，不是误重叠：
占位标签要盖在表格内容区之上（Ant Design / Element 同款做法），否则空
表格只能显示一大片空白，看不出「这里本该有数据」。实现上它必须挂在
``viewport()`` 而不是 Table 本体：

1. 挂到 Table 本体时，它是 viewport 的**兄弟**节点，几何只能靠
   ``setGeometry(viewport().geometry())`` 手工同步——表头高度变化、
   滚动条出现 / 消失都会让它错位（错位后它会盖住表头或露在表格外）。
2. 挂到 viewport 上，它是 viewport 的**子**控件，与被覆盖区域同坐标系，
   由 viewport 的 resize 驱动，不需要任何手工对齐。
3. 父子关系而非同级关系，因此也不会触发审计工具「同级控件重叠」规则
   （该规则针对的是两个并排控件的错误压盖，正是我们要消除的那类缺陷）。

普通子控件随 resize / 主题切换自动重绘，不依赖在父 paintEvent 里向
viewport 绘制（viewport 重绘会擦除）。
"""

from PySide6.QtCore import QEvent, Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHeaderView,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
)

from InstructionX_UIKit.theme import T, ThemeManager, set_font, set_property

__all__ = ["Table"]

#: 语义对齐名 -> 文本对齐标志（单元格与表头共用同一组标志，保证行列一致）
_ALIGN_FLAGS = {
    "left": Qt.AlignLeft | Qt.AlignVCenter,
    "right": Qt.AlignRight | Qt.AlignVCenter,
    "center": Qt.AlignHCenter | Qt.AlignVCenter,
}

#: 行高（px）。与 ``theme._INPUT_HEIGHTS`` 的 md / sm 两档保持一致：
#: 数据行默认 28px（md），``set_compact(True)`` 切到 22px（sm），
#: 表头高度跟随行高，保证「表头—数据行」在同一节奏上。
_ROW_H = 28
_ROW_H_COMPACT = 22


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
        table.set_column_alignment(1, "right")   # 数值列右对齐
    """

    def __init__(self, rows: int = 0, columns: int = 0, sortable: bool = True, parent=None):
        super().__init__(rows, columns, parent)
        self._empty_text = "暂无数据"
        self._row_h = _ROW_H
        #: 显式指定的列对齐 {列号: "left"/"right"/"center"}；未指定的列按数据自动判定
        self._align_override: dict = {}

        header = self.horizontalHeader()
        self.setAlternatingRowColors(True)
        self.verticalHeader().setVisible(False)
        # 行高锁定：默认竖向表头允许拖拽调宽，这里固定档位，保证「行高一致」
        self.verticalHeader().setSectionResizeMode(QHeaderView.Fixed)
        self.verticalHeader().setDefaultSectionSize(self._row_h)
        header.setSectionResizeMode(QHeaderView.Stretch)
        header.setHighlightSections(False)
        # 表头默认左对齐：Qt 的 QHeaderView 默认是居中（defaultAlignment
        # = Qt.AlignCenter），而单元格是左对齐，两者不对齐时表头文字会
        # 「浮」在列中间，破坏行列关系。数值列再单独切成右对齐。
        header.setDefaultAlignment(_ALIGN_FLAGS["left"])
        header.setFixedHeight(self._row_h)
        self.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.setShowGrid(False)
        self.setTextElideMode(Qt.ElideRight)
        self.setWordWrap(False)
        self.setSortingEnabled(sortable)

        # 空态占位：viewport 的子控件（详见模块文档「关于重叠」的说明）
        self._empty_label = QLabel(self.viewport())
        self._empty_label.setAlignment(Qt.AlignCenter)
        self._empty_label.setAttribute(Qt.WA_TransparentForMouseEvents)
        set_property(self._empty_label, "role", "tertiary")
        set_font(self._empty_label, "md")
        self._update_empty_overlay()
        # 视口几何变化（滚动条出现 / 表头高度变化）同样要跟随，
        # 挂在 viewport 的 Resize 上比只接 Table.resizeEvent 更完整。
        self.viewport().installEventFilter(self)
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
        rows = [list(r) for r in rows]
        self.setColumnCount(len(headers))
        self.setHorizontalHeaderLabels(headers)
        self.setRowCount(len(rows))
        aligns = self._detect_alignments(rows, len(headers))
        for r, row in enumerate(rows):
            for c, value in enumerate(row):
                if c >= len(headers):
                    break
                item = QTableWidgetItem(str(value))
                item.setTextAlignment(aligns[c])
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    # 保留原始数值：排序按数值而非字符串（"9" > "10"）
                    item.setData(Qt.EditRole, value)
                self.setItem(r, c, item)
        self._apply_header_alignment(aligns)
        self.setSortingEnabled(sorting)
        self._update_empty_overlay()

    def _detect_alignments(self, rows, columns: int) -> dict:
        """列对齐：显式指定优先，否则整列都是数值时右对齐，否则左对齐。

        判定用「整列」而不是「逐格」——逐格判断会让同一列里有的单元格右
        对齐、有的左对齐，正是数值列看着乱的根因。
        """
        aligns = {}
        for c in range(columns):
            if c in self._align_override:
                aligns[c] = _ALIGN_FLAGS[self._align_override[c]]
                continue
            values = [r[c] for r in rows if c < len(r) and r[c] is not None
                      and str(r[c]).strip() != ""]
            numeric = bool(values) and all(
                isinstance(v, (int, float)) and not isinstance(v, bool)
                for v in values
            )
            aligns[c] = _ALIGN_FLAGS["right" if numeric else "left"]
        return aligns

    def _apply_header_alignment(self, aligns: dict) -> None:
        """把列对齐同步到表头——表头与单元格必须同向，否则行列关系错乱。"""
        header = self.horizontalHeader()
        for c in range(self.columnCount()):
            flags = aligns.get(c, _ALIGN_FLAGS["left"])
            item = self.horizontalHeaderItem(c)
            if item is not None:
                item.setTextAlignment(flags)

    def set_column_alignment(self, column: int, align: str) -> None:
        """指定列对齐：``"left"`` / ``"right"`` / ``"center"``。

        立即作用于已有单元格与表头（不需要重新 ``set_data``）。
        """
        if align not in _ALIGN_FLAGS:
            raise ValueError(
                f"未知列对齐: {align!r}，应为 {tuple(_ALIGN_FLAGS)} 之一")
        self._align_override[int(column)] = align
        flags = _ALIGN_FLAGS[align]
        item = self.horizontalHeaderItem(int(column))
        if item is not None:
            item.setTextAlignment(flags)
        for r in range(self.rowCount()):
            cell = self.item(r, int(column))
            if cell is not None:
                cell.setTextAlignment(flags)

    def column_alignment(self, column: int) -> str:
        """返回列对齐名（显式指定优先，否则按数据判定）。"""
        column = int(column)
        if column in self._align_override:
            return self._align_override[column]
        values = [self.item(r, column).text() if self.item(r, column) else ""
                  for r in range(self.rowCount())]
        return "right" if values and all(self._is_number(v) for v in values) else "left"

    @staticmethod
    def _is_number(text: str) -> bool:
        try:
            float(text.replace(",", ""))
        except ValueError:
            return False
        return True

    def set_empty_text(self, text: str) -> None:
        """设置空状态占位文本。"""
        self._empty_text = text
        self._update_empty_overlay()

    def empty_text(self) -> str:
        return self._empty_text

    def set_compact(self, compact: bool) -> None:
        """紧凑（22px）/ 常规（28px）行高切换，表头高度同步跟随。"""
        self.set_row_height(_ROW_H_COMPACT if compact else _ROW_H)

    def set_row_height(self, height: int) -> None:
        """设置统一行高（px），表头高度同步跟随，保持纵向节奏一致。"""
        self._row_h = max(16, int(height))
        self.verticalHeader().setDefaultSectionSize(self._row_h)
        self.horizontalHeader().setFixedHeight(self._row_h)

    def row_height(self) -> int:
        return self._row_h

    # ------------------------------------------------------------------ 空态
    def _update_empty_overlay(self) -> None:
        """空态占位跟随视口几何与行数状态。"""
        viewport = self.viewport()
        self._empty_label.setGeometry(viewport.rect())
        # 视口变窄时空态文案省略，而不是被硬切（长文案如「暂无符合条件的数据」）
        fm = self._empty_label.fontMetrics()
        self._empty_label.setText(
            fm.elidedText(self._empty_text, Qt.ElideRight,
                          max(0, viewport.width() - T("space.6"))))
        self._empty_label.setVisible(self.rowCount() == 0)
        self._empty_label.raise_()

    def eventFilter(self, watched, event) -> bool:
        if watched is self.viewport() and event.type() == QEvent.Resize:
            self._update_empty_overlay()
        return super().eventFilter(watched, event)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._update_empty_overlay()