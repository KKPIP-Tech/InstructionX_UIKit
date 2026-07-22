# -*- coding: utf-8 -*-
"""日期选择器组件（SPEC §5.1）。

``DatePicker`` 基于 QDateEdit，弹出 QCalendarWidget（其导航栏 /
表头 / 选中态样式由全局 QSS 定制），统一显示格式为 ``yyyy-MM-dd``。
"""

from PySide6.QtCore import QDate
from PySide6.QtWidgets import QCalendarWidget, QDateEdit

from ..theme import set_property

__all__ = ["DatePicker"]

_SIZES = ("sm", "md", "lg")
_FORMAT = "yyyy-MM-dd"


class DatePicker(QDateEdit):
    """日期选择器。

    用途:
        日期录入：键盘输入或点击弹出主题化日历选择。

    参数:
        date: 初始日期（QDate），缺省为今天。
        size: ``sm`` / ``md`` / ``lg``，高度 24 / 32 / 40。
        parent: 父控件。

    示例::

        dp = DatePicker(size="md")
        dp.set_date_str("2025-06-15")
        dp.dateChanged.connect(lambda d: print(d.toString("yyyy-MM-dd")))
    """

    def __init__(self, date: QDate = None, size: str = "md", parent=None):
        super().__init__(parent)
        self.setCalendarPopup(True)
        calendar = QCalendarWidget(self)
        self.setCalendarWidget(calendar)
        self.setDisplayFormat(_FORMAT)
        self.setDate(date if date is not None and date.isValid()
                     else QDate.currentDate())
        self.set_size(size)

    def set_size(self, size: str) -> None:
        """设置尺寸档：``sm`` / ``md`` / ``lg``。"""
        if size not in _SIZES:
            raise ValueError(f"未知日期选择器尺寸: {size!r}")
        set_property(self, "size", size)

    def size_name(self) -> str:
        """当前尺寸档名。"""
        return self.property("uiksize") or "md"

    # ------------------------------------------------------------------
    # 字符串便捷接口
    # ------------------------------------------------------------------

    def set_date_str(self, text: str) -> bool:
        """按 ``yyyy-MM-dd`` 字符串设置日期，返回是否解析成功。"""
        date = QDate.fromString(text, _FORMAT)
        if date.isValid():
            self.setDate(date)
            return True
        return False

    def date_str(self) -> str:
        """当前日期的 ``yyyy-MM-dd`` 字符串。"""
        return self.date().toString(_FORMAT)
