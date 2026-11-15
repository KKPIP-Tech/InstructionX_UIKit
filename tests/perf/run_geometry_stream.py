# -*- coding: utf-8 -*-
"""以相同数据、几何和生命周期门禁验证 RHI 三角网格视口。"""

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests" / "perf"))

from InstructionX_UIKit.charts.geometry_viewport import GeometryLineChartViewport
import run_canvas_stream

run_canvas_stream.CanvasLineChartViewport = GeometryLineChartViewport

if __name__ == "__main__":
    raise SystemExit(run_canvas_stream.main())
