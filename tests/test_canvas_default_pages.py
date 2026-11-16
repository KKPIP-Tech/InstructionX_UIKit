# -*- coding: utf-8 -*-
"""真实窗口回归：图表/蓝图默认直接 Canvas、首帧绘制与重复页面切换。"""

import os
import sys
from pathlib import Path

if os.environ.get("QT_QPA_PLATFORM", "").lower() in ("offscreen", "minimal"):
    print("[跳过] 默认 Canvas 原生窗口回归仅在真实桌面运行")
    sys.exit(0)

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import collections  # noqa: E402
from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from InstructionX_UIKit.theme import ThemeManager  # noqa: E402
from InstructionX_UIKit.charts import ChartWidget  # noqa: E402
from InstructionX_UIKit.blueprint import BlueprintCanvas  # noqa: E402
from demo.main_window import MainWindow  # noqa: E402
from tests.perf.native_input import activate_window  # noqa: E402
from tests.perf.native_screen import grab_native_window  # noqa: E402


def main():
    app = QApplication(sys.argv)
    ThemeManager.instance().apply(app)
    window = MainWindow()
    window.show()
    errors = []

    def check_charts():
        if not activate_window(window):
            errors.append("图表测试窗口未能置前")
        charts = window._page_cache["charts"].findChildren(ChartWidget)
        counts = collections.Counter(c._viewport.active_backend() for c in charts)
        print(f"[图表] 数量={len(charts)} 后端={dict(counts)}", flush=True)
        if len(charts) != 28 or counts != {"canvas-widget": 28}:
            errors.append(f"图表默认后端错误: {dict(counts)}")
        for chart in charts[:3]:
            viewport = chart._viewport
            print(f"[首帧] sync={len(viewport.sync_times)} "
                  f"paint={len(viewport.paint_times)} api={viewport.rhi_api()}", flush=True)
            if not viewport.paint_times:
                errors.append("图表视口没有发生真实 paint")
        grab_native_window(window).save(str(
            ROOT / "tests" / "shots" / "canvas_default_charts.png"))

    def check_blueprint():
        if not activate_window(window):
            errors.append("蓝图测试窗口未能置前")
        canvases = window.findChildren(BlueprintCanvas)
        counts = collections.Counter(c._viewport.active_backend() for c in canvases)
        print(f"[蓝图] 数量={len(canvases)} 后端={dict(counts)}", flush=True)
        if len(canvases) != 2 or counts != {"canvas-widget": 2}:
            errors.append(f"蓝图默认后端错误: {dict(counts)}")
        for canvas in canvases:
            if not canvas._viewport.paint_times:
                errors.append("蓝图画布没有发生真实 paint")
        grab_native_window(window).save(str(
            ROOT / "tests" / "shots" / "canvas_default_blueprint.png"))

    def finish():
        window.close()
        app.exit(1 if errors else 0)

    steps = [
        (500, lambda: window.navigate("charts")),
        (4000, check_charts),
        (5000, lambda: window.navigate("tokens")),
        (6000, lambda: window.navigate("charts")),
        (8000, lambda: window.navigate("blueprint")),
        (10500, check_blueprint),
        (11500, lambda: window.navigate("tokens")),
        (12500, lambda: window.navigate("blueprint")),
        (14000, finish),
    ]
    for delay, callback in steps:
        QTimer.singleShot(delay, callback)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
