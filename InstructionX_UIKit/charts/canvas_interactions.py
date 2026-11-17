# -*- coding: utf-8 -*-
"""dataZoom、brush、timeline 与 toolbox 的 Canvas 原生绘制命令。"""

from PySide6.QtCanvasPainter import QCanvasPainter, QCanvasPath
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFontMetricsF, QPainterPath, QPainterPathStroker

from ..theme import T
from .._draw import arc_points
from ._utils import clamp as _clamp, to_float as _to_float
from .axes import chart_font
from .canvas_paths import line_path, path_from_qpainter
from .canvas_static import _text
from .interact import BrushComponent, ChartTimeline, DataZoomComponent, ToolboxComponent

__all__ = ["is_interactive_component", "interactive_component_key",
           "append_interactive_components"]

_TYPES = (DataZoomComponent, BrushComponent, ChartTimeline, ToolboxComponent)


def is_interactive_component(component):
    return isinstance(component, _TYPES)


def interactive_component_key(component):
    if isinstance(component, DataZoomComponent):
        state = (component.entries, component.start, component.end,
                 component._track, component._h_start, component._h_end)
    elif isinstance(component, BrushComponent):
        state = (component.opt, component._rect, component.selected_items,
                 component._highlight_points())
    elif isinstance(component, ChartTimeline):
        state = (component.opt, component.current, component.playing,
                 component._band, component._play_rect, component._node_pts)
    else:
        state = (component.opt, component._buttons,
                 getattr(component.chart, "datazoom_enabled", True))
    return id(component), repr(state)


def _stroke(commands, path, color, width=1.0, cap=QCanvasPainter.LineCap.Square,
            join=QCanvasPainter.LineJoin.Miter):
    commands.append(("stroke_pen", path, QColor(color), float(width), cap, join))


def _rect_path(rect, radius=0.0):
    path = QCanvasPath(4)
    if radius:
        path.roundRect(QRectF(rect), radius)
    else:
        path.rect(QRectF(rect))
    return path


def _circle(point, radius):
    path = QCanvasPath(2)
    path.ellipse(QRectF(point.x() - radius, point.y() - radius, radius * 2, radius * 2))
    return path


def _data_zoom(commands, component):
    if not component.has_slider or component._track.isNull():
        return
    commands.append(("round_rect", QRectF(component._track), 4.0, QColor(T("color.bg.muted"))))
    selected = QRectF(component._x_of(component.start), component._track.top(),
                      max(2.0, component._x_of(component.end) - component._x_of(component.start)),
                      component._track.height())
    color = QColor(T("color.primary"))
    color.setAlpha(70)
    commands.append(("round_rect", selected, 4.0, color))
    for rect in (component._h_start, component._h_end):
        path = _rect_path(rect, 3.0)
        commands.append(("fill", path, QColor(T("color.bg.elevated"))))
        _stroke(commands, path, QColor(T("color.border.strong")))
        cx = rect.center().x()
        for dx in (-2, 2):
            _stroke(commands, line_path([QPointF(cx + dx, rect.top() + 4),
                                          QPointF(cx + dx, rect.bottom() - 4)]),
                    QColor(T("color.text.tertiary")))
    font = chart_font(T("font.xs"))
    fm = QFontMetricsF(font)
    y = component._track.bottom() + 1
    color = QColor(T("color.text.tertiary"))
    _text(commands, f"{component.start:.0f}%",
          QRectF(component._track.left(), y, 40, fm.height()),
          font, color, QCanvasPainter.TextAlign.Left, QCanvasPainter.TextBaseline.Top)
    _text(commands, f"{component.end:.0f}%",
          QRectF(component._track.right() - 40, y, 40, fm.height()),
          font, color, QCanvasPainter.TextAlign.Right, QCanvasPainter.TextBaseline.Top)


def _brush_highlight(commands, component):
    for point, color in component._highlight_points():
        ring = QColor(color)
        ring.setAlpha(200)
        _stroke(commands, _circle(point, component.HIGHLIGHT_R), ring, 1.8)
        core = QColor(color).lighter(140)
        core.setAlpha(120)
        commands.append(("fill", _circle(point, component.HIGHLIGHT_R * 0.45), core))


def _brush(commands, component):
    _brush_highlight(commands, component)
    if component._rect is None or component._rect.isNull():
        return
    plot = component._plot()
    rect = component._rect.intersected(plot) if not plot.isNull() else component._rect
    if component.opt.get("outOfBrush") and not plot.isNull():
        mask = QColor(T("color.bg.base"))
        opacity = _to_float((component.opt.get("outOfBrush") or {}).get("opacity"), 0.45)
        mask.setAlpha(int(255 * _clamp(opacity if opacity is not None else 0.45, 0.0, 1.0)))
        for area in (
                QRectF(plot.left(), plot.top(), max(0.0, rect.left() - plot.left()), plot.height()),
                QRectF(rect.right(), plot.top(), max(0.0, plot.right() - rect.right()), plot.height()),
                QRectF(rect.left(), plot.top(), rect.width(), max(0.0, rect.top() - plot.top())),
                QRectF(rect.left(), rect.bottom(), rect.width(),
                       max(0.0, plot.bottom() - rect.bottom()))):
            commands.append(("fill", _rect_path(area), QColor(mask)))
    fill = QColor(T("color.primary"))
    fill.setAlpha(36)
    commands.append(("fill", _rect_path(rect), fill))
    source = QPainterPath()
    source.addRect(rect)
    stroker = QPainterPathStroker()
    stroker.setWidth(1.2)
    stroker.setCapStyle(Qt.SquareCap)
    stroker.setDashPattern(Qt.DashLine)
    commands.append(("fill", path_from_qpainter(stroker.createStroke(source)),
                     QColor(T("color.primary"))))


def _timeline(commands, component):
    if not component.labels or not component._node_pts:
        return
    font = chart_font(T("font.xs"))
    fm = QFontMetricsF(font)
    primary = QColor(T("color.primary"))
    border = QColor(T("color.border.strong"))
    _stroke(commands, line_path([component._node_pts[0], component._node_pts[-1]]), border)
    for index, (point, label) in enumerate(zip(component._node_pts, component.labels)):
        current = index == component.current
        path = _circle(point, 5.0 if current else 4.0)
        commands.append(("fill", path, QColor(primary if current else T("color.bg.elevated"))))
        _stroke(commands, path, primary if current else border, 1.6)
        _text(commands, label, QRectF(point.x() - 40, point.y() + 8, 80, fm.height()),
              font, primary if current else QColor(T("color.text.secondary")),
              QCanvasPainter.TextAlign.Center, QCanvasPainter.TextBaseline.Top)
    play = _circle(component._play_rect.center(), component._play_rect.width() / 2)
    commands.append(("fill", play, QColor(T("color.bg.elevated"))))
    _stroke(commands, play, border, 1.2)
    center = component._play_rect.center()
    color = QColor(T("color.text.secondary"))
    if component.playing:
        commands.append(("fill", _rect_path(QRectF(center.x() - 5, center.y() - 5, 3.4, 10)), color))
        commands.append(("fill", _rect_path(QRectF(center.x() + 1.6, center.y() - 5, 3.4, 10)), color))
    else:
        commands.append(("fill", line_path([
            QPointF(center.x() - 3.5, center.y() - 5.5),
            QPointF(center.x() - 3.5, center.y() + 5.5),
            QPointF(center.x() + 5.5, center.y()),
            QPointF(center.x() - 3.5, center.y() - 5.5)]), color))


def _icon_stroke(commands, points, color, width=1.5):
    for start, end in zip(points, points[1:]):
        _stroke(commands, line_path([start, end]), color, width,
                cap=QCanvasPainter.LineCap.Round, join=QCanvasPainter.LineJoin.Round)


def _toolbox(commands, component):
    for name, rect in component._buttons:
        path = _rect_path(rect, 4.0)
        commands.append(("fill", path, QColor(T("color.bg.elevated"))))
        _stroke(commands, path, QColor(T("color.border")))
        enabled = name != "dataZoom" or bool(getattr(component.chart, "datazoom_enabled", True))
        color = QColor(T("color.text.secondary")) if enabled \
            else QColor(T("color.text.disabled"))
        cx, cy = rect.center().x(), rect.center().y()
        if name == "saveAsImage":
            _icon_stroke(commands, [QPointF(cx - 7, cy + 5), QPointF(cx + 7, cy + 5)], color)
            _icon_stroke(commands, [QPointF(cx - 7, cy + 5), QPointF(cx - 7, cy + 1)], color)
            _icon_stroke(commands, [QPointF(cx + 7, cy + 5), QPointF(cx + 7, cy + 1)], color)
            _icon_stroke(commands, [QPointF(cx, cy - 6), QPointF(cx, cy + 2)], color)
            _icon_stroke(commands, [QPointF(cx - 3.5, cy - 1), QPointF(cx, cy + 2.5),
                                    QPointF(cx + 3.5, cy - 1)], color)
        elif name == "restore":
            points = [QPointF(x, y) for x, y in arc_points(QRectF(cx - 6, cy - 6, 12, 12), 40, 290)]
            _icon_stroke(commands, points, color)
            _icon_stroke(commands, [QPointF(cx + 6.2, cy - 2.5), QPointF(cx + 6.2, cy - 6.5),
                                    QPointF(cx + 2.2, cy - 6.5)], color)
        elif name == "dataZoom":
            _stroke(commands, _circle(QPointF(cx - 1.5, cy - 1.5), 4.5), color, 1.5,
                    cap=QCanvasPainter.LineCap.Round, join=QCanvasPainter.LineJoin.Round)
            _icon_stroke(commands, [QPointF(cx + 1.8, cy + 1.8), QPointF(cx + 5.5, cy + 5.5)], color)
            _icon_stroke(commands, [QPointF(cx - 4, cy - 1.5), QPointF(cx + 1, cy - 1.5)], color)
            _icon_stroke(commands, [QPointF(cx - 1.5, cy - 4), QPointF(cx - 1.5, cy + 1)], color)


def append_interactive_components(commands, chart):
    for component in chart.components:
        if isinstance(component, DataZoomComponent):
            _data_zoom(commands, component)
        elif isinstance(component, BrushComponent):
            _brush(commands, component)
        elif isinstance(component, ChartTimeline):
            _timeline(commands, component)
        elif isinstance(component, ToolboxComponent):
            _toolbox(commands, component)
