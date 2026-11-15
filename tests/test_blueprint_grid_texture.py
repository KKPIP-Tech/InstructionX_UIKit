# -*- coding: utf-8 -*-
"""Blueprint 点阵网格使用 GPU 离屏纹理平铺，而非逐点路径。"""

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


def pump(milliseconds=100):
    deadline = time.perf_counter() + milliseconds / 1000
    while time.perf_counter() < deadline:
        app.processEvents()
        time.sleep(0.005)


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


@check("GPU 网格纹理只生成一次并复用")
def _():
    graph = BlueprintGraph()
    node = BlueprintNode("perf", "节点", node_id="a")
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
        commands = viewport._static_scene.commands
        assert any(command[0] == "grid_pattern" for command in commands), commands[:3]
        assert not any(command[0] == "fill" and command[1].commandsSize() > 100
                       for command in commands)
        pump(150)
        viewport._sync_now()
        renderer = viewport._item._renderer
        assert len(renderer._grid_cache) == 1
        assert "direct" in viewport.rhi_api().lower()
    finally:
        viewport.close()
        canvas.close()
        pump()


if __name__ == "__main__":
    app.quit()
    raise SystemExit(1 if _FAILURES else 0)
