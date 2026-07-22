# -*- coding: utf-8 -*-
"""复选框组件（SPEC §5.1）。

``CheckBox`` 基于 QCheckBox，指示框样式由全局 QSS 提供
（含 checked / indeterminate / disabled 态），本类补充三态便捷封装。
"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QCheckBox

__all__ = ["CheckBox"]


class CheckBox(QCheckBox):
    """复选框。

    用途:
        多选 / 开关类输入，支持三态（部分选中）模式，
        指示框外观由全局 QSS 统一绘制。

    参数:
        text: 选项文案。
        tristate: 是否启用三态（Qt.PartiallyChecked）。
        checked: 初始勾选状态。
        parent: 父控件。

    示例::

        agree = CheckBox("我已阅读协议", checked=True)
        tri = CheckBox("全选", tristate=True)
        tri.set_check_state(Qt.PartiallyChecked)
    """

    def __init__(self, text: str = "", tristate: bool = False,
                 checked: bool = False, parent=None):
        super().__init__(text, parent)
        if tristate:
            self.setTristate(True)
        if checked:
            self.setChecked(True)

    # ------------------------------------------------------------------
    # 三态辅助
    # ------------------------------------------------------------------

    def set_tristate(self, on: bool) -> None:
        """设置是否启用三态。"""
        self.setTristate(on)

    def is_tristate(self) -> bool:
        """是否启用了三态。"""
        return self.isTristate()

    def set_check_state(self, state: Qt.CheckState) -> None:
        """设置勾选状态（Checked / Unchecked / PartiallyChecked）。"""
        self.setCheckState(state)

    def check_state(self) -> Qt.CheckState:
        """当前勾选状态。"""
        return self.checkState()
