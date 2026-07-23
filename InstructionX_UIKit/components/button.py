# -*- coding: utf-8 -*-
"""按钮组件（SPEC §5.1）。

``Button`` 基于 QPushButton 子类化，通过动态属性命中全局 QSS 的
变体 / 尺寸 / 形状选择器（见 ``InstructionX_UIKit.theme.build_qss``），
并额外提供 loading（自绘旋转弧）与 block（撑满父布局）能力。
"""

from PySide6.QtCore import Qt, QVariantAnimation, QPointF, QRectF
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QPainter, QPen
from PySide6.QtWidgets import QPushButton, QSizePolicy, QStyle, QStyleOptionButton, QStylePainter

from ..theme import T, ThemeManager, set_property
from ..tokens import DURATION, EASING

__all__ = ["Button"]

#: 合法变体
_VARIANTS = ("default", "primary", "dashed", "text", "link", "danger")
_SIZES = ("sm", "md", "lg")
_SHAPES = ("circle", "round")
#: 旋转弧直径（按尺寸档）
_ARC_D = {"sm": 12, "md": 14, "lg": 16}


class Button(QPushButton):
    """按钮。

    用途:
        触发操作的按钮，支持 6 种变体、3 档尺寸、圆形 / 胶囊形状、
        加载中状态（禁用交互并自绘旋转弧）与 block 撑满模式。

    参数:
        text: 按钮文案。
        variant: ``default`` / ``primary`` / ``dashed`` / ``text`` / ``link`` / ``danger``。
        size: ``sm`` / ``md`` / ``lg``，高度 24 / 32 / 40。
        shape: ``None`` / ``"circle"`` / ``"round"``。
        block: 为 True 时水平方向撑满父布局。
        loading: 初始是否为加载中状态。
        parent: 父控件。

    示例::

        ok = Button("确定", variant="primary", size="md")
        ok.set_loading(True)                # 显示旋转弧并屏蔽点击
        more = Button("查看更多", variant="link")
    """

    def __init__(self, text: str = "", variant: str = "default", size: str = "md",
                 shape: str = None, block: bool = False, loading: bool = False,
                 parent=None):
        super().__init__(text, parent)
        self._loading = False
        self._angle = 0.0
        self._spin = QVariantAnimation(self)
        self._spin.setStartValue(0.0)
        self._spin.setEndValue(360.0)
        self._spin.setDuration(DURATION["slower"] * 2)
        self._spin.setLoopCount(-1)  # 无限循环
        self._spin.setEasingCurve(EASING["linear"])
        self._spin.valueChanged.connect(self._on_spin)
        self.setCursor(Qt.PointingHandCursor)
        self.set_variant(variant)
        self.set_size(size)
        if shape is not None:
            self.set_shape(shape)
        self.set_block(block)
        if loading:
            self.set_loading(True)
        ThemeManager.instance().theme_changed.connect(self.update)

    # ------------------------------------------------------------------
    # 属性
    # ------------------------------------------------------------------

    def set_variant(self, variant: str) -> None:
        """设置按钮变体（见构造参数说明）。"""
        if variant not in _VARIANTS:
            raise ValueError(f"未知按钮变体: {variant!r}")
        set_property(self, "variant", variant)

    def variant(self) -> str:
        """当前变体名。"""
        return self.property("variant") or "default"

    def set_size(self, size: str) -> None:
        """设置尺寸档：``sm`` / ``md`` / ``lg``。"""
        if size not in _SIZES:
            raise ValueError(f"未知按钮尺寸: {size!r}")
        set_property(self, "size", size)

    def size_name(self) -> str:
        """当前尺寸档名。"""
        return self.property("uiksize") or "md"

    def set_shape(self, shape) -> None:
        """设置形状：``None`` / ``"circle"`` / ``"round"``。"""
        if shape is not None and shape not in _SHAPES:
            raise ValueError(f"未知按钮形状: {shape!r}")
        set_property(self, "shape", shape if shape else "none")

    def set_block(self, block: bool) -> None:
        """设置是否水平撑满父布局。"""
        policy = QSizePolicy.Expanding if block else QSizePolicy.Preferred
        self.setSizePolicy(policy, QSizePolicy.Fixed)

    def is_loading(self) -> bool:
        """是否处于加载中状态。"""
        return self._loading

    def set_loading(self, loading: bool) -> None:
        """切换加载中状态：显示旋转弧并屏蔽鼠标 / 键盘触发。"""
        loading = bool(loading)
        if loading == self._loading:
            return
        self._loading = loading
        if loading:
            self._spin.start()
        else:
            self._spin.stop()
        self.updateGeometry()
        self.update()

    # ------------------------------------------------------------------
    # 加载中屏蔽交互
    # ------------------------------------------------------------------

    def mousePressEvent(self, event):
        if self._loading:
            event.ignore()
            return
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        if self._loading:
            event.ignore()
            return
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event):
        if self._loading:
            event.ignore()
            return
        super().keyPressEvent(event)

    # ------------------------------------------------------------------
    # 绘制
    # ------------------------------------------------------------------

    def _on_spin(self, value) -> None:
        self._angle = float(value)
        self.update()

    def sizeHint(self):
        hint = super().sizeHint()
        if self._loading:
            # 为旋转弧预留宽度
            d = _ARC_D.get(self.size_name(), 14)
            hint.setWidth(hint.width() + d + 6)
        return hint

    def _content_color(self) -> QColor:
        """按变体推导 loading 文本 / 弧线颜色。"""
        if not self.isEnabled():
            return QColor(T("color.text.disabled"))
        v = self.variant()
        if v in ("primary", "danger"):
            return QColor(T("color.on.primary"))
        if v == "link":
            return QColor(T("color.primary"))
        return QColor(T("color.text.primary"))

    def _ink_centered_text(self) -> bool:
        """圆形 + 纯文本短文本（≤2 字符，如 "+"）时按墨迹盒自绘居中。

        样式按字体行高盒（含 ascent/descent 空白）居中文本，"+" 等符号
        的可见墨迹在行高盒内偏上，垂直方向会偏 1~2px；圆形按钮尺寸小、
        无留白缓冲，偏移肉眼可见。参照 ``icon_button.py`` 的方案：背景 /
        边框 / 状态仍交给样式绘制，文本改用 ``tightBoundingRect`` 墨迹盒
        自绘，保证水平 + 垂直精确居中。``round`` 胶囊与普通按钮不受影响。
        """
        text = self.text()
        return (self.property("shape") == "circle" and 0 < len(text) <= 2
                and self.icon().isNull())

    def paintEvent(self, event):
        if not self._loading and self._ink_centered_text():
            # 1) 交给样式表绘制按钮底板（背景 / 边框 / 圆角 / 焦点态）
            painter = QStylePainter(self)
            opt = QStyleOptionButton()
            self.initStyleOption(opt)
            opt.text = ""
            painter.drawControl(QStyle.CE_PushButton, opt)
            painter.end()
            # 2) 按墨迹盒自绘短文本：drawText 锚点为 (left, baseline)，
            #    ink 相对该点定位，反向平移使墨迹中心与几何中心重合。
            #    注意需关闭字体 hinting：默认 hinting 会把字形按整像素
            #    网格吸附，渲染结果相对 tightBoundingRect 的设计度量上移
            #    ~0.5px；PreferNoHinting 下渲染墨迹与度量一致，居中精度
            #    达亚像素级（实测偏差 < 0.1px）。
            font = QFont(self.font())
            font.setHintingPreference(QFont.PreferNoHinting)
            p = QPainter(self)
            p.setRenderHint(QPainter.TextAntialiasing)
            p.setFont(font)
            metrics = QFontMetricsF(font)
            ink = metrics.tightBoundingRect(self.text())
            cx = self.width() / 2.0
            cy = self.height() / 2.0
            p.setPen(self.palette().color(self.foregroundRole()))
            p.drawText(QPointF(cx - ink.center().x(), cy - ink.center().y()),
                       self.text())
            p.end()
            return
        if not self._loading:
            super().paintEvent(event)
            return
        # 1) 交给样式表绘制按钮底板（背景 / 边框 / 圆角）
        painter = QStylePainter(self)
        opt = QStyleOptionButton()
        self.initStyleOption(opt)
        opt.text = ""
        painter.drawControl(QStyle.CE_PushButtonBevel, opt)
        painter.end()
        # 2) 自绘旋转弧 + 文本
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        color = self._content_color()
        d = _ARC_D.get(self.size_name(), 14)
        gap = 6
        text_w = p.fontMetrics().horizontalAdvance(self.text())
        total = d + gap + text_w
        x0 = (self.width() - total) / 2.0
        cy = self.height() / 2.0
        # 旋转弧（270 度开口弧，随角度旋转）
        pen = QPen(color)
        pen.setWidth(2)
        pen.setCapStyle(Qt.RoundCap)
        p.setPen(pen)
        arc_rect = QRectF(x0, cy - d / 2.0, d, d)
        p.drawArc(arc_rect, int(self._angle * 16), 270 * 16)
        # 文本
        p.setPen(color)
        text_rect = QRectF(x0 + d + gap, 0, text_w + 2, self.height())
        p.drawText(text_rect, Qt.AlignVCenter | Qt.AlignLeft, self.text())
        p.end()
