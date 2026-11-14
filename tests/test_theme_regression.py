# -*- coding: utf-8 -*-
"""主题动态属性刷新与视觉契约回归。"""

import os
import sys
import traceback
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PySide6.QtWidgets import QApplication, QWidget

from InstructionX_UIKit.theme import ThemeManager, set_property

app = QApplication.instance() or QApplication(sys.argv)
ThemeManager.instance().apply(app)
_FAILURES = []


class RecordingStyle:
    """记录真实样式调用，不接管任何 Qt 样式对象的所有权。"""

    def __init__(self, widget):
        self._style = widget.style()
        self.polished = []
        self.unpolished = []

    def polish(self, obj):
        self.polished.append(obj)
        self._style.polish(obj)

    def unpolish(self, obj):
        self.unpolished.append(obj)
        self._style.unpolish(obj)


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


@case("同值动态属性跳过样式刷新")
def _():
    widget = QWidget()
    style = RecordingStyle(widget)
    widget.style = lambda: style
    set_property(widget, "size", "md")
    if widget.property("uiksize") != "md":
        raise AssertionError("size 应继续映射为 uiksize")
    if style.unpolished.count(widget) != 1 or style.polished.count(widget) != 1:
        raise AssertionError("首次设置应恰好执行一次 unpolish/polish")
    for _index in range(20):
        set_property(widget, "size", "md")
    if style.unpolished.count(widget) != 1 or style.polished.count(widget) != 1:
        raise AssertionError("同值属性不应重复 unpolish/polish")
    set_property(widget, "size", "lg")
    if style.unpolished.count(widget) != 2 or style.polished.count(widget) != 2:
        raise AssertionError("不同值应恰好增加一次 unpolish/polish")
    if widget.property("uiksize") != "lg":
        raise AssertionError("变化后的属性值未生效")
    widget.deleteLater()


if __name__ == "__main__":
    app.processEvents()
    raise SystemExit(1 if _FAILURES else 0)
