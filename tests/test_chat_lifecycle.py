# -*- coding: utf-8 -*-
"""ChatConversation 延迟滚动与销毁生命周期回归。"""

import os
import sys
import traceback
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QEvent
from PySide6.QtWidgets import QApplication

from InstructionX_UIKit.layouts import ChatConversation
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


@case("待执行的滚动回调不得越过销毁")
def _():
    for _index in range(8):
        chat = ChatConversation(show_input=False)
        chat.add_message("assistant", "即将销毁的消息")
        chat.resize(420, 260)
        chat.show()
        chat._follow_after_doc_change()
        if not chat._follow_pending:
            raise AssertionError("测试未建立待执行的滚动回调")
        chat.deleteLater()
        app.sendPostedEvents(None, QEvent.DeferredDelete)
        app.processEvents()


if __name__ == "__main__":
    raise SystemExit(1 if _FAILURES else 0)
