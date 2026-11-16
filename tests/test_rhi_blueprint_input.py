# -*- coding: utf-8 -*-
"""真实窗口回归：RHI 蓝图空白画布鼠标与 tooltip 的坐标映射。"""

import os
import sys
from pathlib import Path

if os.environ.get("QT_QPA_PLATFORM", "").lower() in ("offscreen", "minimal"):
    print("[跳过] RHI 蓝图原生输入回归仅在真实桌面运行")
    sys.exit(0)

os.environ["UIKIT_BLUEPRINT_BACKEND"] = "rhi"
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QPoint, Qt, QTimer, qInstallMessageHandler  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from InstructionX_UIKit.theme import ThemeManager  # noqa: E402
from demo.main_window import MainWindow  # noqa: E402


def main():
    warnings = []
    received = []

    def on_message(_mode, _context, message):
        print(f"[Qt] {message}", flush=True)
        if "QWidget::mapFrom" in message:
            warnings.append(message)

    qInstallMessageHandler(on_message)
    app = QApplication(sys.argv)
    ThemeManager.instance().apply(app)
    window = MainWindow()
    window.show()

    def probe():
        from InstructionX_UIKit.blueprint import BlueprintCanvas
        canvas = next(c for c in window.findChildren(BlueprintCanvas) if c.isVisible())
        viewport = canvas._viewport
        target = viewport._container
        point = QPoint(max(5, target.width() - 24), max(5, target.height() - 24))
        original = canvas.mousePressEvent

        def record(event):
            received.append(event.position())
            original(event)

        canvas.mousePressEvent = record
        QTest.mouseMove(target, point)
        QTest.mouseClick(target, Qt.LeftButton, Qt.NoModifier, point)
        QTest.qWait(150)
        expected = viewport.mapTo(canvas, point)
        if received and received[-1].toPoint() != expected:
            warnings.append(f"坐标错误: {received[-1].toPoint()} != {expected}")
        elif not received:
            warnings.append("空白画布未收到鼠标事件")
        print(f"[验收] mapFrom/坐标警告={len(warnings)} 事件数={len(received)}",
              flush=True)
        window.close()
        app.exit(1 if warnings else 0)

    QTimer.singleShot(500, lambda: window.navigate("blueprint"))
    QTimer.singleShot(4000, probe)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
