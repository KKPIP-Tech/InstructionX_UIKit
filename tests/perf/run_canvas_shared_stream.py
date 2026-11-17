# -*- coding: utf-8 -*-
"""同一顶层窗口两个共享 Canvas Item 图表的连续满载验收。"""

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests" / "perf"))
os.environ.pop("QT_QPA_PLATFORM", None)

import numpy as np
from PySide6.QtCore import QRectF, Qt, QTimer
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication, QHBoxLayout, QMainWindow, QWidget
from InstructionX_UIKit.charts import ChartWidget
from InstructionX_UIKit.charts.canvas_item_viewport import CanvasItemLineChartViewport
from InstructionX_UIKit.theme import ThemeManager
from run_canvas_stream import models_match, reference
from run_canvas_line_features import series_clip_ok, series_color_count, series_ink_bbox
from run_realtime import SEED, frame_metrics


def main():
    app = QApplication.instance() or QApplication(sys.argv)
    ThemeManager.instance().apply(app)
    window = QMainWindow()
    central = QWidget(window)
    layout = QHBoxLayout(central)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(0)
    window.setCentralWidget(central)
    charts = []
    for index in range(2):
        rng = np.random.default_rng(SEED + index)
        x = np.arange(20000, dtype=np.float64)
        values = []
        series = []
        for series_index in range(4):
            data = (np.sin(x / (700 + series_index * 130) + index)
                    + 0.25 * np.cos(x / 190 + series_index)
                    + rng.normal(0, 0.015, len(x)))
            values.append(data)
            series.append({"type": "line", "data": data, "showSymbol": False})
        chart = ChartWidget()
        chart.set_option({"animation": False, "xAxis": {"type": "value"},
                          "yAxis": {"type": "value", "min": -2, "max": 2},
                          "series": series})
        chart.anim.stop()
        chart.anim.set_progress(1.0)
        layout.addWidget(chart)
        viewport = CanvasItemLineChartViewport(chart, parent=chart)
        old = chart._viewport
        chart._viewport = viewport
        old.close()
        old.deleteLater()
        viewport.show()
        charts.append((chart, viewport, values))
    window.resize(2536, 850)
    window.show()
    state = {"tick": 0, "recording": False, "frames": {0: [], 1: []}, "images": {}}
    for index, (_chart, viewport, _values) in enumerate(charts):
        viewport.frameSubmitted.connect(
            lambda index=index: state["frames"][index].append(time.perf_counter())
            if state["recording"] else None)

    def load():
        for _chart, _viewport, values in charts:
            for series_index, data in enumerate(values):
                if not _chart.set_stream_data(np.roll(data, state["tick"] * 17 + series_index),
                                              series=series_index):
                    raise RuntimeError("set_stream_data 返回 False")
        state["tick"] += 1

    timer = QTimer()
    timer.setTimerType(Qt.PreciseTimer)
    timer.setInterval(0)
    timer.timeout.connect(load)
    timer.start()
    QTimer.singleShot(1000, lambda: state.update(recording=True))

    def captured(index, image):
        state["images"][index] = image
        if len(state["images"]) == len(charts):
            app.exit(0)

    def capture_all():
        timer.stop()
        state["recording"] = False
        for _chart, viewport, _values in charts:
            viewport._sync_now()
        for index, (_chart, viewport, _values) in enumerate(charts):
            viewport.grab_canvas(lambda image, index=index: captured(index, image))

    QTimer.singleShot(4000, capture_all)
    QTimer.singleShot(15000, lambda: app.exit(2))
    result = app.exec()
    timer.stop()
    source_sha = subprocess.check_output(["git", "rev-parse", "uniform_style"],
                                         cwd=ROOT, text=True).strip()
    destination = ROOT / "temp" / "performance" / source_sha / "canvas-shared-stream"
    destination.mkdir(parents=True, exist_ok=True)
    reports = {}
    all_pass = result == 0 and len(state["images"]) == len(charts)
    for index, (chart, viewport, _values) in enumerate(charts):
        image = state["images"].get(index)
        if image is None:
            reports[str(index)] = {"pass": False, "error": "未收到回读"}
            all_pass = False
            continue
        actual = image.convertToFormat(QImage.Format_RGBA8888)
        expected = reference(chart, viewport.devicePixelRatioF())
        actual_bbox = series_ink_bbox(actual)
        expected_bbox = series_ink_bbox(expected)
        geometry_ok = actual_bbox is not None and expected_bbox is not None and all(
            abs(a - b) <= 2 for a, b in zip(actual_bbox, expected_bbox))
        colors = {tuple(renderer.color().getRgb()) for renderer in chart.series_renderers}
        color_ok = all(series_color_count(actual, color) > 0 for color in colors)
        plot = chart.primary_coord().plot
        dpr = viewport.devicePixelRatioF()
        outer = QRectF(plot).adjusted(-8, -8, 8, 8)
        clip_ok = series_clip_ok(actual, colors, outer, chart.legend._item_rects, dpr)
        models_ok = models_match(chart, viewport)
        metrics = frame_metrics(f"chart_{index}", state["frames"][index])
        passed = bool(geometry_ok and color_ok and clip_ok and models_ok
                      and metrics["pass"] and max(viewport.paint_times) < 100
                      and viewport.rhi_api() == "Direct3D11")
        reports[str(index)] = {
            "backend": viewport.rhi_api(), "geometry_pass": geometry_ok,
            "color_pass": color_ok, "clip_pass": clip_ok, "models_pass": models_ok,
            "actual_bbox": actual_bbox, "expected_bbox": expected_bbox,
            "metrics": metrics, "command_max_ms": max(viewport.paint_times, default=0),
            "sync_max_ms": max(viewport.sync_times, default=0), "pass": passed,
        }
        actual.save(str(destination / f"chart_{index}_actual.png"))
        expected.save(str(destination / f"chart_{index}_reference.png"))
        all_pass = all_pass and passed
    chart, viewport, values = charts[0]
    before = [(model._points, model._screen_geometry) for model in viewport._line_views]
    chart.hide()
    hidden_ok = not chart._ui_active
    for series_index, data in enumerate(values):
        chart.set_stream_data(np.roll(data, 1000 + series_index), series=series_index)
    hidden_ok = hidden_ok and all(
        model._points is points and model._screen_geometry is geometry
        for model, (points, geometry) in zip(viewport._line_views, before))
    chart.show()
    app.processEvents()
    recovered_ok = chart._ui_active and models_match(chart, viewport)
    shared_ok = charts[0][1]._view is charts[1][1]._view
    for _chart, _viewport, _values in charts:
        _chart.close()
    window.close()
    app.processEvents()
    report = {
        "source_sha": source_sha,
        "test_sha": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "source_dirty": subprocess.run(
            ["git", "diff", "--quiet", source_sha, "--", "InstructionX_UIKit", "demo"],
            cwd=ROOT).returncode != 0,
        "time_utc": datetime.now(timezone.utc).isoformat(),
        "scope": "一个顶层窗口中的两个 line 图表；其他系列和组件另行验收",
        "producer_interval_ms": 0, "producer_ticks": state["tick"],
        "shared_view_pass": shared_ok, "charts": reports,
        "hidden_pause_pass": hidden_ok, "recover_latest_pass": recovered_ok,
        "pass": bool(all_pass and shared_ok and hidden_ok and recovered_ok),
    }
    (destination / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False), flush=True)
    print(f"原始报告：{destination / 'report.json'}", flush=True)
    return 0 if report["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
