# -*- coding: utf-8 -*-
"""真实窗口回归：首次进入 Chart / Blueprint 不得触发空视口离屏回读。

离屏全量测试中自动跳过；实机通过交互测试启动器运行本脚本。
"""

import os
import sys
from pathlib import Path

if os.environ.get("QT_QPA_PLATFORM", "").lower() in ("offscreen", "minimal"):
    print("[跳过] 空 Scene Graph 回读仅存在于真实窗口 RHI 路径")
    sys.exit(0)

os.environ["UIKIT_CHART_BACKEND"] = "rhi"
os.environ["UIKIT_BLUEPRINT_BACKEND"] = "rhi"

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QTimer, qInstallMessageHandler  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from InstructionX_UIKit.theme import ThemeManager  # noqa: E402
from demo.main_window import MainWindow  # noqa: E402

warnings = []
finished = False


def on_qt_message(_mode, _context, message):
    print(f"[Qt] {message}", flush=True)
    if "Failed to create depth/stencil buffer for offscreen readback" in message:
        warnings.append(message)


def finish(window, app):
    global finished
    if finished:
        return
    finished = True
    print(f"[验收] depth/stencil 警告数={len(warnings)}", flush=True)
    window.close()
    app.quit()


def main():
    app = QApplication(sys.argv)
    ThemeManager.instance().apply(app)
    qInstallMessageHandler(on_qt_message)
    window = MainWindow()
    window.show()
    QTimer.singleShot(500, lambda: window.navigate("charts"))
    QTimer.singleShot(3000, lambda: window.navigate("blueprint"))
    QTimer.singleShot(5500, lambda: finish(window, app))
    QTimer.singleShot(20000, lambda: finish(window, app))
    app.exec()
    if not finished or warnings:
        print("[失败] 首次导航出现空视口回读或窗口未正常退出")
        return 1
    print("[通过] Chart / Blueprint 首次导航无空视口回读")
    return 0


if __name__ == "__main__":
    sys.exit(main())
