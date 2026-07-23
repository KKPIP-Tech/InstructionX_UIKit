# -*- coding: utf-8 -*-
"""蓝图画布（BP_SPEC §5）。

``BlueprintCanvas`` 是节点图编辑器的主控件：

- 平移：中键拖拽 / 空格+左键拖拽 / 右键拖拽空白（右键抬起位移 <4px
  弹 ``NodeCreationMenu``）；
- 缩放：滚轮以光标为中心，0.25x–2.5x；
- 背景：主题感知点阵网格，间距随缩放自适应疏密；
- 选择：Ctrl+点选多选、空白左键橡皮筋框选（半透明）；
- Delete 删除选中节点（连带边）与选中边；
- 连线：引脚按下拖出贝塞尔临时线 → 磁吸高亮兼容引脚 → 松开经
  ``graph.add_edge`` 校验建边；拖到空白松开 → 创建菜单，创建后自动连接；
- 边：hover 加粗、点击选中、running 路径 flowing 虚线动画；
- 序列化：``to_dict`` / ``from_dict``（含节点位置与画布 zoom/offset）。

节点为真实子控件（``NodeWidget``），边与临时线由画布统一自绘。
"""

from PySide6.QtCore import QEvent, QPoint, QPointF, QRect, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QWidget

from ..theme import T, ThemeManager
from .edge_widget import EdgeWidget, TempWire
from .execution import ExecutionController
from .menu import NodeContextMenu, NodeCreationMenu
from .model import BlueprintGraph, BlueprintNode, PinDirection, types_compatible
from .node_widget import NodeWidget, PinHandle, safe_slot
from .registry import NodeRegistry

__all__ = ["BlueprintCanvas"]

#: 缩放范围
ZOOM_MIN, ZOOM_MAX = 0.25, 2.5
#: 磁吸半径（视图像素）
MAGNET_R = 22.0
#: 右键抬起判定为点击的位移阈值（px）
CLICK_TOL = 4.0


class BlueprintCanvas(QWidget):
    """蓝图画布控件。

    参数:
        graph: ``BlueprintGraph`` 数据图（节点 / 边变化自动同步到界面）。
        parent: 父控件。

    信号:
        node_moved(str, QPointF): 节点拖动结束（节点 id + 新场景坐标）。
        edge_created(object): 新边建立（``Edge``，含菜单自动连接产生的）。
        edge_removed(str): 边被移除（边 id）。
        selection_changed(list): 选中节点 id 列表变化。

    示例::

        graph = BlueprintGraph()
        canvas = BlueprintCanvas(graph)
        a = canvas.add_node_at("start", QPointF(60, 120))
        canvas.fit_view()
    """

    node_moved = Signal(str, QPointF)
    edge_created = Signal(object)
    edge_removed = Signal(str)
    selection_changed = Signal(list)

    def __init__(self, graph: BlueprintGraph, parent=None):
        super().__init__(parent)
        if graph is None:
            graph = BlueprintGraph()
        self.graph = graph
        self._zoom = 1.0
        self._offset = QPointF(0.0, 0.0)
        self._node_widgets = {}
        self._edge_widgets = {}
        self._selected_nodes = []
        self._selected_edges = []

        # 交互状态
        self._panning = False
        self._pan_start = QPointF()
        self._offset_start = QPointF()
        self._space_down = False
        self._rpress = None
        self._rpan = False
        self._drag = None          # (start_view, {node_id: start_scene_pos})
        self._drag_moved = False
        self._band = None          # (start_view, current_view)
        self._band_additive = False
        self._wire = None          # TempWire
        self._wire_src = None      # (node_id, Pin)
        self._wire_target = None   # (node_id, Pin)
        self._pending_wire = None  # 菜单创建后自动连接用

        self._flow_timer = QTimer(self)
        self._flow_timer.setInterval(50)
        self._flow_timer.timeout.connect(self._tick_flow)

        self._execution = ExecutionController(self)

        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setMinimumSize(320, 240)
        self.setAttribute(Qt.WA_OpaquePaintEvent, True)

        graph.node_added.connect(self._on_node_added)
        graph.node_removed.connect(self._on_node_removed)
        graph.edge_added.connect(self._on_edge_added)
        graph.edge_removed.connect(self._on_edge_removed)
        ThemeManager.instance().theme_changed.connect(
            safe_slot(lambda *_: self._retheme()))

        for node in graph.nodes():
            self._on_node_added(node)
        for edge in graph.edges():
            self._on_edge_added(edge)

    # ------------------------------------------------------------------
    # 公共 API
    # ------------------------------------------------------------------
    def add_node_at(self, type_name: str, scene_pos: QPointF) -> BlueprintNode:
        """经注册表创建节点并放置到场景坐标，返回 ``BlueprintNode``。

        示例::

            node = canvas.add_node_at("start", QPointF(80, 100))
        """
        node = NodeRegistry.instance().create(type_name)
        node.pos = QPointF(scene_pos)
        self.graph.add_node(node)
        return node

    def add_node(self, node: BlueprintNode, scene_pos: QPointF = None) -> BlueprintNode:
        """直接把既有 ``BlueprintNode`` 放入图（可选指定场景坐标）。"""
        if scene_pos is not None:
            node.pos = QPointF(scene_pos)
        self.graph.add_node(node)
        return node

    def set_zoom(self, z: float) -> None:
        """设置缩放（夹在 0.25–2.5），视图中心保持不变。"""
        z = max(ZOOM_MIN, min(ZOOM_MAX, float(z)))
        if abs(z - self._zoom) < 1e-6:
            return
        center_scene = self.view_to_scene(QPointF(self.width() / 2, self.height() / 2))
        self._zoom = z
        self._offset = QPointF(self.width() / 2, self.height() / 2) - center_scene * z
        self._update_view()

    def zoom(self) -> float:
        """当前缩放系数。"""
        return self._zoom

    def center_on(self, node_id: str) -> None:
        """把视图中心对准某节点（缩放不变）。"""
        node = self.graph.node(node_id)
        if node is None:
            return
        center = node.pos + QPointF(node.size.width() / 2, node.size.height() / 2)
        self._offset = QPointF(self.width() / 2, self.height() / 2) - center * self._zoom
        self._update_view()

    def fit_view(self) -> None:
        """适应视图：全部节点居中可见（含边距，缩放夹在合法范围）。"""
        nodes = self.graph.nodes()
        if not nodes:
            self._zoom = 1.0
            self._offset = QPointF(0.0, 0.0)
            self._update_view()
            return
        rect = None
        for node in nodes:
            r = QRectF(node.pos, node.size)
            rect = r if rect is None else rect.united(r)
        margin = 60.0
        rect = rect.adjusted(-margin, -margin, margin, margin)
        vw, vh = max(1, self.width()), max(1, self.height())
        z = min(vw / max(rect.width(), 1.0), vh / max(rect.height(), 1.0))
        self._zoom = max(ZOOM_MIN, min(ZOOM_MAX, z))
        self._offset = (QPointF(vw / 2, vh / 2)
                        - rect.center() * self._zoom)
        self._update_view()

    def execution(self) -> ExecutionController:
        """返回运行指示控制器（画布持有唯一实例）。"""
        return self._execution

    # -- 部件访问 ---------------------------------------------------------
    def node_widget(self, node_id: str):
        """按节点 id 取 ``NodeWidget``，不存在返回 ``None``。"""
        return self._node_widgets.get(node_id)

    def edge_widget(self, edge_id: str):
        """按边 id 取 ``EdgeWidget``，不存在返回 ``None``。"""
        return self._edge_widgets.get(edge_id)

    def pin_scene_pos(self, node_id: str, pin_id: str, direction=None) -> QPointF:
        """引脚圆心的场景坐标（找不到时回退节点左上角）。

        参数:
            direction: 可选 ``PinDirection``；输入 / 输出同名 id 时必须
                指定（``EdgeWidget`` 与拖线逻辑均显式传入）。
        """
        widget = self._node_widgets.get(node_id)
        node = self.graph.node(node_id)
        if widget is not None and node is not None:
            pin = node.pin(pin_id, direction)
            if pin is not None:
                return node.pos + widget.pin_logical_center(pin)
        return QPointF(node.pos) if node is not None else QPointF()

    def selected_nodes(self) -> list:
        """当前选中节点 id 列表。"""
        return list(self._selected_nodes)

    def selected_edges(self) -> list:
        """当前选中边 id 列表。"""
        return list(self._selected_edges)

    # -- 坐标换算 ---------------------------------------------------------
    def scene_to_view(self, pt: QPointF) -> QPointF:
        """场景坐标 → 视图（控件）坐标。"""
        return pt * self._zoom + self._offset

    def view_to_scene(self, pt: QPointF) -> QPointF:
        """视图（控件）坐标 → 场景坐标。"""
        return (QPointF(pt) - self._offset) / self._zoom

    # -- 序列化 -----------------------------------------------------------
    def to_dict(self) -> dict:
        """序列化整张图与视图状态：``{"graph": ..., "view": {...}}``。"""
        return {
            "graph": self.graph.to_dict(),
            "view": {
                "zoom": self._zoom,
                "offset": [self._offset.x(), self._offset.y()],
            },
        }

    def from_dict(self, data: dict) -> None:
        """从 ``to_dict`` 结果恢复：重建节点 / 边并还原 zoom 与 offset。"""
        self.clear_selection()
        self.graph.clear()
        gdata = data.get("graph", data)
        for nd in gdata.get("nodes", []):
            self.graph.add_node(BlueprintNode.from_dict(nd))
        from .model import Edge
        for ed in gdata.get("edges", []):
            edge = Edge.from_dict(ed)
            self.graph._edges[edge.id] = edge
            self.graph.edge_added.emit(edge)
        view = data.get("view", {})
        self._zoom = max(ZOOM_MIN, min(ZOOM_MAX, float(view.get("zoom", 1.0))))
        off = view.get("offset", [0.0, 0.0])
        self._offset = QPointF(float(off[0]), float(off[1]))
        self._update_view()

    # ------------------------------------------------------------------
    # 图信号 → 界面同步
    # ------------------------------------------------------------------
    def _on_node_added(self, node: BlueprintNode) -> None:
        widget = NodeWidget(node, self)
        widget.installEventFilter(self)
        for pin in node.inputs + node.outputs:
            handle = widget.pin_widget(pin.id, pin.direction)
            if handle is not None:
                handle.installEventFilter(self)
        if widget._body is not None:
            widget._body.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        widget._spinner.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        widget.apply_view(self.scene_to_view(node.pos), self._zoom)
        widget.show()
        self._node_widgets[node.id] = widget
        self.update()

    def _on_node_removed(self, node_id: str) -> None:
        widget = self._node_widgets.pop(node_id, None)
        if widget is not None:
            widget.removeEventFilter(self)
            widget.hide()
            widget.deleteLater()
        if node_id in self._selected_nodes:
            self._selected_nodes.remove(node_id)
            self.selection_changed.emit(list(self._selected_nodes))
        self.update()

    def _on_edge_added(self, edge) -> None:
        self._edge_widgets[edge.id] = EdgeWidget(self, edge, self)
        self.edge_created.emit(edge)
        self.update()

    def _on_edge_removed(self, edge_id: str) -> None:
        widget = self._edge_widgets.pop(edge_id, None)
        if widget is not None:
            widget.deleteLater()
        if edge_id in self._selected_edges:
            self._selected_edges.remove(edge_id)
        self.edge_removed.emit(edge_id)
        self.update()

    def _node_layout_changed(self, node_widget: NodeWidget) -> None:
        """节点尺寸变化（属性 / 引脚变化）后重新落位。"""
        node_widget.apply_view(self.scene_to_view(node_widget.node.pos), self._zoom)

    def _retheme(self) -> None:
        for widget in self._node_widgets.values():
            widget.refresh_theme()
        self._update_view()

    def _update_view(self) -> None:
        for node_id, widget in self._node_widgets.items():
            node = self.graph.node(node_id)
            if node is not None:
                widget.apply_view(self.scene_to_view(node.pos), self._zoom)
        self.update()

    # ------------------------------------------------------------------
    # 选择
    # ------------------------------------------------------------------
    def clear_selection(self) -> None:
        """清空节点与边的选中态。"""
        for nid in self._selected_nodes:
            w = self._node_widgets.get(nid)
            if w is not None:
                w.set_selected(False)
        for eid in self._selected_edges:
            ew = self._edge_widgets.get(eid)
            if ew is not None:
                ew.selected = False
        self._selected_nodes = []
        self._selected_edges = []
        self.selection_changed.emit([])
        self.update()

    def select_nodes(self, node_ids, additive: bool = False) -> None:
        """选中节点（``additive`` 为 Ctrl 语义：并入现有选择）。"""
        if not additive:
            self.clear_selection()
        changed = False
        for nid in node_ids:
            if nid in self._selected_nodes:
                continue
            w = self._node_widgets.get(nid)
            if w is None:
                continue
            self._selected_nodes.append(nid)
            w.set_selected(True)
            changed = True
        if changed:
            self.selection_changed.emit(list(self._selected_nodes))
        self.update()

    def toggle_node_selected(self, node_id: str) -> None:
        """Ctrl 点选：切换单个节点的选中态。"""
        if node_id in self._selected_nodes:
            self._selected_nodes.remove(node_id)
            w = self._node_widgets.get(node_id)
            if w is not None:
                w.set_selected(False)
        else:
            self._selected_nodes.append(node_id)
            w = self._node_widgets.get(node_id)
            if w is not None:
                w.set_selected(True)
        self.selection_changed.emit(list(self._selected_nodes))
        self.update()

    def _select_edge(self, edge_id: str, additive: bool) -> None:
        if not additive:
            self.clear_selection()
        if edge_id not in self._selected_edges:
            self._selected_edges.append(edge_id)
            ew = self._edge_widgets.get(edge_id)
            if ew is not None:
                ew.selected = True
        self.update()

    # ------------------------------------------------------------------
    # 事件过滤（节点控件 / 引脚热区）
    # ------------------------------------------------------------------
    def eventFilter(self, obj, event):
        etype = event.type()
        if etype not in (QEvent.MouseButtonPress, QEvent.MouseButtonRelease,
                         QEvent.MouseMove):
            return False
        if isinstance(obj, PinHandle):
            if etype == QEvent.MouseButtonPress and event.button() == Qt.LeftButton:
                self._begin_wire(obj)
                return True
            if self._wire is not None:
                if etype == QEvent.MouseMove:
                    self._update_wire(self.view_pos_of_event(obj, event))
                    return True
                if etype == QEvent.MouseButtonRelease and event.button() == Qt.LeftButton:
                    self._finish_wire(self.view_pos_of_event(obj, event))
                    return True
            return False
        if isinstance(obj, NodeWidget):
            if etype == QEvent.MouseButtonPress:
                view_pos = self.view_pos_of_event(obj, event)
                if event.button() == Qt.LeftButton:
                    self._node_press(obj, view_pos, event.modifiers())
                    return True
                if event.button() == Qt.RightButton:
                    self._rpress = (view_pos, obj)
                    self._rpan = False
                    self._pan_start = QPointF(view_pos)
                    self._offset_start = QPointF(self._offset)
                    return True
            if etype == QEvent.MouseMove:
                view_pos = self.view_pos_of_event(obj, event)
                if self._drag is not None:
                    self._drag_to(view_pos)
                    return True
                if self._rpress is not None and event.buttons() & Qt.RightButton:
                    if (QPointF(view_pos) - self._rpress[0]).manhattanLength() > CLICK_TOL:
                        self._rpan = True
                    return True
            if etype == QEvent.MouseButtonRelease:
                view_pos = self.view_pos_of_event(obj, event)
                if event.button() == Qt.LeftButton and self._drag is not None:
                    self._end_drag()
                    return True
                if event.button() == Qt.RightButton and self._rpress is not None:
                    target_node = self._rpress[1]
                    self._rpress = None
                    if not self._rpan and target_node is obj:
                        self._open_node_menu(obj, event.globalPosition().toPoint())
                    return True
        return False

    def view_pos_of_event(self, obj, event) -> QPointF:
        """把子控件上的事件坐标换算为画布视图坐标。"""
        return QPointF(obj.mapTo(self, event.position().toPoint()))

    # -- 节点拖动 ---------------------------------------------------------
    def _node_press(self, widget: NodeWidget, view_pos: QPointF, modifiers) -> None:
        nid = widget.node.id
        if modifiers & Qt.ControlModifier:
            self.toggle_node_selected(nid)
        elif nid not in self._selected_nodes:
            self.select_nodes([nid])
        if nid in self._selected_nodes:
            starts = {i: QPointF(self.graph.node(i).pos)
                      for i in self._selected_nodes if self.graph.node(i)}
            self._drag = (QPointF(view_pos), starts)
            self._drag_moved = False

    def _drag_to(self, view_pos: QPointF) -> None:
        start_view, starts = self._drag
        delta = (QPointF(view_pos) - start_view) / self._zoom
        if not self._drag_moved and delta.manhattanLength() * self._zoom < 2.0:
            return
        self._drag_moved = True
        for nid, start_pos in starts.items():
            node = self.graph.node(nid)
            if node is None:
                continue
            node.pos = start_pos + delta
            w = self._node_widgets.get(nid)
            if w is not None:
                w.apply_view(self.scene_to_view(node.pos), self._zoom)
        self.update()

    def _end_drag(self) -> None:
        start_view, starts = self._drag
        self._drag = None
        if self._drag_moved:
            for nid in starts:
                node = self.graph.node(nid)
                if node is not None:
                    self.node_moved.emit(nid, QPointF(node.pos))
        self._drag_moved = False

    # ------------------------------------------------------------------
    # 连线（引脚拖拽）
    # ------------------------------------------------------------------
    def _begin_wire(self, handle: PinHandle) -> None:
        pin = handle.pin
        node = handle.node_widget.node
        start = node.pos + handle.logical_center()
        self._wire = TempWire(start, pin.data_type,
                              from_output=pin.direction is PinDirection.Output,
                              parent=self)
        self._wire_src = (node.id, pin)
        self._wire_target = None
        self.update()

    def _update_wire(self, view_pos: QPointF) -> None:
        scene_pt = self.view_to_scene(view_pos)
        self._wire.set_end(scene_pt)
        self._wire_target = self._find_compatible_pin(scene_pt)
        self._wire.magnet = self._wire_target is not None
        if self._wire_target is not None:
            nid, pin = self._wire_target
            self._wire.set_end(self.pin_scene_pos(nid, pin.id, pin.direction))
        self.update()

    def _find_compatible_pin(self, scene_pt: QPointF):
        """在磁吸半径内找最近的兼容引脚（方向相反 + 类型兼容 + 非本节点）。"""
        src_nid, src_pin = self._wire_src
        want_dir = (PinDirection.Input if src_pin.direction is PinDirection.Output
                    else PinDirection.Output)
        radius = MAGNET_R / self._zoom
        best = None
        best_d = radius
        for nid, widget in self._node_widgets.items():
            if nid == src_nid:
                continue
            pins = widget.node.inputs if want_dir is PinDirection.Input else widget.node.outputs
            for pin in pins:
                if src_pin.direction is PinDirection.Output:
                    ok = types_compatible(src_pin.data_type, pin.data_type)
                else:
                    ok = types_compatible(pin.data_type, src_pin.data_type)
                if not ok:
                    continue
                c = self.pin_scene_pos(nid, pin.id, pin.direction)
                d = (c - scene_pt).manhattanLength()
                if d < best_d:
                    best = (nid, pin)
                    best_d = d
        return best

    def _finish_wire(self, view_pos: QPointF) -> None:
        src_nid, src_pin = self._wire_src
        target = self._find_compatible_pin(self.view_to_scene(view_pos))
        wire, self._wire, self._wire_src, self._wire_target = self._wire, None, None, None
        if wire is not None:
            wire.deleteLater()
        if target is not None:
            tgt_nid, tgt_pin = target
            if src_pin.direction is PinDirection.Output:
                self.graph.add_edge(src_nid, src_pin.id, tgt_nid, tgt_pin.id)
            else:
                self.graph.add_edge(tgt_nid, tgt_pin.id, src_nid, src_pin.id)
        else:
            # 拖到空白松开：弹创建菜单，创建后自动连接（UE5 行为）
            scene_pt = self.view_to_scene(view_pos)
            self._pending_wire = (src_nid, src_pin, scene_pt)
            menu = NodeCreationMenu(self)
            want_dir = (PinDirection.Input if src_pin.direction is PinDirection.Output
                        else PinDirection.Output)
            menu.type_chosen.connect(self._create_node_for_wire)
            menu.popup_at(self.mapToGlobal(QPoint(int(view_pos.x()), int(view_pos.y()))),
                          compatible=(want_dir, src_pin.data_type))
        self.update()

    def _create_node_for_wire(self, type_name: str) -> None:
        """拖线松开菜单回调：创建节点并自动连接对应引脚。"""
        pending = self._pending_wire
        self._pending_wire = None
        if pending is None:
            return
        src_nid, src_pin, scene_pt = pending
        node = self.add_node_at(type_name, scene_pt)
        want_dir = (PinDirection.Input if src_pin.direction is PinDirection.Output
                    else PinDirection.Output)
        pins = node.inputs if want_dir is PinDirection.Input else node.outputs
        for pin in pins:
            if src_pin.direction is PinDirection.Output:
                ok = types_compatible(src_pin.data_type, pin.data_type)
            else:
                ok = types_compatible(pin.data_type, src_pin.data_type)
            if not ok:
                continue
            if src_pin.direction is PinDirection.Output:
                self.graph.add_edge(src_nid, src_pin.id, node.id, pin.id)
            else:
                self.graph.add_edge(node.id, pin.id, src_nid, src_pin.id)
            break

    # ------------------------------------------------------------------
    # 画布鼠标事件（空白区）
    # ------------------------------------------------------------------
    def mousePressEvent(self, event) -> None:
        pos = QPointF(event.position())
        if event.button() == Qt.MiddleButton:
            self._start_pan(pos)
            return
        if event.button() == Qt.LeftButton:
            if self._space_down:
                self._start_pan(pos)
                return
            hit = self._edge_at(self.view_to_scene(pos))
            if hit is not None:
                self._select_edge(hit, bool(event.modifiers() & Qt.ControlModifier))
                return
            self._band = (pos, pos)
            self._band_additive = bool(event.modifiers() & Qt.ControlModifier)
            if not self._band_additive:
                self.clear_selection()
            self.update()
            return
        if event.button() == Qt.RightButton:
            self._rpress = (pos, None)
            self._rpan = False
            self._pan_start = QPointF(pos)
            self._offset_start = QPointF(self._offset)
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        pos = QPointF(event.position())
        if self._wire is not None:
            # 拖线中：某些平台事件直接投递到画布而非引脚热区
            self._update_wire(pos)
            return
        if self._panning:
            self._offset = self._offset_start + (pos - self._pan_start)
            self._update_view()
            return
        if self._rpress is not None and event.buttons() & Qt.RightButton:
            start, _target = self._rpress
            if (pos - start).manhattanLength() > CLICK_TOL:
                self._rpan = True
                self.setCursor(Qt.ClosedHandCursor)
            if self._rpan:
                self._offset = self._offset_start + (pos - self._pan_start)
                self._update_view()
            return
        if self._band is not None:
            self._band = (self._band[0], pos)
            self.update()
            return
        self._update_edge_hover(self.view_to_scene(pos))
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        pos = QPointF(event.position())
        if event.button() == Qt.LeftButton and self._wire is not None:
            self._finish_wire(pos)
            return
        if event.button() == Qt.MiddleButton and self._panning:
            self._panning = False
            self.unsetCursor()
            return
        if event.button() == Qt.LeftButton:
            if self._panning:
                self._panning = False
                self.unsetCursor()
                return
            if self._band is not None:
                self._finish_band()
                return
        if event.button() == Qt.RightButton and self._rpress is not None:
            was_pan = self._rpan
            self._rpress = None
            self._rpan = False
            if was_pan:
                self._panning = False
                self.unsetCursor()
            else:
                scene_pt = self.view_to_scene(pos)
                menu = NodeCreationMenu(self)
                menu.type_chosen.connect(
                    lambda t, sp=scene_pt: self.add_node_at(t, sp))
                menu.popup_at(event.globalPosition().toPoint())
            return
        super().mouseReleaseEvent(event)

    def wheelEvent(self, event) -> None:
        delta = event.angleDelta().y()
        if delta == 0:
            return
        factor = 1.15 ** (delta / 120.0)
        new_zoom = max(ZOOM_MIN, min(ZOOM_MAX, self._zoom * factor))
        if abs(new_zoom - self._zoom) < 1e-6:
            return
        cursor = QPointF(event.position())
        self._offset = cursor - (cursor - self._offset) * (new_zoom / self._zoom)
        self._zoom = new_zoom
        self._update_view()
        event.accept()

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key_Space and not event.isAutoRepeat():
            self._space_down = True
            return
        if event.key() in (Qt.Key_Delete, Qt.Key_Backspace):
            self.delete_selection()
            return
        super().keyPressEvent(event)

    def keyReleaseEvent(self, event) -> None:
        if event.key() == Qt.Key_Space and not event.isAutoRepeat():
            self._space_down = False
            if self._panning:
                self._panning = False
                self.unsetCursor()
            return
        super().keyReleaseEvent(event)

    # -- 平移 / 框选 -------------------------------------------------------
    def _start_pan(self, view_pos: QPointF) -> None:
        self._panning = True
        self._pan_start = QPointF(view_pos)
        self._offset_start = QPointF(self._offset)
        self.setCursor(Qt.ClosedHandCursor)

    def _finish_band(self) -> None:
        start, end = self._band
        self._band = None
        rect = QRectF(self.view_to_scene(start), self.view_to_scene(end)).normalized()
        ids = []
        if rect.width() > 2 / self._zoom or rect.height() > 2 / self._zoom:
            for nid, widget in self._node_widgets.items():
                node = widget.node
                if rect.intersects(QRectF(node.pos, node.size)):
                    ids.append(nid)
        if ids:
            self.select_nodes(ids, additive=self._band_additive)
        self.update()

    def delete_selection(self) -> None:
        """删除选中的边与节点（节点连带其全部边），发相应信号。"""
        for eid in list(self._selected_edges):
            self.graph.remove_edge(eid)
        for nid in list(self._selected_nodes):
            self.graph.remove_node(nid)
        self._selected_edges = []
        self._selected_nodes = []
        self.selection_changed.emit([])
        self.update()

    # -- 边 hover / 命中 ---------------------------------------------------
    def _edge_at(self, scene_pt: QPointF):
        for eid, ew in self._edge_widgets.items():
            if ew.contains(scene_pt, tol=7.0 / self._zoom + 3.0):
                return eid
        return None

    def _update_edge_hover(self, scene_pt: QPointF) -> None:
        hit = self._edge_at(scene_pt)
        changed = False
        for eid, ew in self._edge_widgets.items():
            want = eid == hit
            if ew.hovered != want:
                ew.hovered = want
                changed = True
        if changed:
            self.update()

    # -- 节点右键菜单 ------------------------------------------------------
    def _open_node_menu(self, widget: NodeWidget, global_pos: QPoint) -> None:
        nid = widget.node.id
        menu = NodeContextMenu(nid, self)
        menu.duplicate_requested.connect(self._duplicate_node)
        menu.disconnect_requested.connect(
            lambda i: [self.graph.remove_edge(e.id)
                       for e in self.graph.edges_of(i)])
        menu.delete_requested.connect(lambda i: self.graph.remove_node(i))
        menu.exec(global_pos)

    def _duplicate_node(self, node_id: str) -> None:
        """默认复制实现：同类型新节点 + 拷贝属性，位置错开 24px。"""
        node = self.graph.node(node_id)
        if node is None:
            return
        data = node.to_dict()
        data.pop("id", None)
        copy = BlueprintNode.from_dict(data)
        copy.pos = node.pos + QPointF(24.0, 24.0)
        self.graph.add_node(copy)
        self.select_nodes([copy.id])

    # ------------------------------------------------------------------
    # 流动动画
    # ------------------------------------------------------------------
    def _ensure_flow_timer(self) -> None:
        if not self._flow_timer.isActive():
            self._flow_timer.start()

    def _tick_flow(self) -> None:
        any_flowing = False
        for ew in self._edge_widgets.values():
            if ew.flowing:
                ew.advance_dash()
                any_flowing = True
        if not any_flowing:
            self._flow_timer.stop()
        self.update()

    # ------------------------------------------------------------------
    # 绘制
    # ------------------------------------------------------------------
    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(self.rect(), QColor(str(T("color.bg.base"))))
        self._draw_grid(p)
        p.save()
        p.translate(self._offset)
        p.scale(self._zoom, self._zoom)
        for ew in self._edge_widgets.values():
            ew.draw(p)
        if self._wire is not None:
            self._wire.draw(p)
            if self._wire_target is not None:
                nid, pin = self._wire_target
                c = self.pin_scene_pos(nid, pin.id, pin.direction)
                pen = QPen(QColor(str(T("color.primary"))), 2.0)
                p.setPen(pen)
                p.setBrush(Qt.NoBrush)
                p.drawEllipse(c, 9.0, 9.0)
        p.restore()
        if self._band is not None:
            rect = QRectF(self._band[0], self._band[1]).normalized()
            fill = QColor(str(T("color.primary")))
            fill.setAlpha(28)
            border = QColor(str(T("color.primary")))
            border.setAlpha(140)
            p.setPen(QPen(border, 1.2))
            p.setBrush(fill)
            p.drawRect(rect)
        p.end()

    def _draw_grid(self, p: QPainter) -> None:
        """点阵网格：间距随缩放自适应（屏幕间距保持在 18–72px 之间）。"""
        step = 24.0
        while step * self._zoom < 18.0:
            step *= 2.0
        while step * self._zoom > 72.0:
            step /= 2.0
        color = QColor(str(T("color.border")))
        p.setPen(Qt.NoPen)
        p.setBrush(color)
        w, h = self.width(), self.height()
        x0 = self._offset.x() % (step * self._zoom)
        y0 = self._offset.y() % (step * self._zoom)
        r = 1.3
        y = y0
        while y <= h:
            x = x0
            while x <= w:
                p.drawEllipse(QPointF(x, y), r, r)
                x += step * self._zoom
            y += step * self._zoom
