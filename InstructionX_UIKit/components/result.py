# -*- coding: utf-8 -*-
"""结果页 ResultView（SPEC §5.3 result.py）。

success / error / info / warning / 404 自绘图标 + 标题 + 副标题 + 操作区。
"""

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from ..theme import T, ThemeManager, set_property
from shiboken6 import isValid as _shiboken_is_valid


def _connect_theme(widget, slot) -> None:
    """连接主题切换信号；控件销毁后自动忽略回调。"""
    ThemeManager.instance().theme_changed.connect(
        lambda *_: slot() if _shiboken_is_valid(widget) else None)

__all__ = ["ResultView"]


class _ResultIcon(QWidget):
    """结果页状态图标（自绘，主题感知）。"""

    def __init__(self, status: str, parent: QWidget = None):
        super().__init__(parent)
        self._status = status
        self.setFixedSize(88, 88)
        _connect_theme(self, self.update)

    def set_status(self, status: str) -> None:
        self._status = status
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        c = lambda k: T(f"color.{k}")  # noqa: E731
        cx, cy = self.width() / 2.0, self.height() / 2.0
        if self._status == "404":
            font = QFont(self.font())
            font.setPixelSize(34)
            font.setWeight(QFont.Bold)
            painter.setFont(font)
            painter.setPen(QColor(c("text.tertiary")))
            painter.drawText(self.rect(), Qt.AlignCenter, "404")
            painter.end()
            return
        main = {"success": c("success"), "error": c("danger"),
                "warning": c("warning"), "info": c("primary")}[self._status]
        r = 30.0
        # 外圈浅色光晕
        halo = QColor(main)
        halo.setAlpha(40)
        painter.setBrush(halo)
        painter.setPen(Qt.NoPen)
        painter.drawEllipse(QPointF(cx, cy), r + 8, r + 8)
        # 主体圆
        painter.setBrush(QColor(main))
        painter.drawEllipse(QPointF(cx, cy), r, r)
        on = QColor(c("on.primary"))
        if self._status == "success":
            pen = QPen(on)
            pen.setWidthF(3.2)
            pen.setCapStyle(Qt.RoundCap)
            pen.setJoinStyle(Qt.RoundJoin)
            painter.setPen(pen)
            painter.drawPolyline([
                QPointF(cx - 12, cy + 1),
                QPointF(cx - 3, cy + 10),
                QPointF(cx + 13, cy - 9),
            ])
        elif self._status == "error":
            pen = QPen(on)
            pen.setWidthF(3.2)
            pen.setCapStyle(Qt.RoundCap)
            painter.setPen(pen)
            painter.drawLine(QPointF(cx - 8, cy - 8), QPointF(cx + 8, cy + 8))
            painter.drawLine(QPointF(cx + 8, cy - 8), QPointF(cx - 8, cy + 8))
        else:
            font = QFont(self.font())
            font.setPixelSize(34)
            font.setWeight(QFont.Bold)
            painter.setFont(font)
            painter.setPen(on)
            painter.drawText(QRectF(cx - r, cy - r, r * 2, r * 2),
                             Qt.AlignCenter,
                             "i" if self._status == "info" else "!")
        painter.end()


class ResultView(QWidget):
    """结果页：操作结果的整页反馈。

    参数:
        status: ``"success"`` / ``"error"`` / ``"info"`` / ``"warning"`` /
            ``"404"``。
        title: 主标题。
        subtitle: 副标题说明。
        parent: 父控件。

    示例::

        rv = ResultView("success", "提交成功", "我们将在 2 个工作日内处理")
        rv.add_action("返回首页", lambda: print("home"), variant="primary")
        layout.addWidget(rv)
    """

    #: 合法状态
    STATUSES = ("success", "error", "info", "warning", "404")

    def __init__(self, status: str = "success", title: str = "",
                 subtitle: str = "", parent: QWidget = None):
        super().__init__(parent)
        if status not in self.STATUSES:
            raise ValueError(
                f"未知结果状态: {status!r}，应为 {self.STATUSES} 之一")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(0)
        layout.addStretch(1)

        self._icon = _ResultIcon(status, self)
        layout.addWidget(self._icon, 0, Qt.AlignHCenter)
        layout.addSpacing(16)

        self._title = QLabel(title, self)
        set_property(self._title, "uikRv", "title")
        self._title.setAlignment(Qt.AlignCenter)
        layout.addWidget(self._title)
        layout.addSpacing(8)

        self._subtitle = QLabel(subtitle, self)
        set_property(self._subtitle, "uikRv", "subtitle")
        self._subtitle.setAlignment(Qt.AlignHCenter | Qt.AlignTop)
        self._subtitle.setWordWrap(True)
        self._subtitle.setMaximumWidth(460)
        policy = self._subtitle.sizePolicy()
        policy.setHeightForWidth(True)
        self._subtitle.setSizePolicy(policy)
        self._subtitle.setVisible(bool(subtitle))
        sub_row = QHBoxLayout()
        sub_row.addStretch(1)
        sub_row.addWidget(self._subtitle)
        sub_row.addStretch(1)
        layout.addLayout(sub_row)
        layout.addSpacing(24)

        self._actions = QHBoxLayout()
        self._actions.setSpacing(12)
        layout.addLayout(self._actions)
        layout.addStretch(2)

        _connect_theme(self, self._reload_style)
        self._reload_style()

    # -- 公开 API ---------------------------------------------------------
    def set_status(self, status: str) -> None:
        """设置结果状态。"""
        if status not in self.STATUSES:
            raise ValueError(
                f"未知结果状态: {status!r}，应为 {self.STATUSES} 之一")
        self._icon.set_status(status)

    def set_title(self, text: str) -> None:
        """设置主标题。"""
        self._title.setText(text)

    def set_subtitle(self, text: str) -> None:
        """设置副标题（为空则隐藏）。"""
        self._subtitle.setText(text)
        self._subtitle.setVisible(bool(text))

    def add_action(self, text: str, callback=None,
                   variant: str = "default") -> QPushButton:
        """追加操作按钮；``variant`` 为 ``primary`` / ``default`` 等。"""
        btn = QPushButton(text, self)
        set_property(btn, "variant", variant)
        if callable(callback):
            btn.clicked.connect(lambda _=False: callback())
        self._actions.addWidget(btn)
        return btn

    # -- 内部 -------------------------------------------------------------
    def _reload_style(self) -> None:
        c = lambda k: T(f"color.{k}")  # noqa: E731
        self.setStyleSheet(f"""
QLabel[uikRv="title"] {{
    color: {c('text.primary')};
    font-size: {T('font.title.lg')}px;
    font-weight: 600;
}}
QLabel[uikRv="subtitle"] {{
    color: {c('text.secondary')};
    font-size: {T('font.md')}px;
}}
""")
