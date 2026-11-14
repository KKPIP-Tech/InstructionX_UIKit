# -*- coding: utf-8 -*-
"""Win32 原生指针输入预检；通过也不代表任何窗口操作已验收。"""

import ctypes
from ctypes import wintypes
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import platform
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tests" / "perf"))
os.environ.pop("QT_QPA_PLATFORM", None)

from native_input import cursor_pos, move_to


def main():
    source_sha = subprocess.check_output(
        ["git", "rev-parse", "uniform_style"], text=True, cwd=ROOT).strip()
    test_sha = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True, cwd=ROOT).strip()
    report = {
        "source_sha": source_sha, "test_sha": test_sha,
        "time_utc": datetime.now(timezone.utc).isoformat(),
        "platform": platform.platform(), "python": sys.version,
        "scope": "仅 Win32 原生指针输入预检，不是窗口操作验收",
        "native_mouse_verified": False, "pass": False,
    }
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.SetCursorPos.argtypes = [ctypes.c_int, ctypes.c_int]
    user32.SetCursorPos.restype = wintypes.BOOL
    before = cursor_pos()
    report["before"] = before
    direct_result = user32.SetCursorPos(*before)
    report["set_cursor_pos"] = {
        "result": bool(direct_result), "win32_error": ctypes.get_last_error(),
        "actual": cursor_pos(),
    }
    try:
        target = before[0] + 1, before[1]
        report["target"] = target
        actual = move_to(*target)
        report["send_input_actual"] = actual
        if actual != target:
            raise AssertionError(f"SendInput 未到达目标: {actual!r}")
        report["native_mouse_verified"] = True
        report["pass"] = True
    except Exception as exc:
        report["send_input_error"] = repr(exc)
    finally:
        try:
            report["restored"] = move_to(*before)
        except Exception as exc:
            report["restore_error"] = repr(exc)
            user32.SetCursorPos(*before)
        report["after"] = cursor_pos()
        if report["after"] != before:
            report["native_mouse_verified"] = False
            report["pass"] = False
    destination = ROOT / "temp" / "performance" / source_sha / "native-input"
    destination.mkdir(parents=True, exist_ok=True)
    path = destination / "preflight.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False), flush=True)
    print(f"原始报告：{path}", flush=True)
    return 0 if report["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
