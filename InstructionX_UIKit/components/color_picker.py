# -*- coding: utf-8 -*-
"""颜色选择器组件（SPEC §5.1）。

``ColorPicker`` = 自绘色块按钮（点击弹出 QColorDialog）+ 十六进制文本。
色块边长与输入控件共用 ``theme._INPUT_HEIGHTS`` 刻度（sm=22 / md=28 / lg=34），
圆角取 ``radius.sm``，与「日历 / 表格 / 复选框」等小方块元素同档。

本轮修复（轨道 2）：

- **色块尺寸回归刻度**：原私有几何表 ``_EDGE = {sm:24, md:32, lg:40}`` 是
  上一版（未收紧）的输入高度，与同页 ``LineEdit[sm]``（22px）差 2px，
  同行排列时明显错位。现直接只读复用 ``theme._INPUT_HEIGHTS``，
  与其余输入类组件共用唯一刻度来源（契约 §1）。
- **圆角 / 内缩走令牌**：色块圆角 4 与内缩 2 改为 ``T("radius.sm")`` /
  ``T("space.05")``，不再写死。
- 色块与文本之间的间距改为 ``T("layout.inline.gap")``，与页面同行控件
  间距同源。
"""

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QColorDialog, QHBoxLayout, QLabel, QPushButton, QWidget

from ..theme import T, ThemeManager, set_property, _INPUT_HEIGHTS
from ._mixin import SizeMixin

__all__ = ["ColorPicker"]


def _coerce_color(color) -> QColor:
    """把 QColor / 颜色字符串转换为 QColor；无效输入抛中文 ValueError。"""
    qc = QColor(color) if not isinstance(color, QColor) else QColor(color)
    if not qc.isValid():
        raise ValueError(f"无效颜色: {color!r}，应为 QColor 或合法颜色字符串")
    return qc


class _SwatchButton(QPushButton):
    """内部：自绘色块按钮（不用 QSS 背景，直接按当前色绘制）。

    实例级 QSS 只做两件事，都必须在这里做：

    1. **锁死边长**：全局 ``QPushButton`` 的 ``min/max-height`` 优先级高于
       ``setFixedSize``（Qt 样式表同样会覆盖程序化尺寸约束，实测 sm 档会被
       撑回 28px），因此边长必须以 QSS 形式给出。
    2. **清掉底层**：``background: transparent`` + ``border: none``，否则暗色
       主题下 QSS 的 ``bg.elevated`` 会从圆角外侧露出来，色块变成「浅色方块
       + 深色圆角」。

    1px 边框用 ``border.strong``：这是契约 §4「常规分隔用 border」的
    例外——色块颜色由用户任意指定，``border``（亮 #E4E7EC）在白 / 浅灰
    色块上会整块消失，必须用高一档的描边保证「色块边界」始终可见。
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._color = QColor(T("color.primary"))
        self.setCursor(Qt.PointingHandCursor)
        ThemeManager.instance().theme_changed.connect(self.update)

    def set_color(self, color: QColor) -> None:
        self._color = QColor(color)
        self.update()

    def set_edge(self, edge: int) -> None:
        """按令牌刻度锁死色块边长（QSS 盒模型：无边框无内边距时总高即此值）。"""
        self.setFixedSize(edge, edge)
        self.setStyleSheet(
            f"QPushButton {{ min-height: {edge}px; max-height: {edge}px;"
            f" padding: 0; border: none; background: transparent; }}")

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        inset = int(T("space.05"))
        radius = float(T("radius.sm"))
        rect = self.rect().adjusted(inset, inset, -inset, -inset)
        # 色块本体
        p.setPen(Qt.NoPen)
        p.setBrush(self._color if self.isEnabled()
                   else QColor(T("color.text.disabled")))
        p.drawRoundedRect(rect, radius, radius)
        # 边框（深色 / 浅色块上均可见）
        pen_color = QColor(T("color.border.strong"))
        p.setPen(pen_color)
        p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(rect, radius, radius)
        p.end()


class ColorPicker(SizeMixin, QWidget):
    """颜色选择器。

    用途:
        展示并选择颜色：点击色块弹出系统 QColorDialog，
        选择后发射 ``colorChanged`` 并更新色块与十六进制文本。

    参数:
        color: 初始颜色（QColor 或 "#RRGGBB" 字符串）。
        size: ``sm`` / ``md`` / ``lg``，色块边长 22 / 28 / 34（与输入框同刻度）。
        show_text: 是否显示十六进制文本。
        parent: 父控件。

    示例::

        cp = ColorPicker("#3F5E8C", size="md")
        cp.colorChanged.connect(lambda c: print(c.name()))
        cp.set_color(QColor("#3E7E5F"))
    """

    #: 合法尺寸档（SizeMixin 校验用）
    _SIZES = ("sm", "md", "lg")
    _size_label = "颜色选择器"

    #: 颜色变化信号
    colorChanged = Signal(QColor)

    def __init__(self, color="#3F5E8C", size: str = "md",
                 show_text: bool = True, parent=None):
        # 缺省色是**组件的数据默认值**（用户可改的「选中颜色」），不是主题色，
        # 因此不引令牌——UI 本身的颜色（色块描边、圆角、文本）全部走令牌。
        super().__init__(parent)
        self._color = _coerce_color(color)
        self._show_text = show_text
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(int(T("layout.inline.gap")))
        self._swatch = _SwatchButton(self)
        self._swatch.set_color(self._color)
        self._swatch.clicked.connect(self._open_dialog)
        layout.addWidget(self._swatch)
        self._label = QLabel(self._color.name().upper(), self)
        # 次级文字：text.secondary（亮 6.00:1 / 暗 7.62:1，远超 4.5:1）
        set_property(self._label, "role", "secondary")
        layout.addWidget(self._label)
        layout.addStretch(1)
        self.set_size(size)
        if not show_text:
            self._label.hide()

    # ------------------------------------------------------------------
    # 属性
    # ------------------------------------------------------------------

    def color(self) -> QColor:
        """当前颜色。"""
        return QColor(self._color)

    def set_color(self, color) -> None:
        """设置颜色（QColor 或 "#RRGGBB" 字符串），发射 ``colorChanged``。

        无效颜色（如解析失败的字符串）抛中文 ``ValueError``，
        与项目属性校验约定一致；与当前颜色相同时静默忽略。
        """
        color = _coerce_color(color)
        if color == self._color:
            return
        self._color = color
        self._swatch.set_color(color)
        self._label.setText(color.name().upper())
        self.colorChanged.emit(QColor(color))

    def _apply_size(self, size: str) -> None:
        """SizeMixin 钩子：色块边长对齐输入控件刻度。

        控件总高因此也等于该档高度（色块是唯一撑高元素），并锁定
        min / max height，避免被外层布局拉伸成 60px 高——那样「声明的
        ``uiksize``」与「实际渲染高度」就又不一致了（契约 §1）。
        """
        edge = _INPUT_HEIGHTS[size]
        self._swatch.set_edge(edge)
        self.setMinimumHeight(edge)
        self.setMaximumHeight(edge)
        self.updateGeometry()

    def set_show_text(self, on: bool) -> None:
        """设置是否显示十六进制文本。"""
        self._show_text = bool(on)
        self._label.setVisible(on)

    # ------------------------------------------------------------------
    # 弹窗
    # ------------------------------------------------------------------

    def _open_dialog(self) -> None:
        color = QColorDialog.getColor(self._color, self, "选择颜色")
        if color.isValid():
            self.set_color(color)
