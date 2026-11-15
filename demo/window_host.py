# -*- coding: utf-8 -*-
"""UIKit 自有无边框宿主：验证系统与手动窗口手势。"""

from PySide6.QtCore import QEvent, QObject, QPoint, QRect, Qt
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from shiboken6 import isValid as _shiboken_is_valid

from InstructionX_UIKit.theme import T, ThemeManager, set_font


class WindowGestureController(QObject):
    """优先系统手势，系统不可用时保留手动移动和缩放。"""

    MARGIN = 8

    def __init__(self, window, titlebar, system_move=None, system_resize=None):
        super().__init__(window)
        self._window = window
        self._titlebar = titlebar
        self._system_move = system_move or (
            lambda handle: handle.startSystemMove())
        self._system_resize = system_resize or (
            lambda handle, edges: handle.startSystemResize(edges))
        self._manual = None
        titlebar.installEventFilter(self)

    def edges_at(self, position, rect=None):
        rect = self._titlebar.rect() if rect is None else rect
        edges = Qt.Edge(0)
        if position.x() < self.MARGIN:
            edges |= Qt.LeftEdge
        elif position.x() >= rect.width() - self.MARGIN:
            edges |= Qt.RightEdge
        if position.y() < self.MARGIN:
            edges |= Qt.TopEdge
        elif position.y() >= rect.height() - self.MARGIN:
            edges |= Qt.BottomEdge
        return edges

    def eventFilter(self, watched, event):  # noqa: N802
        titlebar = getattr(self, "_titlebar", None)
        window = getattr(self, "_window", None)
        if not _shiboken_is_valid(self) or titlebar is None or window is None \
                or not _shiboken_is_valid(titlebar) or not _shiboken_is_valid(window):
            return False
        if watched is titlebar and event.type() == QEvent.MouseButtonPress \
                and event.button() == Qt.MouseButton.LeftButton:
            position = event.position().toPoint()
            if titlebar.childAt(position) not in (None, titlebar):
                return False
            if self.edges_at(position):
                return False
            if window.windowHandle() is not None \
                    and self._system_move(window.windowHandle()):
                event.accept()
                return True
            self._manual = ("move", event.globalPosition().toPoint(),
                            window.geometry())
            event.accept()
            return True
        return super().eventFilter(watched, event)

    def begin_resize(self, position, global_position, rect=None):
        edges = self.edges_at(position, rect)
        if not edges:
            return False
        handle = self._window.windowHandle()
        if handle is not None and self._system_resize(handle, edges):
            return True
        self._manual = (edges, global_position, self._window.geometry())
        return True

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if self._manual is None:
            return
        edges, origin, geometry = self._manual
        delta = event.globalPosition().toPoint() - origin
        if edges == "move":
            self._window.setGeometry(geometry.translated(delta))
            return
        rect = QRect(geometry)
        min_w, min_h = self._window.minimumSize().width(), self._window.minimumSize().height()
        if edges & Qt.LeftEdge:
            rect.setLeft(min(rect.right() - min_w + 1, rect.left() + delta.x()))
        if edges & Qt.RightEdge:
            rect.setRight(max(rect.left() + min_w - 1, rect.right() + delta.x()))
        if edges & Qt.TopEdge:
            rect.setTop(min(rect.bottom() - min_h + 1, rect.top() + delta.y()))
        if edges & Qt.BottomEdge:
            rect.setBottom(max(rect.top() + min_h - 1, rect.bottom() + delta.y()))
        self._window.setGeometry(rect)

    def mouseReleaseEvent(self, _event) -> None:  # noqa: N802
        self._manual = None


class WindowHost(QMainWindow):
    """带透明、圆角和关闭按钮的无边框验证宿主。"""

    def __init__(self):
        super().__init__()
        self.setWindowFlags(self.windowFlags() | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_NoSystemBackground)
        self.setAutoFillBackground(False)
        self.setMinimumSize(320, 240)
        self.resize(900, 600)
        central = QWidget(self)
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(12, 12, 12, 12)
        titlebar = QFrame(central)
        titlebar.setFixedHeight(48)
        row = QHBoxLayout(titlebar)
        row.setContentsMargins(12, 0, 8, 0)
        title = QLabel("UIKit 窗口手势验证", titlebar)
        title.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        set_font(title, "title.sm", "semibold")
        row.addWidget(title, 1)
        close = QToolButton(titlebar)
        close.setText("×")
        close.setToolTip("关闭")
        close.clicked.connect(self.close)
        row.addWidget(close)
        layout.addWidget(titlebar)
        hint = QLabel("拖动标题栏移动窗口；四边四角缩放窗口。", central)
        set_font(hint, "md")
        layout.addWidget(hint, 1)
        self._central = central
        self._titlebar = titlebar
        self.gesture = WindowGestureController(self, titlebar)
        titlebar.installEventFilter(self)
        central.installEventFilter(self)

    def eventFilter(self, watched, event):  # noqa: N802
        central = getattr(self, "_central", None)
        gesture = getattr(self, "gesture", None)
        if watched is central and central is not None and _shiboken_is_valid(central) \
                and gesture is not None and _shiboken_is_valid(gesture):
            if event.type() == QEvent.MouseButtonPress \
                    and event.button() == Qt.MouseButton.LeftButton:
                if gesture.begin_resize(event.position().toPoint(),
                                        event.globalPosition().toPoint(), central.rect()):
                    event.accept()
                    return True
            if event.type() in (QEvent.MouseMove, QEvent.MouseButtonRelease) \
                    and gesture._manual is not None:
                if event.type() == QEvent.MouseButtonRelease:
                    gesture.mouseReleaseEvent(event)
                else:
                    gesture.mouseMoveEvent(event)
                event.accept()
                return True
        return super().eventFilter(watched, event)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton and self._titlebar.geometry().contains(
                event.position().toPoint()):
            self.gesture.begin_resize(
                self._titlebar.mapFrom(self, event.position().toPoint()),
                event.globalPosition().toPoint())
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        self.gesture.mouseMoveEvent(event)
        event.accept()

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        self.gesture.mouseReleaseEvent(event)
        super().mouseReleaseEvent(event)

    def paintEvent(self, _event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(T("color.bg.elevated")))
        painter.drawRoundedRect(self.rect(), T("radius.lg"), T("radius.lg"))
        painter.end()


def main():
    import sys

    app = QApplication(sys.argv)
    ThemeManager.instance().apply(app)
    window = WindowHost()
    window.show()
    return app.exec()


if __name__ == "__main__":
    import sys

    sys.exit(main())
