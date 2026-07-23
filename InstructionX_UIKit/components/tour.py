# -*- coding: utf-8 -*-
"""漫游式引导 Tour（SPEC §5.3 tour.py）。

覆盖父窗口的引导层：半透明镂空遮罩高亮目标控件 + 步骤气泡，
支持上一步 / 下一步 / 跳过。
"""

from PySide6.QtCore import QEvent, QPoint, QRect, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..theme import T, ThemeManager, set_property
from .drawer import _overlay_color
from shiboken6 import isValid as _shiboken_is_valid


def _connect_theme(widget, slot) -> None:
    """连接主题切换信号；控件销毁后自动忽略回调。"""
    ThemeManager.instance().theme_changed.connect(
        lambda *_: slot() if _shiboken_is_valid(widget) else None)

__all__ = ["Tour"]

_PAD = 6
_GAP = 12


class _TourBubble(QFrame):
    """引导步骤气泡卡片。"""

    skipClicked = Signal()
    prevClicked = Signal()
    nextClicked = Signal()

    def __init__(self, parent: QWidget = None):
        super().__init__(parent)
        self.setObjectName("uikTourBubble")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(6)

        self._title = QLabel(self)
        set_property(self._title, "uikTour", "title")
        layout.addWidget(self._title)

        self._content = QLabel(self)
        self._content.setWordWrap(True)
        self._content.setFixedWidth(264)
        policy = self._content.sizePolicy()
        policy.setHeightForWidth(True)
        self._content.setSizePolicy(policy)
        set_property(self._content, "uikTour", "content")
        layout.addWidget(self._content)

        footer = QHBoxLayout()
        footer.setSpacing(8)
        self._counter = QLabel(self)
        set_property(self._counter, "role", "tertiary")
        footer.addWidget(self._counter)
        footer.addStretch(1)
        self._skip = QPushButton("跳过", self)
        set_property(self._skip, "variant", "link")
        set_property(self._skip, "size", "sm")
        self._prev = QPushButton("上一步", self)
        set_property(self._prev, "variant", "default")
        set_property(self._prev, "size", "sm")
        self._next = QPushButton("下一步", self)
        set_property(self._next, "variant", "primary")
        set_property(self._next, "size", "sm")
        self._skip.clicked.connect(self.skipClicked.emit)
        self._prev.clicked.connect(self.prevClicked.emit)
        self._next.clicked.connect(self.nextClicked.emit)
        footer.addWidget(self._skip)
        footer.addWidget(self._prev)
        footer.addWidget(self._next)
        layout.addLayout(footer)

        _connect_theme(self, self._reload_style)
        self._reload_style()

    def set_data(self, index: int, count: int, title: str,
                 content: str) -> None:
        """刷新气泡内容（步骤序号从 0 开始）。"""
        self._title.setText(title)
        self._content.setText(content)
        self._counter.setText(f"{index + 1}/{count}")
        self._prev.setEnabled(index > 0)
        self._next.setText("完成" if index >= count - 1 else "下一步")
        self.adjustSize()

    def _reload_style(self) -> None:
        c = lambda k: T(f"color.{k}")  # noqa: E731
        self.setStyleSheet(f"""
QFrame#uikTourBubble {{
    background-color: {c('bg.elevated')};
    border: 1px solid {c('border')};
    border-radius: {T('radius.xl')}px;
}}
QLabel[uikTour="title"] {{
    color: {c('text.primary')};
    font-size: {T('font.lg')}px;
    font-weight: 600;
    background-color: transparent;
}}
QLabel[uikTour="content"] {{
    color: {c('text.secondary')};
    background-color: transparent;
}}
""")


class Tour(QWidget):
    """漫游式引导：高亮目标控件 + 步骤气泡。

    参数:
        parent: 父窗口（引导层覆盖它的整个区域）。

    示例::

        tour = Tour(self)
        tour.add_step(save_btn, "保存", "点击这里保存更改")
        tour.start()
    """

    #: 完成全部步骤时发射
    finished = Signal()
    #: 点击「跳过」时发射
    skipped = Signal()
    #: 当前步骤变化信号（从 0 开始）
    currentChanged = Signal(int)

    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self._steps = []     # [(target, title, content)]
        self._index = -1
        self._bubble = _TourBubble(self)
        self._bubble.hide()
        self._bubble.skipClicked.connect(self.skip)
        self._bubble.prevClicked.connect(self.prev)
        self._bubble.nextClicked.connect(self.next)
        if parent is not None:
            parent.installEventFilter(self)
        self.hide()
        _connect_theme(self, self.update)

    # -- 公开 API ---------------------------------------------------------
    def add_step(self, target: QWidget, title: str, content: str) -> None:
        """添加一步引导。"""
        self._steps.append((target, title, content))

    def clear_steps(self) -> None:
        """清空全部步骤。"""
        self._steps = []
        self.stop()

    def start(self, index: int = 0) -> None:
        """开始引导（非阻塞显示覆盖层）。"""
        if not self._steps or self.parent() is None:
            return
        self.setGeometry(self.parent().rect())
        self.show()
        self.raise_()
        self._goto(index)

    def next(self) -> None:
        """下一步；最后一步时完成并发射 finished。"""
        if self._index >= len(self._steps) - 1:
            self.stop()
            self.finished.emit()
        else:
            self._goto(self._index + 1)

    def prev(self) -> None:
        """上一步。"""
        if self._index > 0:
            self._goto(self._index - 1)

    def skip(self) -> None:
        """跳过引导并发射 skipped。"""
        self.stop()
        self.skipped.emit()

    def stop(self) -> None:
        """停止引导（不发射任何信号）。"""
        self._index = -1
        self._bubble.hide()
        self.hide()

    def is_running(self) -> bool:
        return self._index >= 0

    def current(self) -> int:
        return self._index

    # -- 内部 -------------------------------------------------------------
    def _goto(self, index: int) -> None:
        index = max(0, min(index, len(self._steps) - 1))
        self._index = index
        target, title, content = self._steps[index]
        self._bubble.set_data(index, len(self._steps), title, content)
        self._bubble.show()
        self._bubble.raise_()
        self._reposition()
        self.currentChanged.emit(index)
        self.update()

    def _target_rect(self) -> QRect:
        if not (0 <= self._index < len(self._steps)) or self.parent() is None:
            return QRect()
        target = self._steps[self._index][0]
        # Tour 几何与父窗口一致，映射到父窗口坐标即可
        top_left = target.mapTo(self.parent(), QPoint(0, 0))
        return QRect(top_left, target.size()).adjusted(
            -_PAD, -_PAD, _PAD, _PAD)

    def _reposition(self) -> None:
        hole = self._target_rect()
        bw = self._bubble.width()
        bh = self._bubble.height()
        x = hole.center().x() - bw // 2
        x = max(8, min(x, self.width() - bw - 8))
        y = hole.bottom() + _GAP
        if y + bh > self.height() - 8:
            y = hole.top() - _GAP - bh
        y = max(8, min(y, self.height() - bh - 8))
        self._bubble.move(x, y)

    def eventFilter(self, watched, event) -> bool:
        if watched is self.parent() and self.isVisible() \
                and event.type() in (QEvent.Resize, QEvent.Move):
            self.setGeometry(self.parent().rect())
            if self.is_running():
                self._reposition()
        return super().eventFilter(watched, event)

    def mousePressEvent(self, event) -> None:
        event.accept()  # 阻断点击穿透到被遮罩的控件

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key_Escape:
            self.skip()
        else:
            super().keyPressEvent(event)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        radius = T("radius.lg")
        full = QPainterPath()
        full.addRect(QRectF(self.rect()))
        hole = self._target_rect()
        if hole.isValid():
            hole_path = QPainterPath()
            hole_path.addRoundedRect(hole.x(), hole.y(), hole.width(),
                                     hole.height(), radius, radius)
            painter.fillPath(full.subtracted(hole_path), _overlay_color())
            # 高亮描边
            pen = QPen(QColor(255, 255, 255, 230))
            pen.setWidthF(2.0)
            painter.setPen(pen)
            painter.setBrush(Qt.NoBrush)
            painter.drawRoundedRect(hole, radius, radius)
        else:
            painter.fillPath(full, _overlay_color())
        painter.end()
