# -*- coding: utf-8 -*-
"""日期选择器组件（SPEC §5.1）。

``DatePicker`` 基于 QDateEdit，弹出 :class:`~InstructionX_UIKit.components.calendar.Calendar`
（与「日历」页同一套中文表头 / 今日高亮 / 扁平单元格），统一显示格式为
``yyyy-MM-dd``。

本轮修复（轨道 2）：

- **高度对齐契约刻度**：QSS 里 ``QDateEdit`` 走 ``theme._SPIN_BOX``
  （``_INPUT_HEIGHTS - 5``）的私有几何表，Fusion 风格下只额外撑起 2px 边框，
  实际渲染为 19 / 25 / 31px，比声明的档位矮 3px（审计 ``SIZE`` 报错）。
  组件改为**只读复用** ``theme._INPUT_HEIGHTS``（唯一刻度来源），
  以实例级 QSS 覆盖内容盒高度，声明档位与实际渲染严格一致（22 / 28 / 34）。
- **弹层即组件**：改用共享 :class:`Calendar` 作为弹层，删掉原先裸
  ``QCalendarWidget`` 带来的「周日起始 + 竖排周次 + 默认红色周末」等
  与全局主题不一致的默认外观。
- **减法**：默认隐藏上下调节按钮（``NoButtons``），弹层指示箭头即为唯一
  调节入口；28px 控件里两个 12px 子控件塞 10px 箭头本就会互相挤掉
  （契约 §4 减法优先）。需要步进时传 ``stepper=True``。
"""

from PySide6.QtCore import QDate
from PySide6.QtWidgets import QAbstractSpinBox, QDateEdit

from ..theme import _INPUT_HEIGHTS
from ._mixin import SizeMixin
from .calendar import Calendar

__all__ = ["DatePicker"]

_FORMAT = "yyyy-MM-dd"

#: Qt QSS 盒模型：控件总高 = min/max-height（内容盒）+ 上下边框（各 1px）
_BORDER = 1


def input_height_qss(size: str, widget_class: str) -> str:
    """按输入控件刻度生成内容盒高度 QSS（供 date / time 两个选择器共用）。

    参数:
        size: ``sm`` / ``md`` / ``lg``。
        widget_class: 目标控件类名（QSS 类型选择器，须命中实例自身类）。

    返回:
        仅含 ``min-height`` / ``max-height`` 两条声明的 QSS 片段，其余样式
        仍由全局 QSS 提供（实例级 QSS 优先级更高，故能覆盖全局的
        ``max-height``，而 ``setFixedHeight`` 之类的程序化约束不行）。
    """
    content = _INPUT_HEIGHTS[size] - _BORDER * 2
    return (f"{widget_class} {{ min-height: {content}px; "
            f"max-height: {content}px; }}")


class DatePicker(SizeMixin, QDateEdit):
    """日期选择器。

    用途:
        日期录入：键盘输入或点击右侧指示箭头弹出主题化日历选择。

    参数:
        date: 初始日期（QDate），缺省为今天。
        size: ``sm`` / ``md`` / ``lg``，高度 22 / 28 / 34。
        stepper: 是否显示上下调节按钮；缺省 False（扁平，仅弹层选择）。
        parent: 父控件。

    示例::

        dp = DatePicker(size="md")
        dp.set_date_str("2025-06-15")
        dp.dateChanged.connect(lambda d: print(d.toString("yyyy-MM-dd")))

    备注:
        弹层复用 :class:`Calendar` 组件：周一起始、中文短表头、无竖排周次、
        今日主色高亮、周末按次级文字色渲染，与「日历」页完全一致。
    """

    #: 合法尺寸档（SizeMixin 校验用）
    _SIZES = ("sm", "md", "lg")
    _size_label = "日期选择器"

    def __init__(self, date: QDate = None, size: str = "md",
                 stepper: bool = False, parent=None):
        super().__init__(parent)
        self.setCalendarPopup(True)
        # 弹层复用共享 Calendar：周一起始 / 扁平单元格 / 今日高亮 / 周末语义色
        self._calendar = Calendar(self, framed=True)
        self.setCalendarWidget(self._calendar)
        self.setDisplayFormat(_FORMAT)
        self.setButtonSymbols(
            QAbstractSpinBox.UpDownArrows if stepper else QAbstractSpinBox.NoButtons)
        self.setDate(date if date is not None and date.isValid()
                     else QDate.currentDate())
        self.set_size(size)

    # ------------------------------------------------------------------
    # 尺寸：内容盒高度对齐 theme._INPUT_HEIGHTS（契约 §1 密度刻度）
    # ------------------------------------------------------------------

    def _apply_size(self, size: str) -> None:
        """SizeMixin 钩子：把内容盒高度锁定到当前尺寸档。"""
        qss = input_height_qss(size, type(self).__name__)
        if self.styleSheet() != qss:
            self.setStyleSheet(qss)

    # ------------------------------------------------------------------
    # 弹层
    # ------------------------------------------------------------------

    def calendar(self) -> Calendar:
        """弹层日历（共享 Calendar 组件实例）。"""
        return self._calendar

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
