# -*- coding: utf-8 -*-
"""时间选择器组件（SPEC §5.1）。

``TimePicker`` 基于 QTimeEdit，统一显示格式 ``HH:mm:ss``，
高度与调节按钮样式由全局 QSS 提供。
"""

from PySide6.QtCore import QTime
from PySide6.QtWidgets import QTimeEdit

from ._mixin import SizeMixin

__all__ = ["TimePicker"]

_FORMAT = "HH:mm:ss"


class TimePicker(SizeMixin, QTimeEdit):
    """时间选择器。

    用途:
        时间录入：分段编辑（时 / 分 / 秒）+ 调节按钮。

    参数:
        time: 初始时间（QTime），缺省为当前时间。
        size: ``sm`` / ``md`` / ``lg``，高度 24 / 32 / 40。
        parent: 父控件。

    示例::

        tp = TimePicker(size="md")
        tp.set_time_str("09:30:00")
        tp.timeChanged.connect(lambda t: print(t.toString("HH:mm:ss")))
    """

    #: 合法尺寸档（SizeMixin 校验用）
    _SIZES = ("sm", "md", "lg")
    _size_label = "时间选择器"

    def __init__(self, time: QTime = None, size: str = "md", parent=None):
        super().__init__(parent)
        self.setDisplayFormat(_FORMAT)
        self.setTime(time if time is not None and time.isValid()
                     else QTime.currentTime())
        self.set_size(size)

    # ------------------------------------------------------------------
    # 字符串便捷接口
    # ------------------------------------------------------------------

    def set_time_str(self, text: str) -> bool:
        """按 ``HH:mm:ss`` 字符串设置时间，返回是否解析成功。"""
        time = QTime.fromString(text, _FORMAT)
        if time.isValid():
            self.setTime(time)
            return True
        return False

    def time_str(self) -> str:
        """当前时间的 ``HH:mm:ss`` 字符串。"""
        return self.time().toString(_FORMAT)
