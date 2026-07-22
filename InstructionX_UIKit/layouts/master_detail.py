# -*- coding: utf-8 -*-
"""列表-详情布局预设（SPEC §6）。

左侧条目列表 + 右侧详情面板的经典结构，二者置于 ``QSplitter``
中可拖拽调宽。点击列表项，右侧详情联动刷新。

**API 驱动，无内置假数据**：条目由调用方通过 ``items`` 传入，每项为
``(标题, 摘要, 详情正文)`` 三元组；不传 ``items`` 时列表为空、详情区
显示优雅的空占位（「在此放置内容」）。

响应式（resizeEvent 中按 SPEC §2.6 断点处理）：

- ``md`` 及以上：左右并排（QSplitter 水平）；
- ``xs`` / ``sm``：上下堆叠（QSplitter 垂直，列表在上、详情在下）。

示例::

    from InstructionX_UIKit.layouts.master_detail import create_master_detail
    win = create_master_detail(items=[
        ("产品周报", "本周核心指标回顾", "正文……"),
    ])
    win.show()
"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from ..theme import T, set_property
from ..tokens import Breakpoint
from .helpers import TokenColorChip, apply_token_font, empty_placeholder

__all__ = ["MasterDetail", "create_master_detail"]


class MasterDetail(QWidget):
    """列表-详情布局：左列表右详情，窄断点上下堆叠。

    参数:
        items: 条目列表，每项为 ``(标题, 摘要, 详情正文)`` 三元组；
            ``None`` 或空列表时列表为空、详情区显示空占位。
        title: 列表侧栏标题（如「收件箱」；留空则隐藏）。
        actions: 详情区底部操作按钮，每项为 ``(文本, variant)``；按钮
            保存在 ``action_buttons`` 属性中供连接信号。
        parent: 父控件。

    列表使用 ``QListWidget``；选择列表项时详情联动。``resizeEvent``
    中按断点切换 ``QSplitter`` 方向。运行期可调用 :meth:`set_items`
    更换条目。
    """

    def __init__(self, items=None, title="", actions=(), parent=None):
        super().__init__(parent)
        self._bp = ""
        self._items = []
        self.action_buttons = []
        root = QVBoxLayout(self)
        root.setContentsMargins(T("space.4"), T("space.4"), T("space.4"), T("space.4"))
        root.setSpacing(0)

        self._splitter = QSplitter(Qt.Horizontal)
        self._splitter.addWidget(self._build_master(title))
        self._splitter.addWidget(self._build_detail(actions))
        self._splitter.setCollapsible(0, False)
        self._splitter.setCollapsible(1, False)
        self._splitter.setStretchFactor(1, 1)
        root.addWidget(self._splitter, 1)

        self.set_items(items)
        # 初始按宽屏断点构建，首次 resize 时再按实际宽度修正
        self._sync("lg")

    # -- 列表侧 ----------------------------------------------------------
    def _build_master(self, title):
        panel = QFrame()
        panel.setFrameShape(QFrame.StyledPanel)
        lay = QVBoxLayout(panel)
        lay.setContentsMargins(T("space.3"), T("space.3"), T("space.3"), T("space.3"))
        lay.setSpacing(T("space.2"))
        if title:
            head = QLabel(title)
            apply_token_font(head, "font.title.sm", "font.weight.semibold")
            lay.addWidget(head)
        self._list = QListWidget()
        self._list.currentRowChanged.connect(self._show_detail)
        lay.addWidget(self._list, 1)
        return panel

    # -- 详情侧 ----------------------------------------------------------
    def _build_detail(self, actions):
        panel = QFrame()
        panel.setFrameShape(QFrame.StyledPanel)
        self._detail_lay = QVBoxLayout(panel)
        lay = self._detail_lay
        lay.setContentsMargins(T("space.5"), T("space.5"), T("space.5"), T("space.5"))
        lay.setSpacing(T("space.3"))

        self._d_title = QLabel()
        apply_token_font(self._d_title, "font.title.md", "font.weight.semibold")
        self._d_title.setWordWrap(True)
        lay.addWidget(self._d_title)
        self._d_meta = QLabel()
        self._d_meta.setProperty("role", "tertiary")
        apply_token_font(self._d_meta, "font.sm")
        lay.addWidget(self._d_meta)

        self._d_chip = TokenColorChip("color.primary.subtle", "radius.md")
        self._d_chip.setFixedHeight(T("space.16") + T("space.8"))
        lay.addWidget(self._d_chip)

        self._d_body = QLabel()
        self._d_body.setProperty("role", "secondary")
        self._d_body.setWordWrap(True)
        lay.addWidget(self._d_body)

        self._placeholder = empty_placeholder()
        self._placeholder.hide()
        lay.addWidget(self._placeholder, 1)
        lay.addStretch(1)

        if actions:
            action_row = QHBoxLayout()
            action_row.setSpacing(T("space.3"))
            for text, variant in actions:
                btn = QPushButton(text)
                set_property(btn, "variant", variant)
                action_row.addWidget(btn)
                self.action_buttons.append(btn)
            action_row.addStretch(1)
            lay.addLayout(action_row)
        return panel

    # -- 内容 ------------------------------------------------------------
    def set_items(self, items):
        """设置条目列表（``(标题, 摘要, 详情正文)`` 三元组列表）。"""
        self._items = list(items or [])
        self._list.clear()
        for title, summary, _body in self._items:
            self._list.addItem(f"{title}\n{summary}")
        if self._items:
            self._list.setCurrentRow(0)
        else:
            self._show_detail(-1)

    def _show_detail(self, row):
        """按当前行刷新详情面板；无选中时显示空占位。"""
        has = 0 <= row < len(self._items)
        for w in (self._d_title, self._d_meta, self._d_chip, self._d_body):
            w.setVisible(has)
        self._placeholder.setVisible(not has)
        if not has:
            return
        title, summary, body = self._items[row]
        self._d_title.setText(title)
        self._d_meta.setText(summary)
        self._d_body.setText(body)

    # -- 响应式 ----------------------------------------------------------
    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._sync(Breakpoint.from_width(self.width()))

    def _sync(self, bp):
        """按断点切换分栏方向：md 及以上水平，xs/sm 垂直堆叠。"""
        if bp == self._bp:
            return
        self._bp = bp
        horizontal = bp in ("md", "lg", "xl")
        self._splitter.setOrientation(Qt.Horizontal if horizontal else Qt.Vertical)
        extent = self._splitter.width() if horizontal else self._splitter.height()
        extent = max(extent, T("space.16") * 4)
        self._splitter.setSizes([int(extent * 0.34), int(extent * 0.66)])


def create_master_detail(items=None, title="", actions=(), parent=None) -> QWidget:
    """创建列表-详情布局部件。

    参数:
        items: 条目列表，每项为 ``(标题, 摘要, 详情正文)``；不传时
            列表为空、详情区显示空占位。
        title: 列表侧栏标题。
        actions: 详情区底部操作按钮 ``(文本, variant)`` 列表。
        parent: 父控件，默认 ``None``（作为独立窗口使用）。
    """
    return MasterDetail(items=items, title=title, actions=actions, parent=parent)
