# -*- coding: utf-8 -*-
"""Blueprint 网格、边、节点装饰与临时线的 Canvas 原生场景。"""

import math

from PySide6.QtCanvasPainter import QCanvasPainter, QCanvasPath
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainterPath, QPainterPathStroker

from ..theme import T, ThemeManager
from ..charts.canvas_paths import line_path, path_from_qpainter
from ..charts.canvas_static import CanvasStaticScene, _text
from .canvas import GRID_DOT_R
from .edge_widget import bezier_path
from .node_widget import (
    BODY_LINE_H,
    PAD_X,
    PIN_DOT_R,
    PIN_ROW_H,
    SPINNER_SIZE,
    TITLE_H,
    _text_on,
)
from .registry import pin_color

__all__ = ["build_blueprint_scenes", "build_blueprint_flow",
           "blueprint_scene_key", "blueprint_flow_key"]


def _stroke(commands, path, color, width=1.0, cap=QCanvasPainter.LineCap.Square,
            join=QCanvasPainter.LineJoin.Miter):
    commands.append(("stroke_pen", path, QColor(color), float(width), cap, join))


def _circle(commands, center, radius, fill=None, stroke=None, width=1.0):
    path = QCanvasPath(2)
    path.ellipse(QRectF(center.x() - radius, center.y() - radius, radius * 2, radius * 2))
    if fill is not None:
        commands.append(("fill", path, QColor(fill)))
    if stroke is not None:
        _stroke(commands, path, stroke, width)


def _dashed(commands, path, color, width, pattern, offset=0.0):
    stroker = QPainterPathStroker()
    stroker.setWidth(width)
    stroker.setCapStyle(Qt.RoundCap)
    stroker.setDashPattern(pattern)
    stroker.setDashOffset(offset)
    commands.append(("fill", path_from_qpainter(stroker.createStroke(path)), QColor(color)))


def blueprint_scene_key(canvas):
    return (
        repr(canvas.graph.to_dict()), canvas.width(), canvas.height(),
        canvas._zoom, canvas._offset.x(), canvas._offset.y(),
        ThemeManager.instance().mode,
        tuple((node_id, widget._layout_rev, widget._pulse)
              for node_id, widget in canvas._node_widgets.items()),
        tuple(canvas._selected_nodes), tuple(canvas._selected_edges),
        tuple((edge_id, edge.hovered, edge.selected, edge.flowing)
              for edge_id, edge in canvas._edge_widgets.items()),
        None if canvas._wire is None else (
            canvas._wire.start, canvas._wire.end, canvas._wire.magnet),
        repr(canvas._wire_target), repr(canvas._band),
    )


def blueprint_flow_key(canvas):
    return tuple((edge_id, edge._dash_offset)
                  for edge_id, edge in canvas._edge_widgets.items() if edge.flowing)


def _grid_scene(canvas):
    step = 24.0
    while step * canvas._zoom < 18.0:
        step *= 2.0
    while step * canvas._zoom > 72.0:
        step /= 2.0
    step *= canvas._zoom
    ox, oy = canvas._offset.x() % step, canvas._offset.y() % step
    path = QCanvasPath()
    x = ox - math.ceil(ox / step) * step
    while x <= canvas.width() + step:
        y = oy - math.ceil(oy / step) * step
        while y <= canvas.height() + step:
            path.ellipse(QRectF(x - GRID_DOT_R, y - GRID_DOT_R,
                                GRID_DOT_R * 2, GRID_DOT_R * 2))
            y += step
        x += step
    commands = [
        ("fill_rect", QRectF(canvas.rect()), QColor(T("color.bg.base"))),
        ("fill", path, QColor(T("color.border"))),
    ]
    return CanvasStaticScene(commands, ("grid", step, ox, oy, canvas.width(),
                                       canvas.height(), T("color.border"), T("color.bg.base")))


def _selection_glow(commands, canvas):
    if not canvas._selected_nodes:
        return
    spec = ThemeManager.instance().tokens["shadow.md"]
    red, green, blue, alpha = spec["color"]
    blur = float(spec["blur"])
    ox, oy = spec["offset"]
    steps = max(3, int(blur / 2))
    base_radius = float(T("radius.lg")) * canvas._zoom
    for node_id in canvas._selected_nodes:
        node = canvas.graph.node(node_id)
        if node is None:
            continue
        top_left = canvas.scene_to_view(node.pos)
        rect = QRectF(top_left, node.size * canvas._zoom)
        rect.translate(float(ox), float(oy))
        for index in range(steps):
            fraction = (index + 0.5) / steps
            grow = fraction * blur * 0.75
            opacity = int(alpha * (1.0 - fraction) * 0.9)
            if opacity <= 0:
                continue
            radius = base_radius + grow
            _stroke(commands, _rounded(rect.adjusted(-grow, -grow, grow, grow), radius),
                    QColor(red, green, blue, opacity), max(1.0, blur / steps + 0.5))


def _rounded(rect, radius):
    path = QCanvasPath(4)
    path.roundRect(QRectF(rect), radius)
    return path


def _edges(commands, canvas, flowing=None):
    commands.append(("save",))
    commands.append(("translate", QPointF(canvas._offset)))
    commands.append(("scale", canvas._zoom, canvas._zoom))
    for edge in canvas._edge_widgets.values():
        if flowing is not None and edge.flowing != flowing:
            continue
        path = path_from_qpainter(edge.path())
        if edge.flowing:
            _dashed(commands, edge.path(), QColor(T("color.primary")),
                    2.4, [3.0, 3.0], edge._dash_offset)
            continue
        color = QColor(T("color.primary")) if edge.selected else edge._color()
        width = 2.8 if edge.selected else (3.2 if edge.hovered else 2.0)
        _stroke(commands, path, color, width, cap=QCanvasPainter.LineCap.Round)
    commands.append(("restore",))


def _node(commands, canvas, widget):
    node = widget.node
    width, height = node.size.width(), node.size.height()
    radius = float(T("radius.lg"))
    accent = widget.accent_color()
    status = node.status
    commands.append(("save",))
    commands.append(("translate", canvas.scene_to_view(node.pos)))
    commands.append(("scale", canvas._zoom, canvas._zoom))
    source = QPainterPath()
    source.addRoundedRect(QRectF(1.0, 1.0, width - 2.0, height - 2.0), radius, radius)
    path = path_from_qpainter(source)
    commands.append(("fill", path, QColor(T("color.bg.elevated"))))
    band = QPainterPath()
    band.addRoundedRect(QRectF(1.0, 1.0, width - 2.0, TITLE_H + radius), radius, radius)
    clip = QPainterPath()
    clip.addRect(QRectF(1.0, 1.0, width - 2.0, TITLE_H))
    commands.append(("fill", path_from_qpainter(band.intersected(clip)), QColor(accent)))
    _stroke(commands, line_path([QPointF(1.0, TITLE_H), QPointF(width - 1.0, TITLE_H)]),
            QColor(T("color.border")))
    _text(commands, node.title, QRectF(PAD_X, 0.0, width - 2 * PAD_X - 24.0, TITLE_H),
          widget._title_font(), _text_on(accent), QCanvasPainter.TextAlign.Left,
          QCanvasPainter.TextBaseline.Middle)
    if status == "done":
        text = widget.elapsed_text()
        if text:
            rect = widget.badge_rect()
            commands.append(("round_rect", QRectF(rect), rect.height() / 2,
                             QColor(T("color.bg.muted"))))
            font = widget._pin_font()
            _text(commands, text, QRectF(rect), font, QColor(T("color.text.secondary")),
                  QCanvasPainter.TextAlign.Center, QCanvasPainter.TextBaseline.Middle)
    elif status == "error":
        center = QPointF(width - 6.0 - SPINNER_SIZE / 2, TITLE_H / 2)
        radius = SPINNER_SIZE / 2
        _circle(commands, center, radius, fill=QColor(T("color.danger")))
        delta = radius * 0.42
        for start, end in ((QPointF(center.x() - delta, center.y() - delta),
                            QPointF(center.x() + delta, center.y() + delta)),
                           (QPointF(center.x() - delta, center.y() + delta),
                            QPointF(center.x() + delta, center.y() - delta))):
            _stroke(commands, line_path([start, end]), QColor(T("color.on.primary")),
                    1.8, cap=QCanvasPainter.LineCap.Round)
    pin_font = widget._pin_font()
    for pin in node.inputs:
        center = widget.pin_logical_center(pin)
        color = QColor(pin_color(pin.data_type))
        _circle(commands, center, PIN_DOT_R, fill=color)
        if pin.multi:
            _circle(commands, center, PIN_DOT_R + 3.0, stroke=color, width=1.4)
        _text(commands, pin.name,
              QRectF(center.x() + 10.0, center.y() - PIN_ROW_H / 2, width / 2, PIN_ROW_H),
              pin_font, QColor(T("color.text.secondary")), QCanvasPainter.TextAlign.Left,
              QCanvasPainter.TextBaseline.Middle)
    for pin in node.outputs:
        center = widget.pin_logical_center(pin)
        color = QColor(pin_color(pin.data_type))
        _circle(commands, center, PIN_DOT_R, fill=color)
        if pin.multi:
            _circle(commands, center, PIN_DOT_R + 3.0, stroke=color, width=1.4)
        _text(commands, pin.name,
              QRectF(center.x() - 10.0 - width / 2, center.y() - PIN_ROW_H / 2,
                     width / 2, PIN_ROW_H),
              pin_font, QColor(T("color.text.secondary")), QCanvasPainter.TextAlign.Right,
              QCanvasPainter.TextBaseline.Middle)
    if widget._body is None and node.properties:
        y = TITLE_H + max(len(node.inputs), len(node.outputs)) * PIN_ROW_H + 4.0
        for key, value in node.properties.items():
            _text(commands, f"{key}: {value}",
                  QRectF(PAD_X, y, width - 2 * PAD_X, BODY_LINE_H),
                  pin_font, QColor(T("color.text.tertiary")), QCanvasPainter.TextAlign.Left,
                  QCanvasPainter.TextBaseline.Middle)
            y += BODY_LINE_H
    border_color = QColor(T("color.border"))
    border_width = 1.2
    if status == "done":
        border_color = QColor(T("color.success"))
        border_width = 2.0
    elif status == "error":
        border_color = QColor(T("color.danger"))
        border_width = 2.0
    elif status == "running":
        pulse = 0.55 + 0.45 * math.sin(widget._pulse * 2 * math.pi / 0.32)
        border_color = QColor(accent)
        border_color.setAlpha(int(120 + 135 * pulse))
        border_width = 2.0
    if widget._selected:
        border_color = QColor(T("color.primary"))
        border_width = 2.0
    _stroke(commands, path, border_color, border_width)
    commands.append(("restore",))


def _overlay_scene(canvas):
    commands = []
    if canvas._wire is not None:
        wire = canvas._wire
        color = QColor(pin_color(wire.data_type))
        commands.append(("save",))
        commands.append(("translate", QPointF(canvas._offset)))
        commands.append(("scale", canvas._zoom, canvas._zoom))
        path = path_from_qpainter(bezier_path(wire.start, wire.end))
        if wire.magnet:
            _stroke(commands, path, color, 3.0, cap=QCanvasPainter.LineCap.Round)
        else:
            _dashed(commands, bezier_path(wire.start, wire.end), color, 2.0, [4.0, 3.0])
        _circle(commands, wire.end, 3.5, fill=color)
        if canvas._wire_target is not None:
            node_id, pin = canvas._wire_target
            center = canvas.pin_scene_pos(node_id, pin.id, pin.direction)
            _circle(commands, center, 9.0, stroke=QColor(T("color.primary")), width=2.0)
        commands.append(("restore",))
    if canvas._band is not None:
        rect = QRectF(canvas._band[0], canvas._band[1]).normalized()
        fill = QColor(T("color.primary"))
        fill.setAlpha(28)
        border = QColor(T("color.primary"))
        border.setAlpha(140)
        commands.append(("fill", _rounded(rect, 0.0), fill))
        _stroke(commands, _rounded(rect, 0.0), border, 1.2)
    if not commands:
        return None
    return CanvasStaticScene(commands, ("overlay", repr(canvas._wire_target), repr(canvas._band)))


def build_blueprint_flow(canvas):
    if not any(edge.flowing for edge in canvas._edge_widgets.values()):
        return None
    commands = []
    _edges(commands, canvas, flowing=True)
    return CanvasStaticScene(commands, blueprint_flow_key(canvas))


def build_blueprint_scenes(canvas):
    static = _grid_scene(canvas)
    static_commands = list(static.commands)
    _selection_glow(static_commands, canvas)
    _edges(static_commands, canvas, flowing=False)
    static = CanvasStaticScene(static_commands, (static.key, blueprint_scene_key(canvas)))
    commands = []
    for widget in canvas._node_widgets.values():
        _node(commands, canvas, widget)
    component = CanvasStaticScene(commands, blueprint_scene_key(canvas))
    return static, component, _overlay_scene(canvas), blueprint_scene_key(canvas)
