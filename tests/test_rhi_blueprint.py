# -*- coding: utf-8 -*-
"""Blueprint RHI 节点快照与旧 GL 清除回归。"""

import os
import sys
import traceback
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QImage, QPainter
from PySide6.QtWidgets import QApplication, QLineEdit

from InstructionX_UIKit.blueprint import (
    BlueprintCanvas,
    BlueprintGraph,
    register_node_type,
)
from InstructionX_UIKit.theme import ThemeManager

app = QApplication.instance() or QApplication(sys.argv)
ThemeManager.instance().apply(app)
_FAILURES = []
_OWNER = "rhi-blueprint-offscreen"


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
    canvas.resize(900, 620)
    first = canvas.add_node_at("start", QPointF(40, 40))
    second = canvas.add_node_at("rhi_sink", QPointF(350, 100))
    graph.add_edge(first.id, first.outputs[0].id, second.id, second.inputs[0].id)
    canvas.add_node_at("rhi_body", QPointF(70, 300))
    canvas.fit_view()
    canvas.show()
    from PySide6.QtTest import QTest
    QTest.qWait(600)
    assert not canvas._resize_preview.active, "必须在预览结束后比较最终图像"
    return canvas


def reference(canvas, dpr=1.0):
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


@check("Blueprint 不再保留旧 GL 后端")
def _():
    source = (ROOT / "InstructionX_UIKit" / "blueprint" / "viewport.py").read_text(
        encoding="utf-8")
    for token in ("QOpenGLWidget", "QOpenGLContext", "gl_available",
                  "_GLViewport", "UIKIT_BLUEPRINT_GL"):
        assert token not in source, token


@check("Blueprint 节点、连线与自定义体快照像素一致")
def _():
    from InstructionX_UIKit.blueprint.scene_snapshot import build_scene_snapshot
    canvas = make_canvas()
    edit = canvas.findChild(QLineEdit, "rhiBodyEdit")
    assert edit is not None and edit.isVisible() and edit.height() > 0
    snapshot = build_scene_snapshot(canvas, 1.5)
    expected = reference(canvas, 1.5)
    actual = snapshot.image.convertToFormat(QImage.Format_RGBA8888)
    expected = expected.convertToFormat(QImage.Format_RGBA8888)
    output = ROOT / "tests" / "shots" / "rhi_blueprint"
    output.mkdir(parents=True, exist_ok=True)
    actual.save(str(output / "nodes_actual.png"))
    expected.save(str(output / "nodes_expected.png"))
    assert actual.size() == expected.size()
    assert actual == expected
    canvas.close()


if __name__ == "__main__":
    raise SystemExit(1 if _FAILURES else 0)
