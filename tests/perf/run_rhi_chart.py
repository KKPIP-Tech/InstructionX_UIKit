# -*- coding: utf-8 -*-
"""真实 Chart RHI 默认后端、交互与最终像素验收。"""

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

from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QImage, QPainter, QWheelEvent
from PySide6.QtOpenGLWidgets import QOpenGLWidget
from PySide6.QtQuick import QSGRendererInterface
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QVBoxLayout, QWidget

from InstructionX_UIKit.charts import ChartWidget
from InstructionX_UIKit.theme import ThemeManager
from event_scenario import run_event_scenario
from native_screen import grab_native_window


def rgba(image):
    return image.convertToFormat(QImage.Format_RGBA8888)


def reference(chart):
    dpr = chart.devicePixelRatioF()
    image = QImage(round(chart.width() * dpr), round(chart.height() * dpr),
                   QImage.Format_RGBA8888)
    image.setDevicePixelRatio(dpr)
    image.fill(0)
    painter = QPainter(image)
    try:
        chart._paint_contents(painter)
    finally:
        painter.end()
    return image


def main():
    source_sha = subprocess.check_output(
        ["git", "rev-parse", "uniform_style"], text=True, cwd=ROOT).strip()
    output = ROOT / "temp" / "performance" / source_sha / "rhi-chart"
    output.mkdir(parents=True, exist_ok=True)
    app = QApplication.instance() or QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    ThemeManager.instance().apply(app)
    host = QWidget()
    host.setWindowTitle("Chart RHI 最终像素与交互")
    layout = QVBoxLayout(host)
    layout.setContentsMargins(0, 0, 0, 0)
    chart = ChartWidget()
    chart.set_option({
        "animation": False,
        "title": {"text": "RHI Chart"},
        "legend": {"show": True},
        "tooltip": {"show": True, "trigger": "axis"},
        "xAxis": {"type": "value"},
        "yAxis": {"type": "value", "min": -2, "max": 2},
        "dataZoom": [{"type": "inside"}],
        "series": [
            {"type": "line", "name": "曲线 A", "showSymbol": False,
             "data": [__import__("math").sin(index / 30) for index in range(300)]},
            {"type": "line", "name": "曲线 B", "showSymbol": False,
             "data": [__import__("math").cos(index / 40) for index in range(300)]},
        ],
    })
    chart.anim.stop()
    chart.anim.set_progress(1.0)
    layout.addWidget(chart)
    host.resize(1000, 640)
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
            yield 1200
            viewport = chart._viewport
            assert type(viewport).__name__ == "_RhiViewport", type(viewport).__name__
            assert not host.findChildren(QOpenGLWidget)
            api = viewport._view.graphicsApi()
            if platform.system() == "Windows":
                assert api == QSGRendererInterface.GraphicsApi.Direct3D11, api
            assert os.environ.get("QSG_RENDER_LOOP") == "basic"
            checks.append("默认平台 RHI，无旧 GL 表面")

            def compare(name):
                yield 250
                actual = rgba(viewport.grab().toImage())
                expected = rgba(reference(chart))
                snapshot_image = rgba(viewport._scene._snapshot.image)
                snapshot_image.save(str(output / f"{name}_snapshot.png"))
                actual.save(str(output / f"{name}_actual.png"))
                expected.save(str(output / f"{name}_expected.png"))
                screen_image = grab_native_window(viewport._view)
                screen_image.save(str(output / f"{name}_screen.png"))
                assert snapshot_image.size() == expected.size() and snapshot_image == expected, \
                    f"{name} 的 UI 线程快照与参考不一致"
                assert actual.size() == expected.size() and actual == expected, \
                    f"{name} 的 RHI 回读与参考不一致"
                assert screen_image.size() == actual.size() and screen_image == actual, \
                    f"{name} 的桌面合成与 RHI 回读不一致"
                checks.append(name)
                print(f"  [通过] {name}：快照与桌面合成均零像素差异", flush=True)

            yield from compare("初始图像")
            container = viewport._container
            plot = chart.primary_coord().plot
            point = QPoint(round(plot.center().x()), round(plot.center().y()))
            QTest.mouseMove(viewport._view, point)
            yield 200
            assert chart.tooltip.active, "原生容器未转发 tooltip 鼠标移动"
            yield from compare("tooltip 覆盖层")

            item = chart.legend._item_rects[0]
            QTest.mouseClick(container, Qt.LeftButton, Qt.NoModifier,
                             QPoint(round(item.center().x()), round(item.center().y())))
            yield 200
            assert not chart.is_series_visible(chart.series_renderers[0].name), "图例点击未生效"
            yield from compare("图例隐藏系列")
            QTest.mouseClick(container, Qt.LeftButton, Qt.NoModifier,
                             QPoint(round(item.center().x()), round(item.center().y())))
            yield 200
            assert chart.is_series_visible(chart.series_renderers[0].name)

            zoom = next(comp for comp in chart.components if comp.option_key == "dataZoom")
            before = (zoom.start, zoom.end)
            global_point = container.mapToGlobal(point)
            event = QWheelEvent(QPointF(point), QPointF(global_point), QPoint(0, 0),
                                QPoint(0, 120), Qt.NoButton, Qt.NoModifier,
                                Qt.ScrollUpdate, False)
            QApplication.sendEvent(container, event)
            yield 200
            assert (zoom.start, zoom.end) != before, "原生容器未转发缩放滚轮"
            yield from compare("dataZoom 后图像")

            host.resize(920, 580)
            yield 600
            yield from compare("resize 高清恢复")
            ThemeManager.instance().set_mode("dark")
            ThemeManager.instance().apply(app)
            yield 300
            yield from compare("暗色主题")
            chart.hide()
            yield 100
            chart.show()
            yield 500
            yield from compare("隐藏后恢复")
            host.showMinimized()
            yield 250
            assert host.isMinimized() and not chart._ui_active, "最小化未停止图表更新"
            host.showNormal()
            yield 500
            assert not host.isMinimized() and chart._ui_active, "恢复后未重启图表更新"
            yield from compare("最小化后恢复")

            report = {
                "source_sha": source_sha,
                "backend": getattr(api, "name", str(api)),
                "rhi_backend": getattr(viewport._view.rhi().backend(), "name",
                                        str(viewport._view.rhi().backend())),
                "render_loop": os.environ.get("QSG_RENDER_LOOP"),
                "dpr": chart.devicePixelRatioF(),
                "logical_size": [chart.width(), chart.height()],
                "driver": "QTimer + app.exec；输入、抓图和窗口操作均在 GUI 事件循环内",
                "input_mode": "Qt QTest/QWheelEvent；非操作系统原生鼠标轨迹",
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
