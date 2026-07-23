# -*- coding: utf-8 -*-
"""运行指示（BP_SPEC §6）——ComfyUI 式执行状态展示。

``ExecutionController`` 提供**纯 UI** 的运行指示 API：把节点标记为
running / done / error、展示耗时徽标、高亮执行路径上的边（流动虚线）。

重要：本控制器**不执行任何业务逻辑**——不调度、不求值、不跑模型。
它只接收开发者（或模拟器，如 Demo 的 QTimer 顺序模拟）发来的状态
通知并驱动界面反馈。

用法::

    ex = canvas.execution()
    ex.set_path([n1.id, n2.id, n3.id])   # 可选：路径边流动虚线
    ex.start(n1.id)                       # running：脉冲描边 + 旋转圈
    ex.finish(n1.id, 123.0)               # done：success 描边 + "123 ms" 徽标
    ex.fail(n2.id, "模拟失败")            # error：danger 描边 + tooltip
    ex.reset()                            # 全部回 idle，清耗时与路径
"""

import time

from PySide6.QtCore import QObject, Signal

__all__ = ["ExecutionController"]


class ExecutionController(QObject):
    """节点图运行指示控制器（纯 UI，无业务执行）。

    信号:
        node_started(str): 某节点进入 running。
        node_finished(str, float): 某节点完成，参数为耗时毫秒。
        finished(): 所有曾 running 的节点均已结束（finish / fail）。

    由 ``BlueprintCanvas.execution()`` 取得（画布持有唯一实例）。
    """

    node_started = Signal(str)
    node_finished = Signal(str, float)
    finished = Signal()

    def __init__(self, canvas, parent=None):
        super().__init__(parent or canvas)
        self._canvas = canvas
        self._t0 = {}
        self._active = set()
        self._path_edges = []

    # -- 节点状态 ----------------------------------------------------------
    def start(self, node_id: str) -> None:
        """标记节点 running（脉冲描边 + 标题栏旋转圈），记录起始时刻。"""
        node = self._canvas.graph.node(node_id)
        if node is None:
            return
        self._t0[node_id] = time.perf_counter()
        self._active.add(node_id)
        node.set_status("running")
        self.node_started.emit(node_id)

    def finish(self, node_id: str, elapsed_ms=None) -> None:
        """标记节点 done：success 描边 + 耗时徽标。

        参数:
            node_id: 节点 id。
            elapsed_ms: 耗时毫秒；缺省自动计时（自 ``start`` 起算，
                未 ``start`` 过则为 0）。
        """
        node = self._canvas.graph.node(node_id)
        if node is None:
            return
        if elapsed_ms is None:
            t0 = self._t0.pop(node_id, None)
            elapsed_ms = ((time.perf_counter() - t0) * 1000.0
                          if t0 is not None else 0.0)
        self._active.discard(node_id)
        node.set_elapsed_ms(elapsed_ms)
        node.set_status("done")
        self.node_finished.emit(node_id, float(elapsed_ms))
        self._maybe_finished()

    def fail(self, node_id: str, message: str = "") -> None:
        """标记节点 error：danger 描边 + 错误图标，tooltip 显示 ``message``。"""
        node = self._canvas.graph.node(node_id)
        if node is None:
            return
        self._active.discard(node_id)
        self._t0.pop(node_id, None)
        node.error_message = str(message)
        node.set_status("error")
        self._maybe_finished()

    # -- 路径高亮 ----------------------------------------------------------
    def set_path(self, node_ids) -> None:
        """高亮执行路径上的边（流动虚线动画）。

        参数:
            node_ids: 按执行顺序排列的节点 id 序列；相邻两节点之间
                已存在的边将被标记为 flowing。
        """
        self._clear_path()
        graph = self._canvas.graph
        ids = list(node_ids)
        for a, b in zip(ids, ids[1:]):
            for edge in graph.edges():
                if edge.from_node == a and edge.to_node == b:
                    widget = self._canvas.edge_widget(edge.id)
                    if widget is not None:
                        widget.set_flowing(True)
                        self._path_edges.append(widget)
        if self._path_edges:
            self._canvas._ensure_flow_timer()

    def path_edge_ids(self) -> list:
        """当前被高亮的路径边 id 列表（测试 / 调试用）。"""
        return [w.edge.id for w in self._path_edges]

    def _clear_path(self) -> None:
        for widget in self._path_edges:
            widget.set_flowing(False)
        self._path_edges = []

    # -- 复位 --------------------------------------------------------------
    def reset(self) -> None:
        """全部节点回 idle、清耗时与错误信息、取消路径高亮。"""
        self._clear_path()
        self._active.clear()
        self._t0.clear()
        for node in self._canvas.graph.nodes():
            node.error_message = ""
            node.set_elapsed_ms(None)
            node.set_status("idle")

    # -- 内部 --------------------------------------------------------------
    def _maybe_finished(self) -> None:
        if not self._active:
            self.finished.emit()
