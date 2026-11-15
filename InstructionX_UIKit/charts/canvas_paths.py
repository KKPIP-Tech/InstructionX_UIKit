# -*- coding: utf-8 -*-
"""Canvas 原生折线路径（GPU 渲染实施计划 Task 1）。

仅转换几何与断点，不创建位图；实际绘制由 QCanvasPainter / QRhi 完成。
"""

from PySide6.QtCanvasPainter import QCanvasPath
from PySide6.QtCore import QPointF
from PySide6.QtGui import QPainterPath

__all__ = ["line_path", "line_paths", "path_from_qpainter"]


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


def path_from_qpainter(path: QPainterPath, close=False) -> QCanvasPath:
    """保留 ``QPainterPath`` 的直线与三次贝塞尔命令及点序。"""
    command_count = sum(path.elementAt(index).type != QPainterPath.CurveToDataElement
                        for index in range(path.elementCount()))
    result = QCanvasPath(command_count, path.elementCount() * 2)
    for index in range(path.elementCount()):
        element = path.elementAt(index)
        point = QPointF(element.x, element.y)
        if element.type == QPainterPath.MoveToElement:
            result.moveTo(point)
        elif element.type == QPainterPath.LineToElement:
            result.lineTo(point)
        elif element.type == QPainterPath.CurveToElement:
            control2 = path.elementAt(index + 1)
            end = path.elementAt(index + 2)
            result.bezierCurveTo(point, QPointF(control2.x, control2.y),
                                 QPointF(end.x, end.y))
    if close:
        result.closePath()
    return result
