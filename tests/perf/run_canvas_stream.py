# -*- coding: utf-8 -*-
"""多系列 Canvas 流式更新、隐藏恢复、空数据与并行帧率验证。"""

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
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QImage, QPainter
from PySide6.QtWidgets import QApplication
from InstructionX_UIKit.charts import ChartWidget
from InstructionX_UIKit.charts.canvas_viewport import CanvasLineChartViewport
from InstructionX_UIKit.theme import ThemeManager
from run_canvas_line import alpha_bbox, base_color
from run_realtime import SEED, frame_metrics


def make_chart(index):
    rng = np.random.default_rng(SEED + index)
    x = np.arange(20000, dtype=np.float64)
    series = []
    values = []
    for series_index in range(4):
        data = (np.sin(x / (700 + series_index * 130) + index)
                + 0.25 * np.cos(x / 190 + series_index)
                + rng.normal(0, 0.015, len(x)))
        values.append(data)
        series.append({"type": "line", "name": f"图 {index + 1}/系列 {series_index + 1}",
                       "data": data, "showSymbol": False})
    chart = ChartWidget()
    chart.set_option({"animation": False, "xAxis": {"type": "value"},
                      "yAxis": {"type": "value", "min": -2, "max": 2},
                      "series": series})
    chart.anim.stop()
    chart.anim.set_progress(1.0)
    chart.resize(1268, 850)
    chart.show()
    chart._layout_all(force=True)
    chart.hide()
    viewport = CanvasLineChartViewport(chart, parent=chart)
    old = chart._viewport
    chart._viewport = viewport
    old.close()
    old.deleteLater()
    chart.show()
    return chart, viewport, values


def reference(chart, dpr):
    image = QImage(round(chart.width() * dpr), round(chart.height() * dpr),
                   QImage.Format_ARGB32_Premultiplied)
    image.setDevicePixelRatio(dpr)
    image.fill(Qt.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.Antialiasing)
    for renderer in chart.series_renderers:
        renderer.paint(painter, 1.0)
    painter.end()
    return image.convertToFormat(QImage.Format_RGBA8888)


def models_match(chart, viewport):
    if len(viewport._line_views) != len(chart.series_renderers):
        return False
    for model, renderer in zip(viewport._line_views, chart.series_renderers):
        if model._renderer is not renderer:
            return False
        geometry = model._screen_geometry
        if geometry is None:
            if model._points != renderer._points:
                return False
            continue
        renderer._ensure_legacy_geometry()
        if len(renderer._points) != len(geometry[0]) or any(
                abs(point.x() - float(x)) > 1e-9 or abs(point.y() - float(y)) > 1e-9
                for point, x, y in zip(renderer._points, *geometry)):
            return False
    return True


def main():
    app = QApplication.instance() or QApplication(sys.argv)
    ThemeManager.instance().apply(app)
    charts = []
    for index in range(2):
        chart, viewport, values = make_chart(index)
        charts.append((chart, viewport, values))
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
    timer.setInterval(16)
    timer.timeout.connect(load)
    timer.start()
    QTimer.singleShot(1000, lambda: state.update(recording=True))

    def captured(index, image):
        state["images"][index] = image
        if len(state["images"]) == len(charts):
            app.quit()

    QTimer.singleShot(4000, lambda: [viewport.grab_canvas(
        lambda image, index=index: captured(index, image))
        for index, (_chart, viewport, _values) in enumerate(charts)])
    QTimer.singleShot(15000, lambda: app.exit(2))
    result = app.exec()
    timer.stop()
    source_sha = subprocess.check_output(["git", "rev-parse", "uniform_style"],
                                         cwd=ROOT, text=True).strip()
    destination = ROOT / "temp" / "performance" / source_sha / "canvas-stream"
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
        actual_bbox = alpha_bbox(actual)
        expected_bbox = alpha_bbox(expected)
        geometry_ok = actual_bbox is not None and expected_bbox is not None and all(
            abs(a - b) <= 2 for a, b in zip(actual_bbox, expected_bbox))
        expected_colors = {tuple(renderer.color().getRgb()) for renderer in chart.series_renderers}
        color_ok = base_color(actual) in [list(color) for color in expected_colors]
        plot = chart.primary_coord().plot
        dpr = viewport.devicePixelRatioF()
        pixels = np.frombuffer(actual.constBits(), dtype=np.uint8).reshape(
            actual.height(), actual.width(), 4)
        left = max(0, int((plot.left() - 8) * dpr))
        top = max(0, int((plot.top() - 8) * dpr))
        right = min(actual.width(), int(np.ceil((plot.right() + 8) * dpr)))
        bottom = min(actual.height(), int(np.ceil((plot.bottom() + 8) * dpr)))
        outside = pixels[:, :, 3].copy()
        outside[top:bottom, left:right] = 0
        clip_ok = int(np.count_nonzero(outside)) == 0
        models_ok = models_match(chart, viewport)
        metrics = frame_metrics(f"chart_{index}", state["frames"][index])
        chart_pass = bool(geometry_ok and clip_ok and color_ok and models_ok
                          and metrics["pass"] and max(viewport.paint_times) < 100)
        reports[str(index)] = {
            "backend": getattr(viewport.api(), "name", str(viewport.api())),
            "actual_bbox": actual_bbox, "expected_bbox": expected_bbox,
            "geometry_pass": geometry_ok, "clip_pass": clip_ok,
            "color_pass": color_ok, "models_pass": models_ok,
            "metrics": metrics, "command_max_ms": max(viewport.paint_times, default=0.0),
            "sync_max_ms": max(viewport.sync_times, default=0.0),
            "pass": chart_pass,
        }
        actual.save(str(destination / f"chart_{index}_actual.png"))
        expected.save(str(destination / f"chart_{index}_reference.png"))
        all_pass = all_pass and chart_pass and reports[str(index)]["backend"] == "Direct3D11"
    chart, viewport, values = charts[0]
    before = [(model._points, model._screen_geometry) for model in viewport._line_views]
    chart.hide()
    hidden_ok = not chart._ui_active
    for series_index, data in enumerate(values):
        chart.set_stream_data(np.roll(data, 1000 + series_index), series=series_index)
    hidden_ok = hidden_ok and all(
        (model._points, model._screen_geometry) == previous
        for model, previous in zip(viewport._line_views, before))
    chart.show()
    app.processEvents()
    recovered_ok = chart._ui_active and models_match(chart, viewport)
    for _chart, _viewport, _values in charts:
        _chart.close()
    app.processEvents()
    report = {"source_sha": source_sha,
              "test_sha": subprocess.check_output(["git", "rev-parse", "HEAD"],
                                                   cwd=ROOT, text=True).strip(),
              "source_dirty": subprocess.run(
                  ["git", "diff", "--quiet", source_sha, "--", "InstructionX_UIKit", "demo"],
                  cwd=ROOT).returncode != 0,
              "time_utc": datetime.now(timezone.utc).isoformat(),
              "scope": "两个仅 line 的 Canvas 图表；其他系列与轴组件另行验收",
              "charts": reports, "hidden_pause_pass": hidden_ok,
              "recover_latest_pass": recovered_ok,
              "pass": bool(all_pass and hidden_ok and recovered_ok)}
    empty = ChartWidget()
    empty.set_option({"series": []})
    empty_viewport = CanvasLineChartViewport(empty, parent=empty)
    empty_old = empty._viewport
    empty._viewport = empty_viewport
    empty_old.close()
    empty_old.deleteLater()
    empty.show()
    empty_report = {"models": len(empty_viewport._line_views),
                    "pass": len(empty_viewport._line_views) == 0}
    empty.close()
    report["empty"] = empty_report
    report["pass"] = report["pass"] and empty_report["pass"]
    (destination / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False), flush=True)
    print(f"原始报告：{destination / 'report.json'}", flush=True)
    return 0 if report["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
