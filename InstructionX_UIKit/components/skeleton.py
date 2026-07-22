# -*- coding: utf-8 -*-
"""骨架屏 Skeleton（SPEC §5.3 skeleton.py）。

标题 / 段落 / 头像 / 按钮占位形状，微光扫过动画（QTimer 驱动自绘），
颜色实时取自主题令牌。
"""

from PySide6.QtCore import QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPainterPath
from PySide6.QtWidgets import QWidget

from ..theme import T, ThemeManager
from shiboken6 import isValid as _shiboken_is_valid


def _connect_theme(widget, slot) -> None:
    """连接主题切换信号；控件销毁后自动忽略回调。"""
    ThemeManager.instance().theme_changed.connect(
        lambda *_: slot() if _shiboken_is_valid(widget) else None)

__all__ = ["Skeleton"]

_ROW_H = 13
_ROW_GAP = 24


class Skeleton(QWidget):
    """骨架屏：内容加载前的占位轮廓。

    参数:
        avatar: 是否显示头像圆形占位。
        title: 是否显示标题条占位。
        rows: 段落行数。
        button: 是否显示按钮占位。
        active: 是否启用微光扫过动画。
        parent: 父控件。

    示例::

        sk = Skeleton(avatar=True, rows=3, button=True)
        layout.addWidget(sk)
        sk.set_active(True)
    """

    def __init__(self, avatar: bool = False, title: bool = True,
                 rows: int = 3, button: bool = False, active: bool = True,
                 parent: QWidget = None):
        super().__init__(parent)
        self._avatar = bool(avatar)
        self._title = bool(title)
        self._rows = max(0, int(rows))
        self._button = bool(button)
        self._phase = 0.0
        self._timer = QTimer(self)
        self._timer.setInterval(40)
        self._timer.timeout.connect(self._advance)
        _connect_theme(self, self.update)
        self._update_minimum()
        self.set_active(active)

    # -- 公开 API ---------------------------------------------------------
    def set_active(self, active: bool) -> None:
        """启用 / 停止微光动画。"""
        if active:
            self.start()
        else:
            self.stop()

    def is_active(self) -> bool:
        return self._timer.isActive()

    def start(self) -> None:
        """启动微光动画。"""
        if not self._timer.isActive():
            self._timer.start()

    def stop(self) -> None:
        """停止微光动画。"""
        self._timer.stop()
        self.update()

    # -- 内部 -------------------------------------------------------------
    def _update_minimum(self) -> None:
        h = 12
        if self._title:
            h += 26
        h += self._rows * _ROW_GAP
        if self._button:
            h += 44
        self.setMinimumHeight(h)
        self.setMinimumWidth(200)

    def _advance(self) -> None:
        self._phase += 40.0 / 1400.0
        if self._phase > 1.0:
            self._phase -= 1.0
        self.update()

    def _shapes(self) -> list:
        """返回 [(QRectF, radius)] 占位形状列表。"""
        w = float(self.width())
        shapes = []
        x = 0.0
        if self._avatar:
            shapes.append((QRectF(0, 4, 40, 40), 20.0))
            x = 56.0
        y = 10.0
        if self._title:
            shapes.append((QRectF(x, y, max(40.0, w * 0.35 - x), 18), 4.0))
            y += 30
        fracs = [1.0, 0.92, 0.78, 0.62]
        for i in range(self._rows):
            frac = fracs[i] if i < len(fracs) else fracs[-1]
            shapes.append((QRectF(0, y, w * frac, _ROW_H), 4.0))
            y += _ROW_GAP
        if self._button:
            shapes.append((QRectF(0, y + 4, 88, 30), 6.0))
        return shapes

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        shapes = self._shapes()
        if not shapes:
            painter.end()
            return
        base = QColor(T("color.bg.muted"))
        union = QPainterPath()
        for rect, radius in shapes:
            painter.setBrush(base)
            painter.setPen(Qt.NoPen)
            painter.drawRoundedRect(rect, radius, radius)
            sub = QPainterPath()
            sub.addRoundedRect(rect.x(), rect.y(), rect.width(),
                               rect.height(), radius, radius)
            union = union.united(sub)
        if self._timer.isActive():
            # 微光扫过：裁剪到形状区域后绘制移动的浅色渐变带
            w = float(self.width())
            band = max(60.0, w * 0.35)
            gx = -band + self._phase * (w + 2 * band)
            shimmer = QColor(T("color.bg.elevated"))
            shimmer.setAlpha(170)
            transparent = QColor(shimmer)
            transparent.setAlpha(0)
            grad = QLinearGradient(gx, 0, gx + band, 0)
            grad.setColorAt(0.0, transparent)
            grad.setColorAt(0.5, shimmer)
            grad.setColorAt(1.0, transparent)
            painter.setClipPath(union)
            painter.fillRect(self.rect(), grad)
        painter.end()
