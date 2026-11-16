# -*- coding: utf-8 -*-
"""真实窗口回归：Demo 的 Mermaid 官方 WebEngine 主路径与懒加载查看器。

离屏全量测试中自动跳过；实机通过交互测试启动器运行本脚本。
"""

import os
import sys
import time
from pathlib import Path

if os.environ.get("QT_QPA_PLATFORM", "").lower() in ("offscreen", "minimal"):
    print("[跳过] 官方 WebEngine 原生窗口回归仅在真实桌面运行")
    sys.exit(0)

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import runpy  # noqa: E402
from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication, QMainWindow  # noqa: E402
from demo.main_window import MainWindow  # noqa: E402

window = None
success = False
finished = False
deadline = 0.0


def show_and_test(self):
    global window, deadline
    original_show(self)
    if not isinstance(self, MainWindow):
        return
    window = self
    deadline = time.monotonic() + 100
    QTimer.singleShot(500, lambda: self.navigate("markdown_view"))
    QTimer.singleShot(1000, poll)
    QTimer.singleShot(100000, lambda: finish("等待 Mermaid 就绪超时"))


def poll():
    if finished:
        return
    from InstructionX_UIKit.mermaid import MermaidRenderHub, MermaidView
    hub = MermaidRenderHub.instance()
    if hub._web_failed:
        finish("MermaidRenderHub 已降级为受限自绘后端")
        return
    views = window.findChildren(MermaidView)
    if any(v._web is None and v._canvas is not None for v in views):
        finish("MermaidView 已降级")
        return
    if (hub._web_ready and views and not hub._pending
            and all(v._web_ready and v._natural.isValid() for v in views)
            and all(v._poll_timer is None or not v._poll_timer.isActive()
                    for v in views)):
        finish("")
    else:
        QTimer.singleShot(250, poll)


def finish(error):
    global success, finished
    if finished:
        return
    finished = True
    from InstructionX_UIKit.mermaid import MermaidRenderHub
    hub = MermaidRenderHub.instance()
    success = not error and hub._web_ready
    print(f"[验收] 成功={success} 错误={error!r} hub_ready={hub._web_ready} "
          f"hub_failed={hub._web_failed}", flush=True)
    if success:
        page = window._page_cache["markdown_view"]
        page.verticalScrollBar().setValue(page.verticalScrollBar().maximum())
        QTimer.singleShot(250, capture)
        return
    close()


def capture():
    global success
    from InstructionX_UIKit.components import MarkdownView
    from InstructionX_UIKit.mermaid import MermaidRenderHub, MermaidView
    hub = MermaidRenderHub.instance()
    views = window.findChildren(MermaidView)
    if hub._web_failed or any(v._web is None for v in views):
        success = False
        print("[失败] 滚动后 Mermaid 发生降级", flush=True)
        close()
        return
    if time.monotonic() >= deadline:
        success = False
        print("[失败] 滚动后新增查看器未在期限内就绪", flush=True)
        close()
        return
    if (hub._pending or not views or any(
            not v._web_ready or not v._natural.isValid()
            or (v._poll_timer is not None and v._poll_timer.isActive())
            for v in views)):
        QTimer.singleShot(250, capture)
        return
    keys = [key for document in window.findChildren(MarkdownView)
            for key in document._diagram_keys]
    missing = [(key, hub.last_error(key)) for key in keys if hub.get(key) is None]
    if len(keys) < 6 or missing:
        success = False
        print(f"[失败] 图表缓存不完整 keys={len(keys)} missing={missing}", flush=True)
        close()
        return
    print(f"[验收] 查看器={len(views)}，缓存图表={len(keys)}", flush=True)
    from tests.perf.native_screen import grab_native_window
    target = ROOT / "tests" / "shots" / "mermaid_webengine_real.png"
    target.parent.mkdir(parents=True, exist_ok=True)
    if not grab_native_window(window).save(str(target)):
        raise RuntimeError("真实 Mermaid 截图保存失败")
    print(f"[验收] 截图={target}", flush=True)
    close()


def close():
    window.close()
    QApplication.instance().quit()


original_show = QMainWindow.show
QMainWindow.show = show_and_test
try:
    runpy.run_path(str(ROOT / "main.py"), run_name="__main__")
except SystemExit as exc:
    if exc.code:
        raise
if not success:
    sys.exit(1)
print("[通过] Mermaid 官方后端、六张图与懒加载查看器均正常")
