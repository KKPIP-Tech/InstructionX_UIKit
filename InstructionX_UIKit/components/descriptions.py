# -*- coding: utf-8 -*-
"""描述列表组件（SPEC §5.2 descriptions）。

以「标签：值」网格展示只读信息，列数可固定也可随宽度自适应；
可选描边样式（标签区底色区分）。单元格自绘，主题实时感知。
"""

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QColor, QFontMetrics, QPainter, QPen
from PySide6.QtWidgets import QGridLayout, QLabel, QVBoxLayout, QWidget

from InstructionX_UIKit.theme import T, ThemeManager

__all__ = ["Descriptions"]

_CELL_MIN_W = 220  # 自适应模式下每个单元格的最小宽度


class _DescCell(QWidget):
    """单个「标签：值」单元格（自绘，主题感知）。"""

    def __init__(self, label: str, value: str, bordered: bool = False, parent=None):
        super().__init__(parent)
        self._label = label
        self._value = value
        self._bordered = bordered
        ThemeManager.instance().theme_changed.connect(self.update)

    def sizeHint(self) -> QSize:
        fm = QFontMetrics(self.font())
        w = fm.horizontalAdvance(self._label) + fm.horizontalAdvance(self._value) + 32
        h = 36 if self._bordered else 28
        return QSize(max(_CELL_MIN_W // 2, w), h)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        font = painter.font()
        font.setPixelSize(T("font.md"))
        painter.setFont(font)
        fm = painter.fontMetrics()
        rect = self.rect()

        if self._bordered:
            label_w = max(96, fm.horizontalAdvance(self._label) + T("space.4") * 2)
            # 外框 + 标签区底色
            painter.setPen(QPen(QColor(T("color.border"))))
            painter.setBrush(QColor(T("color.bg.elevated")))
            painter.drawRect(rect.adjusted(0, 0, -1, -1))
            painter.fillRect(
                rect.adjusted(0, 0, -(rect.width() - label_w), -1),
                QColor(T("color.bg.subtle")),
            )
            painter.drawLine(label_w, 0, label_w, rect.height() - 1)
            # 文本
            painter.setPen(QColor(T("color.text.secondary")))
            painter.drawText(
                rect.adjusted(T("space.3"), 0, 0, 0).translated(0, 0),
                Qt.AlignVCenter | Qt.AlignLeft,
                self._label,
            )
            painter.setPen(QColor(T("color.text.primary")))
            painter.drawText(
                rect.adjusted(label_w + T("space.3"), 0, -T("space.2"), 0),
                Qt.AlignVCenter | Qt.AlignLeft,
                fm.elidedText(self._value, Qt.ElideRight,
                              max(8, rect.width() - label_w - T("space.5"))),
            )
        else:
            painter.setPen(QColor(T("color.text.secondary")))
            text = f"{self._label}："
            painter.drawText(rect, Qt.AlignVCenter | Qt.AlignLeft, text)
            x = fm.horizontalAdvance(text)
            painter.setPen(QColor(T("color.text.primary")))
            painter.drawText(
                rect.adjusted(x, 0, 0, 0),
                Qt.AlignVCenter | Qt.AlignLeft,
                fm.elidedText(self._value, Qt.ElideRight, max(8, rect.width() - x)),
            )
        painter.end()


class Descriptions(QWidget):
    """描述列表。

    参数:
        title: 顶部标题（可选）。
        column: 固定列数；``0`` 表示随宽度自适应（默认）。
        bordered: 描边样式（标签区带底色）。
        parent: 父控件。

    示例::

        desc = Descriptions("用户信息", bordered=True)
        desc.set_items([("姓名", "张三"), ("城市", "上海")])
        desc.add_item("邮箱", "zhang@example.com")
    """

    def __init__(self, title: str = "", column: int = 0,
                 bordered: bool = False, parent=None):
        super().__init__(parent)
        self._items = []  # [(label, value)]
        self._column = max(0, int(column))
        self._bordered = bool(bordered)
        self._cols = 0

        self._root = QVBoxLayout(self)
        self._root.setContentsMargins(0, 0, 0, 0)
        self._root.setSpacing(T("space.3"))
        self._title_label = QLabel(title, self)
        font = self._title_label.font()
        font.setPixelSize(T("font.title.sm"))
        font.setBold(True)
        self._title_label.setFont(font)
        self._title_label.setVisible(bool(title))
        self._root.addWidget(self._title_label)

        self._grid_host = QWidget(self)
        self._grid = QGridLayout(self._grid_host)
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setSpacing(1 if bordered else T("space.2"))
        self._root.addWidget(self._grid_host, 1)

    # ------------------------------------------------------------------ 数据
    def set_title(self, title: str) -> None:
        """设置标题；空串隐藏。"""
        self._title_label.setText(title)
        self._title_label.setVisible(bool(title))

    def set_items(self, items) -> None:
        """整体替换条目，``items`` 为 ``[(标签, 值), ...]``。"""
        self._items = [(str(k), str(v)) for k, v in items]
        self._rebuild()

    def add_item(self, label: str, value: str) -> None:
        """追加一个条目。"""
        self._items.append((str(label), str(value)))
        self._rebuild()

    def clear(self) -> None:
        """清空全部条目。"""
        self._items.clear()
        self._rebuild()

    def items(self):
        return list(self._items)

    # ------------------------------------------------------------------ 布局
    def _effective_cols(self) -> int:
        if self._column > 0:
            return self._column
        width = max(1, self.width())
        return max(1, min(6, width // _CELL_MIN_W))

    def _rebuild(self) -> None:
        while self._grid.count():
            item = self._grid.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
        cols = self._effective_cols()
        self._cols = cols
        for i, (label, value) in enumerate(self._items):
            cell = _DescCell(label, value, self._bordered, self._grid_host)
            self._grid.addWidget(cell, i // cols, i % cols)
        for c in range(cols):
            self._grid.setColumnStretch(c, 1)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        cols = self._effective_cols()
        if cols != self._cols and self._items:
            self._rebuild()
