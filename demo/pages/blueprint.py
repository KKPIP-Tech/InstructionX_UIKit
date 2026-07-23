# -*- coding: utf-8 -*-
"""蓝图 Demo 页（BP_SPEC §7）。

展示 ``InstructionX_UIKit.blueprint`` 节点图组件的完整用法：

- 顶部工具条：运行 / 单步 / 重置 / 适应视图 / 保存 JSON / 加载 JSON +
  状态标签；
- 中央 ``BlueprintCanvas``：预置「开始→加载图像→预处理→模型推理→
  后处理→保存结果」流水线（exec 链 + image/tensor 数据引脚混排）；
- 右侧属性面板：选中节点时显示其类型 / 标题 / 状态，并用
  ``playground.ParamForm`` 编辑属性（写回 ``node.properties``）。

**纯模拟说明**：本页的「运行 / 单步」只驱动 ``ExecutionController``
的 UI 状态指示（running / done / 耗时徽标 / 路径高亮），不执行任何
真实业务逻辑（不读图、不跑模型）。

节点体说明：``body_builder`` 注入的属性编辑控件在画布内被画布置为
鼠标透明（避免与节点拖拽冲突），仅作展示；实际编辑请用右侧属性面板，
两者写回的都是同一份 ``node.properties``。
"""

import json
import os
import random
import time
from pathlib import Path

from PySide6.QtCore import QPointF, Qt, QTimer
from PySide6.QtWidgets import (
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from InstructionX_UIKit.blueprint import (
    BlueprintCanvas,
    BlueprintGraph,
    register_node_type,
)
from InstructionX_UIKit.components import Button
from InstructionX_UIKit.components.combo_box import ComboBox
from InstructionX_UIKit.components.slider import Slider
from InstructionX_UIKit.components.spin_box import SpinBox
from InstructionX_UIKit.theme import set_property

from .common import code_label, hint_label
from .playground import ParamForm

__all__ = ["create_page", "register_demo_node_types", "PROPERTY_SCHEMAS"]

#: offscreen 下降级读写当前工作目录的该文件（不弹文件对话框）
FALLBACK_JSON = "blueprint_demo.json"

# ---------------------------------------------------------------------------
# 节点属性 schema（右侧属性面板用）
#   ("int",    key, 标签, 默认, 最小, 最大)
#   ("float",  key, 标签, 默认, 最小, 最大)
#   ("choice", key, 标签, 默认, options)
#   ("text",   key, 标签, 默认)
#   ("bool",   key, 标签, 默认)
# ---------------------------------------------------------------------------
PROPERTY_SCHEMAS = {
    "load_image": [
        ("text", "path", "文件路径", "demo/input.png"),
        ("choice", "mode", "色彩模式", "RGB", ["RGB", "RGBA", "L"]),
    ],
    "noise": [
        ("int", "seed", "随机种子", 42, 0, 99999),
        ("text", "shape", "形状", "1x3x224x224"),
    ],
    "resize": [
        ("int", "width", "宽度", 640, 16, 4096),
        ("int", "height", "高度", 480, 16, 4096),
        ("choice", "interpolation", "插值", "bilinear",
         ["nearest", "bilinear", "bicubic", "lanczos"]),
    ],
    "normalize": [
        ("float", "mean", "均值", 0.5, 0.0, 1.0),
        ("float", "std", "标准差", 0.5, 0.01, 1.0),
    ],
    "gaussian_blur": [
        ("int", "radius", "半径", 5, 0, 50),
    ],
    "edge_detect": [
        ("choice", "method", "算法", "sobel", ["sobel", "canny", "laplacian"]),
        ("int", "threshold", "阈值", 128, 0, 255),
    ],
    "cnn": [
        ("int", "layers", "层数", 18, 1, 200),
        ("int", "channels", "通道数", 64, 8, 1024),
    ],
    "transformer": [
        ("int", "layers", "层数", 6, 1, 48),
        ("int", "heads", "注意力头", 8, 1, 32),
    ],
    "fusion": [
        ("float", "weight", "融合权重", 0.5, 0.0, 1.0),
    ],
    "save_result": [
        ("text", "path", "输出路径", "output/result.png"),
        ("choice", "format", "格式", "png", ["png", "jpg", "npy"]),
    ],
    "log_output": [
        ("choice", "level", "级别", "info", ["debug", "info", "warning", "error"]),
    ],
    "perf_probe": [
        ("int", "warn_ms", "告警阈值 ms", 500, 0, 100000),
        ("bool", "enabled", "启用", True),
    ],
}


def _defaults(type_name: str) -> dict:
    """取某节点类型的属性默认值字典。"""
    return {spec[1]: spec[3] for spec in PROPERTY_SCHEMAS.get(type_name, [])}


def apply_defaults(node) -> None:
    """把 schema 默认属性以 setdefault 方式写入 ``node.properties``。"""
    for key, value in _defaults(node.type_name).items():
        node.properties.setdefault(key, value)


# ---------------------------------------------------------------------------
# body_builder：节点体内嵌属性编辑控件（写回 node.properties）
# 注：画布将节点体置为鼠标透明（避免与拖拽冲突），此处控件作展示用；
# 交互编辑由右侧属性面板完成。
# ---------------------------------------------------------------------------

def _mini_label(text: str) -> QLabel:
    lab = QLabel(text)
    set_property(lab, "role", "tertiary")
    return lab


def _body_row(container, label, widget) -> None:
    row = QWidget()
    row.setAttribute(Qt.WA_TransparentForMouseEvents, False)
    lay = QHBoxLayout(row)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(4)
    lay.addWidget(_mini_label(label))
    lay.addWidget(widget, 1)
    container.layout().addWidget(row)
    # sm 控件实际绘制约 24–26px 高；NodeWidget 依容器 sizeHint 计算
    # 节点体区高度，构造期 sizeHint 偏小会导致行重叠，故显式保底
    row.setMinimumHeight(26)


def build_resize_body(node, container) -> None:
    """Resize 节点体：宽 / 高 SpinBox + 插值 ComboBox（写回 properties）。"""
    apply_defaults(node)
    width = SpinBox(16, 4096, int(node.properties["width"]), size="sm")
    width.valueChanged.connect(
        lambda v: node.properties.__setitem__("width", int(v)))
    _body_row(container, "宽", width)
    height = SpinBox(16, 4096, int(node.properties["height"]), size="sm")
    height.valueChanged.connect(
        lambda v: node.properties.__setitem__("height", int(v)))
    _body_row(container, "高", height)
    combo = ComboBox(size="sm")
    for item in ("nearest", "bilinear", "bicubic", "lanczos"):
        combo.addItem(item, item)
    combo.setCurrentIndex(max(0, combo.findData(node.properties["interpolation"])))
    combo.currentIndexChanged.connect(
        lambda i: node.properties.__setitem__("interpolation", combo.itemData(i)))
    _body_row(container, "插值", combo)


def build_cnn_body(node, container) -> None:
    """CNN 节点体：层数 / 通道数 SpinBox（写回 properties）。"""
    apply_defaults(node)
    layers = SpinBox(1, 200, int(node.properties["layers"]), size="sm")
    layers.valueChanged.connect(
        lambda v: node.properties.__setitem__("layers", int(v)))
    _body_row(container, "层数", layers)
    channels = SpinBox(8, 1024, int(node.properties["channels"]), size="sm")
    channels.valueChanged.connect(
        lambda v: node.properties.__setitem__("channels", int(v)))
    _body_row(container, "通道", channels)


def build_blur_body(node, container) -> None:
    """高斯模糊节点体：半径 Slider（写回 properties）。"""
    apply_defaults(node)
    slider = Slider(minimum=0, maximum=50, value=int(node.properties["radius"]))
    slider.set_tip_enabled(False)
    slider.valueChanged.connect(
        lambda v: node.properties.__setitem__("radius", int(v)))
    _body_row(container, "半径", slider)


def build_transformer_body(node, container) -> None:
    """Transformer 节点体：层数 / 注意力头 SpinBox（写回 properties）。"""
    apply_defaults(node)
    layers = SpinBox(1, 48, int(node.properties["layers"]), size="sm")
    layers.valueChanged.connect(
        lambda v: node.properties.__setitem__("layers", int(v)))
    _body_row(container, "层数", layers)
    heads = SpinBox(1, 32, int(node.properties["heads"]), size="sm")
    heads.valueChanged.connect(
        lambda v: node.properties.__setitem__("heads", int(v)))
    _body_row(container, "头数", heads)


# ---------------------------------------------------------------------------
# 节点类型注册（模块级；重复 import 时同名覆盖，安全）
# ---------------------------------------------------------------------------

_EXEC_IN = {"id": "in", "name": "进入", "data_type": "exec"}
_EXEC_OUT = {"id": "out", "name": "退出", "data_type": "exec"}


def register_demo_node_types() -> None:
    """注册 Demo 全部节点类型（分类：流程 / 输入 / 处理 / 模型 / 输出 / 工具）。

    库内置 ``start``（流程）之外注册 12 种；其中 resize / cnn /
    gaussian_blur / transformer 带 ``body_builder`` 属性编辑体。
    """
    # -- 输入 -------------------------------------------------------------
    register_node_type(
        "load_image", "加载图像", "输入",
        inputs=[dict(_EXEC_IN)],
        outputs=[dict(_EXEC_OUT),
                 {"id": "img", "name": "图像", "data_type": "image"}],
        accent="primary", description="从磁盘加载图像（image 输出）",
    )
    register_node_type(
        "noise", "随机噪声", "输入",
        inputs=[dict(_EXEC_IN)],
        outputs=[dict(_EXEC_OUT),
                 {"id": "tensor", "name": "噪声", "data_type": "tensor"}],
        accent="primary", description="生成随机噪声张量（tensor 输出）",
    )
    # -- 处理 -------------------------------------------------------------
    register_node_type(
        "resize", "Resize", "处理",
        inputs=[dict(_EXEC_IN),
                {"id": "img", "name": "图像", "data_type": "image"}],
        outputs=[dict(_EXEC_OUT),
                 {"id": "img", "name": "图像", "data_type": "image"}],
        accent="warning", body_builder=build_resize_body,
        description="调整图像尺寸（宽 / 高 / 插值可编辑）",
    )
    register_node_type(
        "normalize", "归一化", "处理",
        inputs=[dict(_EXEC_IN),
                {"id": "img", "name": "图像", "data_type": "image"}],
        outputs=[dict(_EXEC_OUT),
                 {"id": "tensor", "name": "张量", "data_type": "tensor"}],
        accent="warning", description="图像归一化为张量（预处理）",
    )
    register_node_type(
        "gaussian_blur", "高斯模糊", "处理",
        inputs=[dict(_EXEC_IN),
                {"id": "img", "name": "图像", "data_type": "image"}],
        outputs=[dict(_EXEC_OUT),
                 {"id": "img", "name": "图像", "data_type": "image"}],
        accent="warning", body_builder=build_blur_body,
        description="高斯模糊（半径 Slider 可调）",
    )
    register_node_type(
        "edge_detect", "边缘检测", "处理",
        inputs=[dict(_EXEC_IN),
                {"id": "tensor", "name": "张量", "data_type": "tensor"}],
        outputs=[dict(_EXEC_OUT),
                 {"id": "img", "name": "边缘图", "data_type": "image"}],
        accent="warning", description="从张量提取边缘（后处理）",
    )
    # -- 模型 -------------------------------------------------------------
    register_node_type(
        "cnn", "CNN 模块", "模型",
        inputs=[dict(_EXEC_IN),
                {"id": "tensor", "name": "张量", "data_type": "tensor"}],
        outputs=[dict(_EXEC_OUT),
                 {"id": "tensor", "name": "特征", "data_type": "tensor"}],
        accent="danger", body_builder=build_cnn_body,
        description="卷积骨干（层数 / 通道数可编辑）",
    )
    register_node_type(
        "transformer", "Transformer 模块", "模型",
        inputs=[dict(_EXEC_IN),
                {"id": "tensor", "name": "张量", "data_type": "tensor"}],
        outputs=[dict(_EXEC_OUT),
                 {"id": "tensor", "name": "特征", "data_type": "tensor"}],
        accent="danger", body_builder=build_transformer_body,
        description="注意力模块（层数 / 头数可编辑）",
    )
    register_node_type(
        "fusion", "融合", "模型",
        inputs=[dict(_EXEC_IN),
                {"id": "tensor_a", "name": "张量 A", "data_type": "tensor"},
                {"id": "tensor_b", "name": "张量 B", "data_type": "tensor"}],
        outputs=[dict(_EXEC_OUT),
                 {"id": "tensor", "name": "融合", "data_type": "tensor"}],
        accent="danger", description="两路 tensor 加权融合",
    )
    # -- 输出 -------------------------------------------------------------
    register_node_type(
        "save_result", "保存结果", "输出",
        inputs=[dict(_EXEC_IN),
                {"id": "img", "name": "图像", "data_type": "image"}],
        accent="success", description="把结果写出到磁盘",
    )
    register_node_type(
        "log_output", "日志输出", "输出",
        inputs=[dict(_EXEC_IN),
                {"id": "msg", "name": "消息", "data_type": "any", "multi": True}],
        accent="success", description="打印任意数据到日志",
    )
    # -- 工具 -------------------------------------------------------------
    register_node_type(
        "perf_probe", "性能探针", "工具",
        inputs=[dict(_EXEC_IN),
                {"id": "any_in", "name": "观测", "data_type": "any", "multi": True}],
        outputs=[dict(_EXEC_OUT),
                 {"id": "any_out", "name": "透传", "data_type": "any"}],
        accent="#7A6FC0", description="统计上游耗时并透传数据",
    )


# 模块级注册（库内置 "start" 节点保证开箱即有）
register_demo_node_types()


# ---------------------------------------------------------------------------
# exec 链拓扑排序
# ---------------------------------------------------------------------------

def exec_order(graph: BlueprintGraph) -> list:
    """按 exec 引脚连线做拓扑排序，返回节点 id 执行序列。

    只考虑目标引脚为 ``exec`` 类型的边；图中无 exec 边时回退为
    全部节点的插入序（保证「运行」总有可视反馈）。
    """
    exec_edges = []
    for edge in graph.edges():
        node = graph.node(edge.to_node)
        if node is None:
            continue
        pin = next((p for p in node.inputs if p.id == edge.to_pin), None)
        if pin is not None and pin.data_type == "exec":
            exec_edges.append(edge)
    if not exec_edges:
        return [n.id for n in graph.nodes()]
    involved = []
    for edge in exec_edges:
        for nid in (edge.from_node, edge.to_node):
            if nid not in involved:
                involved.append(nid)
    indeg = {nid: 0 for nid in involved}
    adj = {nid: [] for nid in involved}
    for edge in exec_edges:
        indeg[edge.to_node] += 1
        adj[edge.from_node].append(edge.to_node)
    queue = [nid for nid in involved if indeg[nid] == 0]
    order = []
    while queue:
        nid = queue.pop(0)
        order.append(nid)
        for nxt in adj[nid]:
            indeg[nxt] -= 1
            if indeg[nxt] == 0:
                queue.append(nxt)
    if len(order) != len(involved):  # 有环：剩余按插入序兜底
        order.extend(nid for nid in involved if nid not in order)
    return order


# ---------------------------------------------------------------------------
# 页面
# ---------------------------------------------------------------------------

class BlueprintDemoPage(QWidget):
    """蓝图演示页：工具条 + 画布 + 右侧属性面板。

    公开属性（供测试 / 外部集成）：
        ``graph`` / ``canvas`` / ``status_label`` / ``panel_form``；
        ``delay_range``：运行模拟每节点随机耗时区间（ms），测试可置
        ``(0, 0)`` 加速。
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.delay_range = (200, 800)
        self._order = []
        self._idx = 0
        self._t0 = 0.0
        self._gen = 0          # 运行世代：reset 后使旧定时器回调失效
        self._step_total = 0.0
        self._mode = "run"     # "run"（QTimer 连续）/ "step"（逐节点）

        self.graph = BlueprintGraph()
        # 先接默认属性槽，保证 NodeWidget 构建时 properties 已就位
        self.graph.node_added.connect(apply_defaults)
        self.canvas = BlueprintCanvas(self.graph, self)

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 16)
        root.setSpacing(8)

        title = QLabel("蓝图（节点图）")
        font = title.font()
        font.setPixelSize(18)
        font.setBold(True)
        title.setFont(font)
        root.addWidget(title)
        root.addWidget(hint_label(
            "类 UE5 Blueprint / ComfyUI 节点图编辑器。右键空白创建节点、"
            "引脚拖出连线、Delete 删除选中。「运行 / 单步」为纯 UI 模拟："
            "仅驱动 ExecutionController 状态指示，不含任何业务逻辑。"))
        root.addWidget(code_label(
            'canvas = BlueprintCanvas(BlueprintGraph()); '
            'canvas.add_node_at("resize", QPointF(100, 80))'))

        root.addLayout(self._build_toolbar())

        body = QHBoxLayout()
        body.setSpacing(12)
        body.addWidget(self.canvas, 1)
        body.addWidget(self._build_panel(), 0)
        root.addLayout(body, 1)

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._complete_node)

        self.canvas.selection_changed.connect(self._on_selection)

        self._build_preset()
        self._on_selection([])

    # ------------------------------------------------------------------ 工具条
    def _build_toolbar(self) -> QHBoxLayout:
        bar = QHBoxLayout()
        bar.setSpacing(8)
        self.run_button = Button("运行", variant="primary", size="sm")
        self.run_button.clicked.connect(self.run_all)
        self.step_button = Button("单步", size="sm")
        self.step_button.clicked.connect(self.step_once)
        self.reset_button = Button("重置", size="sm")
        self.reset_button.clicked.connect(self.reset_run)
        self.fit_button = Button("适应视图", size="sm")
        self.fit_button.clicked.connect(self.canvas.fit_view)
        self.save_button = Button("保存 JSON", size="sm")
        self.save_button.clicked.connect(self.save_json)
        self.load_button = Button("加载 JSON", size="sm")
        self.load_button.clicked.connect(self.load_json)
        for btn in (self.run_button, self.step_button, self.reset_button,
                    self.fit_button, self.save_button, self.load_button):
            bar.addWidget(btn)
        self.status_label = QLabel("就绪")
        set_property(self.status_label, "role", "secondary")
        bar.addWidget(self.status_label, 1)
        return bar

    # ------------------------------------------------------------------ 属性面板
    def _build_panel(self) -> QFrame:
        panel = QFrame()
        panel.setFrameShape(QFrame.Shape.StyledPanel)
        panel.setFixedWidth(300)
        lay = QVBoxLayout(panel)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(8)
        head = QLabel("属性面板")
        head_font = head.font()
        head_font.setBold(True)
        head.setFont(head_font)
        lay.addWidget(head)
        self._panel_host = QWidget()
        host_lay = QVBoxLayout(self._panel_host)
        host_lay.setContentsMargins(0, 0, 0, 0)
        host_lay.setSpacing(6)
        lay.addWidget(self._panel_host, 1)
        return panel

    def _clear_panel(self) -> None:
        lay = self._panel_host.layout()
        while lay.count():
            item = lay.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()
        self.panel_form = None

    def _on_selection(self, node_ids) -> None:
        """选中变化 → 重建右侧属性面板（单选展示 + ParamForm 编辑）。"""
        self._clear_panel()
        lay = self._panel_host.layout()
        node = self.graph.node(node_ids[0]) if len(node_ids) == 1 else None
        if node is None:
            hint = hint_label("在画布中选中一个节点，查看 / 编辑其属性。",
                              role="tertiary")
            lay.addWidget(hint)
            lay.addStretch(1)
            return
        apply_defaults(node)

        def info(text, role="secondary"):
            lab = QLabel(text)
            lab.setWordWrap(True)
            set_property(lab, "role", role)
            lay.addWidget(lab)

        info(f"标题：{node.title}")
        info(f"类型：{node.type_name}    ID：{node.id}", role="tertiary")
        info(f"状态：{node.status}"
             + (f"    耗时：{node.elapsed_ms:.0f} ms"
                if node.elapsed_ms is not None else ""), role="tertiary")

        schema = PROPERTY_SCHEMAS.get(node.type_name)
        if not schema:
            info("该节点无可编辑属性。", role="tertiary")
            lay.addStretch(1)
            return
        form = ParamForm()
        for spec in schema:
            kind, key, label, default = spec[:4]
            value = node.properties.get(key, default)
            cb = (lambda v, n=node, k=key: self._set_prop(n, k, v))
            if kind == "int":
                form.add_int(label, int(value), spec[4], spec[5], cb, key=key)
            elif kind == "float":
                form.add_float(label, float(value), spec[4], spec[5], cb, key=key)
            elif kind == "choice":
                form.add_choice(label, list(spec[4]), value, cb, key=key)
            elif kind == "bool":
                form.add_bool(label, bool(value), cb, key=key)
            elif kind == "text":
                form.add_text(label, str(value), cb, key=key)
        lay.addWidget(form)
        lay.addStretch(1)
        self.panel_form = form

    def _set_prop(self, node, key, value) -> None:
        """属性面板写回 ``node.properties`` 并刷新节点外观。"""
        node.properties[key] = value
        node.changed.emit()

    # ------------------------------------------------------------------ 预置图
    def _build_preset(self) -> None:
        """开始→加载图像→预处理(归一化)→模型推理(CNN)→后处理(边缘检测)→保存。"""
        g = self.graph
        n_start = self.canvas.add_node_at("start", QPointF(40, 180))
        n_load = self.canvas.add_node_at("load_image", QPointF(300, 180))
        n_pre = self.canvas.add_node_at("normalize", QPointF(560, 180))
        n_pre.title = "预处理（归一化）"
        n_cnn = self.canvas.add_node_at("cnn", QPointF(840, 180))
        n_cnn.title = "模型推理（CNN）"
        n_post = self.canvas.add_node_at("edge_detect", QPointF(1140, 180))
        n_post.title = "后处理（边缘检测）"
        n_save = self.canvas.add_node_at("save_result", QPointF(1440, 180))
        # exec 链
        g.add_edge(n_start.id, "out", n_load.id, "in")
        g.add_edge(n_load.id, "out", n_pre.id, "in")
        g.add_edge(n_pre.id, "out", n_cnn.id, "in")
        g.add_edge(n_cnn.id, "out", n_post.id, "in")
        g.add_edge(n_post.id, "out", n_save.id, "in")
        # 数据引脚（image / tensor 混排）
        g.add_edge(n_load.id, "img", n_pre.id, "img")
        g.add_edge(n_pre.id, "tensor", n_cnn.id, "tensor")
        g.add_edge(n_cnn.id, "tensor", n_post.id, "tensor")
        g.add_edge(n_post.id, "img", n_save.id, "img")
        self.preset_ids = [n_start.id, n_load.id, n_pre.id,
                           n_cnn.id, n_post.id, n_save.id]

    # ------------------------------------------------------------------ 运行模拟
    def run_all(self) -> None:
        """「运行」：按 exec 链拓扑序，QTimer 逐节点模拟 200–800ms 随机耗时。"""
        self._mode = "run"
        self._prepare_run()
        self._begin_node()

    def step_once(self) -> None:
        """「单步」：每次点击推进一个节点（立即完成，耗时取随机模拟值）。"""
        if not self._order or self._idx >= len(self._order):
            self._mode = "step"
            self._prepare_run()
            self._step_total = 0.0
        ex = self.canvas.execution()
        nid = self._order[self._idx]
        ms = float(random.randint(*self.delay_range))
        ex.start(nid)
        ex.finish(nid, ms)
        self._step_total += ms
        self._idx += 1
        self._after_node(ms)

    def reset_run(self) -> None:
        """「重置」：中断进行中的模拟，全部节点回 idle。"""
        self._gen += 1
        self._timer.stop()
        self._order = []
        self._idx = 0
        self.canvas.execution().reset()
        self.status_label.setText("就绪")

    def _prepare_run(self) -> None:
        self._gen += 1
        self.canvas.execution().reset()
        self._order = exec_order(self.graph)
        self._idx = 0
        self._t0 = time.perf_counter()
        self.canvas.execution().set_path(self._order)

    def _begin_node(self) -> None:
        if self._idx >= len(self._order):
            return
        nid = self._order[self._idx]
        self.canvas.execution().start(nid)
        gen = self._gen
        delay = random.randint(*self.delay_range)
        self.status_label.setText(
            f"运行中 {self._idx + 1}/{len(self._order)} …")
        self._timer.start(delay)
        self._timer.setProperty("gen", gen)

    def _complete_node(self) -> None:
        if self._timer.property("gen") != self._gen:
            return  # 已被重置 / 新一轮取代
        nid = self._order[self._idx]
        self.canvas.execution().finish(nid)  # 缺省自动计时
        self._idx += 1
        node = self.graph.node(nid)
        self._after_node(node.elapsed_ms if node is not None else 0.0)
        if self._idx < len(self._order):
            self._begin_node()

    def _after_node(self, _ms: float) -> None:
        if self._idx >= len(self._order) and self._order:
            if self._mode == "step":
                total = self._step_total  # 单步：累计模拟耗时
            else:
                total = (time.perf_counter() - self._t0) * 1000.0
            self.status_label.setText(
                f"模拟完成：{len(self._order)} 个节点 · 总耗时 {total:.0f} ms"
                "（纯模拟，无业务逻辑）")
        if self.canvas.selected_nodes():
            self._on_selection(self.canvas.selected_nodes())

    # ------------------------------------------------------------------ 序列化
    def _json_path(self, save: bool) -> str:
        """取 JSON 路径：offscreen 降级为 cwd 下固定文件，否则弹文件对话框。"""
        if os.environ.get("QT_QPA_PLATFORM") == "offscreen":
            return str(Path.cwd() / FALLBACK_JSON)
        if save:
            path, _ = QFileDialog.getSaveFileName(
                self, "保存蓝图 JSON", FALLBACK_JSON, "JSON 文件 (*.json)")
        else:
            path, _ = QFileDialog.getOpenFileName(
                self, "加载蓝图 JSON", "", "JSON 文件 (*.json)")
        return path

    def save_json(self) -> None:
        """保存整张图（含位置与 zoom/offset）到 JSON。"""
        path = self._json_path(save=True)
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(self.canvas.to_dict(), fh,
                          ensure_ascii=False, indent=2)
        except OSError as exc:
            self.status_label.setText(f"保存失败：{exc}")
            return
        self.status_label.setText(f"已保存：{path}")

    def load_json(self) -> None:
        """从 JSON 恢复整张图（节点 / 边 / 视图状态）。"""
        path = self._json_path(save=False)
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, ValueError) as exc:
            self.status_label.setText(f"加载失败：{exc}")
            return
        self.reset_run()
        self.canvas.from_dict(data)
        self.canvas.fit_view()
        self.status_label.setText(
            f"已加载：{path}（{len(self.graph.nodes())} 节点 / "
            f"{len(self.graph.edges())} 边）")


def create_page() -> QWidget:
    """页面工厂：返回蓝图演示页（``BlueprintDemoPage``）。"""
    return BlueprintDemoPage()
