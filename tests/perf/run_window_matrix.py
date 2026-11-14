# -*- coding: utf-8 -*-
"""A–H 真实窗口、系统手势、交换帧与音频隔离测量。"""

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests" / "perf"))

from run_realtime import build_complex_window, frame_metrics, process_sample
from PySide6.QtCore import Qt

SEED = 20261114


class AudioProbe:
    def __init__(self, enabled):
        self.enabled = enabled
        self.events = []
        self.available = False
        self._last_state = None
        self._phase = 0
        self._sink = None
        self._device = None
        self._timer = None
        if not enabled:
            return
        import numpy as np
        from PySide6.QtCore import QTimer
        from PySide6.QtMultimedia import QAudio, QAudioFormat, QAudioSink, QMediaDevices

        if QMediaDevices.defaultAudioOutput().isNull():
            self.events.append({"event": "no_output_device"})
            return
        fmt = QAudioFormat()
        fmt.setSampleRate(48000)
        fmt.setChannelCount(2)
        fmt.setSampleFormat(QAudioFormat.Int16)
        self._sink = QAudioSink(fmt)
        self._device = self._sink.start()
        if self._device is None:
            self.events.append({"event": "start_failed"})
            return
        self.available = True
        self._numpy = np
        self._audio_enum = QAudio
        self._timer = QTimer(self._sink)
        self._timer.setInterval(50)
        self._timer.timeout.connect(self._write)
        self._timer.start()

    def _write(self):
        rate = 48000
        count = 2400
        t = (self._numpy.arange(count) + self._phase) / rate
        self._phase += count
        pcm = (self._numpy.sin(2 * self._numpy.pi * 440 * t) * 0.03 * 32767)
        pcm = self._numpy.repeat(pcm.astype(self._numpy.int16), 2)
        self._device.write(pcm.tobytes())
        state = self._sink.state()
        error = self._sink.error()
        if state != self._last_state:
            self.events.append({"event": "state", "state": str(state),
                                "error": str(error), "time": time.perf_counter()})
            self._last_state = state

    def stop(self):
        if self._timer is not None:
            self._timer.stop()
        if self._sink is not None:
            self._sink.stop()


def case_host(case, source):
    from demo.window_host import WindowHost

    host = WindowHost()
    host.resize(1280, 800)
    host.move(100, 60)
    charts = []
    series_data = []
    blueprint = None
    chat = None
    if case in ("complex", "opaque", "native"):
        complex_window, charts, series_data, blueprint, chat, _slider, _progress = build_complex_window()
        old = host.takeCentralWidget()
        old.deleteLater()
        host.setCentralWidget(complex_window.takeCentralWidget())
    elif case == "blank":
        from PySide6.QtWidgets import QFrame
        host.setCentralWidget(QFrame())
    elif case == "form":
        from PySide6.QtWidgets import QFrame, QGridLayout, QLabel, QLineEdit, QPushButton
        content = QFrame()
        grid = QGridLayout(content)
        for index in range(36):
            row, column = divmod(index, 6)
            grid.addWidget(QLabel(f"字段 {index + 1}"), row, column * 2)
            if index % 2:
                grid.addWidget(QLineEdit(f"内容 {index + 1}"), row, column * 2 + 1)
            else:
                grid.addWidget(QPushButton(f"操作 {index + 1}"), row, column * 2 + 1)
        host.setCentralWidget(content)
    elif case == "chart":
        import numpy as np
        from InstructionX_UIKit.charts import ChartWidget
        values = np.sin(np.arange(10000) * 0.01)
        chart = ChartWidget()
        chart.set_option({
            "animation": False,
            "xAxis": {"type": "value"}, "yAxis": {"type": "value"},
            "series": [{"type": "line", "data": values, "showSymbol": False}],
        })
        chart.anim.stop()
        chart.anim.set_progress(1.0)
        charts = [chart]
        series_data = [[values]]
        host.setCentralWidget(chart)
    elif case == "blueprint":
        _window, charts, series_data, blueprint, chat, _slider, _progress = build_complex_window()
        host.setCentralWidget(blueprint)
        charts = []
        series_data = []
        chat = None
    elif case == "mermaid":
        from InstructionX_UIKit.components import MarkdownView
        view = MarkdownView(
            "# Mermaid 隔离\n\n```mermaid\nflowchart LR\nA[输入] --> B[处理] --> C[输出]\n```")
        host.setCentralWidget(view)
    if case == "opaque":
        host.setAttribute(Qt.WA_TranslucentBackground, False)
        host.setAttribute(Qt.WA_NoSystemBackground, False)
        host.setAutoFillBackground(True)
        for widget in host.findChildren(type(host)):
            widget.setGraphicsEffect(None)
    elif case == "native":
        host.setWindowFlags(host.windowFlags() & ~Qt.FramelessWindowHint)
        host.setAttribute(Qt.WA_TranslucentBackground, False)
        host.setAttribute(Qt.WA_NoSystemBackground, False)
        host.setAutoFillBackground(True)
    return host, charts, series_data, blueprint, chat


def measure_case(app, case, phase_seconds, source, output, audio):
    import numpy as np
    from PySide6.QtCore import QTimer
    from native_screen import grab_native_window

    host, charts, series_data, blueprint, chat = case_host(case, source)
    host.setWindowFlag(Qt.WindowStaysOnTopHint, True)
    host.show()
    host.raise_()
    host.activateWindow()
    deadline = time.monotonic() + 1.0
    while time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.004)
    viewports = {}
    for index, chart in enumerate(charts):
        viewports[f"chart_{index}"] = chart._viewport
    if blueprint is not None:
        viewports["blueprint"] = blueprint._viewport
    state = {"frames": {name: [] for name in viewports}, "tasks": [],
             "resources": [], "tick": 0, "recording": False}
    for name, viewport in viewports.items():
        if hasattr(viewport, "frameSwapped"):
            viewport.frameSwapped.connect(
                lambda name=name: state["frames"][name].append(time.perf_counter())
                if state["recording"] else None)
        if hasattr(viewport, "_sync_now"):
            original = viewport._sync_now

            def measured(original=original, name=name):
                started = time.perf_counter()
                try:
                    original()
                finally:
                    state["tasks"].append((name, started, time.perf_counter() - started))
            viewport._sync_now = measured
        elif hasattr(viewport, "paintEvent"):
            original = viewport.paintEvent

            def measured(original=original, name=name):
                started = time.perf_counter()
                try:
                    original()
                finally:
                    state["tasks"].append((name, started, time.perf_counter() - started))
            viewport.paintEvent = measured

    def update():
        started = time.perf_counter()
        try:
            tick = state["tick"]
            for chart_index, chart in enumerate(charts):
                for series_index, values in enumerate(series_data[chart_index]):
                    chart.set_stream_data(np.roll(values, tick + series_index),
                                          series=series_index)
            if chat is not None:
                if tick % 240 == 239:
                    chat.finish_message(0)
                elif tick % 240 == 0:
                    chat.update_message(0, "隔离负载")
                else:
                    chat.append_to_message(0, f" 第 {tick} 个 **分片**")
            state["tick"] += 1
        finally:
            state["tasks"].append(("load", started, time.perf_counter() - started))

    timer = QTimer(host)
    timer.setInterval(16)
    timer.timeout.connect(update)
    timer.start()
    resource_timer = QTimer(host)
    resource_timer.setInterval(250)
    resource_timer.timeout.connect(
        lambda: state["resources"].append(process_sample()) if state["recording"] else None)
    resource_timer.start()
    results = []
    for phase in ("static", "move", "resize", "recover"):
        state["recording"] = True
        state["frames"] = {name: [] for name in viewports}
        state["tasks"] = []
        state["resources"] = []
        geometry_before = host.geometry()
        started = time.monotonic()
        origin = host.geometry()
        while time.monotonic() - started < phase_seconds:
            elapsed = time.monotonic() - started
            if phase == "move":
                host.move(origin.x() + round(80 * np.sin(elapsed * 2.0)),
                          origin.y() + round(30 * np.sin(elapsed * 2.4)))
            elif phase == "resize":
                host.resize(origin.width() + round(100 * np.sin(elapsed * 2.0)),
                            origin.height() + round(70 * np.sin(elapsed * 2.4)))
            app.processEvents()
            time.sleep(0.004)
        state["recording"] = False
        metrics = [frame_metrics(name, state["frames"][name]) for name in viewports]
        geometry_after = host.geometry()
        phase_result = {
            "phase": phase,
            "seconds": phase_seconds,
            "metrics": metrics,
            "long_tasks_ms": [task[2] * 1000 for task in state["tasks"] if task[2] >= 0.1],
            "geometry_before": list(geometry_before.getRect()),
            "geometry_after": list(geometry_after.getRect()),
            "input_mode": "programmatic_geometry",
            "native_mouse_verified": False,
            "resources": state["resources"],
        }
        if phase == "move":
            phase_result["interaction_ok"] = geometry_after != origin
        elif phase == "resize":
            phase_result["interaction_ok"] = geometry_after.size() != origin.size()
        else:
            phase_result["interaction_ok"] = True
        phase_result.update({
            "rhi_apis": {name: viewport.rhi_api()
                         for name, viewport in viewports.items()
                         if hasattr(viewport, "rhi_api")},
            "viewport_types": {name: type(viewport).__name__
                               for name, viewport in viewports.items()},
            "render_loop": os.environ.get("QSG_RENDER_LOOP"),
            "measurement": "QQuickView.frameSwapped；不是 PresentMon",
            "performance_gate_pass": bool(metrics) and all(
                metric.get("pass", False) for metric in metrics)
                and not phase_result["long_tasks_ms"],
        })
        phase_result["qt_active"] = host.isActiveWindow()
        phase_result["capture_policy"] = "置顶测试宿主 + Win32 实际客户区"
        image = grab_native_window(host.windowHandle())
        image.save(str(output / f"{case}_{phase}.png"))
        results.append(phase_result)
    timer.stop()
    resource_timer.stop()
    host.close()
    host.deleteLater()
    app.processEvents()
    return results


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase-seconds", type=float, default=10)
    parser.add_argument("--cases", nargs="*",
                        default=["blank", "form", "chart", "blueprint", "mermaid",
                                 "complex", "opaque", "native"])
    parser.add_argument("--audio", action="store_true")
    parser.add_argument("--label", default="candidate")
    parser.add_argument("--tag", default="matrix")
    args = parser.parse_args()
    source = ROOT
    sys.path.insert(0, str(source))
    os.environ.pop("QT_QPA_PLATFORM", None)
    os.environ.pop("UIKIT_CHART_BACKEND", None)
    os.environ.pop("QSG_RHI_BACKEND", None)
    os.environ.pop("QT_QUICK_BACKEND", None)
    from PySide6.QtWidgets import QApplication
    from InstructionX_UIKit.theme import ThemeManager

    app = QApplication.instance() or QApplication(sys.argv)
    ThemeManager.instance().apply(app)
    source_sha = subprocess.check_output(
        ["git", "rev-parse", "uniform_style"], text=True, cwd=ROOT).strip()
    source_dirty = subprocess.run(
        ["git", "diff", "--quiet", source_sha, "--", "InstructionX_UIKit", "demo"],
        cwd=ROOT).returncode != 0
    destination = ROOT / "temp" / "performance" / source_sha / "window-matrix" / args.tag
    destination.mkdir(parents=True, exist_ok=True)
    audio = AudioProbe(args.audio)
    report = {"source_sha": source_sha, "source_root": str(source),
              "source_dirty": source_dirty,
              "label": args.label, "seed": SEED,
              "phase_seconds": args.phase_seconds,
              "audio_enabled": args.audio,
              "audio_available": audio.available,
              "global_graphics_api_forced": False,
              "native_mouse_verified": False,
              "cases": {}}
    try:
        for case in args.cases:
            print(f"开始 {case}", flush=True)
            report["cases"][case] = measure_case(
                app, case, args.phase_seconds, source, destination, audio)
            (destination / "report.json").write_text(
                json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    finally:
        audio.stop()
        report["audio_events"] = audio.events
        (destination / "report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        from InstructionX_UIKit.mermaid import MermaidRenderHub
        hub = MermaidRenderHub.instance()
        hub.shutdown()
        if getattr(hub, "_page", None) is not None:
            hub._page.deleteLater()
            hub._page = None
        app.processEvents()
    print(json.dumps({"output": str(destination),
                      "audio_available": audio.available,
                      "audio_events": audio.events}, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
