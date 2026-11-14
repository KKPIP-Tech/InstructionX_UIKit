# -*- coding: utf-8 -*-
"""滑块组件（SPEC §5.1）。

``Slider`` 基于 QSlider，滑轨 / 手柄样式由全局 QSS 提供；
本类补充三档尺寸、刻度线与拖动时的数值气泡提示（QToolTip）。

**尺寸口径**：滑块没有「内容盒」概念，但它必须能和输入框并排放在同一
行，因此横向滑块的高度同样锁到契约 §1 的密度刻度；纵向滑块的高度是
它的**长度**而非厚度，故改锁宽度。三档的手柄尺寸由实例级 QSS 给出
（全局 QSS 只有一套固定的 12px 手柄，sm 档会显得过大）。
"""

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QCursor
from PySide6.QtWidgets import QSlider, QStyle, QStyleOptionSlider, QToolTip

from ..theme import T, _INPUT_HEIGHTS
from ._mixin import SizeMixin

__all__ = ["Slider"]

#: 各尺寸档的手柄 / 滑轨尺寸（px）。手柄直径 10 → 12 → 14 与密度刻度
#: （22 → 28 → 34）同步等差递进；``margin`` 是手柄相对滑轨的溢出量
#: （= 半手柄 + 半轨道），取整保证手柄完整落在控件内、不被裁切。
_HANDLE = {
    "sm": {"size": 10, "margin": -4, "groove": 4},
    "md": {"size": 12, "margin": -5, "groove": 4},
    "lg": {"size": 14, "margin": -6, "groove": 6},
}
#: 数值气泡与手柄的偏移：图标 ↔ 文字同源（layout.icon.gap）
_TIP_GAP = int(T("layout.icon.gap"))


def _size_qss(size: str) -> str:
    """按尺寸档生成手柄 / 滑轨 QSS（实例级，优先级高于全局 QSS）。"""
    h = _HANDLE[size]
    px, mg, gv = h["size"], h["margin"], h["groove"]
    radius = gv // 2
    return (
        "QSlider::groove:horizontal "
        f"{{ height: {gv}px; border-radius: {radius}px; }}"
        "QSlider::groove:vertical "
        f"{{ width: {gv}px; border-radius: {radius}px; }}"
        "QSlider::sub-page:horizontal, QSlider::add-page:horizontal "
        f"{{ border-radius: {radius}px; }}"
        "QSlider::sub-page:vertical, QSlider::add-page:vertical "
        f"{{ border-radius: {radius}px; }}"
        f"QSlider::handle:horizontal {{ width: {px}px; height: {px}px; "
        f"margin: {mg}px 0; border-radius: {px // 2}px; }}"
        f"QSlider::handle:vertical {{ width: {px}px; height: {px}px; "
        f"margin: 0 {mg}px; border-radius: {px // 2}px; }}"
    )


class Slider(SizeMixin, QSlider):
    """滑块。

    用途:
        连续数值选择；支持刻度线与拖动时跟随手柄的数值提示。

    参数:
        orientation: ``Qt.Horizontal`` / ``Qt.Vertical``。
        minimum / maximum: 取值范围。
        value: 初始值。
        size: ``sm`` / ``md`` / ``lg``。横向滑块锁高度，纵向滑块锁宽度。
        parent: 父控件。

    示例::

        vol = Slider(minimum=0, maximum=100, value=45, size="md")
        vol.set_ticks(10)
        vol.valueChanged.connect(print)

    备注:
        全局 QSS 的 ``::groove`` / ``::handle`` 子控件样式接管了绘制，
        Qt 不再绘制刻度线与刻度文字（实测），因此锁死高度不会裁掉内容；
        ``set_ticks`` 仍保留，用于设置间隔与位置语义。
    """

    #: 合法尺寸档（SizeMixin 校验用）
    _SIZES = ("sm", "md", "lg")
    _size_label = "滑块"

    def __init__(self, orientation: Qt.Orientation = Qt.Horizontal,
                 minimum: int = 0, maximum: int = 100, value: int = 0,
                 size: str = "md", parent=None):
        super().__init__(orientation, parent)
        self.setRange(minimum, maximum)
        self.setValue(value)
        self._tip_enabled = True
        self.valueChanged.connect(self._maybe_show_tip)
        self.sliderReleased.connect(QToolTip.hideText)
        self.set_size(size)

    # ------------------------------------------------------------------
    # 尺寸
    # ------------------------------------------------------------------

    def _apply_size(self, size: str) -> None:
        """SizeMixin 钩子：锁横向高度 / 纵向宽度 + 按档切换手柄尺寸。

        横向锁高、纵向锁宽：纵向滑块的高度是它的**长度**而非厚度，
        真正对应「档位」的是宽度。两种方向都用固定值而非下限——滑块要
        能和输入框并排放进同一行，高度必须严格等于密度刻度。
        """
        edge = _INPUT_HEIGHTS[size]
        if self.orientation() == Qt.Vertical:
            self.setFixedWidth(edge)
        else:
            self.setFixedHeight(edge)
        qss = _size_qss(size)
        if self.styleSheet() != qss:
            self.setStyleSheet(qss)

    # ------------------------------------------------------------------
    # 刻度
    # ------------------------------------------------------------------

    def set_ticks(self, interval: int, position: QSlider.TickPosition = None) -> None:
        """设置刻度间隔与位置（默认在下方 / 左侧）。"""
        if position is None:
            position = (QSlider.TicksBelow
                        if self.orientation() == Qt.Horizontal
                        else QSlider.TicksLeft)
        self.setTickInterval(interval)
        self.setTickPosition(position)

    # ------------------------------------------------------------------
    # 数值提示
    # ------------------------------------------------------------------

    def set_tip_enabled(self, on: bool) -> None:
        """开关拖动时的数值气泡提示。"""
        self._tip_enabled = bool(on)
        if not on:
            QToolTip.hideText()

    def _maybe_show_tip(self, value: int) -> None:
        if not self._tip_enabled or not self.isSliderDown():
            return
        opt = QStyleOptionSlider()
        self.initStyleOption(opt)
        rect = self.style().subControlRect(
            QStyle.CC_Slider, opt, QStyle.SC_SliderHandle, self)
        if self.orientation() == Qt.Horizontal:
            pos = self.mapToGlobal(
                QPoint(rect.center().x(), rect.top() - _TIP_GAP))
        else:
            pos = self.mapToGlobal(
                QPoint(rect.right() + _TIP_GAP, rect.center().y()))
        if pos.isNull():
            pos = QCursor.pos()
        QToolTip.showText(pos, str(value), self)
