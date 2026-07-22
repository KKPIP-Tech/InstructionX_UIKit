# -*- coding: utf-8 -*-
"""圣杯布局预设（SPEC §6）。

经典五区结构：页头 / 页脚 + 左导航侧栏 + 主内容区 + 右信息侧栏，
中间三区置于 ``QSplitter`` 中，拖拽手柄可自由调整宽度。

**API 驱动，无内置假数据**：导航项、页头标题、页脚文案与主 / 侧
内容均由调用方传入；主内容区与右侧栏未设置时显示优雅的空占位
（「在此放置内容」）。

响应式（resizeEvent 中按 SPEC §2.6 断点处理）：

- ``md`` 及以上：左右侧栏同时显示；
- ``sm``：隐藏右侧栏，保留左导航；
- ``xs``：左右侧栏均隐藏，主内容区占满。

示例::

    from InstructionX_UIKit.layouts.holy_grail import create_holy_grail
    win = create_holy_grail(
        title="控制台",
        nav_items=["概览", "分析", "设置"],
        center=my_widget,
    )
    win.show()
"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSplitter,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ..theme import T, set_property
from ..tokens import Breakpoint
from .helpers import TokenColorChip, apply_token_font, empty_placeholder

__all__ = ["HolyGrail", "create_holy_grail"]


class HolyGrail(QWidget):
    """圣杯布局：页头 / 页脚 / 双侧栏 / 主区，中间以 QSplitter 可调。

    参数:
        title: 页头标题（Logo 色块旁）。
        nav_items: 左导航项文本列表（可选项组，首项默认选中）。
        header_actions: 页头右侧文本按钮列表（如 ``("刷新", "设置")``），
            按钮保存在 ``action_buttons`` 属性中供连接信号。
        footer_note: 页脚左侧说明文本。
        status: 页脚右侧状态文本。
        center: 主内容区控件；``None`` 时显示空占位。
        side: 右侧栏控件；``None`` 时显示空占位。
        parent: 父控件。

    ``resizeEvent`` 中按断点折叠侧栏：``sm`` 隐藏右侧栏，``xs`` 双侧栏隐藏。
    运行期可用 :meth:`set_center` / :meth:`set_side` 更换内容。
    """

    def __init__(self, title="", nav_items=(), header_actions=(),
                 footer_note="", status="", center=None, side=None, parent=None):
        super().__init__(parent)
        self._bp = ""
        self.action_buttons = []
        root = QVBoxLayout(self)
        root.setContentsMargins(T("space.4"), T("space.4"), T("space.4"), T("space.4"))
        root.setSpacing(T("space.3"))
        root.addWidget(self._build_header(title, header_actions))

        self._splitter = QSplitter(Qt.Horizontal)
        self._left = self._build_left(nav_items)
        self._center_host = self._build_panel()
        self._side_host = self._build_panel()
        self._splitter.addWidget(self._left)
        self._splitter.addWidget(self._center_host)
        self._splitter.addWidget(self._side_host)
        self._splitter.setCollapsible(1, False)
        self._splitter.setStretchFactor(1, 1)
        root.addWidget(self._splitter, 1)
        root.addWidget(self._build_footer(footer_note, status))
        self.set_center(center)
        self.set_side(side)
        # 初始按宽屏断点构建，首次 resize 时再按实际宽度修正
        self._sync("lg")

    # -- 页头 / 页脚 ------------------------------------------------------
    def _build_header(self, title, header_actions):
        bar = QFrame()
        bar.setFrameShape(QFrame.StyledPanel)
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(T("space.4"), T("space.2"), T("space.4"), T("space.2"))
        lay.setSpacing(T("space.3"))
        chip = TokenColorChip("color.primary", "radius.md")
        chip.setFixedSize(T("space.5"), T("space.5"))
        lay.addWidget(chip)
        if title:
            title_label = QLabel(title)
            apply_token_font(title_label, "font.title.sm", "font.weight.semibold")
            lay.addWidget(title_label)
        lay.addStretch(1)
        for text in header_actions:
            btn = QPushButton(text)
            set_property(btn, "variant", "text")
            lay.addWidget(btn)
            self.action_buttons.append(btn)
        return bar

    def _build_footer(self, footer_note, status):
        bar = QFrame()
        bar.setFrameShape(QFrame.StyledPanel)
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(T("space.4"), T("space.1"), T("space.4"), T("space.1"))
        if footer_note:
            note = QLabel(footer_note)
            note.setProperty("role", "tertiary")
            lay.addWidget(note)
        lay.addStretch(1)
        if status:
            status_label = QLabel(status)
            status_label.setProperty("role", "secondary")
            lay.addWidget(status_label)
        return bar

    # -- 三区 ------------------------------------------------------------
    def _build_left(self, nav_items):
        panel = QFrame()
        panel.setFrameShape(QFrame.StyledPanel)
        lay = QVBoxLayout(panel)
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
        return panel

    def _build_panel(self):
        """构造内容宿主面板，返回 (面板, 面板布局) 中的面板。"""
        panel = QFrame()
        panel.setFrameShape(QFrame.StyledPanel)
        lay = QVBoxLayout(panel)
        lay.setContentsMargins(T("space.3"), T("space.3"), T("space.3"), T("space.3"))
        return panel

    def _set_host_content(self, host, widget):
        """把内容控件装入宿主面板（替换旧内容；None 则显示空占位）。"""
        lay = host.layout()
        while lay.count():
            item = lay.takeAt(0)
            old = item.widget()
            if old is not None:
                old.hide()
                old.setParent(None)
        if widget is None:
            widget = empty_placeholder()
        lay.addWidget(widget, 1)

    def set_center(self, widget):
        """设置主内容区控件；``None`` 时显示空占位。"""
        self._set_host_content(self._center_host, widget)

    def set_side(self, widget):
        """设置右侧信息栏控件；``None`` 时显示空占位。"""
        self._set_host_content(self._side_host, widget)

    # -- 响应式 ----------------------------------------------------------
    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._sync(Breakpoint.from_width(self.width()))

    def _sync(self, bp):
        """按断点折叠侧栏：sm 隐藏右侧栏，xs 双侧栏均隐藏。"""
        if bp == self._bp:
            return
        self._bp = bp
        # 目标可见性自行跟踪（窗口未 show 时 isVisible() 恒为 False，不可依赖）
        left_vis = bp in ("sm", "md", "lg", "xl")
        right_vis = bp in ("md", "lg", "xl")
        self._left.setVisible(left_vis)
        self._side_host.setVisible(right_vis)
        # 侧栏显隐后重新分配三区宽度
        total = max(self._splitter.width(), T("space.16") * 8)
        if left_vis and right_vis:
            self._splitter.setSizes([int(total * 0.2), int(total * 0.6), int(total * 0.2)])
        elif left_vis:
            self._splitter.setSizes([int(total * 0.24), int(total * 0.76), 0])
        else:
            self._splitter.setSizes([0, total, 0])


def create_holy_grail(title="", nav_items=(), header_actions=(),
                      footer_note="", status="", center=None, side=None,
                      parent=None) -> QWidget:
    """创建圣杯布局部件（内容全部由调用方传入）。"""
    return HolyGrail(title=title, nav_items=nav_items,
                     header_actions=header_actions, footer_note=footer_note,
                     status=status, center=center, side=side, parent=parent)
