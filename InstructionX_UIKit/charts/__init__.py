# -*- coding: utf-8 -*-
"""InstructionX_UIKit.charts：类 ECharts 原生图表引擎（纯 QPainter，CHART_SPEC）。

包级导出：``ChartWidget`` / ``register_series`` / ``register_component`` /
注册表 / 协议基类 / 坐标系 / 内置组件。

``series_cartesian`` / ``series_hierarchy`` / ``components`` / ``interact``
由后续代理（C2/C3/C4）提供，此处以 try/except 惰性导入：任一模块缺失或
依赖未就绪时静默跳过，不影响 core 的使用。
"""

from .core import (
    COMPONENT_REGISTRY,
    SERIES_REGISTRY,
    ChartAnimation,
    ChartWidget,
    Legend,
    SeriesRenderer,
    SimpleLineSeriesRenderer,
    Title,
    Tooltip,
    default_palette,
    format_value,
    nice_ticks,
    parse_data_point,
    register_component,
    register_series,
)
from .axes import (
    AxisModel,
    CalendarCoord,
    Coord,
    GridCoord,
    PolarCoord,
    SingleAxisCoord,
    chart_font,
)

__all__ = [
    "ChartWidget",
    "ChartAnimation",
    "SeriesRenderer",
    "Coord",
    "Title",
    "Legend",
    "Tooltip",
    "AxisModel",
    "GridCoord",
    "PolarCoord",
    "SingleAxisCoord",
    "CalendarCoord",
    "SERIES_REGISTRY",
    "COMPONENT_REGISTRY",
    "register_series",
    "register_component",
    "default_palette",
    "nice_ticks",
    "format_value",
    "parse_data_point",
    "chart_font",
    "SimpleLineSeriesRenderer",
]

# ---------------------------------------------------------------------------
# 惰性导入后续代理模块（导入时完成各自的 register_series / register_component；
# 失败不影响 core 使用）
# ---------------------------------------------------------------------------

import importlib as _importlib

for _mod in ("series_cartesian", "series_hierarchy", "components", "interact"):
    try:
        _importlib.import_module(f"{__name__}.{_mod}")
    except Exception:
        pass
del _importlib, _mod
