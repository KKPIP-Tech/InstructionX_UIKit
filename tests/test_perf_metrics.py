# -*- coding: utf-8 -*-
"""固定容量性能指标回归测试（直接运行，不使用 pytest）。"""

import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from InstructionX_UIKit._metrics import MetricRing

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


@check("固定容量样本与精确计数")
def _():
    ring = MetricRing(capacity=2)
    ring.add("paint", 0.001)
    ring.add("paint", 0.003)
    ring.add("paint", 0.005)
    ring.count("hidden_update", 2)
    result = ring.snapshot()
    assert result["paint"]["count"] == 2
    assert abs(result["paint"]["mean"] - 0.004) < 1e-12
    assert result["paint"]["p95"] == 0.005
    assert result["hidden_update"] == 2


@check("空指标与最小容量")
def _():
    ring = MetricRing(capacity=0)
    assert ring.snapshot() == {}
    ring.add("empty", 1.0)
    ring.add("empty", 2.0)
    result = ring.snapshot()
    assert result["empty"]["count"] == 1
    assert result["empty"]["mean"] == 2.0


@check("图表 option、重建与布局指标")
def _():
    from PySide6.QtWidgets import QApplication
    from InstructionX_UIKit.charts import ChartWidget
    from InstructionX_UIKit.theme import ThemeManager

    app = QApplication.instance() or QApplication([])
    ThemeManager.instance().apply(app)
    chart = ChartWidget()
    chart.set_option({"xAxis": {"type": "value"},
                      "yAxis": {"type": "value"},
                      "series": [{"type": "line", "data": [1, 2, 3]}]})
    chart.update_option({"series": [{"type": "line", "data": [2, 3, 4]}]})
    chart.anim.stop()
    chart.anim.set_progress(1.0)
    result = chart._perf_snapshot()
    assert result["option_update_ms"]["count"] == 2, result
    assert result["_rebuild_ms"]["count"] == 2, result
    assert result["layout_ms"]["count"] >= 2, result
    assert result["physical_width"] > 0 and result["physical_height"] > 0
    assert result["backend"]
    chart.close()
    app.quit()


@check("交换帧统计明确判定帧率红线")
def _():
    from tests.perf.run_realtime import frame_metrics

    good = frame_metrics("good", [index / 120 for index in range(121)])
    assert good["pass"] is True, good
    assert good["average_fps"] >= 60
    slow = frame_metrics("slow", [index / 30 for index in range(61)])
    assert slow["pass"] is False, slow
    assert frame_metrics("empty", [0.0])["pass"] is False


if __name__ == "__main__":
    raise SystemExit(1 if _FAILURES else 0)
