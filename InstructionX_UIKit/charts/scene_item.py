# -*- coding: utf-8 -*-
"""只同步不可变快照的 QQuickItem，不在渲染线程解析数据或调用 QPainter。"""

import ctypes
from collections import deque

from PySide6.QtQuick import (
    QQuickItem,
    QSGClipNode,
    QSGGeometry,
    QSGNode,
    QSGSimpleRectNode,
    QSGSimpleTextureNode,
    QSGTexture,
)

from .scene_snapshot import build_scene_snapshot


class ChartSceneItem(QQuickItem):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._snapshot = None
        self._frames = deque(maxlen=3)
        self._static_node = None
        self._clip_node = None
        self._texture = None
        self._texture_key = None
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
        self._static_node = None
        self._clip_node = None
        self.update()

    def updatePaintNode(self, _root, _info):  # noqa: N802
        snapshot = self._snapshot
        if snapshot is None:
            self._frames.clear()
            self._texture = None
            self._texture_key = None
            return None
        root = QSGNode()
        if snapshot.static_image is not None:
            static_node = QSGSimpleTextureNode()
            static_node.setFiltering(QSGTexture.Nearest)
            static_node.setOwnsTexture(False)
            if self._texture is None or self._texture_key != snapshot.static_key:
                self._texture = self.window().createTextureFromImage(
                    snapshot.static_image)
                self._texture_key = snapshot.static_key
            static_node.setTexture(self._texture)
        else:
            static_node = QSGSimpleRectNode()
            static_node.setColor(snapshot.background)
        static_node.setRect(0, 0, snapshot.width, snapshot.height)
        root.appendChildNode(static_node)
        clip = QSGClipNode()
        clip.setIsRectangular(True)
        clip.setClipRect(snapshot.plot)
        root.appendChildNode(clip)
        line_nodes = []
        self._vertex_count = 0
        for line in snapshot.lines:
            vertices = line.vertices
            if len(vertices) < 2:
                continue
            node = QSGSimpleRectNode()
            node.setRect(snapshot.plot)
            node.setColor(line.color)
            geometry = node.geometry()
            geometry.allocate(len(vertices), 0)
            geometry.setDrawingMode(QSGGeometry.DrawLineStrip)
            geometry.setLineWidth(line.width)
            geometry.setVertexDataPattern(QSGGeometry.StreamPattern)
            ctypes.memmove(int(geometry.vertexData()), vertices.ctypes.data,
                           vertices.nbytes)
            geometry.markVertexDataDirty()
            clip.appendChildNode(node)
            line_nodes.append((node, geometry))
            self._vertex_count += len(vertices)
        self._frames.append((root, static_node, clip, line_nodes))
        self._static_node = static_node
        self._clip_node = clip
        return root
