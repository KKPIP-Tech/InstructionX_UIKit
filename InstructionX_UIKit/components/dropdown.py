# -*- coding: utf-8 -*-
"""下拉菜单按钮 DropdownButton（SPEC §5.3 dropdown.py）。

QPushButton + QMenu 封装：菜单项支持图标 / 快捷键 / 危险项，
按钮右侧自绘主题感知的下拉箭头。
"""

from PySide6.QtCore import QPointF, Qt, Signal
from PySide6.QtGui import QColor, QIcon, QPainter, QPen
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QMenu,
    QPushButton,
    QWidget,
    QWidgetAction,
)

from ..theme import T, ThemeManager
from shiboken6 import isValid as _shiboken_is_valid


def _connect_theme(widget, slot) -> None:
    """连接主题切换信号；控件销毁后自动忽略回调。"""
    ThemeManager.instance().theme_changed.connect(
        lambda *_: slot() if _shiboken_is_valid(widget) else None)

__all__ = ["DropdownButton"]


class _DangerItem(QWidget):
    """危险菜单项（QWidgetAction 的默认控件），悬停高亮、点击触发。"""

    clicked = Signal()

    def __init__(self, text: str, parent: QWidget = None):
        super().__init__(parent)
        self.setCursor(Qt.PointingHandCursor)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 0, 12, 0)
        layout.setSpacing(8)
        self._label = QLabel(text, self)
        layout.addWidget(self._label)
        layout.addStretch(1)
        self.setFixedHeight(30)
        self.setMinimumWidth(140)
        _connect_theme(self, self._reload_style)
        self._reload_style()

    def _reload_style(self) -> None:
        c = lambda k: T(f"color.{k}")  # noqa: E731
        self.setStyleSheet(f"""
_DangerItem {{
    background-color: transparent;
    border-radius: {T('radius.sm')}px;
}}
_DangerItem:hover {{ background-color: {c('danger.subtle')}; }}
_DangerItem QLabel {{ color: {c('danger')}; background-color: transparent; }}
""")

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self.clicked.emit()
            event.accept()
            return
        super().mouseReleaseEvent(event)


class DropdownButton(QPushButton):
    """下拉菜单按钮：点击弹出 QMenu，项可带图标 / 快捷键 / 危险样式。

    参数:
        text: 按钮文本。
        parent: 父控件。

    示例::

        dd = DropdownButton("操作")
        dd.add_item("edit", "编辑", shortcut="Ctrl+E")
        dd.add_item("del", "删除", danger=True)
    """

    #: 任意菜单项被触发时发射，参数为该项 key
    triggered = Signal(str)

    def __init__(self, text: str = "", parent: QWidget = None):
        super().__init__(text, parent)
        self._menu = QMenu(self)
        self.setMenu(self._menu)
        # 为右侧自绘箭头预留空间；同时把 ::menu-indicator 尺寸清零。
        # 主题 QSS 仅定义了 QToolButton::menu-indicator，QPushButton 挂菜单后
        # QStyleSheetStyle 会回退基础样式再画一个下拉三角，与 paintEvent 的
        # 自绘箭头并存形成“双箭头”。theme.py 的通用规则无法按组件排除，
        # 故在本组件局部 QSS 中隐藏样式箭头，仅保留主题感知的自绘箭头。
        self.setStyleSheet(
            "QPushButton { padding-right: 22px; }"
            "QPushButton::menu-indicator { width: 0px; height: 0px; }"
        )
        _connect_theme(self, self.update)

    # -- 公开 API ---------------------------------------------------------
    def menu(self) -> QMenu:
        """返回内部 QMenu，便于追加自定义 QAction。"""
        return self._menu

    def add_item(self, key: str, text: str, icon: QIcon = None,
                 shortcut: str = None, danger: bool = False,
                 enabled: bool = True, callback=None):
        """添加菜单项。

        参数:
            key: 项标识，触发时随 ``triggered`` 信号发射。
            text: 显示文本。
            icon: 可选 QIcon。
            shortcut: 可选快捷键文本，如 ``"Ctrl+E"``。
            danger: 是否危险项（红色高亮样式）。
            enabled: 是否可用。
            callback: 触发回调，签名为 ``callback(key)``。
        """
        if danger:
            wa = QWidgetAction(self._menu)
            w = _DangerItem(text, self._menu)
            wa.setDefaultWidget(w)
            self._menu.addAction(wa)
            wa.setEnabled(enabled)
            w.setEnabled(enabled)
            w.clicked.connect(
                lambda k=key, cb=callback: self._activate(k, cb))
            return wa
        action = self._menu.addAction(text)
        if icon is not None:
            action.setIcon(icon)
        if shortcut:
            action.setShortcut(shortcut)
        action.setEnabled(enabled)
        action.triggered.connect(
            lambda _=False, k=key, cb=callback: self._fire(k, cb))
        return action

    def set_items(self, items) -> None:
        """批量设置菜单项，每项为 dict（键同 ``add_item`` 参数）。"""
        self._menu.clear()
        for it in items:
            if it.get("separator"):
                self.add_separator()
            else:
                self.add_item(**{k: v for k, v in it.items() if k != "separator"})

    def add_separator(self) -> None:
        """添加分隔线。"""
        self._menu.addSeparator()

    # -- 内部 -------------------------------------------------------------
    def _activate(self, key: str, callback) -> None:
        self._menu.close()
        self._fire(key, callback)

    def _fire(self, key: str, callback) -> None:
        self.triggered.emit(key)
        if callable(callback):
            callback(key)

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        # 主题感知的下拉箭头
        color = T("color.text.disabled") if not self.isEnabled() \
            else T("color.text.secondary")
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        pen = QPen(QColor(color))
        pen.setWidthF(1.5)
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        painter.setPen(pen)
        cx = self.width() - 13.0
        cy = self.height() / 2.0
        painter.drawPolyline([
            QPointF(cx - 3.2, cy - 1.6),
            QPointF(cx, cy + 1.6),
            QPointF(cx + 3.2, cy - 1.6),
        ])
        painter.end()
