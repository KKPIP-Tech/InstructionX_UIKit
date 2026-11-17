# -*- coding: utf-8 -*-
"""重型视口交互缩放的私有预览状态机。"""

from PySide6.QtCore import QTimer

__all__ = ["ResizePreview"]


class ResizePreview:
    """保存单张有效帧，静止后通知调用方做一次全质量恢复。"""

    def __init__(self, owner, settle_ms=100, on_settle=None):
        self._active = False
        self._snapshot = None
        self._on_settle = on_settle
        self._timer = QTimer(owner)
        self._timer.setSingleShot(True)
        self._timer.setInterval(settle_ms)
        self._timer.timeout.connect(self.finish)

    @property
    def active(self):
        return self._active

    @property
    def snapshot(self):
        return self._snapshot

    def begin(self, snapshot):
        if snapshot is None or snapshot.isNull():
            return False
        if not self._active:
            self._snapshot = snapshot
            self._active = True
        self._timer.start()
        return True

    def touch(self):
        if self._active:
            self._timer.start()

    def finish(self):
        self._timer.stop()
        if not self._active:
            return False
        self._active = False
        self._snapshot = None
        if self._on_settle is not None:
            self._on_settle()
        return True

    def cancel(self):
        self._timer.stop()
        self._active = False
        self._snapshot = None
