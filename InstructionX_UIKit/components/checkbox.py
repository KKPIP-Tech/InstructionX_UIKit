# -*- coding: utf-8 -*-
"""复选框组件（SPEC §5.1）。

``CheckBox`` 基于 QCheckBox，指示框样式由全局 QSS 提供
（含 checked / indeterminate / disabled 态），本类补充三态便捷封装
与三档尺寸。

**尺寸口径**：全局 QSS 只给了 16px 的固定指示框，三档尺寸无法区分，
复选框与同行的输入框（22 / 28 / 34）因此对不齐。故本类以**实例级 QSS**
按 ``uiksize`` 覆盖指示框边长，并把控件高度锁到契约 §1 的密度刻度，
使复选框行与表单里的输入控件严格等高、垂直居中。
"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QCheckBox

from ..theme import T, _INPUT_HEIGHTS
from ._mixin import SizeMixin

__all__ = ["CheckBox"]

#: 指示框边长（px）：随尺寸档递增，两档各 +2（契约 §9 三档均需正常渲染）
_INDICATOR = {"sm": 14, "md": 16, "lg": 18}
#: 指示框 ↔ 文案的间距：图标 ↔ 文字同源（layout.icon.gap）
_INDICATOR_GAP = int(T("layout.icon.gap"))


def _size_qss(size: str) -> str:
    """按尺寸档生成指示框 QSS（实例级，优先级高于全局 QSS）。

    全局 QSS 只有一条 16px 的 ``QCheckBox::indicator``，没有尺寸选择器；
    在此按 ``uiksize`` 补齐三档，使复选框与输入框同档同高。
    """
    edge = _INDICATOR[size]
    return (
        f"QCheckBox::indicator {{ width: {edge}px; height: {edge}px; }}"
        f"QCheckBox {{ spacing: {_INDICATOR_GAP}px; }}"
    )


class CheckBox(SizeMixin, QCheckBox):
    """复选框。

    用途:
        多选 / 开关类输入，支持三态（部分选中）模式，
        指示框外观由全局 QSS 统一绘制。

    参数:
        text: 选项文案。
        tristate: 是否启用三态（Qt.PartiallyChecked）。
        checked: 初始勾选状态。
        size: ``sm`` / ``md`` / ``lg``，高度 22 / 28 / 34。
        parent: 父控件。

    示例::

        agree = CheckBox("我已阅读协议", checked=True)
        tri = CheckBox("全选", tristate=True)
        tri.set_check_state(Qt.PartiallyChecked)

    备注:
        控件高度按密度刻度锁定，指示框与文案在行内垂直居中，
        因此复选框可以直接与输入框放进同一行而不出现错位。
    """

    #: 合法尺寸档（SizeMixin 校验用）
    _SIZES = ("sm", "md", "lg")
    _size_label = "复选框"

    def __init__(self, text: str = "", tristate: bool = False,
                 checked: bool = False, size: str = "md", parent=None):
        super().__init__(text, parent)
        if tristate:
            self.setTristate(True)
        if checked:
            self.setChecked(True)
        self.set_size(size)

    # ------------------------------------------------------------------
    # 尺寸
    # ------------------------------------------------------------------

    def _apply_size(self, size: str) -> None:
        """SizeMixin 钩子：锁定高度 + 按档切换指示框边长。"""
        # 高度用 QSS 而非 setFixedHeight：全局 QWidget 基座规则的字号会
        # 抬高 sizeHint，实例级 QSS 才能给出与输入框严格相等的高度。
        qss = (f"QCheckBox {{ min-height: {_INPUT_HEIGHTS[size]}px; "
               f"max-height: {_INPUT_HEIGHTS[size]}px; }}"
               + _size_qss(size))
        if self.styleSheet() != qss:
            self.setStyleSheet(qss)

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
