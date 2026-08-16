# -*- coding: utf-8 -*-
"""布局预设共享辅助件。

- :class:`TokenColorChip`：主题感知色块（paintEvent 实时取令牌色）；
- :func:`apply_token_font`：按令牌设置控件字阶与字重；
- :func:`empty_placeholder`：布局无内容时的优雅空占位（居中文本
  「在此放置内容」，次要令牌色）——空占位不是假数据；
- :func:`titled_card`：带标题的卡片外框，返回 ``(卡片, 内容布局)``；
- :func:`content_card`：带色块 + 标题 + 描述的内容卡片（与
  ``titled_card`` 并列的通用卡片构建器，供各布局预设复用）。
"""

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QPainter
from PySide6.QtWidgets import (
    QFrame,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ..theme import T, ThemeManager

__all__ = [
    "TokenColorChip",
    "apply_token_font",
    "empty_placeholder",
    "titled_card",
    "content_card",
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


def content_card(title, desc, chip_key="color.primary.subtle", *,
                 chip_radius_key="radius.md", chip_fixed_height=None,
                 chip_min_height=None, chip_expand=False, margins=None,
                 spacing=None, add_stretch=True):
    """构造「色块 + 标题 + 描述」内容卡片（颜色全部主题感知）。

    供各布局预设复用（与 :func:`titled_card` 并列的通用卡片构建器）。

    参数:
        title: 标题文本。
        desc: 描述文本（次要色、自动换行）。
        chip_key: 色块令牌色键，默认 ``color.primary.subtle``。
        chip_radius_key: 色块圆角令牌键，默认 ``radius.md``。
        chip_fixed_height: 色块固定高度（px）；优先于 ``chip_min_height``。
        chip_min_height: 色块最小高度（px）。
        chip_expand: True 时色块垂直弹性填充剩余空间。
        margins: 卡片内边距四元组 ``(左, 上, 右, 下)``，默认全 ``space.4``。
        spacing: 布局间距，默认 ``space.2``。
        add_stretch: True 时末尾追加弹性空间（卡片被拉伸时内容顶对齐）。
    """
    card = QFrame()
    card.setFrameShape(QFrame.StyledPanel)
    lay = QVBoxLayout(card)
    lay.setContentsMargins(*(margins or (T("space.4"),) * 4))
    lay.setSpacing(spacing if spacing is not None else T("space.2"))
    chip = TokenColorChip(chip_key, chip_radius_key)
    if chip_fixed_height is not None:
        chip.setFixedHeight(chip_fixed_height)
    elif chip_min_height is not None:
        chip.setMinimumHeight(chip_min_height)
    if chip_expand:
        chip.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)
    lay.addWidget(chip)
    head = QLabel(title)
    apply_token_font(head, "font.title.sm", "font.weight.semibold")
    lay.addWidget(head)
    body = QLabel(desc)
    body.setProperty("role", "secondary")
    body.setWordWrap(True)
    lay.addWidget(body)
    if add_stretch:
        lay.addStretch(1)
    return card
