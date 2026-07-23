# -*- coding: utf-8 -*-
"""单列堆叠布局预设（SPEC §6）。

文章内容型单列：主体最大宽度 760px 并水平居中，区块之间按
``space`` 令牌保持统一的垂直节奏（space.4 段落、space.6 区块）。
窗口宽于 760px 时两侧留白，窄于 760px 时内容随窗口收缩。
整体置于 ``QScrollArea`` 内，窄窗口可滚动阅读。

**API 驱动，无内置假数据**：标题、副标题、封面、段落、引用与操作
按钮均由调用方传入；全部留空时显示优雅的空占位（「在此放置内容」）。

示例::

    from InstructionX_UIKit.layouts.single_column import create_single_column
    win = create_single_column(
        title="用统一的垂直节奏组织长文内容",
        subtitle="单列布局将阅读动线收敛到一条中轴。",
        paragraphs=["第一段……", "第二段……"],
        quote="好的布局不喧哗。",
        actions=[("阅读全文", "primary"), ("收藏", "default")],
    )
    win.show()
"""

from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ..theme import T, set_property
from ..tokens import Breakpoint
from .helpers import TokenColorChip, apply_token_font, empty_placeholder

__all__ = ["SingleColumn", "create_single_column"]

#: 单列内容最大宽度（SPEC §6：760px）
_MAX_CONTENT_WIDTH = 760


def _paragraph(text):
    """构造正文段落标签（次要色、自动换行）。"""
    label = QLabel(text)
    label.setProperty("role", "secondary")
    label.setWordWrap(True)
    return label


class SingleColumn(QWidget):
    """单列堆叠布局：最大宽 760 居中，垂直节奏取 space 令牌。

    参数:
        kicker: 顶部小字（留空隐藏）。
        title: 大标题（留空隐藏）。
        subtitle: 副标题（留空隐藏）。
        cover_key: 封面色块的令牌色键；``None`` 则不显示封面。
        paragraphs: 正文段落文本列表。
        quote: 引用卡片文本（留空则不显示引用卡片）。
        actions: 结尾操作按钮，每项为 ``(文本, variant)``；按钮保存在
            ``action_buttons`` 属性中供连接信号。
        parent: 父控件。

    全部内容留空时显示空占位。内容窄于最大宽时水平居中，超出时
    自然收缩。
    """

    def __init__(self, kicker="", title="", subtitle="",
                 cover_key=None, paragraphs=(), quote="",
                 actions=(), parent=None):
        super().__init__(parent)
        self.action_buttons = []
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        root.addWidget(scroll)

        host = QWidget()
        self._center = QHBoxLayout(host)
        self._center.addStretch(1)
        self._center.addWidget(self._build_column(
            kicker, title, subtitle, cover_key, paragraphs, quote, actions))
        self._center.addStretch(1)
        scroll.setWidget(host)
        self._bp = ""
        # 初始按宽屏断点设置页边距，首次 resize 时再按实际宽度修正
        self._sync("lg")

    # -- 响应式 ----------------------------------------------------------
    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._sync(Breakpoint.from_width(self.width()))

    def _sync(self, bp):
        """按断点调整外边距：宽屏 space.6，中屏 space.4，窄屏 space.2。"""
        if bp == self._bp:
            return
        self._bp = bp
        if bp in ("lg", "xl"):
            margin = T("space.6")
        elif bp == "md":
            margin = T("space.4")
        else:
            margin = T("space.2")
        self._center.setContentsMargins(margin, margin, margin, margin)

    # -- 单列主体 --------------------------------------------------------
    def _build_column(self, kicker, title, subtitle,
                      cover_key, paragraphs, quote, actions):
        column = QFrame()
        column.setFrameShape(QFrame.NoFrame)
        column.setMaximumWidth(_MAX_CONTENT_WIDTH)
        lay = QVBoxLayout(column)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(T("space.4"))

        has_content = any((kicker, title, subtitle, cover_key,
                           paragraphs, quote, actions))
        if not has_content:
            lay.addWidget(empty_placeholder(), 1)
            return column

        if kicker:
            kicker_label = QLabel(kicker)
            kicker_label.setProperty("role", "tertiary")
            apply_token_font(kicker_label, "font.sm", "font.weight.medium")
            lay.addWidget(kicker_label)

        if title:
            title_label = QLabel(title)
            apply_token_font(title_label, "font.display", "font.weight.bold")
            title_label.setWordWrap(True)
            lay.addWidget(title_label)

        if subtitle:
            subtitle_label = QLabel(subtitle)
            subtitle_label.setProperty("role", "secondary")
            subtitle_label.setWordWrap(True)
            lay.addWidget(subtitle_label)

        if title or subtitle:
            divider = QFrame()
            divider.setFrameShape(QFrame.HLine)
            lay.addWidget(divider)

        if cover_key:
            cover = TokenColorChip(cover_key, "radius.lg")
            cover.setFixedHeight(T("space.16") * 3)
            lay.addWidget(cover)
            lay.addSpacing(T("space.2"))

        for text in paragraphs:
            lay.addWidget(_paragraph(text))

        if quote:
            quote_card = QFrame()
            quote_card.setFrameShape(QFrame.StyledPanel)
            quote_lay = QVBoxLayout(quote_card)
            quote_lay.setContentsMargins(T("space.4"), T("space.4"),
                                         T("space.4"), T("space.4"))
            quote_text = QLabel(quote)
            apply_token_font(quote_text, "font.title.sm", "font.weight.medium")
            quote_text.setWordWrap(True)
            quote_lay.addWidget(quote_text)
            lay.addSpacing(T("space.2"))
            lay.addWidget(quote_card)
            lay.addSpacing(T("space.2"))

        if actions:
            action_row = QHBoxLayout()
            action_row.setSpacing(T("space.3"))
            for text, variant in actions:
                btn = QPushButton(text)
                set_property(btn, "variant", variant)
                action_row.addWidget(btn)
                self.action_buttons.append(btn)
            action_row.addStretch(1)
            lay.addSpacing(T("space.2"))
            lay.addLayout(action_row)
        lay.addStretch(1)
        return column


def create_single_column(kicker="", title="", subtitle="",
                         cover_key=None, paragraphs=(), quote="",
                         actions=(), parent=None) -> QWidget:
    """创建单列堆叠布局部件（内容全部由调用方传入）。"""
    return SingleColumn(kicker=kicker, title=title, subtitle=subtitle,
                        cover_key=cover_key, paragraphs=paragraphs,
                        quote=quote, actions=actions, parent=parent)
