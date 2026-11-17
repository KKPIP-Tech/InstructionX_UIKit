# -*- coding: utf-8 -*-
"""气泡确认框 Popconfirm（SPEC §5.3 popconfirm.py）。

相对锚点控件弹出的轻量确认气泡：标题 + 确认 / 取消按钮，
自绘带箭头的气泡卡片（主题感知）。

图标与内边距引用 ``.alert`` 的提示族共享常量（``ICON_D`` / ``ICON_GAP`` /
``PAD_X``），与 Alert / Message / Notification 的观感一致。
"""

from PySide6.QtCore import QPoint, QRect, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QFontMetrics,
    QGuiApplication,
    QPainter,
    QPainterPath,
    QPen,
)
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..theme import T, ThemeManager, set_property
from .alert import ICON_D, ICON_GAP, PAD_X, _type_icon
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

__all__ = ["Popconfirm"]

#: 箭头高度（气泡顶部为箭头让出的空间）
_ARROW_H = T("space.1")
#: 箭头底边宽度
_ARROW_W = T("space.3")
#: 正文最大宽度；超出后自行折行并锁定高度（契约 §7：不用 wordWrap 让布局去猜）
_TEXT_MAX_W = T("space.16") * 4      # 256
#: 正文与按钮区之间的间距
_BODY_GAP = T("layout.card.gap")
#: 屏幕边缘的安全距离
_EDGE = T("space.2")


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
        # 与 Popover 同理：只给 WA_TranslucentBackground 不够，Qt 仍会用
        # 窗口的系统背景刷子把整个窗口矩形填成不透明色（真机上表现为
        # 一圈矩形色块）。本组件只由 paintEvent 绘制，明确交回背景控制权。
        self.setAttribute(Qt.WA_NoSystemBackground)
        self._anchor = anchor
        self._on_result = on_result
        self._arrow_x = _ARROW_W * 2

        layout = QVBoxLayout(self)
        # 顶部为箭头留 _ARROW_H，其上再加一个内边距档；其余三边统一用
        # layout.card.pad_x，四边同值保证「控件内部文本上下对称」
        layout.setContentsMargins(PAD_X, _ARROW_H + T("space.2"), PAD_X, PAD_X)
        layout.setSpacing(_BODY_GAP)

        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(ICON_GAP)
        self._icon = QLabel(self)
        self._icon.setFixedSize(ICON_D, ICON_D)
        set_property(self._icon, "uikPc", "icon")
        # 标题可能多行：图标顶部对齐，不做垂直居中（契约 §4）
        row.addWidget(self._icon, 0, Qt.AlignTop)
        self._title = QLabel(title, self)
        set_property(self._title, "uikPc", "title")
        # 关闭 wordWrap：宽度与高度在 _relayout() 里按折行结果锁定，
        # 避免 QLabel 在布局中被压成一行（契约 §7）
        self._title.setWordWrap(False)
        row.addWidget(self._title, 1)
        layout.addLayout(row)

        btns = QHBoxLayout()
        btns.setContentsMargins(0, 0, 0, 0)
        btns.setSpacing(T("layout.inline.gap"))
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
    def _relayout(self) -> None:
        """按折行结果锁定标题宽高，使气泡宽度确定且不被布局压缩。"""
        fm = QFontMetrics(self._title.font())
        max_w = _TEXT_MAX_W - ICON_D - ICON_GAP
        one_line = fm.horizontalAdvance(self._title.text())
        if one_line <= max_w:
            self._title.setFixedSize(one_line, fm.height())
            return
        br = fm.boundingRect(QRect(0, 0, max_w, 0), Qt.TextWordWrap,
                             self._title.text())
        # 折行后宽度取满上限，保证绘制/测量用的是同一段断行结果
        self._title.setFixedSize(max_w, max(fm.height(), br.height()))

    def show_popup(self) -> None:
        """在锚点控件下方弹出气泡（空间不足时仍尽量贴边）。"""
        self._relayout()
        self.adjustSize()
        anchor = self._anchor
        gap = T("layout.icon.gap")
        top_left = anchor.mapToGlobal(QPoint(0, anchor.height() + gap))
        x = top_left.x() + anchor.width() // 2 - self.width() // 2
        y = top_left.y()
        screen = QGuiApplication.screenAt(top_left) or \
            QGuiApplication.primaryScreen()
        if screen is not None:
            area = screen.availableGeometry()
            x = max(area.left() + _EDGE,
                    min(x, area.right() - self.width() - _EDGE))
            y = max(area.top() + _EDGE,
                    min(y, area.bottom() - self.height() - _EDGE))
        # 箭头始终贴着锚点水平中心，且不越出气泡圆角
        half = _ARROW_W // 2 + int(T("radius.lg"))
        self._arrow_x = max(half, min(
            anchor.mapToGlobal(QPoint(anchor.width() // 2, 0)).x() - x,
            self.width() - half))
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
QLabel[uikPc="icon"], QLabel[uikPc="title"] {{
    background-color: transparent;
}}
QLabel[uikPc="title"] {{
    color: {c('text.primary')};
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