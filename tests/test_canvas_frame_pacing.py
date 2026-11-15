# -*- coding: utf-8 -*-
"""可见 Canvas 视口在交换帧后继续调度，不把数据更新频率当呈现频率。"""

import os
from pathlib import Path
import sys
import time
import traceback

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.pop("QT_QPA_PLATFORM", None)
os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")
os.environ["UIKIT_CHART_BACKEND"] = "canvas"

from PySide6.QtCore import QPointF
from PySide6.QtWidgets import QApplication
from InstructionX_UIKit.blueprint import BlueprintCanvas, BlueprintGraph, BlueprintNode
from InstructionX_UIKit.charts import ChartWidget
from InstructionX_UIKit.blueprint.canvas_viewport import CanvasBlueprintViewport
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


@check("交换帧继续调度下一次同步且保持隐藏暂停")
def _():
    graph = BlueprintGraph()
    node = BlueprintNode("perf", "静态节点", node_id="a")
    node.pos = QPointF(80, 90)
    graph.add_node(node)
    canvas = BlueprintCanvas(graph)
    canvas.resize(900, 600)
    canvas.show()
    viewport = CanvasBlueprintViewport(canvas, parent=canvas)
    old = canvas._viewport
    canvas._viewport = viewport
    for widget in canvas._node_widgets.values():
        widget.setParent(viewport)
    old.close()
    old.deleteLater()
    viewport.show()
    try:
        viewport._sync_now()
        viewport._sync_timer.stop()
        assert not viewport._sync_timer.isActive()
        viewport._host._emit_frames()
        assert viewport._sync_timer.isActive()
        viewport._suspend()
        viewport._sync_timer.stop()
        viewport._host._emit_frames()
        assert not viewport._sync_timer.isActive()
    finally:
        viewport.close()
        canvas.close()
        deadline = time.perf_counter() + 0.1
        while time.perf_counter() < deadline:
            app.processEvents()
            time.sleep(0.005)


@check("数据更新与交换帧合并为每个呈现周期一次同步")
def _():
    graph = BlueprintGraph()
    node = BlueprintNode("perf", "数据节点", node_id="a")
    node.pos = QPointF(80, 90)
    graph.add_node(node)
    canvas = BlueprintCanvas(graph)
    canvas.resize(900, 600)
    canvas.show()
    viewport = CanvasBlueprintViewport(canvas, parent=canvas)
    old = canvas._viewport
    canvas._viewport = viewport
    for widget in canvas._node_widgets.values():
        widget.setParent(viewport)
    old.close()
    old.deleteLater()
    viewport.show()
    try:
        viewport._sync_now()
        viewport._sync_timer.stop()
        viewport.update()
        assert not viewport._sync_timer.isActive(), "数据更新不应越过下一次交换帧额外同步"
        viewport._host._emit_frames()
        assert viewport._sync_timer.isActive(), "交换帧必须调度包含最新数据的同步"
        viewport._sync_now()
        viewport.update()
        assert not viewport._sync_timer.isActive()
    finally:
        viewport.close()
        canvas.close()
        deadline = time.perf_counter() + 0.1
        while time.perf_counter() < deadline:
            app.processEvents()
            time.sleep(0.005)


@check("干净图表不重复同步而更新后下一帧必须同步")
def _():
    chart = ChartWidget()
    chart.set_option({"animation": False, "xAxis": {"type": "value"},
                      "yAxis": {"type": "value"},
                      "series": [{"type": "line", "data": [0, 1, 0],
                                  "showSymbol": False}]})
    chart.resize(700, 400)
    chart.show()
    viewport = chart._viewport
    frames = []
    viewport.frameSwapped.connect(lambda: frames.append(1))
    try:
        viewport._sync_now()
        viewport._sync_timer.stop()
        viewport._host._emit_frames()
        assert not viewport._sync_timer.isActive(), "无变化图表不应重复同步"
        assert len(frames) == 1, "跳过同步不得跳过真实交换帧通知"
        chart.update()
        viewport._host._emit_frames()
        assert viewport._sync_timer.isActive(), "update 后必须在下一帧同步"
        viewport._sync_now()
        chart.resize(720, 420)
        viewport._host._emit_frames()
        assert viewport._sync_timer.isActive(), "尺寸变化必须在下一帧同步"
        viewport._sync_now()
        assert chart.set_stream_data([1, 0, 1])
        viewport._host._emit_frames()
        assert viewport._sync_timer.isActive(), "流式数据必须在下一帧同步"
    finally:
        chart.close()
        deadline = time.perf_counter() + 0.1
        while time.perf_counter() < deadline:
            app.processEvents()
            time.sleep(0.005)


if __name__ == "__main__":
    app.quit()
    raise SystemExit(1 if _FAILURES else 0)
