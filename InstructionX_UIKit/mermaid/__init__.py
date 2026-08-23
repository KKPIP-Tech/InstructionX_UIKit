# -*- coding: utf-8 -*-
"""Mermaid 子包导出桶。

主渲染为 WebEngine + 官方 mermaid.js（SPEC 禁 WebView/JS 约束经用户显式
豁免，仅限本子包内部）；WebEngine 不可用时自动降级为 ``render`` 模块的
纯 QPainter 自绘子集渲染。

- ``MermaidRenderHub`` / ``render_diagram``：渲染为静态透明底 QImage；
- ``MermaidView``（view.py）：可交互图查看器——内嵌实时渲染，支持
  放大缩小与拖动平移（WebEngine 不可用时降级为自绘静态图画布）。
"""

from .hub import MermaidRenderHub, render_diagram
from .view import MermaidView

__all__ = [
    "MermaidRenderHub",
    "MermaidView",
    "render_diagram",
]
