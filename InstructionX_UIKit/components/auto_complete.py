# -*- coding: utf-8 -*-
"""自动完成输入框组件（SPEC §5.1）。

``AutoComplete`` 继承 ``LineEdit``，基于 QCompleter + QStringListModel
实现候选弹层；输入经防抖（延迟取 ``tokens.DURATION["normal"]``）后再过滤，
避免逐键刷新造成的闪烁。
"""

from PySide6.QtCore import QStringListModel, Qt, QTimer
from PySide6.QtWidgets import QCompleter

from ..tokens import DURATION
from .line_edit import LineEdit

__all__ = ["AutoComplete"]


class AutoComplete(LineEdit):
    """自动完成输入框。

    用途:
        输入时按「包含匹配」弹出候选列表，防抖延迟后过滤，
        选中候选即回填输入框。

    参数:
        items: 候选字符串列表。
        placeholder: 占位提示。
        delay: 防抖延迟（毫秒），默认 ``DURATION["normal"]``。
        parent: 父控件。

    示例::

        ac = AutoComplete(["苹果", "香蕉", "橙子"], placeholder="搜索水果")
        ac.set_items(["北京", "上海", "广州"])
        ac.textChanged.connect(print)
    """

    def __init__(self, items=(), placeholder: str = "", delay: int = None,
                 parent=None):
        super().__init__(placeholder=placeholder, parent=parent)
        self._all = [str(x) for x in items]
        self._delay = DURATION["normal"] if delay is None else int(delay)
        self._model = QStringListModel(self._all, self)
        self._completer = QCompleter(self._model, self)
        self._completer.setCaseSensitivity(Qt.CaseInsensitive)
        self._completer.setFilterMode(Qt.MatchContains)
        self._completer.setCompletionMode(QCompleter.PopupCompletion)
        self.setCompleter(self._completer)
        # 防抖定时器：停止输入 delay 毫秒后才真正过滤
        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(self._delay)
        self._debounce.timeout.connect(self._apply_filter)
        self.textEdited.connect(self._on_text_edited)

    # ------------------------------------------------------------------
    # 候选集管理
    # ------------------------------------------------------------------

    def set_items(self, items) -> None:
        """整体替换候选列表。"""
        self._all = [str(x) for x in items]
        self._apply_filter()

    def items(self) -> list:
        """当前候选列表。"""
        return list(self._all)

    def set_delay(self, delay: int) -> None:
        """设置防抖延迟（毫秒）。"""
        self._delay = int(delay)
        self._debounce.setInterval(self._delay)

    # ------------------------------------------------------------------
    # 延迟过滤
    # ------------------------------------------------------------------

    def _on_text_edited(self, _text: str) -> None:
        self._debounce.start()

    def _apply_filter(self) -> None:
        """防抖到期：按「包含」重建候选模型并刷新弹层。"""
        text = self.text().strip().lower()
        if not text:
            matched = list(self._all)
        else:
            matched = [s for s in self._all if text in s.lower()]
        self._model.setStringList(matched)
        self._completer.setCompletionPrefix(self.text())
        if self.hasFocus() and self.text():
            self._completer.complete()
