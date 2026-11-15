# -*- coding: utf-8 -*-
"""真实 Canvas 视口连续缩放、异步捕获与窗口组合回归。"""

import os
from pathlib import Path
import sys
import traceback

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests" / "perf"))
os.environ.pop("QT_QPA_PLATFORM", None)
os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")

from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
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
    chart.set_option({"xAxis": {"type": "value"}, "yAxis": {"type": "value"},
                      "series": [{"type": "line", "data": [1, 3, 2, 5, 4]}]})
    chart.anim.stop()
    chart.anim.set_progress(1.0)
    chart.move(100, 100)
    chart.show()
    app.processEvents()
    return chart


def make_blueprint():
    from demo.pages.blueprint import create_page
    page = create_page()
    canvas = page.findChild(__import__(
        "InstructionX_UIKit.blueprint", fromlist=["BlueprintCanvas"]).BlueprintCanvas)
    page.resize(800, 500)
    page.move(100, 100)
    page.show()
    app.processEvents()
    return page, canvas


def wait_preview(canvas, active):
    for _index in range(200):
        if canvas._resize_preview.active == active:
            return
        if active:
            canvas.resize(1000, 440)
        QTest.qWait(10)
    raise AssertionError(f"缩放预览状态超时: active={active}")


@check("Canvas 图表连续缩放捕获且最终像素一致")
def _():
    os.environ["UIKIT_CHART_BACKEND"] = "canvas"
    chart = make_chart()
    reference = None
    try:
        chart.resize(900, 420)
        chart.resize(1000, 440)
        wait_preview(chart, True)
        assert chart._preview_capturing is False
        wait_preview(chart, False)
        QTest.qWait(50)
        final = chart._viewport.grab().toImage()
        os.environ["UIKIT_RESIZE_PREVIEW"] = "off"
        reference = make_chart()
        reference.resize(1000, 440)
        QTest.qWait(50)
        expected = reference._viewport.grab().toImage()
        assert final == expected, "预览恢复后的最终图像与全质量路径不一致"
    finally:
        chart.close()
        if reference is not None:
            reference.close()
        os.environ.pop("UIKIT_CHART_BACKEND", None)
        os.environ.pop("UIKIT_RESIZE_PREVIEW", None)


@check("Canvas Blueprint 连续缩放捕获且最终完整清晰")
def _():
    os.environ["UIKIT_BLUEPRINT_BACKEND"] = "canvas"
    page, canvas = make_blueprint()
    reference = None
    reference_canvas = None
    try:
        canvas.resize(900, 520)
        canvas.resize(1000, 540)
        wait_preview(canvas, True)
        assert canvas._preview_capturing is False
        wait_preview(canvas, False)
        assert not canvas._gesture_deferred
        assert all(widget.isVisible() for widget in canvas._node_widgets.values())
        QTest.qWait(50)
        final = canvas._viewport.grab().toImage()
        os.environ["UIKIT_RESIZE_PREVIEW"] = "off"
        reference, reference_canvas = make_blueprint()
        reference_canvas.resize(1000, 540)
        QTest.qWait(50)
        assert final == reference_canvas._viewport.grab().toImage()
    finally:
        page.close()
        if reference is not None:
            reference.close()
        os.environ.pop("UIKIT_BLUEPRINT_BACKEND", None)
        os.environ.pop("UIKIT_RESIZE_PREVIEW", None)


@check("WindowHost 连续更新与几何变化不阻塞同步回读")
def _():
    from run_window_matrix import AudioProbe, measure_case
    os.environ["UIKIT_CHART_BACKEND"] = "canvas"
    os.environ["UIKIT_BLUEPRINT_BACKEND"] = "canvas"
    output = ROOT / "temp" / "canvas_resize_matrix"
    output.mkdir(parents=True, exist_ok=True)
    try:
        results = measure_case(app, "complex", 0.2, ROOT, output, AudioProbe(False))
        assert len(results) == 4
        assert all(item["interaction_ok"] for item in results)
    finally:
        os.environ.pop("UIKIT_CHART_BACKEND", None)
        os.environ.pop("UIKIT_BLUEPRINT_BACKEND", None)


if __name__ == "__main__":
    app.quit()
    raise SystemExit(1 if _FAILURES else 0)
