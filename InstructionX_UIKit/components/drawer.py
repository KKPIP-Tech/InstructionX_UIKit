# -*- coding: utf-8 -*-
"""抽屉 Drawer（SPEC §5.3 drawer.py）。

从父窗口四边滑入的容器：半透明遮罩、滑入滑出动画、
宽度（或高度）可拖拽、点击遮罩关闭。非阻塞 show 方式工作。
"""

from PySide6.QtCore import (
    QEasingCurve,
    QEvent,
    QPoint,
    QPropertyAnimation,
    QRect,
    Qt,
    QVariantAnimation,
)
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ..theme import T, ThemeManager, set_property
from .dialog import _close_icon
from shiboken6 import isValid as _shiboken_is_valid


def _connect_theme(widget, slot) -> None:
    """连接主题切换信号；控件销毁后自动忽略回调。"""
    ThemeManager.instance().theme_changed.connect(
        lambda *_: slot() if _shiboken_is_valid(widget) else None)

__all__ = ["Drawer"]

_MIN_SIZE = 200
_GRIP = 6


def _overlay_color() -> QColor:
    """解析 overlay 令牌（``rgba(r,g,b,a)`` 字符串）为 QColor。"""
    token = str(T("color.overlay"))
    if token.startswith("rgba"):
        inner = token[token.index("(") + 1: token.rindex(")")]
        r, g, b, a = [p.strip() for p in inner.split(",")][:4]
        alpha = float(a)
        alpha = int(round(alpha * 255)) if alpha <= 1.0 else int(alpha)
        return QColor(int(float(r)), int(float(g)), int(float(b)), alpha)
    return QColor(token)


class _Grip(QWidget):
    """抽屉内缘拖拽手柄，按住拖动调整面板尺寸。"""

    def __init__(self, drawer: "Drawer"):
        super().__init__(drawer._panel)
        self._drawer = drawer
        self._dragging = False
        self.setCursor(Qt.SizeHorCursor if drawer.position() in ("left", "right")
                       else Qt.SizeVerCursor)
        self._reposition()

    def _reposition(self) -> None:
        panel = self._drawer._panel
        pos = self._drawer.position()
        if pos == "right":
            self.setGeometry(0, 0, _GRIP, panel.height())
        elif pos == "left":
            self.setGeometry(panel.width() - _GRIP, 0, _GRIP, panel.height())
        elif pos == "top":
            self.setGeometry(0, panel.height() - _GRIP, panel.width(), _GRIP)
        else:
            self.setGeometry(0, 0, panel.width(), _GRIP)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self._dragging = True
            event.accept()

    def mouseMoveEvent(self, event) -> None:
        if not self._dragging:
            return
        self._drawer._drag_to(event.globalPosition().toPoint())

    def mouseReleaseEvent(self, event) -> None:
        self._dragging = False


class Drawer(QDialog):
    """抽屉：从四边滑入，宽度可拖拽，点击遮罩关闭。

    参数:
        parent: 父窗口（抽屉几何跟随它）。
        position: 滑入方向 ``"right"`` / ``"left"`` / ``"top"`` / ``"bottom"``。
        size: 面板宽（左右方向）或高（上下方向）。
        title: 标题文本。
        resizable: 是否允许拖拽调整尺寸。
        parent2: 父控件（关键字参数 ``parent``）。

    示例::

        dr = Drawer(self, position="right", size=360, title="详情")
        dr.set_content(QLabel("内容"))
        dr.open()
    """

    #: 合法滑入方向
    POSITIONS = ("left", "right", "top", "bottom")

    def __init__(self, parent: QWidget = None, position: str = "right",
                 size: int = 360, title: str = "", resizable: bool = True):
        super().__init__(parent, Qt.FramelessWindowHint | Qt.Dialog)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setModal(False)
        if position not in self.POSITIONS:
            raise ValueError(
                f"未知抽屉方向: {position!r}，应为 {self.POSITIONS} 之一")
        self._position = position
        self._size = max(_MIN_SIZE, int(size))
        self._overlay_alpha = 0.0
        self._opened = False
        self._closing = False

        self._panel = QFrame(self)
        self._panel.setObjectName("uikDrawerPanel")
        panel_layout = QVBoxLayout(self._panel)
        panel_layout.setContentsMargins(0, 0, 0, 0)
        panel_layout.setSpacing(0)

        header = QWidget(self._panel)
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(16, 14, 8, 10)
        self._title = QLabel(title, header)
        set_property(self._title, "uikDr", "title")
        header_layout.addWidget(self._title, 1)
        self._close_btn = QToolButton(header)
        self._close_btn.setFixedSize(26, 26)
        self._close_btn.setIcon(_close_icon())
        self._close_btn.setCursor(Qt.PointingHandCursor)
        self._close_btn.clicked.connect(self.close)
        header_layout.addWidget(self._close_btn)
        panel_layout.addWidget(header)

        body = QWidget(self._panel)
        self._body_layout = QVBoxLayout(body)
        self._body_layout.setContentsMargins(16, 4, 16, 16)
        self._body_layout.setSpacing(8)
        panel_layout.addWidget(body, 1)

        self._grip = _Grip(self) if resizable else None
        self._panel.hide()

        self._anim = QPropertyAnimation(self._panel, b"pos", self)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)
        self._anim.setDuration(T("duration.slow"))
        self._anim.finished.connect(self._on_anim_finished)
        self._fade = QVariantAnimation(self)
        self._fade.setDuration(T("duration.normal"))
        self._fade.valueChanged.connect(self._on_fade)

        if parent is not None:
            parent.installEventFilter(self)
        _connect_theme(self, self._reload_style)
        self._reload_style()

    # -- 公开 API ---------------------------------------------------------
    def position(self) -> str:
        """滑入方向。"""
        return self._position

    def set_title(self, text: str) -> None:
        """设置标题。"""
        self._title.setText(text)

    def set_content(self, widget: QWidget) -> None:
        """设置内容区控件（替换原有内容）。"""
        while self._body_layout.count():
            item = self._body_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        self._body_layout.addWidget(widget)

    def content_layout(self) -> QVBoxLayout:
        """返回内容区布局，便于自由添加多个控件。"""
        return self._body_layout

    def panel(self) -> QFrame:
        """返回抽屉面板控件。"""
        return self._panel

    def open(self) -> None:
        """打开抽屉（滑入动画，非阻塞）。"""
        self._sync_geometry()
        self._closing = False
        self.show()
        self.raise_()
        target, hidden = self._panel_positions()
        self._panel.resize(target.size())
        self._panel.move(hidden.topLeft())
        self._panel.show()
        if self._grip is not None:
            self._grip._reposition()
            self._grip.show()
        self._anim.stop()
        self._anim.setStartValue(hidden.topLeft())
        self._anim.setEndValue(target.topLeft())
        self._anim.start()
        self._start_fade(1.0)
        self._opened = True

    def close(self) -> None:  # noqa: A003 - 保持 QDialog 接口
        """关闭抽屉（滑出动画，结束后隐藏）。"""
        if not self.isVisible() or self._closing:
            return
        self._closing = True
        _target, hidden = self._panel_positions()
        self._anim.stop()
        self._anim.setStartValue(self._panel.pos())
        self._anim.setEndValue(hidden.topLeft())
        self._anim.start()
        self._start_fade(0.0)

    def reject(self) -> None:
        """Esc / 右上角关闭：走滑出动画。"""
        self.close()

    def panel_size(self) -> int:
        """面板宽（左右方向）或高（上下方向）。"""
        return self._size

    # -- 内部 -------------------------------------------------------------
    def _sync_geometry(self) -> None:
        if self.parent() is not None:
            top_left = self.parent().mapToGlobal(QPoint(0, 0))
            self.setGeometry(QRect(top_left, self.parent().size()))

    def _panel_positions(self):
        """返回 (目标矩形, 隐藏矩形)。"""
        w, h = self.width(), self.height()
        s = self._size
        if self._position == "right":
            return QRect(w - s, 0, s, h), QRect(w, 0, s, h)
        if self._position == "left":
            return QRect(0, 0, s, h), QRect(-s, 0, s, h)
        if self._position == "top":
            return QRect(0, 0, w, s), QRect(0, -s, w, s)
        return QRect(0, h - s, w, s), QRect(0, h, w, s)

    def _start_fade(self, end: float) -> None:
        self._fade.stop()
        self._fade.setStartValue(self._overlay_alpha)
        self._fade.setEndValue(end)
        self._fade.start()

    def _on_fade(self, value) -> None:
        self._overlay_alpha = float(value)
        self.update()

    def _on_anim_finished(self) -> None:
        if self._closing:
            self._closing = False
            self._opened = False
            self._panel.hide()
            self.hide()

    def _drag_to(self, global_pos: QPoint) -> None:
        geo = self.geometry()
        if self._position == "right":
            new = geo.x() + geo.width() - global_pos.x()
        elif self._position == "left":
            new = global_pos.x() - geo.x()
        elif self._position == "top":
            new = global_pos.y() - geo.y()
        else:
            new = geo.y() + geo.height() - global_pos.y()
        limit = int((self.width() if self._position in ("left", "right")
                     else self.height()) * 0.9)
        self._size = max(_MIN_SIZE, min(int(new), max(_MIN_SIZE, limit)))
        target, _hidden = self._panel_positions()
        self._panel.setGeometry(target)
        if self._grip is not None:
            self._grip._reposition()

    def eventFilter(self, watched, event) -> bool:
        if watched is self.parent() and event.type() in (
                QEvent.Resize, QEvent.Move) and self.isVisible():
            self._sync_geometry()
            if self._opened and not self._closing:
                target, _hidden = self._panel_positions()
                self._panel.setGeometry(target)
                if self._grip is not None:
                    self._grip._reposition()
        return super().eventFilter(watched, event)

    def mousePressEvent(self, event) -> None:
        # 点击遮罩（面板之外）关闭
        if not self._panel.geometry().contains(event.position().toPoint()):
            self.close()
        super().mousePressEvent(event)

    def paintEvent(self, event) -> None:
        if self._overlay_alpha <= 0.0:
            return
        color = _overlay_color()
        color.setAlpha(int(color.alpha() * self._overlay_alpha))
        painter = QPainter(self)
        painter.fillRect(self.rect(), color)
        painter.end()

    def _reload_style(self) -> None:
        c = lambda k: T(f"color.{k}")  # noqa: E731
        self.setStyleSheet(f"""
QFrame#uikDrawerPanel {{
    background-color: {c('bg.elevated')};
    border: 1px solid {c('border')};
}}
QLabel[uikDr="title"] {{
    color: {c('text.primary')};
    font-size: {T('font.title.sm')}px;
    font-weight: 600;
}}
QToolButton {{ background-color: transparent; border: none; }}
QToolButton:hover {{ background-color: {c('bg.muted')}; }}
""")
        self._close_btn.setIcon(_close_icon())
