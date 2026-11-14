# -*- coding: utf-8 -*-
"""真实窗口 gpuDirect 几何、上传、绘制与资源验证（不作为 FPS 证据）。"""

import argparse
import json
import os
import subprocess
import sys
import traceback
from pathlib import Path

os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import numpy as np
from PySide6.QtGui import QImage
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from InstructionX_UIKit.charts import ChartWidget
from InstructionX_UIKit.charts.viewport import _GLViewport, _RasterViewport, gl_available
from InstructionX_UIKit.theme import ThemeManager

SEED = 20261114
_FAILURES = []


def check(condition, message, details=None):
    if condition:
        print(f"  [通过] {message}", flush=True)
    else:
        _FAILURES.append(message)
        print(f"  [失败] {message}: {details}", flush=True)


def pump(milliseconds):
    QTest.qWait(milliseconds)


def curve_geometry(chart, image):
    image = image.convertToFormat(QImage.Format_RGBA8888)
    width, height = image.width(), image.height()
    pixels = np.frombuffer(image.constBits(), dtype=np.uint8).reshape(
        height, width, 4)
    color = chart.series_renderers[0].color()
    target = np.array([color.red(), color.green(), color.blue()])
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
    if not len(xs):
        return {"count": 0, "physical": [width, height]}
    return {
        "count": int(len(xs)),
        "x_span": int(xs.max() - xs.min()),
        "y_span": int(ys.max() - ys.min()),
        "bbox": [int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())],
        "plot_physical": [left, top, right, bottom],
        "physical": [width, height],
    }


def option(values, **series):
    item = {"type": "line", "name": "GPU 验证", "data": values,
            "gpuDirect": True, "showSymbol": False}
    item.update(series)
    return {
        "animation": False,
        "xAxis": {"type": "value"},
        "yAxis": {"type": "value"},
        "series": [item],
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--raster", action="store_true")
    args = parser.parse_args()
    if args.raster:
        os.environ["UIKIT_CHART_GL"] = "off"
    app = QApplication(sys.argv)
    ThemeManager.instance().apply(app)
    output_dir = ROOT / "tests" / "shots" / "gpu_direct"
    output_dir.mkdir(parents=True, exist_ok=True)
    values = np.sin(np.arange(50_000, dtype=np.float64) * 0.001)
    chart = ChartWidget()
    chart.resize(800, 500)
    chart.move(100, 80)
    chart.set_option(option(values))
    chart.anim.stop()
    chart.anim.set_progress(1.0)
    chart.show()
    pump(400)
    viewport = chart._viewport
    renderer = chart.series_renderers[0]
    report = {
        "source_sha": subprocess.check_output(
            ["git", "rev-parse", "uniform_style"], text=True).strip(),
        "note": "真实窗口 GL 几何与状态，不是实际呈现 FPS",
        "platform": app.platformName(),
        "screen": chart.screen().name(),
        "dpr": viewport.devicePixelRatioF(),
        "refresh_rate": chart.screen().refreshRate(),
        "exposed": viewport.window().windowHandle().isExposed(),
        "backend": type(viewport).__name__,
        "gl_available": gl_available(),
        "viewport": type(viewport).__name__,
    }
    image = viewport.grab().toImage() if args.raster else viewport.grabFramebuffer()
    image.save(str(output_dir / ("raster.png" if args.raster else "gpu.png")))
    report["geometry"] = curve_geometry(chart, image)
    check(report["exposed"], "视口真实暴露且未被移出屏幕")
    check(report["geometry"]["count"] > 100, "绘图区有曲线像素", report["geometry"])
    check(report["geometry"].get("x_span", 0) > 500,
          "曲线横坐标覆盖主要绘图区", report["geometry"])
    check(report["geometry"].get("y_span", 0) > 180,
          "曲线纵坐标覆盖主要绘图区", report["geometry"])
    if args.raster:
        check(isinstance(viewport, _RasterViewport), "明确使用软件视口", report["backend"])
    else:
        check(isinstance(viewport, _GLViewport), "明确使用真实 GL 视口", report["backend"])
        pipeline = viewport._gpu_pipes.get(id(renderer))
        check(pipeline is not None, "实际创建逐系列 GL 管线")
        if pipeline is not None:
            report["vertex_count"] = pipeline.vertex_count
            report["upload_count"] = pipeline.upload_count
            report["uploaded_bytes"] = pipeline.uploaded_bytes
            check(pipeline.vertex_count == len(values), "VBO 顶点数等于原始数据点数",
                  pipeline.vertex_count)
            check(pipeline.upload_count >= 1, "确实发生 VBO 上传", pipeline.upload_count)
            check(pipeline.uploaded_bytes == len(values) * 2 * 4,
                  "上传字节数与 float32[n,2] 一致", pipeline.uploaded_bytes)
            draw_results = []
            draw_options = []
            claim_results = []
            original_draw = pipeline.draw

            def record_draw(*draw_args, **draw_kwargs):
                claim_results.append(chart.gpu_claims(renderer))
                result = original_draw(*draw_args, **draw_kwargs)
                draw_results.append(result)
                draw_options.append({**draw_kwargs, "color": draw_args[2]})
                return result

            pipeline.draw = record_draw
            chart.update()
            pump(100)
            check(draw_results and all(draw_results), "GPU draw 实际成功", draw_results)
            check(claim_results and all(claim_results),
                  "绘制期间由真实 GPU 直绘系列认领", claim_results)
            first_uploads = pipeline.upload_count
            chart.update()
            pump(80)
            check(pipeline.upload_count == first_uploads, "数据不变不重复上传",
                  pipeline.upload_count)
            chart.update_option({"series": [{
                "type": "line", "name": "GPU 验证", "data": values,
                "gpuDirect": True, "showSymbol": False,
                "lineStyle": {"width": 6, "color": "#C08A3E"},
            }]})
            chart.anim.stop()
            chart.anim.set_progress(1.0)
            pump(100)
            style_pipeline = viewport._gpu_pipes.get(id(chart.series_renderers[0]))
            original_style_draw = style_pipeline.draw

            def record_style_draw(*draw_args, **draw_kwargs):
                result = original_style_draw(*draw_args, **draw_kwargs)
                draw_results.append(result)
                draw_options.append({**draw_kwargs, "color": draw_args[2]})
                return result

            style_pipeline.draw = record_style_draw
            chart.update()
            pump(150)
            check(draw_options and draw_options[-1].get("width") == 6,
                  "lineStyle.width 传入 GL", draw_options[-1:] )
            expected_color = (192 / 255, 138 / 255, 62 / 255, 1.0)
            actual_color = draw_options[-1].get("color") if draw_options else None
            actual_rgba = ((actual_color.redF(), actual_color.greenF(),
                            actual_color.blueF(), actual_color.alphaF())
                           if hasattr(actual_color, "redF") else actual_color)
            check(actual_rgba is not None and np.allclose(actual_rgba, expected_color),
                  "lineStyle.color 传入 GL", actual_rgba)
            for index in range(12):
                chart.update_option({"series": [{
                    "type": "line", "name": "GPU 验证", "data": values + index,
                    "gpuDirect": True, "showSymbol": False,
                }]})
                chart.anim.stop()
                chart.anim.set_progress(1.0)
                pump(30)
            report["pipelines_after_rebuilds"] = len(viewport._gpu_pipes)
            check(len(viewport._gpu_pipes) <= 1,
                  "渲染器重建后旧管线释放", report["pipelines_after_rebuilds"])
            report["draw_results"] = draw_results
            report["draw_options"] = [
                {key: (value.name() if hasattr(value, "name") else value)
                 for key, value in item.items()} for item in draw_options]
    chart.close()
    chart.deleteLater()
    app.processEvents()
    destination = ROOT / "temp" / "performance" / report["source_sha"]
    destination.mkdir(parents=True, exist_ok=True)
    report["failures"] = _FAILURES
    path = destination / ("raster-geometry.json" if args.raster else "gpu-direct.json")
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"原始报告：{path}", flush=True)
    return 1 if _FAILURES else 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception:
        traceback.print_exc()
        raise SystemExit(1)
