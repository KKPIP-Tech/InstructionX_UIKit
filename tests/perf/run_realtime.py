# -*- coding: utf-8 -*-
"""真实 4K 复杂场景 frameSwapped 性能验收，不使用离屏耗时冒充 FPS。"""

import argparse
import csv
import hashlib
import json
import os
import platform
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SEED = 20261114


def build_complex_window():
    import numpy as np
    from PySide6.QtCore import QPointF, Qt
    from PySide6.QtWidgets import (
        QCheckBox, QFrame, QGridLayout, QHBoxLayout, QLabel, QMainWindow,
        QProgressBar, QSlider, QVBoxLayout, QWidget,
    )
    from InstructionX_UIKit.blueprint import BlueprintCanvas, BlueprintGraph, BlueprintNode
    from InstructionX_UIKit.charts import ChartWidget
    from InstructionX_UIKit.layouts import ChatConversation

    rng = np.random.default_rng(SEED)
    window = QMainWindow()
    central = QWidget(window)
    window.setCentralWidget(central)
    grid = QGridLayout(central)
    grid.setContentsMargins(8, 8, 8, 8)
    grid.setSpacing(8)
    charts = []
    series_data = []
    for chart_index in range(2):
        chart = ChartWidget()
        data = []
        options = []
        for series_index in range(4):
            x = np.arange(20000, dtype=np.float64)
            values = (np.sin(x / (700 + series_index * 130) + chart_index)
                      + 0.25 * np.cos(x / 190 + series_index)
                      + rng.normal(0, 0.015, len(x)))
            data.append(values)
            options.append({
                "type": "line", "name": f"图 {chart_index + 1}/系列 {series_index + 1}",
                "data": values, "showSymbol": False,
            })
        chart.set_option({
            "animation": False,
            "xAxis": {"type": "value"},
            "yAxis": {"type": "value", "min": -2, "max": 2},
            "series": options,
        })
        chart.anim.stop()
        chart.anim.set_progress(1.0)
        charts.append(chart)
        series_data.append(data)
        grid.addWidget(chart, 0, chart_index)

    graph = BlueprintGraph()
    nodes = []
    for index in range(12):
        node = BlueprintNode("perf", f"节点 {index + 1}")
        node.pos = QPointF((index % 4) * 220, (index // 4) * 170)
        if index:
            node.add_input("in")
        if index < 11:
            node.add_output("out")
        graph.add_node(node)
        nodes.append(node)
        if index:
            graph.add_edge(nodes[index - 1].id, "out", node.id, "in")
    blueprint = BlueprintCanvas(graph)
    blueprint._execution.set_path([node.id for node in nodes])
    grid.addWidget(blueprint, 1, 0)

    right = QFrame()
    right_layout = QVBoxLayout(right)
    controls = QHBoxLayout()
    slider = QSlider(Qt.Horizontal)
    slider.setRange(0, 100)
    progress = QProgressBar()
    progress.setRange(0, 100)
    check = QCheckBox("保持实时负载")
    check.setChecked(True)
    controls.addWidget(QLabel("普通控件"))
    controls.addWidget(slider, 1)
    controls.addWidget(progress, 1)
    controls.addWidget(check)
    right_layout.addLayout(controls)
    chat = ChatConversation(show_input=False)
    chat.add_message("assistant", "固定种子的实时 Markdown 负载")
    right_layout.addWidget(chat, 1)
    grid.addWidget(right, 1, 1)
    grid.setRowStretch(0, 3)
    grid.setRowStretch(1, 2)
    grid.setColumnStretch(0, 1)
    grid.setColumnStretch(1, 1)
    return window, charts, series_data, blueprint, chat, slider, progress


def process_sample():
    import ctypes
    from ctypes import wintypes

    class MemoryCounters(ctypes.Structure):
        _fields_ = [
            ("cb", wintypes.DWORD),
            ("PageFaultCount", wintypes.DWORD),
            ("PeakWorkingSetSize", ctypes.c_size_t),
            ("WorkingSetSize", ctypes.c_size_t),
            ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
            ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
            ("PagefileUsage", ctypes.c_size_t),
            ("PeakPagefileUsage", ctypes.c_size_t),
            ("PrivateUsage", ctypes.c_size_t),
        ]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    psapi = ctypes.WinDLL("psapi", use_last_error=True)
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32.GetCurrentProcess.restype = wintypes.HANDLE
    kernel32.GetProcessTimes.restype = wintypes.BOOL
    kernel32.GetProcessTimes.argtypes = [wintypes.HANDLE] + [
        ctypes.POINTER(wintypes.FILETIME)] * 4
    kernel32.GetProcessHandleCount.restype = wintypes.BOOL
    kernel32.GetProcessHandleCount.argtypes = [
        wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    psapi.GetProcessMemoryInfo.restype = wintypes.BOOL
    psapi.GetProcessMemoryInfo.argtypes = [
        wintypes.HANDLE, ctypes.POINTER(MemoryCounters), wintypes.DWORD]
    user32.GetGuiResources.restype = wintypes.DWORD
    user32.GetGuiResources.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    process = kernel32.GetCurrentProcess()
    counters = MemoryCounters()
    counters.cb = ctypes.sizeof(counters)
    if not psapi.GetProcessMemoryInfo(process, ctypes.byref(counters), counters.cb):
        raise ctypes.WinError(ctypes.get_last_error())
    creation = wintypes.FILETIME()
    exit_time = wintypes.FILETIME()
    kernel = wintypes.FILETIME()
    user = wintypes.FILETIME()
    if not kernel32.GetProcessTimes(process, ctypes.byref(creation), ctypes.byref(exit_time),
                                    ctypes.byref(kernel), ctypes.byref(user)):
        raise ctypes.WinError(ctypes.get_last_error())
    handles = wintypes.DWORD()
    if not kernel32.GetProcessHandleCount(process, ctypes.byref(handles)):
        raise ctypes.WinError(ctypes.get_last_error())
    return {
        "time": time.perf_counter(),
        "working_set": counters.WorkingSetSize,
        "private_bytes": counters.PrivateUsage,
        "handles": handles.value,
        "gdi_objects": user32.GetGuiResources(process, 0),
        "user_objects": user32.GetGuiResources(process, 1),
        "cpu_seconds": ((kernel.dwLowDateTime | kernel.dwHighDateTime << 32)
                        + (user.dwLowDateTime | user.dwHighDateTime << 32)) / 10_000_000,
    }


def frame_metrics(name, frames):
    import numpy as np
    if len(frames) < 2:
        return {"viewport": name, "frames": len(frames), "pass": False}
    intervals = np.diff(frames) * 1000
    elapsed = frames[-1] - frames[0]
    average_fps = (len(frames) - 1) / elapsed if elapsed > 0 else 0
    p95 = float(np.percentile(intervals, 95))
    p99 = float(np.percentile(intervals, 99))
    return {
        "viewport": name,
        "frames": len(frames),
        "seconds": elapsed,
        "average_fps": average_fps,
        "p50_ms": float(np.percentile(intervals, 50)),
        "p95_ms": p95,
        "p99_ms": p99,
        "max_ms": float(intervals.max()),
        "over_16_67_ms": int((intervals > 16.67).sum()),
        "over_33_33_ms": int((intervals > 33.33).sum()),
        "pass": bool(elapsed > 0 and average_fps >= 60
                     and p95 <= 16.67 and p99 <= 33.33),
    }


def timing_summary(samples):
    import numpy as np
    values = list(samples)
    if not values:
        return {}
    return {"count": len(values), "mean_ms": float(np.mean(values)),
            "p95_ms": float(np.percentile(values, 95)), "max_ms": float(max(values))}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--seconds", type=float, default=60)
    parser.add_argument("--rounds", type=int, default=5)
    parser.add_argument("--warmup", type=float, default=5)
    parser.add_argument("--label", default="candidate")
    parser.add_argument("--tag", default="formal")
    parser.add_argument("--only", choices=["complex", "charts", "single-chart", "blueprint", "chat", "no-chat"],
                        default="complex")
    parser.add_argument("--enforce", action="store_true")
    parser.add_argument("--backend", choices=["legacy", "rhi", "raster", "canvas"],
                        default="rhi")
    parser.add_argument("--source-root", type=Path)
    parser.add_argument("--source-sha")
    parser.add_argument("--logical-width", type=int, default=2560)
    parser.add_argument("--logical-height", type=int, default=1440)
    parser.add_argument("--windowed", action="store_true")
    args = parser.parse_args()
    if args.seconds <= 0 or args.rounds < 1 or args.warmup < 0:
        parser.error("seconds/rounds/warmup 参数无效")
    if args.logical_width <= 0 or args.logical_height <= 0:
        parser.error("logical-width/logical-height 参数无效")
    if args.source_root is not None and not args.source_sha:
        parser.error("显式 source-root 时必须同时提供 source-sha")
    os.environ.pop("UIKIT_PERF_GPU_DIRECT", None)
    if args.backend == "legacy":
        os.environ.pop("UIKIT_CHART_BACKEND", None)
        os.environ.pop("UIKIT_BLUEPRINT_BACKEND", None)
        os.environ["UIKIT_CHART_GL"] = "auto"
        os.environ["UIKIT_BLUEPRINT_GL"] = "auto"
    else:
        os.environ["UIKIT_CHART_BACKEND"] = args.backend
        os.environ["UIKIT_BLUEPRINT_BACKEND"] = args.backend
        os.environ.pop("UIKIT_CHART_GL", None)
        os.environ.pop("UIKIT_BLUEPRINT_GL", None)
    source = args.source_root.resolve() if args.source_root is not None else ROOT
    if not (source / "InstructionX_UIKit").is_dir():
        parser.error(f"source-root 不含 InstructionX_UIKit: {source}")
    sys.path.insert(0, str(source))
    os.environ.pop("QT_QPA_PLATFORM", None)

    import numpy as np
    import PySide6
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication
    from InstructionX_UIKit import __version__
    from InstructionX_UIKit.theme import ThemeManager

    app = QApplication(sys.argv)
    ThemeManager.instance().apply(app)
    window, charts, series_data, blueprint, chat, slider, progress = build_complex_window()
    if args.only not in ("complex", "charts", "single-chart", "no-chat"):
        for chart in charts:
            chart.hide()
    if args.only == "single-chart":
        charts[1].hide()
    if args.only not in ("complex", "blueprint", "no-chat"):
        blueprint.hide()
    if args.only not in ("complex", "chat"):
        chat.parentWidget().hide()
    window.resize(args.logical_width, args.logical_height)
    window.move(0, 0)
    if args.windowed:
        window.show()
    else:
        window.showFullScreen()
    app.processEvents()
    from native_input import activate_window
    if not activate_window(window) or not window.windowHandle().isExposed():
        raise RuntimeError("真实性能窗口未取得前台或未暴露，不能开始测量")
    viewports = {}
    if args.only in ("complex", "charts", "single-chart", "no-chat"):
        viewports["chart_left"] = charts[0]._viewport
    if args.only in ("complex", "charts", "no-chat"):
        viewports["chart_right"] = charts[1]._viewport
    if args.only in ("complex", "blueprint", "no-chat"):
        viewports["blueprint"] = blueprint._viewport
    state = {
        "round": -1,
        "recording": False,
        "frames": {name: [] for name in viewports},
        "tasks": [],
        "resources": [],
        "tick": 0,
        "failures": [],
        "rounds": [],
    }
    if args.backend == "raster":
        state["failures"].append("raster 仅用于参考，不能用绘制事件冒充真实交换帧")
    for name, viewport in viewports.items():
        if hasattr(viewport, "frameSwapped"):
            viewport.frameSwapped.connect(
                lambda name=name: state["frames"][name].append(time.perf_counter())
                if state["recording"] else None)
        elif args.enforce:
            state["failures"].append(f"{name} 不支持 frameSwapped")
        if hasattr(viewport, "_sync_now"):
            original_sync = viewport._sync_now

            def measured_sync(original=original_sync, name=name):
                started = time.perf_counter()
                try:
                    original()
                finally:
                    state["tasks"].append((name, started, time.perf_counter() - started))

            viewport._sync_now = measured_sync
        elif args.backend != "legacy" and hasattr(viewport, "paintEvent"):
            original_paint = viewport.paintEvent

            def measured_paint(original=original_paint, name=name):
                started = time.perf_counter()
                try:
                    original()
                finally:
                    state["tasks"].append((name, started, time.perf_counter() - started))

            viewport.paintEvent = measured_paint

    state["persistent_failures"] = list(state["failures"])
    state["gc"] = []
    state["gc_started"] = None

    def gc_event(phase, info):
        if phase == "start":
            state["gc_started"] = time.perf_counter()
        elif phase == "stop" and state["gc_started"] is not None:
            state["gc"].append((state["gc_started"],
                                time.perf_counter() - state["gc_started"],
                                info.get("generation")))
            state["gc_started"] = None

    import gc
    gc.callbacks.append(gc_event)

    def sample_resource():
        if state["recording"]:
            try:
                state["resources"].append(process_sample())
            except Exception as exc:
                state["failures"].append(f"资源采样失败: {exc!r}")

    def apply_load():
        tick = state["tick"]
        shift = tick * 17
        if args.only in ("complex", "charts", "single-chart", "no-chat"):
            for chart_index, chart in enumerate(charts):
                if args.only == "single-chart" and chart_index:
                    continue
                for series_index, values in enumerate(series_data[chart_index]):
                    updated = np.roll(values, shift + series_index)
                    if not chart.set_stream_data(updated, series=series_index):
                        state["failures"].append("set_stream_data 返回 False")
        if args.only in ("complex", "chat"):
            chunk = f" 第 {tick} 个 **Markdown 分片**"
            if tick % 240 == 239:
                chat.finish_message(0)
            elif tick % 240 == 0:
                chat.update_message(0, "新一轮实时 Markdown 负载")
            else:
                chat.append_to_message(0, chunk)
        if args.only in ("complex", "chat") and tick % 4 == 0:
            value = tick % 101
            slider.setValue(value)
            progress.setValue(value)
        state["tick"] += 1

    def update_load():
        started = time.perf_counter()
        try:
            apply_load()
        finally:
            state["tasks"].append(("load", started, time.perf_counter() - started))

    load_timer = QTimer(window)
    load_timer.setInterval(16)
    load_timer.timeout.connect(update_load)
    resource_timer = QTimer(window)
    resource_timer.setInterval(250)
    resource_timer.timeout.connect(sample_resource)
    load_timer.start()
    resource_timer.start()

    source_sha = args.source_sha or subprocess.check_output(
        ["git", "rev-parse", "HEAD"], text=True, cwd=source).strip()
    if args.source_root is not None:
        source_dirty = None
    else:
        source_dirty = subprocess.run(
            ["git", "diff", "--quiet", source_sha, "--", "InstructionX_UIKit", "demo"],
            cwd=ROOT).returncode != 0
    if source_dirty is True and args.enforce:
        failure = "工作区源码与声明 SHA 不一致"
        state["persistent_failures"].append(failure)
        state["failures"].append(failure)
    destination = ROOT / "temp" / "performance" / source_sha / "realtime" / args.tag
    destination.mkdir(parents=True, exist_ok=True)
    (destination / "script_snapshot.py").write_text(
        Path(__file__).read_text(encoding="utf-8"), encoding="utf-8")

    def finish_round():
        state["recording"] = False
        round_index = state["round"]
        metrics = [frame_metrics(name, state["frames"][name]) for name in viewports]
        long_tasks = [task for task in state["tasks"] if task[2] >= 0.1]
        dpr = window.devicePixelRatioF()
        physical = [window.width() * dpr, window.height() * dpr]
        expected = [args.logical_width * dpr, args.logical_height * dpr]
        physical_matches = all(abs(actual - target) <= 1.0
                               for actual, target in zip(physical, expected))
        for metric in metrics:
            metric["pass"] = (
                metric.get("average_fps", 0) >= 60
                and metric.get("p95_ms", float("inf")) <= 16.67
                and metric.get("p99_ms", float("inf")) <= 33.33)
        passed = (bool(metrics) and all(metric["pass"] for metric in metrics)
                  and not long_tasks and physical_matches
                  and not state["failures"])
        report = {
            "source_sha": source_sha,
            "source_dirty": source_dirty,
            "source_root": str(source),
            "package_version": __version__,
            "pyside6": PySide6.__version__,
            "python": sys.version,
            "os": platform.platform(),
            "seed": SEED,
            "label": args.label,
            "tag": args.tag,
            "only": args.only,
            "backend": args.backend,
            "render_loop": os.environ.get("QSG_RENDER_LOOP"),
            "rhi_apis": {name: viewport.rhi_api()
                         for name, viewport in viewports.items()
                         if hasattr(viewport, "rhi_api")},
            "round": round_index + 1,
            "requested_seconds": args.seconds,
            "screen": window.screen().name(),
            "refresh_rate": window.screen().refreshRate(),
            "logical_size": [window.width(), window.height()],
            "dpr": dpr,
            "physical_size": physical,
            "viewport_types": {name: type(viewport).__name__
                               for name, viewport in viewports.items()},
            "data_series": [len(values) for chart in series_data for values in chart],
            "data_sha256": [hashlib.sha256(values.tobytes()).hexdigest()
                            for chart in series_data for values in chart],
            "metrics": metrics,
            "paint_times_ms": {name: timing_summary(getattr(viewport, "paint_times", ()))
                               for name, viewport in viewports.items()},
            "sync_times_ms": {name: timing_summary(getattr(viewport, "sync_times", ()))
                              for name, viewport in viewports.items()},
            "long_tasks_ms": [task[2] * 1000 for task in long_tasks],
            "gc_times_ms": timing_summary([event[1] * 1000 for event in state["gc"]]),
            "failures": state["failures"],
            "pass": passed,
            "measurement": "局部 Scene Graph 帧完成信号 + UI 数据同步耗时；不是 PresentMon",
        }
        round_name = f"round_{round_index + 1:02d}"
        (destination / f"{round_name}.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        with (destination / f"{round_name}_frames.csv").open("w", newline="", encoding="utf-8") as stream:
            writer = csv.writer(stream)
            writer.writerow(["viewport", "frame", "timestamp", "interval_ms"])
            for name, frames in state["frames"].items():
                previous = None
                for index, timestamp in enumerate(frames):
                    writer.writerow([name, index, timestamp,
                                     "" if previous is None else (timestamp - previous) * 1000])
                    previous = timestamp
        with (destination / f"{round_name}_ui_tasks.csv").open("w", newline="", encoding="utf-8") as stream:
            writer = csv.writer(stream)
            writer.writerow(["source", "started", "duration_ms"])
            writer.writerows((source, started, duration * 1000)
                             for source, started, duration in state["tasks"])
        with (destination / f"{round_name}_gc.csv").open("w", newline="", encoding="utf-8") as stream:
            writer = csv.writer(stream)
            writer.writerow(["started", "duration_ms", "generation"])
            writer.writerows((started, duration * 1000, generation)
                             for started, duration, generation in state["gc"])
        with (destination / f"{round_name}_resources.csv").open("w", newline="", encoding="utf-8") as stream:
            fields = ["time", "working_set", "private_bytes", "handles",
                      "gdi_objects", "user_objects", "cpu_seconds"]
            writer = csv.DictWriter(stream, fieldnames=fields)
            writer.writeheader()
            writer.writerows(state["resources"])
        state["rounds"].append(report)
        print(json.dumps({"round": round_index + 1, "pass": passed,
                          "metrics": metrics,
                          "long_tasks_ms": report["long_tasks_ms"],
                          "failures": state["failures"]}, ensure_ascii=False), flush=True)
        if round_index + 1 < args.rounds:
            state["round"] += 1
            state["frames"] = {name: [] for name in viewports}
            state["tasks"] = []
            state["resources"] = []
            state["gc"] = []
            state["failures"] = list(state["persistent_failures"])
            state["recording"] = True
            QTimer.singleShot(int(args.seconds * 1000), finish_round)
        else:
            load_timer.stop()
            resource_timer.stop()
            summary = {"source_sha": source_sha, "rounds": state["rounds"],
                       "all_pass": all(item["pass"] for item in state["rounds"])}
            (destination / "summary.json").write_text(
                json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
            window.close()
            app.exit(0 if summary["all_pass"] or not args.enforce else 2)

    def start_round():
        state["round"] = 0
        state["tasks"] = []
        state["gc"] = []
        state["gc_started"] = None
        state["recording"] = True
        sample_resource()
        QTimer.singleShot(int(args.seconds * 1000), finish_round)

    QTimer.singleShot(int(args.warmup * 1000), start_round)
    print(json.dumps({"source": str(source), "source_sha": source_sha,
                      "screen": window.screen().name(),
                      "refresh": window.screen().refreshRate(),
                      "logical": [window.width(), window.height()],
                      "dpr": window.devicePixelRatioF(),
                      "rounds": args.rounds, "seconds": args.seconds,
                      "output": str(destination)}, ensure_ascii=False), flush=True)
    gc.callbacks.remove(gc_event)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
