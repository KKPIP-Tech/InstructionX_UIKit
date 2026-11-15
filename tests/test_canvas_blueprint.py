# -*- coding: utf-8 -*-
"""Canvas Blueprint 原生场景、交互与生命周期回归。"""

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

import numpy as np
from PySide6.QtCore import QPoint, QPointF, Qt, QTimer
from PySide6.QtGui import QImage, QPainter
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from InstructionX_UIKit.blueprint import BlueprintCanvas, BlueprintGraph, BlueprintNode, PinDirection
from InstructionX_UIKit.theme import ThemeManager
from run_canvas_line_features import series_ink_bbox

_FAILURES = []
app = QApplication.instance() or QApplication(sys.argv)
ThemeManager.instance().apply(app)


def pump(milliseconds=200):
    deadline = time.perf_counter() + milliseconds / 1000
    while time.perf_counter() < deadline:
        app.processEvents()
        time.sleep(0.005)


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


def make_canvas():
    graph = BlueprintGraph()
    first = BlueprintNode("custom", "加载", node_id="a")
    first.add_output("img", "图像", "image")
    first.pos = QPointF(80, 90)
    first.properties["path"] = "a.png"
    second = BlueprintNode("custom", "推理", node_id="b")
    second.add_input("in", "进入", "exec")
    second.add_input("img", "图像", "image")
    second.add_input("img2", "图像2", "image")
    second.pos = QPointF(440, 250)
    graph.add_node(first)
    graph.add_node(second)
    graph.add_edge("a", "img", "b", "img")
    canvas = BlueprintCanvas(graph)
    canvas.resize(900, 600)
    canvas.show()
    app.processEvents()
    return graph, canvas


def replace_viewport(canvas):
    from InstructionX_UIKit.blueprint.canvas_viewport import CanvasBlueprintViewport
    viewport = CanvasBlueprintViewport(canvas, parent=canvas)
    old = canvas._viewport
    canvas._viewport = viewport
    for widget in canvas._node_widgets.values():
        widget.setParent(viewport)
    old.close()
    old.deleteLater()
    viewport.setGeometry(canvas.rect())
    viewport.show()
    viewport.raise_()
    canvas._update_view()
    viewport._sync_now()
    return viewport


def grab(viewport):
    result = {}

    def captured(image):
        result["image"] = image.copy()
        app.exit(0)

    QTimer.singleShot(0, lambda: viewport.grab_canvas(captured))
    QTimer.singleShot(6000, lambda: app.exit(2))
    if app.exec() != 0 or result.get("image") is None:
        raise RuntimeError("Blueprint Canvas 回读失败")
    return result["image"].convertToFormat(QImage.Format_RGBA8888)


def reference(canvas, dpr):
    image = QImage(round(canvas.width() * dpr), round(canvas.height() * dpr),
                   QImage.Format_ARGB32_Premultiplied)
    image.setDevicePixelRatio(dpr)
    image.fill(Qt.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setRenderHint(QPainter.TextAntialiasing)
    canvas._paint_contents(painter)
    for widget in canvas._node_widgets.values():
        painter.save()
        painter.translate(widget.pos())
        painter.scale(widget._scale, widget._scale)
        widget._paint_content(painter)
        painter.restore()
    painter.end()
    return image.convertToFormat(QImage.Format_RGBA8888)


def center_rgb(image, point):
    dpr = image.devicePixelRatioF()
    pixels = np.frombuffer(image.constBits(), dtype=np.uint8).reshape(
        image.height(), image.width(), 4)
    x, y = round(point.x() * dpr), round(point.y() * dpr)
    return pixels[y - 1:y + 2, x - 1:x + 2, :3].mean(axis=(0, 1))


def assert_matches(viewport, canvas, name, points=()):
    actual = grab(viewport)
    expected = reference(canvas, viewport.devicePixelRatioF())
    destination = ROOT / "temp" / "canvas_blueprint"
    destination.mkdir(parents=True, exist_ok=True)
    actual.save(str(destination / f"{name}.png"))
    expected.save(str(destination / f"{name}_reference.png"))
    actual_bbox, expected_bbox = series_ink_bbox(actual), series_ink_bbox(expected)
    assert actual_bbox is not None and expected_bbox is not None, name
    assert all(abs(a - b) <= 3 for a, b in zip(actual_bbox, expected_bbox)), (
        name, actual_bbox, expected_bbox)
    for point in points:
        delta = np.abs(center_rgb(actual, point).astype(int)
                       - center_rgb(expected, point).astype(int))
        assert int(delta.max()) <= 3, (name, point, delta)


@check("原生网格、节点、引脚、状态、临时线与主题")
def _():
    _graph, canvas = make_canvas()
    viewport = replace_viewport(canvas)
    try:
        assert viewport.supports_node_proxy
        assert viewport._static_scene is not None
        assert viewport._component_scene is not None
        texts = {command[1] for command in viewport._component_scene.commands
                 if command[0] == "text"}
        assert {"加载", "推理", "图像", "进入", "path: a.png"} <= texts, texts
        assert any(command[0] == "stroke_pen" for command in viewport._component_scene.commands)
        assert_matches(viewport, canvas, "initial")
        canvas._selected_nodes = ["a"]
        canvas.node_widget("a").set_selected(True)
        first = canvas.graph.node("a")
        first.set_status("done")
        first.set_elapsed_ms(12)
        canvas.graph.node("b").set_status("error")
        viewport._sync_now()
        texts = {command[1] for command in viewport._component_scene.commands
                 if command[0] == "text"}
        assert "12 ms" in texts
        assert_matches(viewport, canvas, "selected_states")
        handle = canvas.node_widget("a").pin_widget("img", PinDirection.Output)
        canvas._begin_wire(handle)
        canvas._update_wire(canvas.scene_to_view(QPointF(520, 380)))
        viewport._sync_now()
        assert canvas._wire is not None and viewport._overlay_scene is not None
        assert_matches(viewport, canvas, "temporary_wire")
        target = canvas.pin_scene_pos("b", "img2", PinDirection.Input)
        canvas._finish_wire(canvas.scene_to_view(target))
        viewport._sync_now()
        assert len(canvas.graph.edges()) == 2
        first.set_status("running")
        canvas.node_widget("a")._pulse = 0.0
        viewport._sync_now()
        assert_matches(viewport, canvas, "running")
        canvas.set_zoom(1.25)
        canvas._end_zoom_gesture()
        viewport._sync_now()
        assert_matches(viewport, canvas, "zoomed")
        ThemeManager.instance().set_mode("dark")
        viewport._sync_now()
        assert_matches(viewport, canvas, "dark")
        canvas.showMinimized()
        pump()
        canvas.showNormal()
        pump()
        viewport._sync_now()
        assert_matches(viewport, canvas, "restored")
    finally:
        viewport.close()
        canvas.close()
        ThemeManager.instance().set_mode("light")
        pump()


@check("真实节点拖动、Delete、resize 与关闭生命周期")
def _():
    graph, canvas = make_canvas()
    viewport = replace_viewport(canvas)
    moved = []
    canvas.node_moved.connect(lambda node_id, pos: moved.append((node_id, pos)))
    try:
        node = graph.node("a")
        original = QPointF(node.pos)
        start = canvas.scene_to_view(original + QPointF(24, 12))
        end = start + QPointF(54, 38)
        QTest.mousePress(viewport._view, Qt.LeftButton, Qt.NoModifier,
                         QPoint(round(start.x()), round(start.y())))
        QTest.mouseMove(viewport._view, QPoint(round(end.x()), round(end.y())))
        QTest.mouseRelease(viewport._view, Qt.LeftButton, Qt.NoModifier,
                           QPoint(round(end.x()), round(end.y())))
        viewport._sync_now()
        assert node.pos != original and moved, (node.pos, moved)
        canvas._selected_nodes = ["a"]
        canvas.node_widget("a").set_selected(True)
        viewport._view.requestActivate()
        viewport._view.contentItem().setFocus(True)
        QTest.keyClick(viewport._view, Qt.Key_Delete)
        viewport._sync_now()
        assert graph.node("a") is None
        assert "a" not in canvas._node_widgets
        assert len(graph.edges()) == 0
        assert_matches(viewport, canvas, "deleted")
        canvas.resize(820, 560)
        viewport._sync_now()
        assert_matches(viewport, canvas, "resized")
        QTest.mouseClick(viewport._view, Qt.RightButton, Qt.NoModifier, QPoint(700, 420))
        pump(60)
        popup = app.activePopupWidget()
        assert popup is not None, "空白处右键未打开创建菜单"
        QTest.keyClick(popup, Qt.Key_Escape)
        pump(40)
        assert app.activePopupWidget() is None
    finally:
        viewport.close()
        canvas.close()
        pump()
    assert viewport._item is None


@check("自定义节点体保持真实控件输入能力")
def _():
    from PySide6.QtWidgets import QLineEdit
    from InstructionX_UIKit.blueprint import register_node_type

    def build_body(node, container):
        editor = QLineEdit("32")
        editor.setObjectName("canvasBodyEditor")
        container.layout().addWidget(editor)

    register_node_type("canvas_body", "自定义", "测试", body_builder=build_body)
    graph = BlueprintGraph()
    node = BlueprintNode("canvas_body", "自定义", node_id="body")
    node.pos = QPointF(90, 100)
    graph.add_node(node)
    canvas = BlueprintCanvas(graph)
    canvas.resize(900, 600)
    canvas.show()
    viewport = replace_viewport(canvas)
    try:
        widget = canvas.node_widget("body")
        widget._body.setAttribute(Qt.WA_TransparentForMouseEvents, False)
        editor = widget._body.findChild(QLineEdit, "canvasBodyEditor")
        assert editor is not None and editor.isVisible()
        assert not widget.uses_proxy()
        global_pos = editor.mapToGlobal(QPoint(6, 6))
        local = viewport._view.mapFromGlobal(global_pos)
        QTest.mouseClick(viewport._view, Qt.LeftButton, Qt.NoModifier, local)
        editor.selectAll()
        for char in "64":
            QTest.keyClick(viewport._view, getattr(Qt, f"Key_{char}"))
        assert editor.text() == "64", editor.text()
        viewport._sync_now()
        assert_matches(viewport, canvas, "custom_body")
    finally:
        viewport.close()
        canvas.close()
        pump()


@check("Blueprint 生产工厂 canvas 选项与默认后端")
def _():
    from InstructionX_UIKit.blueprint.canvas_viewport import CanvasBlueprintViewport
    from InstructionX_UIKit.blueprint.rhi_viewport import _RhiViewport
    from InstructionX_UIKit.blueprint.viewport import _RasterViewport
    previous = os.environ.get("UIKIT_BLUEPRINT_BACKEND")
    try:
        os.environ.pop("UIKIT_BLUEPRINT_BACKEND", None)
        _graph, canvas = make_canvas()
        assert isinstance(canvas._viewport, _RhiViewport)
        canvas.close()
        os.environ["UIKIT_BLUEPRINT_BACKEND"] = "canvas"
        _graph, canvas = make_canvas()
        assert isinstance(canvas._viewport, CanvasBlueprintViewport)
        assert canvas._viewport.mean_sync_ms() >= 0
        assert "direct" in canvas._viewport.rhi_api().lower()
        canvas.close()
        os.environ["UIKIT_BLUEPRINT_BACKEND"] = "raster"
        _graph, canvas = make_canvas()
        assert isinstance(canvas._viewport, _RasterViewport)
        canvas.close()
    finally:
        if previous is None:
            os.environ.pop("UIKIT_BLUEPRINT_BACKEND", None)
        else:
            os.environ["UIKIT_BLUEPRINT_BACKEND"] = previous
        pump()


if __name__ == "__main__":
    app.quit()
    raise SystemExit(1 if _FAILURES else 0)
