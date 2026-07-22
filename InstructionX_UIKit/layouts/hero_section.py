# -*- coding: utf-8 -*-
"""英雄区布局预设（SPEC §6）。

落地页首屏：左侧为大标题 + 副文案 + 双按钮（主 / 次），
右侧为自绘插图占位（主题感知几何图形，纯装饰、非假数据）。

**API 驱动，无内置假数据**：所有文案与按钮文本均由调用方传入；
留空的部分自动隐藏（按钮文本为空则不创建该按钮）。

响应式（resizeEvent 中按 SPEC §2.6 断点处理）：

- ``md`` 及以上：左右并排，插图居右；
- ``xs`` / ``sm``：切换为上下堆叠，插图移到文案下方。

示例::

    from InstructionX_UIKit.layouts.hero_section import create_hero_section
    win = create_hero_section(
        kicker="My App",
        title="用令牌与断点\\n搭建响应式界面",
        subtitle="颜色、间距、圆角全部取自设计令牌。",
        primary_text="开始使用",
        secondary_text="查看文档",
    )
    win.show()
"""

from PySide6.QtGui import QColor, QPainter
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..theme import T, ThemeManager, set_property
from ..tokens import Breakpoint
from .helpers import apply_token_font

__all__ = ["HeroSection", "create_hero_section"]


class HeroIllustration(QWidget):
    """主题感知插图占位：自绘圆角底板 + 圆形 + 短条，paintEvent 实时取色。

    纯装饰性空占位图形（不含任何数据），可直接作为英雄区右侧默认插图。
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(T("space.16") * 3, T("space.16") * 3)
        ThemeManager.instance().theme_changed.connect(self.update)

    def paintEvent(self, event):  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(Qt.NoPen)
        rect = self.rect()
        margin = T("space.2")
        base = rect.adjusted(margin, margin, -margin, -margin)

        # 底板：primary.subtle 大圆角矩形
        painter.setBrush(QColor(T("color.primary.subtle")))
        painter.drawRoundedRect(base, T("radius.xl"), T("radius.xl"))

        # 圆形：primary 主色，叠在底板右上
        side = min(base.width(), base.height()) // 2
        painter.setBrush(QColor(T("color.primary")))
        painter.drawEllipse(base.center().x(), base.top() + T("space.4"), side, side)

        # 短条两根：success / warning，装饰几何元素
        bar_w = max(T("space.6"), base.width() // 4)
        bar_h = T("space.4")
        left = base.left() + T("space.6")
        bottom = base.bottom() - T("space.6")
        painter.setBrush(QColor(T("color.success")))
        painter.drawRoundedRect(left, bottom - bar_h * 2 - T("space.2"),
                                bar_w, bar_h, T("radius.sm"), T("radius.sm"))
        painter.setBrush(QColor(T("color.warning")))
        painter.drawRoundedRect(left, bottom - bar_h,
                                int(bar_w * 1.6), bar_h, T("radius.sm"), T("radius.sm"))


class HeroSection(QWidget):
    """英雄区：大标题 + 副文案 + 双按钮 + 右侧插图占位。

    参数:
        kicker: 顶部小字（留空隐藏）。
        title: 大标题（留空隐藏）。
        subtitle: 副文案（留空隐藏）。
        primary_text: 主按钮文本（留空则不创建主按钮）。
        secondary_text: 次按钮文本（留空则不创建次按钮）。
        hint: 底部提示小字（留空隐藏）。
        illustration: 右侧插图控件；``None`` 时使用默认的
            :class:`HeroIllustration` 装饰占位图。
        parent: 父控件。

    ``resizeEvent`` 中按断点在「左右并排」与「上下堆叠」之间切换
    （通过 ``QBoxLayout.setDirection`` 实现，无需重建控件）。
    主 / 次按钮分别保存为 ``primary_button`` / ``secondary_button``
    属性，供调用方连接信号。
    """

    def __init__(self, kicker="", title="", subtitle="",
                 primary_text="", secondary_text="", hint="",
                 illustration=None, parent=None):
        super().__init__(parent)
        self._bp = ""
        self.primary_button = None
        self.secondary_button = None
        root = QVBoxLayout(self)
        root.setContentsMargins(T("space.6"), T("space.6"), T("space.6"), T("space.6"))

        self._hero = QBoxLayout(QBoxLayout.LeftToRight)
        self._hero.setSpacing(T("space.8"))
        self._hero.addLayout(
            self._build_text(kicker, title, subtitle,
                             primary_text, secondary_text, hint), 3)
        self._hero.addWidget(
            illustration if illustration is not None else HeroIllustration(), 2)
        root.addLayout(self._hero, 1)
        # 初始按宽屏断点构建，首次 resize 时再按实际宽度修正
        self._sync("lg")

    # -- 文案列 ----------------------------------------------------------
    def _build_text(self, kicker, title, subtitle,
                    primary_text, secondary_text, hint):
        lay = QVBoxLayout()
        lay.setSpacing(T("space.4"))

        if kicker:
            kicker_label = QLabel(kicker)
            kicker_label.setProperty("role", "tertiary")
            apply_token_font(kicker_label, "font.sm", "font.weight.medium")
            lay.addWidget(kicker_label)

        if title:
            title_label = QLabel(title)
            apply_token_font(title_label, "font.hero", "font.weight.bold")
            lay.addWidget(title_label)

        if subtitle:
            subtitle_label = QLabel(subtitle)
            subtitle_label.setProperty("role", "secondary")
            subtitle_label.setWordWrap(True)
            lay.addWidget(subtitle_label)

        if primary_text or secondary_text:
            actions = QHBoxLayout()
            actions.setSpacing(T("space.3"))
            if primary_text:
                self.primary_button = QPushButton(primary_text)
                set_property(self.primary_button, "variant", "primary")
                set_property(self.primary_button, "size", "lg")
                actions.addWidget(self.primary_button)
            if secondary_text:
                self.secondary_button = QPushButton(secondary_text)
                set_property(self.secondary_button, "variant", "default")
                set_property(self.secondary_button, "size", "lg")
                actions.addWidget(self.secondary_button)
            actions.addStretch(1)
            lay.addLayout(actions)

        if hint:
            hint_label = QLabel(hint)
            hint_label.setProperty("role", "tertiary")
            apply_token_font(hint_label, "font.sm")
            lay.addWidget(hint_label)
        lay.addStretch(1)
        return lay

    # -- 响应式 ----------------------------------------------------------
    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._sync(Breakpoint.from_width(self.width()))

    def _sync(self, bp):
        """按断点切换英雄区方向：md 及以上左右，xs/sm 上下。"""
        if bp == self._bp:
            return
        self._bp = bp
        if bp in ("md", "lg", "xl"):
            self._hero.setDirection(QBoxLayout.LeftToRight)
        else:
            self._hero.setDirection(QBoxLayout.TopToBottom)


def create_hero_section(kicker="", title="", subtitle="",
                        primary_text="", secondary_text="", hint="",
                        illustration=None, parent=None) -> QWidget:
    """创建英雄区布局部件（文案与按钮文本均由调用方传入）。"""
    return HeroSection(kicker=kicker, title=title, subtitle=subtitle,
                       primary_text=primary_text, secondary_text=secondary_text,
                       hint=hint, illustration=illustration, parent=parent)
