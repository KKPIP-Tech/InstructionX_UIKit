# -*- coding: utf-8 -*-
"""气泡确认框 Popconfirm（SPEC §5.3 popconfirm.py）。

相对锚点控件弹出的轻量确认气泡：标题 + 确认 / 取消按钮，
自绘带箭头的气泡卡片（主题感知）。
"""

from PySide6.QtCore import QPoint, QRect, Qt, Signal
from PySide6.QtGui import QColor, QGuiApplication, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..theme import T, ThemeManager, set_property
from .alert import _type_icon
from shiboken6 import isValid as _shiboken_is_valid


def _connect_theme(widget, slot) -> None:
    """连接主题切换信号；控件销毁后自动忽略回调。"""
    ThemeManager.instance().theme_changed.connect(
        lambda *_: slot() if _shiboken_is_valid(widget) else None)

__all__ = ["Popconfirm"]

_ARROW_H = 8
_ARROW_W = 14


class Popconfirm(QFrame):
    """气泡确认框：点击锚点控件后弹出，确认 / 取消。

    参数:
        anchor: 锚点控件（气泡相对它定位）。
        title: 确认提示文本。
        ok_text: 确认按钮文本。
        cancel_text: 取消按钮文本。
        on_result: 结果回调，签名为 ``on_result(ok: bool)``。
        parent: Qt 父对象（通常为 None，气泡为顶层弹出窗）。

    示例::

        pc = Popconfirm(btn, "确定删除该文件吗？")
        pc.confirmed.connect(lambda: print("已确认"))
        pc.show_popup()
    """

    #: 点击确认时发射
    confirmed = Signal()
    #: 点击取消时发射
    canceled = Signal()

    def __init__(self, anchor: QWidget, title: str, ok_text: str = "确定",
                 cancel_text: str = "取消", on_result=None,
                 parent: QWidget = None):
        super().__init__(parent, Qt.Popup | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self._anchor = anchor
        self._on_result = on_result
        self._arrow_x = 24

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, _ARROW_H + 10, 12, 12)
        layout.setSpacing(10)

        row = QHBoxLayout()
        row.setSpacing(8)
        self._icon = QLabel(self)
        self._icon.setFixedSize(18, 18)
        row.addWidget(self._icon, 0, Qt.AlignTop)
        self._title = QLabel(title, self)
        self._title.setWordWrap(True)
        self._title.setMaximumWidth(240)
        policy = self._title.sizePolicy()
        policy.setHeightForWidth(True)
        self._title.setSizePolicy(policy)
        set_property(self._title, "uikPc", "title")
        row.addWidget(self._title, 1)
        layout.addLayout(row)

        btns = QHBoxLayout()
        btns.setSpacing(8)
        btns.addStretch(1)
        self._cancel = QPushButton(cancel_text, self)
        set_property(self._cancel, "variant", "default")
        set_property(self._cancel, "size", "sm")
        self._ok = QPushButton(ok_text, self)
        set_property(self._ok, "variant", "primary")
        set_property(self._ok, "size", "sm")
        self._cancel.clicked.connect(self._on_cancel)
        self._ok.clicked.connect(self._on_ok)
        btns.addWidget(self._cancel)
        btns.addWidget(self._ok)
        layout.addLayout(btns)

        _connect_theme(self, self._reload)
        self._reload()

    # -- 公开 API ---------------------------------------------------------
    def show_popup(self) -> None:
        """在锚点控件下方弹出气泡（空间不足时仍尽量贴边）。"""
        self.adjustSize()
        anchor = self._anchor
        top_left = anchor.mapToGlobal(QPoint(0, anchor.height() + 4))
        x = top_left.x() + anchor.width() // 2 - self.width() // 2
        y = top_left.y()
        screen = QGuiApplication.screenAt(top_left) or \
            QGuiApplication.primaryScreen()
        if screen is not None:
            area = screen.availableGeometry()
            x = max(area.left() + 8, min(x, area.right() - self.width() - 8))
            y = max(area.top() + 8, min(y, area.bottom() - self.height() - 8))
        self._arrow_x = max(16, min(
            anchor.mapToGlobal(QPoint(anchor.width() // 2, 0)).x() - x,
            self.width() - 16))
        self.move(x, y)
        self.show()
        self.update()

    def ok_button(self) -> QPushButton:
        return self._ok

    def cancel_button(self) -> QPushButton:
        return self._cancel

    @staticmethod
    def confirm(anchor: QWidget, title: str, on_result=None,
                ok_text: str = "确定", cancel_text: str = "取消") -> "Popconfirm":
        """静态便捷方法：弹出气泡确认框并返回实例（非阻塞）。"""
        pc = Popconfirm(anchor, title, ok_text, cancel_text, on_result)
        pc.show_popup()
        return pc

    # -- 内部 -------------------------------------------------------------
    def _on_ok(self) -> None:
        self.confirmed.emit()
        if callable(self._on_result):
            self._on_result(True)
        self.close()

    def _on_cancel(self) -> None:
        self.canceled.emit()
        if callable(self._on_result):
            self._on_result(False)
        self.close()

    def _reload(self) -> None:
        c = lambda k: T(f"color.{k}")  # noqa: E731
        self.setStyleSheet(f"""
QLabel[uikPc="title"] {{
    color: {c('text.primary')};
    background-color: transparent;
}}
""")
        self._icon.setPixmap(_type_icon("warning", T("color.warning")))
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        c = lambda k: T(f"color.{k}")  # noqa: E731
        radius = T("radius.lg")
        w, h = self.width() - 1, self.height() - 1
        path = QPainterPath()
        # 圆角气泡主体（顶部留箭头高度）
        body_top = _ARROW_H
        path.addRoundedRect(0, body_top, w, h - body_top, radius, radius)
        # 顶部箭头
        ax = self._arrow_x
        arrow = QPainterPath()
        arrow.moveTo(ax - _ARROW_W / 2, body_top + 0.5)
        arrow.lineTo(ax, 0)
        arrow.lineTo(ax + _ARROW_W / 2, body_top + 0.5)
        arrow.closeSubpath()
        united = path.united(arrow)
        painter.fillPath(united, QColor(c("bg.elevated")))
        pen = QPen(QColor(c("border")))
        pen.setWidthF(1.0)
        painter.setPen(pen)
        painter.drawPath(united)
        painter.end()
