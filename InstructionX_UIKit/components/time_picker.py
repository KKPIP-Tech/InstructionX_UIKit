# -*- coding: utf-8 -*-
"""时间选择器组件（SPEC §5.1）。

``TimePicker`` 基于 QTimeEdit，统一显示格式 ``HH:mm:ss``，与 :class:`DatePicker`
共用同一套「输入控件刻度 → QSS 内容盒高度」换算（``input_height_qss``），
因此两者的 sm / md / lg 高度口径完全一致。

本轮修复（轨道 2）：

- **高度对齐契约刻度**：原实现声明 ``uiksize="md"`` 却只渲染 25px
  （全局 QSS 的 ``_SPIN_BOX`` 私有几何表比实际多算 3px，审计 ``SIZE`` 报错）。
  现按 ``theme._INPUT_HEIGHTS`` 以实例级 QSS 锁定内容盒高度：22 / 28 / 34。
- **分节间距取令牌**：``HH : mm : ss`` 分节器与文字的间距改用
  ``layout.icon.gap``，不再写死 2px 裸数字（契约 §2）。
"""

from PySide6.QtCore import QTime
from PySide6.QtWidgets import QTimeEdit

from ..theme import T
from ._mixin import SizeMixin
from .date_picker import input_height_qss

__all__ = ["TimePicker"]

_FORMAT = "HH:mm:ss"


class TimePicker(SizeMixin, QTimeEdit):
    """时间选择器。

    用途:
        时间录入：分段编辑（时 / 分 / 秒）+ 调节按钮。

    参数:
        time: 初始时间（QTime），缺省为当前时间。
        size: ``sm`` / ``md`` / ``lg``，高度 22 / 28 / 34。
        stepper: 是否显示上下调节按钮；缺省 True（分段步进仍是时间录入的
            主交互入口，28px 刻度下两个 13px 子控件各容一枚 10px 箭头）。
        parent: 父控件。

    示例::

        tp = TimePicker(size="md")
        tp.set_time_str("09:30:00")
        tp.timeChanged.connect(lambda t: print(t.toString("HH:mm:ss")))

    备注:
        分节器（``HH`` 与 ``mm`` 之间的 ``:``）左右留白取
        ``layout.icon.gap``，与导航项「图标 ↔ 文字」同源，三档同步缩放。
    """

    #: 合法尺寸档（SizeMixin 校验用）
    _SIZES = ("sm", "md", "lg")
    _size_label = "时间选择器"

    def __init__(self, time: QTime = None, size: str = "md",
                 stepper: bool = True, parent=None):
        super().__init__(parent)
        self.setDisplayFormat(_FORMAT)
        self.setTime(time if time is not None and time.isValid()
                     else QTime.currentTime())
        self.set_size(size)

    # ------------------------------------------------------------------
    # 尺寸：内容盒高度对齐 theme._INPUT_HEIGHTS（契约 §1 密度刻度）
    # ------------------------------------------------------------------

    def _apply_size(self, size: str) -> None:
        """SizeMixin 钩子：锁定内容盒高度 + 分节器留白。"""
        # 分节器只接受 QSS 可识别的边距写法；用令牌值而非裸数字，
        # 避免同一控件在三个尺寸档下出现不同的魔数间距
        gap = int(T("layout.icon.gap"))
        qss = (input_height_qss(size, type(self).__name__)
               + f" QTimeEdit::section {{ margin: 0 {gap}px; }}")
        if self.styleSheet() != qss:
            self.setStyleSheet(qss)

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
