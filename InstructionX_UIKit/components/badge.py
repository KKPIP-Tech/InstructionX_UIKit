# -*- coding: utf-8 -*-
"""徽标组件（SPEC §5.2 badge）。

可包裹任意子控件并在其右上角叠加数字 / 红点角标，也可独立使用；
超过最大值显示 ``99+``；自绘实现，亮 / 暗主题实时感知。

实现要点：角标是 Badge 的**独立子控件**（``_Pill``），创建顺序在被
包裹控件之后并在几何变化时 ``raise_()``，保证绘制层级始终高于被
包裹控件（修复角标被遮挡的 z-order 缺陷）；角标宽度由绘制字体的
真实文本宽度加水平内边距决定（最小为高度，形成 pill 圆角），保证
``99+`` 等宽文本完整显示。
"""

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter
from PySide6.QtWidgets import QVBoxLayout, QWidget

from InstructionX_UIKit.theme import T, ThemeManager

__all__ = ["Badge"]

#: 角标角色 -> 颜色令牌
_COLOR_KEYS = {
    "danger": "color.danger",
    "primary": "color.primary",
    "success": "color.success",
    "warning": "color.warning",
}

_PILL_H = 18  # 数字角标高度
_DOT_D = 8    # 红点直径
_PAD_X = 6    # 数字角标单侧水平内边距（保证文本不顶边）


class _Pill(QWidget):
    """角标本体（Badge 的顶层子控件，自绘数字 / 红点）。

    作为独立子控件浮于被包裹控件之上绘制，避免"父控件 paintEvent
    绘制、被子控件遮挡"的 z-order 问题；鼠标事件穿透，不干扰被包裹
    控件的交互。
    """

    def __init__(self, badge: "Badge"):
        super().__init__(badge)
        self._badge = badge
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)

    def paintEvent(self, event) -> None:
        badge = self._badge
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = self.rect()
        color = QColor(T(_COLOR_KEYS[badge._color_role]))
        painter.setPen(Qt.NoPen)
        painter.setBrush(color)
        h = rect.height()
        painter.drawRoundedRect(rect, h / 2, h / 2)  # pill 半径 = 高度一半
        if not badge._dot:
            painter.setPen(QColor(T("color.on.primary")))
            painter.setFont(badge._text_font())
            painter.drawText(rect, Qt.AlignCenter, badge._text())
        painter.end()


class Badge(QWidget):
    """数字 / 红点徽标。

    参数:
        widget: 被包裹的子控件（可选；不传则为独立角标）。
        count: 角标数字。
        max_count: 上限，超出显示 ``{max}+``，默认 99。
        dot: 红点模式（不显示数字）。
        color: ``"danger"`` / ``"primary"`` / ``"success"`` / ``"warning"``。
        parent: 父控件。

    示例::

        badge = Badge(QPushButton("消息"), count=5)
        badge.set_count(120)            # 显示 99+
        dot = Badge(dot=True)           # 独立红点
    """

    def __init__(self, widget=None, count: int = 0, max_count: int = 99,
                 dot: bool = False, color: str = "danger", parent=None):
        super().__init__(parent)
        self._count = int(count)
        self._max = int(max_count)
        self._dot = bool(dot)
        self._show_zero = False
        self._color_role = "danger"
        self._pill = None
        self.set_color(color)
        self._child = None
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, _PILL_H // 2, self._overhang_x(), 0)
        self._layout.setSpacing(0)
        if widget is not None:
            self.set_widget(widget)
        # 角标最后创建：位于 children 末尾（绘制层级顶层）
        self._pill = _Pill(self)
        ThemeManager.instance().theme_changed.connect(self._on_theme_changed)
        self._sync_pill()

    # ------------------------------------------------------------------ 配置
    def set_widget(self, widget: QWidget) -> None:
        """设置被包裹的子控件（角标叠加在其右上角）。"""
        if self._child is not None:
            self._layout.removeWidget(self._child)
            self._child.setParent(None)
        self._child = widget
        self._layout.addWidget(widget)
        if self._pill is not None:
            # 重新挂到 children 末尾：换绑子控件后角标仍是最后（顶层）子控件
            self._pill.setParent(None)
            self._pill.setParent(self)
        self.updateGeometry()
        self._sync_pill()

    def child(self):
        """返回被包裹的子控件（可能为 None）。"""
        return self._child

    def set_count(self, count: int) -> None:
        """设置角标数字。"""
        self._count = max(0, int(count))
        self._sync_pill()

    def count(self) -> int:
        return self._count

    def set_max_count(self, max_count: int) -> None:
        """设置数字上限，超出显示 ``{max}+``。"""
        self._max = max(1, int(max_count))
        self._sync_pill()

    def max_count(self) -> int:
        return self._max

    def set_dot(self, dot: bool) -> None:
        """切换红点模式（不显示数字）。"""
        self._dot = bool(dot)
        self._sync_pill()

    def is_dot(self) -> bool:
        return self._dot

    def set_show_zero(self, show: bool) -> None:
        """数字为 0 时是否仍显示角标。"""
        self._show_zero = bool(show)
        self._sync_pill()

    def set_color(self, color: str) -> None:
        """设置角标颜色角色：danger/primary/success/warning。"""
        if color not in _COLOR_KEYS:
            raise ValueError(f"未知角标颜色: {color!r}")
        self._color_role = color
        self._sync_pill()

    # ------------------------------------------------------------------ 几何
    def _visible(self) -> bool:
        return self._dot or self._count > 0 or self._show_zero

    def _text(self) -> str:
        if self._count > self._max:
            return f"{self._max}+"
        return str(self._count)

    def _text_font(self) -> QFont:
        """角标数字的绘制字体（测量与绘制共用，保证宽度一致）。"""
        font = QFont(self.font())
        font.setPixelSize(T("font.xs"))
        return font

    def _pill_width(self) -> int:
        """角标宽度：min-width = 高度，文本超宽时横向扩展。"""
        if self._dot:
            return _DOT_D
        fm = QFontMetrics(self._text_font())
        return max(_PILL_H, fm.horizontalAdvance(self._text()) + 2 * _PAD_X)

    def _overhang_x(self) -> int:
        """角标相对子控件右缘的外溢宽度（布局右侧预留，向上取整）。"""
        return -(-max(_PILL_H, self._pill_width()) // 2)

    def sizeHint(self) -> QSize:
        if self._child is not None:
            base = self._child.sizeHint()
            return QSize(base.width() + self._overhang_x(),
                         base.height() + _PILL_H // 2)
        if self._dot:
            return QSize(_DOT_D, _DOT_D)
        return QSize(self._pill_width() + 4, _PILL_H + 4)

    def minimumSizeHint(self) -> QSize:
        return self.sizeHint()

    # ------------------------------------------------------------------ 角标同步
    def _sync_pill(self) -> None:
        """按当前状态刷新角标几何 / 可见性，并保持绘制顶层。"""
        if self._pill is None:
            return
        if not self._visible():
            self._pill.hide()
            return
        w = self._pill_width()
        h = _DOT_D if self._dot else _PILL_H
        if self._child is not None:
            # 右侧预留外溢宽度，锚定子控件右上角（角标完整落在控件边界内）
            overhang = self._overhang_x()
            margins = self._layout.contentsMargins()
            if margins.right() != overhang:
                self._layout.setContentsMargins(0, _PILL_H // 2, overhang, 0)
            cx = self.width() - overhang
            cy = _PILL_H // 2
        else:
            cx = self.width() / 2
            cy = self.height() / 2
        self._pill.setGeometry(round(cx - w / 2), round(cy - h / 2), w, h)
        self._pill.show()
        self._pill.raise_()  # 保持顶层：不被被包裹控件遮挡
        self._pill.update()

    def _on_theme_changed(self, _mode) -> None:
        self._sync_pill()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._sync_pill()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._sync_pill()
