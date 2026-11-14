# -*- coding: utf-8 -*-
"""图表、Blueprint 与页面宿主的激活生命周期回归。"""

import contextlib
import io
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
from PySide6.QtWidgets import QApplication

from InstructionX_UIKit.blueprint import BlueprintCanvas, BlueprintGraph, BlueprintNode
from InstructionX_UIKit.charts import ChartWidget
from InstructionX_UIKit.theme import ThemeManager
from demo.main_window import MainWindow

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


@case("图表隐藏暂停动画与流式定时器，恢复最新数据")
def _():
    chart = ChartWidget()
    chart.set_option({
        "xAxis": {"type": "category", "data": []},
        "yAxis": {"type": "value"},
        "series": [{"type": "line", "data": []}],
    })
    chart.resize(640, 360)
    chart.show()
    app.processEvents()
    session = chart.stream(window=32, interval=0.005)
    updates = []
    original_update = chart._viewport.update
    chart._viewport.update = lambda *args: updates.append(args) or original_update(*args)
    chart.anim.start()
    assert chart.anim.is_running()
    chart.hide()
    assert not chart.anim.is_running()
    assert not session._timer.isActive()
    session.write([1, 2, 3])
    QTest.qWait(40)
    assert list(chart.series_renderers[0].data_view()) == []
    updates.clear()
    chart.update()
    assert not updates, "隐藏后不应转发重绘"
    chart.show()
    assert session._timer.isActive()
    assert chart.anim.is_running()
    assert list(chart.series_renderers[0].data_view()) == [1, 2, 3]
    assert updates, "恢复应请求最新帧"
    session.close()
    chart.close()
    chart.deleteLater()
    app.sendPostedEvents(None, QEvent.DeferredDelete)


@case("Blueprint 隐藏停止流动且恢复已有流动状态")
def _():
    graph = BlueprintGraph()
    first = BlueprintNode("test", "起点")
    first.add_output("out")
    second = BlueprintNode("test", "终点")
    second.add_input("in")
    graph.add_node(first)
    graph.add_node(second)
    edge = graph.add_edge(first.id, "out", second.id, "in")
    assert edge is not None
    canvas = BlueprintCanvas(graph)
    canvas.resize(640, 360)
    canvas.show()
    app.processEvents()
    canvas._execution.set_path([first.id, second.id])
    assert canvas._flow_timer.isActive()
    widget = canvas.edge_widget(edge.id)
    canvas.hide()
    assert not canvas._flow_timer.isActive()
    offset = widget._dash_offset
    canvas._tick_flow()
    assert widget._dash_offset == offset
    updates = []
    original_update = canvas._viewport.update
    canvas._viewport.update = lambda *args: updates.append(args) or original_update(*args)
    canvas.update()
    assert not updates, "隐藏后不应转发重绘"
    canvas.show()
    assert canvas._flow_timer.isActive()
    assert widget.flowing
    assert updates, "恢复应请求最新帧"
    canvas.close()
    assert not canvas._flow_timer.isActive()
    canvas.deleteLater()
    app.sendPostedEvents(None, QEvent.DeferredDelete)


@case("页面宿主发送退出和进入激活通知")
def _():
    window = MainWindow()
    window.resize(1280, 800)
    window.show()
    window.navigate("tokens")
    window.navigate("button")
    window.navigate("tokens")
    first = window._page_cache["tokens"]
    second = window._page_cache["button"]
    events = []
    first.on_ui_deactivated = lambda: events.append("tokens off")
    second.on_ui_activated = lambda: events.append("button on")
    window.navigate("button")
    assert events == ["tokens off", "button on"], events
    window.close()
    window.deleteLater()
    app.sendPostedEvents(None, QEvent.DeferredDelete)


@case("销毁窗口后主题通知不访问已删除控件")
def _():
    for key in ("tokens", "button", "anim_property"):
        window = MainWindow()
        window.navigate(key)
        window.show()
        app.processEvents()
        window.close()
        window.deleteLater()
        app.sendPostedEvents(None, QEvent.DeferredDelete)
    tm = ThemeManager.instance()
    errors = io.StringIO()
    with contextlib.redirect_stderr(errors):
        tm.set_mode("dark")
        app.processEvents()
        tm.set_mode("light")
        app.processEvents()
    details = errors.getvalue()
    assert "already deleted" not in details and "RuntimeError" not in details, details[:2000]


if __name__ == "__main__":
    app.processEvents()
    raise SystemExit(1 if _FAILURES else 0)
