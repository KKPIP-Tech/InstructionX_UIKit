# -*- coding: utf-8 -*-
"""下拉选择框组件（SPEC §5.1）。

``ComboBox`` 基于 QComboBox，下拉弹层样式由全局 QSS 提供；
``searchable=True`` 时变为可编辑并附带「包含匹配」的 QCompleter，
输入即过滤候选，编辑结束时自动回退到合法选项。

本轮修复（轨道 2）：

- **两种模式文字左缘对齐**：可编辑模式下全局 QSS 给内嵌 ``QLineEdit``
  加了 ``0 4px`` 内边距，导致同一控件「可编辑 / 不可编辑」两种状态的
  文字左缘差 5px。组件按不可编辑档的左边距把内嵌编辑框内边距归零，
  两态文字左缘严格一致（契约 §3）。
- **弹层圆角归位**：全局 QSS 的下拉面板用了 ``radius.md``，而契约 §4
  规定「下拉面板」用 ``radius.lg``，且与 ``QMenu``（级联选择器）不一致。
  组件把弹层圆角改由 ``T("radius.lg")`` 驱动，与菜单 / 对话框浮层同档。
- 文档中的高度刻度由旧的 24 / 32 / 40 更正为契约的 22 / 28 / 34。
"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QComboBox, QCompleter

from ..theme import T
from ._mixin import SizeMixin

__all__ = ["ComboBox"]


def popup_radius_qss() -> str:
    """下拉 / 补全弹层的圆角 QSS（仅覆盖圆角，其余仍走全局 QSS）。

    契约 §4：浮层（Dialog / Drawer / Popover / Menu / 下拉面板）用
    ``radius.lg``；全局 QSS 目前给下拉面板的是 ``radius.md``，与 ``QMenu``
    不一致。组件侧以令牌覆盖，主题侧建议统一（见 deliverable 共享层需求）。
    """
    return f"QAbstractItemView {{ border-radius: {int(T('radius.lg'))}px; }}"


class ComboBox(SizeMixin, QComboBox):
    """下拉选择框。

    用途:
        单选下拉；可选搜索过滤模式（输入关键字即时过滤候选）。

    参数:
        items: 选项字符串列表。
        size: ``sm`` / ``md`` / ``lg``，高度 22 / 28 / 34。
        searchable: 是否可输入搜索过滤。
        placeholder: 搜索模式下的占位提示。
        parent: 父控件。

    示例::

        city = ComboBox(["北京", "上海", "广州"], searchable=True)
        city.currentTextChanged.connect(print)

    备注:
        搜索模式下编辑结束（失焦 / 回车）时按**精确匹配**回退：编辑文本
        与某选项完全相等（区分大小写，如 "abc" 不匹配选项 "Abc"）则选中
        该选项，否则回退到上次合法选项；无任何选项时清空编辑框。
    """

    #: 合法尺寸档（SizeMixin 校验用）
    _SIZES = ("sm", "md", "lg")
    _size_label = "下拉框"

    def __init__(self, items=(), size: str = "md", searchable: bool = False,
                 placeholder: str = "", parent=None):
        super().__init__(parent)
        self._last_valid = -1
        self._searchable = False   # 须早于 set_size：_apply_size 会读它
        if items:
            self.addItems([str(x) for x in items])
        self.set_size(size)
        # 弹层圆角：一次性设置（view() 首次调用即创建并缓存）
        self.view().setStyleSheet(popup_radius_qss())
        if searchable:
            self.set_searchable(True, placeholder=placeholder)
        self.currentIndexChanged.connect(self._track_valid)
        self._track_valid(self.currentIndex())

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
            self._align_search_field()
            completer = QCompleter(self.model(), self)
            completer.setCompletionMode(QCompleter.PopupCompletion)
            completer.setFilterMode(Qt.MatchContains)
            completer.setCaseSensitivity(Qt.CaseInsensitive)
            completer.popup().setStyleSheet(popup_radius_qss())
            self.setCompleter(completer)
            line.editingFinished.connect(self._on_editing_finished)
        else:
            self.setCompleter(None)

    def _align_search_field(self) -> None:
        """让可编辑模式的文字左缘与不可编辑模式严格一致。

        不可编辑模式的文字起点 = 边框 1px + 全局左边距 ``space.3``；
        内嵌 ``QLineEdit`` 自身又被全局 QSS 加了 4px 左内边距，两态因此
        差 5px。这里把内嵌编辑框内边距归零（0 不是魔数），并把尺寸档
        透传给它，使字号随 sm / md / lg 同步。
        """
        line = self.lineEdit()
        if line is None:
            return
        line.setStyleSheet("QLineEdit { padding: 0; }")
        line.setProperty("size", self.size_name())
        line.setProperty("uiksize", self.size_name())
        line.style().unpolish(line)
        line.style().polish(line)

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

    def _apply_size(self, size: str) -> None:
        """SizeMixin 钩子：尺寸档变化时同步内嵌编辑框（可编辑模式）。"""
        if self._searchable:
            self._align_search_field()

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
