# -*- coding: utf-8 -*-
"""穿梭框组件（SPEC §5.1）。

``Transfer`` = 源列表 + 目标列表（双 QListWidget）+ 左右移动按钮，
支持多选移动、双击移动与标题定制。
"""

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..theme import set_property

__all__ = ["Transfer"]


class Transfer(QWidget):
    """穿梭框。

    用途:
        在两个列表之间移动条目（如权限分配、字段挑选）。
        选中若干项后点击方向按钮移动，也可双击单项移动。

    参数:
        items: 初始全部条目（默认放入源列表）。
        source_title / target_title: 左右列表标题。
        parent: 父控件。

    示例::

        tr = Transfer(["苹果", "香蕉", "橙子", "葡萄"])
        tr.changed.connect(lambda target: print("已选:", target))
        print(tr.target_items())
    """

    #: 目标列表变化信号（参数为目标条目文案列表）
    changed = Signal(list)

    def __init__(self, items=(), source_title: str = "源列表",
                 target_title: str = "目标列表", parent=None):
        super().__init__(parent)
        self._source_title = QLabel(source_title, self)
        self._target_title = QLabel(target_title, self)
        for label in (self._source_title, self._target_title):
            set_property(label, "role", "secondary")
        self._source = QListWidget(self)
        self._target = QListWidget(self)
        for lst in (self._source, self._target):
            lst.setSelectionMode(QListWidget.ExtendedSelection)
            lst.setMinimumHeight(160)
            lst.setMinimumWidth(160)
        self._btn_right = QPushButton("→", self)
        self._btn_left = QPushButton("←", self)
        for btn in (self._btn_right, self._btn_left):
            set_property(btn, "size", "sm")
            btn.setFixedWidth(40)
        self._btn_right.setToolTip("移动选中项到目标列表")
        self._btn_left.setToolTip("移动选中项回源列表")
        self._btn_right.clicked.connect(lambda: self._move(self._source, self._target))
        self._btn_left.clicked.connect(lambda: self._move(self._target, self._source))
        self._source.itemDoubleClicked.connect(
            lambda _item: self._move(self._source, self._target))
        self._target.itemDoubleClicked.connect(
            lambda _item: self._move(self._target, self._source))

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        left = QVBoxLayout()
        left.setSpacing(4)
        left.addWidget(self._source_title)
        left.addWidget(self._source, 1)
        layout.addLayout(left, 1)
        mid = QVBoxLayout()
        mid.addStretch(1)
        mid.addWidget(self._btn_right)
        mid.addWidget(self._btn_left)
        mid.addStretch(1)
        layout.addLayout(mid)
        right = QVBoxLayout()
        right.setSpacing(4)
        right.addWidget(self._target_title)
        right.addWidget(self._target, 1)
        layout.addLayout(right, 1)

        self._all = []
        if items:
            self.set_items(items)

    # ------------------------------------------------------------------
    # 数据接口
    # ------------------------------------------------------------------

    def set_items(self, items) -> None:
        """设置全部条目（重置为：全部在源列表）。"""
        self._all = [str(x) for x in items]
        self._source.clear()
        self._target.clear()
        for text in self._all:
            QListWidgetItem(text, self._source)
        self._emit_changed()

    def source_items(self) -> list:
        """源列表条目文案。"""
        return [self._source.item(i).text() for i in range(self._source.count())]

    def target_items(self) -> list:
        """目标列表条目文案。"""
        return [self._target.item(i).text() for i in range(self._target.count())]

    def set_target_items(self, items) -> None:
        """指定目标条目；其余（在全集中）留在源列表。"""
        targets = [str(x) for x in items]
        self._source.clear()
        self._target.clear()
        for text in self._all:
            if text in targets:
                QListWidgetItem(text, self._target)
            else:
                QListWidgetItem(text, self._source)
        # 允许目标包含全集之外的条目
        for text in targets:
            if text not in self._all:
                QListWidgetItem(text, self._target)
        self._emit_changed()

    def set_titles(self, source_title: str, target_title: str) -> None:
        """修改左右列表标题。"""
        self._source_title.setText(source_title)
        self._target_title.setText(target_title)

    # ------------------------------------------------------------------
    # 移动逻辑
    # ------------------------------------------------------------------

    def _move(self, src: QListWidget, dst: QListWidget) -> None:
        rows = sorted((src.row(i) for i in src.selectedItems()), reverse=True)
        if not rows:
            return
        # 逆序取出避免行号位移，再按原相对顺序追加到目标列表
        taken = [src.takeItem(row) for row in rows]
        for item in reversed(taken):
            if item is not None:
                dst.addItem(item)
        dst.clearSelection()
        self._emit_changed()

    def _emit_changed(self) -> None:
        self.changed.emit(self.target_items())
