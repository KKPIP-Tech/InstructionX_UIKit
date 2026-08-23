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
        # 可复用控件缓存（增量更新：不销毁可复用部分，主题切换保留
        # 跳转框输入；仅结构变化时重建对应控件）
        self._prev_btn = None
        self._next_btn = None
        self._page_widgets = []   # 页码按钮 / 省略号（按显示顺序）
        self._total_label = None
        self._combo = None
        self._combo_options = None
        self._jump_edit = None
        self._jump_labels = None
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
        """按当前状态增量同步控件（仅结构变化时重建，不销毁可复用控件）。"""
        count = self.page_count()

        # 1) 导航按钮：长期持有，仅更新图标与可用态（主题切换刷新图标）
        if self._prev_btn is None:
            self._prev_btn = self._nav_button(
                "left", True, lambda: self.set_current(self._current - 1))
            self._next_btn = self._nav_button(
                "right", True, lambda: self.set_current(self._current + 1))
        self._prev_btn.setEnabled(self._current > 1)
        self._prev_btn.setIcon(_chevron("left"))
        self._next_btn.setEnabled(self._current < count)
        self._next_btn.setIcon(_chevron("right"))

        # 2) 页码按钮序列：结构相同则原位更新，不同才重建中段
        self._sync_page_buttons()

        # 3) 总数标签
        if self._total > 0:
            if self._total_label is None:
                self._total_label = QLabel(self)
                set_property(self._total_label, "role", "tertiary")
            self._total_label.setText(f"共 {self._total} 条")
        elif self._total_label is not None:
            self._total_label.deleteLater()
            self._total_label = None

        # 4) 每页条数选择
        if self._show_size_changer:
            if self._combo is None:
                self._combo = QComboBox(self)
                set_property(self._combo, "size", "sm")
                self._combo.activated.connect(
                    lambda i, c=self._combo: self.set_page_size(c.itemData(i)))
            if self._combo_options != tuple(self._size_options):
                self._combo.clear()
                for n in self._size_options:
                    self._combo.addItem(f"{n} 条/页", n)
                self._combo_options = tuple(self._size_options)
            idx = self._combo.findData(self._page_size)
            if idx >= 0:
                self._combo.setCurrentIndex(idx)
        elif self._combo is not None:
            self._combo.deleteLater()
            self._combo = None
            self._combo_options = None

        # 5) 跳转框：主题切换不重建，输入文本得以保留
        if self._show_jumper:
            if self._jump_edit is None:
                lab = QLabel("跳至", self)
                set_property(lab, "role", "secondary")
                edit = QLineEdit(self)
                set_property(edit, "size", "sm")
                edit.setFixedWidth(52)
                edit.setAlignment(Qt.AlignCenter)
                edit.returnPressed.connect(lambda e=edit: self._jump(e))
                lab2 = QLabel("页", self)
                set_property(lab2, "role", "secondary")
                self._jump_edit = edit
                self._jump_labels = (lab, lab2)
        elif self._jump_edit is not None:
            for w in self._jump_labels + (self._jump_edit,):
                w.deleteLater()
            self._jump_edit = None
            self._jump_labels = None

        # 重新装配布局（takeAt 不销毁控件，原位顺序不变）
        while self._layout.count():
            self._layout.takeAt(0)
        self._layout.addWidget(self._prev_btn)
        for w in self._page_widgets:
            self._layout.addWidget(w)
        self._layout.addWidget(self._next_btn)
        if self._total_label is not None:
            self._layout.addWidget(self._total_label)
        if self._combo is not None:
            self._layout.addWidget(self._combo)
        if self._jump_edit is not None:
            self._layout.addWidget(self._jump_labels[0])
            self._layout.addWidget(self._jump_edit)
            self._layout.addWidget(self._jump_labels[1])
        self._layout.addStretch(1)

    def _sync_page_buttons(self) -> None:
        """页码按钮序列与目标序列对齐：结构相同原位更新，不同重建。"""
        items = self._page_items(self._current, self.page_count())
        current_values = [getattr(w, "_pg_value", None)
                          for w in self._page_widgets]
        if current_values == items:
            for w in self._page_widgets:
                if isinstance(w, QToolButton):
                    set_property(w, "current",
                                 "true" if w._pg_value == self._current
                                 else "false")
            return
        for w in self._page_widgets:
            w.deleteLater()
        self._page_widgets = []
        for p in items:
            if p is None:
                dots = QLabel("…", self)
                set_property(dots, "role", "tertiary")
                dots._pg_value = None
                self._page_widgets.append(dots)
                continue
            btn = QToolButton(self)
            btn.setText(str(p))
            btn._pg_value = p
            set_property(btn, "uikPg", "page")
            set_property(btn, "current",
                         "true" if p == self._current else "false")
            btn.setCursor(Qt.PointingHandCursor)
            btn.clicked.connect(lambda _=False, page=p: self.set_current(page))
            self._page_widgets.append(btn)

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
