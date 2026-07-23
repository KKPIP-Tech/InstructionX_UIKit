# -*- coding: utf-8 -*-
"""分段控制器组件（SPEC §5.1）。

``SegmentedControl`` 全自绘：圆角底槽 + 滑动指示块（位置 / 宽度经
QPropertyAnimation 平滑过渡，时长 / 缓动取设计令牌）。
"""

from PySide6.QtCore import (
    Property,
    QParallelAnimationGroup,
    QPropertyAnimation,
    QRectF,
    QSize,
    Qt,
    Signal,
)
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QWidget

from ..theme import T, ThemeManager, set_property
from ..tokens import DURATION, EASING, TokenState

__all__ = ["SegmentedControl"]

_SIZES = ("sm", "md", "lg")
_HEIGHT = {"sm": 24, "md": 32, "lg": 40}
_PAD = 2.0        # 底槽内边距
_ITEM_HP = 16.0   # 分段文字左右留白


class SegmentedControl(QWidget):
    """分段控制器。

    用途:
        在 2 个及以上互斥选项间切换（如日 / 周 / 月视图），
        选中指示块随点击平滑滑动。

    参数:
        items: 分段文案列表。
        current: 初始选中下标。
        size: ``sm`` / ``md`` / ``lg``，高度 24 / 32 / 40。
        parent: 父控件。

    示例::

        seg = SegmentedControl(["日", "周", "月"], current=1)
        seg.currentChanged.connect(lambda i: print("切换到:", i))
        seg.set_current(2)
    """

    #: 选中下标变化信号
    currentChanged = Signal(int)

    def __init__(self, items=(), current: int = 0, size: str = "md",
                 parent=None):
        super().__init__(parent)
        self._items = []
        self._enabled = []
        self._current = -1
        self._thumb_x = 0.0
        self._thumb_w = 0.0
        self._size_name = "md"
        self.set_size(size)
        if items:
            self.set_items(items)
        if self._items:
            self.set_current(min(max(0, current), len(self._items) - 1),
                             animate=False)
        ThemeManager.instance().theme_changed.connect(self.update)
        # set_token 会话覆盖时重绘（QSS 不感知令牌覆盖，自绘需监听）
        TokenState.instance().token_changed.connect(self.update)

    # ------------------------------------------------------------------
    # Qt 属性（供 QPropertyAnimation 驱动）
    # ------------------------------------------------------------------

    def _get_thumb_x(self) -> float:
        return self._thumb_x

    def _set_thumb_x(self, v: float) -> None:
        self._thumb_x = float(v)
        self.update()

    def _get_thumb_w(self) -> float:
        return self._thumb_w

    def _set_thumb_w(self, v: float) -> None:
        self._thumb_w = float(v)
        self.update()

    thumbX = Property(float, _get_thumb_x, _set_thumb_x)
    thumbW = Property(float, _get_thumb_w, _set_thumb_w)

    # ------------------------------------------------------------------
    # 数据接口
    # ------------------------------------------------------------------

    def set_items(self, items) -> None:
        """整体替换分段文案列表。"""
        self._items = [str(x) for x in items]
        self._enabled = [True] * len(self._items)
        self._current = -1
        if self._items:
            self.set_current(0, animate=False)
        self.updateGeometry()
        self.update()

    def add_item(self, text: str) -> None:
        """追加一个分段。"""
        self._items.append(str(text))
        self._enabled.append(True)
        if self._current < 0:
            self.set_current(0, animate=False)
        self.updateGeometry()
        self.update()

    def set_item_enabled(self, index: int, enabled: bool) -> None:
        """启用 / 禁用某个分段。"""
        if 0 <= index < len(self._items):
            self._enabled[index] = bool(enabled)
            self.update()

    def count(self) -> int:
        """分段数量。"""
        return len(self._items)

    def current(self) -> int:
        """当前选中下标。"""
        return self._current

    def current_text(self) -> str:
        """当前选中文案。"""
        if 0 <= self._current < len(self._items):
            return self._items[self._current]
        return ""

    def set_current(self, index: int, animate: bool = True) -> None:
        """选中指定分段（默认滑动动画过渡）。"""
        if not (0 <= index < len(self._items)):
            return
        if not self._enabled[index]:
            return
        changed = index != self._current
        self._current = index
        x, w = self._thumb_target(index)
        if animate and changed:
            group = QParallelAnimationGroup(self)
            for prop, target in ((b"thumbX", x), (b"thumbW", w)):
                anim = QPropertyAnimation(self, prop, self)
                anim.setDuration(DURATION["normal"])
                anim.setEasingCurve(EASING["standard"])
                anim.setStartValue(getattr(self, prop.decode()))
                anim.setEndValue(target)
                group.addAnimation(anim)
            group.start(QParallelAnimationGroup.DeleteWhenStopped)
            self._anim_group = group  # 防 GC
        else:
            self._thumb_x, self._thumb_w = x, w
            self.update()
        if changed:
            self.currentChanged.emit(index)

    def set_size(self, size: str) -> None:
        """设置尺寸档：``sm`` / ``md`` / ``lg``。"""
        if size not in _SIZES:
            raise ValueError(f"未知分段控制器尺寸: {size!r}")
        self._size_name = size
        set_property(self, "size", size)
        self.setFixedHeight(_HEIGHT[size])
        self.updateGeometry()

    def size_name(self) -> str:
        """当前尺寸档名。"""
        return self._size_name

    # ------------------------------------------------------------------
    # 几何
    # ------------------------------------------------------------------

    def _item_widths(self) -> list:
        fm = self.fontMetrics()
        return [fm.horizontalAdvance(t) + _ITEM_HP * 2 for t in self._items]

    def _item_rects(self) -> list:
        rects = []
        x = _PAD
        for w in self._item_widths():
            rects.append(QRectF(x, _PAD, w, self.height() - _PAD * 2))
            x += w
        return rects

    def _thumb_target(self, index: int):
        rects = self._item_rects()
        rect = rects[index]
        return rect.x(), rect.width()

    def sizeHint(self) -> QSize:
        w = sum(self._item_widths()) + _PAD * 2 if self._items else 120
        return QSize(int(w), _HEIGHT[self._size_name])

    def minimumSizeHint(self) -> QSize:
        return self.sizeHint()

    # ------------------------------------------------------------------
    # 交互
    # ------------------------------------------------------------------

    def mousePressEvent(self, event):
        if event.button() != Qt.LeftButton or not self.isEnabled():
            return
        x = event.position().x()
        for i, rect in enumerate(self._item_rects()):
            if rect.contains(event.position()) and self._enabled[i]:
                self.set_current(i)
                break

    # ------------------------------------------------------------------
    # 绘制
    # ------------------------------------------------------------------

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        radius = h / 2.0 if h <= 24 else 6.0
        # 底槽
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(T("color.bg.muted")))
        p.drawRoundedRect(0, 0, w, h, radius, radius)
        # 指示块
        if 0 <= self._current < len(self._items) and self._thumb_w > 0:
            thumb = QRectF(self._thumb_x, _PAD, self._thumb_w, h - _PAD * 2)
            p.setBrush(QColor(T("color.bg.elevated")))
            p.drawRoundedRect(thumb, 4.0, 4.0)
            p.setPen(QColor(T("color.border.strong")))
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(thumb, 4.0, 4.0)
        # 文案
        font = p.font()
        p.setFont(font)
        for i, rect in enumerate(self._item_rects()):
            if not self.isEnabled() or not self._enabled[i]:
                color = QColor(T("color.text.disabled"))
            elif i == self._current:
                color = QColor(T("color.text.primary"))
            else:
                color = QColor(T("color.text.secondary"))
            p.setPen(color)
            p.drawText(rect, Qt.AlignCenter, self._items[i])
        p.end()
