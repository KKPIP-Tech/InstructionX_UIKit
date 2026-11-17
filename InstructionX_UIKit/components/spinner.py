# -*- coding: utf-8 -*-
"""加载指示器 Spinner（SPEC §5.3 spinner.py）。

自绘旋转弧（QTimer 驱动），支持 sm / md / lg 尺寸与提示文案，
颜色实时取自主题令牌。

密度刻度对齐（契约 §1）：``size`` 档位通过 ``uiksize`` 声明，因此控件
**总高**必须等于该档高度（sm 22 / md 28 / lg 34），否则消费者按档位排版
会错位。弧直径仍按档位取 16 / 24 / 32，垂直居中于档位盒内；带提示文案
时在档位盒下方追加一行文案（此时控件高于档位高度——它是「指示器 + 说明」
的整块，不再是单行控件）。

轨道色取 ``bg.muted``（与 ProgressBar 同一套），只把前景弧留给状态色：
进度类控件用同一枚轨道色，整套组件看起来才是一个系统。
"""

from PySide6.QtCore import QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QFontMetrics, QPainter, QPen
from PySide6.QtWidgets import QWidget

from .._draw import draw_arc
from ..theme import T, set_property
from ..tokens import TokenState
from .dialog import _connect_theme

__all__ = ["Spinner"]

#: 尺寸档 -> 弧直径（px）
_ARC = {"sm": 16, "md": 24, "lg": 32}
#: 尺寸档 -> 控件总高（px），与 theme._INPUT_HEIGHTS 的密度刻度一致
_HEIGHT = {"sm": 22, "md": 28, "lg": 34}
#: 尺寸档 -> 弧线宽（px）
_STROKE = {"sm": 2.0, "md": 2.0, "lg": 3.0}
#: 旋转弧覆盖角度（度）：留一段缺口，旋转才可读
_SWEEP = 270
#: 刷新节拍（ms）与步进角（度）：16ms × 8° = 800ms 一圈，慢而稳
_FRAME_MS = 16
_STEP = 8
#: 弧与提示文案之间的间距
_TIP_GAP = T("layout.inset.pad_y")
#: 提示文案字阶
_TIP_SCALE = "sm"


class Spinner(QWidget):
    """加载指示器：旋转弧 + 可选提示文案。

    参数:
        size: 弧直径档位 ``"sm"``(16) / ``"md"``(24) / ``"lg"``(32)，
            控件总高对应 22 / 28 / 34。
        tip: 提示文案（显示在弧下方，为空则不显示）。
        parent: 父控件。

    示例::

        sp = Spinner(size="md", tip="加载中…")
        layout.addWidget(sp)
        sp.start()
    """

    #: 尺寸档位（弧直径 px）
    SIZES = dict(_ARC)

    def __init__(self, size: str = "md", tip: str = "",
                 parent: QWidget = None):
        super().__init__(parent)
        self._size = "md"
        self._tip = tip
        self._angle = 0
        self._spinning = True  # 期望旋转状态（与可见性无关）
        self._timer = QTimer(self)
        self._timer.setInterval(_FRAME_MS)
        self._timer.timeout.connect(self._advance)
        _connect_theme(self, self.update)
        self.set_size(size)
        self._apply_tip()
        # 定时器仅在可见时运行：隐藏期间不空转（showEvent 启动）
        if self.isVisible():
            self._timer.start()

    # -- 公开 API ---------------------------------------------------------
    def set_size(self, size: str) -> None:
        """设置尺寸档位（同步更新声明属性与控件总高）。"""
        if size not in _ARC:
            raise ValueError(
                f"未知 Spinner 尺寸: {size!r}，应为 {tuple(_ARC)} 之一")
        self._size = size
        set_property(self, "size", size)
        self._apply_tip()
        self.updateGeometry()
        self.update()

    def size(self) -> str:  # noqa: A003 - 与令牌档位语义一致
        return self._size

    def set_tip(self, text: str) -> None:
        """设置提示文案。"""
        self._tip = text
        self._apply_tip()
        self.updateGeometry()
        self.update()

    def tip(self) -> str:
        return self._tip

    def set_spinning(self, spinning: bool) -> None:
        """启动 / 停止旋转。"""
        if spinning:
            self.start()
        else:
            self.stop()

    def is_spinning(self) -> bool:
        """是否处于旋转状态（期望状态，与可见性无关）。"""
        return self._spinning

    def start(self) -> None:
        """启动旋转动画（可见时定时器立即运行）。"""
        self._spinning = True
        if self.isVisible() and not self._timer.isActive():
            self._timer.start()

    def stop(self) -> None:
        """停止旋转动画。"""
        self._spinning = False
        self._timer.stop()
        self.update()

    def showEvent(self, event) -> None:
        # 可见时按期望状态启停定时器，隐藏期间不空转
        super().showEvent(event)
        if self._spinning:
            self._timer.start()

    def hideEvent(self, event) -> None:
        self._timer.stop()
        super().hideEvent(event)

    def sizeHint(self):
        d = _ARC[self._size]
        w, h = d, _HEIGHT[self._size]
        if self._tip:
            fm = QFontMetrics(self._tip_font())
            w = max(w, fm.horizontalAdvance(self._tip))
            h = _HEIGHT[self._size] + _TIP_GAP + fm.height()
        hint = super().sizeHint()
        hint.setWidth(w)
        hint.setHeight(h)
        return hint

    def minimumSizeHint(self):
        return self.sizeHint()

    # -- 内部 -------------------------------------------------------------
    def _tip_font(self):
        """提示文案字体（令牌字阶，与自绘绘制同源）。"""
        return TokenState.instance().font(_TIP_SCALE, "regular")

    def _apply_tip(self) -> None:
        """按当前档位与文案锁定几何：有文案则高度 = 档位高 + 间距 + 行高。"""
        h = _HEIGHT[self._size]
        if self._tip:
            h += _TIP_GAP + QFontMetrics(self._tip_font()).height()
        self.setFixedHeight(h)
        if self._tip:
            self.setMinimumWidth(
                QFontMetrics(self._tip_font()).horizontalAdvance(self._tip))
        else:
            self.setMinimumWidth(0)

    def _advance(self) -> None:
        self._angle = (self._angle + _STEP) % 360
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        d = float(_ARC[self._size])
        pen_w = _STROKE[self._size]
        x = (self.width() - d) / 2.0
        rect = QRectF(x + pen_w / 2, pen_w / 2, d - pen_w, d - pen_w)
        # 轨道（与 ProgressBar 同一枚底色）
        track = QColor(T("color.bg.muted"))
        pen = QPen(track)
        pen.setWidthF(pen_w)
        pen.setCapStyle(Qt.RoundCap)
        painter.setPen(pen)
        draw_arc(painter, rect, 0.0, 360.0)
        # 旋转弧
        pen = QPen(QColor(T("color.primary")))
        pen.setWidthF(pen_w)
        pen.setCapStyle(Qt.RoundCap)
        painter.setPen(pen)
        draw_arc(painter, rect, -self._angle, float(_SWEEP))
        # 提示文案
        if self._tip:
            font = self._tip_font()
            painter.setFont(font)
            painter.setPen(QColor(T("color.text.secondary")))
            tip_h = QFontMetrics(font).height()
            tip_rect = QRectF(0, _HEIGHT[self._size] + _TIP_GAP,
                              self.width(), tip_h)
            painter.drawText(tip_rect, Qt.AlignHCenter | Qt.AlignVCenter,
                             self._tip)
        painter.end()
