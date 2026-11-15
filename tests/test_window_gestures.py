# -*- coding: utf-8 -*-
"""系统窗口手势与手动回退回归（直接运行，不使用 pytest）。"""

import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from demo.window_host import WindowHost
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


def make_host():
    host = WindowHost()
    host.show()
    app.processEvents()
    return host


@check("系统 move 成功时不走手动位移")
def _():
    host = make_host()
    calls = []
    host.gesture._system_move = lambda handle: calls.append(handle) or True
    geometry = host.geometry()
    QTest.mouseClick(host._titlebar, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(50, 24))
    assert len(calls) == 1
    QTest.mouseMove(host, QPoint(90, 70))
    assert host.geometry() == geometry
    host.close()


@check("系统 resize 四角映射成功")
def _():
    host = make_host()
    calls = []
    host.gesture._system_resize = lambda handle, edges: calls.append(edges) or True
    geometry = host.geometry()
    QTest.mouseClick(host._titlebar, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
                     host._titlebar.rect().bottomRight() - QPoint(1, 1))
    assert len(calls) == 1
    assert calls[0] == (Qt.RightEdge | Qt.BottomEdge), calls
    QTest.mouseMove(host, QPoint(920, 70))
    assert host.geometry() == geometry
    host.close()


@check("系统不可用时手动移动窗口")
def _():
    host = make_host()
    origin = host.geometry()
    QTest.mousePress(host._titlebar, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(50, 24))
    manual_origin = host.gesture._manual[1]
    target_global = host.mapToGlobal(QPoint(50, 50))
    QTest.mouseMove(host, target_global)
    assert host.geometry().topLeft() == origin.topLeft() + (
        target_global - manual_origin), (host.geometry(), origin, manual_origin)
    QTest.mouseRelease(host._titlebar, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(50, 50))
    host.close()


@check("手动右下角缩放保留最小尺寸")
def _():
    host = make_host()
    origin = host.geometry()
    QTest.mousePress(host._titlebar, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
                     host._titlebar.rect().bottomRight() - QPoint(1, 1))
    manual_origin = host.gesture._manual[1]
    target_global = host.mapToGlobal(QPoint(920, 70))
    QTest.mouseMove(host, target_global)
    delta = target_global - manual_origin
    assert host.width() == origin.width() + delta.x(), (
        host.width(), origin.width(), delta)
    assert host.height() == origin.height() + delta.y(), (
        host.height(), origin.height(), delta)
    QTest.mouseRelease(host._titlebar, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(920, 70))
    host.close()


@check("客户区四边四角调用系统缩放")
def _():
    host = make_host()
    calls = []
    host.gesture._system_resize = lambda handle, edges: calls.append(edges) or True
    central = host.centralWidget()
    width, height = central.width(), central.height()
    cases = [
        (QPoint(2, height // 2), Qt.LeftEdge),
        (QPoint(width - 2, height // 2), Qt.RightEdge),
        (QPoint(width // 2, 2), Qt.TopEdge),
        (QPoint(width // 2, height - 2), Qt.BottomEdge),
        (QPoint(2, 2), Qt.LeftEdge | Qt.TopEdge),
        (QPoint(width - 2, 2), Qt.RightEdge | Qt.TopEdge),
        (QPoint(2, height - 2), Qt.LeftEdge | Qt.BottomEdge),
        (QPoint(width - 2, height - 2), Qt.RightEdge | Qt.BottomEdge),
    ]
    for point, expected in cases:
        QTest.mouseClick(central, Qt.MouseButton.LeftButton,
                         Qt.KeyboardModifier.NoModifier, point)
        assert calls and calls[-1] == expected, (point, expected, calls)
    host.close()


@check("标题栏双击最大化与还原")
def _():
    host = make_host()
    origin = host.geometry()
    QTest.mouseDClick(host._titlebar, Qt.MouseButton.LeftButton,
                        Qt.KeyboardModifier.NoModifier, QPoint(50, 24))
    assert host.isMaximized(), host.windowState()
    QTest.mouseDClick(host._titlebar, Qt.MouseButton.LeftButton,
                        Qt.KeyboardModifier.NoModifier, QPoint(50, 24))
    assert not host.isMaximized(), host.windowState()
    assert host.geometry() == origin, (host.geometry(), origin)
    assert host.gesture._manual is None
    host.close()


@check("透明宿主与关闭按钮正常")
def _():
    host = make_host()
    assert host.testAttribute(Qt.WA_TranslucentBackground)
    assert host.testAttribute(Qt.WA_NoSystemBackground)
    assert not host.autoFillBackground()
    close = host._titlebar.findChild(__import__(
        "PySide6.QtWidgets", fromlist=["QToolButton"]).QToolButton)
    QTest.mouseClick(close, Qt.MouseButton.LeftButton)
    assert not host.isVisible()


if __name__ == "__main__":
    app.quit()
    raise SystemExit(1 if _FAILURES else 0)
