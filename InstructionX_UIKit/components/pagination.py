# -*- coding: utf-8 -*-
"""分页器 Pagination（SPEC §5.3 pagination.py）。

页码自动省略、上一页/下一页、跳转输入、每页条数选择。
"""

from PySide6.QtCore import QPointF, Qt, Signal
from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QToolButton,
    QWidget,
)

from ..theme import T, ThemeManager, set_property
from shiboken6 import isValid as _shiboken_is_valid


def _connect_theme(widget, slot) -> None:
    """连接主题切换信号；控件销毁后自动忽略回调。"""
    ThemeManager.instance().theme_changed.connect(
        lambda *_: slot() if _shiboken_is_valid(widget) else None)

__all__ = ["Pagination"]


def _chevron(direction: str) -> QIcon:
    """绘制主题感知的左 / 右箭头图标。"""
    pm = QPixmap(12, 12)
    pm.fill(Qt.transparent)
    painter = QPainter(pm)
    painter.setRenderHint(QPainter.Antialiasing)
    pen = QPen(QColor(T("color.text.secondary")))
    pen.setWidthF(1.5)
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    painter.setPen(pen)
    pts = {"left": [(7.4, 2.8), (4.2, 6.0), (7.4, 9.2)],
           "right": [(4.6, 2.8), (7.8, 6.0), (4.6, 9.2)]}[direction]
    painter.drawPolyline([QPointF(x, y) for x, y in pts])
    painter.end()
    return QIcon(pm)


class Pagination(QWidget):
    """分页器：页码省略、跳转输入、每页条数。

    参数:
        total: 数据总条数。
        page_size: 每页条数。
        current: 初始页码（从 1 开始）。
        parent: 父控件。

    示例::

        pg = Pagination(total=238, page_size=10)
        pg.set_show_jumper(True)
        pg.currentChanged.connect(print)
    """

    #: 页码变化信号
    currentChanged = Signal(int)
    #: 每页条数变化信号
    pageSizeChanged = Signal(int)

    def __init__(self, total: int = 0, page_size: int = 10,
                 current: int = 1, parent: QWidget = None):
        super().__init__(parent)
        self._total = max(0, int(total))
        self._page_size = max(1, int(page_size))
        self._current = 1
        self._show_jumper = False
        self._show_size_changer = False
        self._size_options = (10, 20, 50, 100)
        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(6)
        _connect_theme(self, self._on_theme_changed)
        self._reload_style()
        self.set_current(current)

    # -- 公开 API ---------------------------------------------------------
    def set_total(self, total: int) -> None:
        """设置数据总条数。"""
        self._total = max(0, int(total))
        self.set_current(min(self._current, self.page_count()))

    def total(self) -> int:
        return self._total

    def set_page_size(self, page_size: int) -> None:
        """设置每页条数（超出页码范围时自动收敛）。"""
        page_size = max(1, int(page_size))
        if page_size == self._page_size:
            return
        self._page_size = page_size
        self.pageSizeChanged.emit(page_size)
        self.set_current(min(self._current, self.page_count()))
        self._rebuild()

    def page_size(self) -> int:
        return self._page_size

    def set_current(self, page: int) -> None:
        """设置当前页码（自动收敛到合法范围）。"""
        page = max(1, min(int(page), self.page_count()))
        changed = page != self._current
        self._current = page
        self._rebuild()
        if changed:
            self.currentChanged.emit(page)

    def current(self) -> int:
        return self._current

    def page_count(self) -> int:
        """总页数（至少 1 页）。"""
        return max(1, -(-self._total // self._page_size))

    def set_show_jumper(self, show: bool) -> None:
        """是否显示「跳至 N 页」输入。"""
        self._show_jumper = bool(show)
        self._rebuild()

    def set_show_size_changer(self, show: bool, options=None) -> None:
        """是否显示每页条数选择；``options`` 为可选条数序列。"""
        self._show_size_changer = bool(show)
        if options:
            self._size_options = tuple(int(x) for x in options)
        self._rebuild()

    # -- 内部 -------------------------------------------------------------
    @staticmethod
    def _page_items(current: int, count: int) -> list:
        """计算页码序列，None 表示省略号。"""
        if count <= 7:
            return list(range(1, count + 1))
        pages = {1, count}
        for p in (current - 1, current, current + 1):
            if 2 <= p <= count - 1:
                pages.add(p)
        ordered = sorted(pages)
        result = []
        prev = 0
        for p in ordered:
            if p - prev > 1:
                result.append(None)
            result.append(p)
            prev = p
        return result

    def _rebuild(self) -> None:
        while self._layout.count():
            item = self._layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()

        count = self.page_count()
        prev_btn = self._nav_button("left", self._current > 1,
                                    lambda: self.set_current(self._current - 1))
        self._layout.addWidget(prev_btn)

        for p in self._page_items(self._current, count):
            if p is None:
                dots = QLabel("…", self)
                set_property(dots, "role", "tertiary")
                self._layout.addWidget(dots)
                continue
            btn = QToolButton(self)
            btn.setText(str(p))
            set_property(btn, "uikPg", "page")
            set_property(btn, "current", "true" if p == self._current else "false")
            btn.setCursor(Qt.PointingHandCursor)
            btn.clicked.connect(lambda _=False, page=p: self.set_current(page))
            self._layout.addWidget(btn)

        next_btn = self._nav_button("right", self._current < count,
                                    lambda: self.set_current(self._current + 1))
        self._layout.addWidget(next_btn)

        if self._total > 0:
            total_label = QLabel(f"共 {self._total} 条", self)
            set_property(total_label, "role", "tertiary")
            self._layout.addWidget(total_label)

        if self._show_size_changer:
            combo = QComboBox(self)
            set_property(combo, "size", "sm")
            for n in self._size_options:
                combo.addItem(f"{n} 条/页", n)
            idx = combo.findData(self._page_size)
            if idx >= 0:
                combo.setCurrentIndex(idx)
            combo.activated.connect(
                lambda i, c=combo: self.set_page_size(c.itemData(i)))
            self._layout.addWidget(combo)

        if self._show_jumper:
            lab = QLabel("跳至", self)
            set_property(lab, "role", "secondary")
            edit = QLineEdit(self)
            set_property(edit, "size", "sm")
            edit.setFixedWidth(52)
            edit.setAlignment(Qt.AlignCenter)
            edit.returnPressed.connect(lambda e=edit: self._jump(e))
            lab2 = QLabel("页", self)
            set_property(lab2, "role", "secondary")
            self._layout.addWidget(lab)
            self._layout.addWidget(edit)
            self._layout.addWidget(lab2)

        self._layout.addStretch(1)

    def _nav_button(self, direction: str, enabled: bool, slot) -> QToolButton:
        btn = QToolButton(self)
        set_property(btn, "uikPg", "nav")
        btn.setIcon(_chevron(direction))
        btn.setEnabled(enabled)
        btn.setCursor(Qt.PointingHandCursor if enabled else Qt.ArrowCursor)
        btn.clicked.connect(lambda _=False: slot())
        return btn

    def _jump(self, edit: QLineEdit) -> None:
        text = edit.text().strip()
        edit.clear()
        if text.isdigit():
            self.set_current(int(text))

    def _on_theme_changed(self) -> None:
        # 样式表与箭头图标都需要按新主题重建
        self._reload_style()
        self._rebuild()

    def _reload_style(self) -> None:
        c = lambda k: T(f"color.{k}")  # noqa: E731
        self.setStyleSheet(f"""
QToolButton[uikPg="nav"] {{
    border: 1px solid {c('border')};
    background-color: {c('bg.elevated')};
    border-radius: {T('radius.md')}px;
    min-width: 28px; max-width: 28px;
    min-height: 28px; max-height: 28px;
    padding: 0;
}}
QToolButton[uikPg="nav"]:hover:enabled {{
    border-color: {c('primary')};
}}
QToolButton[uikPg="nav"]:disabled {{
    background-color: {c('bg.muted')};
}}
QToolButton[uikPg="page"] {{
    border: 1px solid {c('border')};
    background-color: {c('bg.elevated')};
    color: {c('text.primary')};
    border-radius: {T('radius.md')}px;
    min-width: 28px; max-width: 28px;
    min-height: 28px; max-height: 28px;
    padding: 0;
}}
QToolButton[uikPg="page"]:hover {{
    border-color: {c('primary')};
    color: {c('primary')};
}}
QToolButton[uikPg="page"][current="true"] {{
    border-color: {c('primary')};
    color: {c('primary')};
    font-weight: 600;
}}
""")
