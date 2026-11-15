# -*- coding: utf-8 -*-
"""Chart tooltip 与坐标指示器的 Canvas 原生场景。"""

from PySide6.QtCanvasPainter import QCanvasPainter, QCanvasPath
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFontMetricsF, QPainterPath, QPainterPathStroker

from ..theme import T, ThemeManager
from .axes import CalendarCoord, GridCoord, PolarCoord, SingleAxisCoord, chart_font
from .canvas_paths import path_from_qpainter
from .canvas_static import CanvasStaticScene, _line, _text

__all__ = ["CanvasTooltipScene", "build_tooltip_scene"]


class CanvasTooltipScene(CanvasStaticScene):
    def __init__(self, commands, key, box):
        super().__init__(commands, key)
        self.box = QRectF(box)

    def draw(self, painter):
        painter.resetClipping()
        super().draw(painter)


def _dashed(commands, start, end, color):
    source = QPainterPath(start)
    source.lineTo(end)
    stroker = QPainterPathStroker()
    stroker.setWidth(1.0)
    stroker.setCapStyle(Qt.SquareCap)
    stroker.setDashPattern(Qt.DashLine)
    commands.append(("fill", path_from_qpainter(stroker.createStroke(source)), QColor(color)))


def _marker(commands, coord, pos):
    color = QColor(T("color.border.strong"))
    if isinstance(coord, GridCoord):
        x = min(max(pos.x(), coord.plot.left()), coord.plot.right())
        y = min(max(pos.y(), coord.plot.top()), coord.plot.bottom())
        _dashed(commands, QPointF(x, coord.plot.top()), QPointF(x, coord.plot.bottom()), color)
        _dashed(commands, QPointF(coord.plot.left(), y), QPointF(coord.plot.right(), y), color)
    elif isinstance(coord, PolarCoord):
        _line(commands, coord.center, pos, color)
        radius = ((pos.x() - coord.center.x()) ** 2 + (pos.y() - coord.center.y()) ** 2) ** 0.5
        if radius > 1:
            path = QCanvasPath(2)
            path.ellipse(QRectF(coord.center.x() - radius, coord.center.y() - radius,
                                radius * 2, radius * 2))
            commands.append(("stroke", path, color, 1.0))
    elif isinstance(coord, SingleAxisCoord):
        x = min(max(pos.x(), coord.plot.left()), coord.plot.right())
        _dashed(commands, QPointF(x, coord.rect.top() + 8),
                QPointF(x, coord.rect.bottom() - 8), color)
    elif isinstance(coord, CalendarCoord):
        day = coord.date_at(pos)
        if day is not None:
            rect = coord.cell_rect(day).adjusted(0.5, 0.5, -0.5, -0.5)
            path = QCanvasPath(4)
            path.rect(rect)
            commands.append(("stroke", path, QColor(T("color.primary")), 1.4))
    else:
        raise NotImplementedError(f"Canvas tooltip 坐标指示器未实现: {type(coord).__name__}")


def build_tooltip_scene(chart):
    tooltip = chart.tooltip
    if not tooltip.shown or not tooltip.active:
        return None
    pos = tooltip._pos
    marker = tooltip._marker_pos if tooltip._marker_pos is not None else pos
    key = (
        chart.width(), chart.height(), ThemeManager.instance().mode,
        pos.x(), pos.y(), marker.x(), marker.y(),
        tuple((color.getRgb() if color is not None else None, name, str(value))
              for color, name, value in tooltip._lines),
    )
    commands = []
    coord = chart.primary_coord()
    if coord is not None:
        _marker(commands, coord, marker)
    font = chart_font(T("font.xs"))
    fm = QFontMetricsF(font)
    pad_x, pad_y, line_gap, dot = 10.0, 8.0, 3.0, 8.0
    line_h = fm.height()
    rows = [(color, f"{name}: {value}" if name else str(value))
            for color, name, value in tooltip._lines]
    text_w = max((fm.horizontalAdvance(text) for _, text in rows), default=0.0)
    width = pad_x * 2 + (dot + 5 if any(color is not None for color, _ in rows) else 0) + text_w
    height = pad_y * 2 + len(rows) * line_h + max(0, len(rows) - 1) * line_gap
    area = QRectF(0, 0, chart.width(), chart.height())
    x, y = pos.x() + 14, pos.y() + 14
    if x + width > area.right() - 4:
        x = pos.x() - width - 14
    if y + height > area.bottom() - 4:
        y = pos.y() - height - 14
    x = min(max(x, 4.0), max(4.0, area.right() - width - 4))
    y = min(max(y, 4.0), max(4.0, area.bottom() - height - 4))
    box = QRectF(x, y, width, height)
    radius = float(T("radius.md"))
    shadow_color = QColor(T("color.text.primary"))
    for index, alpha in ((6, 16), (4, 22), (2, 30)):
        color = QColor(shadow_color)
        color.setAlpha(alpha)
        commands.append(("round_rect", box.translated(0, 2).adjusted(
            -index / 2, -index / 2, index / 2, index / 2), radius + index / 2, color))
    commands.append(("round_rect_border", box, radius, QColor(T("color.bg.elevated")),
                     QColor(T("color.border")), 1.0))
    ty = box.top() + pad_y
    for color, label in rows:
        tx = box.left() + pad_x
        if color is not None:
            commands.append(("fill_circle", QRectF(tx, ty + line_h / 2 - dot / 2, dot, dot),
                             QColor(color)))
            tx += dot + 5
        _text(commands, label, QRectF(tx, ty, box.right() - pad_x - tx, line_h),
              font, QColor(T("color.text.primary")), QCanvasPainter.TextAlign.Left,
              QCanvasPainter.TextBaseline.Middle)
        ty += line_h + line_gap
    return CanvasTooltipScene(commands, key, box)
