# -*- coding: utf-8 -*-
"""加载指示器 Spinner（SPEC §5.3 spinner.py）。

自绘旋转弧（QTimer 驱动），支持 sm / md / lg 尺寸与提示文案，
颜色实时取自主题令牌。
"""

from PySide6.QtCore import QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QFontMetrics, QPainter, QPen
from PySide6.QtWidgets import QWidget

from ..theme import T, ThemeManager, set_property
from shiboken6 import isValid as _shiboken_is_valid


def _connect_theme(widget, slot) -> None:
    """连接主题切换信号；控件销毁后自动忽略回调。"""
    ThemeManager.instance().theme_changed.connect(
        lambda *_: slot() if _shiboken_is_valid(widget) else None)

__all__ = ["Spinner"]


class Spinner(QWidget):
    """加载指示器：旋转弧 + 可选提示文案。

    参数:
        size: 弧直径档位 ``"sm"``(16) / ``"md"``(24) / ``"lg"``(32)。
        tip: 提示文案（显示在弧下方，为空则不显示）。
        parent: 父控件。

    示例::

        sp = Spinner(size="md", tip="加载中…")
        layout.addWidget(sp)
        sp.start()
    """

    #: 尺寸档位（弧直径 px）
    SIZES = {"sm": 16, "md": 24, "lg": 32}

    def __init__(self, size: str = "md", tip: str = "",
                 parent: QWidget = None):
        super().__init__(parent)
        self._size = "md"
        self._tip = tip
        self._angle = 0
        self._timer = QTimer(self)
        self._timer.setInterval(16)
        self._timer.timeout.connect(self._advance)
        _connect_theme(self, self.update)
        self.set_size(size)
        self.start()

    # -- 公开 API ---------------------------------------------------------
    def set_size(self, size: str) -> None:
        """设置尺寸档位。"""
        if size not in self.SIZES:
            raise ValueError(
                f"未知 Spinner 尺寸: {size!r}，应为 {tuple(self.SIZES)} 之一")
        self._size = size
        set_property(self, "size", size)
        self.updateGeometry()
        self.update()

    def size(self) -> str:  # noqa: A003 - 与令牌档位语义一致
        return self._size

    def set_tip(self, text: str) -> None:
        """设置提示文案。"""
        self._tip = text
        self.updateGeometry()
        self.update()

    def tip(self) -> str:
        return self._tip

    def set_spinning(self, spinning: bool) -> None:
        """启动 / 停止旋转。"""
        if spinning:
            self.start()
        else:
            self.stop()

    def is_spinning(self) -> bool:
        return self._timer.isActive()

    def start(self) -> None:
        """启动旋转动画。"""
        if not self._timer.isActive():
            self._timer.start()

    def stop(self) -> None:
        """停止旋转动画。"""
        self._timer.stop()
        self.update()

    def sizeHint(self):
        d = self.SIZES[self._size]
        w = d
        h = d
        if self._tip:
            fm = QFontMetrics(self.font())
            w = max(w, fm.horizontalAdvance(self._tip))
            h += 6 + fm.height()
        hint = super().sizeHint()
        hint.setWidth(w)
        hint.setHeight(h)
        return hint

    # -- 内部 -------------------------------------------------------------
    def _advance(self) -> None:
        self._angle = (self._angle + 10) % 360
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        d = self.SIZES[self._size]
        pen_w = max(2.0, d / 10.0)
        x = (self.width() - d) / 2.0
        rect = QRectF(x + pen_w / 2, pen_w / 2, d - pen_w, d - pen_w)
        # 背景弧（淡轨道）
        track = QColor(T("color.primary"))
        track.setAlpha(45)
        pen = QPen(track)
        pen.setWidthF(pen_w)
        pen.setCapStyle(Qt.RoundCap)
        painter.setPen(pen)
        painter.drawArc(rect, 0, 360 * 16)
        # 旋转弧
        pen = QPen(QColor(T("color.primary")))
        pen.setWidthF(pen_w)
        pen.setCapStyle(Qt.RoundCap)
        painter.setPen(pen)
        painter.drawArc(rect, -self._angle * 16, 270 * 16)
        # 提示文案
        if self._tip:
            painter.setFont(self.font())
            painter.setPen(QColor(T("color.text.secondary")))
            tip_rect = QRectF(0, d + 6, self.width(),
                              self.height() - d - 6)
            painter.drawText(tip_rect, Qt.AlignHCenter | Qt.AlignTop,
                             self._tip)
        painter.end()
