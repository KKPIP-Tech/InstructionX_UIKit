# -*- coding: utf-8 -*-
"""自绘 / 定时器类动画预设（SPEC §7.2，anim-B 代理）。

本模块包含 24 个基于 ``QTimer`` / ``QVariantAnimation`` + ``paintEvent``
自绘的动画控件，全部主题感知：

- 绘制时在 ``paintEvent`` 中实时调用 ``InstructionX_UIKit.theme.T()`` 取色；
- 构造时连接 ``ThemeManager.instance().theme_changed`` 到 ``self.update()``；
- 默认时长 / 缓动取自 ``tokens.DURATION`` / ``tokens.EASING``；
- 所有动画均由定时器或 QVariantAnimation 驱动，不阻塞事件循环；
- 伪 3D（CardTilt / CubeRotator / FlipCard / CoverFlow）通过
  ``QTransform`` 的透视系数（m13/m23）近似，无需 OpenGL。

类清单（对照 SPEC §7.2）：
    SpinnerArc, LikeBurstButton, MagneticButton, CheckDraw, BouncingDots,
    SkeletonShimmer, Shimmer, ProgressStriped, ParallaxArea, ScrollReveal,
    HorizontalScrollStrip, StickyHeader, ScrollProgressBar, ScrollStoryArea,
    MarqueeLabel, FluidBackground, TypewriterLabel, TextDecodeLabel,
    NumberRollLabel, LetterStaggerLabel, CardTilt, CubeRotator, FlipCard,
    CoverFlow
"""

import math
import random

from PySide6.QtCore import (
    QAbstractAnimation,
    QEasingCurve,
    QElapsedTimer,
    QEvent,
    QPoint,
    QPointF,
    QRect,
    QRectF,
    QSize,
    Qt,
    QTimer,
    QVariantAnimation,
    Signal,
)
from PySide6.QtGui import (
    QColor,
    QFont,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QRadialGradient,
    QTransform,
)
from PySide6.QtWidgets import (
    QAbstractButton,
    QFrame,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ..theme import T, ThemeManager
from ..tokens import DURATION, EASING
from .property import _SnapshotOverlay, _grab_pixmap

__all__ = [
    "SpinnerArc",
    "LikeBurstButton",
    "MagneticButton",
    "CheckDraw",
    "BouncingDots",
    "SkeletonShimmer",
    "Shimmer",
    "ProgressStriped",
    "ParallaxArea",
    "ScrollReveal",
    "HorizontalScrollStrip",
    "StickyHeader",
    "ScrollProgressBar",
    "ScrollStoryArea",
    "MarqueeLabel",
    "FluidBackground",
    "TypewriterLabel",
    "TextDecodeLabel",
    "NumberRollLabel",
    "LetterStaggerLabel",
    "CardTilt",
    "CubeRotator",
    "FlipCard",
    "CoverFlow",
]

# ---------------------------------------------------------------------------
# 内部工具
# ---------------------------------------------------------------------------


def _theme_refresh(widget) -> None:
    """主题切换时触发重绘（SPEC §3 自绘组件约定）。

    直接连接 ``widget.update`` 绑定方法：连接以 widget 为接收方上下文，
    控件销毁时 Qt 自动断开——旧实现连 lambda（无接收方），ThemeManager
    单例的信号槽列表会永久持有已销毁控件的包装对象，每次主题切换对
    全部死对象空转（调用 update() 抛 RuntimeError 被守卫吞掉）。绑定
    方法自动断连后无需守卫，属 Qt 层机制保证。
    """
    ThemeManager.instance().theme_changed.connect(widget.update)


def _parse_color(text: str) -> QColor:
    """解析 ``#hex`` 与 ``rgba(r,g,b,a)`` / ``rgb(r,g,b)`` 字符串。"""
    text = text.strip()
    if text.startswith("#"):
        return QColor(text)
    if text.startswith("rgb"):
        body = text[text.index("(") + 1: text.rindex(")")]
        parts = [p.strip() for p in body.split(",")]
        r, g, b = (int(float(parts[i])) for i in range(3))
        a = 255
        if len(parts) > 3:
            av = float(parts[3])
            a = int(av * 255) if av <= 1.0 else int(av)
        return QColor(r, g, b, a)
    return QColor(text)


def _qcolor(key_or_color) -> QColor:
    """令牌键（如 ``"primary"``）或颜色字符串转 ``QColor``。"""
    if isinstance(key_or_color, QColor):
        return QColor(key_or_color)
    text = str(key_or_color)
    if text.startswith("#") or text.startswith("rgb"):
        return _parse_color(text)
    return _parse_color(str(T(f"color.{text}")))


def _with_alpha(color: QColor, alpha: int) -> QColor:
    c = QColor(color)
    c.setAlpha(max(0, min(255, int(alpha))))
    return c


def _mix(c1: QColor, c2: QColor, t: float) -> QColor:
    """两色线性插值（t=0 取 c1，t=1 取 c2）。"""
    t = max(0.0, min(1.0, float(t)))
    return QColor(
        int(c1.red() + (c2.red() - c1.red()) * t),
        int(c1.green() + (c2.green() - c1.green()) * t),
        int(c1.blue() + (c2.blue() - c1.blue()) * t),
        int(c1.alpha() + (c2.alpha() - c1.alpha()) * t),
    )


def _is_dark() -> bool:
    return ThemeManager.instance().mode == "dark"


def _drop_anim(owner, anim) -> None:
    anims = getattr(owner, "_uik_anims", None)
    if anims is not None and anim in anims:
        anims.remove(anim)


def _run_anim(owner, duration, easing, on_value, on_finish=None):
    """创建并启动一个 0.0→1.0 的 QVariantAnimation，返回句柄。

    动画挂在 ``owner`` 下并保存引用，结束后自动释放，便于中途 ``stop()``。
    """
    anim = QVariantAnimation(owner)
    anim.setStartValue(0.0)
    anim.setEndValue(1.0)
    anim.setDuration(max(1, int(duration)))
    if isinstance(easing, QEasingCurve.Type):
        anim.setEasingCurve(QEasingCurve(easing))
    elif isinstance(easing, QEasingCurve):
        anim.setEasingCurve(easing)
    anim.valueChanged.connect(lambda v: on_value(float(v)))
    if on_finish is not None:
        anim.finished.connect(on_finish)
    anim.finished.connect(lambda: _drop_anim(owner, anim))
    # 手动 stop() 不发射 finished：捕获 Stopped 状态同步清理句柄，
    # 否则反复 start/stop 时 _uik_anims 死句柄无限累积（_drop_anim 幂等）
    anim.stateChanged.connect(
        lambda new, _old, a=anim, o=owner: _drop_anim(o, a)
        if new == QAbstractAnimation.Stopped else None)
    anims = getattr(owner, "_uik_anims", None)
    if anims is None:
        anims = []
        owner._uik_anims = anims
    anims.append(anim)
    anim.start()
    return anim


class _Ticker:
    """定频心跳定时器：回调 ``callback(elapsed_ms, dt_ms)``。

    ``dt`` 用 ``QElapsedTimer`` 实测：系统繁忙时 QTimer 触发延迟，
    以名义 interval 累加会造成周期动画相位漂移；实测 dt 保证
    ``elapsed`` 始终等于真实流逝时间。
    """

    def __init__(self, owner, callback, interval=16):
        self._timer = QTimer(owner)
        self._timer.setInterval(max(5, int(interval)))
        self._elapsed = 0
        self._callback = callback
        self._stopwatch = QElapsedTimer()
        self._stopwatch.start()
        self._timer.timeout.connect(self._on_tick)

    def _on_tick(self):
        dt = self._stopwatch.restart()
        self._elapsed += dt
        self._callback(self._elapsed, dt)

    def start(self):
        self._timer.start()

    def stop(self):
        self._timer.stop()

    def isActive(self) -> bool:
        return self._timer.isActive()

    def reset(self):
        self._elapsed = 0
        self._stopwatch.restart()

    @property
    def elapsed(self) -> int:
        return self._elapsed


class _HiddenPauseMixin:
    """自绘动画控件混入：隐藏时暂停动画源、重新显示时恢复（§7.2 约定）。

    隐藏控件定时器空转不仅耗电，TypewriterLabel 等回调还会继续推进
    状态。约定动画源成员名：``_ticker``（_Ticker）/ ``_timer``（QTimer）
    / ``_auto``（QTimer 自动轮播）/ ``_anim``（QVariantAnimation）。
    hideEvent 记录并暂停在跑的源；showEvent 调用 ``_resume_anim()``
    恢复（默认重调 ``start()``，子类按需覆写，如无 start() 的类）。
    """

    def _anim_sources(self):
        """生成 (名称, 在跑的动画源) 对。"""
        for name in ("_ticker", "_timer", "_auto"):
            src = getattr(self, name, None)
            if src is not None and src.isActive():
                yield name, src
        anim = getattr(self, "_anim", None)
        if anim is not None and anim.state() == QAbstractAnimation.Running:
            yield "_anim", anim

    def _anim_active(self) -> bool:
        return any(True for _ in self._anim_sources())

    def _pause_anim(self) -> None:
        for _name, src in self._anim_sources():
            src.stop()

    def _resume_anim(self) -> None:
        start = getattr(self, "start", None)
        if callable(start):
            start()

    def hideEvent(self, event):
        self._uik_was_animating = self._anim_active()
        if self._uik_was_animating:
            self._pause_anim()
        super().hideEvent(event)

    def showEvent(self, event):
        super().showEvent(event)
        if getattr(self, "_uik_was_animating", False):
            self._uik_was_animating = False
            self._resume_anim()


def _snapshot_ratio(widget) -> float:
    """快照超采样倍率：取 ``max(devicePixelRatioF, 3.0)``。

    伪 3D 变换（CardTilt / CubeRotator / FlipCard）会对快照位图做透视
    缩放插值，1x 快照在旋转角度下文字明显发虚；按不低于 3x 采样并
    ``setDevicePixelRatio`` 后，绘制时自动缩回逻辑尺寸，任意角度下
    文字边缘都保持锐利。
    """
    try:
        dpr = float(widget.devicePixelRatioF())
    except Exception:  # pragma: no cover - 极端平台兜底
        dpr = 1.0
    return max(3.0, dpr)


def _grab_widget(widget, ratio=None) -> QPixmap:
    """按 ``ratio`` 超采样抓取控件快照（隐藏控件亦可），返回已设 DPR 的位图。"""
    ratio = float(ratio) if ratio else _snapshot_ratio(widget)
    size = widget.size()
    w = max(2, int(math.ceil(size.width() * ratio)))
    h = max(2, int(math.ceil(size.height() * ratio)))
    pm = QPixmap(w, h)
    pm.setDevicePixelRatio(ratio)
    pm.fill(Qt.transparent)
    widget.render(pm)
    return pm


def _rot_y(deg: float, persp: float) -> QTransform:
    """绕竖直轴（Y）旋转的伪透视变换：W = 1 + x*sin/d。"""
    rad = math.radians(deg)
    c, s = math.cos(rad), math.sin(rad)
    d = max(1.0, float(persp))
    return QTransform(c, 0.0, s / d, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0)


def _rot_x(deg: float, persp: float) -> QTransform:
    """绕水平轴（X）旋转的伪透视变换：W = 1 + y*sin/d。"""
    rad = math.radians(deg)
    c, s = math.cos(rad), math.sin(rad)
    d = max(1.0, float(persp))
    return QTransform(1.0, 0.0, 0.0, 0.0, c, s / d, 0.0, 0.0, 1.0)


def _tilt_transform(cx: float, cy: float, rx: float, ry: float,
                    persp: float) -> QTransform:
    """绕 ``(cx, cy)`` 的伪透视倾斜矩阵（先 X 轴倾转、再 Y 轴倾转）。

    注意：``QTransform.translate`` 与 ``operator*`` 的复合顺序反直觉，
    直接 ``translate(c) -> t * rot -> translate(-c)`` 会让两个平移相互
    抵消，实际绕左上角旋转、把内容甩出控件 rect 造成裁剪。这里按数学
    约定做 3x3 齐次矩阵相乘 ``M = T(c) · RotY · RotX · T(-c)``，
    保证严格绕中心变换。
    """
    d = max(1.0, float(persp))
    c1, s1 = math.cos(math.radians(rx)), math.sin(math.radians(rx))
    c2, s2 = math.cos(math.radians(ry)), math.sin(math.radians(ry))
    t_pos = ((1.0, 0.0, cx), (0.0, 1.0, cy), (0.0, 0.0, 1.0))
    t_neg = ((1.0, 0.0, -cx), (0.0, 1.0, -cy), (0.0, 0.0, 1.0))
    rot_y = ((c2, 0.0, 0.0), (0.0, 1.0, 0.0), (s2 / d, 0.0, 1.0))
    rot_x = ((1.0, 0.0, 0.0), (0.0, c1, 0.0), (0.0, s1 / d, 1.0))

    def mul(a, b):
        return tuple(
            tuple(sum(a[i][k] * b[k][j] for k in range(3)) for j in range(3))
            for i in range(3))

    m = mul(t_pos, mul(rot_y, mul(rot_x, t_neg)))
    return QTransform(m[0][0], m[1][0], m[2][0],
                      m[0][1], m[1][1], m[2][1],
                      m[0][2], m[1][2], m[2][2])


def _face_pixmap(size: QSize, title: str, subtitle: str = "",
                 ratio: float = 1.0) -> QPixmap:
    """绘制默认卡片面（圆角面板 + 标题 + 副标题），供 3D 类控件复用。

    ``ratio`` 为超采样倍率（>=1）：位图按 ``size * ratio`` 分配并
    ``setDevicePixelRatio(ratio)``，透视变换绘制时文字边缘保持锐利。
    """
    ratio = max(1.0, float(ratio))
    w = max(2, int(size.width()))
    h = max(2, int(size.height()))
    pm = QPixmap(int(math.ceil(w * ratio)), int(math.ceil(h * ratio)))
    pm.setDevicePixelRatio(ratio)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    rect = QRectF(0.5, 0.5, w - 1.0, h - 1.0)
    p.setPen(QPen(_qcolor("primary"), 1.6))
    p.setBrush(_qcolor("primary.subtle"))
    radius = float(T("radius.lg"))
    p.drawRoundedRect(rect, radius, radius)
    p.setPen(_qcolor("text.primary"))
    font = QFont(p.font())
    font.setPixelSize(int(T("font.title.md")))
    font.setWeight(QFont.DemiBold)
    p.setFont(font)
    title_rect = QRectF(rect.x(), rect.y(), rect.width(),
                        rect.height() * (0.62 if subtitle else 1.0))
    p.drawText(title_rect, Qt.AlignCenter, title)
    if subtitle:
        font.setPixelSize(int(T("font.sm")))
        font.setWeight(QFont.Normal)
        p.setFont(font)
        p.setPen(_qcolor("text.secondary"))
        sub_rect = QRectF(rect.x(), rect.y() + rect.height() * 0.5,
                          rect.width(), rect.height() * 0.42)
        p.drawText(sub_rect, Qt.AlignHCenter | Qt.AlignTop, subtitle)
    p.end()
    return pm


def _cached_face_snapshot(holder, widget, text, subtitle, idx=0) -> QPixmap:
    """按 (序号, 尺寸, 内容控件, 文本, 主题模式) 缓存伪 3D 组件的内容快照。

    paintEvent 每帧对内容 ``render()`` 不低于 3x 超采样位图代价高
    （大控件时 CPU / 内存峰值明显）；缓存后仅在尺寸变化（resizeEvent
    清缓存）或内容变更（setContent / setFrontWidget 等清缓存）时重抓。
    键含主题模式：主题切换自动换键重新抓取（内容控件为隐藏状态，
    必须经 render() 才能按新令牌重绘）。会话级 ``set_token`` 覆盖不
    换模式，缓存不感知（覆盖键仅作用于绘制时取色，属可接受边角）。
    """
    key = (idx, holder.width(), holder.height(), widget, text,
           ThemeManager.instance().mode)
    pm = holder._snap_cache.get(key)
    if pm is None:
        if widget is not None:
            pm = _grab_widget(widget)
        if pm is None or pm.isNull():
            pm = _face_pixmap(holder.size(), text, subtitle,
                              ratio=_snapshot_ratio(holder))
        holder._snap_cache[key] = pm
    return pm


# ---------------------------------------------------------------------------
# 1. SpinnerArc —— 旋转圈
# ---------------------------------------------------------------------------


class SpinnerArc(_HiddenPauseMixin, QWidget):
    """旋转圈加载指示器（QTimer 驱动圆弧旋转）。

    用途：等待 / 加载场景的轻量指示器，颜色跟随 ``color.primary``。
    主要参数：
        size: 直径（px），默认 32；
        line_width: 弧线线宽，默认 ``size // 8``（至少 2）；
        speed: 每帧步进角度（度），默认 10；interval: 帧间隔（ms），默认 16。
    示例::

        sp = SpinnerArc(size=28)
        sp.start()      # 启动旋转（构造后默认已启动）
        sp.stop()       # 停止旋转
    """

    def __init__(self, size=32, line_width=None, speed=10.0, interval=16, parent=None):
        super().__init__(parent)
        self._size = int(size)
        self._lw = int(line_width) if line_width else max(2, self._size // 8)
        self._speed = float(speed)
        self._angle = 0.0
        self.setFixedSize(self._size, self._size)
        self._ticker = _Ticker(self, self._advance, interval)
        _theme_refresh(self)
        self.start()

    def start(self):
        """启动旋转。"""
        self._ticker.start()

    def stop(self):
        """停止旋转。"""
        self._ticker.stop()

    def isRunning(self) -> bool:
        return self._ticker.isActive()

    def _advance(self, _elapsed, _dt):
        self._angle = (self._angle + self._speed) % 360.0
        self.update()

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        m = self._lw / 2.0 + 1.0
        rect = QRectF(m, m, self.width() - 2 * m, self.height() - 2 * m)
        pen = QPen(_qcolor("border"))
        pen.setWidthF(float(self._lw))
        pen.setCapStyle(Qt.RoundCap)
        p.setPen(pen)
        p.drawArc(rect, 0, 360 * 16)
        pen.setColor(_qcolor("primary"))
        p.setPen(pen)
        p.drawArc(rect, int(-self._angle * 16), 110 * 16)
        p.end()


# ---------------------------------------------------------------------------
# 2. BouncingDots —— 跳动的点
# ---------------------------------------------------------------------------


class BouncingDots(_HiddenPauseMixin, QWidget):
    """跳动的点：若干圆点依次上下弹跳（输入中 / 加载中暗示）。

    用途：聊天「正在输入」、局部加载等场景。
    主要参数：
        count: 圆点数量，默认 3；diameter: 直径（px），默认 8；
        amplitude: 弹跳高度（px），默认 6；period: 单点弹跳周期（ms），默认 600。
    示例::

        dots = BouncingDots(count=3, diameter=8)
        dots.start()
        dots.stop()
    """

    def __init__(self, count=3, diameter=8, amplitude=6, period=600,
                 interval=16, parent=None):
        super().__init__(parent)
        self._count = max(1, int(count))
        self._d = int(diameter)
        self._amp = float(amplitude)
        self._period = max(120, int(period))
        spacing = self._d + 2
        self.setFixedSize(self._count * self._d + (self._count - 1) * spacing,
                          self._d + int(self._amp) + 2)
        self._spacing = spacing
        self._ticker = _Ticker(self, lambda _e, _d2: self.update(), interval)
        _theme_refresh(self)
        self.start()

    def start(self):
        """启动跳动。"""
        self._ticker.start()

    def stop(self):
        """停止跳动。"""
        self._ticker.stop()

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        base = _qcolor("primary")
        for i in range(self._count):
            # phase 经取模恒在 [0, 1)，无需 phase < 1.0 分支
            phase = ((self._ticker.elapsed / self._period) - i * 0.16) % 1.0
            lift = math.sin(math.pi * phase)
            y = self._amp * (1.0 - lift) + 1.0
            c = _with_alpha(base, int(140 + 115 * lift))
            p.setBrush(c)
            x = i * (self._d + self._spacing)
            p.drawEllipse(QRectF(x, y, self._d, self._d))
        p.end()


# ---------------------------------------------------------------------------
# 3. CheckDraw —— 对勾描绘
# ---------------------------------------------------------------------------


class CheckDraw(_HiddenPauseMixin, QWidget):
    """对勾描绘动画：圆环渐现 + 对勾逐笔描出。

    用途：提交成功、任务完成等正向即时反馈。
    主要参数：
        size: 直径（px），默认 28；
        duration: 全程时长（ms），默认 ``DURATION["slow"]``；
        缓动固定取 ``EASING["emphasis"]``。
    示例::

        ck = CheckDraw(size=48)
        ck.start()      # 播放描绘动画
        ck.reset()      # 清零，回到未描绘状态
    """

    def __init__(self, size=28, duration=None, parent=None):
        super().__init__(parent)
        self._size = int(size)
        self._duration = int(duration if duration else DURATION["slow"])
        self._progress = 0.0
        self._anim = None
        self.setFixedSize(self._size, self._size)
        _theme_refresh(self)

    def start(self):
        """从头播放描绘动画，返回动画句柄。"""
        if self._anim is not None:
            self._anim.stop()
        self._anim = _run_anim(self, self._duration, EASING["emphasis"],
                               self._set_progress)
        return self._anim

    def reset(self):
        """清零进度（不播放动画）。"""
        if self._anim is not None:
            self._anim.stop()
            self._anim = None
        self._progress = 0.0
        self.update()

    def setProgress(self, value: float):
        """直接设置进度 0~1（供外部时间线驱动）。"""
        self._set_progress(value)

    def progress(self) -> float:
        return self._progress

    def _set_progress(self, v: float):
        self._progress = max(0.0, min(1.0, float(v)))
        self.update()

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        lw = max(2.0, self._size / 12.0)
        m = lw / 2.0 + 1.0
        rect = QRectF(m, m, w - 2 * m, h - 2 * m)

        circle_phase = min(1.0, self._progress / 0.55)
        check_phase = max(0.0, min(1.0, (self._progress - 0.45) / 0.55))

        # 底环
        pen = QPen(_qcolor("border.strong"))
        pen.setWidthF(lw)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        p.drawEllipse(rect)

        if circle_phase > 0.0:
            # 填充圆（随圆环进度淡入）
            fill = _with_alpha(_qcolor("primary"), int(255 * circle_phase))
            p.setPen(Qt.NoPen)
            p.setBrush(fill)
            inner = rect.adjusted(lw * 0.8, lw * 0.8, -lw * 0.8, -lw * 0.8)
            p.drawEllipse(inner)
            # 圆环描边进度（从顶部顺时针）
            pen = QPen(_qcolor("primary"))
            pen.setWidthF(lw)
            pen.setCapStyle(Qt.RoundCap)
            p.setPen(pen)
            p.setBrush(Qt.NoBrush)
            p.drawArc(rect, 90 * 16, int(-360 * 16 * circle_phase))

        if check_phase > 0.0:
            # 对勾两点折线：p1 -> p2 -> p3（相对坐标）
            p1 = QPointF(w * 0.28, h * 0.54)
            p2 = QPointF(w * 0.45, h * 0.70)
            p3 = QPointF(w * 0.74, h * 0.34)
            l1 = math.hypot(p2.x() - p1.x(), p2.y() - p1.y())
            l2 = math.hypot(p3.x() - p2.x(), p3.y() - p2.y())
            total = l1 + l2
            head = total * check_phase
            pts = [p1]
            if head <= l1:
                t = head / l1 if l1 else 1.0
                pts.append(QPointF(p1.x() + (p2.x() - p1.x()) * t,
                                   p1.y() + (p2.y() - p1.y()) * t))
            else:
                pts.append(p2)
                t = (head - l1) / l2 if l2 else 1.0
                pts.append(QPointF(p2.x() + (p3.x() - p2.x()) * t,
                                   p2.y() + (p3.y() - p2.y()) * t))
            pen = QPen(_qcolor("on.primary"))
            pen.setWidthF(lw)
            pen.setCapStyle(Qt.RoundCap)
            pen.setJoinStyle(Qt.RoundJoin)
            p.setPen(pen)
            p.drawPolyline(pts)
        p.end()


# ---------------------------------------------------------------------------
# 4. LikeBurstButton —— 点赞爆裂按钮
# ---------------------------------------------------------------------------


class LikeBurstButton(_HiddenPauseMixin, QAbstractButton):
    """点赞爆裂按钮：点击心形放大回弹，并迸出 8~12 个粒子扩散淡出。

    用途：点赞 / 收藏等情绪化交互。可勾选（checkable），勾选态为已点赞。
    主要参数：
        size: 按钮边长（px），默认 44；
        particle_count: 粒子数（自动夹在 8~12），默认 10。
    信号：``likedChanged(bool)``。
    示例::

        btn = LikeBurstButton()
        btn.likedChanged.connect(lambda on: print("已点赞" if on else "取消"))
        btn.click()       # 触发爆裂动画
    """

    likedChanged = Signal(bool)

    _PALETTE = ("danger", "warning", "primary", "success")

    def __init__(self, size=44, particle_count=10, parent=None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self._size = int(size)
        self._count = max(8, min(12, int(particle_count)))
        self._heart_scale = 1.0
        self._particles = []
        self._scale_anim = None
        self.setFixedSize(self._size, self._size)
        self._ticker = _Ticker(self, self._tick, 16)
        self.toggled.connect(self._on_toggled)
        _theme_refresh(self)

    def _on_toggled(self, checked: bool):
        self.likedChanged.emit(checked)
        if checked:
            self._play_scale(0.55, 1.0, DURATION["slow"], EASING["spring"])
            self._spawn()
        else:
            self._play_scale(0.8, 1.0, DURATION["fast"], EASING["standard"])

    def _play_scale(self, a, b, duration, easing):
        if self._scale_anim is not None:
            self._scale_anim.stop()
        self._scale_anim = _run_anim(
            self, duration, easing,
            lambda v: setattr(self, "_heart_scale", a + (b - a) * v),
            on_finish=self._on_scale_done)
        self._ticker.start()

    def _on_scale_done(self):
        """缩放动画结束复位句柄：停机判定依赖其 None，不复位则 ticker
        60fps 空转至控件销毁。"""
        self._scale_anim = None
        self._ticker.start()  # 唤醒 ticker 走一次停机判定

    def _resume_anim(self):
        # 无公共 start()：恢复时重启动 ticker（_tick 空闲判定会自动停机）
        self._ticker.start()

    def _spawn(self):
        now = self._ticker.elapsed
        for i in range(self._count):
            angle = (2.0 * math.pi * i / self._count) + random.uniform(-0.28, 0.28)
            self._particles.append({
                "angle": angle,
                "speed": self._size * random.uniform(0.55, 1.05),
                "size": random.uniform(2.2, 4.6),
                "color": random.choice(self._PALETTE),
                "born": now,
                "life": random.uniform(420.0, 680.0),
            })

    def _tick(self, elapsed, _dt):
        alive = [pt for pt in self._particles if elapsed - pt["born"] < pt["life"]]
        self._particles = alive
        if not alive and self._scale_anim is None:
            self._ticker.stop()
        self.update()

    @staticmethod
    def _heart_path(cx, cy, s):
        path = QPainterPath(QPointF(cx, cy + 0.36 * s))
        path.cubicTo(QPointF(cx - 1.05 * s, cy - 0.28 * s),
                     QPointF(cx - 0.52 * s, cy - 0.98 * s),
                     QPointF(cx, cy - 0.46 * s))
        path.cubicTo(QPointF(cx + 0.52 * s, cy - 0.98 * s),
                     QPointF(cx + 1.05 * s, cy - 0.28 * s),
                     QPointF(cx, cy + 0.36 * s))
        path.closeSubpath()
        return path

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        cx, cy = w / 2.0, h / 2.0

        if self.underMouse():
            p.setPen(Qt.NoPen)
            p.setBrush(_qcolor("bg.muted"))
            p.drawEllipse(QRectF(1, 1, w - 2, h - 2))

        # 粒子（心形下层）
        now = self._ticker.elapsed
        p.setPen(Qt.NoPen)
        for pt in self._particles:
            t = (now - pt["born"]) / pt["life"]
            if t < 0.0 or t >= 1.0:
                continue
            ease = 1.0 - (1.0 - t) ** 3
            r = pt["speed"] * ease
            x = cx + math.cos(pt["angle"]) * r
            y = cy + math.sin(pt["angle"]) * r
            alpha = int(230 * (1.0 - t))
            p.setBrush(_with_alpha(_qcolor(pt["color"]), alpha))
            d = pt["size"] * (1.0 - 0.4 * t)
            p.drawEllipse(QPointF(x, y), d, d)

        # 心形
        s = self._size * 0.30 * self._heart_scale
        path = self._heart_path(cx, cy, s)
        if self.isChecked():
            p.setPen(Qt.NoPen)
            p.setBrush(_qcolor("danger"))
        else:
            pen = QPen(_qcolor("text.tertiary"))
            pen.setWidthF(2.0)
            p.setPen(pen)
            p.setBrush(Qt.NoBrush)
        p.drawPath(path)
        p.end()


# ---------------------------------------------------------------------------
# 5. MagneticButton —— 磁吸按钮
# ---------------------------------------------------------------------------


class MagneticButton(_HiddenPauseMixin, QAbstractButton):
    """磁吸按钮：鼠标靠近时按钮向光标方向位移（上限约 8px），离开弹回。

    用途：重点操作的趣味强调。位移通过自绘偏移实现，不影响布局。
    主要参数：
        text: 按钮文案；max_offset: 最大位移（px），默认 8；
        magnet_range: 磁吸触发半径（px），默认 96；
        弹回缓动固定为 ``EASING["spring"]``（OutBack）。
    示例::

        btn = MagneticButton("磁吸按钮")
        btn.clicked.connect(lambda: print("clicked"))
        btn.show()
    """

    def __init__(self, text="", max_offset=8.0, magnet_range=96.0, parent=None):
        super().__init__(parent)
        self._text = str(text)
        self._max = float(max_offset)
        self._range = float(magnet_range)
        self._offset = QPointF(0.0, 0.0)
        self._target = QPointF(0.0, 0.0)
        self._spring = None
        self.setMouseTracking(True)
        self.setCursor(Qt.PointingHandCursor)
        self._ticker = _Ticker(self, self._track, 16)
        _theme_refresh(self)

    # -- 状态 -----------------------------------------------------------
    @property
    def offset(self) -> QPointF:
        """当前位移（px）。"""
        return QPointF(self._offset)

    def text(self) -> str:
        return self._text

    def setText(self, text: str):
        self._text = str(text)
        self.updateGeometry()
        self.update()

    def sizeHint(self):
        fm = self.fontMetrics()
        pad = int(T("space.4"))
        extra = int(2 * self._max + 2)
        w = fm.horizontalAdvance(self._text) + 2 * pad + extra
        return QSize(max(w, 64 + extra), 32 + extra)

    def minimumSizeHint(self):
        return self.sizeHint()

    # -- 事件 -----------------------------------------------------------
    def showEvent(self, event):
        super().showEvent(event)
        parent = self.parentWidget()
        if parent is not None:
            # showEvent 可多次触发：安装前先移除，防同一事件被过滤 N 次
            parent.removeEventFilter(self)
            parent.installEventFilter(self)
            parent.setMouseTracking(True)

    def eventFilter(self, obj, event):
        if obj is self.parentWidget():
            etype = event.type()
            if etype == QEvent.MouseMove:
                pos = self.mapFromGlobal(event.globalPosition().toPoint())
                self._update_target(pos)
            elif etype == QEvent.Leave:
                self._release()
        return super().eventFilter(obj, event)

    def mouseMoveEvent(self, event):
        self._update_target(event.position().toPoint())
        super().mouseMoveEvent(event)

    def leaveEvent(self, event):
        self._release()
        super().leaveEvent(event)

    # -- 位移逻辑 -------------------------------------------------------
    def _update_target(self, pos):
        c = self.rect().center()
        dx, dy = pos.x() - c.x(), pos.y() - c.y()
        dist = math.hypot(dx, dy)
        if 1e-3 < dist < self._range:
            k = min(self._max, dist * 0.35) / dist
            self._set_target(QPointF(dx * k, dy * k))
        else:
            self._release()

    def _set_target(self, pt):
        self._target = QPointF(pt)
        if self._spring is not None:
            self._spring.stop()
            self._spring = None
        self._ticker.start()

    def _release(self):
        self._target = QPointF(0.0, 0.0)
        if math.hypot(self._offset.x(), self._offset.y()) < 0.4:
            self._offset = QPointF(0.0, 0.0)
            self.update()
            return
        start = QPointF(self._offset)
        if self._spring is not None:
            self._spring.stop()
        self._spring = _run_anim(
            self, DURATION["slow"], EASING["spring"],
            lambda v: self._apply_offset(QPointF(start.x() * (1.0 - v),
                                                 start.y() * (1.0 - v))))

    def _apply_offset(self, pt):
        self._offset = pt
        self.update()

    def _track(self, _elapsed, _dt):
        if self._target.isNull():
            self._ticker.stop()
            return
        nx = self._offset + (self._target - self._offset) * 0.35
        if (self._target - nx).manhattanLength() < 0.2:
            nx = QPointF(self._target)
        self._offset = nx
        self.update()

    def _resume_anim(self):
        # 无公共 start()：恢复跟踪 ticker（_track 空闲判定会自动停机）
        self._ticker.start()

    # -- 绘制 -----------------------------------------------------------
    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        m = self._max + 1.0
        rect = QRectF(self.rect()).adjusted(m, m, -m, -m)
        rect.translate(self._offset)
        hover = self.underMouse()
        pressed = self.isDown()
        if pressed:
            bg = _qcolor("primary.subtle")
        elif hover:
            bg = _mix(_qcolor("bg.elevated"), _qcolor("primary.subtle"), 0.45)
        else:
            bg = _qcolor("bg.elevated")
        border = _qcolor("primary") if (hover or pressed) else _qcolor("border")
        text_color = (_qcolor("primary") if (hover or pressed)
                      else _qcolor("text.primary"))
        p.setPen(QPen(border, 1.2))
        p.setBrush(bg)
        radius = float(T("radius.md"))
        p.drawRoundedRect(rect, radius, radius)
        p.setPen(text_color)
        p.drawText(rect, Qt.AlignCenter, self._text)
        p.end()


# ---------------------------------------------------------------------------
# 6. SkeletonShimmer —— 骨架屏微光扫过
# ---------------------------------------------------------------------------


class SkeletonShimmer(_HiddenPauseMixin, QWidget):
    """骨架屏占位 + 微光扫过（可被组件库骨架屏复用）。

    用途：内容加载期间的占位反馈；默认提供「头像 + 标题 + 两行文本」布局，
    可通过 ``blocks`` 自定义占位块（相对坐标 0~1）。
    主要参数：
        blocks: 元组序列 ``("rect"|"circle", x, y, w, h)``；
        period: 扫光周期（ms），默认 1400；interval: 帧间隔（ms），默认 33。
    示例::

        sk = SkeletonShimmer()
        sk.resize(280, 96)
        sk.start()
    """

    #: 默认占位块：("形状", x, y, w, h)，坐标为控件宽高的相对值
    DEFAULT_BLOCKS = (
        ("circle", 0.04, 0.12, 0.24, 0.76),
        ("rect", 0.34, 0.16, 0.58, 0.20),
        ("rect", 0.34, 0.48, 0.44, 0.15),
        ("rect", 0.34, 0.74, 0.62, 0.15),
    )

    def __init__(self, blocks=None, period=1400, interval=33, parent=None):
        super().__init__(parent)
        self._blocks = tuple(blocks) if blocks else self.DEFAULT_BLOCKS
        self._period = max(200, int(period))
        self._ticker = _Ticker(self, lambda _e, _d: self.update(), interval)
        _theme_refresh(self)
        self.start()

    def start(self):
        """启动扫光。"""
        self._ticker.start()

    def stop(self):
        """停止扫光。"""
        self._ticker.stop()

    def sizeHint(self):
        return QSize(280, 96)

    def _blocks_path(self) -> QPainterPath:
        w, h = self.width(), self.height()
        path = QPainterPath()
        radius = float(T("radius.sm"))
        for block in self._blocks:
            kind, x, y, bw, bh = block
            rect = QRectF(x * w, y * h, bw * w, bh * h)
            if kind == "circle":
                path.addEllipse(rect)
            else:
                path.addRoundedRect(rect, radius, radius)
        return path

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        path = self._blocks_path()
        p.setPen(Qt.NoPen)
        p.setBrush(_qcolor("bg.muted"))
        p.drawPath(path)
        # 微光扫过（裁剪到占位块内）
        w = self.width()
        band = w * 0.5
        phase = (self._ticker.elapsed % self._period) / self._period
        cx = -band + (w + 2 * band) * phase
        alpha = 130 if not _is_dark() else 55
        grad = QLinearGradient(cx - band / 2.0, 0, cx + band / 2.0, 0)
        grad.setColorAt(0.0, QColor(255, 255, 255, 0))
        grad.setColorAt(0.5, QColor(255, 255, 255, alpha))
        grad.setColorAt(1.0, QColor(255, 255, 255, 0))
        p.setClipPath(path)
        p.fillRect(self.rect(), grad)
        p.end()


# ---------------------------------------------------------------------------
# 7. Shimmer —— 任意区域微光扫过
# ---------------------------------------------------------------------------


class Shimmer(_HiddenPauseMixin, QWidget):
    """任意矩形区域的微光扫过效果，可独立使用或作为覆盖层叠加到目标控件上。

    用途：卡片、图片、按钮等区域的「加载 / 高光」强调。
    主要参数：
        period: 扫光周期（ms），默认 ``DURATION["slower"] * 3``；
        band: 光带宽度占比（0~1），默认 0.4；
        overlay: True 时透明背景 + 鼠标穿透，作为覆盖层叠到目标之上。
    示例::

        sh = Shimmer()
        sh.resize(200, 64)
        sh.start()
    """

    def __init__(self, period=None, band=0.4, overlay=False, interval=33, parent=None):
        super().__init__(parent)
        self._period = max(200, int(period if period else DURATION["slower"] * 3))
        self._band = max(0.1, min(1.0, float(band)))
        self._overlay = bool(overlay)
        if self._overlay:
            self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
            self.setAttribute(Qt.WA_TranslucentBackground, True)
            self.setStyleSheet("background: transparent;")
        self._ticker = _Ticker(self, lambda _e, _d: self.update(), interval)
        _theme_refresh(self)
        self.start()

    def start(self):
        """启动扫光。"""
        self._ticker.start()

    def stop(self):
        """停止扫光。"""
        self._ticker.stop()

    def sizeHint(self):
        return QSize(200, 64)

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        radius = float(T("radius.md"))
        clip = QPainterPath()
        clip.addRoundedRect(QRectF(0, 0, w, h), radius, radius)
        if not self._overlay:
            p.setPen(Qt.NoPen)
            p.setBrush(_qcolor("bg.muted"))
            p.drawPath(clip)
        band_px = w * self._band
        phase = (self._ticker.elapsed % self._period) / self._period
        cx = -band_px + (w + 2 * band_px) * phase
        alpha = 110 if not _is_dark() else 48
        grad = QLinearGradient(cx - band_px / 2.0, 0, cx + band_px / 2.0, 0)
        grad.setColorAt(0.0, QColor(255, 255, 255, 0))
        grad.setColorAt(0.5, QColor(255, 255, 255, alpha))
        grad.setColorAt(1.0, QColor(255, 255, 255, 0))
        p.setClipPath(clip)
        p.fillRect(self.rect(), grad)
        p.end()


# ---------------------------------------------------------------------------
# 8. ProgressStriped —— 条纹流动进度条
# ---------------------------------------------------------------------------


class ProgressStriped(_HiddenPauseMixin, QWidget):
    """条纹流动进度条：斜纹持续滚动，表达「进行中」。

    用途：上传 / 下载 / 批处理等不确定时长任务的进度反馈。
    主要参数：
        value: 初始进度 0~100；height: 条高（px），默认 10；
        stripe: 条纹间距（px），默认 12；running: 条纹是否持续流动。
    示例::

        bar = ProgressStriped(value=35)
        bar.animateTo(80)        # 平滑过渡到 80%
        bar.setValue(100)
    """

    def __init__(self, value=0.0, height=10, stripe=12, interval=40, parent=None):
        super().__init__(parent)
        self._value = max(0.0, min(100.0, float(value)))
        self._stripe = max(4, int(stripe))
        self._offset = 0.0
        self._anim = None
        self.setMinimumWidth(80)
        self.setFixedHeight(int(height))
        self._ticker = _Ticker(self, self._flow, interval)
        _theme_refresh(self)
        self.start()

    def start(self):
        """启动条纹流动。"""
        self._ticker.start()

    def stop(self):
        """停止条纹流动。"""
        self._ticker.stop()

    def value(self) -> float:
        return self._value

    def setValue(self, v: float):
        """直接设置进度 0~100。"""
        if self._anim is not None:
            self._anim.stop()
            self._anim = None
        self._set_value(v)

    def animateTo(self, v: float, duration=None):
        """以标准缓动平滑过渡到目标进度，返回动画句柄。"""
        if self._anim is not None:
            self._anim.stop()
        start = self._value
        end = max(0.0, min(100.0, float(v)))
        self._anim = _run_anim(
            self, duration if duration else DURATION["slow"], EASING["standard"],
            lambda t: self._set_value(start + (end - start) * t))
        return self._anim

    def _set_value(self, v: float):
        self._value = max(0.0, min(100.0, float(v)))
        self.update()

    def _flow(self, _elapsed, _dt):
        self._offset = (self._offset + 1.0) % (self._stripe * 2.0)
        self.update()

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        radius = h / 2.0
        # 轨道
        p.setPen(Qt.NoPen)
        p.setBrush(_qcolor("bg.muted"))
        p.drawRoundedRect(QRectF(0, 0, w, h), radius, radius)
        fill_w = w * self._value / 100.0
        if fill_w > 0.5:
            clip = QPainterPath()
            clip.addRoundedRect(QRectF(0, 0, fill_w, h), radius, radius)
            p.setClipPath(clip)
            p.fillRect(QRectF(0, 0, fill_w, h), _qcolor("primary"))
            # 斜纹（45°，随 offset 滚动）
            pen = QPen(QColor(255, 255, 255, 64))
            pen.setWidthF(self._stripe * 0.42)
            p.setPen(pen)
            x = -h + self._offset
            while x < fill_w + h:
                p.drawLine(QPointF(x, h), QPointF(x + h, 0))
                x += self._stripe * 2.0
        p.end()


# ---------------------------------------------------------------------------
# 9. MarqueeLabel —— 跑马灯
# ---------------------------------------------------------------------------


class MarqueeLabel(_HiddenPauseMixin, QWidget):
    """跑马灯：文本超出宽度时横向循环滚动，支持中文。

    用途：长标题、通知、歌词等单行文本的有限空间展示。
    主要参数：
        text: 文本；speed: 每帧像素步进，默认 1.6；
        gap: 首尾衔接间隔（px），默认 56；pause: 起始停顿（ms），默认 900。
    示例::

        mq = MarqueeLabel("这是一条很长很长需要滚动展示的中文通知")
        mq.resize(220, 24)
        mq.start()
    """

    def __init__(self, text="", speed=1.6, gap=56, pause=900, interval=30, parent=None):
        super().__init__(parent)
        self._text = str(text)
        self._speed = float(speed)
        self._gap = int(gap)
        self._pause = int(pause)
        self._offset = 0.0
        self._text_w = 0
        self._ticker = _Ticker(self, self._advance, interval)
        _theme_refresh(self)
        self.start()

    def text(self) -> str:
        return self._text

    def setText(self, text: str):
        """设置文本并重新从头滚动。"""
        self._text = str(text)
        self._offset = 0.0
        self._ticker.reset()
        self.update()

    def start(self):
        """启动滚动。"""
        self._ticker.start()

    def stop(self):
        """停止滚动。"""
        self._ticker.stop()

    def sizeHint(self):
        fm = self.fontMetrics()
        return QSize(min(max(60, fm.horizontalAdvance(self._text)), 260),
                     fm.height() + 8)

    def _advance(self, elapsed, _dt):
        if elapsed < self._pause:
            return
        if self._text_w <= self.width():
            return
        span = self._text_w + self._gap
        self._offset = (self._offset + self._speed) % span
        self.update()

    def paintEvent(self, _event):
        p = QPainter(self)
        fm = self.fontMetrics()
        self._text_w = fm.horizontalAdvance(self._text)
        baseline = (self.height() + fm.ascent() - fm.descent()) / 2.0
        p.setPen(_qcolor("text.primary"))
        if self._text_w <= self.width():
            p.drawText(QPointF(0.0, baseline), self._text)
        else:
            x = -self._offset
            span = self._text_w + self._gap
            while x < self.width():
                p.drawText(QPointF(x, baseline), self._text)
                x += span
        p.end()


# ---------------------------------------------------------------------------
# 10. FluidBackground —— 流体渐变背景
# ---------------------------------------------------------------------------


class FluidBackground(_HiddenPauseMixin, QWidget):
    """流体渐变背景：多色相正弦叠加的缓慢流动色块，30fps 性能可控。

    用途：登录页、英雄区、空状态等大面积背景的氛围渲染。
    主要参数：
        colors: 参与流动的语义色键序列，默认 ``("primary", "success", "warning")``；
        blobs: 色块数量，默认 3；fps: 帧率上限，默认 30；
        speed: 流动速度倍率，默认 1.0。
    示例::

        bg = FluidBackground()
        bg.resize(640, 360)
        bg.show()      # 作为底层背景，内容控件置于其上
    """

    def __init__(self, colors=None, blobs=3, fps=30, speed=1.0, parent=None):
        super().__init__(parent)
        self._colors = tuple(colors) if colors else ("primary", "success", "warning")
        self._blobs = max(1, int(blobs))
        self._speed = float(speed)
        interval = max(15, int(1000 / max(1, int(fps))))
        self._ticker = _Ticker(self, lambda _e, _d: self.update(), interval)
        _theme_refresh(self)
        self.start()

    def start(self):
        """启动流动。"""
        self._ticker.start()

    def stop(self):
        """停止流动。"""
        self._ticker.stop()

    def sizeHint(self):
        return QSize(480, 270)

    def paintEvent(self, _event):
        p = QPainter(self)
        w, h = self.width(), self.height()
        base = _qcolor("bg.base")
        grad = QLinearGradient(0, 0, 0, h)
        grad.setColorAt(0.0, base)
        grad.setColorAt(1.0, _qcolor("bg.subtle"))
        p.fillRect(self.rect(), grad)

        t = self._ticker.elapsed / 1000.0 * self._speed
        alpha = 64 if not _is_dark() else 84
        for i in range(self._blobs):
            w1 = 0.55 + i * 0.21
            w2 = 0.42 + i * 0.17
            ph = i * 2.13
            cx = w * (0.5 + 0.42 * math.sin(t * w1 + ph))
            cy = h * (0.5 + 0.38 * math.cos(t * w2 + ph * 1.3))
            r = min(w, h) * (0.52 + 0.16 * math.sin(t * 0.6 + i * 1.7))
            color = _qcolor(self._colors[i % len(self._colors)])
            rg = QRadialGradient(QPointF(cx, cy), max(8.0, r))
            rg.setColorAt(0.0, _with_alpha(color, alpha))
            rg.setColorAt(1.0, _with_alpha(color, 0))
            p.fillRect(self.rect(), rg)
        p.end()


# ---------------------------------------------------------------------------
# 11. TypewriterLabel —— 打字机
# ---------------------------------------------------------------------------


class TypewriterLabel(_HiddenPauseMixin, QLabel):
    """打字机：逐字显示文本，带闪烁光标，支持中文。

    用途：引导文案、AI 回复、终端风格输出等逐字呈现场景。
    主要参数：
        text: 完整文本；interval: 每字间隔（ms），默认 60；
        cursor: 是否显示闪烁光标，默认 True。
    信号：``finished()`` 全部打完时发射。
    示例::

        tw = TypewriterLabel("欢迎使用 InstructionX_UIKit")
        tw.finished.connect(lambda: print("done"))
        tw.start("重新打一段中文")   # 可随时重打
    """

    finished = Signal()

    CURSOR_CHAR = "▏"

    def __init__(self, text="", interval=60, cursor=True, parent=None):
        super().__init__("", parent)
        self._full = ""
        self._shown = 0
        self._cursor = bool(cursor)
        self._blink = True
        self._timer = QTimer(self)
        self._timer.setInterval(max(10, int(interval)))
        self._timer.timeout.connect(self._step)
        self._blink_timer = QTimer(self)
        self._blink_timer.setInterval(460)
        self._blink_timer.timeout.connect(self._toggle_blink)
        _theme_refresh(self)
        self._full = str(text)
        if self._full:
            self.start()

    def fullText(self) -> str:
        """完整文本。"""
        return self._full

    def setText(self, text: str):  # noqa: N802（保持 QLabel 接口）
        """设置文本并立即开始逐字打出。"""
        self._full = str(text)
        self.start()

    def setInterval(self, ms: int):
        """设置每字间隔（ms）。"""
        self._timer.setInterval(max(10, int(ms)))

    def start(self, text=None):
        """开始（或重新开始）打字；可附带新文本。"""
        if text is not None:
            self._full = str(text)
        self._shown = 0
        self._timer.start()
        if self._cursor:
            self._blink_timer.start()
        self._render()

    def stop(self):
        """停止打字（保持当前已显示内容）。"""
        self._timer.stop()
        self._blink_timer.stop()

    def _step(self):
        if self._shown >= len(self._full):
            self.stop()
            self._render()
            self.finished.emit()
            return
        self._shown += 1
        self._render()

    def _toggle_blink(self):
        self._blink = not self._blink
        if self._shown < len(self._full):
            self._render()

    def _render(self):
        shown = self._full[:self._shown]
        if self._cursor and self._shown < len(self._full):
            shown += self.CURSOR_CHAR if self._blink else " "
        super().setText(shown)


# ---------------------------------------------------------------------------
# 12. TextDecodeLabel —— 文字解码
# ---------------------------------------------------------------------------


class TextDecodeLabel(_HiddenPauseMixin, QLabel):
    """文字解码：乱码字符逐步「解码」为最终文本，支持中文。

    用途：科技感标题进场、解密 / 扫描氛围文案。
    主要参数：
        text: 目标文本；step: 每字错峰间隔（ms），默认 45；
        span: 同时处于乱码态的字符窗口，默认 4；
        interval: 刷新帧间隔（ms），默认 30。
    信号：``finished()`` 解码完成时发射。
    示例::

        dc = TextDecodeLabel("机密档案已解密")
        dc.start()                 # 播放解码
        dc.start("新的目标文本")   # 换文本重播
    """

    finished = Signal()

    #: 乱码字符池（英文 + 数字 + 常见汉字）
    POOL = ("abcdefghijklmnopqrstuvwxyz0123456789"
            "的一是在不了有和人这中大为上个国我以要他时来用们生到作地于出")

    def __init__(self, text="", step=45, span=4, interval=30, parent=None):
        super().__init__("", parent)
        self._full = str(text)
        self._step = max(5, int(step))
        self._span = max(1, int(span))
        self._interval = max(10, int(interval))
        self._elapsed = 0
        self._timer = QTimer(self)
        self._timer.setInterval(self._interval)
        self._timer.timeout.connect(self._tick)
        _theme_refresh(self)
        super().setText(self._full)

    def fullText(self) -> str:
        return self._full

    def setText(self, text: str):  # noqa: N802（保持 QLabel 接口）
        """设置目标文本（静态显示，调用 ``start()`` 播放解码）。"""
        self.stop()
        self._full = str(text)
        super().setText(self._full)

    def start(self, text=None):
        """开始（或重新开始）解码动画。"""
        if text is not None:
            self._full = str(text)
        self._elapsed = 0
        self._timer.start()
        self._render()

    def stop(self):
        """停止解码。"""
        self._timer.stop()

    def _tick(self):
        self._elapsed += self._interval
        head = self._elapsed // self._step
        if head - self._span >= len(self._full):
            self.stop()
            super().setText(self._full)
            self.finished.emit()
            return
        self._render()

    def _render(self):
        head = self._elapsed // self._step
        out = []
        for i, ch in enumerate(self._full):
            if i < head - self._span:
                out.append(ch)
            elif i < head:
                out.append(ch if ch.isspace() else random.choice(self.POOL))
            else:
                break
        super().setText("".join(out))


# ---------------------------------------------------------------------------
# 13. NumberRollLabel —— 数字滚动（count-up）
# ---------------------------------------------------------------------------


class NumberRollLabel(_HiddenPauseMixin, QLabel):
    """数字滚动标签：从当前值缓动滚动到目标值（count-up / count-down）。

    用途：统计数字、积分、金额等需要强调变化过程的数值展示。
    主要参数：
        value: 初始值；decimals: 小数位，默认 0；
        prefix / suffix: 前后缀文本；duration: 默认 ``DURATION["slower"]``；
        easing: 默认 ``EASING["emphasis"]``。
    信号：``valueChanged(float)``。
    说明：构造时初始值直接显示；``setValue`` 与 ``rollTo`` 一样总是从
    当前显示值缓动滚动到新值（动画挂在标签自身上，不会被提前回收）；
    ``reset(v)`` 立即跳变（不播动画），用于重放前归零。
    示例::

        num = NumberRollLabel(0, prefix="¥", decimals=2)
        num.rollTo(1024.50)        # 缓动滚到目标值
        num.reset(0)               # 立即归零（不播动画）
        num.setValue(1024.50)      # 重新从 0 缓动滚到目标值
    """

    valueChanged = Signal(float)

    def __init__(self, value=0.0, decimals=0, prefix="", suffix="",
                 duration=None, easing=None, parent=None):
        super().__init__("", parent)
        self._value = float(value)
        self._decimals = int(decimals)
        self._prefix = str(prefix)
        self._suffix = str(suffix)
        self._duration = int(duration if duration else DURATION["slower"])
        self._easing = easing if easing else EASING["emphasis"]
        self._anim = None
        font = self.font()
        font.setPixelSize(int(T("font.display")))
        font.setWeight(QFont.DemiBold)
        self.setFont(font)
        self.setAlignment(Qt.AlignCenter)
        _theme_refresh(self)
        self._render()

    def value(self) -> float:
        return self._value

    def reset(self, v: float = 0.0):
        """立即设置数值（不播放滚动动画），并停止进行中的动画。

        用于「播放前归零再滚到目标值」的演示 / 重放场景：
        ``rollTo`` / ``setValue`` 总是从当前值起滚，若当前值已等于
        目标值则画面无变化——先 ``reset(0)`` 即可重复看到滚动过程。
        """
        if self._anim is not None:
            self._anim.stop()
            self._anim = None
        self._set_value(float(v))

    def setValue(self, v: float):
        """设置数值：总是从当前显示值缓动滚动到新值，返回动画句柄。

        旧版为立即跳变（动画不生效）；现与 ``rollTo`` 等价，动画
        parent 为标签自身并持有引用，start == end 时也会完整走完
        （画面无变化属于预期——需强制重滚请先 ``reset()``）。
        """
        return self.rollTo(float(v))

    def rollTo(self, target: float, duration=None, easing=None):
        """滚动到目标值，返回动画句柄。"""
        if self._anim is not None:
            self._anim.stop()
        start = self._value
        end = float(target)
        self._anim = _run_anim(
            self,
            duration if duration else self._duration,
            easing if easing else self._easing,
            lambda t: self._set_value(start + (end - start) * t))
        return self._anim

    # 中文习惯别名
    roll_to = rollTo

    def _set_value(self, v: float):
        self._value = float(v)
        self._render()
        self.valueChanged.emit(self._value)

    def _render(self):
        super().setText(f"{self._prefix}{self._value:,.{self._decimals}f}{self._suffix}")


# ---------------------------------------------------------------------------
# 14. LetterStaggerLabel —— 逐字进场
# ---------------------------------------------------------------------------


class LetterStaggerLabel(_HiddenPauseMixin, QWidget):
    """逐字进场：每个字符依次淡入并上浮归位，支持中文。

    用途：标题、口号等需要强调排版的短文本进场。
    主要参数：
        text: 文本；stagger: 相邻字符错峰（ms），默认 55；
        letter_duration: 单字动画时长（ms），默认 ``DURATION["slow"]``；
        rise: 初始下偏移（px），默认 12；缓动取 ``EASING["standard"]``。
    信号：``finished()`` 全部字符进场完成时发射。
    示例::

        ls = LetterStaggerLabel("逐字进场效果")
        ls.resize(260, 40)
        ls.replay()      # 重放
    """

    finished = Signal()

    def __init__(self, text="", stagger=55, letter_duration=None, rise=12,
                 interval=16, parent=None):
        super().__init__(parent)
        self._text = str(text)
        self._stagger = max(5, int(stagger))
        self._letter_duration = int(letter_duration if letter_duration
                                    else DURATION["slow"])
        self._rise = float(rise)
        self._elapsed = 0
        self._done = False
        self._ticker = _Ticker(self, self._advance, interval)
        _theme_refresh(self)
        self.start()

    def text(self) -> str:
        return self._text

    def setText(self, text: str):
        """设置文本并重新进场。"""
        self._text = str(text)
        self.start()

    def start(self):
        """从头播放逐字进场。"""
        self._elapsed = 0
        self._done = False
        self._ticker.reset()
        self._ticker.start()
        self.update()

    # 别名，便于“重放”语义
    replay = start

    def stop(self):
        """停止（冻结在当前帧）。"""
        self._ticker.stop()

    def sizeHint(self):
        fm = self.fontMetrics()
        return QSize(fm.horizontalAdvance(self._text) + 8,
                     fm.height() + 8 + int(self._rise))

    def _advance(self, elapsed, _dt):
        self._elapsed = elapsed
        total = len(self._text) * self._stagger + self._letter_duration
        if elapsed >= total and not self._done:
            self._done = True
            self._ticker.stop()
            self.finished.emit()
        self.update()

    def paintEvent(self, _event):
        if not self._text:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        fm = self.fontMetrics()
        widths = [fm.horizontalAdvance(ch) for ch in self._text]
        total_w = sum(widths)
        x = max(0.0, (self.width() - total_w) / 2.0)
        baseline = (self.height() + fm.ascent() - fm.descent()) / 2.0
        color = _qcolor("text.primary")
        curve = QEasingCurve(EASING["standard"])
        for i, ch in enumerate(self._text):
            raw = (self._elapsed - i * self._stagger) / self._letter_duration
            prog = max(0.0, min(1.0, raw))
            eased = curve.valueForProgress(prog)
            p.setPen(_with_alpha(color, int(255 * eased)))
            dy = (1.0 - eased) * self._rise
            p.drawText(QPointF(x, baseline + dy), ch)
            x += widths[i]
        p.end()


# ---------------------------------------------------------------------------
# 15. ParallaxArea —— 视差滚动容器
# ---------------------------------------------------------------------------


class ParallaxArea(QScrollArea):
    """视差滚动容器：滚动时各图层按不同速率位移，形成纵深视差。

    用途：落地页头图、分层插画等「背景慢、前景快」的滚动体验。
    主要参数：
        addLayer(widget, factor): factor=1 随内容正常滚动，0 完全固定，
        0~1 之间为减速视差（值越小越慢）。
    说明：滚动由 ``valueChanged`` 信号驱动图层重定位。
    示例::

        pa = ParallaxArea()
        pa.addLayer(QLabel("远山（慢）"), factor=0.3)
        pa.addLayer(QLabel("前景（快）"), factor=0.9)
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWidgetResizable(True)
        self._container = QWidget()
        self.setWidget(self._container)
        self._layers = []          # [(widget, base_y, factor)]
        self._cursor = 0
        self._margin = int(T("space.4"))
        self.verticalScrollBar().valueChanged.connect(self._on_scroll)
        _theme_refresh(self)

    def addLayer(self, widget, factor=0.5, height=None):
        """追加一个图层，返回该控件。

        参数:
            widget: 图层控件（自动改挂到容器内、拉伸至视口宽）。
            factor: 滚动速率比，1=正常滚动，0=固定不动。
            height: 可选固定高度。
        """
        widget.setParent(self._container)
        if height:
            widget.setFixedHeight(int(height))
        h = widget.height() if widget.height() > 1 else max(40, widget.sizeHint().height())
        width = max(32, self.viewport().width() - 2 * self._margin)
        widget.setGeometry(self._margin, self._cursor, width, h)
        widget.show()
        self._layers.append((widget, self._cursor, float(factor)))
        self._cursor += h + int(T("space.6"))
        self._container.setMinimumHeight(self._cursor + int(T("space.16")))
        self._on_scroll(self.verticalScrollBar().value())
        return widget

    def layers(self) -> int:
        """图层数量。"""
        return len(self._layers)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        width = max(32, self.viewport().width() - 2 * self._margin)
        for widget, _base, _factor in self._layers:
            widget.resize(width, widget.height())
        self._on_scroll(self.verticalScrollBar().value())

    def _on_scroll(self, value):
        for widget, base, factor in self._layers:
            widget.move(widget.x(), base + int(value * (1.0 - factor)))


# ---------------------------------------------------------------------------
# 16. ScrollReveal —— 进入视口渐显
# ---------------------------------------------------------------------------


class ScrollReveal(QScrollArea):
    """滚动渐显容器：内容区直接子控件进入视口时自动淡入。

    用途：长页面分块进场，降低首屏信息压力。
    主要参数：
        content: 内容控件（通常为带 QVBoxLayout 的 QWidget）；
        threshold: 触发阈值（子控件顶边进入视口高度比例），默认 0.85；
        渐显时长取 ``DURATION["normal"]``，缓动取 ``EASING["standard"]``。
    说明：渐显通过「隐藏子控件（保留布局占位）+ 快照叠加层淡入」实现，
    **不使用 QGraphicsOpacityEffect**（真机 Windows + QSS + 高 DPI 下
    效果常驻 / 整片不绘制的平台坑）；结束后摘除叠加层并显示原控件，
    最终渲染与平台无关。扫描在控件尚未 show / 视口未就绪时会自动
    重试，避免演示卡「先构建后显示」时序下块被错误预隐藏。
    示例::

        box = QWidget(); lay = QVBoxLayout(box)
        for i in range(12): lay.addWidget(QLabel(f"第 {i+1} 块"))
        sr = ScrollReveal(box)
    """

    def __init__(self, content=None, threshold=0.85, parent=None):
        super().__init__(parent)
        self.setWidgetResizable(True)
        self._threshold = float(threshold)
        self._revealed = set()
        self._pre_hidden = {}   # 被预隐藏的子控件 → 原 QSizePolicy
        self._scan_retries = 0
        if content is not None:
            self.setContent(content)
        self.verticalScrollBar().valueChanged.connect(lambda *_: self._scan())
        _theme_refresh(self)

    def setContent(self, content: QWidget):
        """设置内容控件并对其直接子控件启用渐显。"""
        for child in self._pre_hidden:
            try:
                child.show()
            except RuntimeError:
                pass
        self._revealed.clear()
        self._pre_hidden.clear()
        self._scan_retries = 0
        self.setWidget(content)
        QTimer.singleShot(0, self._scan)

    def refresh(self):
        """手动触发一次扫描（内容增删后调用）。"""
        self._scan()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._scan()

    def showEvent(self, event):
        super().showEvent(event)
        self._scan_retries = 0
        QTimer.singleShot(0, self._scan)

    def _scan(self):
        content = self.widget()
        if content is None:
            return
        viewport = self.viewport()
        # 视口未就绪（未 show / 高度异常）时延迟重试——此时 mapTo 坐标
        # 不可信，预隐藏会把块错误地卡成不可见
        if not self.isVisible() or viewport.height() < 8:
            if self._scan_retries < 60:
                self._scan_retries += 1
                QTimer.singleShot(30, self._scan)
            return
        self._scan_retries = 0
        vh = max(1, viewport.height())
        sb = self.verticalScrollBar()
        # 已滚到底（或不可滚动）时，视口内的子控件一律渐显——否则顶边
        # 永远到不了阈值线的矮块会卡在 opacity=0（不渲染）。
        at_end = sb.value() >= sb.maximum()
        for child in content.findChildren(QWidget, options=Qt.FindDirectChildrenOnly):
            if child in self._revealed:
                continue
            # 视口判定统一用 mapTo(viewport) 的视口坐标系
            top = child.mapTo(viewport, QPoint(0, 0)).y()
            bottom = top + child.height()
            if bottom <= 0:
                # 已滚过视口上方：直接置为可见（无需再播动画）
                self._revealed.add(child)
                self._reveal(child, instant=True)
            elif top < vh and (top < vh * self._threshold or at_end):
                self._revealed.add(child)
                self._reveal(child)
            else:
                self._pre_hide(child)

    def _pre_hide(self, child):
        """未入视口的子控件隐藏（保留布局占位，滚动条不跳动）。"""
        if child in self._pre_hidden or child in self._revealed:
            return
        if child.isHidden():
            return  # 外部已隐藏的控件不接管
        sp = QSizePolicy(child.sizePolicy())
        if not sp.retainSizeWhenHidden():
            sp.setRetainSizeWhenHidden(True)
            child.setSizePolicy(sp)
        child.hide()
        self._pre_hidden[child] = sp

    def _reveal(self, child, instant=False):
        """渐显一个子控件；``instant=True`` 时直接显示（已滚过视口的情况）。

        渐显路径：隐藏原控件（保留占位），以快照叠加层 0→1 淡入，
        结束换回原控件——快照抓取对隐藏控件同样有效，全程无
        QGraphicsOpacityEffect。
        """
        orig_policy = self._pre_hidden.pop(child, None)
        if instant:
            if orig_policy is not None:
                child.setSizePolicy(orig_policy)
            child.show()
            return
        if orig_policy is None and not child.isHidden():
            # 直接进入视口（从未被预隐藏）：先隐藏再快照淡入
            sp = QSizePolicy(child.sizePolicy())
            if not sp.retainSizeWhenHidden():
                sp.setRetainSizeWhenHidden(True)
                child.setSizePolicy(sp)
            child.hide()
            orig_policy = sp  # 结束后还原用户原策略
        pixmap = _grab_pixmap(child)
        overlay = _SnapshotOverlay(child, pixmap, margin=1)
        overlay.opacity = 0.0

        def _finish(c=child, o=overlay, p=orig_policy):
            if p is not None:
                try:
                    c.setSizePolicy(p)
                except RuntimeError:
                    pass
            try:
                c.show()
            except RuntimeError:
                pass
            try:
                o.hide()
                o.deleteLater()
            except RuntimeError:
                pass

        def _fade(v, o=overlay):
            o.opacity = float(v)
            o.update()  # opacity 是普通属性，须显式触发逐帧重绘

        _run_anim(self, DURATION["normal"], EASING["standard"],
                  _fade, on_finish=_finish)


# ---------------------------------------------------------------------------
# 17. HorizontalScrollStrip —— 横向滚动条带
# ---------------------------------------------------------------------------


class HorizontalScrollStrip(_HiddenPauseMixin, QScrollArea):
    """横向滚动条带：条目横向排布并自动无缝循环滚动，悬停暂停。

    用途：标签云、Logo 墙、公告条等横向信息带。
    主要参数：
        items: 字符串序列（自动生成胶囊标签）或 QWidget 序列；
        step: 每帧像素步进，默认 1.5；interval: 帧间隔（ms），默认 30；
        autoplay: 是否自动滚动，默认 True。
    说明：字符串条目自动复制一份实现无缝循环（valueChanged 驱动回卷）。
    示例::

        strip = HorizontalScrollStrip(["设计", "令牌", "组件", "动画", "布局"])
        strip.resize(420, 44)
        strip.show()
    """

    def __init__(self, items=(), step=1.5, interval=30, autoplay=True, parent=None):
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._step = float(step)
        self._items = list(items)
        self._chips = []
        self._copy_span = 0
        self._paused = False
        self._container = QWidget()
        self._layout = QHBoxLayout(self._container)
        self._layout.setContentsMargins(12, 6, 12, 6)
        self._layout.setSpacing(int(T("space.3")))
        self.setWidget(self._container)
        self._ticker = _Ticker(self, self._advance, interval)
        sb = self.horizontalScrollBar()
        sb.valueChanged.connect(self._wrap)
        sb.rangeChanged.connect(lambda *_: self._measure())
        _theme_refresh(self)
        ThemeManager.instance().theme_changed.connect(self._restyle)
        self._rebuild()
        if autoplay:
            self.start()

    # -- 内容 -----------------------------------------------------------
    def addItem(self, item):
        """追加条目（字符串转胶囊标签，QWidget 直接嵌入），随后重建。"""
        self._items.append(item)
        self._rebuild()

    def items(self) -> int:
        return len(self._items)

    def _make_chip(self, text: str) -> QLabel:
        chip = QLabel(text)
        chip.setProperty("uik_chip", True)
        self._style_chip(chip)
        self._chips.append(chip)
        return chip

    @staticmethod
    def _style_chip(chip: QLabel):
        chip.setStyleSheet(
            f"background-color: {T('color.bg.muted')};"
            f"color: {T('color.text.secondary')};"
            f"border-radius: 13px; padding: 4px 14px;")

    def _restyle(self):
        for chip in self._chips:
            self._style_chip(chip)

    def _rebuild(self):
        self._chips = []
        while self._layout.count():
            item = self._layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()
        for _copy in range(2):
            for entry in self._items:
                if isinstance(entry, str):
                    self._layout.addWidget(self._make_chip(entry))
                elif isinstance(entry, QWidget):
                    if _copy == 0:
                        self._layout.addWidget(entry)
        self._container.adjustSize()
        QTimer.singleShot(0, self._measure)

    def _measure(self):
        margins = self._layout.contentsMargins()
        spacing = self._layout.spacing()
        self._copy_span = max(
            0, (self._container.width() - margins.left() - margins.right()
                + spacing) // 2)

    # -- 滚动 -----------------------------------------------------------
    def start(self):
        """启动自动滚动。"""
        self._ticker.start()

    def stop(self):
        """停止自动滚动。"""
        self._ticker.stop()

    def enterEvent(self, event):
        self._paused = True
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._paused = False
        super().leaveEvent(event)

    def _advance(self, _elapsed, _dt):
        if self._paused:
            return
        sb = self.horizontalScrollBar()
        if sb.maximum() <= 0:
            return
        sb.setValue(sb.value() + self._step)

    def _wrap(self, value):
        if self._copy_span > 0 and value >= self._copy_span:
            self.horizontalScrollBar().setValue(int(value - self._copy_span))


# ---------------------------------------------------------------------------
# 18. StickyHeader —— 粘性固定头
# ---------------------------------------------------------------------------


class StickyHeader(QScrollArea):
    """粘性固定头：页头随内容滚动，到达顶部后吸附固定。

    用途：长列表分组头、文章标题栏等需要常驻的场景。
    主要参数：
        setHeaderWidget(w): 设置吸附头部控件；
        setBody(body, cover_height): 设置主体内容；``cover_height`` 为头部
        上方的封面区高度（头部先随封面滚走再吸附，0 表示始终吸附）。
    示例::

        sh = StickyHeader()
        sh.setHeaderWidget(QLabel("章节标题"))
        sh.setBody(long_content, cover_height=120)
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWidgetResizable(True)
        self._header = None
        self._header_h = 0
        self._cover_h = 0
        self._body = None
        self._container = QWidget()
        self._layout = QVBoxLayout(self._container)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(0)
        self._spacer = QWidget()
        self._layout.addWidget(self._spacer)
        self.setWidget(self._container)
        self.verticalScrollBar().valueChanged.connect(lambda _v: self._place())
        _theme_refresh(self)

    def setHeaderWidget(self, widget: QWidget):
        """设置粘性头部控件（自动吸附在视口顶部）。"""
        self._header = widget
        widget.setParent(self.viewport())
        hint = widget.sizeHint().height()
        self._header_h = hint if hint > 0 else 40
        widget.setFixedHeight(self._header_h)
        widget.show()
        widget.raise_()
        self._refresh_spacer()
        self._place()

    def headerWidget(self):
        return self._header

    def setBody(self, body: QWidget, cover_height=0):
        """设置主体内容；cover_height 为头部上方预留的封面高度。"""
        if self._body is not None:
            self._layout.removeWidget(self._body)
            self._body.setParent(None)
        self._body = body
        self._cover_h = max(0, int(cover_height))
        self._layout.addWidget(body)
        self._refresh_spacer()
        self._place()

    def _refresh_spacer(self):
        self._spacer.setFixedHeight(self._cover_h + self._header_h)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._place()

    def _place(self):
        if self._header is None:
            return
        value = self.verticalScrollBar().value()
        y = max(0, self._cover_h - value)
        self._header.setGeometry(0, y, self.viewport().width(), self._header_h)
        self._header.raise_()


# ---------------------------------------------------------------------------
# 19. ScrollProgressBar —— 滚动进度条
# ---------------------------------------------------------------------------


class ScrollProgressBar(QWidget):
    """滚动进度条：实时显示所挂载 QScrollArea 的滚动进度。

    用途：长文阅读、向导页等顶部的阅读进度提示。
    主要参数：
        area: 目标 QScrollArea（也可稍后 ``attach(area)``）；
        height: 条高（px），默认 4。
    说明：由目标滚动条 ``valueChanged`` / ``rangeChanged`` 信号驱动。
    示例::

        sp = ScrollProgressBar(scroll_area)
        sp.setValue(0.5)      # 未挂接时可手动设置 0~1
        sp.value()
    """

    def __init__(self, area=None, height=4, parent=None):
        super().__init__(parent)
        self._value = 0.0
        self._range = (0, 0)
        self._sb = None
        self.setFixedHeight(int(height))
        self.setMinimumWidth(60)
        _theme_refresh(self)
        if area is not None:
            self.attach(area)

    def attach(self, area: QScrollArea):
        """挂载到一个 QScrollArea（垂直滚动条）。"""
        sb = area.verticalScrollBar()
        self._sb = sb
        sb.valueChanged.connect(self._on_scroll)
        sb.rangeChanged.connect(self._on_range)
        self._on_range(sb.minimum(), sb.maximum())

    def value(self) -> float:
        """当前进度 0~1。"""
        return self._value

    def setValue(self, frac: float):
        """手动设置进度 0~1（未挂接滚动区时使用）。"""
        self._value = max(0.0, min(1.0, float(frac)))
        self.update()

    def _on_range(self, minimum, maximum):
        self._range = (minimum, maximum)
        if self._sb is not None:
            self._on_scroll(self._sb.value())

    def _on_scroll(self, v):
        minimum, maximum = self._range
        span = max(1, maximum - minimum)
        self._value = max(0.0, min(1.0, (v - minimum) / span))
        self.update()

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        radius = h / 2.0
        p.setPen(Qt.NoPen)
        p.setBrush(_qcolor("bg.muted"))
        p.drawRoundedRect(QRectF(0, 0, w, h), radius, radius)
        if self._value > 0.0:
            p.setBrush(_qcolor("primary"))
            p.drawRoundedRect(QRectF(0, 0, max(h, w * self._value), h),
                              radius, radius)
        p.end()


# ---------------------------------------------------------------------------
# 20. ScrollStoryArea —— 滚动叙事
# ---------------------------------------------------------------------------


class _StoryOverlay(QWidget):
    """ScrollStoryArea 的视口覆盖层：绘制时间线轴与步骤圆点。"""

    def __init__(self, area):
        super().__init__(area.viewport())
        self._area = area
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setStyleSheet("background: transparent;")
        self.hide()

    def bind(self):
        self.setGeometry(self._area.viewport().rect())
        self.show()
        self.raise_()

    def paintEvent(self, _event):
        area = self._area
        n = area.stepCount()
        if n == 0:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        x = w - 22.0
        top, bottom = 20.0, h - 20.0
        # 轴
        p.setPen(QPen(_qcolor("border.strong"), 2.0))
        p.drawLine(QPointF(x, top), QPointF(x, bottom))
        # 进度
        frac = area.progress()
        p.setPen(QPen(_qcolor("primary"), 2.4))
        p.drawLine(QPointF(x, top), QPointF(x, top + (bottom - top) * frac))
        # 步骤圆点
        active = area.activeIndex()
        for i in range(n):
            y = top + (bottom - top) * (i / max(1, n - 1) if n > 1 else 0.5)
            if i == active:
                p.setPen(Qt.NoPen)
                p.setBrush(_qcolor("primary"))
                p.drawEllipse(QPointF(x, y), 5.0, 5.0)
            else:
                p.setPen(QPen(_qcolor("border.strong"), 1.6))
                p.setBrush(_qcolor("bg.elevated"))
                p.drawEllipse(QPointF(x, y), 3.5, 3.5)
        p.end()


class _StoryStepPanel(QFrame):
    """ScrollStoryArea 的步骤卡片：paintEvent 内按 alpha 参数化整体不透明度。

    不使用 QGraphicsOpacityEffect（项目红线：真机 Windows + QSS +
    高 DPI 下常驻效果可能整片不渲染）。改为「离屏缓存 + 半透明合成」：
    全不透明内容（含 QSS 样式与子控件）在 paintEvent **之外**经
    render() 抓进缓存位图，paintEvent 仅按当前 alpha 把缓存合成回
    自身。【勿改回】在 paintEvent 内直接 ``self.render()``：控件此时
    正处于自身绘制上下文，Qt 判定递归重绘（"QWidget::repaint:
    Recursive repaint detected"），后续 QPainter 拿不到 paint engine
    （"Painter must be active" 系列刷屏）且实际不绘制（真机 Windows
    与 offscreen 均可复现，探针 temp/_story_probe.py）。
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFrameShape(QFrame.StyledPanel)
        self._alpha = 0.3
        self._cache = None          # 全不透明内容缓存位图（paintEvent 外抓取）
        self._capture_pending = False
        self._capturing = False     # 缓存抓取触发的离屏重入戳记
        # 主题切换后 QSS 颜色变化，缓存需失效重抓；绑定方法随控件销毁
        # 自动断连（与 _theme_refresh 同一机制）
        ThemeManager.instance().theme_changed.connect(self._invalidate_cache)

    def set_alpha(self, alpha: float):
        """设置整体不透明度 0~1（仅变化时重绘，抑制滚动高频下的无谓重绘）。"""
        alpha = max(0.0, min(1.0, float(alpha)))
        if abs(alpha - self._alpha) > 0.002:
            self._alpha = alpha
            self.update()

    def alpha(self) -> float:
        return self._alpha

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._invalidate_cache()

    def _invalidate_cache(self):
        """尺寸 / 主题变化后丢弃缓存并按需安排重抓。"""
        self._cache = None
        if self._alpha < 0.999:
            self._schedule_capture()

    def _schedule_capture(self):
        if self._capture_pending:
            return
        self._capture_pending = True
        QTimer.singleShot(0, self._capture)

    def _capture(self):
        """在 paintEvent 外把自身（含 QSS 与子控件）渲染进缓存位图。"""
        self._capture_pending = False
        if self.width() < 2 or self.height() < 2:
            return
        dpr = max(1.0, float(self.devicePixelRatioF()))
        pm = QPixmap(max(2, int(math.ceil(self.width() * dpr))),
                     max(2, int(math.ceil(self.height() * dpr))))
        pm.setDevicePixelRatio(dpr)
        pm.fill(Qt.transparent)
        # render() 会触发一次离屏 paintEvent：戳记挡在缓存就绪前，
        # 保证抓进位图的是基类全不透明内容而非缓存自身的二次合成
        self._capturing = True
        try:
            self.render(pm)
        finally:
            self._capturing = False
        self._cache = pm
        if self._alpha < 0.999:
            self.update()

    def paintEvent(self, event):
        if self._capturing or self._alpha >= 0.999 or self._cache is None:
            if (not self._capturing and self._alpha < 0.999
                    and self._cache is None):
                # 缓存未就绪：先按不透明兜底绘制，异步抓缓存后切换为
                # 半透明合成（仅首帧，避免在绘制上下文里调用 render()）
                self._schedule_capture()
            super().paintEvent(event)
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        p.setOpacity(self._alpha)
        p.drawPixmap(0, 0, self._cache)
        p.end()


class ScrollStoryArea(QScrollArea):
    """滚动叙事：滚动进度驱动一条侧轴时间线，步骤卡片靠近视口中心时点亮。

    用途：产品历程、教程步骤、版本故事线等随滚动推进的叙事页面。
    主要参数：
        addStep(title, text): 追加一个叙事步骤卡片；
        progress(): 当前滚动进度 0~1；activeIndex(): 当前激活步骤序号。
    说明：步骤卡片的明暗由 :class:`_StoryStepPanel` 在 paintEvent 内
    按进度参数化 alpha 实现，不使用 QGraphicsOpacityEffect。
    示例::

        st = ScrollStoryArea()
        st.addStep("第一步", "准备环境并安装依赖")
        st.addStep("第二步", "编写第一个页面")
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWidgetResizable(True)
        self._steps = []
        self._progress = 0.0
        self._active = -1
        self._bottom_pad = 24
        self._container = QWidget()
        self._layout = QVBoxLayout(self._container)
        self._layout.setContentsMargins(24, 24, 56, self._bottom_pad)
        self._layout.setSpacing(int(T("space.6")))
        self.setWidget(self._container)
        self._overlay = _StoryOverlay(self)
        self.verticalScrollBar().valueChanged.connect(lambda _v: self._update_story())
        _theme_refresh(self)

    def addStep(self, title: str, text: str) -> QFrame:
        """追加叙事步骤，返回步骤卡片控件。"""
        panel = _StoryStepPanel()
        lay = QVBoxLayout(panel)
        lay.setContentsMargins(16, 12, 16, 12)
        lay.setSpacing(6)
        title_label = QLabel(title)
        font = title_label.font()
        font.setPixelSize(int(T("font.title.sm")))
        font.setWeight(QFont.DemiBold)
        title_label.setFont(font)
        body_label = QLabel(text)
        body_label.setWordWrap(True)
        body_label.setProperty("role", "secondary")
        lay.addWidget(title_label)
        lay.addWidget(body_label)
        self._layout.addWidget(panel)
        self._steps.append(panel)
        QTimer.singleShot(0, self._update_story)
        return panel

    def stepCount(self) -> int:
        """步骤数量。"""
        return len(self._steps)

    def progress(self) -> float:
        """滚动进度 0~1。"""
        return self._progress

    def activeIndex(self) -> int:
        """当前最接近视口中心的步骤序号（无步骤时为 -1）。"""
        return self._active

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._overlay.bind()
        self._update_bottom_pad()
        self._update_story()

    def showEvent(self, event):
        super().showEvent(event)
        self._overlay.bind()
        self._update_bottom_pad()
        self._update_story()

    def _update_bottom_pad(self):
        """底部留白提升到半个视口高：滚到底时末卡片能靠近视口中心。

        否则高视口 + 矮卡片时，视口中心在最大滚动处离末卡片中心比
        倒数第二张更远，最后一个时间线点永远不会被点亮（off-by-one）。
        """
        pad = max(24, self.viewport().height() // 2)
        if pad != self._bottom_pad:
            self._bottom_pad = pad
            m = self._layout.contentsMargins()
            self._layout.setContentsMargins(m.left(), m.top(), m.right(), pad)

    def _update_story(self):
        sb = self.verticalScrollBar()
        span = max(1, sb.maximum() - sb.minimum())
        self._progress = max(0.0, min(1.0, (sb.value() - sb.minimum()) / span))
        center_y = sb.value() + self.viewport().height() / 2.0
        best, best_dist = -1, float("inf")
        vh = max(1, self.viewport().height())
        for i, panel in enumerate(self._steps):
            panel_center = panel.y() + panel.height() / 2.0
            dist = abs(panel_center - center_y)
            if dist < best_dist:
                best, best_dist = i, dist
            near = max(0.0, 1.0 - dist / (vh * 0.75))
            panel.set_alpha(0.3 + 0.7 * near)
        if self._steps and sb.maximum() > sb.minimum():
            # 端点修正：滚到底末步必点亮，回到顶首步必点亮
            if sb.value() >= sb.maximum():
                best = len(self._steps) - 1
            elif sb.value() <= sb.minimum():
                best = 0
        self._active = best
        self._overlay.update()


# ---------------------------------------------------------------------------
# 21. CardTilt —— 卡片倾斜（随鼠标 3D 透视）
# ---------------------------------------------------------------------------


class CardTilt(_HiddenPauseMixin, QWidget):
    """卡片倾斜：鼠标在卡片上移动时产生伪 3D 透视倾斜，离开弹回。

    用途：重点卡片、商品封面等的立体质感强调。无需 OpenGL，
    通过 ``QTransform`` 透视系数模拟。
    主要参数：
        content: 可选内容控件（隐藏原控件、以其快照参与倾斜）；
        max_angle: 最大倾角（度），默认 10；persp: 透视距离，默认 700；
        回弹缓动取 ``EASING["spring"]``。
    说明：绘制时按最大倾角预先内缩内容区域（四周留出透视外扩余量），
    保证任意倾角下卡片四边都不被自身 rect 裁剪；内容快照按不低于 3x
    超采样抓取，倾斜时文字不模糊。
    示例::

        tilt = CardTilt(QLabel("封面内容"))
        tilt.resize(260, 170)
        tilt.show()
    """

    def __init__(self, content=None, max_angle=10.0, persp=700.0, parent=None):
        super().__init__(parent)
        self._content = None
        self._max_angle = float(max_angle)
        self._persp = float(persp)
        self._rx = 0.0
        self._ry = 0.0
        self._anim = None
        self._margin_cache = {}
        self._snap_cache = {}     # 内容快照缓存（键含尺寸 / 内容 / 主题）
        self.setMouseTracking(True)
        self.setMinimumSize(220, 150)
        _theme_refresh(self)
        if content is not None:
            self.setContent(content)

    def setContent(self, widget: QWidget):
        """设置内容控件（其快照随倾斜渲染）。"""
        self._content = widget
        widget.setParent(self)
        widget.resize(self.size())
        widget.hide()
        self._snap_cache = {}

    def contentWidget(self):
        return self._content

    def tilt(self):
        """当前倾角 (rx, ry)，单位度。"""
        return self._rx, self._ry

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._content is not None:
            self._content.resize(self.size())
        self._snap_cache = {}

    def mouseMoveEvent(self, event):
        w, h = max(1, self.width()), max(1, self.height())
        nx = (event.position().x() - w / 2.0) / (w / 2.0)
        ny = (event.position().y() - h / 2.0) / (h / 2.0)
        nx = max(-1.0, min(1.0, nx))
        ny = max(-1.0, min(1.0, ny))
        if self._anim is not None:
            self._anim.stop()
            self._anim = None
        self._ry = nx * self._max_angle
        self._rx = -ny * self._max_angle
        self.update()
        super().mouseMoveEvent(event)

    def leaveEvent(self, event):
        start_rx, start_ry = self._rx, self._ry
        if abs(start_rx) > 0.01 or abs(start_ry) > 0.01:
            if self._anim is not None:
                self._anim.stop()
            self._anim = _run_anim(
                self, DURATION["slow"], EASING["spring"],
                lambda v: self._set_tilt(start_rx * (1.0 - v),
                                         start_ry * (1.0 - v)))
        super().leaveEvent(event)

    def _set_tilt(self, rx, ry):
        self._rx, self._ry = rx, ry
        self.update()

    def _content_pixmap(self) -> QPixmap:
        return _cached_face_snapshot(
            self, self._content, "CardTilt", "移动鼠标查看倾斜")

    def _tilt_margin(self, w: int, h: int) -> float:
        """最大倾角下四角透视外扩的最大像素量（+2 安全余量），按尺寸缓存。"""
        key = (w, h)
        margin = self._margin_cache.get(key)
        if margin is not None:
            return margin
        cx, cy = w / 2.0, h / 2.0
        worst = 0.0
        for sx in (-1.0, 1.0):
            for sy in (-1.0, 1.0):
                ox, oy = cx + sx * cx, cy + sy * cy
                for srx in (-1.0, 1.0):
                    for sry in (-1.0, 1.0):
                        t = _tilt_transform(cx, cy,
                                            srx * self._max_angle,
                                            sry * self._max_angle,
                                            self._persp)
                        pt = t.map(QPointF(ox, oy))
                        worst = max(worst,
                                    (pt.x() - ox) * sx,
                                    (pt.y() - oy) * sy)
        margin = max(0.0, worst) + 2.0
        self._margin_cache[key] = margin
        return margin

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        w, h = self.width(), self.height()
        cx, cy = w / 2.0, h / 2.0
        pm = self._content_pixmap()
        # 底部软影（随倾斜轻微偏移）
        shadow_alpha = 46 if not _is_dark() else 90
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(0, 0, 0, shadow_alpha))
        off = self._ry * 0.6
        p.drawEllipse(QRectF(w * 0.12 + off, h - 13.0, w * 0.76, 9.0))
        # 伪 3D 变换绘制内容：绕控件中心倾转；目标区域按最大倾角
        # 预先内缩，四角在任意倾角下都不会被自身 rect 裁剪
        m = self._tilt_margin(w, h)
        target = QRectF(m, m, w - 2.0 * m, h - 2.0 * m)
        p.setTransform(_tilt_transform(cx, cy, self._rx, self._ry, self._persp))
        p.drawPixmap(target, pm, QRectF(pm.rect()))
        p.end()


# ---------------------------------------------------------------------------
# 22. CubeRotator —— 立方体旋转（两画面）
# ---------------------------------------------------------------------------


class CubeRotator(_HiddenPauseMixin, QWidget):
    """立方体旋转：两个画面像立方体相邻面一样绕竖直轴切换。

    用途：双状态展示（前后对比、双视图切换）、广告位轮播。
    主要参数：
        front / side: 两个面的文本（也可用 setFrontWidget / setSideWidget
        传入控件）；persp: 透视距离，默认 520；
        rotate(): 旋转 180° 切换到另一面；时长取 ``DURATION["slower"]``。
    示例::

        cube = CubeRotator("正面", "侧面")
        cube.rotate()          # 手动旋转
        cube.startAuto(2400)   # 自动轮流旋转
    """

    def __init__(self, front="正面", side="侧面", persp=520.0, parent=None):
        super().__init__(parent)
        self._texts = [str(front), str(side)]
        self._widgets = [None, None]
        self._face = 0
        self._angle = 0.0        # 动画进行中的角度 0~180
        self._anim = None
        self._persp = float(persp)
        self._snap_cache = {}    # 面快照缓存（键含面序号 / 尺寸 / 内容 / 主题）
        self.setMinimumSize(240, 160)
        self._auto = QTimer(self)
        self._auto.timeout.connect(self.rotate)
        _theme_refresh(self)

    def setFrontWidget(self, widget: QWidget):
        """设置正面控件（快照渲染）。"""
        self._widgets[0] = self._adopt(widget)
        self._snap_cache = {}

    def setSideWidget(self, widget: QWidget):
        """设置侧面控件（快照渲染）。"""
        self._widgets[1] = self._adopt(widget)
        self._snap_cache = {}

    def _adopt(self, widget):
        widget.setParent(self)
        widget.resize(self.size())
        widget.hide()
        return widget

    def resizeEvent(self, event):
        super().resizeEvent(event)
        for w in self._widgets:
            if w is not None:
                w.resize(self.size())
        self._snap_cache = {}

    def face(self) -> int:
        """当前朝向的面：0 正面，1 侧面。"""
        return self._face

    def rotate(self, duration=None):
        """旋转到另一面；动画进行中调用无效，返回动画句柄或 None。

        句柄被外部 ``stop()``（如演示卡重放停止旧句柄）时 ``on_finish``
        不触发、``_anim`` 不复位会导致之后调用全部失效，且角度可能停在
        90°（侧棱朝前、画面全空）；这里检测残留句柄自动解锁并吸附到
        就近一面。
        """
        if self._anim is not None:
            if self._anim.state() == QAbstractAnimation.Running:
                return None
            # 过半则视为已翻到另一面（angle 归 0，与 _finish 同构），
            # 未过半则回到当前面——角度复位保证画面不卡在侧棱空帧
            if self._angle >= 90.0:
                self._face = 1 - self._face
            self._anim = None
            self._angle = 0.0
            self.update()
        # InOutSine：同 FlipCard，避免起步段即冲到侧棱空帧
        self._anim = _run_anim(
            self, duration if duration else DURATION["slower"],
            QEasingCurve(QEasingCurve.InOutSine),
            lambda v: self._set_angle(v * 180.0),
            on_finish=self._finish)
        return self._anim

    def startAuto(self, interval=2400):
        """启动自动轮流旋转。"""
        self._auto.start(int(interval))

    def stopAuto(self):
        """停止自动旋转。"""
        self._auto.stop()

    def _resume_anim(self):
        # 无公共 start()：恢复自动轮播定时器（隐藏前在跑才被调用）
        self._auto.start()

    def _set_angle(self, deg):
        self._angle = deg
        self.update()

    def _finish(self):
        self._face = 1 - self._face
        self._angle = 0.0
        self._anim = None
        self.update()

    def _face_pixmap(self, idx) -> QPixmap:
        return _cached_face_snapshot(
            self, self._widgets[idx], self._texts[idx],
            "rotate() 切换到另一面", idx)

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        w, h = self.width(), self.height()
        cx, cy = w / 2.0, h / 2.0
        angle = self._angle
        if angle < 90.0:
            shown, face_angle = self._face, angle
        else:
            shown, face_angle = 1 - self._face, angle - 180.0
        pm = self._face_pixmap(shown)
        transform = QTransform()
        transform.translate(cx, cy)
        transform = transform * _rot_y(face_angle, self._persp)
        transform.translate(-cx, -cy)
        p.setTransform(transform)
        p.drawPixmap(QRectF(0.0, 0.0, float(w), float(h)), pm, QRectF(pm.rect()))
        p.end()


# ---------------------------------------------------------------------------
# 23. FlipCard —— 翻转卡片
# ---------------------------------------------------------------------------


class FlipCard(_HiddenPauseMixin, QWidget):
    """翻转卡片：正 / 背两面绕竖直轴 180° 翻转（点击或调用 flip()）。

    用途：会员卡片、单词卡、信息正反对照展示。
    主要参数：
        front / back: 两面文本（也可用 setFrontWidget / setBackWidget）；
        persp: 透视距离，默认 640；时长取 ``DURATION["slower"]``。
    信号：``flipped(bool)`` True 表示当前为背面朝上。
    示例::

        card = FlipCard("问题", "答案")
        card.flipped.connect(lambda back: print("背面" if back else "正面"))
        card.flip()
    """

    flipped = Signal(bool)

    def __init__(self, front="正面", back="背面", persp=640.0, parent=None):
        super().__init__(parent)
        self._texts = [str(front), str(back)]
        self._widgets = [None, None]
        self._flipped = False
        self._angle = 0.0
        self._anim = None
        self._persp = float(persp)
        self._snap_cache = {}    # 面快照缓存（键含面序号 / 尺寸 / 内容 / 主题）
        self.setMinimumSize(220, 140)
        self.setCursor(Qt.PointingHandCursor)
        _theme_refresh(self)

    def setFrontWidget(self, widget: QWidget):
        """设置正面控件（快照渲染）。"""
        self._widgets[0] = self._adopt(widget)
        self._snap_cache = {}

    def setBackWidget(self, widget: QWidget):
        """设置背面控件（快照渲染）。"""
        self._widgets[1] = self._adopt(widget)
        self._snap_cache = {}

    def _adopt(self, widget):
        widget.setParent(self)
        widget.resize(self.size())
        widget.hide()
        return widget

    def resizeEvent(self, event):
        super().resizeEvent(event)
        for w in self._widgets:
            if w is not None:
                w.resize(self.size())
        self._snap_cache = {}

    def isFlipped(self) -> bool:
        return self._flipped

    def flip(self, duration=None):
        """翻转到另一面，返回动画句柄（动画进行中返回 None）。

        动画句柄若被外部 ``stop()``（如演示卡重放停止旧句柄），
        ``on_finish`` 不会触发、``_anim`` 不复位会导致之后点击 /
        调用全部失效；这里检测「非 Running 的残留句柄」并自动解锁，
        角度取就近一面吸附。
        """
        if self._anim is not None:
            if self._anim.state() == QAbstractAnimation.Running:
                return None
            # 被外部停止的残留句柄：解锁并吸附到就近一面
            self._anim = None
            self._angle = 180.0 if self._angle >= 90.0 else 0.0
            self._flipped = self._angle >= 90.0
            self.update()
        start = self._angle
        target = 180.0 if not self._flipped else 0.0
        # InOutSine：翻转两端慢、中段快——起步段角度小（不会因 OutCubic
        # 在前 ~20% 就冲到 ~85° 侧棱空帧），观感也更接近真实翻牌
        self._anim = _run_anim(
            self, duration if duration else DURATION["slower"],
            QEasingCurve(QEasingCurve.InOutSine),
            lambda v: self._set_angle(start + (target - start) * v),
            on_finish=lambda: self._finish(target))
        return self._anim

    def _set_angle(self, deg):
        self._angle = deg
        self.update()

    def _finish(self, target):
        self._angle = target
        self._anim = None
        self._flipped = target >= 90.0
        self.flipped.emit(self._flipped)
        self.update()

    def mousePressEvent(self, event):
        # 显式接受按下事件：默认实现 ignore 后事件会向父容器（演示卡）
        # 冒泡，部分平台下点击链路表现为「点击无反应」
        event.accept()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self.rect().contains(event.position().toPoint()):
            event.accept()
            self.flip()
            return
        super().mouseReleaseEvent(event)

    def _face_pixmap(self, idx) -> QPixmap:
        return _cached_face_snapshot(
            self, self._widgets[idx], self._texts[idx], "点击翻转", idx)

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        w, h = self.width(), self.height()
        cx, cy = w / 2.0, h / 2.0
        angle = self._angle % 360.0
        if angle <= 90.0 or angle >= 270.0:
            shown = 0
            face_angle = angle if angle <= 90.0 else angle - 360.0
        else:
            shown = 1
            face_angle = angle - 180.0
        pm = self._face_pixmap(shown)
        transform = QTransform()
        transform.translate(cx, cy)
        transform = transform * _rot_y(face_angle, self._persp)
        transform.translate(-cx, -cy)
        p.setTransform(transform)
        p.drawPixmap(QRectF(0.0, 0.0, float(w), float(h)), pm, QRectF(pm.rect()))
        p.end()


# ---------------------------------------------------------------------------
# 24. CoverFlow —— 立体轮播（透视堆叠）
# ---------------------------------------------------------------------------


class CoverFlow(QWidget):
    # 注意：不混入 _HiddenPauseMixin——slideTo 对「_anim 非 None」直接
    # 返回 None 且无解锁逻辑，隐藏停机会让后续导航永久失效；其切换
    # 动画仅 slow(320) 且非定时器空转，隐藏期间短时运行可接受。
    """立体轮播：3~5 项卡片以伪 3D 透视堆叠，居中聚焦、两侧旋转退后。

    用途：专辑封面、商品推荐、图片精选等强调当前项的横向浏览。
    主要参数：
        items: 条目标题序列；persp: 透视距离，默认 460；
        next() / prev() / slideTo(i) 切换当前项；左右方向键同样可用；
        切换时长取 ``DURATION["slow"]``，缓动取 ``EASING["standard"]``。
    信号：``currentChanged(int)``。
    示例::

        cf = CoverFlow(["设计", "组件", "动画", "布局", "主题"])
        cf.currentChanged.connect(lambda i: print("当前", i))
        cf.next()
    """

    currentChanged = Signal(int)

    def __init__(self, items=(), persp=460.0, parent=None):
        super().__init__(parent)
        self._titles = [str(t) for t in items]
        self._pos = 0.0
        self._anim = None
        self._persp = float(persp)
        self.setMinimumSize(520, 280)
        self.setFocusPolicy(Qt.StrongFocus)
        _theme_refresh(self)

    def setItems(self, items):
        """重置条目并回到第一项。"""
        if self._anim is not None:
            self._anim.stop()
            self._anim = None
        self._titles = [str(t) for t in items]
        self._pos = 0.0
        self.update()

    def count(self) -> int:
        return len(self._titles)

    def currentIndex(self) -> int:
        if not self._titles:
            return -1
        return max(0, min(len(self._titles) - 1, int(round(self._pos))))

    def next(self):
        """切换到下一项，返回动画句柄或 None。"""
        return self.slideTo(self.currentIndex() + 1)

    def prev(self):
        """切换到上一项，返回动画句柄或 None。"""
        return self.slideTo(self.currentIndex() - 1)

    def slideTo(self, index: int, duration=None):
        """切换到指定项，返回动画句柄（无变化或动画中返回 None）。"""
        if not self._titles or self._anim is not None:
            return None
        target = max(0, min(len(self._titles) - 1, int(index)))
        if abs(target - self._pos) < 1e-3:
            return None
        start = self._pos
        self._anim = _run_anim(
            self, duration if duration else DURATION["slow"], EASING["standard"],
            lambda v: self._set_pos(start + (target - start) * v),
            on_finish=lambda: self._finish(target))
        return self._anim

    def _set_pos(self, v):
        self._pos = v
        self.update()

    def _finish(self, target):
        self._anim = None
        self._pos = float(target)
        self.currentChanged.emit(int(target))
        self.update()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Left:
            self.prev()
            return
        if event.key() == Qt.Key_Right:
            self.next()
            return
        super().keyPressEvent(event)

    def mouseReleaseEvent(self, event):
        # 点击左 / 右三分之一区域切换
        if self._titles and event.button() == Qt.LeftButton:
            x = event.position().x()
            if x < self.width() / 3.0:
                self.prev()
            elif x > self.width() * 2.0 / 3.0:
                self.next()
        super().mouseReleaseEvent(event)

    def _card_color(self, i: int) -> QColor:
        base = _qcolor("primary")
        hue = (base.hue() + i * 26) % 360
        sat = min(255, int(base.hsvSaturation() * 0.85) + 40)
        val = max(120, base.value())
        return QColor.fromHsv(hue, sat, val)

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        w, h = self.width(), self.height()
        p.fillRect(self.rect(), _qcolor("bg.base"))
        n = len(self._titles)
        if n == 0:
            p.setPen(_qcolor("text.tertiary"))
            p.drawText(self.rect(), Qt.AlignCenter, "（空）setItems() 添加条目")
            p.end()
            return
        cw = min(220.0, w * 0.34)
        ch = min(240.0, h * 0.72)
        cx, cy = w / 2.0, h / 2.0
        order = sorted(range(n), key=lambda i: -abs(i - self._pos))
        dim_color = QColor(0, 0, 0) if _is_dark() else QColor(255, 255, 255)
        for i in order:
            d = i - self._pos
            if abs(d) > 2.6:
                continue
            xoff = d * cw * 0.74
            scale = max(0.5, 1.0 - 0.16 * abs(d))
            ry = -52.0 * max(-1.0, min(1.0, d))
            transform = QTransform()
            transform.translate(cx + xoff, cy)
            transform = transform * _rot_y(ry, self._persp)
            transform.scale(scale, scale)
            p.setTransform(transform)
            card = QRectF(-cw / 2.0, -ch / 2.0, cw, ch)
            # 卡面：纵向渐变 + 序号 + 标题
            top = _mix(self._card_color(i), QColor(255, 255, 255), 0.18)
            bottom = self._card_color(i)
            grad = QLinearGradient(card.topLeft(), card.bottomLeft())
            grad.setColorAt(0.0, top)
            grad.setColorAt(1.0, bottom)
            p.setPen(QPen(_qcolor("border.strong"), 1.0))
            p.setBrush(grad)
            radius = float(T("radius.xl"))
            p.drawRoundedRect(card, radius, radius)
            p.setPen(_qcolor("on.primary"))
            font = QFont(p.font())
            font.setPixelSize(int(T("font.hero")))
            font.setWeight(QFont.Bold)
            p.setFont(font)
            p.drawText(QRectF(card.x(), card.y() + ch * 0.16, cw, ch * 0.4),
                       Qt.AlignCenter, str(i + 1))
            font.setPixelSize(int(T("font.title.sm")))
            font.setWeight(QFont.DemiBold)
            p.setFont(font)
            p.drawText(QRectF(card.x(), card.y() + ch * 0.62, cw, ch * 0.24),
                       Qt.AlignCenter, self._titles[i])
            # 深度压暗 / 提亮蒙层
            dim = min(1.0, abs(d) / 2.0)
            if dim > 0.01:
                p.setPen(Qt.NoPen)
                dim_color.setAlpha(int(150 * dim))
                p.setBrush(dim_color)
                p.drawRoundedRect(card, radius, radius)
        p.end()
