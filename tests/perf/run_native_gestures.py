# -*- coding: utf-8 -*-
"""使用 Win32 原生鼠标验证系统窗口手势与手动回退。"""

import argparse
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

from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from demo.window_host import WindowHost
from InstructionX_UIKit.theme import ThemeManager
from native_input import client_to_physical, cursor_pos, left_button, move_to


GESTURES = ("move", "left", "right", "top", "bottom",
            "top-left", "top-right", "bottom-left", "bottom-right")


def pump(milliseconds):
    QTest.qWait(milliseconds)


def point_for(host, gesture):
    rect = host._titlebar.rect()
    points = {
        "move": QPoint(50, 24),
        "left": QPoint(2, 24), "right": QPoint(rect.width() - 2, 24),
        "top": QPoint(50, 2), "bottom": QPoint(50, rect.height() - 2),
        "top-left": QPoint(2, 2), "top-right": QPoint(rect.width() - 2, 2),
        "bottom-left": QPoint(2, rect.height() - 2),
        "bottom-right": QPoint(rect.width() - 2, rect.height() - 2),
    }
    return points[gesture]


def drag(host, point, delta, records):
    app = QApplication.instance()
    start = client_to_physical(host._titlebar, point)
    target = client_to_physical(host._titlebar, point + delta)
    before = host.geometry()
    move_to(*start)
    pump(20)
    finished = threading.Event()
    errors = []

    def inject():
        try:
            left_button(True)
            time.sleep(0.05)
            for index in range(1, 7):
                position = (round(start[0] + (target[0] - start[0]) * index / 6),
                            round(start[1] + (target[1] - start[1]) * index / 6))
                move_to(*position)
                time.sleep(0.012)
        except Exception as exc:
            errors.append(repr(exc))
        finally:
            left_button(False)
            finished.set()

    worker = threading.Thread(target=inject, name=f"native-{host.winId()}")
    worker.start()
    manual = False
    deadline = time.monotonic() + 10
    while not finished.wait(0.004):
        app.processEvents()
        manual = manual or host.gesture._manual is not None
        if time.monotonic() > deadline:
            raise TimeoutError("原生窗口拖动未在 10 秒内结束")
    worker.join()
    pump(80)
    if errors:
        raise RuntimeError(errors)
    after = host.geometry()
    records.append({"before": list(before.getRect()), "after": list(after.getRect()),
                    "manual_during_drag": manual,
                    "manual_after_release": host.gesture._manual is not None,
                    "start": start, "target": target, "cursor": cursor_pos()})
    return before, after


def run_case(app, gesture, mode, seconds, rounds):
    if gesture not in GESTURES:
        raise ValueError(f"未知手势: {gesture}")
    if mode not in ("system", "manual"):
        raise ValueError(f"未知模式: {mode}")
    host = WindowHost()
    if mode == "manual":
        host.gesture._system_move = lambda _handle: False
        host.gesture._system_resize = lambda _handle, _edges: False
    host.resize(900, 600)
    host.move(180, 100)
    host.show()
    host.raise_()
    host.activateWindow()
    pump(600)
    original_cursor = cursor_pos()
    results = []
    try:
        for round_index in range(rounds):
            started = time.monotonic()
            records = []
            failures = []
            origin = host.geometry()
            while time.monotonic() - started < seconds and not failures:
                delta = QPoint(80, 45) if gesture == "move" else QPoint(60, 40)
                if gesture in ("left", "top-left", "bottom-left"):
                    delta.setX(-delta.x())
                if gesture in ("top", "top-left", "top-right"):
                    delta.setY(-delta.y())
                before, after = drag(host, point_for(host, gesture), delta, records)
                if gesture == "move":
                    changed = after.topLeft() != before.topLeft()
                else:
                    changed = after.size() != before.size()
                if not changed:
                    failures.append("原生拖动未改变窗口几何")
                if records[-1]["manual_after_release"]:
                    failures.append("释放后手动手势未结束")
                if mode == "manual" and not records[-1]["manual_during_drag"]:
                    failures.append("强制回退未进入手动路径")
                if mode == "system" and records[-1]["manual_during_drag"]:
                    failures.append("系统手势意外进入手动路径")
                _before, restored = drag(host, point_for(host, gesture), -delta, records)
                if abs(restored.x() - origin.x()) > 2 or abs(restored.y() - origin.y()) > 2 \
                        or abs(restored.width() - origin.width()) > 2 \
                        or abs(restored.height() - origin.height()) > 2:
                    failures.append(f"反向拖动未恢复原几何: {restored} != {origin}")
                origin = host.geometry()
            results.append({"round": round_index + 1, "seconds": time.monotonic() - started,
                            "gesture": gesture, "mode": mode, "drags": records,
                            "failures": failures, "pass": not failures})
            print(gesture, mode, results[-1]["round"],
                  "PASS" if results[-1]["pass"] else "FAIL",
                  f"drags={len(records)}", failures, flush=True)
            if failures:
                break
    finally:
        left_button(False)
        try:
            move_to(*original_cursor)
        finally:
            host.close()
            app.processEvents()
    return results


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--seconds", type=float, default=30)
    parser.add_argument("--rounds", type=int, default=5)
    parser.add_argument("--gestures", nargs="+", default=["move", "bottom-right"])
    parser.add_argument("--modes", nargs="+", default=["system", "manual"])
    parser.add_argument("--tag", default="native-gestures")
    args = parser.parse_args()
    app = QApplication.instance() or QApplication(sys.argv)
    ThemeManager.instance().apply(app)
    source_sha = subprocess.check_output(
        ["git", "rev-parse", "uniform_style"], cwd=ROOT, text=True).strip()
    report = {"source_sha": source_sha,
              "test_sha": subprocess.check_output(["git", "rev-parse", "HEAD"],
                                                   cwd=ROOT, text=True).strip(),
              "source_dirty": subprocess.run(
                  ["git", "diff", "--quiet", source_sha, "--", "InstructionX_UIKit", "demo"],
                  cwd=ROOT).returncode != 0,
              "time_utc": datetime.now(timezone.utc).isoformat(),
              "seconds": args.seconds, "rounds": args.rounds,
              "input_mode": "Win32 SendInput", "cases": {},
              "scope": "WindowHost 标题栏四边、四角与移动；不是客户区边框或性能验收",
              "performance_gate_pass": False}
    for gesture in args.gestures:
        for mode in args.modes:
            try:
                report["cases"][f"{gesture}:{mode}"] = run_case(
                    app, gesture, mode, args.seconds, args.rounds)
            except Exception as exc:
                report["cases"][f"{gesture}:{mode}"] = [{
                    "round": 1, "seconds": 0, "drags": [],
                    "failures": [repr(exc)], "pass": False}]
    report["pass"] = bool(report["cases"]) and all(
        case and all(item["pass"] for item in case) for case in report["cases"].values())
    report["duration_gate_pass"] = bool(
        report["pass"] and args.seconds >= 30 and args.rounds >= 5)
    destination = ROOT / "temp" / "performance" / source_sha / args.tag
    destination.mkdir(parents=True, exist_ok=True)
    path = destination / "report.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"pass": report["pass"], "report": str(path)}, ensure_ascii=False), flush=True)
    return 0 if report["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
