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


def wait_until(predicate, timeout_ms=2000):
    from time import monotonic
    deadline = monotonic() + timeout_ms / 1000
    while not predicate() and monotonic() < deadline:
        QTest.qWait(5)
    if not predicate():
        raise AssertionError("等待异步状态完成超时")


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
    bar = chat._scroll.verticalScrollBar()
    wait_until(lambda: bar.maximum() > 0)
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
    bar = chat._scroll.verticalScrollBar()
    wait_until(lambda: bar.maximum() > 0)
    bar.setValue(0)
    chat._on_scroll_value(0)
    assert not chat._follow
    chat.clear_messages()
    assert chat._follow
    chat.add_message("assistant", "新的消息")
    chat._follow_scroll()
    assert bar.value() == bar.maximum()
    chat.close()


@check("流式 chunk 合并且完成时强制同步")
def _():
    chat = make_chat()
    view = chat._bubbles[0].view
    original = view.append_markdown
    calls = []
    view.append_markdown = lambda chunk: calls.append(chunk) or original(chunk)
    chunks = [f"\n\n第 {index} 段 **加粗** 与 $x_{index}$" for index in range(40)]
    for chunk in chunks:
        chat.append_to_message(0, chunk)
    assert chat.messages()[0]["content"] == "初始消息" + "".join(chunks)
    assert not calls, "同一渲染批次之前不应逐 chunk 更新 MarkdownView"
    wait_until(lambda: bool(calls))
    assert len(calls) == 1, f"40 个 chunk 应合并为一次渲染: {len(calls)}"
    chat.append_to_message(0, "\n\n最后的 **片段**")
    chat.finish_message(0)
    assert len(calls) == 2, "finish_message 必须立即冲刷最后一批"
    assert view.markdown() == chat.messages()[0]["content"]
    chat.close()


@check("统计按批次刷新且结束时立即冻结")
def _():
    chat = make_chat()
    bubble = chat._bubbles[0]
    original = bubble.set_stats_text
    calls = []
    bubble.set_stats_text = lambda text: calls.append(text) or original(text)
    for index in range(40):
        chat.append_to_message(0, f"第 {index} 个分片")
    assert not calls, "统计不应逐 chunk 更新"
    QTest.qWait(150)
    assert 1 <= len(calls) <= 2, f"统计应按约 8 Hz 合并刷新: {len(calls)}"
    chat.append_to_message(0, "最后片段")
    chat.finish_message(0)
    assert calls and "用时" in calls[-1]
    assert bubble._stats_label.text() == calls[-1]
    chat.close()


@check("更新与清空后旧流式回调不得覆盖新消息")
def _():
    chat = make_chat()
    chat.append_to_message(0, "旧分片")
    chat.update_message(0, "**新内容**")
    QTest.qWait(180)
    assert chat._bubbles[0].view.markdown() == "**新内容**"
    assert chat.messages()[0]["content"] == "**新内容**"
    chat.append_to_message(0, "即将清空")
    chat.clear_messages()
    chat.add_message("assistant", "全新会话")
    QTest.qWait(180)
    assert len(chat._bubbles) == 1
    assert chat._bubbles[0].view.markdown() == "全新会话"
    assert chat.messages() == [{"role": "assistant", "content": "全新会话", "info": ""}]
    chat.close()


@check("隐藏停更且恢复只提交最新合并内容")
def _():
    chat = make_chat()
    view = chat._bubbles[0].view
    original = view.append_markdown
    calls = []
    view.append_markdown = lambda chunk: calls.append(chunk) or original(chunk)
    chat.append_to_message(0, "隐藏前的分片")
    chat.hide()
    assert not chat._render_timer.isActive()
    chat.append_to_message(0, "隐藏期间的分片")
    QTest.qWait(180)
    assert not calls, "隐藏期间不得渲染或补跑历史帧"
    assert not chat._stats_timer.isActive()
    chat.show()
    assert len(calls) == 1
    assert calls[0] == "隐藏前的分片隐藏期间的分片"
    assert view.markdown() == chat.messages()[0]["content"]
    chat.close()


@check("待渲染文本有界且内联编辑使旧回调失效")
def _():
    chat = make_chat()
    for _index in range(20):
        chat.append_to_message(0, "x" * 4096)
    pending = sum(len(text) for text in chat._pending_chunks.values())
    assert pending <= 65536, f"待处理文本超过容量上限: {pending}"
    chat.finish_message(0)
    assert chat._bubbles[0].view.markdown() == chat.messages()[0]["content"]
    bubble = chat._bubbles[0]
    bubble.start_edit(chat.messages()[0]["content"])
    chat.append_to_message(0, "编辑期间到达的旧分片")
    bubble._editor.setPlainText("**编辑后的新内容**")
    chat._confirm_edit(0, bubble)
    QTest.qWait(180)
    assert bubble.view.markdown() == "**编辑后的新内容**"
    assert chat.messages()[0]["content"] == "**编辑后的新内容**"
    chat.close()


if __name__ == "__main__":
    app.quit()
    raise SystemExit(1 if _FAILURES else 0)
