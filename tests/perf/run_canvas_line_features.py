# -*- coding: utf-8 -*-
"""Canvas 折线扩展形态的几何、颜色、裁剪与自一致验证。"""

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
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtWidgets import QApplication
from InstructionX_UIKit.charts import ChartWidget
from InstructionX_UIKit.charts.canvas_viewport import CanvasLineViewport
from InstructionX_UIKit.theme import T, ThemeManager
from run_canvas_line import alpha_bbox, base_color


def grab_pair(viewport, app, points):
    result = {}

    def second(image):
        result["second"] = image
        app.quit()

    def first(image):
        result["first"] = image
        viewport.set_paths(points)
        QTimer.singleShot(100, lambda: viewport.grab_canvas(second))

    QTimer.singleShot(400, lambda: viewport.grab_canvas(first))
    QTimer.singleShot(6000, lambda: app.exit(2))
    if app.exec() != 0 or result.get("first") is None or result.get("second") is None:
        raise RuntimeError("Canvas 回读失败")
    return (result["first"].convertToFormat(QImage.Format_RGBA8888),
            result["second"].convertToFormat(QImage.Format_RGBA8888))


def render_case(app, name, series, dark=False):
    previous_mode = ThemeManager.instance().mode
    chart = ChartWidget()
    chart.set_option({"animation": False, "xAxis": {"type": "value"},
                      "yAxis": {"type": "value", "min": -2, "max": 2},
                      "series": [series]})
    chart.anim.stop()
    chart.anim.set_progress(1.0)
    chart.resize(800, 500)
    chart.show()
    app.processEvents()
    chart._layout_all(force=True)
    chart.hide()
    chart._viewport._view.hide()
    renderer = chart.series_renderers[0]
    coord = chart.primary_coord()
    viewport = CanvasLineViewport(renderer, coord)
    viewport.resize(chart.width(), chart.height())
    if dark:
        ThemeManager.instance().set_mode("dark")
    viewport.show()
    actual, repeated = grab_pair(viewport, app, renderer._points)
    repeat_changed = int(actual != repeated)
    expected = QImage(round(chart.width() * viewport.devicePixelRatioF()),
                      round(chart.height() * viewport.devicePixelRatioF()),
                      QImage.Format_ARGB32_Premultiplied)
    expected.setDevicePixelRatio(viewport.devicePixelRatioF())
    expected.fill(Qt.transparent)
    painter = QPainter(expected)
    painter.setRenderHint(QPainter.Antialiasing)
    renderer.paint(painter, 1.0)
    painter.end()
    expected = expected.convertToFormat(QImage.Format_RGBA8888)
    actual_bbox = alpha_bbox(actual)
    expected_bbox = alpha_bbox(expected)
    geometry_ok = actual_bbox is not None and expected_bbox is not None and all(
        abs(a - b) <= 2 for a, b in zip(actual_bbox, expected_bbox))
    commands = sum(path.commandsSize() for path in viewport._paths)
    data_size = sum(path.commandsDataSize() for path in viewport._paths)
    if name == "smooth":
        structure_ok = commands == len(renderer._points) \
            and data_size == 2 + 6 * (len(renderer._points) - 1)
    elif name == "step":
        structure_ok = commands == 3 * len(renderer._points) - 2 \
            and data_size == 2 * commands
    elif name == "area":
        structure_ok = bool(getattr(viewport, "_areas", []))
    elif name in ("dash", "dot"):
        structure_ok = bool(getattr(viewport, "_dashes", []))
    elif name in ("symbols", "symbols_dark"):
        expected_count = renderer._last_symbol_count
        structure_ok = 0 < getattr(viewport, "_last_symbol_count", 0) == expected_count
    else:
        structure_ok = True
    dpr = viewport.devicePixelRatioF()
    pixels = np.frombuffer(actual.constBits(), dtype=np.uint8).reshape(
        actual.height(), actual.width(), 4)
    expected_pixels = np.frombuffer(expected.constBits(), dtype=np.uint8).reshape(
        expected.height(), expected.width(), 4)
    actual_ink = int(np.count_nonzero(pixels[:, :, 3]))
    expected_ink = int(np.count_nonzero(expected_pixels[:, :, 3]))
    ink_ratio = actual_ink / expected_ink if expected_ink else 0.0
    ink_ratio_ok = ink_ratio >= 0.55 if name == "area" else True
    outer = QRectF(coord.plot).adjusted(-8, -8, 8, 8)
    left = max(0, int(outer.left() * dpr))
    top = max(0, int(outer.top() * dpr))
    right = min(actual.width(), int(np.ceil(outer.right() * dpr)))
    bottom = min(actual.height(), int(np.ceil(outer.bottom() * dpr)))
    outside = pixels[:, :, 3].copy()
    outside[top:bottom, left:right] = 0
    clip_ok = int(np.count_nonzero(outside)) == 0
    expected_color = list(renderer.color().getRgb())
    actual_color = base_color(actual)
    if name in ("symbols", "symbols_dark"):
        color_ok = viewport._color.getRgb() == tuple(expected_color) and actual_color in (
            expected_color, list(QColor(T("color.bg.elevated")).getRgb()))
    else:
        color_ok = actual_color == expected_color
    delta = pixels.astype(np.int16) - expected_pixels.astype(np.int16)
    backend = getattr(viewport.api(), "name", str(viewport.api()))
    report = {
        "backend": backend,
        "geometry_pass": geometry_ok, "clip_pass": clip_ok,
        "color_pass": color_ok, "repeat_changed": repeat_changed,
        "structure_pass": structure_ok, "path_commands": commands,
        "actual_ink": actual_ink, "expected_ink": expected_ink,
        "ink_ratio": ink_ratio, "ink_ratio_pass": ink_ratio_ok,
        "actual_bbox": actual_bbox, "expected_bbox": expected_bbox,
        "expected_color": expected_color, "actual_color": actual_color,
        "viewport_color": list(viewport._color.getRgb()),
        "qpainter_changed_pixels": int(np.any(delta.reshape(-1, 4), axis=1).sum()),
        "qpainter_max_delta": int(np.abs(delta).max()),
        "command_max_ms": max(viewport.paint_times, default=0.0),
        "pass": bool(backend == "Direct3D11" and geometry_ok and clip_ok and color_ok
                     and not repeat_changed and structure_ok and ink_ratio_ok),
    }
    viewport.close()
    chart.close()
    ThemeManager.instance().set_mode(previous_mode)
    app.processEvents()
    return report, actual, expected


def main():
    app = QApplication.instance() or QApplication(sys.argv)
    ThemeManager.instance().apply(app)
    values = np.sin(np.arange(80) / 7) + np.cos(np.arange(80) / 13) * 0.3
    cases = {
        "smooth": {"type": "line", "data": values, "smooth": True, "showSymbol": False},
        "step": {"type": "line", "data": values, "step": "middle", "showSymbol": False},
        "area": {"type": "line", "data": values,
                 "areaStyle": {"opacity": 0.22}, "showSymbol": False},
        "dash": {"type": "line", "data": values,
                 "lineStyle": {"type": "dashed"}, "showSymbol": False},
        "dot": {"type": "line", "data": values,
                "lineStyle": {"type": "dotted"}, "showSymbol": False},
        "symbols": {"type": "line", "data": values, "showSymbol": True},
        "symbols_dark": {"type": "line", "data": values, "showSymbol": True},
    }
    source_sha = subprocess.check_output(["git", "rev-parse", "uniform_style"],
                                         cwd=ROOT, text=True).strip()
    destination = ROOT / "temp" / "performance" / source_sha / "canvas-line-features"
    destination.mkdir(parents=True, exist_ok=True)
    report = {"source_sha": source_sha,
              "test_sha": subprocess.check_output(["git", "rev-parse", "HEAD"],
                                                   cwd=ROOT, text=True).strip(),
              "source_dirty": subprocess.run(
                  ["git", "diff", "--quiet", source_sha, "--", "InstructionX_UIKit", "demo"],
                  cwd=ROOT).returncode != 0,
              "time_utc": datetime.now(timezone.utc).isoformat(),
              "qpainter_pixel_equality_required": False,
              "cases": {}}
    for name, series in cases.items():
        try:
            case, actual, expected = render_case(app, name, series, dark=name == "symbols_dark")
            actual.save(str(destination / f"{name}_actual.png"))
            expected.save(str(destination / f"{name}_reference.png"))
        except Exception as exc:
            case = {"pass": False, "error": repr(exc)}
        case["backend"] = case.get("backend", "unknown")
        report["cases"][name] = case
        print(name, case, flush=True)
    report["pass"] = all(case.get("pass", False) for case in report["cases"].values())
    (destination / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"pass": report["pass"], "report": str(destination / "report.json")},
                     ensure_ascii=False), flush=True)
    return 0 if report["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
