# -*- coding: utf-8 -*-
"""进度条 ProgressBar / CircleProgress（SPEC §5.3 progress_bar.py）。

直线进度条基于 QProgressBar 子类化（自绘轨道 + 状态色 + 百分比文本），
环形进度为纯自绘控件；二者均主题感知。
"""

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPen
from PySide6.QtWidgets import QProgressBar, QWidget

from ..theme import T, ThemeManager, set_property

from shiboken6 import isValid as _shiboken_is_valid


def _connect_theme(widget, slot) -> None:
    """连接主题切换信号；控件销毁后自动忽略回调。"""
    ThemeManager.instance().theme_changed.connect(
        lambda *_: slot() if _shiboken_is_valid(widget) else None)


__all__ = ["ProgressBar", "CircleProgress"]

_STATUSES = ("normal", "success", "warning", "error")


def _status_color(status: str) -> QColor:
    key = {"normal": "primary", "success": "success",
           "warning": "warning", "error": "danger"}[status]
    return QColor(T(f"color.{key}"))


class ProgressBar(QProgressBar):
    """直线进度条：状态色 + 可选百分比文本。

    参数:
        value: 初始值（0-100）。
        status: ``"normal"`` / ``"success"`` / ``"warning"`` / ``"error"``。
        show_info: 是否在右侧显示百分比文本。
        parent: 父控件。

    示例::

        pb = ProgressBar(45)
        pb.set_status("success")
        layout.addWidget(pb)
    """

    #: 合法状态
    STATUSES = _STATUSES

    def __init__(self, value: int = 0, status: str = "normal",
                 show_info: bool = True, parent: QWidget = None):
        super().__init__(parent)
        self.setRange(0, 100)
        self.setTextVisible(False)
        self._status = "normal"
        self._show_info = bool(show_info)
        _connect_theme(self, self.update)
        self.set_status(status)
        self.setValue(value)

    # -- 公开 API ---------------------------------------------------------
    def set_status(self, status: str) -> None:
        """设置状态（决定进度颜色）。"""
        if status not in _STATUSES:
            raise ValueError(
                f"未知进度状态: {status!r}，应为 {_STATUSES} 之一")
        self._status = status
        set_property(self, "status", status)
        self.update()

    def status(self) -> str:
        return self._status

    def set_show_info(self, show: bool) -> None:
        """是否显示百分比文本。"""
        self._show_info = bool(show)
        self.update()

    def sizeHint(self):
        hint = super().sizeHint()
        hint.setHeight(18)
        return hint

    def minimumSizeHint(self):
        hint = super().minimumSizeHint()
        hint.setHeight(18)
        return hint

    # -- 绘制 -------------------------------------------------------------
    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        value_span = max(1, self.maximum() - self.minimum())
        ratio = max(0.0, min(1.0, (self.value() - self.minimum())
                             / value_span))
        text = f"{int(round(ratio * 100))}%"
        font = QFont(self.font())
        font.setPixelSize(T("font.sm"))
        fm = QFontMetrics(font)
        text_w = fm.horizontalAdvance(text) + 10 if self._show_info else 0

        bar_h = 8.0
        y = (self.height() - bar_h) / 2.0
        track = QRectF(0, y, self.width() - text_w, bar_h)
        painter.setBrush(QColor(T("color.bg.muted")))
        painter.setPen(Qt.NoPen)
        painter.drawRoundedRect(track, 4, 4)
        if ratio > 0.0:
            chunk = QRectF(track.x(), track.y(),
                           max(bar_h, track.width() * ratio), bar_h)
            painter.setBrush(_status_color(self._status))
            painter.drawRoundedRect(chunk, 4, 4)
        if self._show_info:
            painter.setFont(font)
            color = _status_color(self._status) if self._status != "normal" \
                else QColor(T("color.text.secondary"))
            painter.setPen(color)
            painter.drawText(
                QRectF(track.width() + 10, 0, text_w, self.height()),
                Qt.AlignLeft | Qt.AlignVCenter, text)
        painter.end()


class CircleProgress(QWidget):
    """环形进度条：圆环 + 中心百分比 / 状态符号。

    参数:
        value: 初始值（0-100）。
        width: 控件直径（px）。
        stroke: 圆环宽度（px）。
        status: ``"normal"`` / ``"success"`` / ``"warning"`` / ``"error"``。
        parent: 父控件。

    示例::

        cp = CircleProgress(75)
        cp.set_status("success")
        layout.addWidget(cp)
    """

    #: 合法状态
    STATUSES = _STATUSES

    #: 值变化信号
    valueChanged = Signal(int)

    def __init__(self, value: int = 0, width: int = 110, stroke: int = 8,
                 status: str = "normal", parent: QWidget = None):
        super().__init__(parent)
        self._value = 0
        self._width = max(48, int(width))
        self._stroke = max(2, int(stroke))
        self._status = "normal"
        _connect_theme(self, self.update)
        self.set_status(status)
        self.set_value(value)
        self.setFixedSize(self._width, self._width)

    # -- 公开 API ---------------------------------------------------------
    def set_value(self, value: int) -> None:
        """设置进度值（0-100）。"""
        value = max(0, min(100, int(value)))
        if value == self._value:
            self.update()
            return
        self._value = value
        self.valueChanged.emit(value)
        self.update()

    def value(self) -> int:
        return self._value

    def set_status(self, status: str) -> None:
        """设置状态（决定圆弧颜色与完成符号）。"""
        if status not in _STATUSES:
            raise ValueError(
                f"未知进度状态: {status!r}，应为 {_STATUSES} 之一")
        self._status = status
        self.update()

    def status(self) -> str:
        return self._status

    def sizeHint(self):
        from PySide6.QtCore import QSize
        return QSize(self._width, self._width)

    # -- 绘制 -------------------------------------------------------------
    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        s = float(self._stroke)
        rect = QRectF(s / 2, s / 2, self.width() - s, self.height() - s)
        # 轨道
        pen = QPen(QColor(T("color.bg.muted")))
        pen.setWidthF(s)
        painter.setPen(pen)
        painter.drawEllipse(rect)
        # 进度弧（从顶部开始，顺时针）
        color = _status_color(self._status)
        pen = QPen(color)
        pen.setWidthF(s)
        pen.setCapStyle(Qt.RoundCap)
        painter.setPen(pen)
        span = int(-3.6 * self._value * 16)
        if span:
            painter.drawArc(rect, 90 * 16, span)
        # 中心内容
        cx, cy = self.width() / 2.0, self.height() / 2.0
        if self._status == "success" and self._value >= 100:
            pen = QPen(color)
            pen.setWidthF(max(3.0, s / 2))
            pen.setCapStyle(Qt.RoundCap)
            pen.setJoinStyle(Qt.RoundJoin)
            painter.setPen(pen)
            u = self.width() / 110.0
            painter.drawPolyline([
                QPointF(cx - 14 * u, cy + 1 * u),
                QPointF(cx - 4 * u, cy + 11 * u),
                QPointF(cx + 15 * u, cy - 10 * u),
            ])
        else:
            font = QFont(self.font())
            font.setPixelSize(max(12, int(self._width * 0.18)))
            font.setWeight(QFont.DemiBold)
            painter.setFont(font)
            painter.setPen(QColor(T("color.text.primary")))
            painter.drawText(self.rect(), Qt.AlignCenter,
                             f"{self._value}%")
        painter.end()
