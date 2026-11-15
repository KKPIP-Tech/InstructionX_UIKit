# -*- coding: utf-8 -*-
"""关系图与线图的 Canvas 原生几何和共享视口。"""

from PySide6.QtCanvasPainter import QCanvasPainter, QCanvasPath
from PySide6.QtCore import QPointF, QRectF
from PySide6.QtGui import QColor, QFontMetricsF

from ..theme import T
from ._utils import ON_FILL_WHITE, to_float as _to_float, with_alpha
from .canvas_hierarchy import _CanvasHierarchyView, _stroke
from .canvas_paths import line_path, path_from_qpainter
from .canvas_relations import CanvasRelationsChartViewport
from .canvas_static import _text
from .series_hierarchy import GraphSeriesRenderer, LinesSeriesRenderer, _label_font

__all__ = ["CanvasGraphView", "CanvasLinesView", "CanvasNetworkChartViewport"]


def _ellipse(point, radius):
    path = QCanvasPath(2)
    path.ellipse(QRectF(point.x() - radius, point.y() - radius, radius * 2, radius * 2))
    return path


class CanvasGraphView(_CanvasHierarchyView):
    def set_geometry(self, renderer, anim_t):
        self._reset(renderer, anim_t)
        self._source_nodes = renderer._nodes
        self._source_edges = renderer._edges
        self._dots = []
        self._edge_paths = []
        commands = []
        if not renderer._nodes:
            self._animated_positions = []
            self._finish(renderer, commands)
            return
        center = QPointF(sum(node["pos"].x() for node in renderer._nodes) / len(renderer._nodes),
                         sum(node["pos"].y() for node in renderer._nodes) / len(renderer._nodes))
        self._animated_positions = [QPointF(
            center.x() + (node["pos"].x() - center.x()) * anim_t,
            center.y() + (node["pos"].y() - center.y()) * anim_t)
            for node in renderer._nodes]
        edge_color = with_alpha(QColor(T("color.border.strong")), 160)
        for source, target in renderer._edges:
            if not (0 <= source < len(self._animated_positions)
                    and 0 <= target < len(self._animated_positions)):
                continue
            path = line_path([self._animated_positions[source], self._animated_positions[target]])
            self._edge_paths.append(path)
            self._outlines.append((path, QColor(edge_color), 1.2))
            _stroke(commands, path, edge_color, 1.2)
        option = dict(renderer.opt.get("label") or {})
        show = bool(option.get("show", True))
        font = _label_font(option.get("fontSize"))
        fm = QFontMetricsF(font)
        for node, point in zip(renderer._nodes, self._animated_positions):
            radius = node["size"] / 2
            path = _ellipse(point, radius)
            self._dots.append(path)
            commands.append(("fill", path, QColor(node["color"])))
            _stroke(commands, path, QColor(T("color.bg.elevated")), 1.5)
            if show and node["name"]:
                width = fm.horizontalAdvance(node["name"])
                _text(commands, node["name"],
                      QRectF(point.x() - width / 2, point.y() + radius + 2,
                             width + 4, fm.height()),
                      font, QColor(T("color.text.primary")), QCanvasPainter.TextAlign.Center,
                      QCanvasPainter.TextBaseline.Top)
        self._finish(renderer, commands)


class CanvasLinesView(_CanvasHierarchyView):
    def _sync_key(self, renderer):
        return super()._sync_key(renderer) + (id(renderer._segments), renderer._phase)

    def set_geometry(self, renderer, anim_t):
        self._reset(renderer, anim_t)
        self._source_segments = renderer._segments
        self._phase = renderer._phase
        self._segment_paths = []
        self._trails = []
        commands = []
        line_style = dict(renderer.opt.get("lineStyle") or {})
        width = _to_float(line_style.get("width"), 2.0)
        color = QColor(str(line_style.get("color"))) if line_style.get("color") \
            else renderer.color()
        curveness = _to_float(line_style.get("curveness"), 0.0)
        line_color = with_alpha(color, int(220 * anim_t))
        for segment in renderer._segments:
            path = path_from_qpainter(renderer._curve_path(
                segment["p0"], segment["p1"], curveness))
            self._segment_paths.append(path)
            self._outlines.append((path, QColor(line_color), width))
            _stroke(commands, path, line_color, width, cap=QCanvasPainter.LineCap.Round)
        endpoint_color = with_alpha(color, int(200 * anim_t))
        for segment in renderer._segments:
            for point in (segment["p0"], segment["p1"]):
                path = _ellipse(point, 2.5)
                self._areas.append((path, QColor(endpoint_color)))
                commands.append(("fill", path, QColor(endpoint_color)))
        effect = renderer._effect_opt()
        if bool(effect.get("show", False)) and anim_t > 0.5:
            size = _to_float(effect.get("symbolSize"), 6.0)
            dot_color = QColor(str(effect.get("color"))) if effect.get("color") \
                else QColor(ON_FILL_WHITE)
            count = len(renderer._segments)
            for index, segment in enumerate(renderer._segments):
                phase = (self._phase + index / max(1, count)) % 1.0
                point = renderer._curve_path(segment["p0"], segment["p1"],
                                             curveness).pointAtPercent(phase)
                outer = _ellipse(point, size)
                inner = _ellipse(point, size / 2)
                self._trails.append((outer, inner))
                commands.append(("fill", outer, with_alpha(dot_color, 60)))
                commands.append(("fill", inner, QColor(dot_color)))
        self._finish(renderer, commands)


class CanvasNetworkChartViewport(CanvasRelationsChartViewport):
    """支持 graph、lines 及全部既有系列的共享 Scene Graph 视口。"""

    @staticmethod
    def _line_models(renderers):
        added = (GraphSeriesRenderer, LinesSeriesRenderer)
        existing = [renderer for renderer in renderers if type(renderer) not in added]
        CanvasRelationsChartViewport._line_models(existing)
        return list(renderers)

    def _model_for(self, renderer, coord):
        if type(renderer) is GraphSeriesRenderer:
            return CanvasGraphView(renderer, coord)
        if type(renderer) is LinesSeriesRenderer:
            return CanvasLinesView(renderer, coord)
        return super()._model_for(renderer, coord)
