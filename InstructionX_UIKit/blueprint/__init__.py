# -*- coding: utf-8 -*-
"""蓝图（节点图）组件包（BP_SPEC §1）。

类 UE5 Blueprint / ComfyUI 的节点图编辑器，**纯 UI 与交互**，不含业务
执行逻辑。扩展性第一：节点类型、引脚类型、菜单、节点体内容全部可
注册 / 覆写。

快速上手::

    from PySide6.QtCore import QPointF
    from InstructionX_UIKit.blueprint import (
        BlueprintGraph, BlueprintCanvas, register_node_type)

    register_node_type(
        "resize", "Resize", "处理",
        inputs=[{"id": "img", "name": "图像", "data_type": "image"}],
        outputs=[{"id": "img", "name": "图像", "data_type": "image"}],
        description="调整图像尺寸",
    )
    graph = BlueprintGraph()
    canvas = BlueprintCanvas(graph)
    canvas.add_node_at("start", QPointF(40, 120))
    canvas.show()
"""

from .canvas import BlueprintCanvas
from .edge_widget import EdgeWidget, TempWire, bezier_path
from .execution import ExecutionController
from .menu import NodeContextMenu, NodeCreationMenu
from .model import (
    BlueprintGraph,
    BlueprintNode,
    Edge,
    Pin,
    PinDirection,
    types_compatible,
)
from .node_widget import NodeWidget, PinHandle, format_elapsed
from .registry import (
    PIN_COLORS,
    NodeRegistry,
    NodeSpec,
    pin_color,
    register_node_type,
    register_pin_type,
)

__all__ = [
    # model
    "PinDirection",
    "Pin",
    "Edge",
    "BlueprintNode",
    "BlueprintGraph",
    "types_compatible",
    # registry
    "NodeSpec",
    "NodeRegistry",
    "register_node_type",
    "PIN_COLORS",
    "register_pin_type",
    "pin_color",
    # widgets
    "NodeWidget",
    "PinHandle",
    "format_elapsed",
    "EdgeWidget",
    "TempWire",
    "bezier_path",
    "BlueprintCanvas",
    # menus
    "NodeCreationMenu",
    "NodeContextMenu",
    # execution
    "ExecutionController",
]
