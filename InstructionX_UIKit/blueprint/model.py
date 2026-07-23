# -*- coding: utf-8 -*-
"""蓝图数据模型（BP_SPEC §2）。

本模块只包含纯数据与信号，不涉及任何界面绘制：

- ``PinDirection`` / ``Pin``：引脚方向与引脚描述；
- ``Edge``：一条输出引脚到输入引脚的连线；
- ``BlueprintNode``：节点（引脚、属性、运行状态、耗时），可 JSON 序列化；
- ``BlueprintGraph``：图容器，负责增删查与 ``add_edge`` 全量校验
  （方向相反、类型兼容含 any 通配、单连接替换、禁止自连 / 重复）。

示例::

    graph = BlueprintGraph()
    a = BlueprintNode("start", "开始"); a.add_output("out", "开始", "exec")
    b = BlueprintNode("proc", "处理");  b.add_input("in", "进入", "exec")
    graph.add_node(a); graph.add_node(b)
    edge = graph.add_edge(a.id, "out", b.id, "in")   # 校验通过返回 Edge
    data = graph.to_dict()                            # JSON 可序列化
"""

import uuid
from dataclasses import dataclass, field
from enum import Enum

from PySide6.QtCore import QObject, QPointF, QSizeF, Signal

__all__ = [
    "PinDirection",
    "Pin",
    "Edge",
    "BlueprintNode",
    "BlueprintGraph",
    "types_compatible",
]


def _new_id() -> str:
    """生成短随机 id（节点 / 边通用）。"""
    return uuid.uuid4().hex[:12]


class PinDirection(Enum):
    """引脚方向：``Input`` 输入 / ``Output`` 输出。"""

    Input = "input"
    Output = "output"


def types_compatible(out_type: str, in_type: str) -> bool:
    """判断输出类型与输入类型是否兼容（``"any"`` 双向通配）。

    参数:
        out_type: 输出引脚的 ``data_type``。
        in_type: 输入引脚的 ``data_type``。

    返回:
        类型相同，或任一端为 ``"any"`` 时为 ``True``。
    """
    if out_type == "any" or in_type == "any":
        return True
    return out_type == in_type


@dataclass
class Pin:
    """引脚描述。

    参数:
        id: 节点内唯一 id（如 ``"out"``）。
        name: 显示名（如 ``"开始"``）。
        direction: ``PinDirection.Input`` / ``PinDirection.Output``。
        data_type: 数据类型键，决定颜色（见 ``registry.PIN_COLORS``），
            缺省 ``"any"`` 表示通配。
        multi: 仅对输入引脚有意义：是否允许多连接（缺省 ``False``，
            此时新连线会自动替换旧连线）。
    """

    id: str
    name: str
    direction: PinDirection
    data_type: str = "any"
    multi: bool = False

    def to_dict(self) -> dict:
        """序列化为 JSON 友好字典。"""
        return {
            "id": self.id,
            "name": self.name,
            "direction": self.direction.value,
            "data_type": self.data_type,
            "multi": self.multi,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Pin":
        """由 ``to_dict`` 结果重建引脚。"""
        return cls(
            id=data["id"],
            name=data.get("name", data["id"]),
            direction=PinDirection(data.get("direction", "input")),
            data_type=data.get("data_type", "any"),
            multi=bool(data.get("multi", False)),
        )


@dataclass
class Edge:
    """一条连线：``from_*`` 为输出端，``to_*`` 为输入端。"""

    id: str
    from_node: str
    from_pin: str
    to_node: str
    to_pin: str

    def to_dict(self) -> dict:
        """序列化为 JSON 友好字典。"""
        return {
            "id": self.id,
            "from_node": self.from_node,
            "from_pin": self.from_pin,
            "to_node": self.to_node,
            "to_pin": self.to_pin,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Edge":
        """由 ``to_dict`` 结果重建边。"""
        return cls(
            id=data["id"],
            from_node=data["from_node"],
            from_pin=data["from_pin"],
            to_node=data["to_node"],
            to_pin=data["to_pin"],
        )


class BlueprintNode(QObject):
    """蓝图节点（数据 + 状态，不直接绘制）。

    参数:
        type_name: 注册表中的类型名（如 ``"start"``）。
        title: 节点标题（可修改，重命名即改它）。
        node_id: 可选固定 id，缺省自动生成。

    常用属性:
        .pos / .size: 场景坐标位置与逻辑尺寸（``QPointF`` / ``QSizeF``）。
        .inputs / .outputs: 引脚列表。
        .properties: 开发者自定义参数字典（节点体展示 / 编辑，可序列化）。
        .status: ``"idle" | "running" | "done" | "error"``。
        .elapsed_ms: 最近一次运行耗时（毫秒），未运行为 ``None``。
        .accent: 标题栏强调色（令牌键或 hex，来自注册表，可为 ``None``）。
    """

    #: 节点任意数据变化（标题 / 引脚 / 属性 / 位置）
    changed = Signal()
    #: 运行状态变化，参数为新状态字符串
    status_changed = Signal(str)

    def __init__(self, type_name: str, title: str, node_id: str = None, parent=None):
        super().__init__(parent)
        self.id = node_id or _new_id()
        self.type_name = str(type_name)
        self.title = str(title)
        self.pos = QPointF(0.0, 0.0)
        self.size = QSizeF(180.0, 80.0)
        self.inputs = []
        self.outputs = []
        self.properties = {}
        self.accent = None
        self._status = "idle"
        self._elapsed_ms = None
        self.error_message = ""

    # -- 状态 ------------------------------------------------------------
    @property
    def status(self) -> str:
        """当前运行状态：``idle / running / done / error``。"""
        return self._status

    def set_status(self, status: str) -> None:
        """设置运行状态并发射 ``status_changed``（画布监听以刷新外观）。"""
        if status not in ("idle", "running", "done", "error"):
            raise ValueError(f"未知节点状态: {status!r}")
        if status == self._status:
            return
        self._status = status
        self.status_changed.emit(status)
        self.changed.emit()

    @property
    def elapsed_ms(self):
        """最近一次运行耗时（毫秒），未运行为 ``None``。"""
        return self._elapsed_ms

    def set_elapsed_ms(self, value) -> None:
        """设置耗时（毫秒或 ``None``），触发重绘以更新耗时徽标。"""
        self._elapsed_ms = None if value is None else float(value)
        self.changed.emit()

    # -- 引脚 ------------------------------------------------------------
    def add_input(self, pin_id: str, name: str = None, data_type: str = "any",
                  multi: bool = False) -> Pin:
        """追加一个输入引脚并返回它。

        示例::

            node.add_input("img", "图像", "image")
            node.add_input("in", "进入", "exec", multi=True)
        """
        pin = Pin(pin_id, name if name is not None else pin_id,
                  PinDirection.Input, data_type, multi)
        self.inputs.append(pin)
        self.changed.emit()
        return pin

    def add_output(self, pin_id: str, name: str = None, data_type: str = "any",
                   multi: bool = False) -> Pin:
        """追加一个输出引脚并返回它（参数同 ``add_input``）。"""
        pin = Pin(pin_id, name if name is not None else pin_id,
                  PinDirection.Output, data_type, multi)
        self.outputs.append(pin)
        self.changed.emit()
        return pin

    def pin(self, pin_id: str, direction: "PinDirection" = None):
        """按 id 查找引脚，找不到返回 ``None``。

        参数:
            pin_id: 引脚 id。
            direction: 可选方向过滤。注意输入与输出允许使用相同 id
                （如 ComfyUI 风格的 ``"img"`` 进 / ``"img"`` 出），
                省略方向时按先输入后输出返回首个命中。
        """
        if direction is PinDirection.Input:
            return next((p for p in self.inputs if p.id == pin_id), None)
        if direction is PinDirection.Output:
            return next((p for p in self.outputs if p.id == pin_id), None)
        for pin in self.inputs + self.outputs:
            if pin.id == pin_id:
                return pin
        return None

    # -- 序列化 ----------------------------------------------------------
    def to_dict(self) -> dict:
        """序列化为 JSON 友好字典（含位置 / 尺寸 / 引脚 / 属性）。"""
        return {
            "id": self.id,
            "type_name": self.type_name,
            "title": self.title,
            "pos": [self.pos.x(), self.pos.y()],
            "size": [self.size.width(), self.size.height()],
            "accent": self.accent,
            "inputs": [p.to_dict() for p in self.inputs],
            "outputs": [p.to_dict() for p in self.outputs],
            "properties": dict(self.properties),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "BlueprintNode":
        """由 ``to_dict`` 结果重建节点（运行时状态不回放，保持 idle）。"""
        node = cls(data["type_name"], data.get("title", data["type_name"]),
                   node_id=data.get("id"))
        pos = data.get("pos", [0.0, 0.0])
        size = data.get("size", [180.0, 80.0])
        node.pos = QPointF(float(pos[0]), float(pos[1]))
        node.size = QSizeF(float(size[0]), float(size[1]))
        node.accent = data.get("accent")
        node.inputs = [Pin.from_dict(p) for p in data.get("inputs", [])]
        node.outputs = [Pin.from_dict(p) for p in data.get("outputs", [])]
        node.properties = dict(data.get("properties", {}))
        return node


class BlueprintGraph(QObject):
    """蓝图图容器：节点与边的增删查、连线校验、序列化。

    ``add_edge`` 校验规则（任一不满足返回 ``None``，不产生副作用）：

    1. 节点与引脚必须存在；
    2. 方向必须相反（``from_*`` 为输出、``to_*`` 为输入）；
    3. 数据类型兼容（``"any"`` 双向通配）；
    4. 禁止自连（同一节点）与完全重复（同两端引脚）的边；
    5. 输入引脚非 ``multi`` 时保持单连接：旧边自动移除后接入新边。

    示例::

        graph = BlueprintGraph()
        graph.edge_added.connect(lambda e: print("新连线", e.id))
        graph.add_edge(a.id, "out", b.id, "in")
    """

    node_added = Signal(object)
    node_removed = Signal(str)
    edge_added = Signal(object)
    edge_removed = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._nodes = {}
        self._edges = {}

    # -- 节点 ------------------------------------------------------------
    def add_node(self, node: BlueprintNode) -> BlueprintNode:
        """加入节点（id 冲突时抛 ``ValueError``），发射 ``node_added``。"""
        if node.id in self._nodes:
            raise ValueError(f"节点 id 冲突: {node.id}")
        self._nodes[node.id] = node
        self.node_added.emit(node)
        return node

    def remove_node(self, node_id: str) -> bool:
        """移除节点并连带移除其全部边，发射相应信号；不存在返回 ``False``。"""
        node = self._nodes.pop(node_id, None)
        if node is None:
            return False
        for edge in list(self._edges.values()):
            if edge.from_node == node_id or edge.to_node == node_id:
                self.remove_edge(edge.id)
        self.node_removed.emit(node_id)
        return True

    def node(self, node_id: str):
        """按 id 取节点，不存在返回 ``None``。"""
        return self._nodes.get(node_id)

    def nodes(self) -> list:
        """全部节点列表（插入序）。"""
        return list(self._nodes.values())

    # -- 边 --------------------------------------------------------------
    def add_edge(self, from_node: str, from_pin: str,
                 to_node: str, to_pin: str):
        """校验并建立连线，成功返回 ``Edge``，失败返回 ``None``。

        校验：方向相反（输出→输入）、类型兼容（any 通配）、禁止自连 /
        重复；输入非 multi 时自动移除旧边（单连接替换）。
        """
        n1, n2 = self._nodes.get(from_node), self._nodes.get(to_node)
        if n1 is None or n2 is None:
            return None
        # 方向特定查找：输入 / 输出允许同名 id（如 "img" 进与 "img" 出）
        p_out = next((p for p in n1.outputs if p.id == from_pin), None)
        p_in = next((p for p in n2.inputs if p.id == to_pin), None)
        if p_out is None or p_in is None:
            return None
        if from_node == to_node:
            return None
        if not types_compatible(p_out.data_type, p_in.data_type):
            return None
        for edge in self._edges.values():
            if (edge.from_node == from_node and edge.from_pin == from_pin
                    and edge.to_node == to_node and edge.to_pin == to_pin):
                return None  # 完全重复
        if not p_in.multi:
            for edge in list(self._edges.values()):
                if edge.to_node == to_node and edge.to_pin == to_pin:
                    self.remove_edge(edge.id)  # 单连接替换
        edge = Edge(_new_id(), from_node, from_pin, to_node, to_pin)
        self._edges[edge.id] = edge
        self.edge_added.emit(edge)
        return edge

    def remove_edge(self, edge_id: str) -> bool:
        """移除边，发射 ``edge_removed``；不存在返回 ``False``。"""
        edge = self._edges.pop(edge_id, None)
        if edge is None:
            return False
        self.edge_removed.emit(edge_id)
        return True

    def edge(self, edge_id: str):
        """按 id 取边，不存在返回 ``None``。"""
        return self._edges.get(edge_id)

    def edges(self) -> list:
        """全部边列表（插入序）。"""
        return list(self._edges.values())

    def edges_of(self, node_id: str) -> list:
        """与某节点相连的全部边（两端任一命中）。"""
        return [e for e in self._edges.values()
                if e.from_node == node_id or e.to_node == node_id]

    def clear(self) -> None:
        """清空全部节点与边（逐条发射移除信号，界面自动同步）。"""
        for edge_id in list(self._edges.keys()):
            self.remove_edge(edge_id)
        for node_id in list(self._nodes.keys()):
            self.remove_node(node_id)

    # -- 序列化 ----------------------------------------------------------
    def to_dict(self) -> dict:
        """序列化为 JSON 友好字典：``{"nodes": [...], "edges": [...]}``。"""
        return {
            "nodes": [n.to_dict() for n in self._nodes.values()],
            "edges": [e.to_dict() for e in self._edges.values()],
        }

    @classmethod
    def from_dict(cls, data: dict) -> "BlueprintGraph":
        """由 ``to_dict`` 结果重建整张图（节点 / 边顺序保持）。"""
        graph = cls()
        for nd in data.get("nodes", []):
            graph.add_node(BlueprintNode.from_dict(nd))
        for ed in data.get("edges", []):
            edge = Edge.from_dict(ed)
            graph._edges[edge.id] = edge
            graph.edge_added.emit(edge)
        return graph
