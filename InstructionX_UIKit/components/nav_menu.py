# -*- coding: utf-8 -*-
"""侧边导航菜单 NavMenu（SPEC §5.3 nav_menu.py）。

支持分组、分组折叠（带主题感知箭头图标）、选中项左侧指示条。
"""

from PySide6.QtCore import QPointF, Qt, Signal
from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QPushButton, QVBoxLayout, QWidget

from ..theme import T, ThemeManager, set_property
from shiboken6 import isValid as _shiboken_is_valid


def _connect_theme(widget, slot) -> None:
    """连接主题切换信号；控件销毁后自动忽略回调。"""
    ThemeManager.instance().theme_changed.connect(
        lambda *_: slot() if _shiboken_is_valid(widget) else None)

__all__ = ["NavMenu"]


def _chevron_icon(direction: str) -> QIcon:
    """绘制 12x12 主题感知的折叠箭头图标。"""
    pm = QPixmap(12, 12)
    pm.fill(Qt.transparent)
    painter = QPainter(pm)
    painter.setRenderHint(QPainter.Antialiasing)
    pen = QPen(QColor(T("color.text.tertiary")))
    pen.setWidthF(1.5)
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    painter.setPen(pen)
    pts = {
        "down": [(2.8, 4.6), (6.0, 7.8), (9.2, 4.6)],
        "right": [(4.6, 2.8), (7.8, 6.0), (4.6, 9.2)],
    }[direction]
    painter.drawPolyline([QPointF(x, y) for x, y in pts])
    painter.end()
    return QIcon(pm)


class NavMenu(QWidget):
    """侧边导航菜单：分组、折叠、选中条指示。

    参数:
        parent: 父控件。

    示例::

        nav = NavMenu()
        nav.add_group("概览")
        nav.add_item("dash", "仪表盘", group="概览")
    """

    #: 选中项变化信号，参数为 item key
    currentChanged = Signal(str)

    def __init__(self, parent: QWidget = None):
        super().__init__(parent)
        self._stack = QVBoxLayout(self)
        self._stack.setContentsMargins(8, 8, 8, 8)
        self._stack.setSpacing(2)
        self._stack.addStretch(1)
        self._groups = {}   # title -> {"header", "body", "layout", "collapsed", "collapsible"}
        self._items = {}    # key -> QPushButton
        self._current = None
        _connect_theme(self, self._reload_style)
        self._reload_style()

    # -- 公开 API ---------------------------------------------------------
    def add_group(self, title: str, collapsible: bool = True) -> None:
        """添加分组；``collapsible`` 为 True 时点击组头可折叠/展开。"""
        header = QPushButton(title, self)
        set_property(header, "uikNav", "group")
        header.setCursor(Qt.PointingHandCursor if collapsible
                         else Qt.ArrowCursor)
        body = QWidget(self)
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(0, 0, 0, 4)
        body_layout.setSpacing(2)
        info = {"header": header, "body": body, "collapsed": False,
                "collapsible": collapsible}
        self._groups[title] = info
        if collapsible:
            header.clicked.connect(
                lambda _=False, t=title: self.set_collapsed(
                    t, not self._groups[t]["collapsed"]))
        idx = self._stack.count() - 1
        self._stack.insertWidget(idx, header)
        self._stack.insertWidget(idx + 1, body)
        self._refresh_group_icon(title)

    def add_item(self, key: str, text: str, icon: QIcon = None,
                 group: str = None) -> None:
        """添加导航项；``group`` 为分组标题，None 表示顶层项。"""
        btn = QPushButton(text, self)
        set_property(btn, "uikNav", "item")
        set_property(btn, "indent", "true" if group else "false")
        set_property(btn, "selected", "false")
        if icon is not None:
            btn.setIcon(icon)
        btn.setCursor(Qt.PointingHandCursor)
        btn.clicked.connect(lambda _=False, k=key: self.set_current(k))
        self._items[key] = btn
        if group is not None:
            if group not in self._groups:
                self.add_group(group)
            self._groups[group]["body"].layout().addWidget(btn)
        else:
            self._stack.insertWidget(self._stack.count() - 1, btn)

    def set_current(self, key: str) -> None:
        """设置选中项（选中条指示跟随）。"""
        if key not in self._items:
            raise KeyError(f"未知导航项: {key!r}")
        if key == self._current:
            return
        self._current = key
        for k, btn in self._items.items():
            set_property(btn, "selected", "true" if k == key else "false")
        self.currentChanged.emit(key)

    def current(self) -> str:
        """返回当前选中项 key。"""
        return self._current

    def set_collapsed(self, title: str, collapsed: bool) -> None:
        """折叠 / 展开指定分组。"""
        info = self._groups[title]
        info["collapsed"] = bool(collapsed)
        info["body"].setVisible(not collapsed)
        self._refresh_group_icon(title)

    def is_collapsed(self, title: str) -> bool:
        """返回分组是否处于折叠状态。"""
        return self._groups[title]["collapsed"]

    # -- 内部 -------------------------------------------------------------
    def _refresh_group_icon(self, title: str) -> None:
        info = self._groups[title]
        if info["collapsible"]:
            info["header"].setIcon(
                _chevron_icon("right" if info["collapsed"] else "down"))

    def _reload_style(self) -> None:
        c = lambda k: T(f"color.{k}")  # noqa: E731
        self.setStyleSheet(f"""
QPushButton[uikNav="group"] {{
    border: none;
    background-color: transparent;
    color: {c('text.tertiary')};
    text-align: left;
    font-size: {T('font.xs')}px;
    font-weight: 600;
    padding: 0 8px;
    min-height: 26px;
    max-height: 26px;
}}
QPushButton[uikNav="item"] {{
    border: none;
    border-left: 3px solid transparent;
    background-color: transparent;
    color: {c('text.secondary')};
    text-align: left;
    padding: 0 12px;
    border-radius: {T('radius.md')}px;
    min-height: 32px;
    max-height: 32px;
}}
QPushButton[uikNav="item"][indent="true"] {{ padding-left: 22px; }}
QPushButton[uikNav="item"]:hover {{
    background-color: {c('bg.muted')};
    color: {c('text.primary')};
}}
QPushButton[uikNav="item"][selected="true"] {{
    background-color: {c('primary.subtle')};
    color: {c('primary')};
    font-weight: 600;
    border-left-color: {c('primary')};
}}
""")
        for title in self._groups:
            self._refresh_group_icon(title)
