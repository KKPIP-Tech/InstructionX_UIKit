# -*- coding: utf-8 -*-
"""真实 Canvas 视口连续缩放、直接动态渲染与窗口组合回归。"""

import os
from pathlib import Path
import sys
import time
import traceback

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests" / "perf"))
os.environ.pop("QT_QPA_PLATFORM", None)
os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")

from PySide6.QtGui import QImage
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


def pump(milliseconds):
    deadline = time.monotonic() + milliseconds / 1000
    while time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.004)


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


def forbid_resize_grab(viewport):
    original = viewport.grab
    calls = []

    def forbidden(*_args, **_kwargs):
        calls.append(1)
        raise AssertionError("Canvas 缩放不得生成旧帧截图")

    viewport.grab = forbidden
    return original, calls


def grab_async(viewport):
    result = {}

    def captured(image):
        result["image"] = image.copy()

    viewport.grab_canvas(captured)
    for _index in range(500):
        if "image" in result:
            return result["image"]
        pump(2)
    raise AssertionError("Canvas 异步回读超时")


@check("Canvas 图表连续缩放直接渲染且动画与数据不中断")
def _():
    os.environ["UIKIT_CHART_BACKEND"] = "canvas"
    chart = make_chart()
    reference = None
    viewport = chart._viewport
    original_grab, calls = forbid_resize_grab(viewport)
    try:
        chart.anim.start()
        for size in ((900, 420), (1000, 440), (960, 460), (1000, 440)):
            chart.resize(*size)
            pump(20)
        assert not calls
        assert not chart._resize_preview.active
        assert not chart._preview_capturing
        assert chart.anim.is_running(), "直接缩放不得暂停动画"
        assert chart.set_stream_data([2, 4, 1, 5, 3]), "直接缩放不得中断流式数据"
        chart.anim.stop()
        chart.anim.set_progress(1.0)
        viewport.grab = original_grab
        pump(50)
        final = grab_async(viewport)
        os.environ["UIKIT_RESIZE_PREVIEW"] = "off"
        reference = make_chart()
        reference.set_stream_data([2, 4, 1, 5, 3])
        reference.resize(1000, 440)
        pump(50)
        expected = grab_async(reference._viewport)
        if final != expected:
            final.save(str(ROOT / "temp" / "canvas_resize_chart_final.png"))
            expected.save(str(ROOT / "temp" / "canvas_resize_chart_expected.png"))
        assert final == expected, "直接缩放后的最终图像与全质量路径不一致"
    finally:
        viewport.grab = original_grab
        chart.close()
        if reference is not None:
            reference.close()
        os.environ.pop("UIKIT_CHART_BACKEND", None)
        os.environ.pop("UIKIT_RESIZE_PREVIEW", None)


@check("Canvas Blueprint 直接缩放保持真实控件与流动动画")
def _():
    os.environ["UIKIT_BLUEPRINT_BACKEND"] = "canvas"
    page, canvas = make_blueprint()
    reference = None
    reference_canvas = None
    viewport = canvas._viewport
    original_grab, calls = forbid_resize_grab(viewport)
    try:
        edge = next(iter(canvas._edge_widgets.values()))
        edge.set_flowing(True)
        canvas._ensure_flow_timer()
        for size in ((900, 520), (1000, 540), (960, 560), (1000, 540)):
            canvas.resize(*size)
            pump(20)
        assert not calls
        assert not canvas._resize_preview.active
        assert not canvas._preview_capturing
        assert not canvas._gesture_deferred
        assert all(widget.isVisible() for widget in canvas._node_widgets.values())
        assert canvas._flow_timer.isActive(), "直接缩放不得停止流动动画"
        edge.set_flowing(False)
        canvas.update()
        viewport.grab = original_grab
        page.resize(1232, 800)
        canvas.resize(1000, 540)
        pump(50)
        final = grab_async(viewport)
        os.environ["UIKIT_RESIZE_PREVIEW"] = "off"
        reference, reference_canvas = make_blueprint()
        reference.resize(1232, 800)
        reference_canvas.resize(1000, 540)
        pump(50)
        expected = grab_async(reference_canvas._viewport)
        if final != expected:
            print("BLUEPRINT_SIZES", canvas.size(), viewport.size(), viewport._view.size(),
                  reference_canvas.size(), reference_canvas._viewport.size(),
                  reference_canvas._viewport._view.size(), flush=True)
            final.save(str(ROOT / "temp" / "canvas_resize_blueprint_final.png"))
            expected.save(str(ROOT / "temp" / "canvas_resize_blueprint_expected.png"))
        assert final == expected
    finally:
        viewport.grab = original_grab
        page.close()
        if reference is not None:
            reference.close()
        os.environ.pop("UIKIT_BLUEPRINT_BACKEND", None)
        os.environ.pop("UIKIT_RESIZE_PREVIEW", None)


@check("Blueprint 同步 grab 与异步回读保持像素一致")
def _():
    os.environ["UIKIT_BLUEPRINT_BACKEND"] = "canvas"
    page, canvas = make_blueprint()
    try:
        pump(100)
        for _index in range(3):
            direct = canvas._viewport.grab().toImage().convertToFormat(QImage.Format_RGBA8888)
            asynchronous = grab_async(canvas._viewport).convertToFormat(QImage.Format_RGBA8888)
            assert not direct.isNull()
            if direct != asynchronous:
                print("QImage_META", direct.format(), asynchronous.format(),
                      direct.devicePixelRatioF(), asynchronous.devicePixelRatioF(),
                      direct.colorSpace().isValid(), asynchronous.colorSpace().isValid(), flush=True)
                direct.save(str(ROOT / "temp" / "canvas_sync_direct.png"))
                asynchronous.save(str(ROOT / "temp" / "canvas_sync_async.png"))
            assert direct == asynchronous
            assert canvas._viewport.grabFramebuffer().convertToFormat(
                QImage.Format_RGBA8888) == direct
    finally:
        page.close()
        os.environ.pop("UIKIT_BLUEPRINT_BACKEND", None)


@check("WindowHost 连续更新与几何变化不阻塞直接渲染")
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
