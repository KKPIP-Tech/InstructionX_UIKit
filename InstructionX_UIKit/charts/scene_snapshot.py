# -*- coding: utf-8 -*-
"""图表局部 Scene Graph 的不可变 UI 线程快照。"""

from dataclasses import dataclass

import numpy as np
from PySide6.QtCore import QRectF
from PySide6.QtGui import QColor, QImage, QPainter, QPixmap

from ..theme import T
from .axes import GridCoord


@dataclass(frozen=True)
class SceneLine:
    vertices: object
    color: QColor
    width: float


@dataclass(frozen=True)
class SceneSnapshot:
    static_image: QImage
    static_key: object
    background: QColor
    plot: QRectF
    width: int
    height: int
    lines: tuple
    version: int


_VERSION = 0


def quick_capability(chart) -> bool:
    """当前 option 是否能不缺失任何可见功能地进入局部 Scene Graph。"""
    if chart._resize_preview.snapshot is not None or chart.overload_limited():
        return False
    if chart.anim.is_running() or abs(chart.anim.t - 1.0) > 1e-9:
        return False
    if chart.tooltip.active or chart._components or len(chart._coords) != 1:
        return False
    if not isinstance(chart.primary_coord(), GridCoord):
        return False
    from .series_cartesian import LineSeriesRenderer
    for renderer in chart.series_renderers:
        if not isinstance(renderer, LineSeriesRenderer):
            return False
        if not renderer.visible:
            continue
        option = renderer.opt
        if option.get("smooth") or option.get("step") or "areaStyle" in option:
            return False
        if option.get("showSymbol", True) is not False:
            return False
        style = option.get("lineStyle") or {}
        if str(style.get("type") or "solid") not in ("solid", ""):
            return False
    return True


def build_scene_snapshot(chart, dpr: float) -> SceneSnapshot:
    """在 UI 线程取得静态层、采样后屏幕点和样式；渲染线程不再读图表。"""
    global _VERSION
    if not quick_capability(chart):
        raise ValueError("当前 option 不满足 Scene Graph 能力门禁")
    chart._layout_all()
    dpr = max(1.0, float(dpr))
    device = QPixmap(1, 1)
    device.setDevicePixelRatio(dpr)
    painter = QPainter(device)
    try:
        static = chart._static_pixmap(painter)
    finally:
        painter.end()
    lines = []
    for renderer in chart.series_renderers:
        if not renderer.visible:
            continue
        style = renderer.opt.get("lineStyle") or {}
        color = (QColor(style["color"])
                 if isinstance(style.get("color"), str) and style["color"]
                 else renderer.color())
        try:
            width = float(style.get("width", 2.0) or 2.0)
        except (TypeError, ValueError):
            width = 2.0
        segment = []
        for point in renderer._points:
            if point is None:
                if len(segment) >= 2:
                    lines.append(SceneLine(
                        np.asarray(segment, dtype=np.float32), QColor(color), width))
                segment = []
                continue
            segment.append((point.x(), point.y()))
        if len(segment) >= 2:
            lines.append(SceneLine(
                np.asarray(segment, dtype=np.float32), QColor(color), width))
    _VERSION += 1
    return SceneSnapshot(
        static_image=static.toImage() if static is not None else None,
        static_key=(chart._static_key, chart._static_dpr),
        background=QColor(T("color.bg.base")),
        plot=QRectF(chart.primary_coord().plot),
        width=chart.width(),
        height=chart.height(),
        lines=tuple(lines),
        version=_VERSION,
    )
