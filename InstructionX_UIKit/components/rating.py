# -*- coding: utf-8 -*-
"""星级评分组件（SPEC §5.1）。

``Rating`` 全自绘五角星，支持半星模式、只读展示与鼠标悬停预览；
数值变化经 QVariantAnimation 平滑过渡（时长 / 缓动取设计令牌）。
"""

import math

from PySide6.QtCore import Qt, QVariantAnimation, QSize
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPolygonF
from PySide6.QtCore import QPointF, Signal
from PySide6.QtWidgets import QWidget

from ..theme import T, ThemeManager
from ..tokens import DURATION, EASING, TokenState

__all__ = ["Rating"]


def _star_polygon(cx: float, cy: float, r: float) -> QPolygonF:
    """以 (cx, cy) 为中心、外接半径 r 的五角星多边形。"""
    pts = []
    inner = r * 0.42
    for i in range(10):
        radius = r if i % 2 == 0 else inner
        angle = -math.pi / 2 + i * math.pi / 5
        pts.append(QPointF(cx + radius * math.cos(angle),
                           cy + radius * math.sin(angle)))
    return QPolygonF(pts)


class Rating(QWidget):
    """星级评分。

    用途:
        打分输入或只读展示；可选半星精度，值变化带平滑过渡动画。

    参数:
        count: 星星总数。
        value: 初始分值。
        allow_half: 是否允许半星（0.5 步进）。
        read_only: 只读展示（不响应鼠标）。
        star_size: 单颗星边长（px）。
        parent: 父控件。

    示例::

        r = Rating(count=5, value=3.5, allow_half=True)
        r.valueChanged.connect(lambda v: print("评分:", v))
        r.set_value(4.0)
    """

    #: 分值变化信号（提交后发射，参数为 float 分值）
    valueChanged = Signal(float)

    def __init__(self, count: int = 5, value: float = 0.0,
                 allow_half: bool = False, read_only: bool = False,
                 star_size: int = 20, parent=None):
        super().__init__(parent)
        self._count = max(1, int(count))
        self._allow_half = bool(allow_half)
        self._read_only = bool(read_only)
        self._star = max(12, int(star_size))
        self._gap = 4
        self._value = self._normalize(value)
        self._display = float(self._value)
        self._hover = None
        self._anim = QVariantAnimation(self)
        self._anim.setDuration(DURATION["fast"])
        self._anim.setEasingCurve(EASING["standard"])
        self._anim.valueChanged.connect(self._on_anim)
        if not self._read_only:
            self.setMouseTracking(True)
            self.setCursor(Qt.PointingHandCursor)
        ThemeManager.instance().theme_changed.connect(self.update)
        # set_token 会话覆盖时重绘（QSS 不感知令牌覆盖，自绘需监听）
        TokenState.instance().token_changed.connect(self.update)

    # ------------------------------------------------------------------
    # 属性
    # ------------------------------------------------------------------

    def value(self) -> float:
        """当前分值。"""
        return self._value

    def set_value(self, value: float, animate: bool = True) -> None:
        """设置分值（默认平滑过渡），发射 ``valueChanged``。"""
        value = self._normalize(value)
        if value == self._value:
            return
        self._value = value
        if animate:
            self._anim.stop()
            self._anim.setStartValue(self._display)
            self._anim.setEndValue(float(value))
            self._anim.start()
        else:
            self._display = float(value)
            self.update()
        self.valueChanged.emit(self._value)

    def set_allow_half(self, on: bool) -> None:
        """设置是否允许半星。"""
        self._allow_half = bool(on)
        self.set_value(self._normalize(self._value))

    def set_read_only(self, on: bool) -> None:
        """设置只读模式。"""
        self._read_only = bool(on)
        self.setMouseTracking(not on)
        self.setCursor(Qt.PointingHandCursor if not on else Qt.ArrowCursor)

    def _normalize(self, value: float) -> float:
        value = max(0.0, min(float(self._count), float(value)))
        if self._allow_half:
            value = round(value * 2) / 2.0
        else:
            value = float(round(value))
        return value

    def _on_anim(self, v) -> None:
        self._display = float(v)
        self.update()

    # ------------------------------------------------------------------
    # 交互
    # ------------------------------------------------------------------

    def _value_at(self, x: float) -> float:
        """把 x 坐标换算为分值。"""
        cell = self._star + self._gap
        idx = int(x // cell)
        frac = (x - idx * cell) / self._star
        frac = max(0.0, min(1.0, frac))
        if self._allow_half:
            frac = math.ceil(frac * 2) / 2.0
        else:
            frac = 1.0 if frac > 0 else 0.0
        return self._normalize(idx + frac)

    def mouseMoveEvent(self, event):
        if self._read_only:
            return
        self._hover = self._value_at(event.position().x())
        self.update()

    def leaveEvent(self, event):
        self._hover = None
        self.update()
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        if self._read_only:
            return
        if event.button() == Qt.LeftButton:
            self.set_value(self._value_at(event.position().x()))

    # ------------------------------------------------------------------
    # 绘制
    # ------------------------------------------------------------------

    def sizeHint(self) -> QSize:
        w = self._count * self._star + (self._count - 1) * self._gap
        return QSize(w, self._star)

    def minimumSizeHint(self) -> QSize:
        return self.sizeHint()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        shown = self._hover if self._hover is not None else self._display
        filled = QColor(T("color.warning"))
        empty = QColor(T("color.text.disabled"))
        if not self.isEnabled():
            filled = QColor(T("color.text.disabled"))
            empty = QColor(T("color.bg.muted"))
        for i in range(self._count):
            cx = i * (self._star + self._gap) + self._star / 2.0
            cy = self.height() / 2.0
            star = _star_polygon(cx, cy, self._star / 2.0)
            frac = max(0.0, min(1.0, shown - i))
            # 先画空星
            p.setPen(Qt.NoPen)
            p.setBrush(empty)
            p.drawPolygon(star)
            # 再按比例裁剪画实星
            if frac > 0:
                p.save()
                path = QPainterPath()
                left = cx - self._star / 2.0
                path.addRect(left, 0, self._star * frac, self.height())
                p.setClipPath(path)
                p.setBrush(filled)
                p.drawPolygon(star)
                p.restore()
        p.end()
