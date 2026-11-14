# -*- coding: utf-8 -*-
"""gpuDirect 显式版本、能力门禁与逐系列状态回归（离屏，不代表真实 GL 性能）。"""

import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import numpy as np
from PySide6.QtWidgets import QApplication

from InstructionX_UIKit.charts import ChartWidget
from InstructionX_UIKit.charts.gl_series import GLSeriesPipeline
from InstructionX_UIKit.charts.viewport import _GLViewport
from InstructionX_UIKit.theme import ThemeManager
import InstructionX_UIKit.charts.series_cartesian as cartesian

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


def make_renderer(extra=None):
    chart = ChartWidget()
    chart.resize(640, 360)
    series = {"type": "line", "data": np.arange(300, dtype=np.float64),
              "gpuDirect": True, "showSymbol": False}
    series.update(extra or {})
    chart.set_option({"xAxis": {"type": "value"},
                      "yAxis": {"type": "value"}, "series": [series]})
    chart.anim.stop()
    chart.anim.set_progress(1.0)
    return chart, chart.series_renderers[0]


@check("显式版本不变时复用顶点，递增时才重新转换")
def _():
    chart, renderer = make_renderer()
    original = cartesian._to_data_vertices
    calls = []

    def counted(data):
        calls.append(1)
        return original(data)

    cartesian._to_data_vertices = counted
    try:
        first = renderer.gpu_vertex_data()
        second = renderer.gpu_vertex_data()
        assert first["vertices"] is second["vertices"]
        assert len(calls) == 1, calls
        renderer.opt["gpuVersion"] = 2
        third = renderer.gpu_vertex_data()
        assert third["version"] != second["version"]
        assert len(calls) == 2, calls
    finally:
        cartesian._to_data_vertices = original
    chart.close()


@check("未实现的视觉样式禁止 gpuDirect")
def _():
    for extra in ({"smooth": True}, {"step": "middle"},
                  {"areaStyle": {}}, {"showSymbol": True},
                  {"lineStyle": {"type": "dashed"}}):
        chart, renderer = make_renderer(extra)
        assert renderer.gpu_vertex_data() is None, extra
        assert renderer.gpu_transform(chart.primary_coord()) is None, extra
        chart.close()


@check("上传计数和字节数只记录实际上传")
def _():
    class Buffer:
        def __init__(self):
            self.allocations = []

        def bind(self):
            return None

        def allocate(self, data, size):
            self.allocations.append((data, size))

        def release(self):
            return None

    pipeline = GLSeriesPipeline()
    pipeline._ready = True
    pipeline._vbo = Buffer()
    points = np.array([[0, 0], [1, 1], [2, 2]], dtype=np.float32)
    assert pipeline.set_vertices(points, version=1)
    assert not pipeline.set_vertices(points, version=1)
    assert pipeline.upload_count == 1
    assert pipeline.uploaded_bytes == points.nbytes
    assert pipeline.set_vertices(points, version=2)
    assert pipeline.upload_count == 2
    assert pipeline.uploaded_bytes == points.nbytes * 2
    assert pipeline.vertex_count == 3


@check("每个系列持有独立管线且同系列复用")
def _():
    chart, first = make_renderer()
    second = first.__class__(chart, dict(first.opt))
    viewport = _GLViewport(chart)

    class Context:
        @staticmethod
        def isValid():
            return True

    viewport.context = lambda: Context()
    original = GLSeriesPipeline.ensure
    GLSeriesPipeline.ensure = lambda self, _context: setattr(self, "_ready", True) or True
    try:
        pipe_a = viewport.ensure_gpu_pipeline(first)
        pipe_b = viewport.ensure_gpu_pipeline(second)
        assert pipe_a is not pipe_b
        assert viewport.ensure_gpu_pipeline(first) is pipe_a
        assert viewport.ensure_gpu_pipeline(second) is pipe_b
    finally:
        GLSeriesPipeline.ensure = original
        viewport.close()
        chart.close()


if __name__ == "__main__":
    app.quit()
    raise SystemExit(1 if _FAILURES else 0)
