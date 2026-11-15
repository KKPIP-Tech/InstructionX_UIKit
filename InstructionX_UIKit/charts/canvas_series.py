# -*- coding: utf-8 -*-
"""柱状系列的 Canvas 原生几何与共享视口扩展。"""

from PySide6.QtCanvasPainter import QCanvasPath
from PySide6.QtCore import QRectF
from PySide6.QtGui import QColor, QTransform

from ..theme import T
from .axes import GridCoord
from .canvas_item_viewport import CanvasItemLineChartViewport
from .series_cartesian import BarSeriesRenderer, LineSeriesRenderer

__all__ = ["CanvasBarView", "CanvasBarChartViewport"]


class CanvasBarView:
    def __init__(self, renderer, coord=None):
        self._renderer = renderer
        self._coord = coord
        self._plot = QRectF(coord.plot) if isinstance(coord, GridCoord) else None
        self._points = []
        self._screen_geometry = None
        self._paths = []
        self._areas = []
        self._dashes = []
        self._color = QColor(renderer.color())
        self._symbol_fill = QColor(T("color.bg.elevated"))
        self._symbol_setting = False
        self._symbol_size = 6.0
        self._line_width = 2.0
        self._anim_t = 1.0
        self._visible = renderer.visible
        self._source_bars = None
        self.set_geometry(renderer, self._anim_t)

    def set_geometry(self, renderer, anim_t):
        coord = renderer.chart.coord_for(renderer.opt)
        self._coord = coord
        self._plot = QRectF(coord.plot) if isinstance(coord, GridCoord) else None
        self._source_bars = renderer._bars
        self._anim_t = float(anim_t)
        self._color = QColor(renderer.color())
        self._areas = []
        if not isinstance(coord, GridCoord):
            return
        value_axis = coord.x_axis if renderer._horizontal else coord.y_axis
        for bar in self._source_bars:
            value = renderer._animated_value(bar, anim_t)
            v1 = bar["v0"] + value
            width = bar["w"]
            if renderer._horizontal:
                pa = value_axis.map(bar["v0"], coord.plot.left(), coord.plot.right())
                pb = value_axis.map(v1, coord.plot.left(), coord.plot.right())
                rect = QRectF(min(pa, pb), bar["center"] - width / 2,
                              abs(pb - pa), width)
            else:
                pa = value_axis.map(bar["v0"], coord.plot.bottom(), coord.plot.top())
                pb = value_axis.map(v1, coord.plot.bottom(), coord.plot.top())
                rect = QRectF(bar["center"] - width / 2, min(pa, pb),
                              width, abs(pb - pa))
            if rect.width() <= 0 or rect.height() <= 0:
                continue
            radius = min(bar["radius"], rect.width() / 2, rect.height() / 2)
            path = QCanvasPath(4)
            if radius > 0.5:
                path.roundRect(rect, radius)
            else:
                path.rect(rect)
            self._areas.append((path, QColor(self._color)))

    def _draw(self, painter, scale=None):
        if not self._visible:
            return
        painter.save()
        try:
            painter.setTransform(QTransform())
            painter.scale(1.0 if scale is None else scale)
            if self._plot is not None:
                painter.setClipRect(self._plot)
            else:
                painter.resetClipping()
            painter.setAntialias(1.0)
            for path, brush in self._areas:
                painter.setFillStyle(brush)
                painter.fill(path)
        finally:
            painter.restore()

    def close(self):
        pass

    def deleteLater(self):  # noqa: N802
        pass


class CanvasBarChartViewport(CanvasItemLineChartViewport):
    """支持 line 与 bar 的共享 Scene Graph 视口。"""

    @staticmethod
    def _line_models(renderers):
        if any(type(renderer) not in (LineSeriesRenderer, BarSeriesRenderer)
               for renderer in renderers):
            raise NotImplementedError("CanvasBarChartViewport 当前仅支持 line 和 bar 系列")
        return list(renderers)

    def _model_for(self, renderer, coord):
        if type(renderer) is BarSeriesRenderer:
            return CanvasBarView(renderer, coord)
        return super()._model_for(renderer, coord)

    def _sync_series_model(self, model):
        if not isinstance(model, CanvasBarView):
            super()._sync_series_model(model)
            return
        renderer = model._renderer
        model._visible = renderer.visible
        if model._source_bars is not renderer._bars \
                or model._anim_t != self._chart.anim.t \
                or model._color != renderer.color():
            model.set_geometry(renderer, self._chart.anim.t)
