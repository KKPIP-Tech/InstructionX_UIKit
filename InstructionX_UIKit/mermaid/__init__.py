# -*- coding: utf-8 -*-
"""Mermaid 子包导出桶。

主渲染为 WebEngine + 官方 mermaid.js（SPEC 禁 WebView/JS 约束经用户显式
豁免，仅限本子包内部）；WebEngine 不可用时自动降级为 ``render`` 模块的
纯 QPainter 自绘子集渲染。
"""

from .hub import MermaidRenderHub, render_diagram

__all__ = [
    "MermaidRenderHub",
    "render_diagram",
]
