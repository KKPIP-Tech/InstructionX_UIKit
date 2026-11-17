# -*- coding: utf-8 -*-
"""分页器 Pagination（SPEC §5.3 pagination.py）。

页码自动省略、上一页/下一页、跳转输入、每页条数选择；提供 sm / md / lg
三档尺寸，页码按钮与导航按钮的高度直接跟随 ``theme._INPUT_HEIGHTS``。

四态约定（与 Tabs / NavMenu / Breadcrumb / Dropdown 同一套语义）：

======== ==================== =========================================
状态      文字                 底色 / 指示
======== ==================== =========================================
常规      ``text.primary``    ``bg.elevated`` + ``border`` 1px 方框
悬停      ``text.primary``    ``bg.muted`` + ``border.strong`` 1px
选中/当前 ``primary`` + 半粗    ``primary.subtle`` 底 + ``primary`` 2px 边框
禁用      ``text.disabled``   ``bg.muted``，箭头同为 ``text.disabled``
======== ==================== =========================================

> 旧实现里「悬停」与「当前」都是 primary 描边 + primary 文字，肉眼完全
> 分不出；这里把悬停退回中性底色，把 primary.subtle + 2px 描边留给当前页。
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

#: 合法尺寸档 -> 该档控件总高（px）。与 ``theme._INPUT_HEIGHTS`` 同源，
#: 全局 QSS 的 ``[uiksize]`` 规则给的是「内容盒」高度（总高 - 2），
#: 这里记的是含边框的总高，用于宽度与省略号节奏。
#: TODO(shared): 建议 tokens.py ``_LAYOUT`` 补
#:   layout.control.h.sm/md/lg = 22/28/34，供所有自绘组件共用。
_SIZE_H = {"sm": 22, "md": 28, "lg": 34}
#: 左右箭头图标边长（与 NavMenu 的折叠箭头同为 12px / 1.5 线宽）
_CHEVRON_D = 12
#: 跳转输入框宽度
_JUMP_W = T("space.12") + T("space.1")


def _chevron(direction: str, color: str = None) -> QIcon:
    """绘制主题感知的左 / 右箭头图标。"""
    pm = QPixmap(_CHEVRON_D, _CHEVRON_D)
    pm.fill(Qt.transparent)
    painter = QPainter(pm)
    painter.setRenderHint(QPainter.Antialiasing)
    pen = QPen(QColor(color or T("color.text.secondary")))
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
        pg.set_size("sm")
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
        self._size = "md"
        self._show_jumper = False
        self._show_size_changer = False
        self._size_options = (10, 20, 50, 100)
        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(T("layout.inline.gap"))
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
    def set_size(self, size: str) -> None:
        """设置尺寸档 ``"sm"`` / ``"md"`` / ``"lg"``（默认 ``"md"``）。

        高度由全局 QSS 的 ``[uiksize]`` 提供，本方法只切换动态属性并
        重建页码序列的宽度节奏。
        """
        if size not in _SIZE_H:
            raise ValueError(
                f"未知分页尺寸: {size!r}，应为 {tuple(_SIZE_H)} 之一")
        if size == self._size:
            return
        self._size = size
        self._reload_style()
        # 页码按钮 / 省略号需要按新尺寸重新生成宽度
        self._drop_page_widgets()
        # 已存在的每页条数选择 / 跳转框同步换档（它们是被复用的长寿命控件，
        # 不会在 _rebuild 里重建，只能在这里补一次）
        for w in (self._combo, self._jump_edit):
            if w is not None:
                set_property(w, "size", size)
        for b in (self._prev_btn, self._next_btn):
            if b is not None:
                set_property(b, "size", size)
                self._apply_box(b)
        self._rebuild()

    def size_name(self) -> str:
        """返回当前尺寸档。"""
        return self._size

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
        self._prev_btn.setIcon(_chevron(
            "left", None if self._current > 1 else T("color.text.disabled")))
        self._next_btn.setEnabled(self._current < count)
        self._next_btn.setIcon(_chevron(
            "right", None if self._current < count else T("color.text.disabled")))

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
                set_property(self._combo, "size", self._size)
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
                set_property(edit, "size", self._size)
                edit.setFixedWidth(_JUMP_W)
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

    def _apply_box(self, btn: QToolButton) -> None:
        """把页码 / 导航按钮固定为「档位总高」见方的正方形。

        宽度用 ``setFixedWidth`` 而非局部 QSS 的 min/max-width：局部样式表
        对「在首次 show 之前创建的子控件」不会在后续 setStyleSheet 时
        重新求解（实测 set_size() 在 show 前调用会失效），而
        ``setFixedWidth`` 是几何层面的约束，任何时机调用都确定生效。
        取值即「档位总高」（22 / 28 / 34），与全局 ``[uiksize]`` 给出的
        内容盒高度 + 上下各 1px 边框完全一致，页码按钮因此是正方形。
        """
        btn.setFixedWidth(_SIZE_H[self._size])

    def _drop_page_widgets(self) -> None:
        """丢弃旧页码控件。

        先 ``setParent(None)`` 再 ``deleteLater()``：deleteLater 真正生效
        要等下一轮事件循环，在那之前旧控件仍是子控件，尺寸切换的一瞬间
        会同时存在两套尺寸的页码按钮（渲染上表现为「跳一下」）。
        """
        for w in self._page_widgets:
            w.setParent(None)
            w.deleteLater()
        self._page_widgets = []

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
        self._drop_page_widgets()
        box = _SIZE_H[self._size]
        for p in items:
            if p is None:
                dots = QLabel("…", self)
                set_property(dots, "role", "tertiary")
                # 省略号占「一个页码按钮 + 一个间距」的宽度，整行节奏与
                # 有页码时完全一致，不会因为省略号把后面的页码挤歪
                dots.setFixedWidth(box + self._layout.spacing())
                dots.setAlignment(Qt.AlignCenter)
                dots._pg_value = None
                self._page_widgets.append(dots)
                continue
            btn = QToolButton(self)
            btn.setText(str(p))
            btn._pg_value = p
            set_property(btn, "uikPg", "page")
            set_property(btn, "size", self._size)
            self._apply_box(btn)
            set_property(btn, "current",
                         "true" if p == self._current else "false")
            btn.setCursor(Qt.PointingHandCursor)
            btn.clicked.connect(lambda _=False, page=p: self.set_current(page))
            self._page_widgets.append(btn)

    def _nav_button(self, direction: str, enabled: bool, slot) -> QToolButton:
        btn = QToolButton(self)
        set_property(btn, "uikPg", "nav")
        set_property(btn, "size", self._size)
        self._apply_box(btn)
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
        weight = T("font.weight.semibold")
        radius = T("radius.md")
        # 选中强调 2px：与 Tabs 下划线 / NavMenu 左强调条同粗
        # TODO(shared): 建议 tokens.py 补 layout.indicator.w = 2
        indicator = 2
        box = _SIZE_H[self._size]
        # QSS 的 min/max-height 量的是「内容盒」，控件总高 = 内容盒 + 上下边框。
        # 常规态 1px 边框 → 内容盒 = box - 2；选中态为了用 2px 强调边框，
        # 内容盒必须收成 box - 4，两态的外框才都是 box（按钮始终是正方形，
        # 当前页不会比邻居大一圈）。
        content = box - 2
        content_sel = box - 2 * indicator
        self.setStyleSheet(f"""
QToolButton[uikPg="nav"] {{
    border: 1px solid {c('border')};
    background-color: {c('bg.elevated')};
    border-radius: {radius}px;
    padding: 0;
    min-height: {content}px; max-height: {content}px;
}}
QToolButton[uikPg="nav"]:hover:enabled {{
    background-color: {c('bg.muted')};
    border-color: {c('border.strong')};
}}
QToolButton[uikPg="nav"]:disabled {{
    background-color: {c('bg.muted')};
    border-color: {c('border')};
}}
QToolButton[uikPg="page"] {{
    border: 1px solid {c('border')};
    background-color: {c('bg.elevated')};
    color: {c('text.primary')};
    border-radius: {radius}px;
    padding: 0;
    font-size: {T('font.md')}px;
    min-height: {content}px; max-height: {content}px;
}}
QToolButton[uikPg="page"]:hover {{
    background-color: {c('bg.muted')};
    border-color: {c('border.strong')};
    color: {c('text.primary')};
}}
QToolButton[uikPg="page"]:disabled {{
    color: {c('text.disabled')};
    background-color: {c('bg.muted')};
}}
QToolButton[uikPg="page"][current="true"] {{
    border: {indicator}px solid {c('primary')};
    background-color: {c('primary.subtle')};
    color: {c('primary')};
    font-weight: {weight};
    min-height: {content_sel}px; max-height: {content_sel}px;
}}
QToolButton[uikPg="page"][current="true"]:hover {{
    background-color: {c('primary.subtle')};
    color: {c('primary')};
}}
""")
        # 局部样式表改动后必须重新 polish 整棵子树：Qt 只保证「已 polish
        # 过」的控件会重算规则，set_size() 在首次 show 之前调用时，新建的
        # 页码按钮会沿用旧样式表的 min/max-height（实测高度停在 md 档）。
        # unpolish/polish 必须成对出现在同一轮事件处理里，否则 QSS 引用的
        # 图片 / 字体缓存会被提前释放（这里只改尺寸与颜色，不会走到那一步）。
        style = self.style()
        for w in self.findChildren(QWidget):
            style.unpolish(w)
        style.unpolish(self)
        style.polish(self)
        for w in self.findChildren(QWidget):
            style.polish(w)