# -*- coding: utf-8 -*-
"""图标按钮组件（SPEC §5.1）。

``IconButton`` 基于 QToolButton，支持 QIcon 图标或单字符文本符号，
通过动态属性命中全局 QSS 的变体 / 尺寸 / 形状选择器。
"""

from PySide6.QtCore import QPointF, QSize, Qt
from PySide6.QtGui import QFontMetricsF, QIcon, QPainter
from PySide6.QtWidgets import QStyle, QStyleOptionToolButton, QToolButton

from ..theme import set_property

__all__ = ["IconButton"]

_VARIANTS = (None, "default", "primary", "danger")
_SIZES = ("sm", "md", "lg")
_SHAPES = (None, "circle", "round")
#: 各尺寸档的控件边长（px）
_EDGE = {"sm": 24, "md": 32, "lg": 40}
#: 各尺寸档的图标边长（px）
_ICON = {"sm": 14, "md": 16, "lg": 20}

#: 实例级 QSS：图标按钮无文本，清零内边距使总高严格等于尺寸档边长。
#: 全局 QSS 的 ``padding: 4px`` / ``padding: 0 12px`` 会让 min-height（内容盒）
#: 额外加上 padding，透明变体总高变为 edge+8（如 md 圆形 32x40），破坏正圆
#: 并使视觉中心相对期望几何中心偏移。属性选择器版本用于压过全局变体规则。
_INSTANCE_QSS = """
QToolButton { padding: 0px; }
QToolButton[variant="primary"] { padding: 0px; }
QToolButton[variant="default"] { padding: 0px; }
QToolButton[variant="danger"] { padding: 0px; }
"""


class IconButton(QToolButton):
    """图标按钮。

    用途:
        仅含图标（QIcon）或单个文本符号（如 ``+``、``×``）的紧凑按钮，
        常用于工具栏、卡片操作区。支持变体、尺寸与圆形 / 胶囊形状。

    参数:
        icon: QIcon 实例；为 None 时使用 ``text`` 作为文本符号。
        text: 文本符号（未提供 icon 时显示）。
        variant: ``None``（透明底）/ ``default`` / ``primary`` / ``danger``。
        size: ``sm`` / ``md`` / ``lg``，对应边长 24 / 32 / 40。
        shape: ``None`` / ``"circle"``（正圆，宽 = 高）/ ``"round"``。
        parent: 父控件。

    示例::

        add = IconButton(text="+", variant="primary", shape="circle")
        gear = IconButton(icon=QIcon(":/icons/gear.svg"), size="sm")
        close = IconButton(text="×", variant="danger")
    """

    def __init__(self, icon: QIcon = None, text: str = "", variant: str = None,
                 size: str = "md", shape: str = None, parent=None):
        super().__init__(parent)
        self.setCursor(Qt.PointingHandCursor)
        self.setStyleSheet(_INSTANCE_QSS)
        self._size = "md"
        self._shape = None
        if icon is not None and not icon.isNull():
            self.setIcon(icon)
        elif text:
            self.setText(text)
        if variant is not None:
            self.set_variant(variant)
        self.set_size(size)
        if shape is not None:
            self.set_shape(shape)

    # ------------------------------------------------------------------
    # 属性
    # ------------------------------------------------------------------

    def set_variant(self, variant: str) -> None:
        """设置变体：``default`` / ``primary`` / ``danger``。"""
        if variant not in _VARIANTS:
            raise ValueError(f"未知图标按钮变体: {variant!r}")
        set_property(self, "variant", variant if variant else "none")

    def variant(self) -> str:
        """当前变体名（未设置时返回空串）。"""
        v = self.property("variant")
        return "" if v in (None, "none") else v

    def set_size(self, size: str) -> None:
        """设置尺寸档：``sm`` / ``md`` / ``lg``。"""
        if size not in _SIZES:
            raise ValueError(f"未知图标按钮尺寸: {size!r}")
        self._size = size
        set_property(self, "size", size)
        self.setIconSize(QSize(_ICON[size], _ICON[size]))
        self._apply_shape_geometry()

    def size_name(self) -> str:
        """当前尺寸档名。"""
        return self._size

    def set_shape(self, shape) -> None:
        """设置形状：``None`` / ``"circle"`` / ``"round"``。"""
        if shape not in _SHAPES:
            raise ValueError(f"未知图标按钮形状: {shape!r}")
        self._shape = shape
        set_property(self, "shape", shape if shape else "none")
        self._apply_shape_geometry()

    def _apply_shape_geometry(self) -> None:
        """圆形时固定为正方形（宽 = 高 = 尺寸档边长），其余形状最小同宽。"""
        edge = _EDGE[self._size]
        if self._shape == "circle":
            self.setFixedSize(edge, edge)
        else:
            # 高度由全局 QSS 的 min/max-height（padding 已清零）精确控制；
            # 最小宽度对齐边长，保证图标按钮近似方形的可点击区域。
            self.setMinimumSize(edge, 0)
            self.setMaximumSize(16777215, 16777215)

    # ------------------------------------------------------------------
    # 内容设置
    # ------------------------------------------------------------------

    def set_icon(self, icon: QIcon) -> None:
        """设置 QIcon 图标（与文本符号二选一，后者会被清空）。"""
        self.setText("")
        self.setIcon(icon)

    def set_symbol(self, text: str) -> None:
        """设置文本符号（与图标二选一，前者会被清空）。"""
        self.setIcon(QIcon())
        self.setText(text)

    # ------------------------------------------------------------------
    # 绘制：文本符号按墨迹盒精确居中（QIcon 由样式绘制，天然居中）
    # ------------------------------------------------------------------
    #
    # 根因：QToolButton 样式按字体行高盒（含 ascent/descent 空白）居中
    # 文本，而可见墨迹（如 +、×）在行高盒内偏上，导致视觉中心下移
    # 1~1.5px。此处背景仍交给样式绘制，文本符号改用 tightBoundingRect
    # 求墨迹中心后自绘，保证任意尺寸 / 形状下精确居中。

    def paintEvent(self, event) -> None:
        """图标走样式默认绘制；纯文本符号自绘并按墨迹居中。"""
        if not self.icon().isNull() or not self.text():
            super().paintEvent(event)
            return
        p = QPainter(self)
        opt = QStyleOptionToolButton()
        self.initStyleOption(opt)
        opt.text = ""  # 仅绘制背景 / 边框 / 状态
        self.style().drawComplexControl(QStyle.CC_ToolButton, opt, p, self)
        font = self.font()
        font.setPixelSize(_ICON[self._size])
        p.setFont(font)
        metrics = QFontMetricsF(font)
        ink = metrics.tightBoundingRect(self.text())
        # drawText 的锚点是 (left, baseline)，ink 相对该点定位；
        # 反向平移使墨迹盒中心与控件几何中心重合。
        cx = self.width() / 2.0
        cy = self.height() / 2.0
        p.setPen(self.palette().color(self.foregroundRole()))
        p.drawText(QPointF(cx - ink.center().x(), cy - ink.center().y()),
                   self.text())
        p.end()
