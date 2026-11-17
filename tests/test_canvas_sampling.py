# -*- coding: utf-8 -*-
"""Canvas 数值采样与按需回读回归（直接运行，不使用 pytest）。"""

import os
from pathlib import Path
import sys
import traceback

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")

import numpy as np
from PySide6.QtWidgets import QApplication
from InstructionX_UIKit.charts.canvas_viewport import CanvasLineChartViewport
from InstructionX_UIKit.charts.sampling import bucket_sample, sample_indices
from InstructionX_UIKit.charts.series_cartesian import _pin_endpoints

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


@check("数值采样下标逐项保持原像素桶与端点语义")
def _():
    rng = np.random.default_rng(20261115)
    for n, buckets in ((20000, 1197), (20001, 997), (997, 331), (3, 2)):
        values = rng.normal(size=n)
        if n > 10:
            values[[0, 4, -1]] = np.nan
        entries, _count = bucket_sample(values, buckets)
        expected = [x for x, _y in _pin_endpoints(entries, values, None)]
        actual = sample_indices(values, buckets).tolist()
        assert actual == expected, (n, buckets, actual[:20], expected[:20])


@check("未请求回读时不创建离屏画布")
def _():
    from InstructionX_UIKit.charts import ChartWidget
    chart = ChartWidget()
    chart.set_option({"series": [{"type": "line", "data": [1, 2, 3]}]})
    viewport = CanvasLineChartViewport(chart, parent=chart)
    try:
        viewport.prePaint(None)
        assert viewport._canvas is None
    finally:
        viewport.close()
        chart.close()


if __name__ == "__main__":
    app.quit()
    raise SystemExit(1 if _FAILURES else 0)
