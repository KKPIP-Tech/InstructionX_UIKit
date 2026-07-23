# -*- coding: utf-8 -*-
"""滑块组件（SPEC §5.1）。

``Slider`` 基于 QSlider，滑轨 / 手柄样式由全局 QSS 提供；
本类补充刻度线与拖动时的数值气泡提示（QToolTip）。
"""

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QCursor
from PySide6.QtWidgets import QSlider, QStyle, QStyleOptionSlider, QToolTip

__all__ = ["Slider"]


class Slider(QSlider):
    """滑块。

    用途:
        连续数值选择；支持刻度线与拖动时跟随手柄的数值提示。

    参数:
        orientation: ``Qt.Horizontal`` / ``Qt.Vertical``。
        minimum / maximum: 取值范围。
        value: 初始值。
        parent: 父控件。

    示例::

        vol = Slider(minimum=0, maximum=100, value=45)
        vol.set_ticks(10)
        vol.valueChanged.connect(print)
    """

    def __init__(self, orientation: Qt.Orientation = Qt.Horizontal,
                 minimum: int = 0, maximum: int = 100, value: int = 0,
                 parent=None):
        super().__init__(orientation, parent)
        self.setRange(minimum, maximum)
        self.setValue(value)
        self._tip_enabled = True
        self.valueChanged.connect(self._maybe_show_tip)
        self.sliderReleased.connect(QToolTip.hideText)

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
            pos = self.mapToGlobal(QPoint(rect.center().x(), rect.top() - 6))
        else:
            pos = self.mapToGlobal(QPoint(rect.right() + 6, rect.center().y()))
        if pos.isNull():
            pos = QCursor.pos()
        QToolTip.showText(pos, str(value), self)
