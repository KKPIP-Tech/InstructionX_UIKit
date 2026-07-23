# -*- coding: utf-8 -*-
"""蓝图注册表（BP_SPEC §3）——扩展性核心。

本模块提供节点类型 / 引脚类型的全部扩展点：

- ``NodeSpec``：节点类型描述（引脚、分类、强调色、自定义体构建器、描述）；
- ``NodeRegistry``：单例注册表，``register`` / ``create`` / ``specs`` /
  ``categories`` / ``search``；
- ``register_node_type``：一行代码注册节点类型的便捷函数；
- ``PIN_COLORS`` / ``register_pin_type`` / ``pin_color``：引脚类型配色。

``body_builder`` 是最重要的扩展点：签名为
``Callable[[BlueprintNode, QWidget], None]``，第二个参数是节点体容器
（透明背景、自带垂直布局 ``container.layout()``），开发者在其中创建
任意编辑控件并写回 ``node.properties``。

完整示例::

    from PySide6.QtWidgets import QSpinBox
    from InstructionX_UIKit.blueprint import register_node_type

    def build_resize_body(node, container):
        spin = QSpinBox()
        spin.setRange(1, 8192)
        spin.setValue(int(node.properties.get("width", 512)))
        spin.valueChanged.connect(
            lambda v: node.properties.__setitem__("width", int(v)))
        container.layout().addWidget(spin)

    register_node_type(
        "resize", "Resize", "处理",
        inputs=[{"id": "img", "name": "图像", "data_type": "image"}],
        outputs=[{"id": "img", "name": "图像", "data_type": "image"}],
        accent="primary", body_builder=build_resize_body,
        description="调整图像尺寸",
    )
"""

from dataclasses import dataclass, field
from typing import Callable, Optional

from ..theme import T
from .model import BlueprintNode, PinDirection

__all__ = [
    "NodeSpec",
    "NodeRegistry",
    "register_node_type",
    "PIN_COLORS",
    "register_pin_type",
    "pin_color",
]


# ---------------------------------------------------------------------------
# 引脚类型配色
# ---------------------------------------------------------------------------

#: 引脚类型 → 颜色。值可以是令牌键（如 ``"success"`` 即 ``color.success``）
#: 或 ``#hex`` 颜色字符串。``exec`` 为执行流引脚（浅灰白）。
PIN_COLORS = {
    "any": "text.tertiary",
    "int": "success",
    "float": "primary",
    "str": "warning",
    "image": "#C080D0",
    "tensor": "#4FA8A0",
    "exec": "#E8E8E8",
}


def register_pin_type(name: str, color: str) -> None:
    """注册 / 覆盖一种引脚类型配色。

    参数:
        name: 类型名（``Pin.data_type`` 使用的键，如 ``"audio"``）。
        color: 令牌键（``"success"`` 等，自动取 ``color.<name>``）或 hex。

    示例::

        register_pin_type("audio", "#E0A030")
        register_pin_type("mask", "danger")
    """
    PIN_COLORS[str(name)] = str(color)


def pin_color(data_type: str) -> str:
    """取引脚类型对应的实时颜色（hex 字符串），主题感知。

    值若为令牌键则经 ``T("color.<key>")`` 实时解析；未知类型回退 ``any``。
    """
    value = PIN_COLORS.get(data_type, PIN_COLORS["any"])
    if value.startswith("#") or value.startswith("rgb"):
        return value
    return str(T(f"color.{value}"))


# ---------------------------------------------------------------------------
# 节点类型描述
# ---------------------------------------------------------------------------

@dataclass
class NodeSpec:
    """节点类型描述（注册表条目）。

    参数:
        type_name: 类型唯一键（如 ``"resize"``）。
        title: 节点默认标题（创建节点时可再改）。
        category: 分类名（创建菜单按它分组，如 ``"处理"``）。
        inputs / outputs: 引脚字典列表，每项
            ``{"id", "name", "data_type", "multi"}``（后三个可缺省）。
        accent: 标题栏强调色（令牌键如 ``"primary"`` 或 hex），
            ``None`` 时使用默认灰。
        body_builder: 自定义节点体构建器
            ``Callable[[BlueprintNode, QWidget], None]``，缺省 ``None``
            表示以 properties 键值对展示。
        description: 描述文本（创建菜单 tooltip / 副标题）。
    """

    type_name: str
    title: str
    category: str
    inputs: list = field(default_factory=list)
    outputs: list = field(default_factory=list)
    accent: Optional[str] = None
    body_builder: Optional[Callable] = None
    description: str = ""


# ---------------------------------------------------------------------------
# 注册表（单例）
# ---------------------------------------------------------------------------

class NodeRegistry:
    """节点类型注册表（单例）。

    用法::

        reg = NodeRegistry.instance()
        reg.register(NodeSpec("resize", "Resize", "处理", ...))
        node = reg.create("resize")          # -> BlueprintNode（引脚已就位）
        reg.search("图像")                    # 按标题/类型/描述模糊搜索
        reg.categories()                     # ["流程", "输入", ...]

    Demo / 应用层通常使用便捷函数 ``register_node_type``。
    """

    _instance = None

    def __init__(self):
        self._specs = {}

    @classmethod
    def instance(cls) -> "NodeRegistry":
        """返回全局唯一注册表实例。"""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    # -- 注册 ------------------------------------------------------------
    def register(self, spec: NodeSpec) -> NodeSpec:
        """注册节点类型（同 ``type_name`` 覆盖），返回 ``spec``。"""
        if not spec.type_name:
            raise ValueError("NodeSpec.type_name 不能为空")
        self._specs[spec.type_name] = spec
        return spec

    def unregister(self, type_name: str) -> bool:
        """注销节点类型；不存在返回 ``False``。"""
        return self._specs.pop(type_name, None) is not None

    def spec(self, type_name: str):
        """按类型名取 ``NodeSpec``，未注册返回 ``None``。"""
        return self._specs.get(type_name)

    # -- 查询 ------------------------------------------------------------
    def specs(self, category: str = None) -> list:
        """全部 ``NodeSpec``（可按分类过滤），按注册顺序返回。"""
        items = list(self._specs.values())
        if category is not None:
            items = [s for s in items if s.category == category]
        return items

    def categories(self) -> list:
        """全部分类名（按注册出现顺序，去重）。"""
        seen = []
        for spec in self._specs.values():
            if spec.category not in seen:
                seen.append(spec.category)
        return seen

    def search(self, keyword: str) -> list:
        """按关键字模糊搜索（匹配类型名 / 标题 / 分类 / 描述，忽略大小写）。"""
        kw = str(keyword).strip().lower()
        if not kw:
            return self.specs()
        result = []
        for spec in self._specs.values():
            hay = (spec.type_name + spec.title + spec.category
                   + spec.description).lower()
            if kw in hay:
                result.append(spec)
        return result

    # -- 创建 ------------------------------------------------------------
    def create(self, type_name: str) -> BlueprintNode:
        """按类型创建 ``BlueprintNode``：引脚 / 标题 / 强调色按 spec 就位。

        未注册的类型抛 ``KeyError``。``body_builder`` 不在此调用——
        它由 ``NodeWidget`` 在构建节点体时执行（UI 层职责）。
        """
        spec = self._specs.get(type_name)
        if spec is None:
            raise KeyError(f"未注册的节点类型: {type_name!r}")
        node = BlueprintNode(spec.type_name, spec.title)
        node.accent = spec.accent
        for pd in spec.inputs:
            node.add_input(pd["id"], pd.get("name"), pd.get("data_type", "any"),
                           bool(pd.get("multi", False)))
        for pd in spec.outputs:
            node.add_output(pd["id"], pd.get("name"), pd.get("data_type", "any"),
                            bool(pd.get("multi", False)))
        return node


def register_node_type(type_name: str, title: str, category: str,
                       inputs=(), outputs=(), accent=None,
                       body_builder=None, description: str = "") -> NodeSpec:
    """便捷函数：一行注册节点类型（等价 ``NodeRegistry.instance().register``）。

    参数:
        type_name / title / category: 见 ``NodeSpec``。
        inputs / outputs: 引脚字典序列，如
            ``[{"id": "img", "name": "图像", "data_type": "image"}]``。
        accent: 标题栏强调色（令牌键或 hex）。
        body_builder: ``Callable[[BlueprintNode, QWidget], None]``，
            在节点体容器中注入自定义编辑 UI（见模块 docstring 完整示例）。
        description: 创建菜单中的描述 / tooltip。

    返回:
        注册成功的 ``NodeSpec``。
    """
    spec = NodeSpec(type_name=type_name, title=title, category=category,
                    inputs=list(inputs), outputs=list(outputs), accent=accent,
                    body_builder=body_builder, description=description)
    return NodeRegistry.instance().register(spec)


# ---------------------------------------------------------------------------
# 内置节点类型
# ---------------------------------------------------------------------------

#: 内置起始节点（exec 输出），保证开箱即有；Demo 可在此基础上扩展。
register_node_type(
    "start", "开始", "流程",
    outputs=[{"id": "out", "name": "开始", "data_type": "exec"}],
    accent="success",
    description="流程入口：从此引脚拖出执行流",
)
