# -*- coding: utf-8 -*-
"""Canvas 实线真实 GPU 的几何、颜色、帧率与资源验证。"""

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests" / "perf"))
os.environ.pop("QT_QPA_PLATFORM", None)

import numpy as np
from PySide6.QtCore import QRectF, Qt, QTimer
from PySide6.QtGui import QImage, QPainter
from PySide6.QtWidgets import QApplication
from InstructionX_UIKit.charts import ChartWidget
from InstructionX_UIKit.charts.canvas_viewport import CanvasLineViewport
from InstructionX_UIKit.theme import ThemeManager
from run_realtime import SEED, frame_metrics


def alpha_bbox(image):
    pixels = np.frombuffer(image.constBits(), dtype=np.uint8).reshape(
        image.height(), image.width(), 4)
    ys, xs = np.where(pixels[:, :, 3] != 0)
    if not len(xs):
        return None
    return [int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())]


def base_color(image):
    pixels = np.frombuffer(image.constBits(), dtype=np.uint8).reshape(-1, 4)
    opaque = pixels[pixels[:, 3] == 255]
    if not len(opaque):
        return None
    colors, counts = np.unique(opaque, axis=0, return_counts=True)
    return colors[int(np.argmax(counts))].tolist()


def main():
    app = QApplication.instance() or QApplication(sys.argv)
    ThemeManager.instance().apply(app)
    rng = np.random.default_rng(SEED)
    x = np.arange(20000, dtype=np.float64)
    values = np.sin(x / 700) + 0.25 * np.cos(x / 190) + rng.normal(0, 0.015, len(x))
    chart = ChartWidget()
    chart.set_option({"animation": False, "xAxis": {"type": "value"},
                      "yAxis": {"type": "value", "min": -2, "max": 2},
                      "series": [{"type": "line", "data": values, "showSymbol": False}]})
    chart.anim.stop()
    chart.anim.set_progress(1.0)
    chart.resize(1268, 850)
    chart.show()
    app.processEvents()
    chart._layout_all(force=True)
    chart.hide()
    chart._viewport._view.hide()
    renderer = chart.series_renderers[0]
    coord = chart.primary_coord()
    viewport = CanvasLineViewport(renderer, coord)
    viewport.resize(chart.width(), chart.height())
    viewport.move(0, 0)
    viewport.show()
    state = {"recording": False, "frames": [], "errors": [], "image": None}
    viewport.frameSubmitted.connect(
        lambda: state["frames"].append(__import__("time").perf_counter())
        if state["recording"] else None)
    timer = QTimer(viewport)
    timer.setInterval(0)
    timer.timeout.connect(viewport.update)
    timer.start()
    QTimer.singleShot(1000, lambda: state.update(recording=True))
    QTimer.singleShot(4000, lambda: viewport.grab_canvas(
        lambda image: (state.update(image=image), app.quit())))
    QTimer.singleShot(12000, lambda: app.exit(2))
    result = app.exec()
    timer.stop()
    report = {"errors": list(state["errors"])}
    if state["image"] is None:
        report["pass"] = False
        report["error"] = f"回读未完成: {result}"
        print(json.dumps(report, ensure_ascii=False), flush=True)
        return 1
    dpr = viewport.devicePixelRatioF()
    expected = QImage(round(chart.width() * dpr), round(chart.height() * dpr),
                      QImage.Format_ARGB32_Premultiplied)
    expected.setDevicePixelRatio(dpr)
    expected.fill(Qt.transparent)
    painter = QPainter(expected)
    painter.setRenderHint(QPainter.Antialiasing)
    renderer.paint(painter, 1.0)
    painter.end()
    actual = state["image"].convertToFormat(QImage.Format_RGBA8888)
    expected = expected.convertToFormat(QImage.Format_RGBA8888)
    actual_bbox = alpha_bbox(actual)
    expected_bbox = alpha_bbox(expected)
    geometry_ok = actual_bbox is not None and expected_bbox is not None and all(
        abs(a - b) <= 2 for a, b in zip(actual_bbox, expected_bbox))
    pixels = np.frombuffer(actual.constBits(), dtype=np.uint8).reshape(
        actual.height(), actual.width(), 4)
    plot = coord.plot
    outer = QRectF(plot).adjusted(-8, -8, 8, 8)
    left = max(0, int(outer.left() * dpr))
    top = max(0, int(outer.top() * dpr))
    right = min(actual.width(), int(np.ceil(outer.right() * dpr)))
    bottom = min(actual.height(), int(np.ceil(outer.bottom() * dpr)))
    outside = pixels[:, :, 3].copy()
    outside[top:bottom, left:right] = 0
    clip_ok = int(np.count_nonzero(outside)) == 0
    expected_color = list(renderer.color().getRgb())
    actual_color = base_color(actual)
    color_ok = actual_color == expected_color
    delta = pixels.astype(np.int16) - np.frombuffer(
        expected.constBits(), dtype=np.uint8).reshape(
            expected.height(), expected.width(), 4).astype(np.int16)
    metrics = frame_metrics("canvas", state["frames"])
    backend = getattr(viewport.api(), "name", str(viewport.api()))
    source_sha = subprocess.check_output(["git", "rev-parse", "uniform_style"],
                                         cwd=ROOT, text=True).strip()
    report.update({
        "source_sha": source_sha,
        "test_sha": subprocess.check_output(["git", "rev-parse", "HEAD"],
                                             cwd=ROOT, text=True).strip(),
        "source_dirty": subprocess.run(
            ["git", "diff", "--quiet", source_sha, "--", "InstructionX_UIKit", "demo"],
            cwd=ROOT).returncode != 0,
        "time_utc": datetime.now(timezone.utc).isoformat(),
        "backend": backend, "points": len(renderer._points), "dpr": dpr,
        "physical_size": [actual.width(), actual.height()],
        "timer_interval_ms": timer.interval(),
        "workload": "静态路径连续重绘；不减少点、不关闭抗锯齿、不使用整帧 QImage",
        "actual_bbox": actual_bbox, "expected_bbox": expected_bbox,
        "geometry_pass": geometry_ok, "clip_pass": clip_ok,
        "expected_color": expected_color, "actual_color": actual_color,
        "color_pass": color_ok,
        "qpainter_changed_pixels": int(np.any(delta.reshape(-1, 4), axis=1).sum()),
        "qpainter_max_delta": int(np.abs(delta).max()),
        "qpainter_pixel_equality_required": False,
        "allowed_rasterization": "QCanvasPainter / QRhi（所有者已允许抗锯齿算法差异）",
        "command_mean_ms": float(np.mean(viewport.paint_times)),
        "command_max_ms": float(np.max(viewport.paint_times)),
        "metrics": metrics,
        "pass": bool(result == 0 and backend == "Direct3D11" and geometry_ok
                     and clip_ok and color_ok and metrics["pass"]
                     and max(viewport.paint_times) < 100),
    })
    destination = ROOT / "temp" / "performance" / source_sha / "canvas-line"
    destination.mkdir(parents=True, exist_ok=True)
    actual.save(str(destination / "actual.png"))
    expected.save(str(destination / "reference.png"))
    (destination / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    viewport.close()
    chart.close()
    app.processEvents()
    print(json.dumps(report, ensure_ascii=False), flush=True)
    print(f"原始报告：{destination / 'report.json'}", flush=True)
    return 0 if report["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
