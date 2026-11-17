# -*- coding: utf-8 -*-
"""Canvas 图表视口的能力检查与生产工厂。"""

from .canvas_map import CanvasComponentsChartViewport
from .canvas_visuals import component_scene_key

__all__ = ["create_canvas_viewport"]


def create_canvas_viewport(chart, parent=None):
    CanvasComponentsChartViewport._line_models(chart.series_renderers)
    component_scene_key(chart)
    return CanvasComponentsChartViewport(chart, parent=chart if parent is None else parent)
