# -*- coding: utf-8 -*-
"""标签页组件 Tabs（SPEC §5.3 tabs.py）。

基于 QTabWidget 子类化，``line`` 样式直接复用全局 QSS（SPEC §4），
``card`` / ``segmented`` 通过局部 QSS 按当前主题令牌生成，
主题切换时自动重载。
"""

from PySide6.QtWidgets import QTabWidget, QWidget

from ..theme import T, ThemeManager, set_property
from shiboken6 import isValid as _shiboken_is_valid


def _connect_theme(widget, slot) -> None:
    """连接主题切换信号；控件销毁后自动忽略回调。"""
    ThemeManager.instance().theme_changed.connect(
        lambda *_: slot() if _shiboken_is_valid(widget) else None)

__all__ = ["Tabs"]


class Tabs(QTabWidget):
    """标签页容器，支持 line / card / segmented 三种样式。

    用途：在同一区域内切换多组内容页。

    参数:
        variant: 样式变体，``"line"``（下划线，默认）、``"card"``（卡片式）
            或 ``"segmented"``（分段控制器风格）。
        parent: 父控件。

    示例::

        tabs = Tabs(variant="card")
        tabs.addTab(QWidget(), "概览")
        tabs.set_variant("segmented")
    """

    #: 合法样式变体
    VARIANTS = ("line", "card", "segmented")

    def __init__(self, variant: str = "line", parent: QWidget = None):
        super().__init__(parent)
        self._variant = "line"
        _connect_theme(self, self._reload_style)
        self.set_variant(variant)

    # -- 公开 API ---------------------------------------------------------
    def set_variant(self, variant: str) -> None:
        """设置样式变体：``line`` / ``card`` / ``segmented``。"""
        if variant not in self.VARIANTS:
            raise ValueError(
                f"未知 Tabs 变体: {variant!r}，应为 {self.VARIANTS} 之一")
        self._variant = variant
        set_property(self, "variant", variant)
        self._reload_style()

    def variant(self) -> str:
        """返回当前样式变体。"""
        return self._variant

    # -- 内部 -------------------------------------------------------------
    def _reload_style(self) -> None:
        """按当前主题令牌重建局部 QSS（line 交给全局 QSS）。"""
        if self._variant == "line":
            self.setStyleSheet("")
            return
        c = lambda k: T(f"color.{k}")  # noqa: E731
        r_md, r_sm = T("radius.md"), T("radius.sm")
        if self._variant == "card":
            qss = f"""
QTabWidget::pane {{
    border: 1px solid {c('border')};
    border-radius: {r_md}px;
    background-color: {c('bg.base')};
    top: -1px;
}}
QTabBar::tab {{
    background-color: {c('bg.muted')};
    color: {c('text.secondary')};
    border: 1px solid {c('border')};
    border-bottom: none;
    border-top-left-radius: {r_md}px;
    border-top-right-radius: {r_md}px;
    padding: 7px 16px;
    margin-right: 4px;
}}
QTabBar::tab:hover {{ color: {c('text.primary')}; }}
QTabBar::tab:selected {{
    background-color: {c('bg.base')};
    color: {c('primary')};
}}
QTabBar::tab:disabled {{ color: {c('text.disabled')}; }}
"""
        else:  # segmented
            qss = f"""
QTabWidget::pane {{
    border: none;
    border-top: 1px solid {c('border')};
    background-color: {c('bg.base')};
}}
QTabBar {{
    background-color: {c('bg.muted')};
    border-radius: {r_md}px;
    padding: 2px;
}}
QTabBar::tab {{
    background-color: transparent;
    border: none;
    color: {c('text.secondary')};
    padding: 5px 16px;
    border-radius: {r_sm}px;
    margin: 1px;
}}
QTabBar::tab:hover {{ color: {c('text.primary')}; }}
QTabBar::tab:selected {{
    background-color: {c('bg.elevated')};
    color: {c('primary')};
    font-weight: 600;
}}
QTabBar::tab:disabled {{ color: {c('text.disabled')}; }}
"""
        self.setStyleSheet(qss)
