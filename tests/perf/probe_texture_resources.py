# -*- coding: utf-8 -*-
"""统计 RHI 纹理创建与销毁，验证旧帧资源不能无界积累。"""

import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests" / "perf"))
os.environ.pop("QT_QPA_PLATFORM", None)

from PySide6.QtCore import QEvent, Qt, QTimer, QUrl
from PySide6.QtGui import QGuiApplication, QImage
from PySide6.QtQml import qmlRegisterType
from PySide6.QtQuick import QQuickView
from InstructionX_UIKit._rhi_texture import RhiTextureItem, SceneSnapshot
from event_scenario import run_event_scenario
from run_realtime import process_sample


class ProbeTextureItem(RhiTextureItem):
    def __init__(self):
        super().__init__()
        self._version = 0
        self._image = QImage(256, 256, QImage.Format_RGBA8888)

    def build_snapshot(self, _source, _dpr):
        self._version += 1
        self._image.fill(Qt.GlobalColor(self._version % 7 + 1))
        return SceneSnapshot(self._image, 256, 256, 1.0, self._version)


qmlRegisterType(ProbeTextureItem, "Probe", 1, 0, "ProbeTextureItem")
app = QGuiApplication(sys.argv)
app.setQuitOnLastWindowClosed(False)
view = QQuickView()
view.setColor(Qt.white)
view.setGeometry(100, 80, 320, 240)
view.setFlags(view.flags() | Qt.WindowStaysOnTopHint)
view.setResizeMode(QQuickView.SizeRootObjectToView)
state = {"created": 0, "destroyed": 0, "frames": 0}
original_create = view.createTextureFromImage


def tracked_create(image):
    texture = original_create(image)
    if texture is not None:
        state["created"] += 1
        texture.destroyed.connect(lambda *_: state.__setitem__(
            "destroyed", state["destroyed"] + 1))
    return texture


view.createTextureFromImage = tracked_create
view.setSource(QUrl.fromLocalFile(str(ROOT / "temp" / "rhi_texture_probe.qml")))
item = view.rootObject().findChild(ProbeTextureItem)
timer = QTimer(view)
timer.setInterval(16)
timer.timeout.connect(lambda: item.sync(None, 1.0))
view.frameSwapped.connect(lambda: state.__setitem__("frames", state["frames"] + 1))
view.show()
state["memory_before"] = process_sample()


def scenario():
    yield 100
    timer.start()
    while state["frames"] < 48:
        yield 16
    timer.stop()
    state["memory_after"] = process_sample()
    state["destroyed_before_close"] = state["destroyed"]
    view.setSource(QUrl())
    view.close()
    view.deleteLater()
    app.sendPostedEvents(None, QEvent.DeferredDelete)
    app.processEvents()
    state["destroyed_after_close"] = state["destroyed"]
    source_sha = subprocess.check_output(
        ["git", "rev-parse", "uniform_style"], text=True, cwd=ROOT).strip()
    report = {
        "source_sha": source_sha, "graphics_api": view.graphicsApi().name,
        "created": state["created"], "destroyed_before_close": state["destroyed_before_close"],
        "destroyed_after_close": state["destroyed_after_close"],
        "memory_before": state["memory_before"], "memory_after": state["memory_after"],
        "private_delta": state["memory_after"]["private_bytes"] - state["memory_before"]["private_bytes"],
    }
    report["pass"] = (report["graphics_api"] == "Direct3D11"
                      and report["created"] >= 24
                      and report["destroyed_before_close"] >= report["created"] - 3
                      and report["destroyed_after_close"] == report["created"])
    destination = ROOT / "temp" / "performance" / source_sha
    destination.mkdir(parents=True, exist_ok=True)
    (destination / "texture-resources.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False), flush=True)
    app.exit(0 if report["pass"] else 1)


raise SystemExit(run_event_scenario(app, scenario()))
