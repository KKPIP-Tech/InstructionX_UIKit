# -*- coding: utf-8 -*-
"""真实窗口回归：顺序点击聊天/图表/蓝图时顶层窗口不得销毁重建。"""

import os
import sys
from pathlib import Path

if sys.platform != "win32" or os.environ.get(
        "QT_QPA_PLATFORM", "").lower() in ("offscreen", "minimal"):
    print("[跳过] 原生窗口重建钩子仅在 Windows 真实桌面运行")
    sys.exit(0)

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = "--no-sandbox"

import ctypes  # noqa: E402
import ctypes.wintypes as wt  # noqa: E402
from PySide6.QtCore import Qt, QTimer, qInstallMessageHandler  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication, QScrollArea  # noqa: E402

from InstructionX_UIKit.theme import ThemeManager  # noqa: E402
from demo.main_window import MainWindow  # noqa: E402
from tests.perf.native_screen import grab_native_window  # noqa: E402


def main():
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    hook_proc = ctypes.CFUNCTYPE(ctypes.c_long, ctypes.c_int, wt.WPARAM, wt.LPARAM)
    user32.CallNextHookEx.restype = ctypes.c_long
    user32.CallNextHookEx.argtypes = [
        ctypes.c_void_p, ctypes.c_int, wt.WPARAM, wt.LPARAM]
    user32.SetWindowsHookExW.restype = ctypes.c_void_p
    user32.SetWindowsHookExW.argtypes = [
        ctypes.c_int, hook_proc, ctypes.c_void_p, wt.DWORD]
    user32.UnhookWindowsHookEx.argtypes = [ctypes.c_void_p]
    main_destroyed = []
    warnings = []
    phase = "startup"

    def title(hwnd):
        buffer = ctypes.create_unicode_buffer(512)
        user32.GetWindowTextW(hwnd, buffer, 512)
        return buffer.value

    hook = None

    def callback(code, wparam, lparam):
        if code == 4 and "InstructionX_UIKit" in title(wparam):
            main_destroyed.append(phase)
            print(f"[主窗口销毁][{phase}]", flush=True)
        return user32.CallNextHookEx(hook, code, wparam, lparam)

    callback_ref = hook_proc(callback)

    def on_message(_mode, _context, message):
        if "QWidget::mapFrom" in message:
            warnings.append(message)
            print(f"[Qt][{phase}] {message}", flush=True)

    qInstallMessageHandler(on_message)
    app = QApplication(sys.argv)
    ThemeManager.instance().apply(app)
    window = MainWindow()
    window.show()
    hook = user32.SetWindowsHookExW(
        5, callback_ref, None, kernel32.GetCurrentThreadId())
    if not hook:
        window.close()
        return 1

    keys = ["chat_conversation", "tokens", "chat_conversation", "charts", "tokens",
            "charts", "blueprint", "tokens", "blueprint"]
    state = {"index": 0}

    def advance():
        nonlocal phase
        if state["index"] >= len(keys):
            failed = bool(main_destroyed or warnings)
            print(f"[验收] 主窗口销毁={len(main_destroyed)} "
                  f"mapFrom={len(warnings)}", flush=True)
            grab_native_window(window).save(str(
                ROOT / "tests" / "shots" / "page_switch_real.png"))
            user32.UnhookWindowsHookEx(hook)
            window.close()
            app.exit(1 if failed else 0)
            return
        key = keys[state["index"]]
        state["index"] += 1
        phase = key
        item = window._sidebar._items[key]
        window._sidebar.findChild(QScrollArea).ensureWidgetVisible(item)
        app.processEvents()
        QTest.mouseClick(item, Qt.LeftButton)
        print(f"[顺序导航] {state['index']}/{len(keys)} {key} "
              f"current={window._current}", flush=True)
        if window._current != key:
            warnings.append(f"导航失败: {key}")
        QTimer.singleShot(1800, advance)

    QTimer.singleShot(500, advance)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
