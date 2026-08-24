# -*- coding: utf-8 -*-
"""组件私有共享混入（不进组件包 ``__init__`` 导出）。

``SizeMixin`` 收敛输入类 11 个组件复制粘贴的 ``set_size`` / ``size_name``
逻辑：尺寸档校验（中文 ``ValueError``）、动态属性 ``size``（映射
``uiksize``）设置与尺寸名查询；尺寸相关的附加动作（固定几何、图标
边长、文本边距等）由子类覆写 ``_apply_size`` 钩子实现。

``QWIDGETSIZE_MAX`` 集中于此，供需要「恢复默认最大尺寸」的控件使用，
替代魔法数 16777215。
"""

from ..theme import set_property

__all__ = []  # 私有模块：不导出任何符号

#: Qt 的控件尺寸上限哨兵值 QWIDGETSIZE_MAX（(1<<24)-1）。PySide6 未把
#: 该 C++ 宏导出到 Python，这里按 Qt 源码值定义同名常量以替代魔法数。
QWIDGETSIZE_MAX = 16777215


class SizeMixin:
    """尺寸档共享逻辑。

    约定:
        子类定义类属性 ``_SIZES``（合法尺寸档元组）与 ``_size_label``
        （中文组件名，用于报错文案，如 ``"按钮"`` → ``未知按钮尺寸``）。

    参数:
        size: ``_SIZES`` 中的尺寸档名，非法值抛中文 ``ValueError``。
    """

    _SIZES = ("sm", "md", "lg")
    _size_label = "控件"

    def set_size(self, size: str) -> None:
        """设置尺寸档（合法取值见子类 ``_SIZES``）。"""
        if size not in self._SIZES:
            raise ValueError(f"未知{self._size_label}尺寸: {size!r}")
        set_property(self, "size", size)
        self._apply_size(size)

    def _apply_size(self, size: str) -> None:
        """动态属性设置后的附加动作钩子（子类按需覆写）。"""

    def size_name(self) -> str:
        """当前尺寸档名。"""
        return self.property("uiksize") or "md"
