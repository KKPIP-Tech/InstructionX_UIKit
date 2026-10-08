# -*- coding: utf-8 -*-
"""下拉菜单按钮 DropdownButton（SPEC §5.3 dropdown.py）。

QPushButton + QMenu 封装：菜单项支持图标 / 快捷键 / 危险项，
按钮右侧自绘主题感知的下拉箭头。

四态约定（与 Tabs / NavMenu / Breadcrumb / Pagination 同一套语义）：

======== ==================== =================================
状态      文字                 底色
======== ==================== =================================
常规      ``text.primary``    透明
悬停      ``primary``        ``primary.subtle``（全局 QMenu 规则）
选中/按下  ``primary``        ``primary.subtle``
禁用      ``text.disabled``   透明，箭头同为 ``text.disabled``
危险项    ``danger``         ``danger.subtle``
======== ==================== =================================
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

__all__ = ["DropdownButton"]

#: 箭头离右边缘的距离（``space.2``）
_ARROW_INSET = T("space.2")
#: 箭头半宽：绘制时以 12px 画布为基准等比缩放
_ARROW_HALF = 3.2
#: 按钮右侧为箭头预留的空白（``space.4``），比箭头 inset 宽一档，
#: 文字与箭头之间才留得下 ``layout.icon.gap`` 的呼吸
_PAD_RIGHT = T("space.4")
#: 菜单项高度 = 内容盒（内容盒高 + 上下各 4px padding = 28px md 档）
_ITEM_CONTENT_H = T("space.4") - T("space.2") + T("space.1")   # 20
#: 菜单项左内边距，与全局面包屑 / 卡片内边距同档
_ITEM_PAD_X = T("layout.card.pad_x")


class _DangerItem(QWidget):
    """危险菜单项（QWidgetAction 的默认控件），悬停高亮、点击触发。"""

    clicked = Signal()

    def __init__(self, text: str, parent: QWidget = None):
        super().__init__(parent)
        self.setCursor(Qt.PointingHandCursor)
        layout = QHBoxLayout(self)
        # 与普通 QMenu::item 同内边距，危险项才不会比旁边那几行高一截
        layout.setContentsMargins(_ITEM_PAD_X, 0, _ITEM_PAD_X, 0)
        layout.setSpacing(T("layout.inline.gap"))
        self._label = QLabel(text, self)
        layout.addWidget(self._label)
        layout.addStretch(1)
        # 高度必须与普通菜单项一致（内容盒 20 + 上下 padding 4 + 4 = 28），
        # 否则危险项会在菜单里凸出来一截
        self.setFixedHeight(_ITEM_CONTENT_H + 2 * (T("space.4") - T("space.2")))
        self.setMinimumWidth(T("layout.sidebar.w") // 2)
        _connect_theme(self, self._reload_style)
        self._reload_style()

    def set_text_color_enabled(self, enabled: bool) -> None:
        """禁用态只改文字色（QWidget 的 enabled 由 QWidgetAction 同步）。"""
        self._label.setEnabled(enabled)

    def _reload_style(self) -> None:
        c = lambda k: T(f"color.{k}")  # noqa: E731
        self.setStyleSheet(f"""
_DangerItem {{
    background-color: transparent;
    border-radius: {T('radius.sm')}px;
}}
_DangerItem:hover {{ background-color: {c('danger.subtle')}; }}
_DangerItem:disabled {{ background-color: transparent; }}
_DangerItem QLabel {{ color: {c('danger')}; background-color: transparent; }}
_DangerItem QLabel:disabled {{ color: {c('text.disabled')}; }}
""")

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.LeftButton and self.isEnabled():
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
            f"QPushButton {{ padding-right: {_PAD_RIGHT}px; }}"
            "QPushButton::menu-indicator { width: 0px; height: 0px; }"
        )
        # 菜单项四态与全局 QMenu 规则一致，只把左内边距统一到 _ITEM_PAD_X，
        # 并给一个确定的内容盒高度——_DangerItem 依赖同一数值，两者才能等高
        self._menu.setStyleSheet(f"""
QMenu {{ padding: {T('space.1')}px; }}
QMenu::item {{
    padding: {T('space.1')}px {T('space.6')}px {T('space.1')}px
             {_ITEM_PAD_X}px;
    min-height: {_ITEM_CONTENT_H}px;
    border-radius: {T('radius.sm')}px;
}}
""")
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
            w.set_text_color_enabled(enabled)
            if enabled:
                w.clicked.connect(
                    lambda k=key, cb=callback: self._activate(k, cb))
            return wa
        action = self._menu.addAction(text)
        if icon is not None:
            action.setIcon(icon)
        if shortcut:
            action.setShortcut(shortcut)
        action.setEnabled(enabled)
        if enabled:
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
        # 主题感知的下拉箭头：禁用态与菜单项禁用态同为 text.disabled
        color = T("color.text.disabled") if not self.isEnabled() \
            else T("color.text.secondary")
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        pen = QPen(QColor(color))
        pen.setWidthF(1.5)
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        painter.setPen(pen)
        cx = self.width() - _ARROW_INSET
        cy = self.height() / 2.0
        painter.drawPolyline([
            QPointF(cx - _ARROW_HALF, cy - _ARROW_HALF / 2.0),
            QPointF(cx, cy + _ARROW_HALF / 2.0),
            QPointF(cx + _ARROW_HALF, cy - _ARROW_HALF / 2.0),
        ])
        painter.end()