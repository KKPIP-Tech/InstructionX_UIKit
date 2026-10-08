# -*- coding: utf-8 -*-
"""骨架屏 Skeleton（SPEC §5.3 skeleton.py）。

内容加载前的占位轮廓 + 微光扫过动画（QTimer 驱动自绘），颜色实时取自
主题令牌。

**与真实内容对齐**（本组件的重点）：占位块的圆角与高度必须等于它将要变成
的那个真实元素，否则数据到达的瞬间会出现「形状跳变」：

===================  ==================  ==================
占位块                真实元素              对齐依据
===================  ==================  ==================
头像                  Avatar（同尺寸圆形）  半径 = 边长 / 2
标题条                卡片标题（title.sm）  高度 = 标题行高
段落行                正文（md × 1.5 行高）  高度 = 正文行高
按钮                  Button（md 档）      高度 / 圆角 = 密度刻度
===================  ==================  ==================

微光节奏：帧节拍 25fps（微光是缓慢渐变扫过，不需要 60fps），一轮
``duration.slower × 3``；扫过的亮色在亮色主题取 ``bg.elevated``、暗色取
``border``——暗色下 ``bg.elevated`` 比底色 ``bg.muted`` **更暗**，直接用
会让微光变成一道脏渍。
"""

from PySide6.QtCore import QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPainterPath
from PySide6.QtWidgets import QWidget

from ..theme import T, ThemeManager
from .dialog import _connect_theme

__all__ = ["Skeleton"]

#: 头像占位边长（与 Avatar 的圆形档同尺寸）
_AVATAR = T("space.10")
#: 标题条高度（≈ font.title.sm 行高）
_TITLE_H = T("space.4") + T("space.05")
#: 段落行高（≈ font.md × font.line_height.body = 20px）
_ROW_H = T("space.5")
#: 段落行距（行与行之间留半档，行高 + 行距 = 24px 网格）
_ROW_PITCH = T("space.6")
#: 按钮占位：高度取 md 档密度刻度、圆角取 radius.md，与真实按钮一致
_BUTTON_H = T("space.6") + T("space.05") * 2     # 28 = md 控件高度
_BUTTON_W = T("space.16")      # ≈ 两字 md 按钮宽度
#: 段落行宽度比例（末行收短，模拟真实段落的换行节奏）
_ROW_FRACS = (1.0, 0.92, 0.78, 0.62)
#: 标题条宽度占文字列的比例
_TITLE_FRAC = 0.55
#: 占位块最小宽度（过窄时不再按比例缩，避免退化成一根竖线）
_MIN_BAR = T("space.10")
#: 控件最小宽度
_MIN_W = T("space.12") * 4
#: 微光刷新节拍（ms）：25fps，渐变扫过足够顺滑且省 CPU
_FRAME_MS = 40
#: 微光一轮时长（ms）：取令牌时长而非裸数字
_SWEEP_MS = T("duration.slower") * 3


class Skeleton(QWidget):
    """骨架屏：内容加载前的占位轮廓。

    参数:
        avatar: 是否显示头像圆形占位。
        title: 是否显示标题条占位。
        rows: 段落行数。
        button: 是否显示按钮占位。
        active: 是否启用微光扫过动画。
        parent: 父控件。

    示例::

        sk = Skeleton(avatar=True, rows=3, button=True)
        layout.addWidget(sk)
        sk.set_active(True)
    """

    def __init__(self, avatar: bool = False, title: bool = True,
                 rows: int = 3, button: bool = False, active: bool = True,
                 parent: QWidget = None):
        super().__init__(parent)
        self._avatar = bool(avatar)
        self._title = bool(title)
        self._rows = max(0, int(rows))
        self._button = bool(button)
        self._phase = 0.0
        self._active = True  # 期望动画状态（与可见性无关）
        self._timer = QTimer(self)
        self._timer.setInterval(_FRAME_MS)
        self._timer.timeout.connect(self._advance)
        _connect_theme(self, self.update)
        self._update_minimum()
        self.set_active(active)

    # -- 公开 API ---------------------------------------------------------
    def set_active(self, active: bool) -> None:
        """启用 / 停止微光动画。"""
        if active:
            self.start()
        else:
            self.stop()

    def is_active(self) -> bool:
        """是否启用微光动画（期望状态，与可见性无关）。"""
        return self._active

    def start(self) -> None:
        """启动微光动画（可见时定时器立即运行）。"""
        self._active = True
        if self.isVisible() and not self._timer.isActive():
            self._timer.start()

    def stop(self) -> None:
        """停止微光动画。"""
        self._active = False
        self._timer.stop()
        self.update()

    def showEvent(self, event) -> None:
        # 可见时按期望状态启停定时器，隐藏期间不空转
        super().showEvent(event)
        if self._active:
            self._timer.start()

    def hideEvent(self, event) -> None:
        self._timer.stop()
        super().hideEvent(event)

    # -- 内部 -------------------------------------------------------------
    def _update_minimum(self) -> None:
        """最小高度由版面函数本身推出（单一事实来源，不再另算一套）。"""
        _shapes, bottom = self._layout(float(_MIN_W))
        self.setMinimumHeight(bottom + T("space.05"))
        self.setMinimumWidth(_MIN_W)

    def _advance(self) -> None:
        self._phase += _FRAME_MS / float(_SWEEP_MS)
        if self._phase > 1.0:
            self._phase -= 1.0
        self.update()

    def _layout(self, width: float) -> tuple:
        """按真实内容块排布占位形状。

        返回 ``([(QRectF, radius), ...], 底部 y)``。有头像时，标题与段落
        都排在头像右侧的文字列里（此前段落从 x=0 起排，会从头像底下穿过去
        并与头像竖向重叠 4px）。
        """
        shapes = []
        x = 0.0
        if self._avatar:
            shapes.append((QRectF(x, 0, _AVATAR, _AVATAR), _AVATAR / 2.0))
            x = _AVATAR + T("space.3")
        column = max(0.0, width - x)
        y = 0.0
        if self._title:
            shapes.append((QRectF(x, y, max(_MIN_BAR, column * _TITLE_FRAC),
                                  _TITLE_H), float(T("radius.sm"))))
            y += _TITLE_H + T("space.3")
        for i in range(self._rows):
            frac = _ROW_FRACS[i] if i < len(_ROW_FRACS) else _ROW_FRACS[-1]
            shapes.append((QRectF(x, y, max(_MIN_BAR, column * frac), _ROW_H),
                           float(T("radius.sm"))))
            y += _ROW_PITCH
        if self._button:
            # 按钮与真实 md 按钮同高同圆角，避免数据到达时圆角 / 高度跳变
            shapes.append((QRectF(0, y, _BUTTON_W, _BUTTON_H),
                           float(T("radius.md"))))
            y += _BUTTON_H
        return shapes, y

    def _shapes(self) -> list:
        """兼容旧接口：返回当前宽度下的占位形状列表。"""
        return self._layout(float(self.width()))[0]

    def _shimmer_color(self) -> QColor:
        """微光亮色：亮色取 elevated（比底色亮），暗色取 border（比底色亮）。"""
        key = "color.border" if ThemeManager.instance().mode == "dark" \
            else "color.bg.elevated"
        color = QColor(T(key))
        color.setAlpha(170)
        return color

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        shapes = self._shapes()
        if not shapes:
            painter.end()
            return
        base = QColor(T("color.bg.muted"))
        union = QPainterPath()
        for rect, radius in shapes:
            painter.setBrush(base)
            painter.setPen(Qt.NoPen)
            painter.drawRoundedRect(rect, radius, radius)
            sub = QPainterPath()
            sub.addRoundedRect(rect.x(), rect.y(), rect.width(),
                               rect.height(), radius, radius)
            union = union.united(sub)
        if self._timer.isActive():
            # 微光扫过：裁剪到形状区域后绘制移动的浅色渐变带
            w = float(self.width())
            band = max(float(T("space.12")), w * 0.35)
            gx = -band + self._phase * (w + 2 * band)
            shimmer = self._shimmer_color()
            transparent = QColor(shimmer)
            transparent.setAlpha(0)
            grad = QLinearGradient(gx, 0, gx + band, 0)
            grad.setColorAt(0.0, transparent)
            grad.setColorAt(0.5, shimmer)
            grad.setColorAt(1.0, transparent)
            painter.setClipPath(union)
            painter.fillRect(self.rect(), grad)
        painter.end()
