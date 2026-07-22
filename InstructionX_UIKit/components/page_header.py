# -*- coding: utf-8 -*-
"""页头 PageHeader（SPEC §5.3 page_header.py）。

包含返回按钮、标题、副标题、面包屑槽与右侧操作区，底部带分隔线。
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

from ..theme import T, ThemeManager, set_property
from .breadcrumb import Breadcrumb
from shiboken6 import isValid as _shiboken_is_valid


def _connect_theme(widget, slot) -> None:
    """连接主题切换信号；控件销毁后自动忽略回调。"""
    ThemeManager.instance().theme_changed.connect(
        lambda *_: slot() if _shiboken_is_valid(widget) else None)

__all__ = ["PageHeader"]


def _back_icon() -> QIcon:
    """绘制主题感知的返回箭头图标。"""
    pm = QPixmap(14, 14)
    pm.fill(Qt.transparent)
    painter = QPainter(pm)
    painter.setRenderHint(QPainter.Antialiasing)
    pen = QPen(QColor(T("color.text.secondary")))
    pen.setWidthF(1.6)
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    painter.setPen(pen)
    painter.drawPolyline([
        QPointF(9.0, 3.0), QPointF(4.5, 7.0), QPointF(9.0, 11.0)])
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
        root.setContentsMargins(16, 12, 16, 12)
        root.setSpacing(6)

        self._row = QHBoxLayout()
        self._row.setSpacing(12)
        root.addLayout(self._row)

        self._back = QToolButton(self)
        self._back.setFixedSize(28, 28)
        self._back.setCursor(Qt.PointingHandCursor)
        self._back.setToolTip("返回")
        self._back.clicked.connect(self.backClicked.emit)
        self._row.addWidget(self._back, 0, Qt.AlignTop)

        col = QVBoxLayout()
        col.setSpacing(2)
        self._title = QLabel(title, self)
        set_property(self._title, "uikPh", "title")
        self._subtitle = QLabel(subtitle, self)
        set_property(self._subtitle, "uikPh", "subtitle")
        self._subtitle.setVisible(bool(subtitle))
        col.addWidget(self._title)
        col.addWidget(self._subtitle)
        self._row.addLayout(col, 1)

        self._actions = QHBoxLayout()
        self._actions.setSpacing(8)
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
        """设置面包屑槽内容（文本列表），显示在标题上方。"""
        if self._breadcrumb is None:
            self._breadcrumb = Breadcrumb(items, parent=self)
            self.layout().insertWidget(0, self._breadcrumb)
        else:
            self._breadcrumb.set_items(items)

    def breadcrumb(self) -> Breadcrumb:
        """返回内部 Breadcrumb（未设置时为 None）。"""
        return self._breadcrumb

    def add_action(self, widget: QWidget) -> None:
        """向右侧操作区追加控件（通常为按钮）。"""
        self._actions.addWidget(widget)

    # -- 内部 -------------------------------------------------------------
    def _reload_style(self) -> None:
        c = lambda k: T(f"color.{k}")  # noqa: E731
        self.setStyleSheet(f"""
PageHeader {{
    background-color: {c('bg.base')};
    border-bottom: 1px solid {c('border')};
}}
QLabel[uikPh="title"] {{
    color: {c('text.primary')};
    font-size: {T('font.title.md')}px;
    font-weight: 600;
}}
QLabel[uikPh="subtitle"] {{
    color: {c('text.secondary')};
    font-size: {T('font.sm')}px;
}}
""")
        self._back.setIcon(_back_icon())
