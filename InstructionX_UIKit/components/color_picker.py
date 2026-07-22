# -*- coding: utf-8 -*-
"""颜色选择器组件（SPEC §5.1）。

``ColorPicker`` = 自绘色块按钮（点击弹出 QColorDialog）+ 十六进制文本。
色块按当前主题绘制边框，尺寸遵循 sm=24 / md=32 / lg=40 高度体系。
"""

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QColorDialog, QHBoxLayout, QLabel, QPushButton, QWidget

from ..theme import T, ThemeManager, set_property

__all__ = ["ColorPicker"]

_SIZES = ("sm", "md", "lg")
_EDGE = {"sm": 24, "md": 32, "lg": 40}


class _SwatchButton(QPushButton):
    """内部：自绘色块按钮（不用 QSS 背景，直接按当前色绘制）。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._color = QColor(T("color.primary"))
        self.setCursor(Qt.PointingHandCursor)
        ThemeManager.instance().theme_changed.connect(self.update)

    def set_color(self, color: QColor) -> None:
        self._color = QColor(color)
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        rect = self.rect().adjusted(2, 2, -2, -2)
        radius = 4.0
        # 色块本体
        p.setPen(Qt.NoPen)
        p.setBrush(self._color if self.isEnabled()
                   else QColor(T("color.text.disabled")))
        p.drawRoundedRect(rect, radius, radius)
        # 边框（深色块上仍可见）
        pen_color = QColor(T("color.border.strong"))
        p.setPen(pen_color)
        p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(rect, radius, radius)
        p.end()


class ColorPicker(QWidget):
    """颜色选择器。

    用途:
        展示并选择颜色：点击色块弹出系统 QColorDialog，
        选择后发射 ``colorChanged`` 并更新色块与十六进制文本。

    参数:
        color: 初始颜色（QColor 或 "#RRGGBB" 字符串）。
        size: ``sm`` / ``md`` / ``lg``，色块边长 24 / 32 / 40。
        show_text: 是否显示十六进制文本。
        parent: 父控件。

    示例::

        cp = ColorPicker("#3F5E8C", size="md")
        cp.colorChanged.connect(lambda c: print(c.name()))
        cp.set_color(QColor("#3E7E5F"))
    """

    #: 颜色变化信号
    colorChanged = Signal(QColor)

    def __init__(self, color="#3F5E8C", size: str = "md",
                 show_text: bool = True, parent=None):
        super().__init__(parent)
        self._color = QColor(color) if not isinstance(color, QColor) else QColor(color)
        self._show_text = show_text
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        self._swatch = _SwatchButton(self)
        self._swatch.set_color(self._color)
        self._swatch.clicked.connect(self._open_dialog)
        layout.addWidget(self._swatch)
        self._label = QLabel(self._color.name().upper(), self)
        set_property(self._label, "role", "secondary")
        layout.addWidget(self._label)
        layout.addStretch(1)
        self.set_size(size)
        if not show_text:
            self._label.hide()

    # ------------------------------------------------------------------
    # 属性
    # ------------------------------------------------------------------

    def color(self) -> QColor:
        """当前颜色。"""
        return QColor(self._color)

    def set_color(self, color) -> None:
        """设置颜色（QColor 或 "#RRGGBB" 字符串），发射 ``colorChanged``。"""
        color = QColor(color) if not isinstance(color, QColor) else QColor(color)
        if not color.isValid() or color == self._color:
            return
        self._color = color
        self._swatch.set_color(color)
        self._label.setText(color.name().upper())
        self.colorChanged.emit(QColor(color))

    def set_size(self, size: str) -> None:
        """设置尺寸档：``sm`` / ``md`` / ``lg``。"""
        if size not in _SIZES:
            raise ValueError(f"未知颜色选择器尺寸: {size!r}")
        set_property(self, "size", size)
        edge = _EDGE[size]
        self._swatch.setFixedSize(edge, edge)

    def size_name(self) -> str:
        """当前尺寸档名。"""
        return self.property("uiksize") or "md"

    def set_show_text(self, on: bool) -> None:
        """设置是否显示十六进制文本。"""
        self._show_text = bool(on)
        self._label.setVisible(on)

    # ------------------------------------------------------------------
    # 弹窗
    # ------------------------------------------------------------------

    def _open_dialog(self) -> None:
        color = QColorDialog.getColor(self._color, self, "选择颜色")
        if color.isValid():
            self.set_color(color)
