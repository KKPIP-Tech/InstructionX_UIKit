# -*- coding: utf-8 -*-
"""ScrollStoryArea 异步截图与销毁生命周期回归。"""

import os
import sys
import time
import traceback
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QEvent
from PySide6.QtWidgets import QApplication
from shiboken6 import isValid

from InstructionX_UIKit.anim import ScrollStoryArea
from InstructionX_UIKit.theme import ThemeManager

app = QApplication.instance() or QApplication(sys.argv)
ThemeManager.instance().apply(app)
_FAILURES = []


def pump(ms):
    deadline = time.monotonic() + ms / 1000
    while time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.002)


def case(name):
    def decorate(function):
        try:
            function()
            print(f"  [通过] {name}")
        except Exception:
            _FAILURES.append(name)
            print(f"  [失败] {name}")
            traceback.print_exc()
        return function
    return decorate


@case("截图回调待执行时销毁整个区域")
def _():
    area = ScrollStoryArea()
    panel = area.addStep("销毁步骤", "销毁后不得再访问步骤控件。")
    area.resize(360, 220)
    area.show()
    if not panel._capture_pending:
        raise AssertionError("测试未建立待执行的截图回调")
    area.deleteLater()
    app.sendPostedEvents(None, QEvent.DeferredDelete)
    if isValid(area) or isValid(panel):
        raise AssertionError("测试未实际销毁区域与步骤")
    app.processEvents()


@case("重复销毁不留下异步回调")
def _():
    for _index in range(12):
        area = ScrollStoryArea()
        area.addStep("第一步", "测试控件反复创建与销毁。")
        area.addStep("第二步", "每次创建都应调度一次区域更新。")
        area.resize(360, 220)
        area.show()
        area.deleteLater()
        app.sendPostedEvents(None, QEvent.DeferredDelete)
        app.processEvents()


if __name__ == "__main__":
    raise SystemExit(1 if _FAILURES else 0)
