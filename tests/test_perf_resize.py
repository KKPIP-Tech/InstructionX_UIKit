# -*- coding: utf-8 -*-
"""重型视口缩放预览与最终高清恢复回归（直接运行）。"""

import os
import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from InstructionX_UIKit._resize_preview import ResizePreview
from InstructionX_UIKit.charts import ChartWidget
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


def make_chart():
    chart = ChartWidget()
    chart.resize(800, 400)
    chart.set_option({
        "xAxis": {"type": "value"},
        "yAxis": {"type": "value"},
        "series": [{"type": "line", "data": [1, 3, 2, 5, 4]}],
    })
    chart.anim.stop()
    chart.anim.set_progress(1.0)
    chart.show()
    app.processEvents()
    return chart


@check("预览状态机拒绝空帧并只结算一次")
def _():
    calls = []
    preview = ResizePreview(app, on_settle=lambda: calls.append(1))
    assert not preview.begin(None)
    assert not preview.begin(QPixmap())
    image = QPixmap(32, 32)
    image.fill(Qt.red)
    assert preview.begin(image)
    preview.touch()
    assert preview.finish()
    assert calls == [1]
    assert not preview.active and preview.snapshot is None
    assert not preview._timer.isActive()
    preview.begin(image)
    preview.cancel()
    assert calls == [1]
    assert not preview.active and preview.snapshot is None


@check("Chart 连续缩放仅一次全量恢复且最终像素一致")
def _():
    chart = make_chart()
    original = chart._layout_all
    calls = []
    chart._layout_all = lambda force=False: calls.append(force) or original(force)
    chart.resize(900, 420)
    assert chart._resize_preview.active
    assert not calls
    chart.resize(1000, 440)
    assert not calls
    QTest.qWait(160)
    assert calls.count(True) == 1, calls
    assert not chart._resize_preview.active
    chart.resize(1000, 440)
    app.processEvents()
    final = chart._viewport.grab().toImage()
    os.environ["UIKIT_RESIZE_PREVIEW"] = "off"
    reference = make_chart()
    reference.resize(1000, 440)
    app.processEvents()
    expected = reference._viewport.grab().toImage()
    assert final == expected, "预览恢复后的最终图像与全质量路径不一致"
    renderer = chart.series_renderers[0]
    assert renderer.hit_test(renderer._points[0]) is not None
    chart.close()
    reference.close()
    os.environ.pop("UIKIT_RESIZE_PREVIEW", None)


@check("关闭预览保持逐次全量布局")
def _():
    os.environ["UIKIT_RESIZE_PREVIEW"] = "off"
    chart = make_chart()
    original = chart._layout_all
    calls = []
    chart._layout_all = lambda force=False: calls.append(force) or original(force)
    chart.resize(900, 420)
    assert not chart._resize_preview.active
    assert calls
    chart.close()
    os.environ.pop("UIKIT_RESIZE_PREVIEW", None)


def make_blueprint():
    from demo.pages.blueprint import create_page

    page = create_page()
    canvas = page.findChild(__import__(
        "InstructionX_UIKit.blueprint", fromlist=["BlueprintCanvas"]).BlueprintCanvas)
    page.resize(800, 500)
    page.show()
    app.processEvents()
    return page, canvas


@check("Blueprint 节点预览只结算一次且最终完整清晰")
def _():
    page, canvas = make_blueprint()
    original = canvas._update_view
    calls = []
    canvas._update_view = lambda: calls.append(1) or original()
    canvas.resize(900, 520)
    assert canvas._resize_preview.active
    assert not calls
    canvas.resize(1000, 540)
    assert not calls
    QTest.qWait(160)
    assert calls == [1], calls
    assert not canvas._resize_preview.active
    assert not canvas._gesture_deferred
    assert all(widget.isVisible() for widget in canvas._node_widgets.values())
    final = canvas._viewport.grab().toImage()
    os.environ["UIKIT_RESIZE_PREVIEW"] = "off"
    reference, reference_canvas = make_blueprint()
    reference_canvas.resize(1000, 540)
    app.processEvents()
    assert final == reference_canvas._viewport.grab().toImage()
    os.environ.pop("UIKIT_RESIZE_PREVIEW", None)
    if canvas._edge_widgets:
        edge = next(iter(canvas._edge_widgets.values()))
        edge.flowing = True
        canvas._ensure_flow_timer()
        assert canvas._flow_timer.isActive()
        canvas.resize(1040, 560)
        assert not canvas._flow_timer.isActive()
        QTest.qWait(160)
        assert canvas._flow_timer.isActive()
    page.close()
    reference.close()
    os.environ.pop("UIKIT_RESIZE_PREVIEW", None)


if __name__ == "__main__":
    app.quit()
    raise SystemExit(1 if _FAILURES else 0)
