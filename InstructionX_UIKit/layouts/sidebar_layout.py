# -*- coding: utf-8 -*-
"""侧边栏布局预设（SPEC §6）。

左侧导航侧栏 + 右侧内容区的经典后台结构。侧栏可在「完整宽度」
与「图标栏」两种状态间切换：

- 展开：宽度 208px，导航项显示「矢量图标 + 文本」；
- 折叠：宽度 56px 图标栏，导航项只保留图标（文本置空），标题隐藏。

图标取自 ``InstructionX_UIKit.icons`` 矢量图标集，颜色随选中态与主题
变化（选中 = ``color.primary``，未选中 = ``color.text.secondary``）。

**API 驱动，无内置假数据**：品牌名、导航项与右侧内容均由调用方传入；
内容区未设置时显示优雅的空占位（「在此放置内容」）。

响应式（resizeEvent 中按 SPEC §2.6 断点处理）：``xs`` / ``sm``
自动折叠为图标栏，``md`` 及以上自动展开；底部「收起 / 展开」
按钮可随时手动切换。

示例::

    from InstructionX_UIKit.layouts.sidebar_layout import create_sidebar_layout
    win = create_sidebar_layout(
        brand="控制台",
        nav_items=[("home", "首页"), ("settings", "设置")],
        content=my_widget,
    )
    win.show()
"""

from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ..icons import get_icon
from ..theme import T, ThemeManager, set_property
from ..tokens import Breakpoint
from .helpers import TokenColorChip, apply_token_font, empty_placeholder

__all__ = ["SidebarLayout", "create_sidebar_layout"]

#: 侧栏展开 / 折叠宽度（px，取自 space 令牌量级）
_EXPANDED_WIDTH = 208
_COLLAPSED_WIDTH = 56

#: 导航图标边长（px）
_NAV_ICON_SIZE = 18


class SidebarLayout(QWidget):
    """侧边栏布局：左导航 + 右内容，可折叠为图标栏。

    参数:
        brand: 侧栏顶部品牌名（Logo 色块旁；留空隐藏）。
        nav_items: 导航项列表，每项为 ``(图标名, 文本)``，图标名取自
            ``InstructionX_UIKit.icons.ICON_NAMES``；按钮保存在
            ``nav_buttons`` 属性中供连接信号。
        content: 右侧内容区控件；``None`` 时显示空占位。
        parent: 父控件。

    ``resizeEvent`` 中按断点自动折叠 / 展开（xs/sm 折叠，md 及以上展开），
    底部按钮支持手动切换；导航选中态由 ``QToolButton:checked`` 的全局
    QSS 表达。运行期可用 :meth:`set_content` 更换内容区。
    """

    def __init__(self, brand="", nav_items=(), content=None, parent=None):
        super().__init__(parent)
        self._collapsed = False
        self._bp = ""
        root = QHBoxLayout(self)
        root.setContentsMargins(T("space.4"), T("space.4"), T("space.4"), T("space.4"))
        root.setSpacing(T("space.4"))
        root.addWidget(self._build_sidebar(brand, nav_items))
        self._content_host = QWidget()
        host_lay = QVBoxLayout(self._content_host)
        host_lay.setContentsMargins(0, 0, 0, 0)
        root.addWidget(self._content_host, 1)
        self.set_content(content)
        # 初始按宽屏断点展开，首次 resize 时再按实际宽度修正
        self._sync("lg")

    # -- 侧栏 ------------------------------------------------------------
    def _build_sidebar(self, brand, nav_items):
        self._sidebar = QFrame()
        self._sidebar.setFrameShape(QFrame.StyledPanel)
        lay = QVBoxLayout(self._sidebar)
        lay.setContentsMargins(T("space.2"), T("space.3"), T("space.2"), T("space.3"))
        lay.setSpacing(T("space.1"))

        head_row = QHBoxLayout()
        head_row.setSpacing(T("space.2"))
        chip = TokenColorChip("color.primary", "radius.md")
        chip.setFixedSize(T("space.5"), T("space.5"))
        head_row.addWidget(chip)
        self._brand = QLabel(brand)
        apply_token_font(self._brand, "font.title.sm", "font.weight.bold")
        head_row.addWidget(self._brand)
        head_row.addStretch(1)
        lay.addLayout(head_row)
        # Logo 行前拉伸标记：折叠时在前侧补一段对称拉伸，使图标精确居中
        self._head_row = head_row
        self._head_centered = False
        lay.addSpacing(T("space.3"))

        self.nav_buttons = []
        self._nav_buttons = []
        first = None
        for icon_name, text in nav_items:
            btn = QToolButton()
            btn.setCheckable(True)
            btn.setAutoExclusive(True)
            btn.setToolTip(text)
            btn.setIconSize(QSize(_NAV_ICON_SIZE, _NAV_ICON_SIZE))
            btn.toggled.connect(self._refresh_nav_icons)
            lay.addWidget(btn)
            self._nav_buttons.append((btn, icon_name, text))
            self.nav_buttons.append(btn)
            if first is None:
                first = btn
        if first is not None:
            first.setChecked(True)
        lay.addStretch(1)
        ThemeManager.instance().theme_changed.connect(self._refresh_nav_icons)

        self._toggle = QPushButton()
        set_property(self._toggle, "variant", "text")
        self._toggle.clicked.connect(self.toggle_sidebar)
        lay.addWidget(self._toggle)
        self._apply_collapsed(False)
        return self._sidebar

    # -- 内容区 ----------------------------------------------------------
    def set_content(self, widget):
        """设置右侧内容区控件；``None`` 时显示空占位。"""
        lay = self._content_host.layout()
        while lay.count():
            item = lay.takeAt(0)
            old = item.widget()
            if old is not None:
                old.hide()
                old.setParent(None)
        if widget is None:
            widget = empty_placeholder()
        lay.addWidget(widget, 1)

    # -- 折叠逻辑 --------------------------------------------------------
    def toggle_sidebar(self):
        """手动在展开 / 图标栏之间切换。"""
        self._apply_collapsed(not self._collapsed)

    def _apply_collapsed(self, collapsed):
        """应用折叠状态：调整侧栏宽度；折叠为图标栏时仅显示图标。"""
        self._collapsed = collapsed
        self._sidebar.setFixedWidth(_COLLAPSED_WIDTH if collapsed else _EXPANDED_WIDTH)
        self._brand.setVisible(not collapsed and bool(self._brand.text()))
        self._center_logo(collapsed)
        for btn, _icon_name, text in self._nav_buttons:
            policy = btn.sizePolicy()
            if collapsed:
                btn.setToolButtonStyle(Qt.ToolButtonIconOnly)
                btn.setText("")  # 图标栏不出现单字 / 文本
                # QToolButton 默认水平 Fixed 尺寸策略：按钮只取 sizeHint
                # 宽度（图标 18 + padding 8 = 26px）并在栏内左对齐，图标
                # 中心偏离 56px 栏中心约 6px。折叠态改为 Expanding 使按钮
                # 撑满栏宽，样式绘制 ToolButtonIconOnly 时图标即在按钮
                # （也即栏）内精确水平居中；对称 padding 不产生偏移。
                policy.setHorizontalPolicy(QSizePolicy.Expanding)
            else:
                btn.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
                btn.setText(text)
                # 展开态恢复 QToolButton 默认的 Fixed 水平策略，保持原样
                policy.setHorizontalPolicy(QSizePolicy.Fixed)
            btn.setSizePolicy(policy)
        self._refresh_nav_icons()
        self._toggle.setText("»" if collapsed else "«  收起导航")

    def _refresh_nav_icons(self, *_args):
        """按选中态与当前主题重建导航图标（选中主色，未选中次要文本色）。"""
        for btn, icon_name, _text in self._nav_buttons:
            key = "color.primary" if btn.isChecked() else "color.text.secondary"
            btn.setIcon(get_icon(icon_name, _NAV_ICON_SIZE, T(key)))

    def _center_logo(self, collapsed):
        """折叠态在 Logo 行前补一段与尾部对称的拉伸，使图标在 56px
        栏宽内精确水平居中；展开态恢复原左对齐布局。"""
        if collapsed and not self._head_centered:
            self._head_row.insertStretch(0, 1)
            self._head_centered = True
        elif not collapsed and self._head_centered:
            item = self._head_row.takeAt(0)
            del item
            self._head_centered = False

    # -- 响应式 ----------------------------------------------------------
    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._sync(Breakpoint.from_width(self.width()))

    def _sync(self, bp):
        """按断点自动折叠（xs/sm）或展开（md 及以上）侧栏。"""
        if bp == self._bp:
            return
        self._bp = bp
        self._apply_collapsed(bp in ("xs", "sm"))


def create_sidebar_layout(brand="", nav_items=(), content=None, parent=None) -> QWidget:
    """创建侧边栏布局部件。

    参数:
        brand: 侧栏顶部品牌名。
        nav_items: 导航项 ``(图标名, 文本)`` 列表。
        content: 右侧内容区控件；不传时显示空占位。
        parent: 父控件，默认 ``None``（作为独立窗口使用）。
    """
    return SidebarLayout(brand=brand, nav_items=nav_items,
                         content=content, parent=parent)
