# -*- coding: utf-8 -*-
"""ChartWidget 的 Scene Graph 纹理项。"""

from .._rhi_texture import RhiTextureItem
from .scene_snapshot import build_scene_snapshot


class ChartSceneItem(RhiTextureItem):
    def build_snapshot(self, chart, dpr):
        return build_scene_snapshot(chart, dpr)
