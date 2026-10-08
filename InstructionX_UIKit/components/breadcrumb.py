# -*- coding: utf-8 -*-
"""面包屑导航 Breadcrumb（SPEC §5.3 breadcrumb.py）。

分隔符可配置，末级为「当前」态加粗显示，非末级可点击并发出 itemClicked
信号，支持逐级禁用。

四态约定（与 Tabs / NavMenu / Pagination / Dropdown 同一套语义）：

======== ==================== ==================================
状态      文字                 底色 / 指示
======== ==================== ==================================
当前(末级) ``text.primary``   无底色，半粗（你在这里）
常规      ``text.secondary``   透明
悬停      ``text.primary``    ``bg.muted`` 圆角底
按下      ``primary.pressed``  ``bg.muted`` 圆角底
禁用      ``text.disabled``   透明，不可点击
======== ==================== ==================================
"""

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QWidget

from ..theme import T, ThemeManager, set_property
from shiboken6 import isValid as _shiboken_is_valid


def _connect_theme(widget, slot) -> None:
    """连接主题切换信号；组件销毁时断开连接（shiboken 守卫双保险）。"""
    manager = ThemeManager.instance()
    receiver = lambda *_: slot() if _shiboken_is_valid(widget) else None
    manager.theme_changed.connect(receiver)

    def _cleanup(_obj=None):
        try:
            manager.theme_changed.disconnect(receiver)
        except (RuntimeError, TypeError):
            pass

    widget.destroyed.connect(_cleanup)

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
        bc.set_item_enabled(0, False)
    """

    #: 点击非末级项时发射，参数为 (索引, 文本)
    itemClicked = Signal(int, str)

    def __init__(self, items=None, separator: str = "/", parent: QWidget = None):
        super().__init__(parent)
        self._items = [str(x) for x in (items or [])]
        self._separator = separator
        # 与 items 等长，逐级可用性（末级恒可用：它就是「当前」）
        self._enabled = [True] * len(self._items)
        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(T("layout.icon.gap"))
        _connect_theme(self, self._reload_style)
        self._reload_style()
        self._rebuild()

    # -- 公开 API ---------------------------------------------------------
    def set_items(self, items) -> None:
        """设置层级文本列表（逐级可用性重置为全部可用）。"""
        self._items = [str(x) for x in items]
        self._enabled = [True] * len(self._items)
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

    def set_item_enabled(self, index: int, enabled: bool) -> None:
        """设置某一级的可用性；末级（当前项）恒为可用，调用忽略。"""
        if not 0 <= index < len(self._items) - 1:
            return
        self._enabled[index] = bool(enabled)
        self._rebuild()

    def item_enabled(self, index: int) -> bool:
        """返回某一级的可用性。"""
        if not 0 <= index < len(self._enabled):
            return False
        return self._enabled[index]

    # -- 内部 -------------------------------------------------------------
    def _rebuild(self) -> None:
        while self._layout.count():
            item = self._layout.takeAt(0)
            w = item.widget()
            if w is not None:
                # 先脱离父级再 deleteLater：deleteLater 要等下一轮事件循环
                # 才真正析构，在那之前旧控件仍是子控件，会以未布局的默认
                # 几何（原点、默认 sizeHint）留在版面里——既可能被审计判成
                # OVERFLOW/COLLIDE，渲染上也会短暂重叠。
                w.setParent(None)
                w.deleteLater()
        n = len(self._items)
        for i, text in enumerate(self._items):
            if i < n - 1:
                enabled = self._enabled[i] if i < len(self._enabled) else True
                btn = QPushButton(text, self)
                set_property(btn, "uikBc", "item")
                # 高度改由全局 [uiksize="sm"] 提供（内容盒 20 + 边框 1 = 22），
                # 本地 QSS 不再写死 min/max-height，避免与尺寸令牌打架
                set_property(btn, "size", "sm")
                btn.setEnabled(enabled)
                btn.setCursor(
                    Qt.PointingHandCursor if enabled else Qt.ArrowCursor)
                if enabled:
                    btn.clicked.connect(
                        lambda _=False, idx=i: self.itemClicked.emit(
                            idx, self._items[idx]))
                self._layout.addWidget(btn)
                sep = QLabel(self._separator, self)
                set_property(sep, "uikBc", "sep")
                # 分隔符本身只有一个字形宽（"/" 约 7px），比可点击目标小；
                # 给一个最小宽度，既保证它在高密度行里有稳定的左右留白，
                # 也避免被版面审计判成「过小、不可点」。
                sep.setMinimumWidth(T("space.2"))
                self._layout.addWidget(sep)
            else:
                last = QLabel(text, self)
                set_property(last, "uikBc", "last")
                self._layout.addWidget(last)
        self._layout.addStretch(1)

    def _reload_style(self) -> None:
        c = lambda k: T(f"color.{k}")  # noqa: E731
        radius = T("radius.sm")
        self.setStyleSheet(f"""
QPushButton[uikBc="item"] {{
    border: 1px solid transparent;
    background-color: transparent;
    color: {c('text.secondary')};
    border-radius: {radius}px;
    padding: 0 {T('space.1')}px;
    font-size: {T('font.md')}px;
}}
QPushButton[uikBc="item"]:hover {{
    background-color: {c('bg.muted')};
    color: {c('text.primary')};
}}
QPushButton[uikBc="item"]:pressed {{
    background-color: {c('bg.muted')};
    color: {c('primary.pressed')};
}}
QPushButton[uikBc="item"]:disabled {{
    background-color: transparent;
    color: {c('text.disabled')};
}}
QLabel[uikBc="sep"] {{
    color: {c('text.disabled')};
    background-color: transparent;
}}
QLabel[uikBc="last"] {{
    color: {c('text.primary')};
    font-weight: {T('font.weight.semibold')};
    background-color: transparent;
}}
""")