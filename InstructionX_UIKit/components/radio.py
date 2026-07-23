# -*- coding: utf-8 -*-
"""单选框组件（SPEC §5.1）。

``RadioButton`` 基于 QRadioButton（指示器样式由全局 QSS 提供）；
``RadioGroup`` 为 QButtonGroup 的便捷封装，提供按 id 管理与文案查询。
"""

from PySide6.QtWidgets import QButtonGroup, QRadioButton

__all__ = ["RadioButton", "RadioGroup"]


class RadioButton(QRadioButton):
    """单选框。

    用途:
        互斥单选输入；同一父控件 / 同一 RadioGroup 内自动互斥。

    参数:
        text: 选项文案。
        checked: 初始选中状态。
        parent: 父控件。

    示例::

        a = RadioButton("方案一", checked=True)
        b = RadioButton("方案二")
        c = RadioButton("方案三")
    """

    def __init__(self, text: str = "", checked: bool = False, parent=None):
        super().__init__(text, parent)
        if checked:
            self.setChecked(True)


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

    # ------------------------------------------------------------------
    # 按钮管理
    # ------------------------------------------------------------------

    def add_button(self, button, id: int = None):
        """添加按钮；传入字符串时自动创建 ``RadioButton``。

        参数:
            button: ``RadioButton`` 实例或选项文案。
            id: 业务 id，缺省时自增分配。

        返回:
            添加的按钮实例。
        """
        if isinstance(button, str):
            button = RadioButton(button)
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
