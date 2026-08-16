# -*- coding: utf-8 -*-
"""连线绘制（BP_SPEC §1 edge_widget.py）。

本模块不创建 QWidget——边与临时线由画布在 ``paintEvent`` 中统一绘制，
这里提供「边部件」对象封装几何与视觉状态，便于命中检测与测试断言：

- ``bezier_path(p1, p2)``：蓝图风格贝塞尔曲线（曲率随水平距离变化）；
- ``EdgeWidget``：一条已建立连线的几何 / 绘制 / 命中（hover 加粗、
  点击选中、running 路径 flowing 虚线动画）；
- ``TempWire``：引脚拖拽中的临时线（磁吸到兼容引脚时高亮）。
"""

import math

from PySide6.QtCore import QObject, QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen

from ..theme import T
from .registry import pin_color

__all__ = ["bezier_path", "EdgeWidget", "TempWire"]


def bezier_path(p1: QPointF, p2: QPointF) -> QPainterPath:
    """生成两点间的蓝图风格三次贝塞尔曲线路径。

    控制点沿水平方向外推，外推距离随水平间距增大
    （``clamp(abs(dx) * 0.5, 40, 240)``），垂直堆叠时也有自然弧度。
    """
    dx = abs(p2.x() - p1.x())
    off = min(max(dx * 0.5, 40.0), 240.0)
    path = QPainterPath(p1)
    path.cubicTo(QPointF(p1.x() + off, p1.y()),
                 QPointF(p2.x() - off, p2.y()), p2)
    return path


def _path_points(path: QPainterPath, count: int = 24) -> list:
    """按参数均匀采样曲线上的点（命中检测用）。"""
    return [path.pointAtPercent(i / count) for i in range(count + 1)]


#: 边颜色解析缓存：键为 ``T()`` 解析后的色值字符串（主题切换后解析值
#: 变化，缓存自然失效）；容量封顶时整体清空，避免主题反复切换无界增长。
_COLOR_CACHE = {}
_COLOR_CACHE_MAX = 64
#: 边画笔缓存：键为 (颜色 RGBA, 宽度, 线型, dash 模式)。同上，颜色取
#: 实时解析结果，主题切换自然失效；容量封顶整体清空。
_PEN_CACHE = {}
_PEN_CACHE_MAX = 96


def _cached_color(token_value) -> QColor:
    """按 ``T()`` 解析值缓存 QColor 并返回**副本**（避免每帧 hex 解析）。

    返回副本允许调用方原地 ``setAlpha`` 等修改而不污染缓存条目。
    """
    key = str(token_value)
    color = _COLOR_CACHE.get(key)
    if color is None:
        color = QColor(key)
        if len(_COLOR_CACHE) >= _COLOR_CACHE_MAX:
            _COLOR_CACHE.clear()
        _COLOR_CACHE[key] = color
    return QColor(color)


def _cached_pen(color: QColor, width: float, style=Qt.SolidLine,
                dash=None) -> QPen:
    """按 (颜色, 宽度, 线型, dash) 缓存 QPen（复用：dash 相位由调用方
    在每次绘制前重设，共享画笔在单线程 GUI 下安全）。"""
    # Qt6 枚举（Qt.PenStyle）不可 int() 转换，取 .value 作缓存键
    style_v = getattr(style, "value", style)
    key = (color.rgba(), width, style_v,
           tuple(dash) if dash is not None else None)
    pen = _PEN_CACHE.get(key)
    if pen is None:
        pen = QPen(QColor.fromRgba(color.rgba()), width)
        pen.setStyle(style)
        pen.setCapStyle(Qt.RoundCap)
        if dash is not None:
            pen.setDashPattern(dash)
        if len(_PEN_CACHE) >= _PEN_CACHE_MAX:
            _PEN_CACHE.clear()
        _PEN_CACHE[key] = pen
    return pen


class EdgeWidget(QObject):
    """一条已建立连线的部件（几何 + 视觉状态，画布负责绘制）。

    参数:
        canvas: 所属 ``BlueprintCanvas``（用于查询引脚场景坐标）。
        edge: ``model.Edge`` 数据对象。

    状态属性：
        ``hovered`` / ``selected`` / ``flowing``（running 路径流动虚线）。

    性能要点：贝塞尔路径 / 包围盒 / 命中采样点 / 基础颜色全部按端点
    坐标缓存（端点变化时惰性重建），避免每帧 / 每次命中检测重建路径。
    """

    def __init__(self, canvas, edge, parent=None):
        super().__init__(parent or canvas)
        self.canvas = canvas
        self.edge = edge
        self.hovered = False
        self.selected = False
        self.flowing = False
        self._dash_offset = 0.0
        # 几何缓存（端点几何键未变时零重建；见 _ensure_path）
        self._geo_key = None
        self._path = None
        self._p1 = None
        self._p2 = None
        self._bounds = None
        self._samples = None
        # 基础颜色（边的引脚类型创建后不变，惰性取一次）
        self._base_color = None

    # -- 几何 ------------------------------------------------------------
    def source_pos(self) -> QPointF:
        """输出端引脚的场景坐标（取不到时回退节点左上角）。"""
        from .model import PinDirection
        return self.canvas.pin_scene_pos(self.edge.from_node, self.edge.from_pin,
                                         PinDirection.Output)

    def target_pos(self) -> QPointF:
        """输入端引脚的场景坐标。"""
        from .model import PinDirection
        return self.canvas.pin_scene_pos(self.edge.to_node, self.edge.to_pin,
                                         PinDirection.Input)

    def _ensure_path(self) -> None:
        """端点几何变化时重建路径并级联失效派生缓存。

        几何键 = 两端节点场景坐标 + 两端节点布局版本（引脚逻辑偏移随
        布局变化）。键未变时每帧仅付两次 dict 查找与元组比较，不再走
        ``pin_scene_pos`` → ``pin_logical_center`` 的完整解析链。
        """
        canvas = self.canvas
        src = canvas.graph.node(self.edge.from_node)
        tgt = canvas.graph.node(self.edge.to_node)
        sw = canvas._node_widgets.get(self.edge.from_node)
        tw = canvas._node_widgets.get(self.edge.to_node)
        key = (
            None if src is None else (
                src.pos.x(), src.pos.y(),
                sw._layout_rev if sw is not None else -1),
            None if tgt is None else (
                tgt.pos.x(), tgt.pos.y(),
                tw._layout_rev if tw is not None else -1),
        )
        if self._path is not None and key == self._geo_key:
            return
        self._geo_key = key
        self._p1, self._p2 = self.source_pos(), self.target_pos()
        self._path = bezier_path(self._p1, self._p2)
        self._bounds = None
        self._samples = None

    def path(self) -> QPainterPath:
        """当前贝塞尔曲线路径（场景坐标，缓存）。"""
        self._ensure_path()
        return self._path

    def bounding_rect(self) -> QRectF:
        """路径外接矩形（含描边余量，场景坐标，缓存）。"""
        self._ensure_path()
        if self._bounds is None:
            self._bounds = self._path.boundingRect().adjusted(-8, -8, 8, 8)
        return self._bounds

    def contains(self, scene_pt: QPointF, tol: float = 7.0) -> bool:
        """命中检测：场景点距曲线采样点的最小距离小于 ``tol`` 即命中。

        先做包围盒粗筛（含容差），通过后才比对缓存的曲线采样点。
        """
        coarse = self.bounding_rect().adjusted(-tol, -tol, tol, tol)
        if not coarse.contains(scene_pt):
            return False
        self._ensure_path()
        if self._samples is None:
            self._samples = _path_points(self._path)
        for pt in self._samples:
            if math.hypot(pt.x() - scene_pt.x(), pt.y() - scene_pt.y()) <= tol:
                return True
        return False

    def _color(self) -> QColor:
        """边的基础颜色（按源引脚类型，惰性缓存）。

        注意 ``_base_color`` 缓存的是主题相关色值：主题切换时画布调用
        ``invalidate_color()`` 失效重建（见 ``BlueprintCanvas._retheme``）。
        """
        if self._base_color is None:
            from .model import PinDirection
            node = self.canvas.graph.node(self.edge.from_node)
            pin = (node.pin(self.edge.from_pin, PinDirection.Output)
                   if node is not None else None)
            self._base_color = (_cached_color(pin_color(pin.data_type))
                                if pin is not None
                                else _cached_color(str(T("color.text.tertiary"))))
        return QColor(self._base_color)

    def invalidate_color(self) -> None:
        """失效缓存的边基础色（主题切换后由画布调用，下次绘制实时取色）。"""
        self._base_color = None

    # -- 状态 ------------------------------------------------------------
    def set_flowing(self, on: bool) -> None:
        """设置 / 取消流动虚线动画（由 ExecutionController.set_path 驱动）。

        状态翻转时请求画布局部重绘本边包围盒，确保流动虚线及时出现 /
        清除（画布定时器只负责推进相位，不负责状态翻转后的首帧）。
        """
        on = bool(on)
        if on == self.flowing:
            return
        self.flowing = on
        update = getattr(self.canvas, "_update_scene_rects", None)
        if update is not None:
            update([self.bounding_rect()])
        else:
            self.canvas.update()

    def advance_dash(self, step: float = 1.6) -> None:
        """推进流动虚线相位（画布定时器调用）。"""
        self._dash_offset -= step

    # -- 绘制 ------------------------------------------------------------
    def draw(self, p: QPainter) -> None:
        """在已做场景变换的画笔上绘制本条边（抗锯齿、主题实时取色）。

        画笔经 ``_cached_pen`` 按 (色值, 宽度, 线型) 复用：绘制期高频
        （画布每帧遍历全部边）避免每条边每次绘制重新解析令牌与构造
        QPen；主题切换后色值变化，缓存键随之变化自然失效。
        """
        path = self.path()
        if self.flowing:
            pen = _cached_pen(_cached_color(str(T("color.primary"))), 2.4,
                              Qt.DashLine, [3.0, 3.0])
            pen.setDashOffset(self._dash_offset)
            p.setPen(pen)
            p.setBrush(Qt.NoBrush)
            p.drawPath(path)
            return
        width = 2.0
        color = self._color()
        if self.selected:
            color = _cached_color(str(T("color.primary")))
            width = 2.8
        elif self.hovered:
            width = 3.2
        pen = _cached_pen(color, width)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        p.drawPath(path)


class TempWire(QObject):
    """引脚拖拽中的临时连线。

    参数:
        start: 起始引脚的场景坐标。
        data_type: 起始引脚数据类型（决定线条颜色）。

    ``magnet`` 置真时线条加粗高亮（磁吸到兼容引脚的反馈）。
    """

    def __init__(self, start: QPointF, data_type: str = "any", parent=None):
        super().__init__(parent)
        self.start = QPointF(start)
        self.end = QPointF(start)
        self.data_type = data_type or "any"
        self.magnet = False

    def set_end(self, scene_pt: QPointF) -> None:
        """更新临时线末端（场景坐标）。"""
        self.end = QPointF(scene_pt)

    def draw(self, p: QPainter) -> None:
        """绘制临时线（拖拽中虚线，磁吸时实线加粗）。"""
        path = bezier_path(self.start, self.end)
        color = QColor(pin_color(self.data_type))
        if self.magnet:
            pen = QPen(color, 3.0)
        else:
            pen = QPen(color, 2.0)
            pen.setStyle(Qt.DashLine)
            pen.setDashPattern([4.0, 3.0])
        pen.setCapStyle(Qt.RoundCap)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        p.drawPath(path)
        # 末端小圆点
        p.setPen(Qt.NoPen)
        p.setBrush(color)
        p.drawEllipse(self.end, 3.5, 3.5)
