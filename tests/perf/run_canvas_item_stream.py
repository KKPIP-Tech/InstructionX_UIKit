# -*- coding: utf-8 -*-
"""以同一负载验收 QCanvasPainterItem 的多系列流式绘制。"""

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests" / "perf"))

from InstructionX_UIKit.charts.canvas_item_viewport import CanvasItemLineChartViewport
import run_canvas_stream

run_canvas_stream.CanvasLineChartViewport = CanvasItemLineChartViewport

if __name__ == "__main__":
    raise SystemExit(run_canvas_stream.main())
