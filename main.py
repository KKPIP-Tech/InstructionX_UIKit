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
from PySide6.QtQuick import QQuickWindow, QSGRendererInterface  # noqa: E402

from InstructionX_UIKit.theme import ThemeManager  # noqa: E402
from demo.main_window import MainWindow  # noqa: E402


def main() -> int:
    # 统一图形 API 为 OpenGL：蓝图页 QOpenGLWidget 会把顶层窗口的合成
    # 锁定为 OpenGL，而 Qt6 的 QWebEngineView（Mermaid 交互查看器）内部
    # 基于 Qt Quick RHI，Windows 上默认 Direct3D11——两者不一致会导致
    # "QQuickWidget: Failed to get a QRhi" 报错刷屏与窗口闪烁。
    # 必须在 QApplication 创建前调用。
    QQuickWindow.setGraphicsApi(QSGRendererInterface.GraphicsApi.OpenGL)
    app = QApplication(sys.argv)
    ThemeManager.instance().apply(app)  # 生成并设置全局 QSS（默认亮色）
    # MainWindow 构造时已 resize 1280x800，此处不再重复设置
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
