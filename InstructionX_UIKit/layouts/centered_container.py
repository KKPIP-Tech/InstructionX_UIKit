# -*- coding: utf-8 -*-
"""居中容器布局预设（SPEC §6）。

内容限宽 960px 并在窗口中水平居中：宽屏下两侧留白，窄于 960px
时内容随窗口收缩。适合表单页、结果页、设置页等「一条中轴」场景。

**API 驱动，无内置假数据**：页头（标题 / 副标题 / 操作按钮）、卡片
与底部提示均由调用方传入；卡片为空时显示优雅的空占位
（「在此放置内容」）。

响应式（resizeEvent 中按 SPEC §2.6 断点处理）：

- ``md`` 及以上：内容卡片 3 列；
- ``sm``：2 列；
- ``xs``：1 列。

示例::

    from InstructionX_UIKit.layouts.centered_container import create_centered_container
    win = create_centered_container(
        title="账号设置",
        subtitle="内容限宽 960px。",
        actions=[("保存修改", "primary"), ("取消", "default")],
        cards=[("个人资料", "头像、昵称与签名。", "color.primary")],
    )
    win.show()
"""

from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..theme import T, set_property
from ..tokens import Breakpoint
from .helpers import TokenColorChip, apply_token_font, empty_placeholder

__all__ = ["CenteredContainer", "create_centered_container"]

#: 内容最大宽度（SPEC §6：960px）
_MAX_CONTENT_WIDTH = 960

#: 内容卡片各断点列数
_COLUMNS = {"xs": 1, "sm": 2, "md": 3, "lg": 3, "xl": 3}


def _mini_card(title, desc, chip_key):
    """构造内容小卡片：色块条 + 标题 + 描述。"""
    card = QFrame()
    card.setFrameShape(QFrame.StyledPanel)
    lay = QVBoxLayout(card)
    lay.setContentsMargins(T("space.4"), T("space.3"), T("space.4"), T("space.3"))
    lay.setSpacing(T("space.2"))
    chip = TokenColorChip(chip_key, "radius.sm")
    chip.setFixedHeight(T("space.2"))
    lay.addWidget(chip)
    head = QLabel(title)
    apply_token_font(head, "font.title.sm", "font.weight.semibold")
    lay.addWidget(head)
    body = QLabel(desc)
    body.setProperty("role", "secondary")
    body.setWordWrap(True)
    lay.addWidget(body)
    return card


class CenteredContainer(QWidget):
    """居中容器：内容限宽 960 水平居中。

    参数:
        title: 页头主标题（留空则整行页头隐藏）。
        subtitle: 页头副标题（留空隐藏）。
        actions: 页头右侧操作按钮，每项为 ``(文本, variant)``；按钮
            保存在 ``action_buttons`` 属性中供连接信号。
        cards: 内容卡片列表，每项为 ``(标题, 描述, 色块令牌键)`` 或
            ``QWidget``；空时显示空占位。
        note: 底部提示文本（留空则不显示提示条）。
        parent: 父控件。

    ``resizeEvent`` 中按断点调整内容卡片列数（3/2/1）。
    """

    def __init__(self, title="", subtitle="", actions=(),
                 cards=None, note="", parent=None):
        super().__init__(parent)
        self._cols = 0
        self.action_buttons = []
        self._title = title
        self._subtitle = subtitle
        self._actions = tuple(actions)
        self._cards = [
            item if isinstance(item, QWidget) else _mini_card(*item)
            for item in (cards or [])
        ]
        self._note = note
        root = QHBoxLayout(self)
        root.setContentsMargins(T("space.4"), T("space.6"), T("space.4"), T("space.6"))
        root.addStretch(1)
        root.addWidget(self._build_container())
        root.addStretch(1)
        # 初始按宽屏列数摆放，首次 resize 时再按实际宽度修正
        self._relayout(_COLUMNS["lg"])

    # -- 容器主体 --------------------------------------------------------
    def _build_container(self):
        container = QWidget()
        container.setMaximumWidth(_MAX_CONTENT_WIDTH)
        lay = QVBoxLayout(container)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(T("space.4"))

        if self._title or self._subtitle or self._actions:
            header = QHBoxLayout()
            header.setSpacing(T("space.3"))
            title_box = QVBoxLayout()
            title_box.setSpacing(T("space.1"))
            if self._title:
                title = QLabel(self._title)
                apply_token_font(title, "font.title.lg", "font.weight.semibold")
                title_box.addWidget(title)
            if self._subtitle:
                subtitle = QLabel(self._subtitle)
                subtitle.setProperty("role", "secondary")
                subtitle.setWordWrap(True)
                title_box.addWidget(subtitle)
            header.addLayout(title_box, 1)
            for text, variant in self._actions:
                btn = QPushButton(text)
                set_property(btn, "variant", variant)
                header.addWidget(btn)
                self.action_buttons.append(btn)
            lay.addLayout(header)

        self._grid = QGridLayout()
        self._grid.setSpacing(T("space.4"))
        lay.addLayout(self._grid)
        self._placeholder = empty_placeholder()

        if self._note:
            note = QFrame()
            note.setFrameShape(QFrame.StyledPanel)
            note_lay = QVBoxLayout(note)
            note_lay.setContentsMargins(T("space.4"), T("space.3"),
                                        T("space.4"), T("space.3"))
            text = QLabel(self._note)
            text.setProperty("role", "secondary")
            text.setWordWrap(True)
            note_lay.addWidget(text)
            lay.addWidget(note)
        lay.addStretch(1)
        return container

    # -- 响应式 ----------------------------------------------------------
    def resizeEvent(self, event):
        super().resizeEvent(event)
        cols = _COLUMNS[Breakpoint.from_width(self.width())]
        if cols != self._cols:
            self._relayout(cols)

    def _relayout(self, cols):
        """按列数重排内容卡片（控件保持父子关系，仅改变网格位置）。"""
        self._cols = cols
        while self._grid.count():
            self._grid.takeAt(0)
        if self._cards:
            self._placeholder.hide()
            for i, card in enumerate(self._cards):
                self._grid.addWidget(card, i // cols, i % cols)
        else:
            self._grid.addWidget(self._placeholder, 0, 0, 1, cols)
            self._placeholder.show()
        for c in range(_COLUMNS["lg"]):
            self._grid.setColumnStretch(c, 1 if c < cols else 0)


def create_centered_container(title="", subtitle="", actions=(),
                              cards=None, note="", parent=None) -> QWidget:
    """创建居中容器布局部件（内容全部由调用方传入）。"""
    return CenteredContainer(title=title, subtitle=subtitle, actions=actions,
                             cards=cards, note=note, parent=parent)
