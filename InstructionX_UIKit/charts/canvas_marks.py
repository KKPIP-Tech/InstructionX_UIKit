# -*- coding: utf-8 -*-
"""标注与 Graphic 组件的 Canvas 原生绘制命令。"""

from PySide6.QtCanvasPainter import QCanvasPainter, QCanvasPath
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFontMetricsF, QPainterPath, QPainterPathStroker

from ..theme import T
from ._utils import to_float as _to_float
from .axes import chart_font
from .canvas_paths import line_path, path_from_qpainter
from .canvas_static import _text
from .components import GraphicComponent, MarkAreaComponent, MarkLineComponent, MarkPointComponent

__all__ = ["is_native_component", "native_component_key", "append_native_components"]

_NATIVE_TYPES = (MarkPointComponent, MarkLineComponent, MarkAreaComponent, GraphicComponent)


def is_native_component(component):
    return isinstance(component, _NATIVE_TYPES)


def native_component_key(chart):
    result = []
    for component in chart.components:
        if not is_native_component(component):
            continue
        renderer = component._renderer() if hasattr(component, "_renderer") else None
        color = component._color() if hasattr(component, "_color") else QColor(T("color.primary"))
        geometry = tuple(repr(getattr(component, name, None))
                         for name in ("_marks", "_lines", "_areas", "elements", "rect"))
        result.append((id(component), repr(getattr(component, "opt", None)),
                       repr(component.series_opt)
                       if hasattr(component, "series_opt") else None,
                       geometry, renderer.visible if renderer is not None else None,
                       color.getRgb()))
    return tuple(result)


def _stroke(commands, path, color, width=1.0, cap=QCanvasPainter.LineCap.Square):
    commands.append(("stroke_pen", path, QColor(color), float(width), cap,
                     QCanvasPainter.LineJoin.Miter))


def _dashed(commands, start, end, color):
    source = QPainterPath(start)
    source.lineTo(end)
    stroker = QPainterPathStroker()
    stroker.setWidth(1.4)
    stroker.setCapStyle(Qt.SquareCap)
    stroker.setDashPattern(Qt.DashLine)
    commands.append(("fill", path_from_qpainter(stroker.createStroke(source)), QColor(color)))


def _mark_point(commands, component):
    if not component._marks or not component._visible():
        return
    color = component._color()
    font = chart_font(T("font.xs"))
    fm = QFontMetricsF(font)
    for mark in component._marks:
        point = mark["pos"]
        path = QCanvasPath(2)
        path.ellipse(QRectF(point.x() - 4.2, point.y() - 4.2, 8.4, 8.4))
        commands.append(("fill", path, QColor(color)))
        _stroke(commands, path, QColor(T("color.bg.elevated")), 1.4)
        top = QPointF(point.x(), point.y() - 14)
        _stroke(commands, line_path([QPointF(point.x(), point.y() - 4.5), top]), color, 1.4)
        width = fm.horizontalAdvance(mark["text"])
        _text(commands, mark["text"],
              QRectF(point.x() - width / 2 - 2, top.y() - fm.height() - 2,
                     width + 4, fm.height()),
              font, QColor(T("color.text.primary")), QCanvasPainter.TextAlign.Center,
              QCanvasPainter.TextBaseline.Middle)


def _mark_line(commands, component):
    if not component._lines or not component._visible():
        return
    coord = component._coord()
    plot = coord.plot
    color = component._color()
    font = chart_font(T("font.xs"))
    fm = QFontMetricsF(font)
    for line in component._lines:
        if line["orient"] == "h":
            py = coord.y_axis.map(_to_float(line["value"], 0.0), plot.bottom(), plot.top())
            _dashed(commands, QPointF(plot.left(), py), QPointF(plot.right(), py), color)
            _text(commands, line["text"],
                  QRectF(plot.right() - 120, py - fm.height() - 3, 118, fm.height()),
                  font, color, QCanvasPainter.TextAlign.Right, QCanvasPainter.TextBaseline.Middle)
        else:
            px = coord.x_axis.map(line["value"], plot.left(), plot.right())
            _dashed(commands, QPointF(px, plot.top()), QPointF(px, plot.bottom()), color)
            _text(commands, line["text"], QRectF(px + 4, plot.top() + 3, 120, fm.height()),
                  font, color, QCanvasPainter.TextAlign.Left, QCanvasPainter.TextBaseline.Middle)


def _mark_area(commands, component):
    if not component._areas or not component._visible():
        return
    color = QColor(T("color.primary"))
    color.setAlpha(28)
    for rect in component._areas:
        path = QCanvasPath(4)
        path.rect(QRectF(rect))
        commands.append(("fill", path, QColor(color)))


def _brush(commands, path, style, default_fill):
    fill = style.get("fill")
    if fill != "none" and fill is not False:
        commands.append(("fill", path, QColor(fill or default_fill)))
    stroke = style.get("stroke")
    if stroke:
        _stroke(commands, path, QColor(stroke), _to_float(style.get("lineWidth"), 1.0) or 1.0)


def _graphic(commands, component):
    for element in component.elements:
        typ = str(element.get("type") or "")
        shape = element.get("shape") or {}
        style = element.get("style") or {}
        base = component._anchor(element)
        if typ == "circle":
            cx = base.x() + (_to_float(shape.get("cx"), 0.0) or 0.0)
            cy = base.y() + (_to_float(shape.get("cy"), 0.0) or 0.0)
            radius = _to_float(shape.get("r"), 20.0) or 20.0
            path = QCanvasPath(2)
            path.ellipse(QRectF(cx - radius, cy - radius, radius * 2, radius * 2))
            _brush(commands, path, style, T("color.primary"))
        elif typ == "rect":
            x = base.x() + (_to_float(shape.get("x"), 0.0) or 0.0)
            y = base.y() + (_to_float(shape.get("y"), 0.0) or 0.0)
            width = _to_float(shape.get("width"), 40.0) or 40.0
            height = _to_float(shape.get("height"), 24.0) or 24.0
            radius = _to_float(shape.get("r"), 0.0) or 0.0
            path = QCanvasPath(4)
            if radius > 0:
                path.roundRect(QRectF(x, y, width, height), radius)
            else:
                path.rect(QRectF(x, y, width, height))
            _brush(commands, path, style, T("color.primary.subtle"))
        elif typ == "text":
            text = str(style.get("text") or "")
            if not text:
                continue
            size = int(_to_float(style.get("fontSize"), T("font.xs")) or T("font.xs"))
            font = chart_font(size)
            fm = QFontMetricsF(font)
            x = base.x() + (_to_float(shape.get("x"), 0.0) or 0.0)
            y = base.y() + (_to_float(shape.get("y"), 0.0) or 0.0)
            _text(commands, text, QRectF(x, y, fm.horizontalAdvance(text) + 4, fm.height() + 2),
                  font, QColor(style.get("fill") or T("color.text.primary")),
                  QCanvasPainter.TextAlign.Left, QCanvasPainter.TextBaseline.Top)
        elif typ == "line":
            start = QPointF(base.x() + (_to_float(shape.get("x1"), 0.0) or 0.0),
                            base.y() + (_to_float(shape.get("y1"), 0.0) or 0.0))
            end = QPointF(base.x() + (_to_float(shape.get("x2"), 40.0) or 40.0),
                          base.y() + (_to_float(shape.get("y2"), 0.0) or 0.0))
            _stroke(commands, line_path([start, end]),
                    QColor(style.get("stroke") or T("color.border.strong")),
                    _to_float(style.get("lineWidth"), 2.0) or 2.0)


def append_native_components(commands, chart):
    for component in chart.components:
        if isinstance(component, MarkPointComponent):
            _mark_point(commands, component)
        elif isinstance(component, MarkLineComponent):
            _mark_line(commands, component)
        elif isinstance(component, MarkAreaComponent):
            _mark_area(commands, component)
        elif isinstance(component, GraphicComponent):
            _graphic(commands, component)
