# -*- coding: utf-8 -*-
"""数字调节框组件（SPEC §5.1）。

``SpinBox`` / ``DoubleSpinBox`` 基于 QSpinBox / QDoubleSpinBox，
底板（背景 / 边框 / 圆角 / 聚焦态）由全局 QSS 提供。

**高度口径**：本轮修复了「声明 md 却只渲染 25px」的缺陷。原因是全局 QSS
的 ``_SPIN_BOX`` 私有几何表按 ``_INPUT_HEIGHTS - 5`` 计算内容盒高度，
Fusion 风格下实际只额外撑起 2px 边框（而非其注释里假设的 3px），
三档因此各差 3px。现与 DatePicker / TimePicker 共用
``date_picker.input_height_qss``，以**实例级 QSS** 把内容盒高度锁定到
22 / 28 / 34（契约 §1），三个尺寸档口径完全一致。
"""

from PySide6.QtWidgets import QDoubleSpinBox, QSpinBox

from ._mixin import SizeMixin
from .date_picker import input_height_qss

__all__ = ["SpinBox", "DoubleSpinBox"]

#: QSS 类型选择器名：QSpinBox 与 QDoubleSpinBox 是两个不同的类，
#: 高度 QSS 必须按各自类名下发，否则只命中其中一个。
_QSS_CLASS = {"SpinBox": "QSpinBox", "DoubleSpinBox": "QDoubleSpinBox"}


class _SpinBoxSizeMixin(SizeMixin):
    """``SpinBox`` / ``DoubleSpinBox`` 共用的尺寸档实现。"""

    #: 合法尺寸档（SizeMixin 校验用）
    _SIZES = ("sm", "md", "lg")
    _size_label = "调节框"

    def _apply_size(self, size: str) -> None:
        """SizeMixin 钩子：锁定内容盒高度（契约 §1 密度刻度）。

        走实例级 QSS 而非 ``setFixedHeight``：QSS 的 ``min/max-height``
        优先级高于程序化尺寸约束，只有更具体的实例级 QSS 才能压过全局
        QSS 里那条少算 3px 的 ``max-height``。
        """
        qss = input_height_qss(size, _QSS_CLASS[type(self).__name__])
        if self.styleSheet() != qss:
            self.setStyleSheet(qss)


class SpinBox(_SpinBoxSizeMixin, QSpinBox):
    """整数调节框。

    用途:
        整数数值录入，带上下调节按钮（样式由全局 QSS 提供）。

    参数:
        minimum / maximum: 取值范围。
        value: 初始值。
        step: 步进。
        size: ``sm``（22）/ ``md``（28）/ ``lg``（34）。
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


class DoubleSpinBox(_SpinBoxSizeMixin, QDoubleSpinBox):
    """小数调节框。

    用途:
        浮点数值录入，支持小数位数与前缀 / 后缀单位。

    参数:
        minimum / maximum: 取值范围。
        value: 初始值。
        step: 步进。
        decimals: 小数位数。
        suffix: 后缀单位文本（如 " px"）。
        size: ``sm``（22）/ ``md``（28）/ ``lg``（34）。
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
