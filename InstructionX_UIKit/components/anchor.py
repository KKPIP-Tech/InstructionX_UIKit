# -*- coding: utf-8 -*-
"""锚点导航 Anchor（SPEC §5.3 anchor.py）。

垂直链接列表，配合 QScrollArea 使用：点击滚动到目标段落，
滚动时自动高亮当前段落。
"""

from PySide6.QtCore import QPoint, Qt, Signal
from PySide6.QtWidgets import QPushButton, QScrollArea, QVBoxLayout, QWidget

from ..theme import T, ThemeManager, set_property
from shiboken6 import isValid as _shiboken_is_valid


def _connect_theme(widget, slot) -> None:
    """连接主题切换信号；控件销毁后自动忽略回调。"""
    ThemeManager.instance().theme_changed.connect(
        lambda *_: slot() if _shiboken_is_valid(widget) else None)

__all__ = ["Anchor"]


class Anchor(QWidget):
    """锚点导航：配合 QScrollArea 高亮当前滚动到的段落。

    参数:
        parent: 父控件。

    示例::

        anchor = Anchor()
        anchor.set_items([("base", "基本信息"), ("safe", "安全设置")])
        anchor.bind_scroll_area(scroll_area)
    """

    #: 当前锚点变化信号，参数为锚点 key
    currentChanged = Signal(str)

    def __init__(self, parent: QWidget = None):
        super().__init__(parent)
        self._items = []          # [(key, title, target_widget|None)]
        self._buttons = {}        # key -> QPushButton
        self._current = None
        self._scroll_area = None
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(0)
        self._layout.addStretch(1)
        _connect_theme(self, self._reload_style)
        self._reload_style()

    # -- 公开 API ---------------------------------------------------------
    def set_items(self, items) -> None:
        """批量设置锚点。

        参数 ``items`` 为 ``[(key, title)]`` 或
        ``[(key, title, target_widget)]`` 序列。
        """
        for btn in self._buttons.values():
            self._layout.removeWidget(btn)
            btn.deleteLater()
        self._buttons.clear()
        self._items = []
        self._current = None
        for it in items:
            key, title = it[0], it[1]
            target = it[2] if len(it) > 2 else None
            self._append(key, title, target)
        if self._items:
            self.set_current(self._items[0][0])

    def add_item(self, key: str, title: str, target: QWidget = None) -> None:
        """追加一个锚点；``target`` 为滚动区域内的目标控件（可选）。"""
        self._append(key, title, target)
        if self._current is None:
            self.set_current(key)

    def set_target(self, key: str, target: QWidget) -> None:
        """为已有锚点绑定目标控件。"""
        self._items = [(k, t, target if k == key else w)
                       for k, t, w in self._items]

    def bind_scroll_area(self, area: QScrollArea) -> None:
        """绑定滚动区域，滚动时自动高亮当前段落。"""
        self._scroll_area = area
        area.verticalScrollBar().valueChanged.connect(self._on_scroll)

    def set_current(self, key: str) -> None:
        """设置当前高亮锚点。"""
        if key == self._current or key not in self._buttons:
            return
        self._current = key
        for k, btn in self._buttons.items():
            set_property(btn, "active", "true" if k == key else "false")
        self.currentChanged.emit(key)

    def current(self) -> str:
        """返回当前锚点 key。"""
        return self._current

    def scroll_to(self, key: str) -> None:
        """滚动到指定锚点对应的目标控件。"""
        if self._scroll_area is None or self._scroll_area.widget() is None:
            return
        for k, _t, target in self._items:
            if k == key and target is not None:
                y = target.mapTo(self._scroll_area.widget(), QPoint(0, 0)).y()
                self._scroll_area.verticalScrollBar().setValue(max(0, y))
                return

    # -- 内部 -------------------------------------------------------------
    def _append(self, key: str, title: str, target: QWidget) -> None:
        btn = QPushButton(title, self)
        btn.setCursor(Qt.PointingHandCursor)
        set_property(btn, "active", "false")
        btn.clicked.connect(lambda _=False, k=key: self._on_click(k))
        self._layout.insertWidget(self._layout.count() - 1, btn)
        self._buttons[key] = btn
        self._items.append((key, title, target))

    def _on_click(self, key: str) -> None:
        self.set_current(key)
        self.scroll_to(key)

    def _on_scroll(self, value: int) -> None:
        area_widget = self._scroll_area.widget() if self._scroll_area else None
        if area_widget is None:
            return
        best = None
        for key, _title, target in self._items:
            if target is None:
                continue
            y = target.mapTo(area_widget, QPoint(0, 0)).y()
            if y <= value + 8:
                best = key
            elif best is None:
                best = key
        if best is not None:
            self.set_current(best)

    def _reload_style(self) -> None:
        c = lambda k: T(f"color.{k}")  # noqa: E731
        self.setStyleSheet(f"""
QPushButton {{
    border: none;
    border-left: 2px solid {c('border')};
    border-radius: 0px;
    background-color: transparent;
    color: {c('text.secondary')};
    text-align: left;
    padding: 0 14px;
    min-height: 26px;
    max-height: 26px;
    font-size: {T('font.sm')}px;
}}
QPushButton:hover {{ color: {c('primary')}; }}
QPushButton[active="true"] {{
    color: {c('primary')};
    border-left-color: {c('primary')};
    background-color: {c('primary.subtle')};
    font-weight: 600;
}}
""")
