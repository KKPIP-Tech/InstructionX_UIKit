# -*- coding: utf-8 -*-
"""RHI 图表默认后端、像素几何、透明清理与生命周期回归。"""

import os
import sys
import traceback
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
if os.environ.get("UIKIT_REAL"):
    os.environ.pop("QT_QPA_PLATFORM", None)
    os.environ.pop("QSG_RHI_BACKEND", None)
os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests" / "perf"))

import numpy as np
from PySide6.QtCore import QEvent
from PySide6.QtGui import QImage, QPainter
from PySide6.QtWidgets import QApplication

from InstructionX_UIKit.charts import ChartWidget
from InstructionX_UIKit.charts.scene_snapshot import build_scene_snapshot
from InstructionX_UIKit.theme import ThemeManager
from event_scenario import run_event_scenario

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


def make_chart():
    values = np.sin(np.arange(1000, dtype=np.float64) * 0.02)
    chart = ChartWidget()
    chart.set_option({
        "animation": False,
        "xAxis": {"type": "value"},
        "yAxis": {"type": "value"},
        "series": [{"type": "line", "name": "RHI 实线", "data": values,
                    "showSymbol": False}],
    })
    chart.anim.stop()
    chart.anim.set_progress(1.0)
    chart.resize(640, 360)
    return chart, values


def reference(chart):
    image = QImage(round(chart.width() * chart.devicePixelRatioF()),
                   round(chart.height() * chart.devicePixelRatioF()),
                   QImage.Format_RGBA8888)
    image.setDevicePixelRatio(chart.devicePixelRatioF())
    image.fill(0)
    painter = QPainter(image)
    try:
        chart._paint_contents(painter)
    finally:
        painter.end()
    return image.convertToFormat(QImage.Format_RGBA8888)


def wait_for(predicate, timeout_ms=2000):
    elapsed = 0
    while not predicate():
        if elapsed >= timeout_ms:
            raise AssertionError("等待 RHI 快照与交换帧超时")
        yield 20
        elapsed += 20


@check("offscreen 使用同一绘制体的软件验证视口")
def _():
    if os.environ.get("UIKIT_REAL"):
        return
    chart, _values = make_chart()
    assert type(chart._viewport).__name__ == "_RasterViewport"
    chart.show()
    app.processEvents()
    assert not chart.grab().isNull()
    chart.close()


@check("全部 option 的 RHI 快照与最终图像一致")
def _():
    if os.environ.get("UIKIT_REAL"):
        return
    chart, _values = make_chart()
    snapshot = build_scene_snapshot(chart, 1.0)
    assert snapshot.image.convertToFormat(QImage.Format_RGBA8888) == reference(chart)
    chart.close()


@check("真实 D3D11 曲线几何与透明节点恢复")
def _():
    if not os.environ.get("UIKIT_REAL"):
        return

    def scenario():
        chart, values = make_chart()
        chart.move(80, 60)
        chart.show()
        chart.raise_()
        chart.activateWindow()
        viewport = chart._viewport
        frames = []
        viewport._view.frameSwapped.connect(lambda: frames.append(1))
        yield from wait_for(
            lambda: viewport._scene._snapshot is not None
            and viewport._scene._texture_key == viewport._scene._snapshot.version
            and bool(frames))
        assert type(viewport).__name__ == "_RhiViewport", type(viewport).__name__
        assert os.environ.get("QSG_RENDER_LOOP") == "basic"
        api = viewport._view.graphicsApi()
        if sys.platform == "win32":
            from PySide6.QtQuick import QSGRendererInterface
            assert api == QSGRendererInterface.GraphicsApi.Direct3D11, api
        image = viewport.grabFramebuffer().convertToFormat(QImage.Format_RGBA8888)
        expected = reference(chart)
        assert image.size() == expected.size() and image == expected
        renderer = chart.series_renderers[0]
        color = renderer.color()
        target = np.array([color.red(), color.green(), color.blue()])
        pixels = np.frombuffer(image.constBits(), dtype=np.uint8).reshape(
            image.height(), image.width(), 4)
        mask = np.all(np.abs(pixels[:, :, :3].astype(np.int16) - target) <= 4, axis=2)
        coord = chart.primary_coord()
        misses = []
        dpr = image.devicePixelRatio()
        for index in range(0, len(values), 50):
            point = coord.map_point(float(index), float(values[index]))
            x, y = round(point.x() * dpr), round(point.y() * dpr)
            if not mask[max(0, y - 5):y + 6, max(0, x - 5):x + 6].any():
                misses.append(index)
        assert not misses, misses
        output = ROOT / "tests" / "shots"
        output.mkdir(exist_ok=True)
        image.save(str(output / "rhi_scene_chart.png"))

        first = viewport._scene._node
        viewport._scene.clear()
        yield 100
        assert viewport._scene._node is first
        assert viewport._scene._texture_key is None
        previous_frames = len(frames)
        viewport._scene.sync(chart, chart.devicePixelRatioF())
        yield from wait_for(
            lambda: viewport._scene._snapshot is not None
            and viewport._scene._texture_key == viewport._scene._snapshot.version
            and len(frames) > previous_frames)
        assert viewport._scene._node is first
        assert viewport._scene._texture_key is not None
        restored = viewport.grabFramebuffer().convertToFormat(QImage.Format_RGBA8888)
        assert restored.size() == expected.size() and restored == expected
        chart.close()
        chart.deleteLater()
        app.sendPostedEvents(None, QEvent.DeferredDelete)
        yield 0

    assert run_event_scenario(app, scenario()) == 0


@check("RHI 视口反复创建销毁无悬空对象")
def _():
    if not os.environ.get("UIKIT_REAL"):
        return
    from shiboken6 import isValid

    def scenario():
        for _index in range(8):
            chart, _values = make_chart()
            chart.show()
            viewport = chart._viewport
            yield from wait_for(
                lambda: viewport._scene._snapshot is not None
                and viewport._scene._texture_key == viewport._scene._snapshot.version)
            assert type(viewport).__name__ == "_RhiViewport"
            assert not chart._viewport.grabFramebuffer().isNull()
            chart.close()
            chart.deleteLater()
            app.sendPostedEvents(None, QEvent.DeferredDelete)
            app.processEvents()
            yield 0
            assert not isValid(chart)

    assert run_event_scenario(app, scenario()) == 0


@check("构造未完成的 Chart 视口可以安全关闭")
def _():
    from InstructionX_UIKit.charts.rhi_viewport import _RhiViewport
    from PySide6.QtWidgets import QWidget
    from PySide6.QtGui import QHideEvent, QCloseEvent

    viewport = _RhiViewport.__new__(_RhiViewport)
    QWidget.__init__(viewport)
    viewport.hideEvent(QHideEvent())
    viewport.closeEvent(QCloseEvent())
    assert not viewport.eventFilter(viewport, QEvent(QEvent.MouseMove))
    viewport.deleteLater()


if __name__ == "__main__":
    raise SystemExit(1 if _FAILURES else 0)
