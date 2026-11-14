# -*- coding: utf-8 -*-
"""局部 Scene Graph 图表的能力门禁与真实窗口几何回归。"""

import os
import sys
import time
import traceback
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
if os.environ.get("UIKIT_REAL"):
    os.environ.pop("QT_QPA_PLATFORM", None)
os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np
from PySide6.QtWidgets import QApplication

if os.environ.get("UIKIT_REAL"):
    from PySide6.QtQuick import QQuickWindow, QSGRendererInterface
    QQuickWindow.setGraphicsApi(QSGRendererInterface.GraphicsApi.OpenGL)

from InstructionX_UIKit.charts import ChartWidget
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


def pump(ms):
    deadline = time.monotonic() + ms / 1000
    while time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.004)


def wait_until(predicate, timeout=2.0):
    deadline = time.monotonic() + timeout
    while not predicate() and time.monotonic() < deadline:
        pump(10)
    if not predicate():
        raise AssertionError("等待 Scene Graph 完成超时")


def make_chart(series=None):
    values = np.sin(np.arange(1000, dtype=np.float64) * 0.02)
    item = {"type": "line", "name": "原生实线", "data": values,
            "showSymbol": False}
    item.update(series or {})
    chart = ChartWidget()
    chart.set_option({
        "animation": False,
        "xAxis": {"type": "value"},
        "yAxis": {"type": "value"},
        "series": [item],
    })
    chart.anim.stop()
    chart.anim.set_progress(1.0)
    chart.resize(640, 360)
    return chart, values


@check("仅普通实线进入 Scene Graph 快照")
def _():
    from InstructionX_UIKit.charts.scene_snapshot import quick_capability

    chart, _values = make_chart()
    assert quick_capability(chart), (chart, "普通实线应受支持")
    for option in ({"smooth": True}, {"step": "middle"}, {"areaStyle": {}},
                   {"showSymbol": True}, {"lineStyle": {"type": "dashed"}}):
        chart, _values = make_chart(option)
        assert not quick_capability(chart), option
        chart.close()
    chart, _values = make_chart({"type": "scatter"})
    assert not quick_capability(chart)
    chart.close()


@check("快照只包含当前屏幕几何与样式")
def _():
    from InstructionX_UIKit.charts.scene_snapshot import build_scene_snapshot

    chart, _values = make_chart()
    chart._layout_all()
    snapshot = build_scene_snapshot(chart, 1.0)
    assert snapshot.lines
    first = snapshot.lines[0]
    assert first.vertices.shape[1] == 2
    assert first.vertices.dtype == np.float32
    assert first.width == 2.0
    assert first.color.name() == chart.series_renderers[0].color().name()
    assert snapshot.static_image is not None
    chart.close()


@check("offscreen 精确回退到已有 QWidget 后端")
def _():
    if os.environ.get("UIKIT_REAL"):
        return
    os.environ["UIKIT_CHART_BACKEND"] = "quick"
    chart, _values = make_chart()
    assert type(chart._viewport).__name__ == "_RasterViewport"
    chart.show()
    pump(60)
    assert not chart.grab().isNull()
    chart.close()
    os.environ.pop("UIKIT_CHART_BACKEND", None)


@check("真实 QQuickView 几何与 option 变化回退")
def _():
    if not os.environ.get("UIKIT_REAL"):
        return
    from InstructionX_UIKit.charts.viewport import create_viewport

    os.environ["UIKIT_CHART_BACKEND"] = "quick"
    chart, values = make_chart()
    chart.move(80, 60)
    chart.show()
    viewport = chart._viewport
    swaps = []
    viewport.frameSwapped.connect(lambda: swaps.append(1))
    wait_until(lambda: len(swaps) >= 2
               and viewport._scene._clip_node is not None
               and viewport._scene._clip_node.childCount() == 1)
    assert type(viewport).__name__ == "_QuickViewport", type(viewport).__name__
    assert viewport.active_backend() == "quick"
    image = viewport.grabFramebuffer()
    image.save(str(ROOT / "tests" / "shots" / "scene_quick.png"))
    assert image.width() == round(chart.width() * chart.devicePixelRatioF())
    assert image.height() == round(chart.height() * chart.devicePixelRatioF())
    renderer = chart.series_renderers[0]
    color = renderer.color()
    target = np.array([color.red(), color.green(), color.blue()])
    pixels = np.frombuffer(image.constBits(), dtype=np.uint8).reshape(
        image.height(), image.width(), 4)
    mask = np.all(np.abs(pixels[:, :, :3].astype(np.int16) - target) <= 4, axis=2)
    coord = chart.primary_coord()
    misses = []
    for index in range(0, len(values), 50):
        point = coord.map_point(float(index), float(values[index]))
        x = round(point.x() * image.devicePixelRatio())
        y = round(point.y() * image.devicePixelRatio())
        if not mask[max(0, y - 5):y + 6, max(0, x - 5):x + 6].any():
            misses.append(index)
    assert not misses, misses
    chart.update_option({"series": [{
        "type": "line", "name": "回退", "data": values,
        "showSymbol": False, "smooth": True,
    }]})
    chart.anim.stop()
    chart.anim.set_progress(1.0)
    viewport.update()
    pump(120)
    assert viewport.active_backend() in ("gl", "raster"), viewport.active_backend()
    assert not viewport.grabFramebuffer().isNull()
    chart.close()
    os.environ.pop("UIKIT_CHART_BACKEND", None)


@check("Scene Graph 反复创建销毁无悬空节点")
def _():
    if not os.environ.get("UIKIT_REAL"):
        return
    from PySide6.QtCore import QEvent
    from shiboken6 import isValid

    os.environ["UIKIT_CHART_BACKEND"] = "quick"
    for _index in range(8):
        chart, _values = make_chart()
        chart.show()
        viewport = chart._viewport
        wait_until(lambda: viewport._scene._clip_node is not None
                   and viewport._scene._clip_node.childCount() == 1)
        chart.close()
        chart.deleteLater()
        app.sendPostedEvents(None, QEvent.DeferredDelete)
        app.processEvents()
        assert not isValid(chart)
    os.environ.pop("UIKIT_CHART_BACKEND", None)


if __name__ == "__main__":
    raise SystemExit(1 if _FAILURES else 0)
