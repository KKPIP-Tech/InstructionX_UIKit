# -*- coding: utf-8 -*-
"""面包屑导航 Breadcrumb（SPEC §5.3 breadcrumb.py）。

分隔符可配置，末级加粗显示，非末级可点击并发出 itemClicked 信号。
"""

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QWidget

from ..theme import T, ThemeManager, set_property
from shiboken6 import isValid as _shiboken_is_valid


def _connect_theme(widget, slot) -> None:
    """连接主题切换信号；控件销毁后自动忽略回调。"""
    ThemeManager.instance().theme_changed.connect(
        lambda *_: slot() if _shiboken_is_valid(widget) else None)

__all__ = ["Breadcrumb"]


class Breadcrumb(QWidget):
    """面包屑导航，展示当前页面在层级中的位置。

    参数:
        items: 初始层级文本列表，如 ``["首页", "组件", "面包屑"]``。
        separator: 分隔符，默认 ``"/"``。
        parent: 父控件。

    示例::

        bc = Breadcrumb(["首页", "组件", "面包屑"])
        bc.set_separator(">")
        bc.itemClicked.connect(lambda i, t: print(i, t))
    """

    #: 点击非末级项时发射，参数为 (索引, 文本)
    itemClicked = Signal(int, str)

    def __init__(self, items=None, separator: str = "/", parent: QWidget = None):
        super().__init__(parent)
        self._items = [str(x) for x in (items or [])]
        self._separator = separator
        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(6)
        _connect_theme(self, self._reload_style)
        self._reload_style()
        self._rebuild()

    # -- 公开 API ---------------------------------------------------------
    def set_items(self, items) -> None:
        """设置层级文本列表。"""
        self._items = [str(x) for x in items]
        self._rebuild()

    def items(self) -> list:
        """返回当前层级文本列表。"""
        return list(self._items)

    def set_separator(self, separator: str) -> None:
        """设置分隔符。"""
        self._separator = separator
        self._rebuild()

    def separator(self) -> str:
        """返回当前分隔符。"""
        return self._separator

    # -- 内部 -------------------------------------------------------------
    def _rebuild(self) -> None:
        while self._layout.count():
            item = self._layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        n = len(self._items)
        for i, text in enumerate(self._items):
            if i < n - 1:
                btn = QPushButton(text, self)
                btn.setCursor(Qt.PointingHandCursor)
                btn.clicked.connect(
                    lambda _=False, idx=i: self.itemClicked.emit(
                        idx, self._items[idx]))
                self._layout.addWidget(btn)
                sep = QLabel(self._separator, self)
                set_property(sep, "role", "tertiary")
                self._layout.addWidget(sep)
            else:
                last = QLabel(text, self)
                set_property(last, "uikBcLast", "true")
                self._layout.addWidget(last)
        self._layout.addStretch(1)

    def _reload_style(self) -> None:
        c = lambda k: T(f"color.{k}")  # noqa: E731
        self.setStyleSheet(f"""
QPushButton {{
    border: none;
    background-color: transparent;
    color: {c('text.secondary')};
    padding: 0 2px;
    min-height: 22px;
    max-height: 22px;
}}
QPushButton:hover {{ color: {c('primary')}; }}
QPushButton:pressed {{ color: {c('primary.pressed')}; }}
QLabel[uikBcLast="true"] {{
    color: {c('text.primary')};
    font-weight: 600;
}}
""")
