# -*- coding: utf-8 -*-
"""CodeEditor 与 DiffEditor 的真实编辑、IME、面板和生命周期回归。"""

import os
import sys
import time
import traceback
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QEvent, QPoint, Qt
from PySide6.QtGui import QInputMethodEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from InstructionX_UIKit.code_editor import CodeEditor, DiffEditor
from InstructionX_UIKit.theme import ThemeManager

app = QApplication.instance() or QApplication(sys.argv)
ThemeManager.instance().apply(app)
_FAILURES = []


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


def pump(ms):
    deadline = time.monotonic() + ms / 1000
    while time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.003)


def make_editor(text=""):
    editor = CodeEditor()
    editor.resize(720, 420)
    editor.set_text(text)
    cursor = editor.text_area().textCursor()
    cursor.setPosition(len(text))
    editor.text_area().setTextCursor(cursor)
    editor.show()
    editor.setFocus()
    pump(20)
    return editor


def close_editor(editor):
    editor.close()
    editor.deleteLater()
    app.sendPostedEvents(None, QEvent.DeferredDelete)
    app.processEvents()


@check("文本、光标、只读、诊断与折叠")
def _():
    editor = make_editor("def foo():\n    return 1\n" * 30)
    editor.goto_line(42)
    assert editor.cursor_position() == (42, 1), editor.cursor_position()
    editor.set_diagnostics([{"line": 42, "severity": "error", "message": "示例"}])
    assert editor.diagnostics()[0]["line"] == 42
    assert 42 in editor.diagnostic_lines()
    editor.toggle_breakpoint(42)
    assert 42 in editor.breakpoints()
    editor.toggle_breakpoint(42)
    assert 42 not in editor.breakpoints()
    editor.fold_all()
    assert editor.folded_lines()
    editor.unfold_all()
    assert not editor.folded_lines()
    editor.set_readonly(True)
    before = editor.text()
    QTest.keyClicks(editor.text_area(), "x")
    assert editor.text() == before
    editor.set_readonly(False)
    editor.close()
    close_editor(editor)


@check("Ctrl+D 多选与批量编辑")
def _():
    editor = make_editor("foo\nfoo\nfoo")
    for _index in range(3):
        QTest.keyClick(editor.text_area(), Qt.Key_D, Qt.ControlModifier)
    selections = editor.multi_selections()
    assert len(selections) == 3, selections
    QTest.keyClicks(editor.text_area(), "X")
    assert editor.text() == "X\nX\nX", editor.text()
    editor.close()
    close_editor(editor)


@check("查找、计数、大小写与全部替换")
def _():
    editor = make_editor("alpha beta alpha\nAlpha alpha")
    editor.open_find_bar(replace=True)
    bar = editor.find_bar()
    bar.find_edit.setText("alpha")
    editor.find_update()
    assert editor.find_count()[1] == 4, editor.find_count()
    bar.case_btn.setChecked(True)
    editor.find_update()
    assert editor.find_count()[1] == 3, editor.find_count()
    editor.find_next()
    assert editor.find_count()[0] >= 0
    bar.replace_edit.setText("omega")
    editor.replace_all()
    assert editor.text() == "omega beta omega\nAlpha omega", editor.text()
    editor.close_find_bar()
    assert editor.find_count() == (-1, 0)
    editor.close()
    close_editor(editor)


@check("补全、悬停与快捷键配置")
def _():
    editor = make_editor("pri")
    editor.set_language("python")
    editor.set_completion_provider(
        lambda prefix, line, col, language: [
            {"label": "print", "kind": "function", "detail": "内置", "insert": "print("}
        ])
    editor._trigger_completion()
    popup = editor.completion_popup()
    assert popup.count() >= 1
    editor._apply_completion(popup.current_insert_text())
    assert editor.text() == "print(", editor.text()
    editor.set_hover_provider(lambda line, col: f"<b>{line}:{col}</b>")
    editor._show_hover_at(QPoint(0, 0))
    bubble = editor.hover_bubble()
    assert bubble.isVisible()
    assert bubble._label.text() == "<b>1:1</b>", bubble._label.text()
    editor.set_shortcut("trigger_completion", "Ctrl+J")
    assert editor.shortcut("trigger_completion") == "Ctrl+J"
    editor.set_shortcuts_enabled(False)
    assert not editor.shortcuts_enabled()
    editor.close()
    close_editor(editor)


@check("IME 提交与主题切换")
def _():
    editor = make_editor("")
    event = QInputMethodEvent()
    event.setCommitString("中文输入")
    QApplication.sendEvent(editor.text_area(), event)
    assert "中文输入" in editor.text(), editor.text()
    editor.set_language("python")
    assert editor.highlight_engine() is not None
    ThemeManager.instance().set_mode("dark")
    ThemeManager.instance().set_mode("light")
    pump(20)
    editor.close()
    close_editor(editor)


@check("Diff 模式、滚动、字符差异与 hunk 回退")
def _():
    diff = DiffEditor()
    diff.resize(900, 520)
    diff.set_documents("a\nb\nc\n", "a\nB\nc\n")
    assert diff.old_text() == "a\nb\nc\n"
    assert diff.new_text() == "a\nB\nc\n"
    assert diff.hunk_count() >= 1
    diff.set_view_mode("inline")
    assert diff.inline_editor() is not None
    diff.set_char_diff_enabled(True)
    diff.set_view_mode("side-by-side")
    assert len(diff.side_editors()) == 2
    diff.next_hunk()
    diff.prev_hunk()
    diff.set_revert_enabled(True)
    assert diff.revert_hunk(0)
    assert diff.new_text() == diff.old_text()
    diff.set_auto_breakpoint(480)
    diff.resize(460, 520)
    pump(30)
    diff.close()
    close_editor(diff)


if __name__ == "__main__":
    app.quit()
    raise SystemExit(1 if _FAILURES else 0)
