# -*- coding: utf-8 -*-
"""星级评分组件（SPEC §5.1）。

``Rating`` 全自绘五角星，支持半星模式、只读展示与鼠标悬停预览；
数值变化经 QVariantAnimation 平滑过渡（时长 / 缓动取设计令牌）。

本轮修复（轨道 2）：

- **补齐 sm / md / lg 尺寸档**：此前只有 ``star_size`` 一个裸像素参数，
  组件高度恒为 20px，与同行的 ``LineEdit``（22 / 28 / 34）中心对不齐。
  现接入 :class:`~InstructionX_UIKit.components._mixin.SizeMixin`，
  星径按档位取 ``space.4 / 5 / 6``（16 / 20 / 24），控件高度恒等于
  ``theme._INPUT_HEIGHTS``，同行控件垂直居中且声明档位 == 实际高度。
- **空星对比度达标**：空星原用 ``text.disabled``（亮 2.04:1 / 暗 2.52:1，
  低于契约 §5 对装饰性元素的 3:1 下限），改用 ``text.tertiary``
  （亮 3.41:1 / 暗 4.14:1）；禁用态仍用 ``text.disabled``（禁用态豁免）。
- 星间距由裸数字 4 改为 ``T("space.1")``。
"""

import math

from PySide6.QtCore import Qt, QVariantAnimation, QSize
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPolygonF
from PySide6.QtCore import QPointF, Signal
from PySide6.QtWidgets import QWidget

from ..theme import T, ThemeManager, _INPUT_HEIGHTS
from ..tokens import DURATION, EASING, TokenState
from ._mixin import SizeMixin

__all__ = ["Rating"]

#: 各尺寸档的星外接直径（令牌值），与档位高度成固定比例（高 − 2×space.1）
_STAR_TOKEN = {"sm": "space.4", "md": "space.5", "lg": "space.6"}


def _star_polygon(cx: float, cy: float, r: float) -> QPolygonF:
    """以 (cx, cy) 为中心、外接半径 r 的五角星多边形。"""
    pts = []
    inner = r * 0.42
    for i in range(10):
        radius = r if i % 2 == 0 else inner
        angle = -math.pi / 2 + i * math.pi / 5
        pts.append(QPointF(cx + radius * math.cos(angle),
                           cy + radius * math.sin(angle)))
    return QPolygonF(pts)


class Rating(SizeMixin, QWidget):
    """星级评分。

    用途:
        打分输入或只读展示；可选半星精度，值变化带平滑过渡动画。

    参数:
        count: 星星总数。
        value: 初始分值。
        allow_half: 是否允许半星（0.5 步进）。
        read_only: 只读展示（不响应鼠标）。
        star_size: 自定义星外接直径（px）；缺省按尺寸档取令牌值。超出当前
            档位可容纳范围时会收敛到「档位高 − 2×``space.1``」。
        size: ``sm`` / ``md`` / ``lg``，控件高度 22 / 28 / 34（与输入框同刻度）。
        parent: 父控件。

    示例::

        r = Rating(count=5, value=3.5, allow_half=True)
        r.valueChanged.connect(lambda v: print("评分:", v))
        r.set_value(4.0)
        r.set_size("lg")
    """

    #: 合法尺寸档（SizeMixin 校验用）
    _SIZES = ("sm", "md", "lg")
    _size_label = "评分"

    #: 分值变化信号（提交后发射，参数为 float 分值）
    valueChanged = Signal(float)

    def __init__(self, count: int = 5, value: float = 0.0,
                 allow_half: bool = False, read_only: bool = False,
                 star_size: int = None, size: str = "md", parent=None):
        super().__init__(parent)
        self._count = max(1, int(count))
        self._allow_half = bool(allow_half)
        self._read_only = bool(read_only)
        self._star_request = None if star_size is None else int(star_size)
        self._gap = int(T("space.1"))
        self._value = self._normalize(self._finite(value))
        self._display = float(self._value)
        self._hover = None
        self._anim = QVariantAnimation(self)
        self._anim.setDuration(DURATION["fast"])
        self._anim.setEasingCurve(EASING["standard"])
        self._anim.valueChanged.connect(self._on_anim)
        self.set_size(size)
        if not self._read_only:
            self.setMouseTracking(True)
            self.setCursor(Qt.PointingHandCursor)
        ThemeManager.instance().theme_changed.connect(self.update)
        # set_token 会话覆盖时重绘（QSS 不感知令牌覆盖，自绘需监听）
        TokenState.instance().token_changed.connect(self.update)

    # ------------------------------------------------------------------
    # 尺寸
    # ------------------------------------------------------------------

    def _star_for(self, size: str) -> int:
        """当前档位的星外接直径（自定义值优先，且不得越出档位高度）。

        上限为「档位高 − 上下各半档（2px）」，保证星形外接圆不贴边；
        缺省值取 ``_STAR_TOKEN``（16 / 20 / 24），与 22 / 28 / 34 刻度
        大致成 3 : 4 : 5 的比例。
        """
        limit = _INPUT_HEIGHTS[size] - 2 * int(T("space.05"))
        if self._star_request is not None:
            return max(int(T("space.2")), min(self._star_request, limit))
        return min(int(T(_STAR_TOKEN[size])), limit)

    def _apply_size(self, size: str) -> None:
        """SizeMixin 钩子：星径随档位缩放，控件高度对齐输入控件刻度。

        高度**固定**为 ``theme._INPUT_HEIGHTS``：声明的档位与实际渲染高度
        必须一致，否则同行排版会按错误的高度居中（契约 §1 / §8）。
        """
        self._star = self._star_for(size)
        self.setFixedHeight(_INPUT_HEIGHTS[size])
        self.updateGeometry()

    def set_star_size(self, star_size: int = None) -> None:
        """设置星外接直径；传 None 恢复按尺寸档取值。"""
        self._star_request = None if star_size is None else int(star_size)
        self._apply_size(self.size_name())

    def star_size(self) -> int:
        """当前星外接直径（px）。"""
        return self._star

    # ------------------------------------------------------------------
    # 属性
    # ------------------------------------------------------------------

    def value(self) -> float:
        """当前分值。"""
        return self._value

    def set_value(self, value: float, animate: bool = True) -> None:
        """设置分值（默认平滑过渡），发射 ``valueChanged``。

        分值必须为有限数值（NaN / ±inf 抛 ``ValueError``）。
        """
        value = self._normalize(self._finite(value))
        if value == self._value:
            return
        self._value = value
        if animate:
            self._anim.stop()
            self._anim.setStartValue(self._display)
            self._anim.setEndValue(float(value))
            self._anim.start()
        else:
            self._display = float(value)
            self.update()
        self.valueChanged.emit(self._value)

    def set_allow_half(self, on: bool) -> None:
        """设置是否允许半星。"""
        self._allow_half = bool(on)
        self.set_value(self._normalize(self._value))

    def set_read_only(self, on: bool) -> None:
        """设置只读模式。"""
        self._read_only = bool(on)
        self.setMouseTracking(not on)
        self.setCursor(Qt.PointingHandCursor if not on else Qt.ArrowCursor)

    @staticmethod
    def _finite(value) -> float:
        """把输入转换为 float 并校验为有限数值（NaN / inf 抛中文 ValueError）。"""
        value = float(value)
        if not math.isfinite(value):
            raise ValueError(f"非法分值: {value!r}，必须为有限数值")
        return value

    def _normalize(self, value: float) -> float:
        value = max(0.0, min(float(self._count), float(value)))
        if self._allow_half:
            value = round(value * 2) / 2.0
        else:
            value = float(round(value))
        return value

    def _on_anim(self, v) -> None:
        self._display = float(v)
        self.update()

    # ------------------------------------------------------------------
    # 交互
    # ------------------------------------------------------------------

    def _value_at(self, x: float) -> float:
        """把 x 坐标换算为分值。"""
        cell = self._star + self._gap
        idx = int(x // cell)
        frac = (x - idx * cell) / self._star
        frac = max(0.0, min(1.0, frac))
        if self._allow_half:
            frac = math.ceil(frac * 2) / 2.0
        else:
            frac = 1.0 if frac > 0 else 0.0
        return self._normalize(idx + frac)

    def mouseMoveEvent(self, event):
        if self._read_only:
            return
        self._hover = self._value_at(event.position().x())
        self.update()

    def leaveEvent(self, event):
        self._hover = None
        self.update()
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        if self._read_only:
            return
        if event.button() == Qt.LeftButton:
            self.set_value(self._value_at(event.position().x()))

    # ------------------------------------------------------------------
    # 绘制
    # ------------------------------------------------------------------

    def sizeHint(self) -> QSize:
        w = self._count * self._star + (self._count - 1) * self._gap
        return QSize(w, _INPUT_HEIGHTS[self.size_name()])

    def minimumSizeHint(self) -> QSize:
        return self.sizeHint()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        shown = self._hover if self._hover is not None else self._display
        filled = QColor(T("color.warning"))
        # 空星用 text.tertiary（对 bg.base 亮 3.41:1 / 暗 4.14:1，满足
        # 契约 §5 对装饰性元素的 3:1 下限）；text.disabled 仅用于禁用态
        empty = QColor(T("color.text.tertiary"))
        if not self.isEnabled():
            filled = QColor(T("color.text.disabled"))
            empty = QColor(T("color.text.disabled"))
        for i in range(self._count):
            cx = i * (self._star + self._gap) + self._star / 2.0
            cy = self.height() / 2.0
            star = _star_polygon(cx, cy, self._star / 2.0)
            frac = max(0.0, min(1.0, shown - i))
            # 先画空星
            p.setPen(Qt.NoPen)
            p.setBrush(empty)
            p.drawPolygon(star)
            # 再按比例裁剪画实星
            if frac > 0:
                p.save()
                path = QPainterPath()
                left = cx - self._star / 2.0
                path.addRect(left, 0, self._star * frac, self.height())
                p.setClipPath(path)
                p.setBrush(filled)
                p.drawPolygon(star)
                p.restore()
        p.end()
