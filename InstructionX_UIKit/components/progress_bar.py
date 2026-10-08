# -*- coding: utf-8 -*-
"""进度条 ProgressBar / CircleProgress（SPEC §5.3 progress_bar.py）。

直线进度条基于 QProgressBar 子类化（自绘轨道 + 状态色 + 百分比文本），
环形进度为纯自绘控件；二者均主题感知。

直线进度条的三档密度（契约 §1）：

======  ======  ==========  =====  ==========================
档位     总高     轨道厚度     字阶   百分比位置
======  ======  ==========  =====  ==========================
sm      22      4           xs     右缘右对齐，距轨道 8
md      28      6           sm     右缘右对齐，距轨道 8
lg      34      8           md     右缘右对齐，距轨道 8
======  ======  ==========  =====  ==========================

**必须显式覆盖全局 QSS 的高度钳制**：``theme.build_qss`` 给
``QProgressBar`` 写了 ``min-height/max-height: 8px``（为原生 chunk 准备的），
它会把控件压到 8px，百分比文字随即被裁掉（这是本组件此前不可见的缺陷）。
本组件在实例级样式表里按档位重设高度，并用 ``setFixedHeight`` 兜底。
"""

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFontMetrics, QPainter, QPen
from PySide6.QtWidgets import QProgressBar, QWidget

from .._draw import draw_arc
from ..theme import T, set_property
from ..tokens import TokenState
from .dialog import _connect_theme

__all__ = ["ProgressBar", "CircleProgress"]

_STATUSES = ("normal", "success", "warning", "error")
#: 合法尺寸档
_SIZES = ("sm", "md", "lg")
#: 档位 -> 控件总高（与密度刻度一致）
_HEIGHT = {"sm": 22, "md": 28, "lg": 34}
#: 档位 -> 轨道厚度
_TRACK = {"sm": 4, "md": 6, "lg": 8}
#: 档位 -> 百分比字阶
_FONT = {"sm": "xs", "md": "sm", "lg": "md"}
#: 轨道与百分比之间的间距
_TEXT_GAP = T("space.2")
#: 环形进度中心字阶（按直径分档，全部取字阶令牌而非按比例算字号）
_CIRCLE_FONT = ((T("space.12") * 2, "lg"), (T("space.16") * 2, "title.sm"),
                (T("space.16") * 4, "title.md"))


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
        size: 密度档位 ``"sm"`` / ``"md"`` / ``"lg"``（默认 ``"md"``）。

    示例::

        pb = ProgressBar(45)
        pb.set_status("success")
        layout.addWidget(pb)
    """

    #: 合法状态
    STATUSES = _STATUSES

    def __init__(self, value: int = 0, status: str = "normal",
                 show_info: bool = True, parent: QWidget = None,
                 size: str = "md"):
        super().__init__(parent)
        self.setRange(0, 100)
        self.setTextVisible(False)
        self._status = "normal"
        self._show_info = bool(show_info)
        self._size = "md"
        _connect_theme(self, self.update)
        self.set_status(status)
        self.set_size(size)
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
        self.updateGeometry()
        self.update()

    def set_size(self, size: str) -> None:
        """设置密度档位（总高 22 / 28 / 34，轨道 4 / 6 / 8）。"""
        if size not in _SIZES:
            raise ValueError(
                f"未知进度条尺寸: {size!r}，应为 {_SIZES} 之一")
        self._size = size
        set_property(self, "size", size)
        h = _HEIGHT[size]
        # 解除全局 QSS 的 8px 高度钳制（否则百分比文字被裁掉）
        self.setStyleSheet(f"QProgressBar {{ min-height: {h}px;"
                           f" max-height: {h}px; }}")
        self.setFixedHeight(h)
        self.updateGeometry()
        self.update()

    def size_name(self) -> str:
        """当前密度档位名。"""
        return self._size

    def sizeHint(self):
        hint = super().sizeHint()
        hint.setHeight(_HEIGHT[self._size])
        return hint

    def minimumSizeHint(self):
        hint = super().minimumSizeHint()
        hint.setHeight(_HEIGHT[self._size])
        return hint

    # -- 绘制 -------------------------------------------------------------
    def _text_font(self):
        return TokenState.instance().font(_FONT[self._size], "medium")

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        value_span = max(1, self.maximum() - self.minimum())
        ratio = max(0.0, min(1.0, (self.value() - self.minimum())
                             / value_span))
        text = f"{int(round(ratio * 100))}%"
        enabled = self.isEnabled()
        # 轨道 / 填充半径：小圆角档，且不超过轨道高度的一半（否则会变胶囊）
        bar_h = float(_TRACK[self._size])
        radius = min(float(T("radius.sm")), bar_h / 2.0)

        text_w = 0.0
        if self._show_info:
            text_w = QFontMetrics(self._text_font()).horizontalAdvance(text)
        # 空间不够时先让位给轨道：百分比是补充信息，不是主体
        room = self.width() - text_w - (_TEXT_GAP if text_w else 0)
        show_text = self._show_info and room >= bar_h * 2
        track_w = room if show_text else float(self.width())

        y = (self.height() - bar_h) / 2.0
        track = QRectF(0, y, max(0.0, track_w), bar_h)
        painter.setBrush(QColor(T("color.bg.muted")))
        painter.setPen(Qt.NoPen)
        painter.drawRoundedRect(track, radius, radius)
        if ratio > 0.0 and track_w > 0:
            fill = QColor(T("color.text.disabled")) if not enabled \
                else _status_color(self._status)
            chunk = QRectF(track.x(), track.y(),
                           min(track.width(), max(bar_h, track.width() * ratio)),
                           bar_h)
            painter.setBrush(fill)
            painter.drawRoundedRect(chunk, radius, radius)
        if show_text:
            painter.setFont(self._text_font())
            color = QColor(T("color.text.disabled")) if not enabled else (
                _status_color(self._status) if self._status != "normal"
                else QColor(T("color.text.secondary")))
            painter.setPen(color)
            # 百分比右缘与控件右缘对齐（数值列右对齐，见契约 §3）
            painter.drawText(
                QRectF(self.width() - text_w, 0, text_w, self.height()),
                Qt.AlignRight | Qt.AlignVCenter, text)
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
        return QSize(self._width, self._width)

    def minimumSizeHint(self):
        return QSize(self._width, self._width)

    # -- 绘制 -------------------------------------------------------------
    def _center_scale(self) -> str:
        """中心字阶：按直径取对应字阶令牌（而不是按比例算字号）。"""
        scale = _CIRCLE_FONT[-1][1]
        for limit, name in _CIRCLE_FONT:
            if self._width <= limit:
                return name
        return scale

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        enabled = self.isEnabled()
        s = float(self._stroke)
        # 圆环向内缩半个线宽：两端都用圆头笔帽，轨道与进度弧的端点才齐平
        rect = QRectF(s / 2, s / 2, self.width() - s, self.height() - s)
        color = QColor(T("color.text.disabled")) if not enabled \
            else _status_color(self._status)
        pen = QPen(QColor(T("color.bg.muted")) if enabled
                   else QColor(T("color.border")))
        pen.setWidthF(s)
        pen.setCapStyle(Qt.RoundCap)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        painter.drawEllipse(rect)
        # 进度弧（从顶部开始，顺时针）
        if self._value > 0:
            pen = QPen(color)
            pen.setWidthF(s)
            pen.setCapStyle(Qt.RoundCap)
            painter.setPen(pen)
            draw_arc(painter, rect, 90.0, -3.6 * self._value)
        # 中心内容
        cx, cy = self.width() / 2.0, self.height() / 2.0
        if self._status == "success" and self._value >= 100:
            pen = QPen(color)
            pen.setWidthF(max(T("space.05"), s / 2))
            pen.setCapStyle(Qt.RoundCap)
            pen.setJoinStyle(Qt.RoundJoin)
            painter.setPen(pen)
            # 勾按内径等比缩放：大环小环形状一致
            u = (self.width() - s) / 100.0
            painter.drawPolyline([
                QPointF(cx - 14 * u, cy + 1 * u),
                QPointF(cx - 4 * u, cy + 11 * u),
                QPointF(cx + 15 * u, cy - 10 * u),
            ])
        else:
            painter.setFont(TokenState.instance().font(self._center_scale(),
                                                       "medium"))
            painter.setPen(QColor(T("color.text.primary")) if enabled
                           else QColor(T("color.text.disabled")))
            painter.drawText(self.rect(), Qt.AlignCenter,
                             f"{self._value}%")
        painter.end()
