# -*- coding: utf-8 -*-
"""开关组件（SPEC §5.1）。

``Switch`` 基于 QAbstractButton 全自绘：轨道 + 滑块，
切换时使用 QVariantAnimation 平滑过渡滑块位置与轨道颜色，
动画时长与缓动取自设计令牌 ``tokens.DURATION`` / ``tokens.EASING``。
"""

from PySide6.QtCore import Qt, QVariantAnimation
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QAbstractButton

from ..theme import T, ThemeManager, set_property
from ..tokens import DURATION, EASING, TokenState

__all__ = ["Switch"]

_SIZES = ("sm", "md")
#: 各尺寸档 (宽, 高)
_GEOMETRY = {"sm": (32, 16), "md": (44, 22)}


def _blend(c1: QColor, c2: QColor, ratio: float) -> QColor:
    """按 0..1 比例线性插值两种颜色。"""
    r = c1.red() + (c2.red() - c1.red()) * ratio
    g = c1.green() + (c2.green() - c1.green()) * ratio
    b = c1.blue() + (c2.blue() - c1.blue()) * ratio
    return QColor(int(r), int(g), int(b))


class Switch(QAbstractButton):
    """滑块开关。

    用途:
        二元状态切换（开 / 关），全自绘并带平滑过渡动画。

    参数:
        checked: 初始开关状态。
        size: ``sm``（32x16）/ ``md``（44x22）。
        parent: 父控件。

    示例::

        sw = Switch(checked=True, size="md")
        sw.toggled.connect(lambda on: print("开关:", on))
        sw.setChecked(False)
    """

    def __init__(self, checked: bool = False, size: str = "md", parent=None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self._pos = 1.0 if checked else 0.0
        self.setChecked(checked)
        # 位置过渡动画
        self._anim = QVariantAnimation(self)
        self._anim.setDuration(DURATION["normal"])
        self._anim.setEasingCurve(EASING["standard"])
        self._anim.valueChanged.connect(self._on_anim)
        self.toggled.connect(self._start_transition)
        self.set_size(size)
        ThemeManager.instance().theme_changed.connect(self.update)
        # set_token 会话覆盖时重绘（QSS 不感知令牌覆盖，自绘需监听）
        TokenState.instance().token_changed.connect(self.update)

    # ------------------------------------------------------------------
    # 尺寸
    # ------------------------------------------------------------------

    def set_size(self, size: str) -> None:
        """设置尺寸档：``sm`` / ``md``。"""
        if size not in _SIZES:
            raise ValueError(f"未知开关尺寸: {size!r}")
        set_property(self, "size", size)
        w, h = _GEOMETRY[size]
        self.setFixedSize(w, h)

    def size_name(self) -> str:
        """当前尺寸档名。"""
        return self.property("uiksize") or "md"

    # ------------------------------------------------------------------
    # 动画
    # ------------------------------------------------------------------

    def _start_transition(self, checked: bool) -> None:
        """从当前位置动画过渡到目标位置。"""
        self._anim.stop()
        self._anim.setStartValue(self._pos)
        self._anim.setEndValue(1.0 if checked else 0.0)
        self._anim.start()

    def _on_anim(self, value) -> None:
        self._pos = float(value)
        self.update()

    # ------------------------------------------------------------------
    # 绘制
    # ------------------------------------------------------------------

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        if not self.isEnabled():
            p.setOpacity(0.5)
        w, h = self.width(), self.height()
        radius = h / 2.0
        # 轨道颜色：未选中（三级文本灰）→ 选中（主色）插值
        track = _blend(QColor(T("color.text.tertiary")),
                       QColor(T("color.primary")), self._pos)
        p.setPen(Qt.NoPen)
        p.setBrush(track)
        p.drawRoundedRect(0, 0, w, h, radius, radius)
        # 滑块
        margin = 2.0
        knob = h - margin * 2
        x = margin + (w - knob - margin * 2) * self._pos
        p.setBrush(QColor(T("color.on.primary")))
        p.drawEllipse(int(x), int(margin), int(knob), int(knob))
        p.end()

    def sizeHint(self):
        return self.size()
