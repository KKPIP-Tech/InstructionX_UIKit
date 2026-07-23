# -*- coding: utf-8 -*-
"""InstructionX_UIKit：纯组件 / 布局 / 动画 / 图表 UI 库。

本包为独立 UIKit，**不含任何演示数据与 Demo 逻辑**：所有内容由调用方
通过 API 传入。演示程序见仓库根目录的 ``demo/`` 包（``python main.py``
启动）。

快速上手::

    import sys
    from PySide6.QtWidgets import QApplication
    from InstructionX_UIKit.theme import ThemeManager
    from InstructionX_UIKit.components import Button

    app = QApplication(sys.argv)
    ThemeManager.instance().apply(app)   # 应用全局主题（默认亮色）
    btn = Button("确定", variant="primary")
    btn.show()
    app.exec()
"""

from .theme import ThemeManager, T, apply_shadow, build_qss, set_property
from .tokens import (
    LIGHT,
    DARK,
    FONT_FAMILY,
    MONO_FAMILY,
    Breakpoint,
    DURATION,
    EASING,
    TokenState,
)
from .icons import get_icon, ICON_NAMES

__version__ = "alpha-v1.0.0"

__all__ = [
    "__version__",
    # theme
    "ThemeManager",
    "T",
    "build_qss",
    "apply_shadow",
    "set_property",
    # tokens
    "LIGHT",
    "DARK",
    "FONT_FAMILY",
    "MONO_FAMILY",
    "Breakpoint",
    "DURATION",
    "EASING",
    "TokenState",
    # icons
    "get_icon",
    "ICON_NAMES",
]
