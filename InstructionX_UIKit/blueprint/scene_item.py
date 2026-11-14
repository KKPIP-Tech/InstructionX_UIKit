# -*- coding: utf-8 -*-
"""BlueprintCanvas 的 Scene Graph 纹理项。"""

from .._rhi_texture import RhiTextureItem
from .scene_snapshot import build_scene_snapshot


class BlueprintSceneItem(RhiTextureItem):
    def build_snapshot(self, canvas, dpr):
        return build_scene_snapshot(canvas, dpr)
