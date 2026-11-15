# -*- coding: utf-8 -*-
"""Canvas 虚线按原路径弧长切分，不依赖整块描边轮廓。"""

import os
from pathlib import Path
import sys
import traceback

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPointF
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


@check("直线虚线保留长度、间隔与正负相位")
def _():
    from InstructionX_UIKit.charts.canvas_paths import dashed_paths
    path = QPainterPath(QPointF(0, 0))
    path.lineTo(100, 0)
    for offset, expected_start, expected_end in (
            (0.0, 0.0, 3.0), (1.5, 0.0, 1.5), (-1.5, 1.5, 4.5)):
        paths = dashed_paths(path, [3.0, 3.0], offset)
        assert len(paths) == 17, (offset, len(paths))
        first = paths[0]
        start, end = first.positionAt(0), first.positionAt(1)
        assert abs(start.x() - expected_start) < 1e-9, (offset, start)
        assert abs(end.x() - expected_end) < 1e-9, (offset, end)
        assert all(item.commandsSize() >= 2 for item in paths)


@check("贝塞尔虚线只产生可见线段并覆盖全部相位")
def _():
    from InstructionX_UIKit.charts.canvas_paths import dashed_paths
    path = QPainterPath(QPointF(0, 0))
    path.cubicTo(QPointF(30, -80), QPointF(90, 80), QPointF(140, 0))
    paths = dashed_paths(path, [4.0, 3.0], -1.6)
    assert paths
    first = paths[0]
    start = first.positionAt(0)
    end = first.positionAt(first.commandsSize() - 1)
    for point, fraction in ((start, 1.6), (end, 5.6)):
        expected = path.pointAtPercent(fraction / path.length())
        assert (point - expected).manhattanLength() < 1e-6, (point, expected)
    assert all(path.commandsSize() >= 2 for path in paths)


if __name__ == "__main__":
    raise SystemExit(1 if _FAILURES else 0)
