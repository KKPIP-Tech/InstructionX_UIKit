# -*- coding: utf-8 -*-
"""visualMap 等 Chart 组件的 Canvas 原生绘制场景。"""

from PySide6.QtCanvasPainter import QCanvasLinearGradient, QCanvasPainter, QCanvasPath
from PySide6.QtCore import QRectF
from PySide6.QtGui import QColor, QFontMetricsF

from ..theme import T, ThemeManager
from .axes import chart_font, format_value
from .canvas_marks import append_native_components, is_native_component, native_component_key
from .canvas_static import CanvasStaticScene, _text
from .interact import VisualMapComponent, _VM_GAP, _VM_LABEL_H, _VM_LABEL_W

__all__ = ["build_component_scene", "component_scene_key"]


def _visual_map(commands, component):
    bar = QRectF(component._bar)
    if bar.isNull():
        return
    colors = component.colors()
    if component.orient == "vertical":
        gradient = QCanvasLinearGradient(bar.topLeft(), bar.bottomLeft())
    else:
        gradient = QCanvasLinearGradient(bar.topLeft(), bar.topRight())
    for index, color in enumerate(colors):
        fraction = index / (len(colors) - 1) if len(colors) > 1 else 0.0
        gradient.setColorAt(1.0 - fraction if component.orient == "vertical" else fraction,
                            QColor(color))
    path = QCanvasPath(4)
    path.roundRect(bar, 3.0)
    commands.append(("gradient_path", bar, path, gradient,
                     QColor(T("color.border")), 1.0))
    font = chart_font(T("font.xs"))
    fm = QFontMetricsF(font)
    color = QColor(T("color.text.secondary"))
    hi, lo = format_value(component.max), format_value(component.min)
    if component.orient == "vertical":
        _text(commands, hi,
              QRectF(bar.right() + _VM_GAP, bar.top() - fm.height() / 2,
                     _VM_LABEL_W, fm.height()),
              font, color, QCanvasPainter.TextAlign.Left, QCanvasPainter.TextBaseline.Middle)
        _text(commands, lo,
              QRectF(bar.right() + _VM_GAP, bar.bottom() - fm.height() / 2,
                     _VM_LABEL_W, fm.height()),
              font, color, QCanvasPainter.TextAlign.Left, QCanvasPainter.TextBaseline.Middle)
    else:
        _text(commands, lo,
              QRectF(bar.left() - 38, bar.top() - _VM_LABEL_H, 34, _VM_LABEL_H),
              font, color, QCanvasPainter.TextAlign.Right, QCanvasPainter.TextBaseline.Middle)
        _text(commands, hi,
              QRectF(bar.right() + 4, bar.top() - _VM_LABEL_H, 34, _VM_LABEL_H),
              font, color, QCanvasPainter.TextAlign.Left, QCanvasPainter.TextBaseline.Middle)


def _check_components(chart):
    for component in chart.components:
        if isinstance(component, VisualMapComponent) or is_native_component(component):
            continue
        if callable(getattr(component, "paint", None)):
            raise NotImplementedError(
                f"Canvas 组件未实现: {type(component).__name__}")


def component_scene_key(chart):
    _check_components(chart)
    result = []
    for component in chart.components:
        if isinstance(component, VisualMapComponent):
            rect = component._bar
            result.append((id(component), component.min, component.max, component.orient,
                           tuple(component.colors()),
                           (rect.left(), rect.top(), rect.width(), rect.height())))
    return ThemeManager.instance().mode, tuple(result), native_component_key(chart)


def build_component_scene(chart):
    key = component_scene_key(chart)
    if not key[1] and not key[2]:
        return None
    commands = []
    for component in chart.components:
        if isinstance(component, VisualMapComponent):
            _visual_map(commands, component)
    append_native_components(commands, chart)
    return CanvasStaticScene(commands, key)
