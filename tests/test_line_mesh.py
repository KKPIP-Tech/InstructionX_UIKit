# -*- coding: utf-8 -*-
"""RHI 折线三角网格与顶点缓冲回归（直接运行，不使用 pytest）。"""

from pathlib import Path
import sys
import traceback

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np
from PySide6.QtQuick import QSGGeometry
from InstructionX_UIKit.charts.line_mesh import geometry_points, line_mesh

_FAILURES = []


def check(name):
    def decorate(function):
        try:
            function()
            print(f"  [通过] {name}")
        except Exception:
            _FAILURES.append(name)
            print(f"  [失败] {name}")
            traceback.print_exc()
    return decorate


@check("线段和圆接头保持线宽与坐标范围")
def _():
    vertices = line_mesh(np.array([0., 10., 10.]), np.array([0., 0., 10.]), 2., 8)
    assert vertices.shape == (84, 2)
    assert np.isfinite(vertices).all()
    assert np.allclose(vertices.min(axis=0), [-1., -1.])
    assert np.allclose(vertices.max(axis=0), [11., 11.])


@check("纯零长线段不产生墨迹")
def _():
    assert line_mesh(np.array([0., 0.]), np.array([0., 0.]), 2.).shape == (0, 2)
    vertices = line_mesh(np.array([0., 0., 1.]), np.array([0., 0., 0.]), 2., 8)
    assert vertices.shape == (54, 2)


@check("顶点视图直接写入 QSGGeometry 自有内存")
def _():
    expected = np.array([[1., 2.], [3., 4.], [5., 6.]], dtype=np.float32)
    geometry = QSGGeometry(QSGGeometry.defaultAttributes_Point2D(), 3)
    view = geometry_points(geometry)
    view[:] = expected
    geometry.markVertexDataDirty()
    assert np.array_equal(view, expected)
    assert [(point.x, point.y) for point in geometry.vertexDataAsPoint2D()] == [
        (1., 2.), (3., 4.), (5., 6.)]


if __name__ == "__main__":
    raise SystemExit(1 if _FAILURES else 0)
