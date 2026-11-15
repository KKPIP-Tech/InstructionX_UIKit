# -*- coding: utf-8 -*-
"""Blueprint 流动动画不得重建静态网格和节点场景。"""

import os
from pathlib import Path
import sys
import time
import traceback

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.pop("QT_QPA_PLATFORM", None)
os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")

from PySide6.QtCore import QPointF
from PySide6.QtWidgets import QApplication
from InstructionX_UIKit.blueprint import BlueprintCanvas, BlueprintGraph, BlueprintNode
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


@check("流动边独立更新，网格和节点场景复用")
def _():
    graph = BlueprintGraph()
    first = BlueprintNode("perf", "甲", node_id="a")
    first.add_output("out")
    first.pos = QPointF(80, 100)
    second = BlueprintNode("perf", "乙", node_id="b")
    second.add_input("in")
    second.pos = QPointF(400, 200)
    graph.add_node(first)
    graph.add_node(second)
    graph.add_edge("a", "out", "b", "in")
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
        edge = next(iter(canvas._edge_widgets.values()))
        edge.set_flowing(True)
        viewport._sync_now()
        static = viewport._static_scene
        nodes = viewport._component_scene
        flowing = viewport._line_views[0]
        edge.advance_dash()
        viewport._sync_now()
        assert viewport._static_scene is static
        assert viewport._component_scene is nodes
        assert viewport._line_views[0] is not flowing
    finally:
        viewport.close()
        canvas.close()
        deadline = time.perf_counter() + 0.1
        while time.perf_counter() < deadline:
            app.processEvents()
            time.sleep(0.005)


@check("相同流动相位复用路径且几何变化立即失效")
def _():
    from InstructionX_UIKit.blueprint import canvas_scene
    graph = BlueprintGraph()
    first = BlueprintNode("perf", "甲", node_id="a")
    first.add_output("out")
    first.pos = QPointF(80, 100)
    second = BlueprintNode("perf", "乙", node_id="b")
    second.add_input("in")
    second.pos = QPointF(400, 200)
    graph.add_node(first)
    graph.add_node(second)
    graph.add_edge("a", "out", "b", "in")
    canvas = BlueprintCanvas(graph)
    canvas.resize(900, 600)
    canvas.show()
    app.processEvents()
    edge = next(iter(canvas._edge_widgets.values()))
    edge.set_flowing(True)
    original = canvas_scene.dashed_paths
    calls = []

    def counted(*args, **kwargs):
        calls.append(args)
        return original(*args, **kwargs)

    canvas_scene.dashed_paths = counted
    try:
        edge._dash_offset = -1.6
        first_scene = canvas_scene.build_blueprint_flow(canvas)
        edge._dash_offset = -7.6
        second_scene = canvas_scene.build_blueprint_flow(canvas)
        assert len(calls) == 1, f"相同相位重复构建: {len(calls)} 次"
        assert len(first_scene.commands) == len(second_scene.commands)
        for left, right in zip(first_scene.commands, second_scene.commands):
            assert left[0] == right[0]
            if left[0] != "stroke_pen":
                continue
            assert left[1].commandsSize() == right[1].commandsSize()
            for index in range(left[1].commandsSize()):
                delta = left[1].positionAt(index) - right[1].positionAt(index)
                assert delta.manhattanLength() < 1e-6
        first.pos = QPointF(120, 140)
        app.processEvents()
        canvas_scene.build_blueprint_flow(canvas)
        assert len(calls) == 2, "节点移动后必须重建新几何"
    finally:
        canvas_scene.dashed_paths = original
        canvas.close()
        deadline = time.perf_counter() + 0.1
        while time.perf_counter() < deadline:
            app.processEvents()
            time.sleep(0.005)


if __name__ == "__main__":
    app.quit()
    raise SystemExit(1 if _FAILURES else 0)
