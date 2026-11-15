# -*- coding: utf-8 -*-
"""树图与桑基图的 Canvas 原生几何和共享视口。"""

from PySide6.QtCanvasPainter import QCanvasPainter, QCanvasPath
from PySide6.QtCore import QPointF, QRectF
from PySide6.QtGui import QColor, QFontMetricsF, QPainterPath

from ..theme import T
from ._utils import to_float as _to_float, with_alpha
from .canvas_blocks import CanvasBlocksChartViewport
from .canvas_hierarchy import _CanvasHierarchyView, _stroke
from .canvas_paths import line_path, path_from_qpainter
from .canvas_static import _text
from .series_hierarchy import SankeySeriesRenderer, TreeSeriesRenderer, _label_font

__all__ = ["CanvasTreeView", "CanvasSankeyView", "CanvasRelationsChartViewport"]


class CanvasTreeView(_CanvasHierarchyView):
    def set_geometry(self, renderer, anim_t):
        self._reset(renderer, anim_t)
        self._source_nodes = renderer._nodes
        self._source_edges = renderer._edges
        self._edge_paths = []
        self._dots = []
        commands = []
        orient = str(renderer.opt.get("orient") or "LR").upper()
        edge = str(renderer.opt.get("edge") or "polyline")
        color = QColor(T("color.border.strong"))
        for p0, p1 in renderer._edges:
            q1 = QPointF(p0.x() + (p1.x() - p0.x()) * anim_t,
                         p0.y() + (p1.y() - p0.y()) * anim_t)
            if edge == "curve":
                source = QPainterPath(p0)
                if orient == "TB":
                    middle = (p0.y() + q1.y()) / 2
                    source.cubicTo(QPointF(p0.x(), middle), QPointF(q1.x(), middle), q1)
                else:
                    middle = (p0.x() + q1.x()) / 2
                    source.cubicTo(QPointF(middle, p0.y()), QPointF(middle, q1.y()), q1)
                path = path_from_qpainter(source)
                self._edge_paths.append(path)
                self._outlines.append((path, QColor(color), 1.2))
                _stroke(commands, path, color, 1.2)
            else:
                middle = QPointF(q1.x(), p0.y()) if orient == "TB" \
                    else QPointF(p0.x(), q1.y())
                self._edge_paths.append(line_path([p0, middle, q1]))
                for start, end in ((p0, middle), (middle, q1)):
                    path = line_path([start, end])
                    self._outlines.append((path, QColor(color), 1.2))
                    _stroke(commands, path, color, 1.2)
        option = dict(renderer.opt.get("label") or {})
        show = bool(option.get("show", True))
        font = _label_font(option.get("fontSize"))
        fm = QFontMetricsF(font)
        size = _to_float(renderer.opt.get("symbolSize"), 8.0)
        for node, point in renderer._nodes:
            path = QCanvasPath(2)
            path.ellipse(QRectF(point.x() - size / 2, point.y() - size / 2, size, size))
            brush = QColor(node.color or renderer.color())
            self._dots.append(path)
            commands.append(("fill", path, brush))
            _stroke(commands, path, QColor(T("color.bg.elevated")), 1.5)
            if not show or not node.name:
                continue
            width = fm.horizontalAdvance(node.name)
            if orient == "TB":
                _text(commands, node.name,
                      QRectF(point.x() - width / 2, point.y() + size / 2 + 2,
                             width + 4, fm.height()),
                      font, QColor(T("color.text.primary")), QCanvasPainter.TextAlign.Center,
                      QCanvasPainter.TextBaseline.Top)
            elif not node.children:
                _text(commands, node.name,
                      QRectF(point.x() + size / 2 + 3, point.y() - fm.height() / 2,
                             width + 4, fm.height()),
                      font, QColor(T("color.text.primary")), QCanvasPainter.TextAlign.Left,
                      QCanvasPainter.TextBaseline.Middle)
            else:
                _text(commands, node.name,
                      QRectF(point.x() - width - size / 2 - 3,
                             point.y() - fm.height() / 2, width + 4, fm.height()),
                      font, QColor(T("color.text.primary")), QCanvasPainter.TextAlign.Right,
                      QCanvasPainter.TextBaseline.Middle)
        self._finish(renderer, commands)


class CanvasSankeyView(_CanvasHierarchyView):
    def set_geometry(self, renderer, anim_t):
        self._reset(renderer, anim_t)
        self._source_nodes = renderer._nodes
        self._source_bands = renderer._bands
        self._bands = []
        self._nodes = []
        commands = []
        for band in renderer._bands:
            path = path_from_qpainter(band["path"])
            color = with_alpha(band["color"], int(70 * anim_t))
            self._bands.append((path, color))
            self._areas.append((path, QColor(color)))
            commands.append(("fill", path, color))
        option = dict(renderer.opt.get("label") or {})
        show = bool(option.get("show", True))
        font = _label_font(option.get("fontSize"))
        fm = QFontMetricsF(font)
        max_depth = max((node["depth"] for node in renderer._nodes), default=0)
        for node in renderer._nodes:
            rect = node["rect"]
            path = QCanvasPath(4)
            path.rect(QRectF(rect))
            color = with_alpha(node["color"], int(255 * anim_t))
            self._nodes.append((path, color))
            self._areas.append((path, QColor(color)))
            commands.append(("fill", path, color))
            if not show:
                continue
            width = fm.horizontalAdvance(node["name"])
            if node["depth"] >= max_depth:
                _text(commands, node["name"],
                      QRectF(rect.left() - width - 6, rect.center().y() - fm.height() / 2,
                             width + 4, fm.height()),
                      font, QColor(T("color.text.primary")), QCanvasPainter.TextAlign.Right,
                      QCanvasPainter.TextBaseline.Middle)
            else:
                _text(commands, node["name"],
                      QRectF(rect.right() + 4, rect.center().y() - fm.height() / 2,
                             width + 4, fm.height()),
                      font, QColor(T("color.text.primary")), QCanvasPainter.TextAlign.Left,
                      QCanvasPainter.TextBaseline.Middle)
        self._finish(renderer, commands)


class CanvasRelationsChartViewport(CanvasBlocksChartViewport):
    """支持树图、桑基图及既有系列的共享 Scene Graph 视口。"""

    @staticmethod
    def _line_models(renderers):
        added = (TreeSeriesRenderer, SankeySeriesRenderer)
        existing = [renderer for renderer in renderers if type(renderer) not in added]
        CanvasBlocksChartViewport._line_models(existing)
        return list(renderers)

    def _model_for(self, renderer, coord):
        if type(renderer) is TreeSeriesRenderer:
            return CanvasTreeView(renderer, coord)
        if type(renderer) is SankeySeriesRenderer:
            return CanvasSankeyView(renderer, coord)
        return super()._model_for(renderer, coord)
