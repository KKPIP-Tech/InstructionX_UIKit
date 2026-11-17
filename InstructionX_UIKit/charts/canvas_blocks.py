# -*- coding: utf-8 -*-
"""漏斗、旭日图与矩形树图的 Canvas 原生几何。"""

import math

from PySide6.QtCanvasPainter import QCanvasPainter, QCanvasPath
from PySide6.QtCore import QPointF, QRectF
from PySide6.QtGui import QColor, QFontMetricsF

from ..theme import T
from .._draw import annular_sector
from ._utils import ON_FILL_WHITE, clamp as _clamp, to_float as _to_float, with_alpha
from .axes import format_value
from .canvas_hierarchy import CanvasHierarchyChartViewport, _CanvasHierarchyView, _stroke
from .canvas_paths import line_path, path_from_qpainter
from .canvas_static import _text
from .series_hierarchy import (
    FunnelSeriesRenderer,
    SunburstSeriesRenderer,
    TreemapSeriesRenderer,
    _label_font,
)

__all__ = ["CanvasFunnelView", "CanvasSunburstView", "CanvasTreemapView",
           "CanvasBlocksChartViewport"]


def _polygon_path(polygon, close=True):
    points = [polygon[index] for index in range(len(polygon))]
    if close and points:
        points.append(points[0])
    return line_path(points)


class CanvasFunnelView(_CanvasHierarchyView):
    def set_geometry(self, renderer, anim_t):
        self._reset(renderer, anim_t)
        self._source_layers = renderer._layers
        commands = []
        option = dict(renderer.opt.get("label") or {})
        show = bool(option.get("show", True))
        inside = str(option.get("position") or "outer") == "inside"
        font = _label_font(option.get("fontSize"))
        fm = QFontMetricsF(font)
        total = sum(layer["value"] for layer in renderer._layers) or 1.0
        count = len(renderer._layers)
        for index, layer in enumerate(renderer._layers):
            local_t = _clamp(anim_t * count - index, 0.0, 1.0)
            if local_t <= 0:
                continue
            polygon = layer["poly"]
            if local_t < 1.0:
                center = (layer["left"] + layer["right"]) / 2
                polygon = [QPointF(polygon[k].x() * local_t + center * (1 - local_t),
                                   polygon[k].y()) for k in range(4)]
            path = _polygon_path(polygon)
            self._areas.append((path, QColor(layer["color"])))
            self._outlines.append((path, QColor(T("color.bg.base")), 1.2))
            commands.append(("fill", path, QColor(layer["color"])))
            _stroke(commands, path, QColor(T("color.bg.base")), 1.2)
            if not show or local_t < 0.6:
                continue
            name = layer["name"] or format_value(layer["value"])
            value_text = format_value(layer["value"])
            if inside:
                _text(commands, f"{name} {value_text}",
                      QRectF(layer["left"], layer["cy"] - fm.height() / 2,
                             layer["right"] - layer["left"], fm.height()),
                      font, QColor(ON_FILL_WHITE), QCanvasPainter.TextAlign.Center,
                      QCanvasPainter.TextBaseline.Middle)
            else:
                _text(commands, name,
                      QRectF(0, layer["cy"] - fm.height() / 2,
                             layer["left"] - 8, fm.height()),
                      font, QColor(T("color.text.primary")), QCanvasPainter.TextAlign.Right,
                      QCanvasPainter.TextBaseline.Middle)
                percent = format_value(round(layer["value"] / total * 100, 1)) + "%"
                _text(commands, f"{value_text} ({percent})",
                      QRectF(layer["right"] + 8, layer["cy"] - fm.height() / 2,
                             110, fm.height()),
                      font, QColor(T("color.text.primary")), QCanvasPainter.TextAlign.Left,
                      QCanvasPainter.TextBaseline.Middle)
        self._finish(renderer, commands)


class CanvasSunburstView(_CanvasHierarchyView):
    def set_geometry(self, renderer, anim_t):
        self._reset(renderer, anim_t)
        self._source_nodes = renderer._nodes
        commands = []
        for node in renderer._nodes:
            span = (node.a1 - node.a0) * anim_t
            if span <= 0.05:
                continue
            r0, r1 = renderer._ring(node.level)
            outer = QRectF(renderer._center.x() - r1, renderer._center.y() - r1,
                           r1 * 2, r1 * 2)
            inner = QRectF(renderer._center.x() - r0, renderer._center.y() - r0,
                           r0 * 2, r0 * 2)
            path = path_from_qpainter(annular_sector(
                outer, inner if r0 > 0.5 else None, 90.0 - node.a0, -span))
            self._areas.append((path, QColor(node.color)))
            self._outlines.append((path, QColor(T("color.bg.base")), 1.0))
            commands.append(("fill", path, QColor(node.color)))
            _stroke(commands, path, QColor(T("color.bg.base")))
        option = dict(renderer.opt.get("label") or {})
        if bool(option.get("show", True)):
            min_angle = _to_float(option.get("minAngle"), 8.0)
            font = _label_font(option.get("fontSize"))
            fm = QFontMetricsF(font)
            for node in renderer._nodes:
                if not node.name:
                    continue
                span = (node.a1 - node.a0) * anim_t
                if span < min_angle:
                    continue
                r0, r1 = renderer._ring(node.level)
                middle = node.a0 + span / 2
                radius = (r0 + r1) / 2
                point = renderer._pt(middle, radius)
                degrees = middle % 360.0
                flip = 90.0 < degrees < 270.0
                width = fm.horizontalAdvance(node.name)
                band_width = math.radians(span) * radius
                if width > max(band_width - 4, 12) and span < 30:
                    continue
                commands.append(("save",))
                commands.append(("translate", QPointF(point)))
                commands.append(("rotate", degrees + (180.0 if flip else 0.0)))
                _text(commands, node.name,
                      QRectF(-width / 2, -fm.height() / 2, width + 2, fm.height()),
                      font, QColor(ON_FILL_WHITE), QCanvasPainter.TextAlign.Center,
                      QCanvasPainter.TextBaseline.Middle)
                commands.append(("restore",))
        self._finish(renderer, commands)


class CanvasTreemapView(_CanvasHierarchyView):
    def set_geometry(self, renderer, anim_t):
        self._reset(renderer, anim_t)
        self._source_nodes = renderer._nodes
        commands = []
        option = dict(renderer.opt.get("label") or {})
        show = bool(option.get("show", True))
        font = _label_font(option.get("fontSize"))
        fm = QFontMetricsF(font)
        for node in renderer._nodes:
            rect = node.rect
            if rect.width() <= 0.5 or rect.height() <= 0.5:
                continue
            color = with_alpha(node.color, 60 + 195 * anim_t)
            path = QCanvasPath(4)
            path.rect(QRectF(rect))
            self._areas.append((path, QColor(color)))
            self._outlines.append((path, QColor(T("color.bg.base")), 1.0))
            commands.append(("fill", path, color))
            _stroke(commands, path, QColor(T("color.bg.base")))
            if not show or not node.name:
                continue
            if rect.width() < fm.horizontalAdvance(node.name) * 0.9 \
                    or rect.height() < fm.height() + 2:
                continue
            text_color = QColor(ON_FILL_WHITE) if node.depth == 0 \
                else with_alpha(QColor(ON_FILL_WHITE), 230)
            _text(commands, node.name,
                  QRectF(rect.left() + 3, rect.top() + 1, rect.width() - 6, fm.height()),
                  font, text_color, QCanvasPainter.TextAlign.Left,
                  QCanvasPainter.TextBaseline.Middle)
        if renderer._crumb:
            _text(commands, renderer._crumb,
                  QRectF(6, renderer._crumb_y, max(20.0, renderer.chart.width() - 12),
                         fm.height() + 2),
                  font, QColor(T("color.text.secondary")), QCanvasPainter.TextAlign.Left,
                  QCanvasPainter.TextBaseline.Middle)
        self._finish(renderer, commands)


class CanvasBlocksChartViewport(CanvasHierarchyChartViewport):
    """支持漏斗、旭日图、矩形树图及既有系列的共享视口。"""

    @staticmethod
    def _line_models(renderers):
        added = (FunnelSeriesRenderer, SunburstSeriesRenderer, TreemapSeriesRenderer)
        existing = [renderer for renderer in renderers if type(renderer) not in added]
        CanvasHierarchyChartViewport._line_models(existing)
        return list(renderers)

    def _model_for(self, renderer, coord):
        if type(renderer) is FunnelSeriesRenderer:
            return CanvasFunnelView(renderer, coord)
        if type(renderer) is SunburstSeriesRenderer:
            return CanvasSunburstView(renderer, coord)
        if type(renderer) is TreemapSeriesRenderer:
            return CanvasTreemapView(renderer, coord)
        return super()._model_for(renderer, coord)
