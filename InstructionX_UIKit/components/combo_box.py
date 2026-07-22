# -*- coding: utf-8 -*-
"""下拉选择框组件（SPEC §5.1）。

``ComboBox`` 基于 QComboBox，下拉弹层样式由全局 QSS 提供；
``searchable=True`` 时变为可编辑并附带「包含匹配」的 QCompleter，
输入即过滤候选，编辑结束时自动回退到合法选项。
"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QComboBox, QCompleter

from ..theme import set_property

__all__ = ["ComboBox"]

_SIZES = ("sm", "md", "lg")


class ComboBox(QComboBox):
    """下拉选择框。

    用途:
        单选下拉；可选搜索过滤模式（输入关键字即时过滤候选）。

    参数:
        items: 选项字符串列表。
        size: ``sm`` / ``md`` / ``lg``，高度 24 / 32 / 40。
        searchable: 是否可输入搜索过滤。
        placeholder: 搜索模式下的占位提示。
        parent: 父控件。

    示例::

        city = ComboBox(["北京", "上海", "广州"], searchable=True)
        city.currentTextChanged.connect(print)
    """

    def __init__(self, items=(), size: str = "md", searchable: bool = False,
                 placeholder: str = "", parent=None):
        super().__init__(parent)
        self._last_valid = -1
        if items:
            self.addItems([str(x) for x in items])
        self.set_size(size)
        self._searchable = False
        if searchable:
            self.set_searchable(True, placeholder=placeholder)
        self.currentIndexChanged.connect(self._track_valid)
        self._track_valid(self.currentIndex())

    # ------------------------------------------------------------------
    # 尺寸
    # ------------------------------------------------------------------

    def set_size(self, size: str) -> None:
        """设置尺寸档：``sm`` / ``md`` / ``lg``。"""
        if size not in _SIZES:
            raise ValueError(f"未知下拉框尺寸: {size!r}")
        set_property(self, "size", size)

    def size_name(self) -> str:
        """当前尺寸档名。"""
        return self.property("uiksize") or "md"

    # ------------------------------------------------------------------
    # 搜索过滤
    # ------------------------------------------------------------------

    def set_searchable(self, on: bool, placeholder: str = "") -> None:
        """开关搜索过滤模式。"""
        on = bool(on)
        if on == self._searchable:
            return
        self._searchable = on
        self.setEditable(on)
        if on:
            self.setInsertPolicy(QComboBox.NoInsert)
            line = self.lineEdit()
            if placeholder:
                line.setPlaceholderText(placeholder)
            completer = QCompleter(self.model(), self)
            completer.setCompletionMode(QCompleter.PopupCompletion)
            completer.setFilterMode(Qt.MatchContains)
            completer.setCaseSensitivity(Qt.CaseInsensitive)
            self.setCompleter(completer)
            line.editingFinished.connect(self._on_editing_finished)
        else:
            self.setCompleter(None)

    def is_searchable(self) -> bool:
        """是否处于搜索过滤模式。"""
        return self._searchable

    def _on_editing_finished(self) -> None:
        """编辑结束：文本匹配到选项则选中，否则回退到上次合法选项。"""
        text = self.lineEdit().text()
        idx = self.findText(text, Qt.MatchFixedString)
        if idx >= 0:
            self.setCurrentIndex(idx)
        elif self._last_valid >= 0 and self.count() > 0:
            self.setCurrentIndex(self._last_valid)
        elif self.count() == 0:
            self.lineEdit().clear()

    def _track_valid(self, index: int) -> None:
        if index >= 0:
            self._last_valid = index

    # ------------------------------------------------------------------
    # 选项管理
    # ------------------------------------------------------------------

    def set_items(self, items) -> None:
        """整体替换选项列表。"""
        self.clear()
        self.addItems([str(x) for x in items])
        self._last_valid = self.currentIndex()

    def items(self) -> list:
        """当前全部选项文案。"""
        return [self.itemText(i) for i in range(self.count())]
