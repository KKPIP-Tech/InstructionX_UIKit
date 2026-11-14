# -*- coding: utf-8 -*-
"""可复现的 QWidget 图表诊断基线（不是实际呈现 FPS）。"""

import hashlib
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import numpy as np
from PySide6.QtGui import QImage, QPainter
from PySide6.QtWidgets import QApplication

from InstructionX_UIKit.charts import ChartWidget
from InstructionX_UIKit.theme import ThemeManager

SEED = 20261114
BASE_SHA = "949b7288a50b6ed5beed744db3c8bf46a13c00ef"


def make_values(count):
    rng = np.random.default_rng(SEED)
    x = np.arange(count, dtype=np.float64)
    values = np.sin(x / max(1.0, count / 40.0)) + rng.normal(0, 0.03, count)
    return values


def measure(chart, frames=5):
    image = QImage(1400, 500, QImage.Format_ARGB32_Premultiplied)
    times = []

    def frame():
        chart._layout_all(force=True)
        painter = QPainter(image)
        chart._paint_contents(painter)
        painter.end()

    frame()
    for _ in range(frames):
        started = time.perf_counter()
        frame()
        times.append((time.perf_counter() - started) * 1000)
    renderer = chart.series_renderers[0]
    points = [point for point in renderer._points if point is not None]
    plot = chart.primary_coord().plot
    x_span = max(point.x() for point in points) - min(point.x() for point in points)
    y_span = max(point.y() for point in points) - min(point.y() for point in points)
    assert x_span >= plot.width() * 0.8, (x_span, plot.width())
    assert y_span >= plot.height() * 0.4, (y_span, plot.height())
    return times, {"x_span": x_span, "y_span": y_span,
                   "plot_width": plot.width(), "plot_height": plot.height()}


def main():
    app = QApplication(sys.argv)
    ThemeManager.instance().apply(app)
    output = {
        "note": "仅离屏诊断，不是实际呈现 FPS",
        "base_source_sha": BASE_SHA,
        "seed": SEED,
        "cases": [],
    }
    for count in (10_000, 100_000, 1_000_000):
        values = make_values(count)
        chart = ChartWidget()
        chart.resize(1400, 500)
        chart.set_option({
            "xAxis": {"type": "value"},
            "yAxis": {"type": "value"},
            "series": [{"type": "line", "name": "固定负载", "data": values}],
        })
        chart.anim.stop()
        chart.anim.set_progress(1.0)
        chart.show()
        app.processEvents()
        times, geometry = measure(chart)
        result = chart._perf_snapshot()
        result.update({
            "count": count,
            "sha256": hashlib.sha256(values.tobytes()).hexdigest(),
            "frame_ms": times,
            "geometry": geometry,
        })
        output["cases"].append(result)
        print(f"{count} 点：{times} ms；geometry={geometry}", flush=True)
        chart.close()
    chart = ChartWidget()
    chart.set_option({
        "xAxis": {"type": "category", "data": []},
        "yAxis": {"type": "value"},
        "series": [{"type": "line", "name": "信号", "data": []}],
    })
    session = chart.stream(series="信号", auto_scale=True)
    session._timer.stop()
    values = make_values(20_000)
    for _ in range(10):
        session._apply(values)
    session.close()
    result = chart._perf_snapshot()
    result["stream_submissions"] = 10
    output["stream"] = result
    print("流式指标：", json.dumps(result, ensure_ascii=False), flush=True)
    chart.close()
    app.quit()
    directory = ROOT / "tests" / "shots" / "perf"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "widget-baseline.json"
    path.write_text(json.dumps(output, ensure_ascii=False, indent=2),
                    encoding="utf-8")
    print(f"基线已保存：{path}")


if __name__ == "__main__":
    main()
