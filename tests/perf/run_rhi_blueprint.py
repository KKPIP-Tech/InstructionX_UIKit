# -*- coding: utf-8 -*-
"""真实 Blueprint RHI 节点、引脚、菜单与嵌入文本控件验收。"""

import json
import os
import platform
import subprocess
import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
os.environ.pop("QT_QPA_PLATFORM", None)
os.environ.pop("QSG_RHI_BACKEND", None)
os.environ.pop("QT_QUICK_BACKEND", None)
os.environ["UIKIT_BLUEPRINT_BACKEND"] = "rhi"

from PySide6.QtCore import QEvent, QPoint, QPointF, QRectF, Qt
from PySide6.QtGui import QImage, QKeyEvent, QKeySequence, QMouseEvent, QPainter, QWheelEvent
from PySide6.QtOpenGLWidgets import QOpenGLWidget
from PySide6.QtQuick import QSGRendererInterface
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLineEdit, QVBoxLayout, QWidget

from InstructionX_UIKit.blueprint import (
    BlueprintCanvas,
    BlueprintGraph,
    PinDirection,
    register_node_type,
)
from InstructionX_UIKit.theme import ThemeManager
from event_scenario import run_event_scenario
from native_screen import grab_native_window

_OWNER = "rhi-blueprint-real"


def move_mouse(view, position, buttons):
    event = QMouseEvent(QEvent.MouseMove, QPointF(position),
                        QPointF(view.mapToGlobal(position)), Qt.NoButton,
                        buttons, Qt.NoModifier)
    QApplication.sendEvent(view, event)


def send_key(view, key, text=""):
    for event_type in (QEvent.KeyPress, QEvent.KeyRelease):
        event = QKeyEvent(event_type, key, Qt.NoModifier, text)
        QApplication.sendEvent(view, event)


def send_text(view, text):
    for character in text:
        send_key(view, QKeySequence(character)[0].key(), character)


def body_builder(node, parent):
    layout = parent.layout()
    edit = QLineEdit(str(node.properties.get("text", "初始文本")))
    edit.setObjectName("rhiBodyEdit")
    edit.textChanged.connect(lambda text: node.setProperty("text", text))
    layout.addWidget(edit)


def make_canvas():
    register_node_type("rhi_body", "文本节点", "测试", owner=_OWNER,
                       body_builder=body_builder)
    register_node_type(
        "rhi_sink", "接收节点", "测试", owner=_OWNER,
        inputs=[{"id": "in", "name": "输入", "data_type": "exec"}])
    graph = BlueprintGraph()
    canvas = BlueprintCanvas(graph, owner=_OWNER)
    first = canvas.add_node_at("start", QPointF(40, 40))
    second = canvas.add_node_at("rhi_sink", QPointF(350, 100))
    graph.add_edge(first.id, first.outputs[0].id, second.id, second.inputs[0].id)
    body = canvas.add_node_at("rhi_body", QPointF(60, 300))
    body_widget = canvas.node_widget(body.id)
    body_widget._body.setAttribute(Qt.WA_TransparentForMouseEvents, False)
    source = canvas.add_node_at("start", QPointF(40, 500))
    target = canvas.add_node_at("rhi_sink", QPointF(400, 500))
    return canvas, first, source, target


def reference(canvas):
    dpr = canvas.devicePixelRatioF()
    image = QImage(round(canvas.width() * dpr), round(canvas.height() * dpr),
                   QImage.Format_RGBA8888)
    image.setDevicePixelRatio(dpr)
    image.fill(Qt.transparent)
    painter = QPainter(image)
    try:
        painter.setRenderHint(QPainter.Antialiasing)
        canvas._paint_contents(painter, None)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        zoom = canvas._zoom
        for widget in canvas._node_widgets.values():
            if not widget.isVisible():
                continue
            position = canvas.scene_to_view(widget.node.pos)
            pixmap = widget.cache_pixmap() if widget.uses_proxy() else widget.grab()
            if widget.uses_proxy() and abs(widget._cache_scale - zoom) > 1e-3:
                rect = QRectF(position.x(), position.y(), widget.node.size.width() * zoom,
                              widget.node.size.height() * zoom)
                painter.drawPixmap(rect, pixmap, QRectF(pixmap.rect()))
            else:
                painter.drawPixmap(position, pixmap)
    finally:
        painter.end()
    return image


def main():
    source_sha = subprocess.check_output(
        ["git", "rev-parse", "uniform_style"], text=True, cwd=ROOT).strip()
    output = ROOT / "temp" / "performance" / source_sha / "rhi-blueprint"
    output.mkdir(parents=True, exist_ok=True)
    app = QApplication.instance() or QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    ThemeManager.instance().apply(app)
    host = QWidget()
    host.setWindowTitle("Blueprint RHI 节点与交互")
    layout = QVBoxLayout(host)
    layout.setContentsMargins(0, 0, 0, 0)
    canvas, first, source, target = make_canvas()
    layout.addWidget(canvas)
    host.resize(1000, 720)
    host.setWindowFlag(Qt.WindowStaysOnTopHint, True)
    host.setWindowFlags(host.windowFlags() | Qt.FramelessWindowHint)
    host.setAttribute(Qt.WA_TranslucentBackground)
    host.setAttribute(Qt.WA_NoSystemBackground)
    host.show()
    host.raise_()
    host.activateWindow()
    checks = []

    def scenario():
        try:
            yield 1000
            viewport = canvas._viewport
            assert type(viewport).__name__ == "_RhiViewport", type(viewport).__name__
            assert not host.findChildren(QOpenGLWidget)
            api = viewport._view.graphicsApi()
            if platform.system() == "Windows":
                assert api == QSGRendererInterface.GraphicsApi.Direct3D11, api
            checks.append("默认平台 RHI，无旧 GL 表面")

            def compare(name):
                yield 250
                actual = viewport.grab().toImage().convertToFormat(QImage.Format_RGBA8888)
                expected = reference(canvas).convertToFormat(QImage.Format_RGBA8888)
                screen_image = grab_native_window(viewport._view).convertToFormat(
                    QImage.Format_RGBA8888)
                actual.save(str(output / f"{name}_actual.png"))
                expected.save(str(output / f"{name}_expected.png"))
                screen_image.save(str(output / f"{name}_screen.png"))
                assert actual.size() == expected.size() and actual == expected, \
                    f"{name} 节点图像不一致"
                assert screen_image.size() == actual.size() and screen_image == actual, \
                    f"{name} 的桌面合成与 RHI 回读不一致"
                checks.append(name)
                print(f"  [通过] {name}：节点与桌面合成均零像素差异", flush=True)

            yield from compare("初始节点与自定义体")
            view = viewport._view
            widget = canvas.node_widget(first.id)
            point = widget.mapTo(canvas, widget.rect().center())
            QTest.mouseClick(view, Qt.LeftButton, Qt.NoModifier, point)
            yield 200
            assert canvas.selected_nodes() == [first.id], canvas.selected_nodes()
            before = QPointF(first.pos)
            destination = point + QPoint(45, 30)
            QTest.mousePress(view, Qt.LeftButton, Qt.NoModifier, point)
            move_mouse(view, destination, Qt.LeftButton)
            QTest.mouseRelease(view, Qt.LeftButton, Qt.NoModifier, destination)
            yield 300
            assert first.pos != before, "节点拖动未生效"
            yield from compare("节点选择与拖动")

            source_widget = canvas.node_widget(source.id)
            target_widget = canvas.node_widget(target.id)
            out = source_widget.pin_widget(source.outputs[0].id, PinDirection.Output)
            into = target_widget.pin_widget(target.inputs[0].id, PinDirection.Input)
            out_point = out.mapTo(canvas, out.rect().center())
            in_point = into.mapTo(canvas, into.rect().center())
            count = len(canvas.graph.edges())
            QTest.mousePress(view, Qt.LeftButton, Qt.NoModifier, out_point)
            assert canvas._wire is not None, "引脚按下未创建临时线"
            move_mouse(view, in_point, Qt.LeftButton)
            QTest.mouseRelease(view, Qt.LeftButton, Qt.NoModifier, in_point)
            yield 250
            assert len(canvas.graph.edges()) == count + 1, "引脚连线未创建"
            yield from compare("引脚连线")

            old_zoom = canvas.zoom()
            point = canvas.rect().center()
            event = QWheelEvent(QPointF(point), QPointF(canvas.mapToGlobal(point)),
                                QPoint(0, 0), QPoint(0, 120), Qt.NoButton,
                                Qt.NoModifier, Qt.ScrollUpdate, False)
            QApplication.sendEvent(view, event)
            yield 350
            assert canvas.zoom() != old_zoom, "滚轮缩放未生效"
            yield from compare("缩放高清恢复")

            edit = canvas.findChild(QLineEdit, "rhiBodyEdit")
            assert edit is not None and edit.isVisible() and edit.height() > 0
            edit_point = edit.mapTo(canvas, edit.rect().center())
            QTest.mouseClick(view, Qt.LeftButton, Qt.NoModifier, edit_point)
            send_text(view, "abc")
            yield 250
            assert edit.text().endswith("abc"), edit.text()
            assert QApplication.focusWidget() is edit, QApplication.focusWidget()
            yield from compare("嵌入文本控件输入")
            canvas.setFocus()
            send_key(view, Qt.Key_Delete)
            yield 200
            assert canvas.graph.node(first.id) is None, "Delete 未删除选中节点"

            blank = QPoint(canvas.width() - 20, canvas.height() - 20)
            QTest.mouseClick(view, Qt.RightButton, Qt.NoModifier, blank)
            yield 200
            popup = QApplication.activePopupWidget()
            assert popup is not None, "右键未打开创建菜单"
            popup.close()
            yield 100
            host.resize(920, 640)
            yield 600
            yield from compare("resize 与菜单恢复")
            assert os.environ.get("QSG_RENDER_LOOP") == "basic"
            host.showMinimized()
            yield 250
            assert host.isMinimized(), "宿主未进入最小化"
            assert not canvas._ui_active, "最小化时未停止画布更新"
            host.showNormal()
            yield 500
            assert canvas._ui_active, "恢复时未重启画布更新"
            assert not host.isMinimized(), "宿主未从最小化恢复"
            yield from compare("最小化后恢复")
            report = {
                "source_sha": source_sha,
                "backend": getattr(api, "name", str(api)),
                "rhi_backend": getattr(viewport._view.rhi().backend(), "name",
                                        str(viewport._view.rhi().backend())),
                "driver": "QTimer + app.exec；输入、抓图和窗口操作均在 GUI 事件循环内",
                "input_mode": "Qt QTest/QMouseEvent/QKeyEvent；非操作系统原生鼠标轨迹",
                "native_mouse_verified": False,
                "checks": checks,
                "pass": True,
            }
            (output / "report.json").write_text(
                json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
            print(json.dumps(report, ensure_ascii=False), flush=True)
        except Exception:
            traceback.print_exc()
            print(json.dumps({"source_sha": source_sha, "checks": checks,
                              "pass": False}, ensure_ascii=False), flush=True)
            raise
        finally:
            host.close()
            host.deleteLater()
            app.sendPostedEvents(None, QEvent.DeferredDelete)
            app.processEvents()

    return run_event_scenario(app, scenario())


if __name__ == "__main__":
    raise SystemExit(main())
