# -*- coding: utf-8 -*-
"""真实窗口原 gpuDirect 选项的 RHI 兼容、像素与资源验证；不作为 FPS 证据。"""

import argparse
import json
import os
import platform
import subprocess
import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")
os.environ.pop("QSG_RHI_BACKEND", None)
os.environ.pop("QT_QUICK_BACKEND", None)

import numpy as np
from PySide6.QtGui import QImage, QPainter
from PySide6.QtQuick import QSGRendererInterface
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from InstructionX_UIKit.charts import ChartWidget
from InstructionX_UIKit.charts.viewport import _RasterViewport
from InstructionX_UIKit.theme import ThemeManager

SEED = 20261114


def reference(chart, image_format=QImage.Format_RGBA8888):
    dpr = chart.devicePixelRatioF()
    image = QImage(round(chart.width() * dpr), round(chart.height() * dpr), image_format)
    image.setDevicePixelRatio(dpr)
    image.fill(0)
    painter = QPainter(image)
    try:
        chart._paint_contents(painter)
    finally:
        painter.end()
    return image


def pixel_geometry(chart, image, rgb=None):
    image = image.convertToFormat(QImage.Format_RGBA8888)
    width, height = image.width(), image.height()
    pixels = np.frombuffer(image.constBits(), dtype=np.uint8).reshape(height, width, 4)
    color = chart.series_renderers[0].color()
    target = np.array(rgb if rgb is not None else (color.red(), color.green(), color.blue()))
    mask = np.all(np.abs(pixels[:, :, :3].astype(np.int16) - target) <= 4, axis=2)
    plot = chart.primary_coord().plot
    dpr = image.devicePixelRatio()
    left = max(0, int(plot.left() * dpr))
    top = max(0, int(plot.top() * dpr))
    right = min(width, int(plot.right() * dpr) + 1)
    bottom = min(height, int(plot.bottom() * dpr) + 1)
    mask[:top] = False
    mask[bottom:] = False
    mask[:, :left] = False
    mask[:, right:] = False
    ys, xs = np.where(mask)
    return {
        "count": int(len(xs)),
        "x_span": int(xs.max() - xs.min()) if len(xs) else 0,
        "y_span": int(ys.max() - ys.min()) if len(ys) else 0,
        "minimum_x_span": plot.width() * dpr * 0.7,
        "minimum_y_span": plot.height() * dpr * 0.5,
        "physical": [width, height],
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--raster", action="store_true", help="离屏软件参考，不是真实 RHI 验收")
    args = parser.parse_args()
    if args.raster:
        os.environ["QT_QPA_PLATFORM"] = "offscreen"
        os.environ["UIKIT_CHART_BACKEND"] = "raster"
    else:
        os.environ.pop("QT_QPA_PLATFORM", None)
    app = QApplication.instance() or QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    ThemeManager.instance().apply(app)
    rng = np.random.default_rng(SEED)
    values = np.sin(np.arange(50_000, dtype=np.float64) * 0.001)
    values += rng.normal(0, 0.01, len(values))
    chart = ChartWidget()
    chart.resize(800, 500)
    chart.move(100, 80)
    chart.set_option({
        "animation": False,
        "xAxis": {"type": "value"},
        "yAxis": {"type": "value"},
        "series": [{"type": "line", "name": "RHI 兼容验证", "data": values,
                    "gpuDirect": True, "gpuVersion": 7, "showSymbol": False}],
    })
    chart.anim.stop()
    chart.anim.set_progress(1.0)
    chart.show()
    QTest.qWait(600)
    viewport = chart._viewport
    renderer = chart.series_renderers[0]
    source_sha = subprocess.check_output(
        ["git", "rev-parse", "uniform_style"], text=True, cwd=ROOT).strip()
    output = ROOT / "tests" / "shots" / "gpu_direct"
    output.mkdir(parents=True, exist_ok=True)
    report = {
        "source_sha": source_sha,
        "note": "RHI 兼容与像素验证，不是实际呈现 FPS",
        "platform": app.platformName(),
        "screen": chart.screen().name(),
        "dpr": viewport.devicePixelRatioF(),
        "refresh_rate": chart.screen().refreshRate(),
        "viewport": type(viewport).__name__,
        "native_mouse_verified": False,
        "failures": [],
    }

    def check(condition, message, details=None):
        if condition:
            print(f"  [通过] {message}", flush=True)
        else:
            report["failures"].append({"check": message, "details": details})
            print(f"  [失败] {message}: {details}", flush=True)

    def compare(name):
        actual = viewport.grab().toImage().convertToFormat(QImage.Format_RGBA8888)
        image_format = (QImage.Format_ARGB32_Premultiplied if args.raster
                        else QImage.Format_RGBA8888)
        expected = reference(chart, image_format).convertToFormat(QImage.Format_RGBA8888)
        actual.save(str(output / f"{name}_actual.png"))
        expected.save(str(output / f"{name}_expected.png"))
        details = {"actual_dpr": actual.devicePixelRatio(),
                   "expected_dpr": expected.devicePixelRatio(),
                   "actual_size": [actual.width(), actual.height()],
                   "expected_size": [expected.width(), expected.height()]}
        same = actual.size() == expected.size()
        if same:
            aa = np.frombuffer(actual.constBits(), dtype=np.uint8).reshape(
                actual.height(), actual.width(), 4)
            bb = np.frombuffer(expected.constBits(), dtype=np.uint8).reshape(
                expected.height(), expected.width(), 4)
            delta = aa.astype(np.int16) - bb.astype(np.int16)
            changed = np.any(delta, axis=2)
            same = not changed.any()
            details.update(changed=int(changed.sum()), max_delta=int(np.abs(delta).max()))
        report.setdefault("pixel_comparisons", {})[name] = details
        check(same, f"{name} 最终图像零像素差异", details)

    try:
        if args.raster:
            check(isinstance(viewport, _RasterViewport), "明确使用离屏软件参考")
        else:
            check(type(viewport).__name__ == "_RhiViewport", "默认使用 RHI 原生视口")
            api = viewport._view.graphicsApi()
            report["rhi_api"] = getattr(api, "name", str(api))
            report["rhi_backend"] = getattr(viewport._view.rhi().backend(), "name",
                                           str(viewport._view.rhi().backend()))
            report["exposed"] = viewport._view.isExposed()
            check(report["exposed"], "原生视口已真实暴露")
            if platform.system() == "Windows":
                check(api == QSGRendererInterface.GraphicsApi.Direct3D11,
                      "Windows 自动选择 Direct3D 11", report["rhi_api"])
        check(renderer.gpu_direct and renderer._gpu_direct, "原 gpuDirect 选项保持兼容")
        check(chart.option()["series"][0]["gpuVersion"] == 7, "显式 gpuVersion 保持原值")
        check(not chart.gpu_claims(renderer), "不再虚构旧 GL 管线认领")
        compare("rhi_initial")
        initial = viewport.grab().toImage()
        report["geometry"] = pixel_geometry(chart, initial)
        geometry = report["geometry"]
        check(geometry["count"] > 100, "绘图区有真实系列像素", geometry)
        check(geometry["x_span"] >= geometry["minimum_x_span"],
              "曲线横坐标覆盖主要绘图区", geometry)
        check(geometry["y_span"] >= geometry["minimum_y_span"],
              "曲线纵坐标覆盖主要绘图区", geometry)
        series_key = chart._series_key
        chart.update()
        QTest.qWait(100)
        check(chart._series_key == series_key, "数据不变复用系列光栅缓存")
        check(chart.static_layer_valid(), "固定轴保留静态层缓存")

        chart.update_option({"series": [{
            "type": "line", "name": "RHI 兼容验证", "data": values,
            "gpuDirect": True, "gpuVersion": 8, "showSymbol": False,
            "lineStyle": {"width": 6, "color": "#C08A3E"},
        }]})
        chart.anim.stop()
        chart.anim.set_progress(1.0)
        QTest.qWait(150)
        renderer = chart.series_renderers[0]
        check(renderer.opt["lineStyle"]["width"] == 6, "线宽完整保留")
        styled = pixel_geometry(chart, viewport.grab().toImage(), (192, 138, 62))
        check(styled["count"] > 100, "线色在最终 RHI 像素中完整保留", styled)
        compare("rhi_style")
        for index in range(12):
            chart.update_option({"series": [{
                "type": "line", "name": "RHI 兼容验证", "data": values + index,
                "gpuDirect": True, "gpuVersion": 9 + index, "showSymbol": False,
            }]})
            chart.anim.stop()
            chart.anim.set_progress(1.0)
            QTest.qWait(25)
        check(chart.series_renderers[0].gpu_direct, "反复重建不丢失 gpuDirect")
        compare("rhi_rebuilt")
        if not args.raster:
            check(len(viewport._scene._frames) <= 3, "Scene Graph 帧引用固定有界")
        chart.close()
        QTest.qWait(50)
        if not args.raster:
            check(not viewport._sync_timer.isActive(), "关闭后停止同步定时器")
            check(viewport._scene._snapshot is None, "关闭后释放当前快照")
        report["pass"] = not report["failures"]
    except Exception as exc:
        report["pass"] = False
        report["exception"] = repr(exc)
        traceback.print_exc()
    finally:
        chart.deleteLater()
        app.processEvents()
        destination = ROOT / "temp" / "performance" / source_sha
        destination.mkdir(parents=True, exist_ok=True)
        path = destination / ("raster-geometry.json" if args.raster else "rhi-direct.json")
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"原始报告：{path}", flush=True)
    return 0 if report.get("pass") else 1


if __name__ == "__main__":
    raise SystemExit(main())
