# -*- coding: utf-8 -*-
"""分栏面板布局预设（SPEC §6）。

三栏 ``QSplitter``（导航 / 列表 / 内容），栏宽可拖拽调整，并「记忆比例」：
用户拖动分栏后，窗口尺寸再变化时仍按用户调整后的比例分配宽度。

**API 驱动，无内置假数据**：导航项、列表条目与内容区均由调用方传入；
列表为空时不预填任何示例行，内容区未设置时显示优雅的空占位
（「在此放置内容」）。

响应式（resizeEvent 中按 SPEC §2.6 断点处理）：

- ``md`` 及以上：三栏并排；
- ``sm``：隐藏导航栏，保留列表 + 内容两栏；
- ``xs``：仅保留内容栏。

示例::

    from InstructionX_UIKit.layouts.split_panel import create_split_panel
    win = create_split_panel(
        nav_items=["工作台", "项目", "设置"],
        list_items=["季度总结", "里程碑计划"],
        content=my_widget,
    )
    win.show()
"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QLabel,
    QListWidget,
    QSplitter,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ..theme import T
from ..tokens import Breakpoint
from .helpers import apply_token_font, empty_placeholder

__all__ = ["SplitPanel", "create_split_panel"]


class SplitPanel(QWidget):
    """分栏面板：QSplitter 三栏，拖拽调宽并记忆比例。

    参数:
        nav_items: 左栏导航项文本列表（可选项组，首项默认选中）；
            按钮保存在 ``nav_buttons`` 属性中供连接信号。
        list_items: 中栏列表条目文本列表（空列表则不预填任何行）。
        content: 右栏内容区控件；``None`` 时显示空占位。
        parent: 父控件。

    ``splitterMoved`` 时记录各栏比例；``resizeEvent`` 中按记忆比例
    重新分配，同时按断点决定栏数（sm 两栏、xs 单栏）。运行期可用
    :meth:`set_content` 更换内容区。
    """

    def __init__(self, nav_items=(), list_items=(), content=None, parent=None):
        super().__init__(parent)
        self._bp = ""
        self._ratios = [0.2, 0.3, 0.5]  # 初始栏宽比例（用户拖拽后更新）
        root = QVBoxLayout(self)
        root.setContentsMargins(T("space.4"), T("space.4"), T("space.4"), T("space.4"))
        root.setSpacing(0)

        self._splitter = QSplitter(Qt.Horizontal)
        self._panes = [
            self._build_nav(nav_items),
            self._build_list(list_items),
            self._build_content(),
        ]
        for pane in self._panes:
            self._splitter.addWidget(pane)
        self._splitter.setCollapsible(1, False)
        self._splitter.splitterMoved.connect(self._remember)
        root.addWidget(self._splitter, 1)
        self.set_content(content)
        # 目标可见性（自行跟踪：窗口未 show 时 isVisible() 恒为 False，不可依赖）
        self._visible = [True, True, True]
        # 初始按宽屏断点构建，首次 resize 时再按实际宽度修正
        self._sync("lg")

    # -- 三栏 ------------------------------------------------------------
    def _build_nav(self, nav_items):
        pane = QFrame()
        pane.setFrameShape(QFrame.StyledPanel)
        lay = QVBoxLayout(pane)
        lay.setContentsMargins(T("space.2"), T("space.3"), T("space.2"), T("space.3"))
        lay.setSpacing(T("space.1"))
        if nav_items:
            head = QLabel("导航")
            apply_token_font(head, "font.sm", "font.weight.semibold")
            head.setProperty("role", "tertiary")
            lay.addWidget(head)
        self.nav_buttons = []
        first = None
        for name in nav_items:
            btn = QToolButton()
            btn.setText(name)
            btn.setCheckable(True)
            btn.setAutoExclusive(True)
            lay.addWidget(btn)
            self.nav_buttons.append(btn)
            if first is None:
                first = btn
        if first is not None:
            first.setChecked(True)
        lay.addStretch(1)
        return pane

    def _build_list(self, list_items):
        pane = QFrame()
        pane.setFrameShape(QFrame.StyledPanel)
        lay = QVBoxLayout(pane)
        lay.setContentsMargins(T("space.3"), T("space.3"), T("space.3"), T("space.3"))
        lay.setSpacing(T("space.2"))
        if list_items:
            head = QLabel("条目列表")
            apply_token_font(head, "font.sm", "font.weight.semibold")
            head.setProperty("role", "tertiary")
            lay.addWidget(head)
        self.list_widget = QListWidget()
        if list_items:
            self.list_widget.addItems(list_items)
            self.list_widget.setCurrentRow(0)
        lay.addWidget(self.list_widget, 1)
        return pane

    def _build_content(self):
        pane = QFrame()
        pane.setFrameShape(QFrame.StyledPanel)
        lay = QVBoxLayout(pane)
        lay.setContentsMargins(T("space.5"), T("space.5"), T("space.5"), T("space.5"))
        lay.setSpacing(T("space.3"))
        return pane

    def set_content(self, widget):
        """设置右栏内容区控件；``None`` 时显示空占位。"""
        lay = self._panes[2].layout()
        while lay.count():
            item = lay.takeAt(0)
            old = item.widget()
            if old is not None:
                old.hide()
                old.setParent(None)
        if widget is None:
            widget = empty_placeholder()
        lay.addWidget(widget, 1)

    # -- 比例记忆 --------------------------------------------------------
    def _remember(self, *_args):
        """拖拽手柄后记录当前各栏宽度比例。"""
        sizes = self._splitter.sizes()
        total = sum(sizes)
        if total > 0 and all(size > 0 for size in sizes):
            self._ratios = [size / total for size in sizes]

    def _apply_sizes(self):
        """按记忆比例把当前分栏宽度分配给可见栏。"""
        visible = [i for i, vis in enumerate(self._visible) if vis]
        width = max(self._splitter.width(), T("space.16") * 4)
        # 可见栏按原比例归一化后分配
        weight = sum(self._ratios[i] for i in visible) or 1.0
        sizes = []
        for i in range(len(self._panes)):
            if i in visible:
                sizes.append(int(width * self._ratios[i] / weight))
            else:
                sizes.append(0)
        self._splitter.setSizes(sizes)

    # -- 响应式 ----------------------------------------------------------
    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._sync(Breakpoint.from_width(self.width()))
        self._apply_sizes()

    def _sync(self, bp):
        """按断点设置栏数：md 及以上三栏，sm 两栏，xs 单栏。"""
        if bp == self._bp:
            return
        self._bp = bp
        self._visible = [bp in ("md", "lg", "xl"), bp in ("sm", "md", "lg", "xl"), True]
        for pane, vis in zip(self._panes, self._visible):
            pane.setVisible(vis)
        self._apply_sizes()


def create_split_panel(nav_items=(), list_items=(), content=None, parent=None) -> QWidget:
    """创建分栏面板布局部件。

    参数:
        nav_items: 左栏导航项文本列表。
        list_items: 中栏列表条目文本列表。
        content: 右栏内容区控件；不传时显示空占位。
        parent: 父控件，默认 ``None``（作为独立窗口使用）。
    """
    return SplitPanel(nav_items=nav_items, list_items=list_items,
                      content=content, parent=parent)
