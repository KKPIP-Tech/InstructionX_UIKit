# -*- coding: utf-8 -*-
"""图文左右布局预设（SPEC §6）。

营销 / 介绍页常见的「图左文右、图右文左」交替段落：奇数段图在左、
偶数段图在右，形成 Z 字形阅读动线。媒体为主题感知色块占位。

**API 驱动，无内置假数据**：段落内容由调用方通过 ``sections`` 传入，
每项为 ``(标题, 正文, 色块令牌键)`` 三元组；不传 ``sections`` 时
显示优雅的空占位（「在此放置内容」）。

响应式（resizeEvent 中按 SPEC §2.6 断点处理）：

- ``md`` 及以上：图文左右交替并排；
- ``xs`` / ``sm``：每段改为上下堆叠，媒体统一在上、文案在下。

整体置于 ``QScrollArea`` 内，窄窗口可滚动浏览。

示例::

    from InstructionX_UIKit.layouts.media_left_right import create_media_left_right
    win = create_media_left_right(sections=[
        ("特性一：令牌驱动", "颜色、间距、圆角全部来自设计令牌。",
         "color.primary.subtle"),
    ], link_text="了解更多")
    win.show()
"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ..theme import T, set_property
from ..tokens import Breakpoint
from .helpers import TokenColorChip, apply_token_font, empty_placeholder

__all__ = ["MediaLeftRight", "create_media_left_right"]


class MediaSection(QWidget):
    """单个图文段落：媒体块 + 文案列，支持左右交替与窄屏堆叠。

    参数:
        title: 段落标题。
        body: 段落正文。
        chip_key: 媒体色块的令牌色键。
        link_text: 文案列底部链接按钮文本（留空则不创建）；按钮保存在
            ``link_button`` 属性中供连接信号。
    """

    def __init__(self, title, body, chip_key, link_text="", parent=None):
        super().__init__(parent)
        self.link_button = None
        self._grid = QGridLayout(self)
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setHorizontalSpacing(T("space.6"))
        self._grid.setVerticalSpacing(T("space.3"))

        self._media = TokenColorChip(chip_key, "radius.lg")
        self._media.setMinimumHeight(T("space.16") * 2 + T("space.8"))
        self._text = self._build_text(title, body, link_text)
        self.set_horizontal(True)

    def _build_text(self, title, body, link_text):
        box = QFrame()
        box.setFrameShape(QFrame.NoFrame)
        lay = QVBoxLayout(box)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(T("space.2"))
        head = QLabel(title)
        apply_token_font(head, "font.title.md", "font.weight.semibold")
        lay.addWidget(head)
        para = QLabel(body)
        para.setProperty("role", "secondary")
        para.setWordWrap(True)
        lay.addWidget(para)
        if link_text:
            self.link_button = QPushButton(link_text)
            set_property(self.link_button, "variant", "link")
            self.link_button.setCursor(Qt.PointingHandCursor)
            lay.addWidget(self.link_button, 0, Qt.AlignLeft)
        lay.addStretch(1)
        return box

    def set_horizontal(self, horizontal, media_left=True):
        """重排本段：宽屏左右并排（可交替），窄屏媒体在上堆叠。"""
        while self._grid.count():
            self._grid.takeAt(0)
        if horizontal:
            media_col = 0 if media_left else 1
            self._grid.addWidget(self._media, 0, media_col)
            self._grid.addWidget(self._text, 0, 1 - media_col)
            self._grid.setColumnStretch(0, 2)
            self._grid.setColumnStretch(1, 3)
        else:
            self._grid.addWidget(self._media, 0, 0)
            self._grid.addWidget(self._text, 1, 0)
            self._grid.setColumnStretch(0, 1)
            self._grid.setColumnStretch(1, 0)


class MediaLeftRight(QWidget):
    """图文左右布局：图左文右 / 图右文左交替段落。

    参数:
        sections: 段落列表，每项为 ``(标题, 正文, 色块令牌键)`` 三元组；
            ``None`` 或空列表时显示空占位。
        link_text: 各段落文案列的链接按钮文本（留空则不创建按钮）。
        parent: 父控件。

    ``resizeEvent`` 中按断点在「左右交替」与「上下堆叠」之间切换。
    """

    def __init__(self, sections=None, link_text="", parent=None):
        super().__init__(parent)
        self._bp = ""
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        root.addWidget(scroll)

        content = QWidget()
        lay = QVBoxLayout(content)
        lay.setContentsMargins(T("space.6"), T("space.6"), T("space.6"), T("space.6"))
        lay.setSpacing(T("space.8"))
        sections = list(sections or [])
        if sections:
            self._sections = [
                MediaSection(*section, link_text=link_text) for section in sections
            ]
            for section in self._sections:
                lay.addWidget(section)
        else:
            self._sections = []
            lay.addWidget(empty_placeholder(), 1)
        lay.addStretch(1)
        scroll.setWidget(content)
        # 初始按宽屏断点构建，首次 resize 时再按实际宽度修正
        self._sync("lg")

    # -- 响应式 ----------------------------------------------------------
    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._sync(Breakpoint.from_width(self.width()))

    def _sync(self, bp):
        """按断点切换段落排布：md 及以上左右交替，xs/sm 上下堆叠。"""
        if bp == self._bp:
            return
        self._bp = bp
        horizontal = bp in ("md", "lg", "xl")
        for i, section in enumerate(self._sections):
            # 奇数段图左文右，偶数段图右文左
            section.set_horizontal(horizontal, media_left=(i % 2 == 0))


def create_media_left_right(sections=None, link_text="", parent=None) -> QWidget:
    """创建图文左右布局部件。

    参数:
        sections: 段落列表，每项为 ``(标题, 正文, 色块令牌键)``；不传时
            显示空占位。
        link_text: 各段落链接按钮文本（留空则不创建）。
        parent: 父控件，默认 ``None``（作为独立窗口使用）。
    """
    return MediaLeftRight(sections=sections, link_text=link_text, parent=parent)
