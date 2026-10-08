# -*- coding: utf-8 -*-
"""锚点导航 Anchor（SPEC §5.3 anchor.py）。

垂直链接列表，配合 QScrollArea 使用：点击滚动到目标段落，
滚动时自动高亮当前段落。

对齐与密度约定（与 COMPONENT-DESIGN-CONTRACT §3 / §4 对齐）：

- **行高 ``layout.nav.row_h``（30）**：与侧边导航行同级，锚点列表
  是导航不是正文，不再是旧版的 26px 自定义值。
- **文字左缘与选中条左缘分离**：2px 指示条贴在容器左缘，文字统一
  从 ``layout.inset.pad_x``（8）起，切换当前项时文字**不会**左右抖动
  （旧版 ``padding: 0 14px`` 让条与文字挤在一起）。
- **扁平**：常态无底色；只有当前项用 ``primary.subtle`` 一层淡底 +
  ``primary`` 指示条，不加投影、不加圆角（竖列列表不需要）。
- QSS 里的所有尺寸取自令牌，无裸数字。
"""

from PySide6.QtCore import QPoint, Qt, Signal
from PySide6.QtWidgets import QPushButton, QScrollArea, QVBoxLayout, QWidget

from ..theme import T, ThemeManager, set_property
from shiboken6 import isValid as _shiboken_is_valid

#: 当前项指示条宽度：1px 细条（border 档位，不加粗）
_INDICATOR_W = 1
#: 滚动命中判定偏移：半行高，避免刚滚过边界就跳项
_SCROLL_LEAD = T("layout.nav.row_h") // 2


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

__all__ = ["Anchor"]


class Anchor(QWidget):
    """锚点导航：配合 QScrollArea 高亮当前滚动到的段落。

    参数:
        parent: 父控件。

    示例::

        anchor = Anchor()
        anchor.set_items([("base", "基本信息"), ("safe", "安全设置")])
        anchor.bind_scroll_area(scroll_area)
    """

    #: 当前锚点变化信号，参数为锚点 key
    currentChanged = Signal(str)

    def __init__(self, parent: QWidget = None):
        super().__init__(parent)
        self._items = []          # [(key, title, target_widget|None)]
        self._buttons = {}        # key -> QPushButton
        self._current = None
        self._scroll_area = None
        self._scroll_conn = None  # 滚动条 valueChanged 连接（重绑时断开）
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(0)
        self._layout.addStretch(1)
        set_property(self, "role", "plain")
        _connect_theme(self, self._reload_style)
        self._reload_style()

    # -- 公开 API ---------------------------------------------------------
    def set_items(self, items) -> None:
        """批量设置锚点。

        参数 ``items`` 为 ``[(key, title)]`` 或
        ``[(key, title, target_widget)]`` 序列。
        """
        for btn in self._buttons.values():
            self._layout.removeWidget(btn)
            btn.deleteLater()
        self._buttons.clear()
        self._items = []
        self._current = None
        for it in items:
            key, title = it[0], it[1]
            target = it[2] if len(it) > 2 else None
            self._append(key, title, target)
        if self._items:
            self.set_current(self._items[0][0])

    def add_item(self, key: str, title: str, target: QWidget = None) -> None:
        """追加一个锚点；``target`` 为滚动区域内的目标控件（可选）。"""
        self._append(key, title, target)
        if self._current is None:
            self.set_current(key)

    def set_target(self, key: str, target: QWidget) -> None:
        """为已有锚点绑定目标控件。"""
        self._items = [(k, t, target if k == key else w)
                       for k, t, w in self._items]

    def bind_scroll_area(self, area: QScrollArea) -> None:
        """绑定滚动区域，滚动时自动高亮当前段落。

        重复绑定时断开旧滚动条的连接，避免旧信号仍驱动高亮
        （行为错位 / 双触发）。
        """
        if self._scroll_area is not None \
                and _shiboken_is_valid(self._scroll_area) \
                and self._scroll_conn is not None:
            try:
                self._scroll_area.verticalScrollBar().valueChanged.disconnect(
                    self._scroll_conn)
            except (RuntimeError, TypeError):
                pass
        self._scroll_area = area
        self._scroll_conn = area.verticalScrollBar().valueChanged.connect(
            self._on_scroll)

    def set_current(self, key: str) -> None:
        """设置当前高亮锚点。"""
        if key == self._current or key not in self._buttons:
            return
        self._current = key
        for k, btn in self._buttons.items():
            set_property(btn, "active", "true" if k == key else "false")
        self.currentChanged.emit(key)

    def current(self) -> str:
        """返回当前锚点 key。"""
        return self._current

    def scroll_to(self, key: str) -> None:
        """滚动到指定锚点对应的目标控件。"""
        if self._scroll_area is None or self._scroll_area.widget() is None:
            return
        for k, _t, target in self._items:
            if k == key and target is not None:
                y = target.mapTo(self._scroll_area.widget(), QPoint(0, 0)).y()
                self._scroll_area.verticalScrollBar().setValue(max(0, y))
                return

    # -- 内部 -------------------------------------------------------------
    def _append(self, key: str, title: str, target: QWidget) -> None:
        btn = QPushButton(title, self)
        btn.setCursor(Qt.PointingHandCursor)
        set_property(btn, "active", "false")
        btn.clicked.connect(lambda _=False, k=key: self._on_click(k))
        self._layout.insertWidget(self._layout.count() - 1, btn)
        self._buttons[key] = btn
        self._items.append((key, title, target))

    def _on_click(self, key: str) -> None:
        self.set_current(key)
        self.scroll_to(key)

    def _on_scroll(self, value: int) -> None:
        area_widget = self._scroll_area.widget() if self._scroll_area else None
        if area_widget is None:
            return
        best = None
        for key, _title, target in self._items:
            if target is None:
                continue
            y = target.mapTo(area_widget, QPoint(0, 0)).y()
            if y <= value + _SCROLL_LEAD:
                best = key
            elif best is None:
                best = key
        if best is not None:
            self.set_current(best)

    def _reload_style(self) -> None:
        c = lambda k: T(f"color.{k}")  # noqa: E731
        row_h = T("layout.nav.row_h")
        pad_x = T("layout.inset.pad_x")
        self.setStyleSheet(f"""
QPushButton {{
    border: none;
    border-left: {_INDICATOR_W}px solid transparent;
    border-radius: 0px;
    background-color: transparent;
    color: {c('text.secondary')};
    text-align: left;
    padding: 0 {pad_x}px;
    min-height: {row_h}px;
    max-height: {row_h}px;
    font-size: {T('font.md')}px;
}}
QPushButton:hover {{ color: {c('primary')}; background-color: {c('bg.subtle')}; }}
QPushButton[active="true"] {{
    color: {c('primary')};
    border-left-color: {c('primary')};
    background-color: {c('primary.subtle')};
    font-weight: {T('font.weight.semibold')};
}}
""")
