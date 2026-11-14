# -*- coding: utf-8 -*-
"""Chart RHI 快照、完整 option 与旧 GL 清除回归。"""

import os
import sys
import traceback
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PySide6.QtGui import QImage, QPainter
from PySide6.QtWidgets import QApplication

from InstructionX_UIKit.charts import ChartWidget
from InstructionX_UIKit.charts.scene_snapshot import build_scene_snapshot
from InstructionX_UIKit.theme import ThemeManager

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


def settle(chart):
    chart.anim.stop()
    chart.anim.set_progress(1.0)
    chart._layout_all(force=True)


def reference(chart, dpr=1.0):
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


def rgba(image):
    return image.convertToFormat(QImage.Format_RGBA8888)


@check("Chart 不再保留旧 GL 后端")
def _():
    source = (ROOT / "InstructionX_UIKit" / "charts" / "viewport.py").read_text(
        encoding="utf-8")
    for token in ("QOpenGLWidget", "QOpenGLContext", "gl_available",
                  "_GLViewport", "UIKIT_CHART_GL"):
        assert token not in source, token
    assert not (ROOT / "InstructionX_UIKit" / "charts" / "gl_series.py").exists()
    source = (ROOT / "InstructionX_UIKit" / "charts" / "series_cartesian.py").read_text(
        encoding="utf-8")
    assert "from .gl_series" not in source
    main = (ROOT / "main.py").read_text(encoding="utf-8")
    assert "setGraphicsApi" not in main


@check("普通折线快照与既有最终图像逐像素一致")
def _():
    chart = ChartWidget()
    chart.resize(720, 420)
    chart.set_option({
        "animation": False,
        "xAxis": {"type": "value"}, "yAxis": {"type": "value"},
        "series": [{"type": "line", "data": [1, 3, 2, 5, 4], "showSymbol": False}],
    })
    settle(chart)
    snapshot = build_scene_snapshot(chart, 1.0)
    assert hasattr(snapshot, "image"), "RHI 快照必须提供完整最终帧"
    assert rgba(snapshot.image) == rgba(reference(chart))
    chart.close()


@check("smooth、面积、散点、tooltip 和组件不丢失")
def _():
    chart = ChartWidget()
    chart.resize(720, 420)
    chart.set_option({
        "animation": False,
        "title": {"text": "完整能力"},
        "xAxis": {"type": "value"}, "yAxis": {"type": "value"},
        "tooltip": {"show": True, "trigger": "axis"},
        "dataZoom": [{"type": "inside"}],
        "series": [
            {"type": "line", "name": "面积", "data": [1, 3, 2, 5, 4],
             "smooth": True, "areaStyle": {}, "lineStyle": {"type": "dashed"}},
            {"type": "scatter", "name": "散点", "data": [[0, 2], [1, 4], [3, 1]]},
        ],
    })
    settle(chart)
    chart._update_tooltip(chart.primary_coord().plot.center())
    snapshot = build_scene_snapshot(chart, 1.0)
    assert rgba(snapshot.image) == rgba(reference(chart))
    assert chart._components
    chart.close()


@check("RHI 快照保持高 DPR 最终像素")
def _():
    chart = ChartWidget()
    chart.resize(640, 360)
    chart.set_option({
        "animation": False,
        "polar": {},
        "series": [{"type": "pie", "data": [2, 3, 4]}],
    })
    settle(chart)
    snapshot = build_scene_snapshot(chart, 1.5)
    expected = reference(chart, 1.5)
    assert snapshot.image.size() == expected.size()
    assert snapshot.image.devicePixelRatio() == 1.5
    assert rgba(snapshot.image) == rgba(expected)
    chart.close()


if __name__ == "__main__":
    raise SystemExit(1 if _FAILURES else 0)
