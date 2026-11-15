# -*- coding: utf-8 -*-
"""Canvas 原生折线路径（GPU 渲染实施计划 Task 1）。

仅转换几何与断点，不创建位图；实际绘制由 QCanvasPainter / QRhi 完成。
"""

from PySide6.QtCanvasPainter import QCanvasPath

__all__ = ["line_path", "line_paths"]


def line_path(points) -> QCanvasPath:
    """按原顺序构造一条路径，保留重复点、浮点坐标与逆序点。"""
    path = QCanvasPath(len(points))
    if not points:
        return path
    path.moveTo(points[0])
    for point in points[1:]:
        path.lineTo(point)
    return path


def line_paths(points) -> list[QCanvasPath]:
    """按 ``None`` 断点拆分路径，不补线，也不插入伪造数据点。"""
    paths = []
    segment = []
    for point in points:
        if point is None:
            if segment:
                paths.append(line_path(segment))
                segment = []
        else:
            segment.append(point)
    if segment:
        paths.append(line_path(segment))
    return paths
