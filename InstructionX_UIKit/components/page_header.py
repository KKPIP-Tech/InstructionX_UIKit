# -*- coding: utf-8 -*-
"""页头 PageHeader（SPEC §5.3 page_header.py）。

包含返回按钮、标题、副标题、面包屑槽与右侧操作区，底部带分隔线。

对齐约定（与 COMPONENT-DESIGN-CONTRACT §3 对齐）：

- **面包屑 / 标题 / 副标题左缘严格一致**：三者放在同一个竖列里，
  天然共用左缘。旧版把面包屑 ``insertWidget(0, …)`` 到最外层布局，
  而标题在「返回按钮 + 间距」之后的子列里，于是面包屑比标题左移了
  一个返回按钮的宽度（实测 34px），三者对不齐。
- **返回按钮只是缩进**：隐藏返回按钮时竖列整体左移到页头内边距，
  不留空占位（``_back`` 走 ``setVisible(False)``，布局项宽度归零）。
- 字号走 ``set_font``（全局 QSS 会覆盖 ``setFont``，契约 §6），
  所有内边距 / 间距取令牌，页头内部只有底部一条 1px 分隔线。
"""

from PySide6.QtCore import QPointF, Qt, Signal
from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ..theme import T, ThemeManager, set_font, set_property
from .breadcrumb import Breadcrumb
from shiboken6 import isValid as _shiboken_is_valid

#: 返回按钮边长：与 md 档控件高度一致（契约 §1 密度刻度，space.7 = 28）
_BACK_BTN_H = T("space.7")
#: 返回箭头图标边长（小图标，取按钮边长的一半）
_BACK_ICON = _BACK_BTN_H // 2


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

__all__ = ["PageHeader"]


def _back_icon() -> QIcon:
    """绘制主题感知的返回箭头图标。"""
    size = _BACK_ICON
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    painter = QPainter(pm)
    painter.setRenderHint(QPainter.Antialiasing)
    pen = QPen(QColor(T("color.text.secondary")))
    pen.setWidthF(1.6)
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    painter.setPen(pen)
    # 箭头几何按图标边长的比例推导（令牌派生，无裸数字）
    c = size / 2.0
    painter.drawPolyline([
        QPointF(c + size * 0.18, c - size * 0.29),
        QPointF(c - size * 0.18, c),
        QPointF(c + size * 0.18, c + size * 0.29),
    ])
    painter.end()
    return QIcon(pm)


class PageHeader(QWidget):
    """页头：返回、标题、副标题、面包屑槽、操作区。

    参数:
        title: 主标题文本。
        subtitle: 副标题文本（为空则隐藏）。
        show_back: 是否显示返回按钮。
        parent: 父控件。

    示例::

        ph = PageHeader("订单详情", "编号 20240601")
        ph.set_breadcrumb(["订单", "详情"])
        ph.add_action(QPushButton("编辑"))
    """

    #: 点击返回按钮时发射
    backClicked = Signal()

    def __init__(self, title: str = "", subtitle: str = "",
                 show_back: bool = True, parent: QWidget = None):
        super().__init__(parent)
        self._breadcrumb = None

        root = QVBoxLayout(self)
        root.setContentsMargins(T("layout.page.pad"), T("layout.card.pad_top"),
                                T("layout.page.pad"), T("layout.card.pad_top"))
        root.setSpacing(T("layout.card.gap"))

        self._row = QHBoxLayout()
        self._row.setContentsMargins(0, 0, 0, 0)
        self._row.setSpacing(T("layout.gutter"))
        root.addLayout(self._row)

        self._back = QToolButton(self)
        self._back.setFixedSize(_BACK_BTN_H, _BACK_BTN_H)
        self._back.setCursor(Qt.PointingHandCursor)
        self._back.setToolTip("返回")
        self._back.clicked.connect(self.backClicked.emit)
        self._row.addWidget(self._back, 0, Qt.AlignTop)

        # 竖列：面包屑 → 标题 → 副标题（三者共用左缘，严格对齐）
        col = QVBoxLayout()
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(T("layout.card.title_gap"))
        self._col = col
        self._title = QLabel(title, self)
        set_font(self._title, "title.md", "semibold")
        self._subtitle = QLabel(subtitle, self)
        set_font(self._subtitle, "sm", "regular")
        set_property(self._subtitle, "role", "secondary")
        self._subtitle.setVisible(bool(subtitle))
        col.addWidget(self._title)
        col.addWidget(self._subtitle)
        self._row.addLayout(col, 1)

        self._actions = QHBoxLayout()
        self._actions.setContentsMargins(0, 0, 0, 0)
        self._actions.setSpacing(T("layout.inline.gap"))
        # 注意：**不能**给嵌套布局传 alignment（insertLayout 带对齐参数会
        # 让布局项按整行均分宽度，按钮被拉成两段等宽的大块）。
        # 默认对齐即可，操作区与标题块在行内垂直居中（契约 §3）。
        self._row.addLayout(self._actions)

        self._back.setVisible(show_back)
        _connect_theme(self, self._reload_style)
        self._reload_style()

    # -- 公开 API ---------------------------------------------------------
    def set_title(self, text: str) -> None:
        """设置主标题。"""
        self._title.setText(text)

    def title(self) -> str:
        """返回主标题。"""
        return self._title.text()

    def set_subtitle(self, text: str) -> None:
        """设置副标题（为空则隐藏）。"""
        self._subtitle.setText(text)
        self._subtitle.setVisible(bool(text))

    def subtitle(self) -> str:
        """返回副标题。"""
        return self._subtitle.text()

    def set_show_back(self, visible: bool) -> None:
        """设置是否显示返回按钮。"""
        self._back.setVisible(visible)

    def set_breadcrumb(self, items) -> None:
        """设置面包屑槽内容（文本列表），插在标题上方。

        必须插进标题所在的**同一竖列**：插到最外层布局会让面包屑
        比标题左移一个返回按钮的宽度，三者左缘就对不齐了。
        """
        if self._breadcrumb is None:
            self._breadcrumb = Breadcrumb(items, parent=self)
            self._col.insertWidget(0, self._breadcrumb)
        else:
            self._breadcrumb.set_items(items)
        self._breadcrumb.setVisible(bool(items))

    def breadcrumb(self) -> Breadcrumb:
        """返回内部 Breadcrumb（未设置时为 None）。"""
        return self._breadcrumb

    def add_action(self, widget: QWidget) -> None:
        """向右侧操作区追加控件（通常为按钮）。"""
        self._actions.addWidget(widget, 0, Qt.AlignVCenter)

    # -- 内部 -------------------------------------------------------------
    def _reload_style(self) -> None:
        # 底色 / 底部分隔线走实例级 QSS：与全局 QWidget 基座同源，
        # 但页头自带 1px 底边（页面级分隔），且不带圆角（通栏元素）。
        c = lambda k: T(f"color.{k}")  # noqa: E731
        self.setStyleSheet(f"""
PageHeader {{
    background-color: {c('bg.base')};
    border-bottom: 1px solid {c('border')};
}}
""")
        self._back.setIcon(_back_icon())