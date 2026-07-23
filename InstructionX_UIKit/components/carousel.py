# -*- coding: utf-8 -*-
"""走马灯组件（SPEC §5.2 carousel）。

内容页横向滑动切换（QPropertyAnimation 位移动画），带指示点、
左右箭头与自动播放；悬停时暂停自动播放。
"""

from PySide6.QtCore import (
    QEasingCurve,
    QParallelAnimationGroup,
    QPoint,
    QPropertyAnimation,
    QRect,
    QSize,
    Qt,
    QTimer,
    Signal,
)
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QWidget

from InstructionX_UIKit.theme import T, ThemeManager
from InstructionX_UIKit.tokens import DURATION, EASING

__all__ = ["Carousel"]


class _ArrowButton(QWidget):
    """圆形自绘箭头按钮（左 / 右）。"""

    clicked = Signal()

    def __init__(self, direction: str, parent=None):
        super().__init__(parent)
        assert direction in ("left", "right")
        self._direction = direction
        self._hovered = False
        self.setFixedSize(32, 32)
        self.setCursor(Qt.PointingHandCursor)
        self.setAttribute(Qt.WA_Hover)
        ThemeManager.instance().theme_changed.connect(self.update)

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
        rect = self.rect().adjusted(1, 1, -1, -1)
        bg = QColor(T("color.bg.elevated"))
        bg.setAlpha(230 if self._hovered else 180)
        painter.setPen(QPen(QColor(T("color.border"))))
        painter.setBrush(bg)
        painter.drawEllipse(rect)
        # 箭头
        pen = QPen(QColor(T("color.primary") if self._hovered else T("color.text.secondary")))
        pen.setWidthF(1.8)
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        cx, cy = self.width() / 2, self.height() / 2
        path = QPainterPath()
        if self._direction == "left":
            path.moveTo(cx + 3, cy - 6)
            path.lineTo(cx - 3, cy)
            path.lineTo(cx + 3, cy + 6)
        else:
            path.moveTo(cx - 3, cy - 6)
            path.lineTo(cx + 3, cy)
            path.lineTo(cx - 3, cy + 6)
        painter.drawPath(path)
        painter.end()


class _DotsBar(QWidget):
    """指示点条：当前项为长条，其余为圆点，点击切换。"""

    clicked = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._count = 0
        self._current = 0
        self.setFixedHeight(16)
        self.setCursor(Qt.PointingHandCursor)
        ThemeManager.instance().theme_changed.connect(self.update)

    def set_count(self, count: int) -> None:
        self._count = max(0, int(count))
        self.setFixedWidth(self._count * 16 + 4)
        self.update()

    def set_current(self, index: int) -> None:
        self._current = int(index)
        self.update()

    def mousePressEvent(self, event) -> None:
        if self._count > 0:
            index = int(event.position().x()) // 16
            if 0 <= index < self._count:
                self.clicked.emit(index)
        super().mousePressEvent(event)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(Qt.NoPen)
        cy = self.height() / 2
        for i in range(self._count):
            x = 4 + i * 16
            if i == self._current:
                painter.setBrush(QColor(T("color.primary")))
                painter.drawRoundedRect(QRect(x, cy - 3, 14, 6), 3, 3)
            else:
                painter.setBrush(QColor(T("color.border.strong")))
                painter.drawEllipse(QRect(x + 3, cy - 3, 6, 6))
        painter.end()


class Carousel(QWidget):
    """走马灯（轮播）容器。

    参数:
        autoplay: 自动播放间隔（毫秒），``0`` 关闭，默认 0。
        parent: 父控件。

    示例::

        carousel = Carousel(autoplay=3000)
        carousel.add_page(QLabel("第一屏"))
        carousel.add_page(QLabel("第二屏"))
        carousel.go_to(1)
    """

    currentChanged = Signal(int)

    def __init__(self, autoplay: int = 0, parent=None):
        super().__init__(parent)
        self._pages = []
        self._current = -1
        self._anim = None
        self._autoplay = 0

        self._viewport = QWidget(self)
        self._prev_btn = _ArrowButton("left", self)
        self._next_btn = _ArrowButton("right", self)
        self._dots = _DotsBar(self)
        self._prev_btn.clicked.connect(self.prev)
        self._next_btn.clicked.connect(self.next)
        self._dots.clicked.connect(self.go_to)

        self._timer = QTimer(self)
        self._timer.timeout.connect(self.next)
        if autoplay:
            self.set_autoplay(autoplay)
        self._update_nav_visibility()

    # ------------------------------------------------------------------ 页面
    def add_page(self, widget: QWidget) -> int:
        """添加一页，返回页索引。"""
        widget.setParent(self._viewport)
        widget.hide()
        self._pages.append(widget)
        self._dots.set_count(len(self._pages))
        if self._current < 0:
            self._current = 0
            widget.show()
            self._layout_pages()
        self._update_nav_visibility()
        return len(self._pages) - 1

    def page(self, index: int):
        return self._pages[index]

    def count(self) -> int:
        return len(self._pages)

    def current_index(self) -> int:
        return self._current

    # ------------------------------------------------------------------ 切换
    def go_to(self, index: int) -> None:
        """滑动切换到指定页。"""
        n = len(self._pages)
        if n == 0 or index == self._current or not (0 <= index < n):
            return
        old_index = self._current
        self._current = index
        self._dots.set_current(index)
        self.currentChanged.emit(index)
        if self._anim is not None or old_index < 0:
            # 动画进行中或首次：直接切换
            if old_index >= 0:
                self._pages[old_index].hide()
            self._pages[index].show()
            self._layout_pages()
            return

        if index == (old_index + 1) % n:
            direction = 1
        elif index == (old_index - 1) % n:
            direction = -1
        else:
            direction = 1 if index > old_index else -1

        old_page = self._pages[old_index]
        new_page = self._pages[index]
        w, h = self._viewport.width(), self._viewport.height()
        new_page.setGeometry(w * direction, 0, w, h)
        new_page.show()
        new_page.raise_()

        group = QParallelAnimationGroup(self)
        for page, start, end in (
            (old_page, QPoint(0, 0), QPoint(-w * direction, 0)),
            (new_page, QPoint(w * direction, 0), QPoint(0, 0)),
        ):
            anim = QPropertyAnimation(page, b"pos", group)
            anim.setDuration(DURATION["slow"])
            anim.setEasingCurve(EASING.get("standard", QEasingCurve.OutCubic))
            anim.setStartValue(start)
            anim.setEndValue(end)
            group.addAnimation(anim)

        def _finish():
            old_page.hide()
            self._layout_pages()
            self._anim = None

        group.finished.connect(_finish)
        self._anim = group
        group.start()

    def next(self) -> None:
        """下一页（循环）。"""
        if self._pages:
            self.go_to((self._current + 1) % len(self._pages))

    def prev(self) -> None:
        """上一页（循环）。"""
        if self._pages:
            self.go_to((self._current - 1) % len(self._pages))

    # ------------------------------------------------------------------ 自动播放
    def set_autoplay(self, interval_ms: int) -> None:
        """设置自动播放间隔（毫秒），``0`` 停止。"""
        self._autoplay = max(0, int(interval_ms))
        self._timer.stop()
        if self._autoplay:
            self._timer.start(self._autoplay)

    def autoplay_interval(self) -> int:
        return self._autoplay

    def enterEvent(self, event) -> None:
        self._timer.stop()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        if self._autoplay:
            self._timer.start(self._autoplay)
        super().leaveEvent(event)

    # ------------------------------------------------------------------ 布局
    def _update_nav_visibility(self) -> None:
        visible = len(self._pages) > 1
        self._prev_btn.setVisible(visible)
        self._next_btn.setVisible(visible)
        self._dots.setVisible(visible)

    def _layout_pages(self) -> None:
        if 0 <= self._current < len(self._pages):
            self._pages[self._current].setGeometry(self._viewport.rect())

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        w, h = self.width(), self.height()
        self._viewport.setGeometry(0, 0, w, h)
        self._layout_pages()
        self._prev_btn.move(12, (h - self._prev_btn.height()) // 2)
        self._next_btn.move(w - self._next_btn.width() - 12,
                            (h - self._next_btn.height()) // 2)
        self._dots.move((w - self._dots.width()) // 2, h - self._dots.height() - 8)
        self._prev_btn.raise_()
        self._next_btn.raise_()
        self._dots.raise_()

    def sizeHint(self) -> QSize:
        return QSize(480, 240)

    def minimumSizeHint(self) -> QSize:
        return QSize(240, 140)
