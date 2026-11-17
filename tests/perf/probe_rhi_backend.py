# -*- coding: utf-8 -*-
"""真实 QQuickView 的平台默认 RHI 与 QWidget 原生嵌入能力探针。"""

import argparse
import json
import os
import platform
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
os.environ.pop("QT_QPA_PLATFORM", None)
os.environ.pop("QSG_RHI_BACKEND", None)
os.environ.pop("QT_QUICK_BACKEND", None)

from PySide6.QtCore import QEvent, QTimer, QUrl
from PySide6.QtQuick import QQuickView, QSGRendererInterface
from PySide6.QtWidgets import QApplication, QVBoxLayout, QWidget


def enum_name(value):
    return getattr(value, "name", str(value))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--cycles", type=int, default=8)
    args = parser.parse_args()
    if args.cycles < 1:
        parser.error("cycles 必须至少为 1")
    source_sha = subprocess.check_output(
        ["git", "rev-parse", "uniform_style"], text=True, cwd=ROOT).strip()
    destination = ROOT / "temp" / "performance" / source_sha / "rhi-backend-probe"
    destination.mkdir(parents=True, exist_ok=True)
    (destination / "script_snapshot.py").write_text(
        Path(__file__).read_text(encoding="utf-8"), encoding="utf-8")
    (destination / "scene_snapshot.qml").write_text(
        (ROOT / "tests" / "perf" / "rhi_probe.qml").read_text(encoding="utf-8"),
        encoding="utf-8")
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    state = {"cycles": [], "index": 0}

    def guarded(callback):
        def invoke():
            try:
                callback()
            except Exception:
                import traceback
                traceback.print_exc()
                app.exit(1)
        return invoke

    def run_cycle():
        host = QWidget()
        host.setWindowTitle("RHI 平台默认后端能力探针")
        host.resize(640, 360)
        layout = QVBoxLayout(host)
        layout.setContentsMargins(0, 0, 0, 0)
        view = QQuickView()
        view.setResizeMode(QQuickView.SizeRootObjectToView)
        view.setSource(QUrl.fromLocalFile(str(ROOT / "tests" / "perf" / "rhi_probe.qml")))
        if view.status() == QQuickView.Error:
            raise RuntimeError(f"探针 QML 加载失败: {view.errors()}")
        container = QWidget.createWindowContainer(view, host)
        layout.addWidget(container)
        host.show()

        def inspect():
            api = view.graphicsApi()
            rhi = view.rhi()
            if rhi is None:
                raise AssertionError("QQuickView 未创建 RHI")
            image = view.grabWindow()
            if image.isNull():
                raise AssertionError("QQuickView 无法回读 Scene Graph 图像")
            expected = {
                "Windows": QSGRendererInterface.GraphicsApi.Direct3D11,
                "Darwin": QSGRendererInterface.GraphicsApi.Metal,
            }.get(platform.system())
            if expected is not None:
                assert api == expected, (api, expected)
            frame = {"count": 0}
            view.frameSwapped.connect(lambda: frame.__setitem__("count", frame["count"] + 1))
            view.update()

            def finish():
                assert frame["count"] >= 1, "Scene Graph 未交换新帧"
                saved = image.save(str(destination / f"cycle_{state['index'] + 1:02d}.png"))
                assert saved
                result = {
                    "cycle": state["index"] + 1,
                    "requested_backend": "platform_default",
                    "graphics_api": enum_name(api),
                    "rhi_backend": enum_name(rhi.backend()),
                    "scene_graph_initialized": view.isSceneGraphInitialized(),
                    "logical_size": [view.width(), view.height()],
                    "dpr": view.devicePixelRatio(),
                    "image_size": [image.width(), image.height()],
                    "embedded_in_qwidget": container.parentWidget() is host,
                    "new_frame_count": frame["count"],
                }
                assert result["scene_graph_initialized"]
                assert result["embedded_in_qwidget"]
                state["cycles"].append(result)
                host.close()
                host.deleteLater()
                app.sendPostedEvents(None, QEvent.DeferredDelete)
                app.processEvents()
                state["index"] += 1
                if state["index"] < args.cycles:
                    QTimer.singleShot(0, guarded(run_cycle))
                else:
                    report = {
                        "source_sha": source_sha,
                        "scope": "Qt RHI 平台能力与原生嵌入；不代表 Chart 或 Blueprint 已迁移",
                        "platform": platform.platform(),
                        "pyside6": __import__("PySide6").__version__,
                        "python": sys.version,
                        "cycles": state["cycles"],
                        "pass": True,
                    }
                    (destination / "report.json").write_text(
                        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
                    print(json.dumps(report, ensure_ascii=False), flush=True)
                    app.exit(0)

            QTimer.singleShot(100, guarded(finish))

        QTimer.singleShot(500, guarded(inspect))

    QTimer.singleShot(0, guarded(run_cycle))
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
