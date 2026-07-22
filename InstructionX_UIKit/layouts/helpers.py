# -*- coding: utf-8 -*-
"""布局预设共享辅助件。

- :class:`TokenColorChip`：主题感知色块（paintEvent 实时取令牌色）；
- :func:`apply_token_font`：按令牌设置控件字阶与字重；
- :func:`empty_placeholder`：布局无内容时的优雅空占位（居中文本
  「在此放置内容」，次要令牌色）——空占位不是假数据；
- :func:`titled_card`：带标题的卡片外框，返回 ``(卡片, 内容布局)``。
"""

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QPainter
from PySide6.QtWidgets import QFrame, QLabel, QVBoxLayout, QWidget

from ..theme import T, ThemeManager

__all__ = [
    "TokenColorChip",
    "apply_token_font",
    "empty_placeholder",
    "titled_card",
]


class TokenColorChip(QWidget):
    """主题感知色块：paintEvent 实时取令牌色，主题切换自动重绘。"""

    def __init__(self, color_key="color.primary", radius_key="radius.md", parent=None):
        super().__init__(parent)
        self._color_key = color_key
        self._radius_key = radius_key
        ThemeManager.instance().theme_changed.connect(self.update)

    def paintEvent(self, event):  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(T(self._color_key)))
        radius = T(self._radius_key)
        painter.drawRoundedRect(self.rect(), radius, radius)


def apply_token_font(widget, size_key="font.md", weight_key="font.weight.regular"):
    """按令牌设置控件字阶与字重。"""
    font = QFont(widget.font())
    font.setPixelSize(T(size_key))
    font.setWeight(QFont.Weight(T(weight_key)))
    widget.setFont(font)


def empty_placeholder(text="在此放置内容", parent=None) -> QWidget:
    """构造空内容占位：单个居中文本，令牌字色，不算假数据。"""
    host = QWidget(parent)
    lay = QVBoxLayout(host)
    lay.setContentsMargins(0, 0, 0, 0)
    label = QLabel(text)
    label.setAlignment(Qt.AlignCenter)
    label.setProperty("role", "tertiary")
    apply_token_font(label, "font.title.sm", "font.weight.medium")
    lay.addWidget(label)
    return host


def titled_card(title):
    """构造带标题的卡片外框，返回 ``(卡片, 内容布局)``。"""
    card = QFrame()
    card.setFrameShape(QFrame.StyledPanel)
    lay = QVBoxLayout(card)
    lay.setContentsMargins(T("space.4"), T("space.3"), T("space.4"), T("space.3"))
    lay.setSpacing(T("space.2"))
    head = QLabel(title)
    apply_token_font(head, "font.sm", "font.weight.semibold")
    head.setProperty("role", "tertiary")
    lay.addWidget(head)
    return card, lay
