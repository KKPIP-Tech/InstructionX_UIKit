# -*- coding: utf-8 -*-
"""Chart 静态轴、标题与图例的 Canvas 原生绘制命令。"""

from PySide6.QtCanvasPainter import QCanvasPainter, QCanvasPath
from PySide6.QtCore import QPointF, QRectF
from PySide6.QtGui import QColor, QFontMetricsF, QTransform

from ..theme import T
from .axes import (
    GridCoord,
    PolarCoord,
    SingleAxisCoord,
    _label_step,
    chart_font,
    format_value,
)
from .canvas_paths import path_from_qpainter

__all__ = ["CanvasStaticScene", "build_static_scene", "static_scene_key"]


class CanvasStaticScene:
    def __init__(self, commands, key):
        self.commands = tuple(commands)
        self.key = key

    def draw(self, painter):
        painter.save()
        try:
            painter.setTransform(QTransform())
            painter.setAntialias(1.0)
            for command in self.commands:
                kind = command[0]
                if kind == "fill_rect":
                    _kind, rect, color = command
                    painter.setFillStyle(color)
                    painter.fillRect(rect)
                elif kind == "stroke":
                    _kind, path, color, width = command
                    painter.setStrokeStyle(color)
                    painter.setLineWidth(width)
                    painter.stroke(path)
                elif kind == "round_rect":
                    _kind, rect, radius, color = command
                    painter.setFillStyle(color)
                    painter.beginPath()
                    painter.roundRect(rect, radius)
                    painter.fill()
                elif kind == "text":
                    _kind, text, rect, font, color, align, baseline = command
                    painter.setFont(font)
                    painter.setFillStyle(color)
                    painter.setTextAlign(align)
                    painter.setTextBaseline(baseline)
                    painter.fillText(text, rect)
                else:
                    raise ValueError(f"未知 Canvas 静态命令: {kind!r}")
        finally:
            painter.restore()


def static_scene_key(chart):
    return (
        chart._static_layer_key(), chart._opt_version,
        repr(chart.title.opt), repr(chart.legend.opt),
        tuple((renderer.name, renderer.visible, renderer.color().getRgb())
              for renderer in chart.series_renderers),
    )


def _line(commands, start, end, color, width=1.0):
    path = QCanvasPath(2)
    path.moveTo(start)
    path.lineTo(end)
    commands.append(("stroke", path, QColor(color), float(width)))


def _text(commands, text, rect, font, color, align, baseline):
    commands.append(("text", str(text), QRectF(rect), font, QColor(color), align, baseline))


def _grid(commands, coord):
    font = coord.x_axis.label_font()
    fm = QFontMetricsF(font)
    grid_color = QColor(T("color.border"))
    axis_color = QColor(T("color.border.strong"))
    text_color = QColor(T("color.text.secondary"))
    name_color = QColor(T("color.text.tertiary"))
    plot, rect = coord.plot, coord.rect
    for tick in coord.y_axis.ticks():
        py = coord.y_axis.map(tick, plot.bottom(), plot.top())
        _line(commands, QPointF(plot.left(), py), QPointF(plot.right(), py), grid_color)
        _text(commands, format_value(tick),
              QRectF(rect.left(), py - fm.height() / 2,
                     max(8.0, plot.left() - rect.left() - 6), fm.height()),
              font, text_color, QCanvasPainter.TextAlign.Right,
              QCanvasPainter.TextBaseline.Middle)
    if coord.x_axis.type == "category":
        cats = coord.x_axis.categories
        step = _label_step(cats, plot.width(), fm)
        for index, category in enumerate(cats):
            px = coord.x_axis.map(index, plot.left(), plot.right(), local=True)
            _line(commands, QPointF(px, plot.top()), QPointF(px, plot.bottom()), grid_color)
            if index % step == 0:
                _text(commands, category, QRectF(px - 40, plot.bottom() + 4, 80, fm.height()),
                      font, text_color, QCanvasPainter.TextAlign.Center,
                      QCanvasPainter.TextBaseline.Top)
    else:
        for tick in coord.x_axis.ticks():
            px = coord.x_axis.map(tick, plot.left(), plot.right())
            _line(commands, QPointF(px, plot.top()), QPointF(px, plot.bottom()), grid_color)
            _text(commands, format_value(tick),
                  QRectF(px - 40, plot.bottom() + 4, 80, fm.height()),
                  font, text_color, QCanvasPainter.TextAlign.Center,
                  QCanvasPainter.TextBaseline.Top)
    _line(commands, plot.bottomLeft(), plot.bottomRight(), axis_color)
    _line(commands, plot.bottomLeft(), plot.topLeft(), axis_color)
    if coord.x_axis.name:
        _text(commands, coord.x_axis.name,
              QRectF(plot.right() - 80, plot.bottom() + 4 + fm.height(), 80, fm.height()),
              font, name_color, QCanvasPainter.TextAlign.Right,
              QCanvasPainter.TextBaseline.Top)
    if coord.y_axis.name:
        _text(commands, coord.y_axis.name,
              QRectF(rect.left(), plot.top() - fm.height() - 4, 120, fm.height()),
              font, name_color, QCanvasPainter.TextAlign.Left,
              QCanvasPainter.TextBaseline.Bottom)


def _polar(commands, coord):
    grid_color = QColor(T("color.border"))
    text_color = QColor(T("color.text.secondary"))
    font = coord.radius_axis.label_font()
    fm = QFontMetricsF(font)
    ticks = coord.radius_axis.ticks()
    span = coord.radius_axis.vmax - coord.radius_axis.vmin
    for tick in ticks[1:]:
        fraction = 1.0 if span == 0 else (tick - coord.radius_axis.vmin) / span
        commands.append(("stroke", path_from_qpainter(coord._ring_path(fraction)),
                         QColor(grid_color), 1.0))
    if coord.angle_axis.type == "category" and coord.angle_axis.categories:
        import math
        count = len(coord.angle_axis.categories)
        for index, category in enumerate(coord.angle_axis.categories):
            theta = -math.pi / 2 + index / count * 2 * math.pi
            outer = QPointF(coord.center.x() + coord.radius * math.cos(theta),
                            coord.center.y() + coord.radius * math.sin(theta))
            _line(commands, coord.center, outer, grid_color)
            lx = coord.center.x() + (coord.radius + 14) * math.cos(theta)
            ly = coord.center.y() + (coord.radius + 14) * math.sin(theta)
            _text(commands, category, QRectF(lx - 40, ly - fm.height() / 2, 80, fm.height()),
                  font, text_color, QCanvasPainter.TextAlign.Center,
                  QCanvasPainter.TextBaseline.Middle)
    for tick in ticks[1:]:
        fraction = 1.0 if span == 0 else (tick - coord.radius_axis.vmin) / span
        _text(commands, format_value(tick),
              QRectF(coord.center.x() + 2,
                     coord.center.y() - coord.radius * fraction - fm.height() / 2,
                     48, fm.height()),
              font, text_color, QCanvasPainter.TextAlign.Left,
              QCanvasPainter.TextBaseline.Middle)


def _single_axis(commands, coord):
    axis_color = QColor(T("color.border.strong"))
    grid_color = QColor(T("color.border"))
    text_color = QColor(T("color.text.secondary"))
    font = coord.axis.label_font()
    fm = QFontMetricsF(font)
    _line(commands, QPointF(coord.plot.left(), coord.line_y),
          QPointF(coord.plot.right(), coord.line_y), axis_color)
    for tick in coord.axis.ticks():
        px = coord.axis.map(tick, coord.plot.left(), coord.plot.right())
        _line(commands, QPointF(px, coord.line_y - 4), QPointF(px, coord.line_y + 4),
              grid_color)
        _text(commands, format_value(tick), QRectF(px - 40, coord.line_y + 6, 80, fm.height()),
              font, text_color, QCanvasPainter.TextAlign.Center,
              QCanvasPainter.TextBaseline.Top)
    if coord.axis.name:
        _text(commands, coord.axis.name,
              QRectF(coord.plot.right() + 6, coord.line_y - fm.height() / 2, 80, fm.height()),
              font, QColor(T("color.text.tertiary")), QCanvasPainter.TextAlign.Left,
              QCanvasPainter.TextBaseline.Middle)


def _legend(commands, chart):
    legend = chart.legend
    if not legend.shown or not legend._item_rects:
        return
    font = chart_font(T("font.xs"))
    for (name, fallback), rect in zip(legend._items, legend._item_rects):
        enabled = chart.is_series_visible(name)
        live = legend._item_color(name) if enabled else None
        swatch = QColor(live) if live is not None else QColor(fallback)
        if not enabled:
            swatch = QColor(T("color.text.disabled"))
        text_color = QColor(T("color.text.primary")) if enabled \
            else QColor(T("color.text.disabled"))
        box = QRectF(rect.left(), rect.center().y() - 4.5, 9, 9)
        commands.append(("round_rect", box, 2.0, swatch))
        _text(commands, name, QRectF(box.right() + 5, rect.top(),
                                     rect.width() - 14, rect.height()),
              font, text_color, QCanvasPainter.TextAlign.Left,
              QCanvasPainter.TextBaseline.Middle)


def _title(commands, chart):
    title = chart.title
    rect = QRectF(0, 0, chart.width(), title.height())
    if not title.text or rect.height() <= 0:
        return
    align = str(title.opt.get("left") or "left")
    title_font = chart_font(T("font.title.md"), T("font.weight.semibold"))
    sub_font = chart_font(T("font.sm"))
    fm_title, fm_sub = QFontMetricsF(title_font), QFontMetricsF(sub_font)
    text_width = fm_title.horizontalAdvance(title.text)
    sub_width = fm_sub.horizontalAdvance(title.subtext) if title.subtext else 0.0
    width = max(text_width, sub_width)
    if align == "center":
        x = rect.center().x() - width / 2
    elif align == "right":
        x = rect.right() - width - 8
    else:
        try:
            x = rect.left() + float(align)
        except (TypeError, ValueError):
            x = rect.left() + 8
    y = rect.top() + 2
    _text(commands, title.text, QRectF(x, y, text_width + 4, fm_title.height()),
          title_font, QColor(T("color.text.primary")), QCanvasPainter.TextAlign.Left,
          QCanvasPainter.TextBaseline.Middle)
    if title.subtext:
        y += fm_title.height() + 2
        _text(commands, title.subtext, QRectF(x, y, sub_width + 4, fm_sub.height()),
              sub_font, QColor(T("color.text.secondary")), QCanvasPainter.TextAlign.Left,
              QCanvasPainter.TextBaseline.Middle)


def build_static_scene(chart):
    chart._layout_all()
    commands = [("fill_rect", QRectF(chart.rect()), QColor(T("color.bg.base")))]
    for coord in chart.coords:
        if isinstance(coord, GridCoord):
            _grid(commands, coord)
        elif isinstance(coord, PolarCoord):
            _polar(commands, coord)
        elif isinstance(coord, SingleAxisCoord):
            _single_axis(commands, coord)
        else:
            raise NotImplementedError(f"Canvas 静态轴未实现: {type(coord).__name__}")
    _legend(commands, chart)
    _title(commands, chart)
    return CanvasStaticScene(commands, static_scene_key(chart))
