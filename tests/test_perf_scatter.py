# -*- coding: utf-8 -*-
"""散点零复制、第三维点径与聚合下标回归（直接运行）。"""

import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import numpy as np
from PySide6.QtWidgets import QApplication

from InstructionX_UIKit.charts import ChartWidget
from InstructionX_UIKit.charts.sampling import column_aggregate
from InstructionX_UIKit.theme import ThemeManager

_FAILURES = []
app = QApplication.instance() or QApplication(sys.argv)
ThemeManager.instance().apply(app)


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


def make_scatter(data, extra=None):
    chart = ChartWidget()
    chart.resize(800, 400)
    option = {"xAxis": {"type": "value"}, "yAxis": {"type": "value"}}
    series = {"type": "scatter", "large": False, "data": data}
    series.update(extra or {})
    option["series"] = [series]
    chart.set_option(option)
    chart.anim.stop()
    chart.anim.set_progress(1.0)
    return chart, chart.series_renderers[0]


@check("聚合显式保存真实原始下标")
def _():
    x_values = np.array([100, 200, 400, 800, 1600, 3200, 6400,
                         12800, 25600, 51200, 102400, 204800, 409600,
                         819200, 1638400, 3276800, 6553600, 13107200,
                         26214400, 52428800], dtype=np.float64)
    buckets, done = column_aggregate(np.arange(20, dtype=np.float64), 4,
                                     x_values=x_values)
    assert done
    assert [bucket["index"] for bucket in buckets] == [2, 7, 12, 17]
    assert [bucket["x"] for bucket in buckets] == [400, 12800, 409600,
                                                   13107200]


@check("结构型数据不支持聚合时精确回退")
def _():
    buckets, done = column_aggregate([[0, 1], [10, 2], [20, 3]], 2)
    assert buckets is None and done is False


@check("散点布局不调用 data() 且第三维点径与命中下标不变")
def _():
    data = [[index, index % 17, index % 5 + 1] for index in range(100)]
    chart, renderer = make_scatter(data, {"symbolSize": [6, 24]})
    renderer.data = lambda: (_ for _ in ()).throw(
        AssertionError("热路径禁止 data() 复制"))
    chart._layout_all(force=True)
    assert len(renderer._dots) == len(data)
    assert len({dot["r"] for dot in renderer._dots}) > 1
    assert [dot["index"] for dot in renderer._dots] == list(range(100))
    hit = renderer.hit_test(renderer._dots[7]["pt"])
    assert hit["dataIndex"] == 7
    chart.close()


@check("数值聚合点的 tooltip 返回真实 dataIndex")
def _():
    chart, renderer = make_scatter(np.arange(5000, dtype=np.float64),
                                   {"large": True})
    chart._layout_all(force=True)
    assert renderer._aggregated and renderer._dots
    for dot in renderer._dots:
        hit = renderer.hit_test(dot["pt"])
        assert hit["dataIndex"] == dot["index"]
        assert hit["dataIndex"] >= 0
    chart.close()


if __name__ == "__main__":
    app.quit()
    raise SystemExit(1 if _FAILURES else 0)
