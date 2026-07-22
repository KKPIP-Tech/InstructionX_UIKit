# -*- coding: utf-8 -*-
"""折叠面板组件（SPEC §5.2 collapse）。

点击标题栏展开 / 收起内容区，展开高度以 QPropertyAnimation
动画过渡；支持手风琴模式（同时仅展开一个面板）。
"""

from PySide6.QtCore import QEasingCurve, QPropertyAnimation, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from InstructionX_UIKit.theme import T, ThemeManager
from InstructionX_UIKit.tokens import DURATION, EASING

__all__ = ["Collapse"]

_HEADER_H = 44


class _PanelHeader(QWidget):
    """面板标题栏（自绘：底色 / 箭头 / 分隔线）。"""

    clicked = Signal()

    def __init__(self, title: str, parent=None):
        super().__init__(parent)
        self._title = title
        self._expanded = False
        self._hovered = False
        self.setFixedHeight(_HEADER_H)
        self.setCursor(Qt.PointingHandCursor)
        self.setAttribute(Qt.WA_Hover)
        ThemeManager.instance().theme_changed.connect(self.update)

    def set_expanded(self, expanded: bool) -> None:
        self._expanded = bool(expanded)
        self.update()

    def enterEvent(self, event) -> None:
        self._hovered = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._hovered = False
        self.update()
        super().leaveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.LeftButton and self.rect().contains(event.position().toPoint()):
            self.clicked.emit()
        super().mouseReleaseEvent(event)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = self.rect()
        painter.fillRect(rect, QColor(T("color.bg.muted") if self._hovered
                                      else T("color.bg.subtle")))
        # 箭头
        pen = QPen(QColor(T("color.text.secondary")))
        pen.setWidthF(1.6)
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        cy = rect.height() / 2
        ax = T("space.3")
        path = QPainterPath()
        if self._expanded:
            path.moveTo(ax - 4, cy - 2)
            path.lineTo(ax + 1, cy + 3)
            path.lineTo(ax + 6, cy - 2)
        else:
            path.moveTo(ax - 1, cy - 5)
            path.lineTo(ax + 4, cy)
            path.lineTo(ax - 1, cy + 5)
        painter.drawPath(path)
        # 标题
        painter.setPen(QColor(T("color.text.primary")))
        font = painter.font()
        font.setPixelSize(T("font.md"))
        font.setBold(True)
        painter.setFont(font)
        painter.drawText(
            QRectF(ax + 16, 0, rect.width() - ax - 32, rect.height()),
            Qt.AlignVCenter | Qt.AlignLeft,
            self._title,
        )
        # 底部分隔线
        painter.setPen(QPen(QColor(T("color.border"))))
        painter.drawLine(rect.bottomLeft(), rect.bottomRight())
        painter.end()


class _Panel(QWidget):
    """单个折叠面板：标题栏 + 可动画伸缩的内容区。"""

    toggled = Signal(bool)

    def __init__(self, title: str, content, parent=None):
        super().__init__(parent)
        self._expanded = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._header = _PanelHeader(title, self)
        self._header.clicked.connect(lambda: self.set_expanded(not self._expanded))
        layout.addWidget(self._header)

        if isinstance(content, str):
            label = QLabel(content, self)
            label.setWordWrap(True)
            content = label
        self._content = content
        self._content_area = QWidget(self)
        area_layout = QVBoxLayout(self._content_area)
        area_layout.setContentsMargins(T("space.3"), T("space.2"),
                                       T("space.3"), T("space.3"))
        area_layout.addWidget(content)
        layout.addWidget(self._content_area)

        self._anim = QPropertyAnimation(self._content_area, b"maximumHeight", self)
        self._anim.setDuration(DURATION["normal"])
        self._anim.setEasingCurve(EASING.get("standard", QEasingCurve.OutCubic))
        self._anim.finished.connect(self._on_anim_finished)

        self._apply_collapsed_state(animate=False)

    # ------------------------------------------------------------------ 状态
    def is_expanded(self) -> bool:
        return self._expanded

    def set_expanded(self, expanded: bool, animate: bool = True) -> None:
        expanded = bool(expanded)
        if expanded == self._expanded:
            return
        self._expanded = expanded
        self._apply_collapsed_state(animate=animate)
        self.toggled.emit(expanded)

    def content_widget(self):
        return self._content

    # ------------------------------------------------------------------ 动画
    def _apply_collapsed_state(self, animate: bool) -> None:
        self._anim.stop()
        self._header.set_expanded(self._expanded)
        area = self._content_area
        area.layout().activate()
        full_h = max(area.sizeHint().height(), 24)
        if self._expanded:
            area.setVisible(True)
            if animate:
                self._anim.setStartValue(0)
                self._anim.setEndValue(full_h)
                self._anim.start()
            else:
                area.setMaximumHeight(16777215)
        else:
            if animate:
                area.setVisible(True)
                self._anim.setStartValue(max(area.height(), 0))
                self._anim.setEndValue(0)
                self._anim.start()
            else:
                area.setMaximumHeight(0)
                area.setVisible(False)

    def _on_anim_finished(self) -> None:
        if self._expanded:
            # 展开完成后放开上限，允许内容随布局再变化
            self._content_area.setMaximumHeight(16777215)
        else:
            self._content_area.setVisible(False)
        self._content_area.updateGeometry()
        self.updateGeometry()


class Collapse(QWidget):
    """折叠面板容器。

    参数:
        accordion: 手风琴模式（同时只展开一个面板），默认 False。
        parent: 父控件。

    示例::

        col = Collapse(accordion=True)
        col.add_panel("第一章", "第一章内容", expanded=True)
        col.add_panel("第二章", QLabel("第二章内容"))
    """

    #: 面板展开状态变化信号，参数为 (索引, 是否展开)
    panel_toggled = Signal(int, bool)

    def __init__(self, accordion: bool = False, parent=None):
        super().__init__(parent)
        self._accordion = bool(accordion)
        self._panels = []
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(0)
        self._layout.addStretch(1)

    # ------------------------------------------------------------------ 面板
    def add_panel(self, title: str, content, expanded: bool = False) -> int:
        """添加面板，``content`` 为控件或多行文本，返回面板索引。"""
        panel = _Panel(title, content, self)
        index = len(self._panels)
        self._panels.append(panel)
        self._layout.insertWidget(self._layout.count() - 1, panel)
        panel.toggled.connect(lambda exp, i=index: self._on_panel_toggled(i, exp))
        if expanded:
            panel.set_expanded(True, animate=False)
        return index

    def panel_count(self) -> int:
        return len(self._panels)

    def set_expanded(self, index: int, expanded: bool) -> None:
        """展开 / 收起指定面板（带动画）。"""
        self._panels[index].set_expanded(expanded)

    def is_expanded(self, index: int) -> bool:
        return self._panels[index].is_expanded()

    def set_accordion(self, accordion: bool) -> None:
        """切换手风琴模式。"""
        self._accordion = bool(accordion)

    def is_accordion(self) -> bool:
        return self._accordion

    # ------------------------------------------------------------------ 内部
    def _on_panel_toggled(self, index: int, expanded: bool) -> None:
        if expanded and self._accordion:
            for i, panel in enumerate(self._panels):
                if i != index and panel.is_expanded():
                    panel.set_expanded(False)
        self.panel_toggled.emit(index, expanded)
