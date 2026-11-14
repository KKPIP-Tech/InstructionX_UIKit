# -*- coding: utf-8 -*-
"""供重型视口复用的 RHI 纹理节点与不可变帧结构。"""

from collections import deque
from dataclasses import dataclass
import os

# 原生嵌入采用 GUI 线程调度，避免输入和窗口生命周期与渲染线程互相等待。
os.environ.setdefault("QSG_RENDER_LOOP", "basic")

from PySide6.QtCore import QRectF, Qt
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
        self._blank_texture = None
        self._node = None
        self.setFlag(QQuickItem.ItemHasContents, True)
        self.destroyed.connect(self._release_textures)

    def build_snapshot(self, source, dpr):
        raise NotImplementedError

    def sync(self, source, dpr):
        self._snapshot = self.build_snapshot(source, dpr)
        self.update()

    def _retain_frame(self, texture):
        expired = self._frames[0] if len(self._frames) == self._frames.maxlen else None
        self._frames.append((self._node, texture))
        if expired is None:
            return
        old_texture = expired[1]
        if old_texture is self._blank_texture or old_texture is self._texture:
            return
        if any(old_texture is frame[1] for frame in self._frames):
            return
        try:
            old_texture.deleteLater()
        except RuntimeError:
            pass

    def _release_textures(self):
        textures = {id(texture): texture for _node, texture in self._frames
                    if texture is not None}
        for texture in (self._texture, self._blank_texture):
            if texture is not None:
                textures[id(texture)] = texture
        self._frames.clear()
        self._snapshot = None
        self._texture = None
        self._texture_key = None
        self._blank_texture = None
        self._node = None
        for texture in textures.values():
            try:
                texture.deleteLater()
            except RuntimeError:
                pass

    def clear(self):
        self._snapshot = None
        self._texture_key = None
        self.update()

    def updatePaintNode(self, root, _info):  # noqa: N802
        snapshot = self._snapshot
        if snapshot is None:
            if self._blank_texture is None:
                image = QImage(1, 1, QImage.Format_RGBA8888)
                image.fill(Qt.transparent)
                self._blank_texture = self.window().createTextureFromImage(image)
            if root is None:
                root = QSGSimpleTextureNode()
            root.setFiltering(QSGTexture.Nearest)
            root.setOwnsTexture(False)
            root.setTexture(self._blank_texture)
            root.setRect(QRectF(0, 0, self.width(), self.height()))
            root.markDirty(QSGNode.DirtyMaterial)
            self._node = root
            self._retain_frame(self._blank_texture)
            return root
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
        self._retain_frame(self._texture)
        return root
