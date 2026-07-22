# -*- coding: utf-8 -*-
"""数字调节框组件（SPEC §5.1）。

``SpinBox`` / ``DoubleSpinBox`` 基于 QSpinBox / QDoubleSpinBox，
高度与按钮样式由全局 QSS 统一（sm=24 / md=32 / lg=40），
本类提供构造即配置的便捷封装。
"""

from PySide6.QtWidgets import QDoubleSpinBox, QSpinBox

from ..theme import set_property

__all__ = ["SpinBox", "DoubleSpinBox"]

_SIZES = ("sm", "md", "lg")


class SpinBox(QSpinBox):
    """整数调节框。

    用途:
        整数数值录入，带上下调节按钮（样式由全局 QSS 提供）。

    参数:
        minimum / maximum: 取值范围。
        value: 初始值。
        step: 步进。
        size: ``sm`` / ``md`` / ``lg``。
        parent: 父控件。

    示例::

        qty = SpinBox(minimum=1, maximum=99, value=2, size="md")
        qty.valueChanged.connect(print)
    """

    def __init__(self, minimum: int = 0, maximum: int = 99, value: int = 0,
                 step: int = 1, size: str = "md", parent=None):
        super().__init__(parent)
        self.setRange(minimum, maximum)
        self.setSingleStep(step)
        self.setValue(value)
        self.set_size(size)

    def set_size(self, size: str) -> None:
        """设置尺寸档：``sm`` / ``md`` / ``lg``。"""
        if size not in _SIZES:
            raise ValueError(f"未知调节框尺寸: {size!r}")
        set_property(self, "size", size)

    def size_name(self) -> str:
        """当前尺寸档名。"""
        return self.property("uiksize") or "md"


class DoubleSpinBox(QDoubleSpinBox):
    """小数调节框。

    用途:
        浮点数值录入，支持小数位数与前缀 / 后缀单位。

    参数:
        minimum / maximum: 取值范围。
        value: 初始值。
        step: 步进。
        decimals: 小数位数。
        suffix: 后缀单位文本（如 " px"）。
        size: ``sm`` / ``md`` / ``lg``。
        parent: 父控件。

    示例::

        price = DoubleSpinBox(minimum=0.0, maximum=9999.0, value=19.9,
                              decimals=2, suffix=" 元")
        price.valueChanged.connect(print)
    """

    def __init__(self, minimum: float = 0.0, maximum: float = 99.99,
                 value: float = 0.0, step: float = 1.0, decimals: int = 2,
                 suffix: str = "", size: str = "md", parent=None):
        super().__init__(parent)
        self.setRange(minimum, maximum)
        self.setSingleStep(step)
        self.setDecimals(decimals)
        if suffix:
            self.setSuffix(suffix)
        self.setValue(value)
        self.set_size(size)

    def set_size(self, size: str) -> None:
        """设置尺寸档：``sm`` / ``md`` / ``lg``。"""
        if size not in _SIZES:
            raise ValueError(f"未知调节框尺寸: {size!r}")
        set_property(self, "size", size)

    def size_name(self) -> str:
        """当前尺寸档名。"""
        return self.property("uiksize") or "md"
