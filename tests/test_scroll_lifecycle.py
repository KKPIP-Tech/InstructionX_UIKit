# -*- coding: utf-8 -*-
"""滚动容器延迟扫描与销毁生命周期回归。"""

import os
import sys
import traceback
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLabel, QVBoxLayout, QWidget
from shiboken6 import isValid

from InstructionX_UIKit.anim import HorizontalScrollStrip, ScrollReveal
from InstructionX_UIKit.theme import ThemeManager

app = QApplication.instance() or QApplication(sys.argv)
ThemeManager.instance().apply(app)
_FAILURES = []


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


@case("ScrollReveal 隐藏重试后销毁不执行扫描")
def _():
    for _index in range(8):
        content = QWidget()
        layout = QVBoxLayout(content)
        for row in range(4):
            layout.addWidget(QLabel(f"第 {row} 块"))
        reveal = ScrollReveal(content)
        app.processEvents()
        reveal.deleteLater()
        app.sendPostedEvents(None, QEvent.DeferredDelete)
        assert not isValid(reveal)
        QTest.qWait(45)


@case("横向滚动条销毁后不再测量布局")
def _():
    for _index in range(8):
        strip = HorizontalScrollStrip(["第一项", "第二项"])
        strip.deleteLater()
        app.sendPostedEvents(None, QEvent.DeferredDelete)
        assert not isValid(strip)
        app.processEvents()


if __name__ == "__main__":
    raise SystemExit(1 if _FAILURES else 0)
