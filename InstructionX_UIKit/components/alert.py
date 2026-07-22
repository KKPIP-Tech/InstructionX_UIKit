# -*- coding: utf-8 -*-
"""警告提示 Alert（SPEC §5.3 alert.py）。

四种类型 info / success / warning / error，支持标题、描述、
操作按钮与关闭按钮；图标为主题感知自绘像素图。
"""

from PySide6.QtCore import QPointF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ..theme import T, ThemeManager, set_property
from shiboken6 import isValid as _shiboken_is_valid


def _connect_theme(widget, slot) -> None:
    """连接主题切换信号；控件销毁后自动忽略回调。"""
    ThemeManager.instance().theme_changed.connect(
        lambda *_: slot() if _shiboken_is_valid(widget) else None)

__all__ = ["Alert"]


def _rgba(hex_color: str, alpha: float) -> str:
    """把 #RRGGBB 转为 QSS rgba() 字符串。"""
    qc = QColor(hex_color)
    return f"rgba({qc.red()},{qc.green()},{qc.blue()},{alpha})"


def _close_icon() -> QIcon:
    """绘制主题感知的关闭 × 图标。"""
    pm = QPixmap(12, 12)
    pm.fill(Qt.transparent)
    painter = QPainter(pm)
    painter.setRenderHint(QPainter.Antialiasing)
    pen = QPen(QColor(T("color.text.tertiary")))
    pen.setWidthF(1.5)
    pen.setCapStyle(Qt.RoundCap)
    painter.setPen(pen)
    painter.drawLine(QPointF(3.0, 3.0), QPointF(9.0, 9.0))
    painter.drawLine(QPointF(9.0, 3.0), QPointF(3.0, 9.0))
    painter.end()
    return QIcon(pm)


def _type_icon(kind: str, color: str) -> QPixmap:
    """绘制 18px 圆形类型图标（填充色 + 白色符号）。"""
    pm = QPixmap(18, 18)
    pm.fill(Qt.transparent)
    painter = QPainter(pm)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setBrush(QColor(color))
    painter.setPen(Qt.NoPen)
    painter.drawEllipse(QPointF(9.0, 9.0), 8.0, 8.0)
    on = QColor(T("color.on.primary"))
    if kind == "success":
        pen = QPen(on)
        pen.setWidthF(1.8)
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        painter.setPen(pen)
        painter.drawPolyline([
            QPointF(5.0, 9.4), QPointF(8.0, 12.2), QPointF(13.2, 6.0)])
    elif kind == "error":
        pen = QPen(on)
        pen.setWidthF(1.8)
        pen.setCapStyle(Qt.RoundCap)
        painter.setPen(pen)
        painter.drawLine(QPointF(6.2, 6.2), QPointF(11.8, 11.8))
        painter.drawLine(QPointF(11.8, 6.2), QPointF(6.2, 11.8))
    else:
        font = QFont()
        font.setPixelSize(12)
        font.setBold(True)
        painter.setFont(font)
        painter.setPen(on)
        painter.drawText(pm.rect(), Qt.AlignCenter,
                         "i" if kind == "info" else "!")
    painter.end()
    return pm


class Alert(QFrame):
    """警告提示条：页面内的醒目光反馈。

    参数:
        type: ``"info"`` / ``"success"`` / ``"warning"`` / ``"error"``。
        title: 标题文本（加粗）。
        description: 描述文本（可换行）。
        closable: 是否显示关闭按钮。
        parent: 父控件。

    示例::

        a = Alert("warning", "请注意", "配置尚未保存", closable=True)
        a.add_action("去保存", lambda: print("save"))
        layout.addWidget(a)
    """

    #: 关闭按钮点击后发射
    closed = Signal()

    #: 合法类型
    TYPES = ("info", "success", "warning", "error")

    def __init__(self, type: str = "info", title: str = "",
                 description: str = "", closable: bool = False,
                 parent: QWidget = None):
        super().__init__(parent)
        self._type = "info"
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(10)

        self._icon = QLabel(self)
        self._icon.setFixedSize(18, 18)
        layout.addWidget(self._icon, 0, Qt.AlignTop)

        col = QVBoxLayout()
        col.setSpacing(2)
        self._title = QLabel(title, self)
        set_property(self._title, "uikAl", "title")
        self._title.setVisible(bool(title))
        self._desc = QLabel(description, self)
        set_property(self._desc, "uikAl", "desc")
        self._desc.setWordWrap(True)
        policy = self._desc.sizePolicy()
        policy.setHeightForWidth(True)
        self._desc.setSizePolicy(policy)
        self._desc.setVisible(bool(description))
        col.addWidget(self._title)
        col.addWidget(self._desc)
        layout.addLayout(col, 1)

        self._actions = QHBoxLayout()
        self._actions.setSpacing(4)
        layout.addLayout(self._actions)

        self._close = QToolButton(self)
        self._close.setFixedSize(24, 24)
        self._close.setCursor(Qt.PointingHandCursor)
        self._close.setVisible(closable)
        self._close.clicked.connect(self._on_close)
        layout.addWidget(self._close, 0, Qt.AlignTop)

        _connect_theme(self, self._reload_style)
        self.set_type(type)

    # -- 公开 API ---------------------------------------------------------
    def set_type(self, type: str) -> None:
        """设置提示类型。"""
        if type not in self.TYPES:
            raise ValueError(f"未知 Alert 类型: {type!r}，应为 {self.TYPES} 之一")
        self._type = type
        set_property(self, "type", type)
        self._reload_style()

    def type(self) -> str:
        return self._type

    def set_title(self, text: str) -> None:
        """设置标题（为空则隐藏）。"""
        self._title.setText(text)
        self._title.setVisible(bool(text))

    def set_description(self, text: str) -> None:
        """设置描述（为空则隐藏）。"""
        self._desc.setText(text)
        self._desc.setVisible(bool(text))

    def add_action(self, text: str, callback=None) -> QPushButton:
        """追加一个操作链接按钮，点击时调用 ``callback()``。"""
        btn = QPushButton(text, self)
        set_property(btn, "uikAl", "action")
        btn.setCursor(Qt.PointingHandCursor)
        if callable(callback):
            btn.clicked.connect(lambda _=False: callback())
        self._actions.addWidget(btn)
        return btn

    # -- 内部 -------------------------------------------------------------
    def _on_close(self) -> None:
        self.hide()
        self.closed.emit()

    def _main_color(self) -> str:
        return {"info": T("color.primary"),
                "success": T("color.success"),
                "warning": T("color.warning"),
                "error": T("color.danger")}[self._type]

    def _subtle_color(self) -> str:
        return {"info": T("color.primary.subtle"),
                "success": T("color.success.subtle"),
                "warning": T("color.warning.subtle"),
                "error": T("color.danger.subtle")}[self._type]

    def _reload_style(self) -> None:
        c = lambda k: T(f"color.{k}")  # noqa: E731
        main = self._main_color()
        self.setStyleSheet(f"""
Alert {{
    background-color: {self._subtle_color()};
    border: 1px solid {_rgba(main, 0.35)};
    border-radius: {T('radius.lg')}px;
}}
QLabel[uikAl="title"] {{
    color: {c('text.primary')};
    font-weight: 600;
    background-color: transparent;
}}
QLabel[uikAl="desc"] {{
    color: {c('text.secondary')};
    background-color: transparent;
}}
QPushButton[uikAl="action"] {{
    border: none;
    background-color: transparent;
    color: {main};
    padding: 0 4px;
    min-height: 22px;
    max-height: 22px;
    font-weight: 600;
}}
QPushButton[uikAl="action"]:hover {{ text-decoration: underline; }}
QToolButton {{ background-color: transparent; border: none; }}
QToolButton:hover {{ background-color: {_rgba(main, 0.15)}; }}
""")
        self._icon.setPixmap(_type_icon(self._type, main))
        self._close.setIcon(_close_icon())
