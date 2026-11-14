# -*- coding: utf-8 -*-
"""原 gpuDirect 选项在 RHI 后端的兼容、像素与资源生命周期（离屏）。"""

import os
import sys
import traceback
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np
from PySide6.QtGui import QImage, QPainter
from PySide6.QtWidgets import QApplication

from InstructionX_UIKit.charts import ChartWidget
from InstructionX_UIKit.charts.scene_item import ChartSceneItem
from InstructionX_UIKit.charts.scene_snapshot import build_scene_snapshot
from InstructionX_UIKit.theme import ThemeManager

app = QApplication.instance() or QApplication(sys.argv)
ThemeManager.instance().apply(app)
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


def make_renderer(extra=None):
    chart = ChartWidget()
    chart.resize(640, 360)
    series = {"type": "line", "data": np.arange(300, dtype=np.float64),
              "gpuDirect": True, "gpuVersion": 1, "showSymbol": False}
    series.update(extra or {})
    chart.set_option({"animation": False, "xAxis": {"type": "value"},
                      "yAxis": {"type": "value", "min": -10, "max": 310},
                      "series": [series]})
    chart.anim.stop()
    chart.anim.set_progress(1.0)
    chart._layout_all(force=True)
    return chart, chart.series_renderers[0]


def reference(chart, dpr=1.0):
    image = QImage(round(chart.width() * dpr), round(chart.height() * dpr),
                   QImage.Format_RGBA8888)
    image.setDevicePixelRatio(dpr)
    image.fill(0)
    painter = QPainter(image)
    try:
        chart._paint_contents(painter)
    finally:
        painter.end()
    return image.convertToFormat(QImage.Format_RGBA8888)


@check("gpuDirect 与显式版本在流式更新中原样保留")
def _():
    chart, renderer = make_renderer()
    assert renderer.gpu_direct
    assert not chart.gpu_claims(renderer)
    chart.set_gpu_owner([renderer])
    assert chart.gpu_claims(renderer)
    chart.set_gpu_owner(None)
    assert not chart.gpu_claims(renderer)
    values = np.arange(300, dtype=np.float64) + 10
    assert chart.set_stream_data(values, series=0)
    assert chart.series_renderers[0] is renderer
    assert renderer.gpu_direct
    option = chart.option()["series"][0]
    assert option["gpuDirect"] is True
    assert option["gpuVersion"] == 1
    assert option["data"] == values.tolist()
    chart.close()


@check("全部视觉样式由 RHI 快照无缺失呈现")
def _():
    for extra in ({"smooth": True}, {"step": "middle"}, {"areaStyle": {}},
                  {"showSymbol": True}, {"lineStyle": {"type": "dashed"}},
                  {"lineStyle": {"width": 6, "color": "#C08A3E"}}):
        chart, _renderer = make_renderer(extra)
        snapshot = build_scene_snapshot(chart, 1.5)
        assert snapshot.image.convertToFormat(QImage.Format_RGBA8888) == reference(chart, 1.5), extra
        chart.close()


@check("固定轴更新保留静态层并生成独立帧版本")
def _():
    chart, _renderer = make_renderer()
    first = build_scene_snapshot(chart, 1.0)
    assert chart.set_stream_data(np.arange(300, dtype=np.float64) + 1, series=0)
    build_scene_snapshot(chart, 1.0)
    static_key = chart._static_key
    assert chart.set_stream_data(np.arange(300, dtype=np.float64) + 2, series=0)
    second = build_scene_snapshot(chart, 1.0)
    assert second.version != first.version
    assert second.image is not first.image
    assert chart._static_key == static_key
    chart.close()


@check("清空保留可复用节点并仅失效纹理版本")
def _():
    chart, _renderer = make_renderer()
    snapshot = build_scene_snapshot(chart, 1.0)
    item = ChartSceneItem()
    node = object()
    texture = object()
    item._node = node
    item._texture = texture
    item._texture_key = snapshot.version
    item._snapshot = snapshot
    item.clear()
    assert item._snapshot is None
    assert item._node is node
    assert item._texture is texture
    assert item._texture_key is None
    assert len(item._frames) <= 3
    chart.close()


@check("旧 GL 管线与顶点接口已完全退出")
def _():
    assert not (ROOT / "InstructionX_UIKit" / "charts" / "gl_series.py").exists()
    chart, renderer = make_renderer()
    assert not hasattr(renderer, "gpu_vertex_data")
    assert not hasattr(renderer, "gpu_transform")
    source = (ROOT / "InstructionX_UIKit" / "charts" / "viewport.py").read_text(
        encoding="utf-8")
    assert "QOpenGLWidget" not in source
    assert "_GLViewport" not in source
    chart.close()


if __name__ == "__main__":
    raise SystemExit(1 if _FAILURES else 0)
