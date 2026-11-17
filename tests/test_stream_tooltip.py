# -*- coding: utf-8 -*-
"""回归：实时滚动数据 tooltip 的轴反查、采样与原始数据取值。"""

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")

import numpy as np  # noqa: E402
from PySide6.QtCore import QPointF  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from InstructionX_UIKit.charts import ChartWidget  # noqa: E402
from InstructionX_UIKit.charts.core import format_value  # noqa: E402
from InstructionX_UIKit.theme import ThemeManager  # noqa: E402

app = QApplication(sys.argv)
ThemeManager.instance().apply(app)
errors = []


def check_stream(count, target):
    chart = ChartWidget()
    chart.resize(1000, 420)
    chart.set_option({
        "animation": False,
        "tooltip": {"trigger": "axis"},
        "xAxis": {"type": "category", "data": []},
        "yAxis": {"type": "value", "min": 0, "max": count - 1},
        "series": [{"type": "line", "name": "stream", "data": [],
                    "showSymbol": False}],
    })
    chart.show()
    app.processEvents()
    session = chart.stream(series="stream", window=count,
                           interval=0.01, auto_scale=False)
    session.write(np.arange(count, dtype=np.float64))
    session._on_tick()
    app.processEvents()
    chart.anim.stop()
    chart.anim.set_progress(1.0)
    chart._layout_all(force=True)
    chart.grab()
    coord = chart.primary_coord()
    x = coord.x_axis.map(target, coord.plot.left(), coord.plot.right())
    point = QPointF(x, coord.plot.center().y())

    chart._update_tooltip(point)
    direct_lines = chart.tooltip._lines
    direct = direct_lines[-1][2] if direct_lines else None
    QTest.mouseMove(chart._viewport, point.toPoint())
    app.processEvents()
    lines = chart.tooltip._lines
    actual = lines[-1][2] if lines else None
    expected = format_value(float(target))
    print(f"点数={count} 目标下标={target} 期望={expected} 精确坐标={direct} "
          f"整数像素={actual} 采样项数={len(chart.series_renderers[0]._entries)}",
          flush=True)
    if direct != expected:
        errors.append(f"{count} 点精确坐标：{direct!r} != {expected!r}")
    if actual is None or abs(int(actual.replace(",", "")) - target) > 1:
        errors.append(f"{count} 点真实像素超出相邻 band：{actual!r}")
    session.close()
    chart.close()
    app.processEvents()


check_stream(20, 7)
check_stream(20000, 10000)
if errors:
    print("[失败] " + "；".join(errors))
    sys.exit(1)
print("[通过] 实时流在未采样与采样场景均返回正确原始数据值")
