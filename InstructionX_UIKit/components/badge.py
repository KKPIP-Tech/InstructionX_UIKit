# -*- coding: utf-8 -*-
"""徽标组件（SPEC §5.2 badge）。

可包裹任意子控件并在其右上角叠加数字 / 红点角标，也可独立使用；
超过最大值显示 ``99+``；自绘实现，亮 / 暗主题实时感知。

实现要点：

1. **角标是 Badge 的独立子控件**（``_Pill``），创建顺序在被包裹控件之后
   并在几何变化时 ``raise_()``，保证绘制层级始终高于被包裹控件（否则角标
   会被子控件盖住——z-order 缺陷）。
2. **包裹模式下 Badge 的高度与宿主一致**（只向右让出角标外溢的一半）。
   若按「角标上下左右各外扩一半」去撑大包裹盒，Badge 就会比宿主高，同一
   行里宿主控件会被顶偏，与相邻控件的中心线 / 基线对不上（实测按钮会下沉
   半个角标高）；角标因此锚在「宿主右缘 - ``space.05``」这条竖线上，
   右半探出包裹盒（包裹盒右侧已预留），纵向落在宿主的 padding 区。
3. **圆角**：数字角标是 pill（半径 = 高度 / 2），红点是整圆。这类计数徽标
   的圆角要跟着自身高度走，用固定 ``radius.sm`` 会在高度变化后出现
   「胶囊两端不平」或「圆角大于半高」；``radius.sm`` 只用于矩形型小标签。
4. 角标宽度由绘制字体的真实文本宽度加水平内边距决定（最小为高度，形成
   pill 圆角），保证 ``99+`` 等宽文本完整显示。
"""

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter
from PySide6.QtWidgets import QVBoxLayout, QWidget

from InstructionX_UIKit.theme import T, ThemeManager

__all__ = ["Badge"]

#: 角标角色 -> 颜色令牌
_COLOR_KEYS = {
    "danger": "color.danger",
    "primary": "color.primary",
    "success": "color.success",
    "warning": "color.warning",
}

#: 数字角标高度 = 2 × space.2（16px）。必须取偶数倍令牌：一半就是
#: space.2，正好是令牌值——早前用 18px 时 ``_PILL_H // 2`` 得到 9px，
#: 直接把非令牌内边距写进了布局。
_PILL_H = T("space.2") * 2
#: 红点直径
_DOT_D = T("space.2")
#: 数字角标单侧水平内边距（保证文本不顶边）
_PAD_X = T("space.1")
#: 角标距包裹盒右缘 / 顶缘的内缩（不压宿主按钮的圆角描边）
_CORNER_INSET = T("space.05")


class _Pill(QWidget):
    """角标本体（Badge 的顶层子控件，自绘数字 / 红点）。

    作为独立子控件浮于被包裹控件之上绘制，避免"父控件 paintEvent
    绘制、被子控件遮挡"的 z-order 问题；鼠标事件穿透，不干扰被包裹
    控件的交互。
    """

    def __init__(self, badge: "Badge"):
        super().__init__(badge)
        self._badge = badge
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)

    def paintEvent(self, event) -> None:
        badge = self._badge
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = self.rect()
        color = QColor(T(_COLOR_KEYS[badge._color_role]))
        painter.setPen(Qt.NoPen)
        painter.setBrush(color)
        h = rect.height()
        # pill 半径 = 高度一半：计数徽标的圆角随自身高度，不取固定档位
        painter.drawRoundedRect(rect, h / 2, h / 2)
        if not badge._dot:
            painter.setPen(QColor(T("color.on.primary")))
            painter.setFont(badge._text_font())
            painter.drawText(rect, Qt.AlignCenter, badge._text())
        painter.end()


class Badge(QWidget):
    """数字 / 红点徽标。

    参数:
        widget: 被包裹的子控件（可选；不传则为独立角标）。
        count: 角标数字。
        max_count: 上限，超出显示 ``{max}+``，默认 99。
        dot: 红点模式（不显示数字）。
        color: ``"danger"`` / ``"primary"`` / ``"success"`` / ``"warning"``。
        parent: 父控件。

    示例::

        badge = Badge(QPushButton("消息"), count=5)
        badge.set_count(120)            # 显示 99+
        dot = Badge(dot=True)           # 独立红点
    """

    def __init__(self, widget=None, count: int = 0, max_count: int = 99,
                 dot: bool = False, color: str = "danger", parent=None):
        super().__init__(parent)
        self._count = int(count)
        self._max = int(max_count)
        self._dot = bool(dot)
        self._show_zero = False
        self._color_role = "danger"
        self._pill = None
        self.set_color(color)
        self._child = None
        self._layout = QVBoxLayout(self)
        # 包裹盒只在右侧为角标留出外溢空间（_layout_margins），高度照宿主，
        # 因此行内垂直居中仍然成立（见模块文档第 2 条）。
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(0)
        if widget is not None:
            self.set_widget(widget)
        # 角标最后创建：位于 children 末尾（绘制层级顶层）
        self._pill = _Pill(self)
        ThemeManager.instance().theme_changed.connect(self._on_theme_changed)
        self._sync_pill()

    # ------------------------------------------------------------------ 配置
    def set_widget(self, widget: QWidget) -> None:
        """设置被包裹的子控件（角标锚在其右上角，右半探出宿主右缘）。"""
        if self._child is not None:
            self._layout.removeWidget(self._child)
            self._child.setParent(None)
        self._child = widget
        self._layout.addWidget(widget)
        if self._pill is not None:
            # 重新挂到 children 末尾：换绑子控件后角标仍是最后（顶层）子控件
            self._pill.setParent(None)
            self._pill.setParent(self)
        self.updateGeometry()
        self._sync_pill()

    def child(self):
        """返回被包裹的子控件（可能为 None）。"""
        return self._child

    def set_count(self, count: int) -> None:
        """设置角标数字。"""
        self._count = max(0, int(count))
        self._sync_pill()

    def count(self) -> int:
        return self._count

    def set_max_count(self, max_count: int) -> None:
        """设置数字上限，超出显示 ``{max}+``。"""
        self._max = max(1, int(max_count))
        self._sync_pill()

    def max_count(self) -> int:
        return self._max

    def set_dot(self, dot: bool) -> None:
        """切换红点模式（不显示数字）。"""
        self._dot = bool(dot)
        self._sync_pill()

    def is_dot(self) -> bool:
        return self._dot

    def set_show_zero(self, show: bool) -> None:
        """数字为 0 时是否仍显示角标。"""
        self._show_zero = bool(show)
        self._sync_pill()

    def set_color(self, color: str) -> None:
        """设置角标颜色角色：danger/primary/success/warning。"""
        if color not in _COLOR_KEYS:
            raise ValueError(f"未知角标颜色: {color!r}")
        self._color_role = color
        self._sync_pill()

    # ------------------------------------------------------------------ 几何
    def _visible(self) -> bool:
        return self._dot or self._count > 0 or self._show_zero

    def _text(self) -> str:
        if self._count > self._max:
            return f"{self._max}+"
        return str(self._count)

    def _text_font(self) -> QFont:
        """角标数字的绘制字体（测量与绘制共用，保证宽度一致）。"""
        font = QFont(self.font())
        font.setPixelSize(T("font.xs"))
        return font

    def _pill_width(self) -> int:
        """角标宽度：min-width = 高度，文本超宽时横向扩展。"""
        if self._dot:
            return _DOT_D
        fm = QFontMetrics(self._text_font())
        return max(_PILL_H, fm.horizontalAdvance(self._text()) + 2 * _PAD_X)

    def _breathing(self) -> int:
        """独立模式下的等边呼吸留白（令牌值，不用裸数字）。"""
        return T("space.1")

    def _overhang_x(self) -> int:
        """包裹盒右侧为角标预留的外溢宽度 = 半个角标，向上取到 2px 基网格。

        必须按角标的**实际宽度**算。早先取 ``max(_PILL_H, _pill_width())``：
        红点宽 8px 却按 ``_PILL_H``=16 预留，右边多让出 4px，圆心被推到
        宿主右缘**外侧** 2px；而数字角标又因向上取整落在**内侧** 1~2px。
        数字、红点于是各站各的位置，一眼看就是错位。
        """
        half = self._pill_width() / 2.0
        return int(-(-half // 2) * 2)

    def _layout_margins(self):
        """包裹盒的外扩边距：右（上）各留半个角标，让角标有一半探出宿主。

        **只向外扩右侧**、高度保持与宿主一致——若上下也扩，包裹盒就比宿主
        高，同一行里宿主控件会被顶偏，与相邻控件的中心线对不上（这正是
        本组件此前的问题）。
        """
        if self._child is None:
            return (0, 0, 0, 0)
        overhang = self._overhang_x()
        return (0, 0, overhang, 0)

    def sizeHint(self) -> QSize:
        if self._child is not None:
            # 高度照宿主，宽度只加右侧外溢：行内垂直居中由宿主决定
            base = self._child.sizeHint()
            return QSize(base.width() + self._overhang_x(), base.height())
        if self._dot:
            d = self._breathing()
            return QSize(_DOT_D + d * 2, _DOT_D + d * 2)
        w, h = self._pill_width(), _PILL_H
        d = self._breathing()
        return QSize(w + d * 2, h + d * 2)

    def minimumSizeHint(self) -> QSize:
        return self.sizeHint()

    # ------------------------------------------------------------------ 角标同步
    def _sync_pill(self) -> None:
        """按当前状态刷新角标几何 / 可见性，并保持绘制顶层。"""
        if self._pill is None:
            return
        want = self._layout_margins()
        cur = self._layout.contentsMargins()
        if (cur.left(), cur.top(), cur.right(), cur.bottom()) != tuple(want):
            self._layout.setContentsMargins(*want)
        if not self._visible():
            self._pill.hide()
            return
        w = self._pill_width()
        h = _DOT_D if self._dot else _PILL_H
        if self._child is not None:
            # 铁律：角标圆心精确落在宿主右缘上，左右各探出一半。
            # 这里直接用宿主实际几何算，不再拿「包裹盒宽 - 内缩 - 宽度」凑
            # —— 那条式子里的 _CORNER_INSET 会把锚点整体推开，与 2px 网格
            # 取整叠加后产生 ±2px 的漂移。
            ch_right = self._child.x() + self._child.width()
            max_h = self.height() - _CORNER_INSET * 2
            if max_h > 0:
                h = min(h, max_h)
            w = min(w, self.width())
            x = ch_right - w / 2.0
            y = _CORNER_INSET
        else:
            x = (self.width() - w) / 2
            y = (self.height() - h) / 2
        self._pill.setGeometry(round(x), round(y), w, h)
        self._pill.show()
        self._pill.raise_()  # 保持顶层：不被被包裹控件遮挡
        self._pill.update()

    def _on_theme_changed(self, _mode) -> None:
        self._sync_pill()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._sync_pill()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._sync_pill()