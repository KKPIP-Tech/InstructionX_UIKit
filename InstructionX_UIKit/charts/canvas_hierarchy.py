# -*- coding: utf-8 -*-
"""饼图、雷达图与仪表盘的 Canvas 原生几何和共享视口。"""

import math

from PySide6.QtCanvasPainter import QCanvasPainter, QCanvasPath
from PySide6.QtCore import QPointF, QRectF
from PySide6.QtGui import QColor, QFontMetricsF

from ..theme import T
from .._draw import arc_points
from ._utils import ON_FILL_WHITE, clamp as _clamp, to_float as _to_float, with_alpha
from .axes import chart_font, format_value
from .canvas_paths import line_path, path_from_qpainter
from .canvas_series import (
    CanvasBarView,
    CanvasFlowChartViewport,
    _with_alpha,
)
from .canvas_static import CanvasStaticScene, _text
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
)
from .series_hierarchy import (
    GaugeSeriesRenderer,
    PieSeriesRenderer,
    RadarSeriesRenderer,
    _label_font,
    _parse_named_values,
    _parse_pct,
)

__all__ = ["CanvasPieView", "CanvasRadarView", "CanvasGaugeView",
           "CanvasHierarchyChartViewport"]


def _stroke(commands, path, color, width=1.0, cap=QCanvasPainter.LineCap.Square,
            join=QCanvasPainter.LineJoin.Miter):
    commands.append(("stroke_pen", path, QColor(color), float(width), cap, join))


class _CanvasHierarchyView(CanvasBarView):
    def _reset(self, renderer, anim_t):
        self._coord = renderer.chart.coord_for(renderer.opt)
        self._plot = None
        radius = getattr(renderer, "_radius", getattr(renderer, "_r_out", 1.0))
        center = renderer._center
        self._area = QRectF(center.x() - radius, center.y() - radius, radius * 2, radius * 2)
        self._anim_t = float(anim_t)
        self._color = QColor(renderer.color())
        self._areas = []
        self._outlines = []
        self._paths = []
        self._arcs = []
        self._scene = None

    def _sync_key(self, renderer):
        center = renderer._center
        return (
            repr(renderer.opt), repr(renderer.prev_data), renderer.chart.anim.t,
            tuple(QColor(color).getRgb() for color in renderer.chart.palette()),
            tuple(T(key) for key in ("color.bg.base", "color.bg.elevated", "color.border",
                                     "color.border.strong", "color.text.primary",
                                     "color.text.secondary")),
            center.x(), center.y(), getattr(renderer, "_radius", None),
            getattr(renderer, "_r_in", None), getattr(renderer, "_r_out", None),
            getattr(renderer, "_value", None),
            id(getattr(renderer, "_sectors", None)),
            id(getattr(renderer, "_indicators", None)),
            id(getattr(renderer, "_polys", None)), id(getattr(renderer, "_entries", None)),
        )

    def _finish(self, renderer, commands):
        self._scene = CanvasStaticScene(commands, None)
        self._signature = self._sync_key(renderer)

    def _draw(self, painter, scale=None):
        if self._visible and self._scene is not None:
            self._scene.draw(painter)


class CanvasPieView(_CanvasHierarchyView):
    def set_geometry(self, renderer, anim_t):
        self._reset(renderer, anim_t)
        self._source_sectors = renderer._sectors
        self._animated = renderer._animated_sectors(anim_t)
        commands = []
        border = QColor(T("color.bg.base"))
        for sector in self._animated:
            source = renderer._sector_path(sector, anim_t)
            if source.isEmpty():
                continue
            path = path_from_qpainter(source)
            self._areas.append((path, QColor(sector["color"])))
            self._outlines.append((path, QColor(border), 1.2))
            commands.append(("fill", path, QColor(sector["color"])))
            _stroke(commands, path, border, 1.2)
        self._labels(renderer, commands, anim_t)
        self._finish(renderer, commands)

    def _center_total(self, renderer, commands, font):
        option = dict(renderer.opt.get("totalLabel") or {})
        title = str(option.get("text") or "")
        value_font = chart_font(T("font.title.md"), T("font.weight.semibold"))
        fm = QFontMetricsF(value_font)
        cy = renderer._center.y()
        if title:
            cy -= fm.height() / 2
        rect = QRectF(renderer._center.x() - renderer._r_in, cy - fm.height() / 2,
                      renderer._r_in * 2, fm.height())
        _text(commands, format_value(renderer._total), rect, value_font,
              QColor(T("color.text.primary")), QCanvasPainter.TextAlign.Center,
              QCanvasPainter.TextBaseline.Middle)
        if title:
            fm2 = QFontMetricsF(font)
            _text(commands, title,
                  QRectF(renderer._center.x() - renderer._r_in, cy + fm.height() / 2,
                         renderer._r_in * 2, fm2.height()),
                  font, QColor(T("color.text.secondary")), QCanvasPainter.TextAlign.Center,
                  QCanvasPainter.TextBaseline.Middle)

    def _labels(self, renderer, commands, anim_t):
        option = dict(renderer.opt.get("label") or {})
        if not bool(option.get("show", True)):
            return
        position = str(option.get("position") or "outside")
        font = _label_font(option.get("fontSize"))
        fm = QFontMetricsF(font)
        if position == "center":
            self._center_total(renderer, commands, font)
            return
        total = sum(sector["value"] for sector in renderer._sectors) or 1.0
        for sector in self._animated:
            span = (sector["a1"] - sector["a0"]) * anim_t
            if span < 4.0:
                continue
            middle = sector["a0"] + span / 2
            name = sector["name"] or format_value(sector["value"])
            percent = format_value(round(sector["value"] / total * 100, 1)) + "%"
            if position == "inside":
                radius = (sector["r0"] + sector["r1"]) / 2
                point = renderer._pt(middle, radius)
                _text(commands, percent,
                      QRectF(point.x() - 40, point.y() - fm.height() / 2, 80, fm.height()),
                      font, QColor(ON_FILL_WHITE), QCanvasPainter.TextAlign.Center,
                      QCanvasPainter.TextBaseline.Middle)
                continue
            pt1 = renderer._pt(middle, sector["r1"] + 2)
            pt2 = renderer._pt(middle, sector["r1"] + 14)
            right = math.sin(math.radians(middle)) >= 0
            pt3 = QPointF(pt2.x() + (14 if right else -14), pt2.y())
            _stroke(commands, line_path([pt1, pt2, pt3]), QColor(T("color.border.strong")))
            text = f"{name} {percent}" if sector["name"] else percent
            width = fm.horizontalAdvance(text)
            rect = QRectF(pt3.x() + 3 if right else pt3.x() - width - 3,
                          pt3.y() - fm.height() / 2, width + 4, fm.height())
            _text(commands, text, rect, font, QColor(T("color.text.primary")),
                  QCanvasPainter.TextAlign.Left if right else QCanvasPainter.TextAlign.Right,
                  QCanvasPainter.TextBaseline.Middle)
        if renderer._r_in > 4 and bool(dict(renderer.opt.get("totalLabel") or {}).get(
                "show", False)):
            self._center_total(renderer, commands, font)


class CanvasRadarView(_CanvasHierarchyView):
    def set_geometry(self, renderer, anim_t):
        self._reset(renderer, anim_t)
        self._source_indicators = renderer._indicators
        self._source_polys = renderer._polys
        self._rings = []
        self._poly_paths = []
        self._dots = []
        commands = []
        count = len(renderer._indicators)
        if not count:
            self._finish(renderer, commands)
            return
        split = max(1, int(_to_float(renderer.opt.get("splitNumber"), 5)))
        for index in range(1, split + 1):
            path = path_from_qpainter(renderer._ring_path(index / split))
            self._rings.append(path)
            _stroke(commands, path, QColor(T("color.border")))
        font = _label_font()
        fm = QFontMetricsF(font)
        for index, indicator in enumerate(renderer._indicators):
            theta = -math.pi / 2 + index / count * 2 * math.pi
            outer = QPointF(renderer._center.x() + renderer._radius * math.cos(theta),
                            renderer._center.y() + renderer._radius * math.sin(theta))
            _stroke(commands, line_path([renderer._center, outer]),
                    QColor(T("color.border.strong")))
            lx = renderer._center.x() + (renderer._radius + 16) * math.cos(theta)
            ly = renderer._center.y() + (renderer._radius + 16) * math.sin(theta)
            _text(commands, indicator["name"], QRectF(lx - 48, ly - fm.height() / 2, 96, fm.height()),
                  font, QColor(T("color.text.secondary")), QCanvasPainter.TextAlign.Center,
                  QCanvasPainter.TextBaseline.Middle)
        area_opt = renderer.opt.get("areaStyle")
        opacity = 0.25
        if isinstance(area_opt, dict):
            opacity = _clamp(_to_float(area_opt.get("opacity"), 0.25), 0.0, 1.0)
        for poly in renderer._polys:
            points = [QPointF(renderer._center.x() + (point.x() - renderer._center.x()) * anim_t,
                              renderer._center.y() + (point.y() - renderer._center.y()) * anim_t)
                      for point in poly["points"]]
            if not points:
                continue
            path = line_path(points + [points[0]])
            self._poly_paths.append(path)
            if area_opt is not None:
                color = with_alpha(poly["color"], opacity * 255)
                self._areas.append((path, color))
                commands.append(("fill", path, color))
            self._outlines.append((path, QColor(poly["color"]), 2.0))
            _stroke(commands, path, poly["color"], 2.0, join=QCanvasPainter.LineJoin.Round)
            for point in points:
                dot = QCanvasPath(2)
                dot.ellipse(QRectF(point.x() - 2.5, point.y() - 2.5, 5, 5))
                self._dots.append(dot)
                commands.append(("fill", dot, QColor(poly["color"])))
                _stroke(commands, dot, poly["color"], 2.0)
        self._finish(renderer, commands)


class CanvasGaugeView(_CanvasHierarchyView):
    def _arc(self, renderer, commands, a_hi, a_lo, radius, width, color):
        a_lo, a_hi = min(a_lo, a_hi), max(a_lo, a_hi)
        if a_hi <= a_lo or radius <= 0:
            return
        rect = QRectF(renderer._center.x() - radius, renderer._center.y() - radius,
                      radius * 2, radius * 2)
        points = [QPointF(x, y) for x, y in arc_points(rect, -a_lo, a_lo - a_hi)]
        self._arcs.append((a_lo, a_hi, radius, width, QColor(color)))
        for start, end in zip(points, points[1:]):
            path = line_path([start, end])
            self._outlines.append((path, QColor(color), width))
            _stroke(commands, path, color, width, cap=QCanvasPainter.LineCap.Butt)

    def set_geometry(self, renderer, anim_t):
        self._reset(renderer, anim_t)
        self._source_entries = renderer._entries
        commands = []
        start, end = renderer._start_angle(), renderer._end_angle()
        previous = renderer._vmin()
        entries = _parse_named_values(renderer.prev_data)
        if entries:
            previous = entries[0][1]
        self._cur_value = previous + (renderer._value - previous) * anim_t
        self._pointer_angle = renderer._value_angle(self._cur_value)
        radius = renderer._radius
        line_style = dict(dict(renderer.opt.get("axisLine") or {}).get("lineStyle") or {})
        width = _to_float(line_style.get("width"), 12.0)
        segments = line_style.get("color")
        arc_radius = radius - width / 2
        if isinstance(segments, list) and segments:
            parsed = [(_clamp(_to_float(item[0], 0.0), 0.0, 1.0), QColor(str(item[1])))
                      for item in segments if isinstance(item, (list, tuple)) and len(item) >= 2]
            parsed.sort(key=lambda item: item[0])
            previous_fraction = 0.0
            for fraction, color in parsed:
                self._arc(renderer, commands,
                          start + (end - start) * previous_fraction,
                          start + (end - start) * fraction, arc_radius, width, color)
                previous_fraction = fraction
            if previous_fraction < 1.0 and parsed:
                self._arc(renderer, commands, start + (end - start) * previous_fraction,
                          end, arc_radius, width, parsed[-1][1])
        else:
            self._arc(renderer, commands, start, end, arc_radius, width,
                      QColor(T("color.border")))
        progress = dict(renderer.opt.get("progress") or {})
        if bool(progress.get("show", False)):
            progress_width = _to_float(progress.get("width"), width)
            self._arc(renderer, commands, max(start, self._pointer_angle),
                      min(start, self._pointer_angle), radius - progress_width / 2,
                      progress_width, renderer.color())
        pointer = dict(renderer.opt.get("pointer") or {})
        if bool(pointer.get("show", True)):
            length = _parse_pct(pointer.get("length", "60%"), radius, radius * 0.6)
            pointer_width = _to_float(pointer.get("width"), 4.0)
            tip = renderer._pt(self._pointer_angle, length)
            back = renderer._pt(self._pointer_angle + 180, 14.0)
            perpendicular = math.radians(self._pointer_angle + 90)
            px = math.cos(perpendicular) * pointer_width / 2
            py = math.sin(perpendicular) * pointer_width / 2
            path = line_path([tip, QPointF(renderer._center.x() + px, renderer._center.y() + py),
                              back, QPointF(renderer._center.x() - px, renderer._center.y() - py),
                              tip])
            self._areas.append((path, QColor(renderer.color())))
            commands.append(("fill", path, QColor(renderer.color())))
        anchor = dict(renderer.opt.get("anchor") or {})
        if bool(anchor.get("show", True)):
            size = _to_float(anchor.get("size"), 10.0)
            path = QCanvasPath(2)
            path.ellipse(QRectF(renderer._center.x() - size / 2,
                                renderer._center.y() - size / 2, size, size))
            commands.append(("fill", path, QColor(renderer.color())))
            _stroke(commands, path, QColor(T("color.bg.elevated")), 2.0)
        detail = dict(renderer.opt.get("detail") or {})
        height = 0.0
        if bool(detail.get("show", True)):
            font = chart_font(detail.get("fontSize") or T("font.title.md"),
                              T("font.weight.semibold"))
            fm = QFontMetricsF(font)
            height = fm.height()
            _text(commands, format_value(self._cur_value),
                  QRectF(renderer._center.x() - radius, renderer._center.y() + radius * 0.22,
                         radius * 2, fm.height()),
                  font, QColor(T("color.text.primary")), QCanvasPainter.TextAlign.Center,
                  QCanvasPainter.TextBaseline.Top)
        title = dict(renderer.opt.get("title") or {})
        name = renderer._entries[0][0] if renderer._entries else renderer.name
        if bool(title.get("show", True)) and name:
            font = _label_font(title.get("fontSize"))
            fm = QFontMetricsF(font)
            _text(commands, name,
                  QRectF(renderer._center.x() - radius,
                         renderer._center.y() + radius * 0.22 + height + 4,
                         radius * 2, fm.height()),
                  font, QColor(T("color.text.secondary")), QCanvasPainter.TextAlign.Center,
                  QCanvasPainter.TextBaseline.Top)
        self._finish(renderer, commands)


class CanvasHierarchyChartViewport(CanvasFlowChartViewport):
    """支持饼图、雷达图、仪表盘及既有系列的共享 Scene Graph 视口。"""

    @staticmethod
    def _line_models(renderers):
        supported = (LineSeriesRenderer, BarSeriesRenderer, ScatterSeriesRenderer,
                     EffectScatterSeriesRenderer, CandlestickSeriesRenderer,
                     BoxplotSeriesRenderer, PictorialBarSeriesRenderer,
                     HeatmapSeriesRenderer, ParallelSeriesRenderer,
                     ThemeRiverSeriesRenderer, PieSeriesRenderer,
                     RadarSeriesRenderer, GaugeSeriesRenderer)
        if any(type(renderer) not in supported for renderer in renderers):
            raise NotImplementedError("CanvasHierarchyChartViewport 当前不支持该系列类型")
        return list(renderers)

    def _model_for(self, renderer, coord):
        if type(renderer) is PieSeriesRenderer:
            return CanvasPieView(renderer, coord)
        if type(renderer) is RadarSeriesRenderer:
            return CanvasRadarView(renderer, coord)
        if type(renderer) is GaugeSeriesRenderer:
            return CanvasGaugeView(renderer, coord)
        return super()._model_for(renderer, coord)

    def _sync_series_model(self, model):
        if not isinstance(model, _CanvasHierarchyView):
            super()._sync_series_model(model)
            return
        renderer = model._renderer
        model._visible = renderer.visible
        if model._signature != model._sync_key(renderer):
            model.set_geometry(renderer, self._chart.anim.t)
