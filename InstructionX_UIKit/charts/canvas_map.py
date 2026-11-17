# -*- coding: utf-8 -*-
"""地图系列与支持全部既有系列的共享 Scene Graph 视口。"""

from PySide6.QtCanvasPainter import QCanvasPainter
from PySide6.QtCore import QRectF
from PySide6.QtGui import QColor

from ..theme import T
from ._utils import ON_FILL_WHITE
from .axes import chart_font
from .canvas_hierarchy import _CanvasHierarchyView, _stroke
from .canvas_network import CanvasNetworkChartViewport
from .canvas_paths import line_path
from .canvas_static import _text
from .components import MapSeriesRenderer

__all__ = ["CanvasMapView", "CanvasComponentsChartViewport"]


class CanvasMapView(_CanvasHierarchyView):
    def _sync_key(self, renderer):
        visual_maps = tuple(repr(getattr(component, "opt", None))
                            for component in renderer.chart.components
                            if callable(getattr(component, "map_color", None)))
        return super()._sync_key(renderer) + (
            id(renderer._polys), repr(renderer._rect),
            repr(renderer.chart._option_ref().get("geo")), visual_maps)

    def set_geometry(self, renderer, anim_t):
        self._reset(renderer, anim_t)
        self._area = QRectF(renderer._rect)
        self._source_polys = renderer._polys
        commands = []
        values = renderer._value_map()
        numeric = [value for value in values.values() if value is not None]
        vmin = min(numeric) if numeric else 0.0
        vmax = max(numeric) if numeric else 1.0
        visual_map = next((component for component in renderer.chart.components
                           if callable(getattr(component, "map_color", None))), None)
        font = chart_font(T("font.xs"))
        for name, polygon in renderer._polys:
            points = [polygon[index] for index in range(len(polygon))]
            path = line_path(points + [points[0]])
            color = renderer._fill_color(name, values, vmin, vmax, visual_map)
            self._areas.append((path, QColor(color)))
            self._outlines.append((path, QColor(T("color.border.strong")), 1.0))
            commands.append(("fill", path, QColor(color)))
            _stroke(commands, path, QColor(T("color.border.strong")))
            center = polygon.boundingRect().center()
            text_color = QColor(ON_FILL_WHITE) if color.lightness() < 130 \
                else QColor(T("color.text.primary"))
            _text(commands, name, QRectF(center.x() - 40, center.y() - 8, 80, 16),
                  font, text_color, QCanvasPainter.TextAlign.Center,
                  QCanvasPainter.TextBaseline.Middle)
        self._finish(renderer, commands)


class CanvasComponentsChartViewport(CanvasNetworkChartViewport):
    """支持地图及全部既有系列的共享 Scene Graph 视口。"""

    @staticmethod
    def _line_models(renderers):
        existing = [renderer for renderer in renderers
                    if type(renderer) is not MapSeriesRenderer]
        CanvasNetworkChartViewport._line_models(existing)
        return list(renderers)

    def _model_for(self, renderer, coord):
        if type(renderer) is MapSeriesRenderer:
            return CanvasMapView(renderer, coord)
        return super()._model_for(renderer, coord)
