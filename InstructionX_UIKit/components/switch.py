# -*- coding: utf-8 -*-
"""开关组件（SPEC §5.1）。

``Switch`` 基于 QAbstractButton 全自绘：轨道 + 滑块，
切换时使用 QVariantAnimation 平滑过渡滑块位置与轨道颜色，
动画时长与缓动取自设计令牌 ``tokens.DURATION`` / ``tokens.EASING``。

**几何口径**：轨道高度严格等于该尺寸档的控件高度
（``theme._INPUT_HEIGHTS``，契约 §1：sm 22 / md 28 / lg 34），
不另设私有几何表——否则「声明的档位」与「实际渲染高度」会脱节，
消费者把开关放进表单行时无法与其他控件对齐。

轨道宽度由高度推导，而非手写三组字面量：手柄直径 = 高度 − 2×内缩，
手柄行程 = 自身直径，故 宽 = 2×手柄 + 2×内缩。三档宽高比因此恒定在
1.82~1.88 之间（不是拍脑袋的三组数字）。
"""

from PySide6.QtCore import Qt, QVariantAnimation
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QAbstractButton

from ..theme import T, ThemeManager, _INPUT_HEIGHTS
from ..tokens import DURATION, EASING, TokenState
from ._mixin import SizeMixin

__all__ = ["Switch"]

#: 手柄与轨道边缘的内缩（px），取 2px 基网格半档（space.05）
_INSET = int(T("space.05"))

#: 各尺寸档 (宽, 高)。高度直接引用 theme._INPUT_HEIGHTS（唯一刻度来源），
#: 宽度按上面推导式算出，保证宽高比在三档间恒定。
_GEOMETRY = {
    size: (int(h - 2 * _INSET) * 2 + 2 * int(_INSET), h)
    for size, h in _INPUT_HEIGHTS.items()
}


def _blend(c1: QColor, c2: QColor, ratio: float) -> QColor:
    """按 0..1 比例线性插值两种颜色。"""
    r = c1.red() + (c2.red() - c1.red()) * ratio
    g = c1.green() + (c2.green() - c1.green()) * ratio
    b = c1.blue() + (c2.blue() - c1.blue()) * ratio
    return QColor(int(r), int(g), int(b))


class Switch(SizeMixin, QAbstractButton):
    """滑块开关。

    用途:
        二元状态切换（开 / 关），全自绘并带平滑过渡动画。

    参数:
        checked: 初始开关状态。
        size: ``sm``（40x22）/ ``md``（52x28）/ ``lg``（64x34）。
        parent: 父控件。

    示例::

        sw = Switch(checked=True, size="md")
        sw.toggled.connect(lambda on: print("开关:", on))
        sw.setChecked(False)

    备注:
        手柄颜色恒为 ``color.on.primary``：开态是「主色之上」的手柄，
        关态则落在灰轨道上，两种主题下手柄与轨道的对比度均 ≥ 3:1
        （非文本 UI 元素的对比度要求）。
    """

    #: 合法尺寸档（SizeMixin 校验用）
    _SIZES = tuple(_INPUT_HEIGHTS)
    _size_label = "开关"

    def __init__(self, checked: bool = False, size: str = "md", parent=None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        # 键盘可达：开关是纯二元控件，需要可见的焦点态
        self.setFocusPolicy(Qt.StrongFocus)
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

    def _apply_size(self, size: str) -> None:
        """SizeMixin 钩子：按尺寸档固定宽高（高度 = 该档控件高度）。"""
        w, h = _GEOMETRY[size]
        self.setFixedSize(w, h)

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
        # 轨道颜色：未选中（占位灰）→ 选中（主色）插值
        track = _blend(QColor(T("color.text.tertiary")),
                       QColor(T("color.primary")), self._pos)
        p.setPen(Qt.NoPen)
        p.setBrush(track)
        p.drawRoundedRect(0, 0, w, h, radius, radius)

        # 手柄：直径 = 高 − 2×内缩，行程 = 自身直径
        knob = h - 2 * _INSET
        x = _INSET + (w - knob - 2 * _INSET) * self._pos
        p.setBrush(QColor(T("color.on.primary")))
        p.drawEllipse(int(x), _INSET, int(knob), int(knob))

        # 焦点态：轨道内侧描一圈主色。画在轨道内而非外侧，避免超出控件
        # 边界被裁切（自绘控件不参与全局 QSS 的 focus 规则）。
        if self.hasFocus():
            p.setBrush(Qt.NoBrush)
            p.setPen(QColor(T("color.primary")))
            p.drawRoundedRect(0.5, 0.5, w - 1, h - 1, radius, radius)
        p.end()

    def sizeHint(self):
        return self.size()
