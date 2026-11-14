# -*- coding: utf-8 -*-
"""供重型视口复用的 RHI 纹理节点与不可变帧结构。"""

from collections import deque
from dataclasses import dataclass

from PySide6.QtCore import QRectF
from PySide6.QtGui import QImage
from PySide6.QtQuick import QSGNode, QQuickItem, QSGSimpleTextureNode, QSGTexture


@dataclass(frozen=True)
class SceneSnapshot:
    image: QImage
    width: int
    height: int
    dpr: float
    version: int


class RhiTextureItem(QQuickItem):
    """UI 线程生成图像，渲染线程仅更新纹理与节点材质。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._snapshot = None
        self._frames = deque(maxlen=3)
        self._texture = None
        self._texture_key = None
        self._node = None
        self.setFlag(QQuickItem.ItemHasContents, True)

    def build_snapshot(self, source, dpr):
        raise NotImplementedError

    def sync(self, source, dpr):
        self._snapshot = self.build_snapshot(source, dpr)
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
        if root is None:
            root = QSGSimpleTextureNode()
        root.setFiltering(QSGTexture.Nearest)
        root.setOwnsTexture(False)
        root.setTexture(self._texture)
        root.setRect(QRectF(0, 0, snapshot.width, snapshot.height))
        root.markDirty(QSGNode.DirtyMaterial)
        self._node = root
        self._frames.append((root, self._texture))
        return root
