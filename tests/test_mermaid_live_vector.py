# -*- coding: utf-8 -*-
"""真实窗口回归：文档 Mermaid 实时 SVG 的拖动、缩放与底层透明互斥。"""

import os
import sys
from pathlib import Path

if os.environ.get("QT_QPA_PLATFORM", "").lower() in ("offscreen", "minimal"):
    print("[跳过] 实时 SVG 原生交互回归仅在真实桌面运行")
    sys.exit(0)

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import runpy  # noqa: E402
from PySide6.QtCore import QPoint, Qt, QTimer  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication, QMainWindow  # noqa: E402
from demo.main_window import MainWindow  # noqa: E402
from tests.perf.native_input import activate_window  # noqa: E402
from tests.perf.native_screen import grab_native_window  # noqa: E402

window = None
success = False
finished = False


def show_and_test(self):
    global window
    original_show(self)
    if not isinstance(self, MainWindow):
        return
    window = self
    QTimer.singleShot(500, lambda: self.navigate("markdown_view"))
    QTimer.singleShot(1000, poll)
    QTimer.singleShot(100000, lambda: finish("等待实时 Mermaid 超时"))


def poll():
    if finished:
        return
    from InstructionX_UIKit.mermaid import MermaidRenderHub, MermaidView
    hub = MermaidRenderHub.instance()
    views = window.findChildren(MermaidView)
    if views and all(v._canvas is not None for v in views):
        finish("文档 Mermaid 退化为预渲染栅格画布")
        return
    if hub._web_failed:
        finish("官方 Mermaid Hub 降级")
        return
    if (hub._web_ready and len(views) >= 5 and not hub._pending
            and all(v._web_ready and v._natural.isValid() for v in views)):
        page = window._page_cache["markdown_view"]
        view = next(v for v in views if v.code().lstrip().startswith("stateDiagram-v2"))
        page.ensureWidgetVisible(view, 40, 40)
        QTimer.singleShot(500, lambda: interact(view))
        return
    QTimer.singleShot(250, poll)


def interact(view):
    view._web.page().runJavaScript(
        "document.getElementById('wrapper').style.transform",
        lambda value: begin_drag(view, value))


def begin_drag(view, before):
    point = QPoint(max(30, view._web.width() // 2),
                   max(30, view._web.height() // 2))
    QTest.mouseMove(view._web, point)
    QTest.mousePress(view._web, Qt.LeftButton, Qt.NoModifier, point)
    QTest.mouseMove(view._web, point + QPoint(36, 24))
    QTest.mouseRelease(view._web, Qt.LeftButton, Qt.NoModifier, point + QPoint(36, 24))
    view._web.page().runJavaScript("window.__uikViewer.zoomIn()")
    QTimer.singleShot(400, lambda: check_interaction(view, before))


def check_interaction(view, before):
    import json
    view._web.page().runJavaScript(
        "JSON.stringify({svg:!!document.querySelector('#wrapper svg'),"
        " transform:document.getElementById('wrapper').style.transform})",
        lambda value: finish("", view, before,
                             json.loads(value) if isinstance(value, str) and value else {}))


def finish(error, view=None, before=None, state=None):
    global success, finished
    if finished:
        return
    finished = True
    live_key = False
    if view is not None:
        from InstructionX_UIKit.components import MarkdownView
        for document in window.findChildren(MarkdownView):
            for key, candidate in document._diagram_overlays.items():
                if candidate is view:
                    live_key = key in document._diagram_live
    success = (not error and isinstance(state, dict) and state.get("svg")
               and state.get("transform") != before and live_key)
    print(f"[验收] 成功={success} 错误={error!r} SVG状态={state} "
          f"前={before!r} 底层透明={live_key}", flush=True)
    if success:
        if not activate_window(window):
            success = False
        else:
            QTest.qWait(400)
            target = ROOT / "tests" / "shots" / "mermaid_live_vector.png"
            if not grab_native_window(window).save(str(target)):
                success = False
    window.close()
    QApplication.instance().quit()


original_show = QMainWindow.show
QMainWindow.show = show_and_test
try:
    runpy.run_path(str(ROOT / "main.py"), run_name="__main__")
except SystemExit as exc:
    if exc.code:
        raise
sys.exit(0 if success else 1)
