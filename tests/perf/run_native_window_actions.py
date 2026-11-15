# -*- coding: utf-8 -*-
"""Win32 原生双击最大化与还原；几何、状态和呈现信号分别记录。"""

import argparse
import ctypes
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests" / "perf"))
os.environ.pop("QT_QPA_PLATFORM", None)

from PySide6.QtCore import QPoint
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from demo.window_host import WindowHost
from InstructionX_UIKit.theme import ThemeManager
from native_input import activate_window, client_to_physical, cursor_pos, left_button, move_to


def double_click(host):
    app = QApplication.instance()
    target = client_to_physical(host._titlebar, QPoint(50, 24))
    move_to(*target)
    QTest.qWait(20)
    finished = threading.Event()
    errors = []

    def inject():
        try:
            for _ in range(2):
                left_button(True)
                time.sleep(0.035)
                left_button(False)
                time.sleep(0.035)
        except Exception as exc:
            errors.append(repr(exc))
        finally:
            left_button(False)
            finished.set()

    worker = threading.Thread(target=inject, name="native-double-click")
    worker.start()
    deadline = time.monotonic() + 10
    while not finished.wait(0.004):
        app.processEvents()
        if time.monotonic() > deadline:
            raise TimeoutError("原生双击未在 10 秒内结束")
    worker.join()
    QTest.qWait(250)
    if errors:
        raise RuntimeError(errors)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--seconds", type=float, default=30)
    parser.add_argument("--rounds", type=int, default=5)
    parser.add_argument("--tag", default="native-maximize")
    args = parser.parse_args()
    app = QApplication.instance() or QApplication(sys.argv)
    ThemeManager.instance().apply(app)
    host = WindowHost()
    host.resize(900, 600)
    host.move(180, 100)
    host.show()
    if not activate_window(host):
        raise RuntimeError("原生窗口动作宿主未取得前台")
    QTest.qWait(600)
    origin = host.geometry()
    original_cursor = cursor_pos()
    frames = []
    frame_signal = getattr(host.windowHandle(), "frameSwapped", None)
    if frame_signal is not None:
        frame_signal.connect(lambda: frames.append(time.perf_counter()))
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.IsZoomed.argtypes = [ctypes.c_void_p]
    user32.IsZoomed.restype = ctypes.c_bool
    results = []
    try:
        for round_index in range(args.rounds):
            started = time.monotonic()
            frame_start = len(frames)
            actions = []
            failures = []
            while time.monotonic() - started < args.seconds and not failures:
                double_click(host)
                maximized = bool(user32.IsZoomed(int(host.winId())))
                action = {"operation": "maximize", "qt_maximized": host.isMaximized(),
                          "win32_zoomed": maximized, "geometry": list(host.geometry().getRect())}
                actions.append(action)
                if not maximized or not host.isMaximized():
                    failures.append("原生双击未最大化窗口")
                    break
                double_click(host)
                restored = not user32.IsZoomed(int(host.winId()))
                action = {"operation": "restore", "qt_maximized": host.isMaximized(),
                          "win32_zoomed": not restored,
                          "geometry": list(host.geometry().getRect())}
                actions.append(action)
                if not restored or host.isMaximized():
                    failures.append("原生双击未还原窗口")
                if any(abs(a - b) > 2 for a, b in zip(host.geometry().getRect(), origin.getRect())):
                    failures.append("还原后几何不一致")
                if host.gesture._manual is not None:
                    failures.append("双击后手动手势未清理")
            result = {"round": round_index + 1, "seconds": time.monotonic() - started,
                      "actions": actions, "frames": frames[frame_start:],
                      "failures": failures, "pass": not failures}
            results.append(result)
            print(f"round={round_index + 1} actions={len(actions)} frames={len(result['frames'])} "
                  f"failures={failures}", flush=True)
            if failures:
                break
    finally:
        left_button(False)
        try:
            move_to(*original_cursor)
        finally:
            host.close()
            app.processEvents()
    source_sha = subprocess.check_output(["git", "rev-parse", "uniform_style"],
                                         cwd=ROOT, text=True).strip()
    report = {"source_sha": source_sha,
              "test_sha": subprocess.check_output(["git", "rev-parse", "HEAD"],
                                                   cwd=ROOT, text=True).strip(),
              "time_utc": datetime.now(timezone.utc).isoformat(),
              "seconds": args.seconds, "rounds": args.rounds,
              "input_mode": "Win32 SendInput 双击",
              "presentation_signal_supported": len(frames) > 1,
              "performance_gate_pass": False,
              "cases": results}
    report["pass"] = bool(results) and all(item["pass"] for item in results)
    report["duration_gate_pass"] = bool(
        report["pass"] and args.seconds >= 30 and args.rounds >= 5)
    destination = ROOT / "temp" / "performance" / source_sha / args.tag
    destination.mkdir(parents=True, exist_ok=True)
    path = destination / "report.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"pass": report["pass"],
                      "presentation_signal_supported": report["presentation_signal_supported"],
                      "report": str(path)}, ensure_ascii=False), flush=True)
    return 0 if report["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
