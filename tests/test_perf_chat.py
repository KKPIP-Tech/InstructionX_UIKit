# -*- coding: utf-8 -*-
"""聊天滚动跟随与事件泵回归（直接运行，不使用 pytest）。"""

import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QCoreApplication
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from InstructionX_UIKit.layouts.chat_conversation import ChatConversation
from InstructionX_UIKit.theme import ThemeManager

_FAILURES = []
app = QApplication.instance() or QApplication(sys.argv)
ThemeManager.instance().apply(app)


def check(name):
    def decorate(function):
        try:
            function()
            print(f"  [通过] {name}")
        except Exception:
            _FAILURES.append(name)
            print(f"  [失败] {name}")
            traceback.print_exc()
    return decorate


def make_chat():
    chat = ChatConversation(show_input=False)
    chat.add_message("assistant", "初始消息")
    chat.resize(420, 260)
    chat.show()
    app.processEvents()
    return chat


@check("文档尺寸回调不重入 processEvents")
def _():
    chat = make_chat()
    original = QCoreApplication.processEvents
    calls = []
    QCoreApplication.processEvents = lambda *args: calls.append(args)
    try:
        chat._follow_after_doc_change()
        QTest.qWait(40)
    finally:
        QCoreApplication.processEvents = original
    assert not calls, f"检测到 {len(calls)} 次重入事件泵"
    chat.close()


@check("底部跟随、用户上翻与恢复跟随")
def _():
    chat = make_chat()
    index = 0
    chat.append_to_message(index, "\n\n" + "\n\n".join(
        f"第 {index} 个 Markdown 段落" for index in range(30)))
    QTest.qWait(40)
    bar = chat._scroll.verticalScrollBar()
    assert bar.maximum() > 0
    chat._follow_scroll()
    assert bar.value() == bar.maximum()
    bar.setValue(0)
    chat._on_scroll_value(0)
    assert not chat._follow
    chat.append_to_message(index, "后续内容")
    QTest.qWait(40)
    assert bar.value() != bar.maximum()
    bar.setValue(bar.maximum())
    chat._on_scroll_value(bar.maximum())
    assert chat._follow
    chat._follow_after_doc_change()
    QTest.qWait(40)
    assert bar.value() == bar.maximum()
    chat.close()


@check("清空消息后恢复自动跟随")
def _():
    chat = make_chat()
    chat.append_to_message(0, "\n\n" + "\n\n".join(
        f"第 {index} 个 Markdown 段落" for index in range(30)))
    QTest.qWait(40)
    bar = chat._scroll.verticalScrollBar()
    assert bar.maximum() > 0
    bar.setValue(0)
    chat._on_scroll_value(0)
    assert not chat._follow
    chat.clear_messages()
    assert chat._follow
    chat.add_message("assistant", "新的消息")
    chat._follow_scroll()
    assert bar.value() == bar.maximum()
    chat.close()


if __name__ == "__main__":
    app.quit()
    raise SystemExit(1 if _FAILURES else 0)
