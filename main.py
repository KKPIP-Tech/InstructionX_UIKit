#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""InstructionX_UIKit · Demo 演示应用入口。

用法::

    python main.py

流程：创建 QApplication → ThemeManager.instance().apply(app) 应用主题 →
显示 MainWindow（1280x800）。顶部条可随时切换亮 / 暗主题，无需重启。
"""

import sys
from pathlib import Path

# 直接 ``python main.py`` 运行时，脚本所在目录（仓库根）需加入导入路径，
# 以便能导入 InstructionX_UIKit 与 demo 包。
ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PySide6.QtWidgets import QApplication  # noqa: E402

from InstructionX_UIKit.theme import ThemeManager  # noqa: E402
from demo.main_window import MainWindow  # noqa: E402


def main() -> int:
    app = QApplication(sys.argv)
    ThemeManager.instance().apply(app)  # 生成并设置全局 QSS（默认亮色）
    window = MainWindow()
    window.resize(1280, 800)
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
