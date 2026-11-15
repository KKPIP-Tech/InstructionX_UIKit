# -*- coding: utf-8 -*-
"""Canvas 折线路径构造回归（直接运行，不使用 pytest）。"""

import os
from pathlib import Path
import sys
import traceback

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")

from PySide6.QtCore import QPointF
from PySide6.QtWidgets import QApplication
from InstructionX_UIKit.charts.canvas_paths import line_path, line_paths, path_from_qpainter

_FAILURES = []
app = QApplication.instance() or QApplication(sys.argv)


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


@check("空输入返回空路径")
def _():
    path = line_path([])
    assert path.isEmpty()
    assert path.commandsSize() == 0
    assert path.commandsDataSize() == 0


@check("单点保留坐标")
def _():
    path = line_path([QPointF(4.5, 8.25)])
    assert path.commandsSize() == 1
    assert path.commandsDataSize() == 2
    point = path.currentPosition()
    assert point.x() == 4.5 and point.y() == 8.25


@check("重复点与逆序点不被改写")
def _():
    points = [QPointF(8, 2), QPointF(8, 2), QPointF(1, 9), QPointF(-3, 4)]
    path = line_path(points)
    assert path.commandsSize() == len(points)
    assert path.commandsDataSize() == len(points) * 2
    point = path.currentPosition()
    assert point.x() == -3 and point.y() == 4


@check("None 按原顺序拆分为独立路径")
def _():
    paths = line_paths([
        None,
        QPointF(1, 1), None, None,
        QPointF(2, 2), QPointF(3, 3), QPointF(4, 4),
        None,
    ])
    assert len(paths) == 2
    assert [path.commandsSize() for path in paths] == [1, 3]
    assert [path.commandsDataSize() for path in paths] == [2, 6]
    assert paths[0].currentPosition().x() == 1
    assert paths[1].currentPosition().x() == 4


@check("全 None 与空输入都不产生路径")
def _():
    assert line_paths([]) == []
    assert line_paths([None, None]) == []


@check("QPainterPath 直线与三次贝塞尔命令完整转换")
def _():
    from PySide6.QtGui import QPainterPath

    source = QPainterPath(QPointF(1, 2))
    source.lineTo(3, 4)
    source.cubicTo(QPointF(5, 6), QPointF(7, 8), QPointF(9, 10))
    path = path_from_qpainter(source)
    assert path.commandsSize() == 3
    assert path.commandsDataSize() == 10
    point = path.currentPosition()
    assert point.x() == 9 and point.y() == 10


if __name__ == "__main__":
    app.quit()
    raise SystemExit(1 if _FAILURES else 0)
