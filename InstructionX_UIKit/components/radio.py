# -*- coding: utf-8 -*-
"""单选框组件（SPEC §5.1）。

``RadioButton`` 基于 QRadioButton（指示器样式由全局 QSS 提供）；
``RadioGroup`` 为 QButtonGroup 的便捷封装，提供按 id 管理与文案查询。

**尺寸口径**：全局 QSS 已为单选框备好 ``[uiksize=sm|lg]`` 的指示器
选择器（md 走基础规则），但组件从不设置 ``size`` 动态属性，
那几条规则始终是死代码。本类补上 ``size`` 参数并把控件高度锁到
契约 §1 的密度刻度，单选框行因此能与同行的输入框严格等高。
"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QButtonGroup, QRadioButton

from ..theme import _INPUT_HEIGHTS
from ._mixin import SizeMixin

__all__ = ["RadioButton", "RadioGroup"]


class RadioButton(SizeMixin, QRadioButton):
    """单选框。

    用途:
        互斥单选输入；同一父控件 / 同一 RadioGroup 内自动互斥。

    参数:
        text: 选项文案。
        checked: 初始选中状态。
        size: ``sm`` / ``md`` / ``lg``，高度 22 / 28 / 34。
        parent: 父控件。

    示例::

        a = RadioButton("方案一", checked=True)
        b = RadioButton("方案二", size="sm")
        c = RadioButton("方案三")

    备注:
        指示器边长由全局 QSS 的 ``[uiksize]`` 规则按档切换，本类只负责
        设置属性并把控件高度对齐密度刻度。
    """

    #: 合法尺寸档（SizeMixin 校验用）
    _SIZES = ("sm", "md", "lg")
    _size_label = "单选框"

    def __init__(self, text: str = "", checked: bool = False,
                 size: str = "md", parent=None):
        super().__init__(text, parent)
        if checked:
            self.setChecked(True)
        self.set_size(size)

    # ------------------------------------------------------------------
    # 尺寸
    # ------------------------------------------------------------------

    def _apply_size(self, size: str) -> None:
        """SizeMixin 钩子：锁定高度（指示器边长走全局 QSS 的尺寸选择器）。"""
        height = _INPUT_HEIGHTS[size]
        qss = (f"QRadioButton {{ min-height: {height}px; "
               f"max-height: {height}px; }}")
        if self.styleSheet() != qss:
            self.setStyleSheet(qss)


class RadioGroup(QButtonGroup):
    """单选分组（QButtonGroup 便捷封装）。

    用途:
        管理一组互斥单选按钮，按 id 读取 / 设置选中项。
        选中变化可连接 Qt6 内置 ``idToggled(int, bool)`` 信号。

    参数:
        exclusive: 是否互斥（默认 True）。
        parent: 父对象。

    示例::

        group = RadioGroup()
        r1 = group.add_button("按月付", id=1)
        r2 = group.add_button("按年付", id=2)
        group.set_checked_id(2)
    """

    def __init__(self, parent=None, exclusive: bool = True):
        super().__init__(parent)
        self.setExclusive(exclusive)
        self._auto_id = 0
        self._owned_buttons = []  # 字符串创建的按钮（组内保活，防 GC）

    # ------------------------------------------------------------------
    # 按钮管理
    # ------------------------------------------------------------------

    def add_button(self, button, id: int = None, size: str = "md"):
        """添加按钮；传入字符串时自动创建 ``RadioButton``。

        参数:
            button: ``RadioButton`` 实例或选项文案。
            id: 业务 id（整数），缺省时自增分配；非整数抛 ``ValueError``。
            size: 仅在按文案创建按钮时生效的尺寸档（sm / md / lg），
                默认 ``md``，与 ``RadioButton`` 的默认值一致。

        返回:
            添加的按钮实例。

        备注:
            由字符串创建的按钮没有外部引用，由组持有保活（无父控件的
            按钮被垃圾回收后 C++ 对象随之销毁，会从界面消失）。
        """
        if id is not None and not isinstance(id, int):
            raise ValueError(f"非法单选按钮 id: {id!r}，应为整数")
        if isinstance(button, str):
            button = RadioButton(button, size=size)
            self._owned_buttons.append(button)
        if id is None:
            self._auto_id += 1
            id = self._auto_id
        self._auto_id = max(self._auto_id, id)
        self.addButton(button, id)
        return button

    def set_checked_id(self, id: int) -> None:
        """按 id 选中按钮；id 不存在时取消全部选中。"""
        btn = self.button(id)
        if btn is not None:
            btn.setChecked(True)
        elif self.checkedButton() is not None:
            self.setExclusive(False)
            self.checkedButton().setChecked(False)
            self.setExclusive(True)

    def checked_id(self) -> int:
        """当前选中按钮的 id，未选中返回 -1。"""
        return self.checkedId()

    def checked_text(self) -> str:
        """当前选中按钮的文案，未选中返回空串。"""
        btn = self.checkedButton()
        return btn.text() if btn is not None else ""

    def set_checked_text(self, text: str) -> bool:
        """按文案选中按钮，返回是否找到。"""
        for btn in self.buttons():
            if btn.text() == text:
                btn.setChecked(True)
                return True
        return False
