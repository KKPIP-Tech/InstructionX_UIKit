# -*- coding: utf-8 -*-
"""柱状系列的 Canvas 原生几何与共享视口扩展。"""

import math

from PySide6.QtCanvasPainter import QCanvasPainter, QCanvasPath
from PySide6.QtCore import QPointF, QRectF
from PySide6.QtGui import QColor, QFontMetricsF, QPainterPath, QTransform

from ..theme import T
from .axes import CalendarCoord, GridCoord, chart_font, format_value
from .canvas_item_viewport import CanvasItemLineChartViewport
from .canvas_paths import line_path, path_from_qpainter
from .canvas_static import _text
from .series_cartesian import (
    BarSeriesRenderer,
    BoxplotSeriesRenderer,
    CandlestickSeriesRenderer,
    EffectScatterSeriesRenderer,
    HeatmapSeriesRenderer,
    LineSeriesRenderer,
    ParallelSeriesRenderer,
    PictorialBarSeriesRenderer,
    ScatterSeriesRenderer,
    ThemeRiverSeriesRenderer,
    _lerp,
    _smooth_path,
    _to_float,
    _with_alpha,
)

__all__ = ["CanvasBarView", "CanvasBarChartViewport",
           "CanvasScatterView", "CanvasScatterChartViewport",
           "CanvasFinancialChartViewport", "CanvasPictorialChartViewport",
           "CanvasHeatmapView", "CanvasHeatmapChartViewport",
           "CanvasFlowChartViewport"]


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
            for path, color, width in getattr(self, "_outlines", ()):
                painter.setStrokeStyle(color)
                painter.setLineWidth(width)
                painter.stroke(path)
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


class CanvasScatterView:
    def __init__(self, renderer, coord=None):
        self._renderer = renderer
        self._coord = coord
        self._plot = QRectF(coord.plot) if isinstance(coord, GridCoord) else None
        self._points = []
        self._screen_geometry = None
        self._paths = []
        self._areas = []
        self._outlines = []
        self._ripples = []
        self._dashes = []
        self._color = QColor(renderer.color())
        self._symbol_fill = QColor(T("color.bg.elevated"))
        self._symbol_setting = False
        self._symbol_size = 6.0
        self._line_width = 1.0
        self._anim_t = 1.0
        self._visible = renderer.visible
        self._source_dots = None
        self._aggregated = False
        self._phase = 0.0
        self._scale = 2.6
        self.set_geometry(renderer, self._anim_t)

    def set_geometry(self, renderer, anim_t):
        coord = renderer.chart.coord_for(renderer.opt)
        self._coord = coord
        self._plot = QRectF(coord.plot) if isinstance(coord, GridCoord) else None
        self._source_dots = renderer._dots
        self._anim_t = float(anim_t)
        self._color = QColor(renderer.color())
        self._aggregated = renderer._aggregated
        self._phase = getattr(renderer, "_phase", 0.0)
        self._scale = getattr(renderer, "_scale", 2.6)
        self._areas = []
        self._outlines = []
        self._ripples = []
        scale = max(0.0, anim_t)
        for dot in self._source_dots:
            point = dot["pt"]
            if self._aggregated:
                side = 2.0 * scale
                if side <= 0:
                    continue
                alpha = 90 + min(145, 12 * int(math.log2(max(1, dot["count"]))))
                path = QCanvasPath(4)
                path.rect(QRectF(point.x() - side / 2, point.y() - side / 2, side, side))
                self._areas.append((path, _with_alpha(self._color, alpha)))
                continue
            radius = dot["r"] * scale
            if radius <= 0:
                continue
            path = QCanvasPath(4)
            path.ellipse(QRectF(point.x() - radius, point.y() - radius,
                                radius * 2, radius * 2))
            self._areas.append((path, _with_alpha(self._color, 190)))
            self._outlines.append((path, _with_alpha(self._color, 230), 1.0))
        if isinstance(renderer, EffectScatterSeriesRenderer):
            for dot in self._source_dots:
                radius = max(dot["r"], 3.0) * (1.0 + self._phase * (self._scale - 1.0))
                point = dot["pt"]
                path = QCanvasPath(4)
                path.ellipse(QRectF(point.x() - radius, point.y() - radius,
                                    radius * 2, radius * 2))
                alpha = 140 * (1.0 - self._phase)
                self._ripples.append((path, _with_alpha(self._color, alpha), 1.6))

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
            for path, color, width in self._outlines:
                painter.setStrokeStyle(color)
                painter.setLineWidth(width)
                painter.stroke(path)
            for path, color, width in self._ripples:
                painter.setStrokeStyle(color)
                painter.setLineWidth(width)
                painter.stroke(path)
        finally:
            painter.restore()

    def close(self):
        pass

    def deleteLater(self):  # noqa: N802
        pass


class CanvasScatterChartViewport(CanvasBarChartViewport):
    """支持 line、bar、scatter 与 effectScatter 的共享视口。"""

    @staticmethod
    def _line_models(renderers):
        supported = (LineSeriesRenderer, BarSeriesRenderer,
                     ScatterSeriesRenderer, EffectScatterSeriesRenderer)
        if any(type(renderer) not in supported for renderer in renderers):
            raise NotImplementedError("CanvasScatterChartViewport 当前仅支持 line、bar、scatter、effectScatter")
        return list(renderers)

    def _model_for(self, renderer, coord):
        if isinstance(renderer, ScatterSeriesRenderer):
            return CanvasScatterView(renderer, coord)
        return super()._model_for(renderer, coord)

    def _sync_series_model(self, model):
        if not isinstance(model, CanvasScatterView):
            super()._sync_series_model(model)
            return
        renderer = model._renderer
        model._visible = renderer.visible
        if model._source_dots is not renderer._dots \
                or model._anim_t != self._chart.anim.t \
                or model._color != renderer.color() \
                or model._aggregated != renderer._aggregated \
                or model._phase != getattr(renderer, "_phase", 0.0) \
                or model._scale != getattr(renderer, "_scale", 2.6):
            model.set_geometry(renderer, self._chart.anim.t)


class _FinancialViewBase(CanvasBarView):
    pass


class CanvasCandlestickView(_FinancialViewBase):
    def set_geometry(self, renderer, anim_t):
        coord = renderer.chart.coord_for(renderer.opt)
        self._coord = coord
        self._plot = QRectF(coord.plot) if isinstance(coord, GridCoord) else None
        self._source_items = renderer._items
        self._anim_t = float(anim_t)
        self._color = QColor(renderer.color())
        self._up_color = renderer._up_color()
        self._down_color = renderer._down_color()
        self._areas = []
        self._outlines = []
        if not isinstance(coord, GridCoord):
            return
        axis = coord.y_axis
        for item in self._source_items:
            if item["prev"] is not None and anim_t < 1.0:
                open_, close, low, high = (
                    _lerp(item["prev"][index], value, anim_t)
                    for index, value in enumerate((item["open"], item["close"],
                                                   item["low"], item["high"])))
            elif anim_t < 1.0:
                open_ = item["open"]
                close = _lerp(open_, item["close"], anim_t)
                low = _lerp(open_, item["low"], anim_t)
                high = _lerp(open_, item["high"], anim_t)
            else:
                open_, close, low, high = item["open"], item["close"], item["low"], item["high"]
            yo = axis.map(open_, coord.plot.bottom(), coord.plot.top())
            yc = axis.map(close, coord.plot.bottom(), coord.plot.top())
            yl = axis.map(low, coord.plot.bottom(), coord.plot.top())
            yh = axis.map(high, coord.plot.bottom(), coord.plot.top())
            color = self._up_color if close >= open_ else self._down_color
            cx, width = item["cx"], item["w"]
            wick = QCanvasPath(2)
            wick.moveTo(cx, yh)
            wick.lineTo(cx, yl)
            self._outlines.append((wick, QColor(color), 1.2))
            body = QCanvasPath(4)
            body.rect(QRectF(cx - width / 2, min(yo, yc), width,
                             max(1.0, abs(yc - yo))))
            self._areas.append((body, QColor(color)))


class CanvasBoxplotView(_FinancialViewBase):
    def set_geometry(self, renderer, anim_t):
        coord = renderer.chart.coord_for(renderer.opt)
        self._coord = coord
        self._plot = QRectF(coord.plot) if isinstance(coord, GridCoord) else None
        self._source_items = renderer._items
        self._anim_t = float(anim_t)
        self._color = QColor(renderer.color())
        self._areas = []
        self._outlines = []
        if not isinstance(coord, GridCoord):
            return
        axis = coord.y_axis
        for item in self._source_items:
            vmin, q1, median, q3, vmax = item["vals"]
            middle = (q1 + q3) / 2
            if anim_t < 1.0:
                vmin = _lerp(middle, vmin, anim_t)
                vmax = _lerp(middle, vmax, anim_t)
                q1 = _lerp(middle, q1, anim_t)
                q3 = _lerp(middle, q3, anim_t)
                median = _lerp(middle, median, anim_t)
            y_min = axis.map(vmin, coord.plot.bottom(), coord.plot.top())
            y_q1 = axis.map(q1, coord.plot.bottom(), coord.plot.top())
            y_med = axis.map(median, coord.plot.bottom(), coord.plot.top())
            y_q3 = axis.map(q3, coord.plot.bottom(), coord.plot.top())
            y_max = axis.map(vmax, coord.plot.bottom(), coord.plot.top())
            cx, width = item["cx"], item["w"]
            for start, end in (
                    ((cx, y_max), (cx, y_min)),
                    ((cx - width / 4, y_min), (cx + width / 4, y_min)),
                    ((cx - width / 4, y_max), (cx + width / 4, y_max))):
                path = QCanvasPath(2)
                path.moveTo(*start)
                path.lineTo(*end)
                self._outlines.append((path, QColor(self._color), 1.2))
            rect = QRectF(cx - width / 2, min(y_q1, y_q3), width,
                          max(1.0, abs(y_q3 - y_q1)))
            box = QCanvasPath(4)
            box.rect(rect)
            self._areas.append((box, _with_alpha(self._color, 60)))
            self._outlines.append((box, QColor(self._color), 1.4))
            median_path = QCanvasPath(2)
            median_path.moveTo(cx - width / 2, y_med)
            median_path.lineTo(cx + width / 2, y_med)
            self._outlines.append((median_path, QColor(self._color), 2.0))


class CanvasFinancialChartViewport(CanvasScatterChartViewport):
    """支持 line、bar、scatter、candlestick 与 boxplot 的共享视口。"""

    @staticmethod
    def _line_models(renderers):
        supported = (LineSeriesRenderer, BarSeriesRenderer, ScatterSeriesRenderer,
                     EffectScatterSeriesRenderer, CandlestickSeriesRenderer,
                     BoxplotSeriesRenderer)
        if any(type(renderer) not in supported for renderer in renderers):
            raise NotImplementedError("CanvasFinancialChartViewport 当前仅支持 line、bar、scatter、candlestick、boxplot")
        return list(renderers)

    def _model_for(self, renderer, coord):
        if type(renderer) is CandlestickSeriesRenderer:
            return CanvasCandlestickView(renderer, coord)
        if type(renderer) is BoxplotSeriesRenderer:
            return CanvasBoxplotView(renderer, coord)
        return super()._model_for(renderer, coord)

    def _sync_series_model(self, model):
        if not isinstance(model, _FinancialViewBase):
            super()._sync_series_model(model)
            return
        renderer = model._renderer
        model._visible = renderer.visible
        changed = model._source_items is not renderer._items \
            or model._anim_t != self._chart.anim.t or model._color != renderer.color()
        if isinstance(model, CanvasCandlestickView):
            changed = changed or model._up_color != renderer._up_color() \
                or model._down_color != renderer._down_color()
        if changed:
            model.set_geometry(renderer, self._chart.anim.t)


def _pictorial_path(kind, cx, cy, width, height):
    radius = min(width, height) / 2
    path = QCanvasPath(6)
    if kind == "circle":
        path.ellipse(QRectF(cx - width / 2, cy - height / 2, width, height))
    elif kind == "pin":
        path.ellipse(QRectF(cx - radius, cy - height * 0.12 - radius,
                            radius * 2, radius * 2))
        path.moveTo(cx - radius * 0.55, cy + height * 0.12)
        path.lineTo(cx, cy + height * 0.52)
        path.lineTo(cx + radius * 0.55, cy + height * 0.12)
        path.closePath()
    else:
        path.roundRect(QRectF(cx - width / 2, cy - height / 2, width, height), 2.0)
    return path


class CanvasPictorialView(CanvasBarView):
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
        sw, sh = renderer._symbol_size()
        repeat = renderer.opt.get("symbolRepeat", False)
        kind = str(renderer.opt.get("symbol") or "rect")
        for bar in self._source_bars:
            value = renderer._animated_value(bar, anim_t)
            v1 = bar["v0"] + value
            if renderer._horizontal:
                pa = value_axis.map(bar["v0"], coord.plot.left(), coord.plot.right())
                pb = value_axis.map(v1, coord.plot.left(), coord.plot.right())
                along, cross = sw, sh
            else:
                pa = value_axis.map(bar["v0"], coord.plot.bottom(), coord.plot.top())
                pb = value_axis.map(v1, coord.plot.bottom(), coord.plot.top())
                along, cross = sh, sw
            direction = 1.0 if pb >= pa else -1.0
            total = abs(pb - pa)
            if total <= 0:
                continue
            if repeat is True:
                count = max(1, int(total // max(1.0, along)))
                offsets = [(index + 0.5) * along for index in range(count)]
                offsets = [offset for offset in offsets if offset <= total] or [total / 2]
            elif repeat:
                count = max(1, int(_to_float(repeat, 1)))
                offsets = [(index + 0.5) * total / count for index in range(count)]
            else:
                offsets = [max(along / 2, total - along / 2)]
            for offset in offsets:
                position = pa + direction * offset
                if renderer._horizontal:
                    path = _pictorial_path(kind, position, bar["center"], along, cross)
                else:
                    path = _pictorial_path(kind, bar["center"], position, cross, along)
                self._areas.append((path, QColor(self._color)))


class CanvasPictorialChartViewport(CanvasFinancialChartViewport):
    """支持象形柱及既有系列的共享 Scene Graph 视口。"""

    @staticmethod
    def _line_models(renderers):
        supported = (LineSeriesRenderer, BarSeriesRenderer, ScatterSeriesRenderer,
                     EffectScatterSeriesRenderer, CandlestickSeriesRenderer,
                     BoxplotSeriesRenderer, PictorialBarSeriesRenderer)
        if any(type(renderer) not in supported for renderer in renderers):
            raise NotImplementedError("CanvasPictorialChartViewport 当前不支持该系列类型")
        return list(renderers)

    def _model_for(self, renderer, coord):
        if type(renderer) is PictorialBarSeriesRenderer:
            return CanvasPictorialView(renderer, coord)
        return super()._model_for(renderer, coord)


class CanvasHeatmapView(CanvasBarView):
    def set_geometry(self, renderer, anim_t):
        coord = renderer.chart.coord_for(renderer.opt)
        self._coord = coord
        self._plot = QRectF(coord.plot) if isinstance(coord, GridCoord) else None
        self._calendar = isinstance(coord, CalendarCoord)
        self._source_cells = renderer._cells
        self._anim_t = float(anim_t)
        self._color = QColor(renderer.color())
        self._cell_colors = tuple(cell["color"].getRgb() for cell in self._source_cells)
        self._areas = []
        for cell in self._source_cells:
            path = QCanvasPath(4)
            if self._calendar:
                path.roundRect(QRectF(cell["rect"]), 2.0)
            else:
                path.rect(QRectF(cell["rect"]))
            color = QColor(cell["color"])
            color.setAlpha(int(255 * max(0.15, anim_t)))
            self._areas.append((path, color))


class CanvasHeatmapChartViewport(CanvasPictorialChartViewport):
    """支持直角与日历热力图、visualMap 的共享 Scene Graph 视口。"""

    @staticmethod
    def _line_models(renderers):
        supported = (LineSeriesRenderer, BarSeriesRenderer, ScatterSeriesRenderer,
                     EffectScatterSeriesRenderer, CandlestickSeriesRenderer,
                     BoxplotSeriesRenderer, PictorialBarSeriesRenderer,
                     HeatmapSeriesRenderer)
        if any(type(renderer) not in supported for renderer in renderers):
            raise NotImplementedError("CanvasHeatmapChartViewport 当前不支持该系列类型")
        return list(renderers)

    def _model_for(self, renderer, coord):
        if type(renderer) is HeatmapSeriesRenderer:
            return CanvasHeatmapView(renderer, coord)
        return super()._model_for(renderer, coord)

    def _sync_series_model(self, model):
        if not isinstance(model, CanvasHeatmapView):
            super()._sync_series_model(model)
            return
        renderer = model._renderer
        model._visible = renderer.visible
        coord = renderer.chart.coord_for(renderer.opt)
        calendar = isinstance(coord, CalendarCoord)
        model._plot = QRectF(coord.plot) if isinstance(coord, GridCoord) else None
        colors = tuple(cell["color"].getRgb() for cell in renderer._cells)
        if model._source_cells is not renderer._cells \
                or model._anim_t != self._chart.anim.t \
                or model._color != renderer.color() \
                or model._calendar != calendar \
                or model._cell_colors != colors:
            model.set_geometry(renderer, self._chart.anim.t)


class _CanvasLabeledView(CanvasBarView):
    def _reset_geometry(self, renderer, anim_t):
        self._coord = renderer.chart.coord_for(renderer.opt)
        self._plot = None
        self._area = QRectF(renderer._area)
        self._anim_t = float(anim_t)
        self._color = QColor(renderer.color())
        self._palette = tuple(QColor(color).getRgb() for color in renderer.chart.palette())
        self._theme_key = (T("color.bg.base"), T("color.text.secondary"),
                           T("color.border.strong"))
        self._background = None
        self._background_color = QColor(T("color.bg.base"))
        self._areas = []
        self._outlines = []
        self._paths = []
        self._label_commands = []

    def _draw(self, painter, scale=None):
        if not self._visible:
            return
        painter.save()
        try:
            painter.resetClipping()
            painter.setTransform(QTransform())
            painter.scale(1.0 if scale is None else scale)
            painter.setAntialias(1.0)
            if self._background is not None:
                painter.setFillStyle(self._background_color)
                painter.fillRect(self._background)
            painter.setLineCap(QCanvasPainter.LineCap.Round)
            painter.setLineJoin(QCanvasPainter.LineJoin.Round)
            for path, brush in self._areas:
                painter.setFillStyle(brush)
                painter.fill(path)
            for path, color, width in self._outlines:
                painter.setStrokeStyle(color)
                painter.setLineWidth(width)
                painter.stroke(path)
            for _kind, text, rect, font, color, align, baseline in self._label_commands:
                painter.setFont(font)
                painter.setFillStyle(color)
                painter.setTextAlign(align)
                painter.setTextBaseline(baseline)
                painter.fillText(text, rect)
        finally:
            painter.restore()


class CanvasParallelView(_CanvasLabeledView):
    def set_geometry(self, renderer, anim_t):
        self._reset_geometry(renderer, anim_t)
        self._source_axes = renderer._axes
        self._source_rows = renderer._rows
        if not renderer._axes:
            return
        self._background = QRectF(self._area.left() - 40, self._area.top() - 34,
                                  self._area.width() + 80, self._area.height() + 60)
        reveal = max(0.0, min(1.0, anim_t))
        color = _with_alpha(self._color, 110)
        for row in self._source_rows:
            points = row["pts"]
            if len(points) < 2:
                continue
            if reveal < 1.0:
                upto = reveal * (len(points) - 1)
                segment = []
                for index, point in enumerate(points):
                    if index <= int(upto):
                        segment.append(point)
                    elif index == int(upto) + 1:
                        fraction = upto - int(upto)
                        segment.append(QPointF(
                            _lerp(points[index - 1].x(), point.x(), fraction),
                            _lerp(points[index - 1].y(), point.y(), fraction)))
                if len(segment) >= 2:
                    self._outlines.append((line_path(segment), QColor(color), 1.6))
            else:
                self._outlines.append((line_path(points), QColor(color), 1.6))
        font = chart_font(T("font.xs"))
        fm = QFontMetricsF(font)
        axis_color = QColor(T("color.border.strong"))
        text_color = QColor(T("color.text.secondary"))
        for axis in self._source_axes:
            x = axis["x"]
            self._outlines.append((line_path([QPointF(x, self._area.top()),
                                              QPointF(x, self._area.bottom())]),
                                   QColor(axis_color), 1.0))
            _text(self._label_commands, axis["name"],
                  QRectF(x - 50, self._area.top() - fm.height() - 6, 100, fm.height()),
                  font, text_color, QCanvasPainter.TextAlign.Center,
                  QCanvasPainter.TextBaseline.Bottom)
            _text(self._label_commands, format_value(axis["vmax"]),
                  QRectF(x - 50, self._area.top() + 2, 100, fm.height()),
                  font, text_color, QCanvasPainter.TextAlign.Center,
                  QCanvasPainter.TextBaseline.Top)
            _text(self._label_commands, format_value(axis["vmin"]),
                  QRectF(x - 50, self._area.bottom() - fm.height() - 2, 100, fm.height()),
                  font, text_color, QCanvasPainter.TextAlign.Center,
                  QCanvasPainter.TextBaseline.Bottom)


class CanvasThemeRiverView(_CanvasLabeledView):
    def set_geometry(self, renderer, anim_t):
        self._reset_geometry(renderer, anim_t)
        self._source_streams = renderer._streams
        self._source_times = renderer._times
        if not self._source_streams:
            return
        self._background = QRectF(self._area.left() - 24, self._area.top() - 20,
                                  self._area.width() + 48, self._area.height() + 50)
        palette = renderer.chart.palette()
        grow = max(0.0, min(1.0, anim_t))
        for stream in self._source_streams:
            color = QColor(palette[stream["color_idx"] % len(palette)])
            top, bottom = [], []
            for a, b in zip(stream["top"], stream["bot"]):
                middle = (a.y() + b.y()) / 2
                top.append(QPointF(a.x(), middle + (a.y() - middle) * grow))
                bottom.append(QPointF(b.x(), middle + (b.y() - middle) * grow))
            if len(top) < 2:
                continue
            source = _smooth_path(top, 0.5)
            bottom_path = _smooth_path(bottom, 0.5)
            elements = [bottom_path.elementAt(index)
                        for index in range(bottom_path.elementCount())]
            reverse = QPainterPath()
            reverse.moveTo(elements[-1].x, elements[-1].y)
            index = len(elements) - 1
            while index >= 3:
                reverse.cubicTo(QPointF(elements[index - 1].x, elements[index - 1].y),
                                QPointF(elements[index - 2].x, elements[index - 2].y),
                                QPointF(elements[index - 3].x, elements[index - 3].y))
                index -= 3
            source.connectPath(reverse)
            source.closeSubpath()
            path = path_from_qpainter(source)
            self._areas.append((path, _with_alpha(color, 150)))
            self._outlines.append((path, _with_alpha(color, 200), 1.0))
        font = chart_font(T("font.xs"))
        fm = QFontMetricsF(font)
        color = QColor(T("color.text.secondary"))
        count = len(self._source_times)
        for tick in range(min(5, count)):
            index = round(tick * (count - 1) / max(1, min(5, count) - 1))
            x = self._area.left() + self._area.width() * (index + 0.5) / count
            _text(self._label_commands, self._source_times[index],
                  QRectF(x - 60, self._area.bottom() + 8, 120, fm.height()),
                  font, color, QCanvasPainter.TextAlign.Center, QCanvasPainter.TextBaseline.Top)


class CanvasFlowChartViewport(CanvasHeatmapChartViewport):
    """支持平行坐标、主题河及既有系列的共享 Scene Graph 视口。"""

    @staticmethod
    def _line_models(renderers):
        supported = (LineSeriesRenderer, BarSeriesRenderer, ScatterSeriesRenderer,
                     EffectScatterSeriesRenderer, CandlestickSeriesRenderer,
                     BoxplotSeriesRenderer, PictorialBarSeriesRenderer,
                     HeatmapSeriesRenderer, ParallelSeriesRenderer,
                     ThemeRiverSeriesRenderer)
        if any(type(renderer) not in supported for renderer in renderers):
            raise NotImplementedError("CanvasFlowChartViewport 当前不支持该系列类型")
        return list(renderers)

    def _model_for(self, renderer, coord):
        if type(renderer) is ParallelSeriesRenderer:
            return CanvasParallelView(renderer, coord)
        if type(renderer) is ThemeRiverSeriesRenderer:
            return CanvasThemeRiverView(renderer, coord)
        return super()._model_for(renderer, coord)

    def _sync_series_model(self, model):
        if not isinstance(model, _CanvasLabeledView):
            super()._sync_series_model(model)
            return
        renderer = model._renderer
        model._visible = renderer.visible
        theme_key = (T("color.bg.base"), T("color.text.secondary"),
                     T("color.border.strong"))
        palette = tuple(QColor(color).getRgb() for color in renderer.chart.palette())
        changed = model._anim_t != self._chart.anim.t \
            or model._color != renderer.color() or model._theme_key != theme_key \
            or model._palette != palette or model._area != renderer._area \
            or getattr(model, "_source_rows", None) is not getattr(renderer, "_rows", None) \
            or getattr(model, "_source_axes", None) is not getattr(renderer, "_axes", None) \
            or getattr(model, "_source_streams", None) is not getattr(renderer, "_streams", None) \
            or getattr(model, "_source_times", None) is not getattr(renderer, "_times", None)
        if changed:
            model.set_geometry(renderer, self._chart.anim.t)
