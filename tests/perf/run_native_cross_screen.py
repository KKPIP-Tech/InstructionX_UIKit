# -*- coding: utf-8 -*-
"""混合 DPI 显示器的原生跨屏拖动与几何恢复验收。"""

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests" / "perf"))
os.environ.pop("QT_QPA_PLATFORM", None)

from PySide6.QtCore import QPoint
from PySide6.QtWidgets import QApplication
from demo.window_host import WindowHost
from InstructionX_UIKit.theme import ThemeManager
from native_input import activate_window, cursor_pos, global_to_physical, left_button, move_to
from run_native_gestures import drag, point_for, pump


def close_enough(actual, expected, tolerance=2):
    return abs(actual.x() - expected.x()) <= tolerance \
        and abs(actual.y() - expected.y()) <= tolerance


def run_case(app, primary, other, mode, seconds, rounds):
    host = WindowHost()
    if mode == "manual":
        host.gesture._system_move = lambda _handle: False
        host.gesture._system_resize = lambda _handle, _edges: False
    host.resize(900, 600)
    host.move(180, 100)
    host.show()
    if not activate_window(host):
        raise RuntimeError("跨屏测试宿主未取得前台")
    pump(600)
    origin = host.geometry()
    original_cursor = cursor_pos()
    point = point_for(host, "move")
    offset = host._titlebar.mapTo(host, point)
    target_origin = other.geometry().topLeft() + QPoint(100, 120)
    results = []
    try:
        for round_index in range(rounds):
            started = time.monotonic()
            records = []
            failures = []
            while time.monotonic() - started < seconds and not failures:
                target_point = target_origin + offset
                drag(host, point, QPoint(), records,
                     target_physical=global_to_physical(other, target_point))
                actual_screen = host.screen()
                record = {"direction": "to_other",
                          "expected_origin": [target_origin.x(), target_origin.y()],
                          "actual_geometry": list(host.geometry().getRect()),
                          "screen": actual_screen.name(), "dpr": host.devicePixelRatioF(),
                          "manual": records[-1]["manual_during_drag"]}
                records[-1].update(record)
                if actual_screen is not other:
                    failures.append(f"窗口未进入目标屏幕: {actual_screen.name()} != {other.name()}")
                if not close_enough(host.geometry().topLeft(), target_origin):
                    failures.append(f"跨屏几何偏移: {host.geometry().topLeft()} != {target_origin}")
                if abs(host.devicePixelRatioF() - other.devicePixelRatio()) > 0.001:
                    failures.append("跨屏后 DPR 未更新")
                if mode == "manual" and not records[-1]["manual_during_drag"]:
                    failures.append("强制回退未进入手动路径")
                if mode == "system" and records[-1]["manual_during_drag"]:
                    failures.append("系统跨屏意外进入手动路径")
                return_point = origin.topLeft() + offset
                drag(host, point, QPoint(), records,
                     target_physical=global_to_physical(primary, return_point))
                records[-1].update({"direction": "to_primary",
                                    "actual_geometry": list(host.geometry().getRect()),
                                    "screen": host.screen().name(),
                                    "dpr": host.devicePixelRatioF()})
                if host.screen() is not primary:
                    failures.append("窗口未返回主屏幕")
                if not close_enough(host.geometry().topLeft(), origin.topLeft()):
                    failures.append(f"返回几何偏移: {host.geometry().topLeft()} != {origin.topLeft()}")
            results.append({"round": round_index + 1, "seconds": time.monotonic() - started,
                            "drags": records, "failures": failures, "pass": not failures})
            print(mode, round_index + 1, "PASS" if not failures else "FAIL",
                  f"crossings={len(records)}", failures, flush=True)
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
    parser.add_argument("--modes", nargs="+", default=["system", "manual"])
    parser.add_argument("--tag", default="native-cross-screen")
    args = parser.parse_args()
    app = QApplication.instance() or QApplication(sys.argv)
    ThemeManager.instance().apply(app)
    primary = app.primaryScreen()
    others = [screen for screen in app.screens() if screen is not primary]
    if not others:
        raise RuntimeError("跨屏验收需要至少两台显示器")
    other = others[0]
    report = {"seconds": args.seconds, "rounds": args.rounds,
              "input_mode": "Win32 SendInput 跨屏标题栏拖动",
              "screens": [{"name": screen.name(), "geometry": list(screen.geometry().getRect()),
                           "dpr": screen.devicePixelRatio()}
                          for screen in app.screens()],
              "performance_gate_pass": False, "cases": {}}
    for mode in args.modes:
        try:
            report["cases"][mode] = run_case(app, primary, other, mode,
                                             args.seconds, args.rounds)
        except Exception as exc:
            report["cases"][mode] = [{"round": 1, "seconds": 0, "drags": [],
                                      "failures": [repr(exc)], "pass": False}]
    report["pass"] = bool(report["cases"]) and all(
        case and all(item["pass"] for item in case) for case in report["cases"].values())
    report["duration_gate_pass"] = bool(
        report["pass"] and args.seconds >= 30 and args.rounds >= 5)
    source_sha = subprocess.check_output(["git", "rev-parse", "uniform_style"],
                                         cwd=ROOT, text=True).strip()
    report["source_sha"] = source_sha
    report["source_dirty"] = subprocess.run(
        ["git", "diff", "--quiet", source_sha, "--", "InstructionX_UIKit", "demo"],
        cwd=ROOT).returncode != 0
    report["test_sha"] = subprocess.check_output(["git", "rev-parse", "HEAD"],
                                                  cwd=ROOT, text=True).strip()
    report["time_utc"] = datetime.now(timezone.utc).isoformat()
    destination = ROOT / "temp" / "performance" / source_sha / args.tag
    destination.mkdir(parents=True, exist_ok=True)
    path = destination / "report.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"pass": report["pass"], "report": str(path)}, ensure_ascii=False), flush=True)
    return 0 if report["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
