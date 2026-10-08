# -*- coding: utf-8 -*-
"""标签页组件 Tabs（SPEC §5.3 tabs.py）。

基于 QTabWidget 子类化，三种样式（``line`` / ``card`` / ``segmented``）都由
本模块的局部 QSS 按当前主题令牌生成，主题切换时自动重载。

四态约定（与 NavMenu / Breadcrumb / Pagination / Dropdown 同一套语义）：

======== ==================== ====================================
状态      文字                 指示元素
======== ==================== ====================================
常规      ``text.secondary``   无
悬停      ``text.primary``    ``line`` 追加 2px ``border.strong`` 下划线
选中      ``primary``+半粗     2px ``primary`` 指示条（位置随样式变）
禁用      ``text.disabled``    无
======== ==================== ====================================
"""

from PySide6.QtWidgets import QStackedWidget, QTabWidget, QWidget

from ..theme import T, ThemeManager, set_property
from shiboken6 import isValid as _shiboken_is_valid


def _connect_theme(widget, slot) -> None:
    """连接主题切换信号；组件销毁时断开连接（shiboken 守卫双保险）。"""
    manager = ThemeManager.instance()
    receiver = lambda *_: slot() if _shiboken_is_valid(widget) else None
    manager.theme_changed.connect(receiver)

    def _cleanup(_obj=None):
        try:
            manager.theme_changed.disconnect(receiver)
        except (RuntimeError, TypeError):
            pass

    widget.destroyed.connect(_cleanup)

__all__ = ["Tabs"]

#: QTabWidget 内部 QStackedWidget 的 objectName（Qt 内部约定）。
_STACK_NAME = "qt_tabwidget_stackedwidget"

#: 选中指示条粗细。本轨（Tabs / NavMenu / Breadcrumb / Pagination / Dropdown）
#: 的强调条一律取 2px——与全局 QSS 里 ``QTabBar::tab:top`` 的下边框同粗，
#: 不同组件之间的「选中」才读得出是同一套语言。
#: TODO(shared): 建议在 tokens.py 的 ``_LAYOUT`` 补 ``layout.indicator.w = 2``，
#:                由本轨与共享层共同引用，避免各处再写一遍魔数。
_INDICATOR_W = 2


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
    def _stack(self):
        """取内部 QStackedWidget（可能为 None，取决于 Qt 是否已创建）。"""
        return self.findChild(QStackedWidget, _STACK_NAME)

    def _sync_pane_insets(self) -> None:
        """把内容区内边距从 Qt 默认的 9px 换成 layout.* 令牌。

        QTabWidget 内部的 QStackedWidget 直接继承 QLayout 的默认边距
        9/9/9/9——奇数，违反 2px 基网格，也是「Tab 内容比其它卡片多缩进
        一截」的来源。内容面板属卡片层，故取 ``layout.card.pad_x`` /
        ``pad_top`` / ``pad_bottom``，与页面卡片的内容边距完全一致。
        """
        stack = self._stack()
        if stack is None:
            return
        lay = stack.layout()
        if lay is None:
            return
        lay.setContentsMargins(T("layout.card.pad_x"),
                                T("layout.card.pad_top"),
                                T("layout.card.pad_x"),
                                T("layout.card.pad_bottom"))

    def _reload_style(self) -> None:
        """按当前主题令牌重建局部 QSS。"""
        self._sync_pane_insets()
        c = lambda k: T(f"color.{k}")  # noqa: E731
        r_md, r_sm = T("radius.md"), T("radius.sm")
        pad_y, pad_x = T("space.2"), T("space.3")
        gap = T("space.05")
        weight = T("font.weight.semibold")
        # 四态共用的悬停 / 禁用 / 选中配色，三种样式只有「指示元素形态」
        # 不同（line=下划线、card=与面板融合、segmented=胶囊底色）
        hover = f"color: {c('text.primary')};"
        selected = f"color: {c('primary')}; font-weight: {weight};"
        disabled = f"color: {c('text.disabled')};"
        # 2px 指示条：line 变体用中性色表示悬停、primary 表示选中
        bar = f"border-bottom: {_INDICATOR_W}px solid %s;"
        line_bar_hover = bar % c("border.strong")
        line_bar_sel = bar % c("primary")

        if self._variant == "line":
            qss = f"""
QTabWidget::pane {{
    border: 1px solid {c('border')};
    border-radius: {r_md}px;
    background-color: {c('bg.base')};
    top: -1px;
}}
QTabBar {{ background-color: transparent; }}
QTabBar::tab {{
    background-color: transparent;
    color: {c('text.secondary')};
    border: none;
    padding: {pad_y}px {pad_x}px;
    margin-right: {gap}px;
    {line_bar_hover}
}}
QTabBar::tab:hover {{ {hover} }}
QTabBar::tab:selected {{ {selected} {line_bar_sel} }}
QTabBar::tab:disabled {{ {disabled} }}
"""
        elif self._variant == "card":
            qss = f"""
QTabWidget::pane {{
    border: 1px solid {c('border')};
    border-radius: {r_md}px;
    background-color: {c('bg.base')};
    top: -1px;
}}
QTabBar {{ background-color: transparent; }}
QTabBar::tab {{
    background-color: {c('bg.muted')};
    color: {c('text.secondary')};
    border: 1px solid {c('border')};
    border-bottom: none;
    border-top-left-radius: {r_md}px;
    border-top-right-radius: {r_md}px;
    padding: {pad_y}px {pad_x}px;
    margin-right: {gap}px;
}}
QTabBar::tab:hover {{ {hover} }}
QTabBar::tab:selected {{ {selected} background-color: {c('bg.base')}; }}
QTabBar::tab:disabled {{ {disabled} }}
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
    padding: {gap}px;
}}
QTabBar::tab {{
    background-color: transparent;
    border: none;
    color: {c('text.secondary')};
    padding: {T('space.1')}px {pad_x}px;
    border-radius: {r_sm}px;
    margin: {gap}px;
}}
QTabBar::tab:hover {{ {hover} }}
QTabBar::tab:selected {{
    {selected} background-color: {c('bg.elevated')};
}}
QTabBar::tab:disabled {{ {disabled} }}
"""
        self.setStyleSheet(qss)