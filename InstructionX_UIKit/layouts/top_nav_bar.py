# -*- coding: utf-8 -*-
"""顶部导航栏布局预设（SPEC §6）。

窗口级结构：顶部导航栏（Logo + 菜单 + 搜索框 + 头像）+ 下方内容区。
响应式（按 SPEC §2.6 断点，在 resizeEvent 中处理）：

- ``md`` 及以上：显示完整菜单项与搜索框；
- ``sm``：保留菜单项，隐藏搜索框；
- ``xs``：菜单折叠为单个「菜单」按钮，同时隐藏搜索框。

**API 驱动，无内置假数据**：品牌名、菜单项、搜索提示、头像文本与
内容卡片均由调用方传入；内容区为空时显示优雅的空占位
（「在此放置内容」）。颜色经全局 QSS 动态属性表达，自绘色块在
paintEvent 中实时取 ``T()`` 令牌色，亮 / 暗主题自动跟随。

示例::

    from InstructionX_UIKit.layouts.top_nav_bar import create_top_nav_bar
    win = create_top_nav_bar(
        brand="控制台",
        menu_items=["首页", "产品", "文档"],
        search_placeholder="搜索文档、组件...",
        cards=[("功能模块一", "模块说明。", "color.primary.subtle")],
    )
    win.show()
"""

from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ..theme import T, set_property
from ..tokens import Breakpoint
from .helpers import TokenColorChip, apply_token_font, empty_placeholder

__all__ = ["TopNavBar", "create_top_nav_bar"]


def _content_card(title, desc, chip_key="color.primary.subtle"):
    """构造内容卡片：色块 + 标题 + 描述（颜色全部主题感知）。"""
    card = QFrame()
    card.setFrameShape(QFrame.StyledPanel)
    lay = QVBoxLayout(card)
    lay.setContentsMargins(T("space.4"), T("space.4"), T("space.4"), T("space.4"))
    lay.setSpacing(T("space.2"))
    chip = TokenColorChip(chip_key, "radius.md")
    chip.setMinimumHeight(T("space.16") + T("space.2"))
    chip.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)
    lay.addWidget(chip)
    head = QLabel(title)
    apply_token_font(head, "font.title.sm", "font.weight.semibold")
    lay.addWidget(head)
    body = QLabel(desc)
    body.setProperty("role", "secondary")
    body.setWordWrap(True)
    lay.addWidget(body)
    return card


class TopNavBar(QWidget):
    """顶部导航栏窗口级布局。

    参数:
        brand: 顶栏品牌名（Logo 色块旁；留空隐藏）。
        menu_items: 顶栏菜单项文本列表；按钮保存在 ``menu_buttons``
            属性中供连接信号。
        search_placeholder: 搜索框占位文本；留空则不创建搜索框。
        user_text: 圆形头像按钮文本（留空则不创建）；按钮保存在
            ``user_button`` 属性中。
        title: 内容区主标题（留空隐藏）。
        subtitle: 内容区副标题（留空隐藏）。
        cards: 内容区卡片列表，每项为 ``(标题, 描述, 色块令牌键)`` 或
            ``QWidget``；空时内容区显示空占位。
        parent: 父控件。

    ``resizeEvent`` 中按 ``Breakpoint.from_width`` 切换顶栏的菜单 /
    搜索可见性与内容卡片区列数。
    """

    def __init__(self, brand="", menu_items=(), search_placeholder="",
                 user_text="", title="", subtitle="", cards=None, parent=None):
        super().__init__(parent)
        self._bp = ""
        self.user_button = None
        root = QVBoxLayout(self)
        root.setContentsMargins(T("space.4"), T("space.4"), T("space.4"), T("space.4"))
        root.setSpacing(T("space.4"))
        root.addWidget(self._build_bar(brand, menu_items,
                                       search_placeholder, user_text))
        root.addLayout(self._build_body(title, subtitle, cards), 1)
        # 初始按宽屏断点构建，首次 resize 时再按实际宽度修正
        self._sync("lg")

    # -- 顶栏 ------------------------------------------------------------
    def _build_bar(self, brand, menu_items, search_placeholder, user_text):
        bar = QFrame()
        bar.setFrameShape(QFrame.StyledPanel)
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(T("space.4"), T("space.2"), T("space.4"), T("space.2"))
        lay.setSpacing(T("space.3"))

        logo_chip = TokenColorChip("color.primary", "radius.md")
        logo_chip.setFixedSize(T("space.6"), T("space.6"))
        lay.addWidget(logo_chip)
        if brand:
            logo = QLabel(brand)
            apply_token_font(logo, "font.title.sm", "font.weight.bold")
            lay.addWidget(logo)
        lay.addSpacing(T("space.4"))

        self.menu_buttons = []
        for name in menu_items:
            btn = QPushButton(name)
            set_property(btn, "variant", "text")
            self.menu_buttons.append(btn)
            lay.addWidget(btn)
        self._menu_more = QPushButton("菜单")
        set_property(self._menu_more, "variant", "default")
        lay.addWidget(self._menu_more)

        lay.addStretch(1)
        self._search = None
        if search_placeholder:
            self._search = QLineEdit()
            self._search.setPlaceholderText(search_placeholder)
            # 可收缩搜索框：保证窄窗口下顶栏最小宽度足够小，xs/sm 折叠才可达
            self._search.setMinimumWidth(T("space.16"))
            self._search.setMaximumWidth(T("space.16") * 3 + T("space.6"))
            lay.addWidget(self._search)

        if user_text:
            self.user_button = QPushButton(user_text)
            set_property(self.user_button, "variant", "primary")
            set_property(self.user_button, "shape", "circle")
            self.user_button.setFixedSize(32, 32)  # 与输入控件 md 高度（32px）对齐
            lay.addWidget(self.user_button)
        return bar

    # -- 内容区 ----------------------------------------------------------
    def _build_body(self, title, subtitle, cards):
        layout = QVBoxLayout()
        layout.setSpacing(T("space.4"))
        if title:
            title_label = QLabel(title)
            apply_token_font(title_label, "font.display", "font.weight.semibold")
            layout.addWidget(title_label)
        if subtitle:
            subtitle_label = QLabel(subtitle)
            subtitle_label.setProperty("role", "secondary")
            layout.addWidget(subtitle_label)

        self._grid = QGridLayout()
        self._grid.setSpacing(T("space.4"))
        cards = list(cards or [])
        if cards:
            self._cards = [
                item if isinstance(item, QWidget) else _content_card(*item)
                for item in cards
            ]
        else:
            self._cards = [empty_placeholder()]
        layout.addLayout(self._grid, 1)
        return layout

    # -- 响应式 ----------------------------------------------------------
    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._sync(Breakpoint.from_width(self.width()))

    def _sync(self, bp):
        """按断点调整顶栏可见性与内容列数：xs 折叠菜单且卡片单列，sm 隐藏搜索框。"""
        if bp == self._bp:
            return
        self._bp = bp
        show_menu = bp in ("sm", "md", "lg", "xl")
        for btn in self.menu_buttons:
            btn.setVisible(show_menu)
        self._menu_more.setVisible(not show_menu and bool(self.menu_buttons))
        if self._search is not None:
            self._search.setVisible(bp in ("md", "lg", "xl"))
        # 内容区卡片：xs 单列，其余两列
        cols = 2 if show_menu else 1
        while self._grid.count():
            self._grid.takeAt(0)
        for i, card in enumerate(self._cards):
            self._grid.addWidget(card, i // cols, i % cols)
        self._grid.setColumnStretch(0, 1)
        self._grid.setColumnStretch(1, 1 if cols == 2 else 0)


def create_top_nav_bar(brand="", menu_items=(), search_placeholder="",
                       user_text="", title="", subtitle="", cards=None,
                       parent=None) -> QWidget:
    """创建顶部导航栏布局部件（内容全部由调用方传入）。"""
    return TopNavBar(brand=brand, menu_items=menu_items,
                     search_placeholder=search_placeholder,
                     user_text=user_text, title=title, subtitle=subtitle,
                     cards=cards, parent=parent)
