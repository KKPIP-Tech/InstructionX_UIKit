# -*- coding: utf-8 -*-
"""NumPy 屏幕坐标通过 Qt 原生数据流批量构造路径。"""

import os
from pathlib import Path
import sys
import traceback

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
from PySide6.QtGui import QPainterPath

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


@check("批量路径逐点保持坐标、顺序和空输入")
def _():
    from InstructionX_UIKit.charts.canvas_paths import array_painter_path
    xs = np.array([1.0, 3.5, -2.0, 7.25], dtype=np.float64)
    ys = np.array([2.0, 4.5, 8.0, -1.25], dtype=np.float64)
    path = array_painter_path(xs, ys)
    assert isinstance(path, QPainterPath)
    assert path.elementCount() == len(xs)
    for index, (x, y) in enumerate(zip(xs, ys)):
        element = path.elementAt(index)
        assert element.x == x and element.y == y, (index, element, x, y)
    assert array_painter_path([], []).isEmpty()


if __name__ == "__main__":
    raise SystemExit(1 if _FAILURES else 0)
