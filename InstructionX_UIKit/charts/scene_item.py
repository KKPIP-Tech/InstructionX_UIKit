# -*- coding: utf-8 -*-
"""只把不可变图像快照同步为 Scene Graph 纹理的 QQuickItem。"""

from collections import deque

from PySide6.QtQuick import QQuickItem, QSGSimpleTextureNode, QSGTexture

from .scene_snapshot import build_scene_snapshot


class ChartSceneItem(QQuickItem):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._snapshot = None
        self._frames = deque(maxlen=3)
        self._texture = None
        self._texture_key = None
        self._node = None
        self._vertex_count = 0
        self.setFlag(QQuickItem.ItemHasContents, True)

    def sync(self, chart, dpr):
        self._snapshot = build_scene_snapshot(chart, dpr)
        self.update()

    def clear(self):
        self._snapshot = None
        self._frames.clear()
        self._texture = None
        self._texture_key = None
        self._node = None
        self.update()

    def updatePaintNode(self, root, _info):  # noqa: N802
        snapshot = self._snapshot
        if snapshot is None:
            self._frames.clear()
            self._texture = None
            self._texture_key = None
            self._node = None
            return None
        if self._texture is None or self._texture_key != snapshot.version:
            texture = self.window().createTextureFromImage(snapshot.image)
            if texture is None:
                return root
            self._texture = texture
            self._texture_key = snapshot.version
        node = QSGSimpleTextureNode()
        node.setFiltering(QSGTexture.Nearest)
        node.setOwnsTexture(False)
        node.setTexture(self._texture)
        node.setRect(0, 0, snapshot.width, snapshot.height)
        self._node = node
        self._frames.append((node, self._texture))
        return node
