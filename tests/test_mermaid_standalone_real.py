# -*- coding: utf-8 -*-
"""真实窗口回归：独立 MermaidView 保持官方 WebEngine 交互后端。"""

import os
import sys
from pathlib import Path

if os.environ.get("QT_QPA_PLATFORM", "").lower() in ("offscreen", "minimal"):
    print("[跳过] 独立 MermaidView 原生 WebEngine 回归仅在真实桌面运行")
    sys.exit(0)

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

flags = os.environ.get("QTWEBENGINE_CHROMIUM_FLAGS", "")
if "--no-sandbox" not in flags.split():
    os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = f"{flags} --no-sandbox".strip()

from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402
from InstructionX_UIKit.theme import ThemeManager  # noqa: E402
from InstructionX_UIKit.mermaid import MermaidView  # noqa: E402
from tests.perf.native_input import activate_window  # noqa: E402
from tests.perf.native_screen import grab_native_window  # noqa: E402


def main():
    app = QApplication(sys.argv)
    ThemeManager.instance().apply(app)
    view = MermaidView("flowchart LR\n    A[独立组件] --> B[WebEngine 交互]")
    view.resize(720, 360)
    view.show()
    state = {"done": False, "ok": False}

    def poll():
        if view._web_failed if hasattr(view, "_web_failed") else False:
            finish()
            return
        if view._web_ready and view._natural.isValid():
            state["ok"] = view.web_active
            finish()
            return
        QTimer.singleShot(250, poll)

    def finish():
        if state["done"]:
            return
        state["done"] = True
        print(f"[验收] web_active={view.web_active} natural={view.natural_size()}",
              flush=True)
        if state["ok"]:
            from PySide6.QtTest import QTest
            activate_window(view)
            QTest.qWait(500)
            grab_native_window(view).save(str(
                ROOT / "tests" / "shots" / "mermaid_standalone_real.png"))
        view.close()
        app.quit()

    QTimer.singleShot(250, poll)
    QTimer.singleShot(60000, finish)
    app.exec()
    return 0 if state["done"] and state["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
