# -*- coding: utf-8 -*-
"""属性类动画预设（SPEC §7.1）。

基于 ``QPropertyAnimation`` / ``QVariantAnimation`` /
``QParallelAnimationGroup`` / ``QSequentialAnimationGroup`` 实现。

统一约定
--------
- 每个预设一个函数，签名为 ``def <name>(target, **opts)``；
- 函数内部即启动动画，并返回动画对象 / 动画组（调用方可 ``stop()``）；
- 时长默认取 ``tokens.DURATION``，缓动默认取 ``tokens.EASING``；
- 不阻塞事件循环；
- 动画对象统一 parent 到 ``target``（或显式保存引用），防止被 GC。

实现取舍（重要，fix/f3 起改为快照叠加层路径）
------------------------------------------------
实测发现两类平台相关缺陷导致动画在真机（Windows + Qt6 + QSS 控件 +
高 DPI）上「完全不渲染」（离屏测试全部通过、无法暴露）：

1. ``QGraphicsEffect``（含 ``QGraphicsOpacityEffect`` /
   ``QGraphicsBlurEffect`` / ``QGraphicsDropShadowEffect`` / 自定义
   ``_TransformEffect``）在该平台组合下可能整片不绘制；
2. ``pos`` / ``geometry`` 属性动画对「布局管理的控件」会被下一次
   布局刷新重置，视觉上等于动画不工作。

因此本模块的入场 / 强调 / 过渡类预设统一改走 :class:`_SnapshotOverlay`
**快照叠加层基元**：动画开始时对目标 ``render()`` 取位图（按
``devicePixelRatioF`` 采样），用一个浮于目标位置的透明叠加 QWidget
以纯 ``QPainter`` 路径施加 透明度 / 缩放 / 旋转 / 平移 / 模糊
（预模糊级联）/ 裁剪揭示 / 辉光 / 投影；动画期间目标由
:class:`_SnapSession` 隐藏（布局管理的目标先用同尺寸占位控件替换，
避免隐藏触发兄弟重排），结束或 ``stop()`` 后自动还原目标可见性与
布局位置。该路径不触碰目标的 ``pos`` / ``graphicsEffect``，在布局
托管与绝对定位两种宿主下行为一致。

仍保留 ``QGraphicsEffect`` 的少数路径：``switch_toggle``（短促按压
反馈，需实时反映 checked 变化）与 ``shared_element(fade=True)``；
主题级 ``apply_shadow`` 不在本模块。各函数 docstring 注明实现路径。
"""

import math
from html import escape as _html_escape

from PySide6.QtCore import (
    QAbstractAnimation,
    QEasingCurve,
    QEvent,
    QObject,
    QParallelAnimationGroup,
    QPoint,
    QPointF,
    QPropertyAnimation,
    QRect,
    QRectF,
    QSequentialAnimationGroup,
    Qt,
    QTimer,
    QVariantAnimation,
    Property,
)
from PySide6.QtGui import (
    QColor,
    QImage,
    QMouseEvent,
    QPainter,
    QPainterPath,
    QPixmap,
)
from PySide6.QtWidgets import (
    QApplication,
    QGraphicsBlurEffect,
    QGraphicsDropShadowEffect,
    QGraphicsEffect,
    QGraphicsOpacityEffect,
    QLabel,
    QStackedWidget,
    QWidget,
)

from ..theme import T, ThemeManager, apply_shadow
from ..tokens import DURATION, EASING

__all__ = [
    "fade_in",
    "fade_out",
    "slide_in",
    "zoom_in",
    "spring_pop",
    "stagger_in",
    "blur_in",
    "mask_reveal",
    "hover_lift",
    "button_morph_loading",
    "ripple",
    "switch_toggle",
    "pulse",
    "bounce",
    "swing",
    "shake",
    "flash_highlight",
    "float_loop",
    "pulse_glow",
    "breathing",
    "gradient_flow",
    "gradient_text_flow",
    "cross_fade",
    "page_transition",
    "slide_transition",
    "container_morph",
    "shared_element",
    "badge_pop",
]

#: QWidget maximumWidth/Height 的默认值（Qt 常量 QWIDGETSIZE_MAX）
_MAX_SIZE = 16777215


# ---------------------------------------------------------------------------
# 内部工具
# ---------------------------------------------------------------------------

def _dur(opts: dict, key: str = "normal") -> int:
    """取动画时长：opts['duration'] 支持 int(ms) / DURATION 键名，缺省取 DURATION[key]。"""
    d = opts.get("duration")
    if d is None:
        return DURATION[key]
    if isinstance(d, str):
        return DURATION[d]
    return int(d)


def _ease(opts: dict, key: str = "standard") -> QEasingCurve:
    """取缓动曲线：opts['easing'] 支持 QEasingCurve.Type / EASING 键名。"""
    e = opts.get("easing")
    if e is None:
        e = EASING[key]
    elif isinstance(e, str):
        e = EASING[e]
    if isinstance(e, QEasingCurve):
        return e
    return QEasingCurve(e)


def _own(target: QObject, anim):
    """防止动画对象被 GC：无 parent 时挂到 target 下，然后返回动画。"""
    if isinstance(anim, QObject) and anim.parent() is None and isinstance(target, QObject):
        anim.setParent(target)
    return anim


def _maybe_remove_effect(target: QWidget, effect: QGraphicsEffect) -> None:
    """动画结束后摘除图形效果（避免常驻像素化渲染影响文字清晰度）。"""
    if target is not None and target.graphicsEffect() is effect:
        target.setGraphicsEffect(None)


def _opacity_effect(target: QWidget) -> QGraphicsOpacityEffect:
    """取 target 上不透明度效果，没有则新建并挂载。"""
    eff = target.graphicsEffect()
    if isinstance(eff, QGraphicsOpacityEffect):
        return eff
    eff = QGraphicsOpacityEffect(target)
    eff.setOpacity(1.0)
    target.setGraphicsEffect(eff)
    return eff


def _lerp_color(c1: QColor, c2: QColor, t: float) -> QColor:
    """两颜色线性插值。"""
    return QColor(
        round(c1.red() + (c2.red() - c1.red()) * t),
        round(c1.green() + (c2.green() - c1.green()) * t),
        round(c1.blue() + (c2.blue() - c1.blue()) * t),
        round(c1.alpha() + (c2.alpha() - c1.alpha()) * t),
    )


def _lerp_gradient(colors, t: float) -> QColor:
    """在循环渐变色带上取 t ∈ [0,1) 位置的颜色（相邻色线性插值）。"""
    n = len(colors)
    if n == 1:
        return QColor(colors[0])
    t = t % 1.0
    seg = t * n
    i = int(seg) % n
    frac = seg - int(seg)
    return _lerp_color(QColor(colors[i]), QColor(colors[(i + 1) % n]), frac)


# ---------------------------------------------------------------------------
# 内部效果与叠加层
# ---------------------------------------------------------------------------

class _TransformEffect(QGraphicsEffect):
    """缩放 / 旋转 / 透明度三合一图形效果。

    Qt6 中 ``QGraphicsScale`` / ``QGraphicsRotation`` 不再继承
    ``QGraphicsEffect``，无法挂到 QWidget；本类以 ``QGraphicsEffect``
    方式实现同等能力，并额外支持透明度，便于「缩放 + 淡入」组合。

    暴露 Qt 属性（可直接被 ``QPropertyAnimation`` 驱动）：
    ``scale``（float，1.0 为原尺寸）、``opacity``（float 0~1）、
    ``angle``（float，绕中心顺时针角度）。
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._scale = 1.0
        self._opacity = 1.0
        self._angle = 0.0

    # -- Qt 属性 -----------------------------------------------------------
    def _get_scale(self) -> float:
        return self._scale

    def _set_scale(self, v: float) -> None:
        self._scale = float(v)
        self.update()

    scale = Property(float, _get_scale, _set_scale)

    def _get_opacity(self) -> float:
        return self._opacity

    def _set_opacity(self, v: float) -> None:
        self._opacity = float(v)
        self.update()

    opacity = Property(float, _get_opacity, _set_opacity)

    def _get_angle(self) -> float:
        return self._angle

    def _set_angle(self, v: float) -> None:
        self._angle = float(v)
        self.update()

    angle = Property(float, _get_angle, _set_angle)

    # -- 绘制 ---------------------------------------------------------------
    def draw(self, painter: QPainter) -> None:  # noqa: N802（Qt 虚函数）
        offset = QPoint()
        pm = self.sourcePixmap(Qt.LogicalCoordinates, offset)
        if pm.isNull():
            return
        w = pm.width() / pm.devicePixelRatio()
        h = pm.height() / pm.devicePixelRatio()
        painter.save()
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        painter.setOpacity(self._opacity)
        # 以控件中心为原点做旋转 / 缩放
        painter.translate(offset.x() + w / 2.0, offset.y() + h / 2.0)
        painter.rotate(self._angle)
        painter.scale(self._scale, self._scale)
        painter.translate(-w / 2.0, -h / 2.0)
        painter.drawPixmap(0, 0, pm)
        painter.restore()


def _transform_effect(target: QWidget) -> _TransformEffect:
    """取 target 上的变换效果，没有则新建并挂载。"""
    eff = target.graphicsEffect()
    if isinstance(eff, _TransformEffect):
        return eff
    eff = _TransformEffect(target)
    target.setGraphicsEffect(eff)
    return eff


def _force_transparent(widget: QWidget) -> None:
    """强制叠加层 / 占位控件背景透明。

    主题全局 QSS 含基座规则 ``QWidget { background-color: <bg.base> }``，
    会把普通 QWidget 刷成不透明底色块；叠加层一旦带不透明底，外扩的
    margin 区域就会变成盖住相邻控件的实心矩形（真机可见的「块」）。
    这里三重压制：
    - ``WA_TranslucentBackground``：render()/grab() 时不再填充窗口底色；
    - ``setAutoFillBackground(False)``：禁止 palette 背景自动填充；
    - 实例级 ``background: transparent``：压过全局 QSS 基座规则
      （实例样式表优先级高于应用程序级样式表）。
    """
    widget.setAttribute(Qt.WA_TranslucentBackground, True)
    widget.setAutoFillBackground(False)
    widget.setStyleSheet("background: transparent; border: none;")


class _Overlay(QWidget):
    """覆盖在目标控件上的透明自绘层（涟漪 / 高亮闪烁共用）。

    - 鼠标事件穿透（``WA_TransparentForMouseEvents``）；
    - ``set_ripple(center, radius, opacity)``：以 center 为圆心画扩散圆；
    - ``set_fill(opacity)``：整体填充（圆角裁剪）。
    """

    def __init__(self, target: QWidget, color: QColor, radius: float = 6.0):
        super().__init__(target)
        _force_transparent(self)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setFocusPolicy(Qt.NoFocus)
        self._color = QColor(color)
        self._corner = float(radius)
        self._mode = None  # None / "ripple" / "fill"
        self._center = QPointF(0, 0)
        self._radius = 0.0
        self._opacity = 0.0
        self.setGeometry(target.rect())
        self.show()
        self.raise_()

    def set_ripple(self, center: QPointF, radius: float, opacity: float) -> None:
        """设置涟漪参数并重绘。"""
        self._mode = "ripple"
        self._center = QPointF(center)
        self._radius = float(radius)
        self._opacity = float(opacity)
        self.update()

    def set_fill(self, opacity: float) -> None:
        """设置整体填充不透明度并重绘。"""
        self._mode = "fill"
        self._opacity = float(opacity)
        self.update()

    def clear(self) -> None:
        """清空并重绘。"""
        self._mode = None
        self._opacity = 0.0
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802（Qt 虚函数）
        if self._mode is None or self._opacity <= 0.0:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        path = QPainterPath()
        path.addRoundedRect(self.rect().toRectF(), self._corner, self._corner)
        painter.setClipPath(path)
        color = QColor(self._color)
        color.setAlphaF(max(0.0, min(1.0, self._opacity)))
        painter.setPen(Qt.NoPen)
        painter.setBrush(color)
        if self._mode == "ripple":
            painter.drawEllipse(self._center, self._radius, self._radius)
        else:
            painter.drawPath(path)
        painter.end()


# ---------------------------------------------------------------------------
# 快照叠加层动画基元（平台鲁棒路径，见模块 docstring）
# ---------------------------------------------------------------------------

def _grab_pixmap(target: QWidget) -> QPixmap:
    """抓取目标控件位图（隐藏控件亦可），按 ``devicePixelRatioF`` 设置 DPR。

    用 ``render()`` 而非 ``grab()``：对尚未 show 或刚被隐藏的控件同样
    有效，且位图按设备像素采样、回放时按逻辑尺寸绘制，高 DPI 下不模糊。
    """
    try:
        dpr = float(target.devicePixelRatioF())
    except Exception:  # noqa: BLE001 - 极端平台兜底
        dpr = 1.0
    dpr = max(1.0, dpr)
    w = max(2, int(math.ceil(max(1, target.width()) * dpr)))
    h = max(2, int(math.ceil(max(1, target.height()) * dpr)))
    pm = QPixmap(w, h)
    pm.setDevicePixelRatio(dpr)
    pm.fill(Qt.transparent)
    target.render(pm)
    return pm


def _blur_pixmap(pm: QPixmap, radius_logical: float) -> QPixmap:
    """「缩小 → 平滑放大」级联生成近似高斯模糊位图（DPR 保持不变）。

    模糊类动画逐帧实时高斯模糊代价高；这里按档位预算位图，
    动画帧间在两档间交叉淡化即可获得平滑的模糊过渡。
    """
    r = float(radius_logical)
    dpr = pm.devicePixelRatio() or 1.0
    k = r * dpr
    if k < 1.05:
        return pm
    w, h = pm.width(), pm.height()
    sw = max(1, int(round(w / k)))
    sh = max(1, int(round(h / k)))
    img = pm.toImage()
    small = img.scaled(sw, sh, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
    back = small.scaled(w, h, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
    out = QPixmap.fromImage(back)
    out.setDevicePixelRatio(dpr)
    return out


def _tinted_pixmap(pm: QPixmap, color: QColor, pad: int = 0) -> QPixmap:
    """保留 alpha、整体替换为单色的剪影位图（辉光 / 投影用）。

    ``pad``（逻辑像素）在四周补透明边距，避免模糊光晕在边缘被裁断。
    """
    dpr = pm.devicePixelRatio() or 1.0
    img = pm.toImage().convertToFormat(QImage.Format_ARGB32_Premultiplied)
    p = int(round(pad * dpr))
    if p > 0:
        canvas = QImage(img.width() + 2 * p, img.height() + 2 * p,
                        QImage.Format_ARGB32_Premultiplied)
        canvas.fill(Qt.transparent)
        cp = QPainter(canvas)
        cp.drawImage(p, p, img)
        cp.end()
        img = canvas
    tint = QImage(img.size(), QImage.Format_ARGB32_Premultiplied)
    tint.fill(color)
    tp = QPainter(tint)
    tp.setCompositionMode(QPainter.CompositionMode_DestinationIn)
    tp.drawImage(0, 0, img)
    tp.end()
    out = QPixmap.fromImage(tint)
    out.setDevicePixelRatio(dpr)
    return out


class _SnapshotOverlay(QWidget):
    """浮于目标控件位置的快照自绘层（不依赖 ``QGraphicsEffect``）。

    paintEvent 中对目标快照位图施加 透明度 / 缩放 / 旋转 / 平移 /
    模糊（预模糊级联）/ 裁剪揭示 / 辉光 / 投影，全部走纯 QPainter
    路径。几何 = 目标几何四周外扩 ``margin``（容纳过冲缩放 / 旋转 /
    位移 / 光晕）。

    属性（直接赋值后 ``update()`` 即重绘）：
    ``opacity`` ``scale`` ``angle`` ``dx`` ``dy`` ``blur``
    ``glow_radius`` / ``glow_color`` ``shadow_blur`` / ``shadow_color`` /
    ``shadow_offset`` / ``shadow_opacity`` ``clip_mode`` / ``clip_progress``

    交互钩子（hover_lift 用）：``on_leave`` 离开回调；``forward_to``
    鼠标事件转发目标（保持被覆盖按钮可点击）。
    """

    def __init__(self, target: QWidget, pixmap: QPixmap, margin: float = 1,
                 mouse_transparent: bool = True):
        parent = target.parentWidget()
        super().__init__(parent if parent is not None else target)
        # 父对象 = 目标父控件，几何 = 目标 geometry（父坐标系）外扩 margin，
        # 坐标系一致；目标随滚动区内容移动时叠加层天然跟随（同一父控件）。
        _force_transparent(self)
        self._target_ref = target
        self._pm = pixmap
        self._margin = max(1, int(math.ceil(margin)))
        self._tw = max(1, target.width())
        self._th = max(1, target.height())
        self.opacity = 1.0
        self.scale = 1.0
        self.angle = 0.0
        self.dx = 0.0
        self.dy = 0.0
        self.blur = 0.0
        self.glow_radius = 0.0
        self.glow_color = None
        self.shadow_blur = 0.0
        self.shadow_color = None
        self.shadow_offset = (0.0, 0.0)
        self.shadow_opacity = 0.0
        self.clip_mode = None
        self.clip_progress = 1.0
        self.on_leave = None
        self.forward_to = None
        self._blur_cache = {}
        self._tint_cache = None
        self._tint_color = None
        self._tint_blur_cache = {}
        if mouse_transparent:
            self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setFocusPolicy(Qt.NoFocus)
        if parent is not None:
            geo = target.geometry()
        else:
            geo = target.rect()
        m = self._margin
        self.setGeometry(geo.adjusted(-m, -m, m, m))
        self.show()
        self.raise_()

    # -- 内部绘制辅助 ------------------------------------------------------
    @staticmethod
    def _draw_pm(painter: QPainter, pm: QPixmap, w: float, h: float) -> None:
        painter.drawPixmap(QRectF(0.0, 0.0, w, h), pm, QRectF(pm.rect()))

    def _blur_level(self, radius: float) -> QPixmap:
        key = max(1, int(round(radius)))
        if key not in self._blur_cache:
            self._blur_cache[key] = _blur_pixmap(self._pm, key)
        return self._blur_cache[key]

    def _tint(self, color: QColor) -> QPixmap:
        if self._tint_cache is None or self._tint_color != color:
            self._tint_cache = _tinted_pixmap(self._pm, color, pad=self._margin)
            self._tint_color = QColor(color)
            self._tint_blur_cache = {}
        return self._tint_cache

    def _glow_pixmap(self, radius: float, color: QColor) -> QPixmap:
        tint = self._tint(color)
        key = max(1, int(round(radius)))
        if key not in self._tint_blur_cache:
            self._tint_blur_cache[key] = _blur_pixmap(tint, key)
        return self._tint_blur_cache[key]

    def _draw_glow(self, painter: QPainter, pm: QPixmap, cx: float, cy: float,
                   w: float, h: float) -> None:
        m = float(self._margin)
        painter.drawPixmap(QRectF(cx - w / 2.0 - m, cy - h / 2.0 - m,
                                  w + 2 * m, h + 2 * m),
                           pm, QRectF(pm.rect()))

    def _apply_clip(self, painter: QPainter, w: float, h: float) -> None:
        p = max(0.0, min(1.0, self.clip_progress))
        mode = self.clip_mode
        if mode == "right":
            painter.setClipRect(QRectF(0.0, 0.0, w * p, h))
        elif mode == "left":
            painter.setClipRect(QRectF(w * (1.0 - p), 0.0, w * p, h))
        elif mode == "down":
            painter.setClipRect(QRectF(0.0, 0.0, w, h * p))
        elif mode == "up":
            painter.setClipRect(QRectF(0.0, h * (1.0 - p), w, h * p))
        elif mode == "circle":
            half = math.hypot(w, h) / 2.0
            path = QPainterPath()
            path.addEllipse(QPointF(w / 2.0, h / 2.0), half * p, half * p)
            painter.setClipPath(path)

    def _draw_content(self, painter: QPainter, w: float, h: float) -> None:
        op = max(0.0, min(1.0, self.opacity))
        if self.blur > 0.05:
            # 在相邻两档预模糊位图间交叉淡化
            lo, hi = 0.0, 1.0
            while hi < self.blur and hi < 128:
                lo, hi = hi, hi * 2.0
            t = 0.0 if hi <= lo else (self.blur - lo) / (hi - lo)
            t = max(0.0, min(1.0, t))
            pm_lo = self._pm if lo == 0.0 else self._blur_level(lo)
            pm_hi = self._blur_level(hi)
            painter.setOpacity(op * (1.0 - t))
            self._draw_pm(painter, pm_lo, w, h)
            painter.setOpacity(op * t)
            self._draw_pm(painter, pm_hi, w, h)
        else:
            painter.setOpacity(op)
            self._draw_pm(painter, self._pm, w, h)

    # -- Qt 虚函数 ---------------------------------------------------------
    def paintEvent(self, event) -> None:  # noqa: N802（Qt 虚函数）
        if self._pm.isNull():
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
        painter.setRenderHint(QPainter.Antialiasing, True)
        m = float(self._margin)
        w, h = float(self._tw), float(self._th)
        cx, cy = m + w / 2.0, m + h / 2.0
        # 辉光 / 投影（内容之下，跟随平移；缩放旋转仅作用于内容）
        if self.glow_radius > 0.0 and self.glow_color is not None:
            glow = self._glow_pixmap(self.glow_radius, self.glow_color)
            painter.save()
            painter.setOpacity(max(0.0, min(1.0, self.opacity)))
            self._draw_glow(painter, glow, cx + self.dx, cy + self.dy, w, h)
            painter.restore()
        if (self.shadow_blur > 0.0 and self.shadow_color is not None
                and self.shadow_opacity > 0.0):
            sh = self._glow_pixmap(self.shadow_blur, self.shadow_color)
            painter.save()
            painter.setOpacity(max(0.0, min(1.0, self.shadow_opacity)))
            self._draw_glow(painter, sh,
                            cx + self.dx + self.shadow_offset[0],
                            cy + self.dy + self.shadow_offset[1], w, h)
            painter.restore()
        # 内容（变换 + 裁剪 + 透明度 / 模糊）
        painter.save()
        painter.translate(cx + self.dx, cy + self.dy)
        painter.rotate(self.angle)
        painter.scale(self.scale, self.scale)
        painter.translate(-w / 2.0, -h / 2.0)
        if self.clip_mode is not None:
            self._apply_clip(painter, w, h)
        self._draw_content(painter, w, h)
        painter.restore()
        painter.end()

    def leaveEvent(self, event) -> None:  # noqa: N802（Qt 虚函数）
        if self.on_leave is not None:
            try:
                self.on_leave()
            except RuntimeError:
                pass
        super().leaveEvent(event)

    def _forward_mouse(self, event) -> None:
        """把鼠标事件换算坐标后转发给被覆盖的目标控件（保持可点击）。"""
        target = self.forward_to
        if target is None:
            event.ignore()
            return
        try:
            delta = (event.position() + QPointF(self.geometry().topLeft())
                     - QPointF(target.geometry().topLeft()))
            forwarded = QMouseEvent(
                event.type(), delta, event.globalPosition(),
                event.button(), event.buttons(), event.modifiers())
            QApplication.sendEvent(target, forwarded)
        except RuntimeError:
            pass
        event.accept()

    def mousePressEvent(self, event) -> None:  # noqa: N802
        self._forward_mouse(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        self._forward_mouse(event)

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802
        self._forward_mouse(event)


class _TargetHold:
    """目标控件在快照动画期间的「占位隐藏」状态（多会话共享、引用计数）。

    布局管理的目标先用同尺寸 spacer 经 ``QLayout.replaceWidget`` 替换，
    避免隐藏触发布局重排（兄弟控件位移）；还原时换回原控件。
    """

    def __init__(self, target: QWidget):
        self.target = target
        self.was_hidden = target.isHidden()
        self.pixmap = _grab_pixmap(target)
        self.spacer = None
        self.count = 0
        parent = target.parentWidget()
        if parent is not None:
            lay = parent.layout()
            if lay is not None and lay.indexOf(target) >= 0:
                spacer = QWidget(parent)
                # spacer 只是透明占位：全局 QSS 基座规则会把普通 QWidget
                # 刷成不透明底色块，必须压制（否则动画期间出现实心矩形）。
                _force_transparent(spacer)
                spacer.setFixedSize(target.size())
                spacer.setSizePolicy(target.sizePolicy())
                spacer.setAttribute(Qt.WA_TransparentForMouseEvents, True)
                if lay.replaceWidget(target, spacer) is not None:
                    self.spacer = spacer
                    spacer.show()
                else:
                    spacer.deleteLater()
        target.setVisible(False)

    def release(self, end_hidden=None) -> None:
        """引用计数减一；归零时还原目标可见性与布局占位。"""
        self.count -= 1
        if end_hidden is not None:
            self.was_hidden = bool(end_hidden)
        if self.count > 0:
            return
        target = self.target
        try:
            target._uik_snap_hold = None
            if self.spacer is not None:
                parent = target.parentWidget()
                lay = parent.layout() if parent is not None else None
                if lay is not None:
                    lay.replaceWidget(self.spacer, target)
                self.spacer.deleteLater()
                self.spacer = None
            target.setHidden(self.was_hidden)
        except RuntimeError:
            pass


class _SnapSession:
    """一次快照叠加动画会话：占位隐藏目标 + 叠加层生命周期。

    ``finish(end_hidden)`` 正常结束（可指定终态隐藏，如 fade_out）；
    ``abort()`` 中止（stop / 目标销毁），一律还原初始可见性。
    两者幂等。
    """

    def __init__(self, target: QWidget, margin: float = 1,
                 mouse_transparent: bool = True, end_hidden=None):
        self.target = target
        self.end_hidden = end_hidden  # 自然结束时的终态隐藏（None=还原初始）
        hold = getattr(target, "_uik_snap_hold", None)
        if hold is None:
            hold = _TargetHold(target)
            target._uik_snap_hold = hold
        hold.count += 1
        self.hold = hold
        self.overlay = _SnapshotOverlay(target, hold.pixmap, margin,
                                        mouse_transparent)
        self._done = False
        try:
            target.destroyed.connect(self.abort)
        except (RuntimeError, TypeError):
            pass

    def finish(self, end_hidden=None) -> None:
        if self._done:
            return
        self._done = True
        if end_hidden is None:
            end_hidden = self.end_hidden
        self.hold.release(end_hidden)
        self._drop_overlay()

    def abort(self, *_args) -> None:
        if self._done:
            return
        self._done = True
        self.hold.release(None)
        self._drop_overlay()

    def _drop_overlay(self) -> None:
        overlay, self.overlay = self.overlay, None
        if overlay is not None:
            try:
                overlay.hide()
                overlay.deleteLater()
            except RuntimeError:
                pass


class _SnapAnimation(QVariantAnimation):
    """快照叠加层动画句柄（``QVariantAnimation`` 子类，API 与原属性动画一致）。

    - ``valueChanged`` 由预设连接到「进度 → 叠加层属性」映射；
    - 正常结束 / 手动 ``stop()`` / 被动画组停止（C++ 路径经
      ``stateChanged`` 信号捕获）/ 目标销毁，都会自动还原目标
      （可见性与布局占位）并移除叠加层；
    - ``end_hidden`` 指定自然结束时的终态隐藏（``fade_out`` 用）；
    - ``overlays`` 可附带「只清理不还原」的游离叠加层（页面过渡用）；
    - ``on_finalize`` 在自然结束、叠加层移除前调用（切页动作用）。
    """

    def __init__(self, sessions=(), parent=None, end_hidden=None, overlays=()):
        super().__init__(parent)
        if isinstance(sessions, _SnapSession):
            sessions = [sessions]
        self._sessions = list(sessions)
        self._overlays = list(overlays)
        self._end_hidden = end_hidden
        self.on_finalize = None
        self._finished = False
        self.finished.connect(self._on_finished)
        self.stateChanged.connect(self._on_state_changed)
        self.destroyed.connect(self._on_destroyed)

    # -- 结束处理 ----------------------------------------------------------
    def _on_finished(self) -> None:
        self._finished = True
        self._teardown(final=True)

    def _on_state_changed(self, new, _old) -> None:
        if new == QAbstractAnimation.Stopped and not self._finished:
            # 自然结束时 stateChanged 与 finished 同步连续发射；
            # 延迟一拍即可区分手动停止（abort）与自然结束（final）
            QTimer.singleShot(0, self._abort_if_unfinished)

    def _abort_if_unfinished(self) -> None:
        try:
            if not self._finished:
                self._teardown(final=False)
        except RuntimeError:
            pass

    def _on_destroyed(self, *_args) -> None:
        self._teardown(final=False)

    def _teardown(self, final: bool) -> None:
        sessions, self._sessions = self._sessions, []
        overlays, self._overlays = self._overlays, []
        if final and self.on_finalize is not None:
            try:
                self.on_finalize()
            except RuntimeError:
                pass
            self.on_finalize = None
        for session in sessions:
            if final:
                session.finish(self._end_hidden)
            else:
                session.abort()
        for overlay in overlays:
            try:
                overlay.hide()
                overlay.deleteLater()
            except RuntimeError:
                pass

    # -- 公共句柄行为 --------------------------------------------------------
    @property
    def sessions(self):
        """当前存活会话列表（测试 / 调试观测用）。"""
        return list(self._sessions)

    def stop(self) -> None:
        """停止并立即还原目标（布局占位与可见性）。"""
        super().stop()
        self._abort_if_unfinished()

    def restore(self) -> None:
        """``stop()`` 的语义别名，便于「应用 ↔ 还原」式调用。"""
        self.stop()


def _start_snap(target, duration, mapper, *, margin=1, easing=None, loops=1,
                end_hidden=None, mouse_transparent=True):
    """创建快照会话 + 驱动动画并启动，返回 :class:`_SnapAnimation`。

    ``mapper(overlay, t)``：t ∈ [0,1]（已按 easing 缓动，除非 easing 传
    Linear 自行分段），负责设置叠加层属性；每帧调用后自动 ``update()``。
    """
    session = _SnapSession(target, margin, mouse_transparent)
    anim = _SnapAnimation(session, target, end_hidden=end_hidden)
    anim.setDuration(max(1, int(duration)))
    anim.setStartValue(0.0)
    anim.setEndValue(1.0)
    anim.setEasingCurve(easing if easing is not None
                        else QEasingCurve(QEasingCurve.Linear))
    anim.setLoopCount(int(loops))
    overlay = session.overlay

    def _apply(value):
        if session.overlay is None:  # 已还原（中途 stop），忽略尾帧
            return
        mapper(overlay, float(value))
        overlay.update()

    anim.valueChanged.connect(_apply)
    _apply(0.0)
    anim.start()
    return _own(target, anim)


def _interp_keys(keys, t: float) -> float:
    """在 [(progress, value), ...] 关键帧间线性插值。"""
    t = max(0.0, min(1.0, float(t)))
    prev_p, prev_v = keys[0]
    for p, v in keys[1:]:
        if t <= p:
            if p <= prev_p:
                return float(v)
            k = (t - prev_p) / (p - prev_p)
            return prev_v + (v - prev_v) * k
        prev_p, prev_v = p, v
    return float(keys[-1][1])


def _shadow_spec(level: str) -> dict:
    """读取主题阴影令牌（``shadow.sm/md/lg``）。"""
    return ThemeManager.instance().tokens[f"shadow.{level}"]


# ---------------------------------------------------------------------------
# 预设：透明度类
# ---------------------------------------------------------------------------

def fade_in(target, **opts):
    """淡入：控件透明度 0 → 1（快照叠加层实现，布局托管 / 绝对定位均可）。

    用途:
        控件出现时的渐显入场。
    参数:
        target: 目标 QWidget。
        duration: 时长 ms 或 DURATION 键名，默认 ``normal``(200)。
        easing: 缓动曲线或 EASING 键名，默认 ``standard``。
        from_opacity: 起始透明度，默认 0.0。
        remove_on_finish: 兼容保留参数（快照路径无效果可摘，忽略）。
    返回:
        动画句柄（QVariantAnimation 子类，parent 到 target，可 stop()；
        stop 时立即还原目标）。

    实现说明:
        动画期间目标隐藏、由快照叠加层按透明度绘制，结束自动还原；
        不使用 QGraphicsEffect，真机（Windows + QSS + 高 DPI）与
        离屏渲染一致。
    示例::

        anim = fade_in(label)
        anim2 = fade_in(card, duration="slow", easing="entrance")
    """
    from_op = float(opts.get("from_opacity", 0.0))
    to_op = float(opts.get("to_opacity", 1.0))
    return _start_snap(
        target, _dur(opts),
        lambda ov, t: setattr(ov, "opacity", from_op + (to_op - from_op) * t),
        margin=1, easing=_ease(opts), end_hidden=False)


def fade_out(target, **opts):
    """淡出：控件渐隐直至不可见（快照叠加层实现）。

    用途:
        控件消失前的渐隐。
    参数:
        target: 目标 QWidget。
        duration: 时长 ms 或 DURATION 键名，默认 ``normal``(200)。
        easing: 缓动曲线或 EASING 键名，默认 ``standard``。
        hide: 兼容保留参数（新路径下结束总是隐藏，见实现说明）。
    返回:
        动画句柄（可 stop() 还原目标为可见）。

    实现说明:
        旧实现以 QGraphicsOpacityEffect 保留 0 透明度收尾（布局占位
        保留、控件逻辑可见）；快照叠加路径下结束等价为
        ``setVisible(False)``——重新显示请调用 ``setVisible(True)``
        或播放 :func:`fade_in`。中途 ``stop()`` 会还原为可见。
    示例::

        anim = fade_out(tooltip)
    """
    return _start_snap(
        target, _dur(opts),
        lambda ov, t: setattr(ov, "opacity", 1.0 - t),
        margin=1, easing=_ease(opts), end_hidden=True)


# ---------------------------------------------------------------------------
# 预设：位移动画
# ---------------------------------------------------------------------------

_DIRECTIONS = ("left", "right", "up", "down")


def _direction_offset(direction: str, dx: float, dy: float) -> QPoint:
    """按方向返回位移向量（direction 表示『从哪一侧进入』）。"""
    return {
        "left": QPoint(-round(dx), 0),
        "right": QPoint(round(dx), 0),
        "up": QPoint(0, -round(dy)),
        "down": QPoint(0, round(dy)),
    }[direction]


def slide_in(target, **opts):
    """滑入：控件从某侧偏移位置滑到当前位置（可叠加淡入）。

    用途:
        面板 / 卡片 / 提示条的入场位移。
    参数:
        target: 目标 QWidget（布局托管 / 绝对定位均可，见实现说明）。
        direction: ``left``/``right``/``up``/``down``，从哪侧滑入，默认 ``left``。
        distance: 位移距离 px，默认 控件宽/高（取方向对应边），至少 32。
        fade: 是否同步淡入（默认 True）。
        duration / easing: 默认 ``normal`` / ``entrance``。
    返回:
        动画句柄（可 stop() 还原）。

    实现说明:
        快照叠加层平移 + 淡入实现；不再使用 ``pos`` 属性动画，
        因此布局管理的目标不会被布局刷新重置（目标原位隐藏，
        叠加层滑入，结束还原，几何不变）。
    示例::

        slide_in(panel, direction="right", distance=120)
    """
    direction = opts.get("direction", "left")
    if direction not in _DIRECTIONS:
        raise ValueError(f"未知方向: {direction!r}，应为 {_DIRECTIONS} 之一")
    distance = opts.get("distance")
    if distance is None:
        distance = max(target.width() if direction in ("left", "right") else target.height(), 32)
    distance = float(distance)
    fade = bool(opts.get("fade", True))
    e_ent = _ease(opts, "entrance")
    e_std = _ease(opts)
    off = _direction_offset(direction, distance, distance)

    def mapper(ov, t):
        k = 1.0 - e_ent.valueForProgress(t)
        ov.dx = off.x() * k
        ov.dy = off.y() * k
        ov.opacity = e_std.valueForProgress(t) if fade else 1.0

    return _start_snap(target, _dur(opts), mapper,
                       margin=abs(distance) + 2, end_hidden=False)


# ---------------------------------------------------------------------------
# 预设：缩放 / 弹性（_TransformEffect 方案，见模块 docstring）
# ---------------------------------------------------------------------------

def zoom_in(target, **opts):
    """缩放进入：控件从较小尺寸平滑放大到原尺寸（可叠加淡入）。

    用途:
        弹层、对话框、图片的放大入场。
    参数:
        target: 目标 QWidget（布局托管 / 绝对定位均可）。
        from_scale: 起始缩放比例，默认 0.6。
        fade: 是否同步淡入（默认 True）。
        duration / easing: 默认 ``normal`` / ``entrance``。
        remove_on_finish: 兼容保留参数（快照路径无效果可摘，忽略）。
    返回:
        动画句柄（可 stop() 还原）。

    实现说明:
        快照叠加层中心缩放 + 淡入实现（缩放围绕控件中心），
        不使用 ``QGraphicsEffect``；弹性缓动（OutBack）的过冲段
        由外扩的叠加层几何完整绘制，不再被裁剪。
    示例::

        zoom_in(dialog_content, from_scale=0.85)
    """
    from_scale = float(opts.get("from_scale", 0.6))
    fade = bool(opts.get("fade", True))
    e_ent = _ease(opts, "entrance")
    e_std = _ease(opts)
    margin = int(math.ceil(max(target.width(), target.height()) * 0.25)) + 2

    def mapper(ov, t):
        ov.scale = from_scale + (1.0 - from_scale) * e_ent.valueForProgress(t)
        ov.opacity = e_std.valueForProgress(t) if fade else 1.0

    return _start_snap(target, _dur(opts), mapper, margin=margin,
                       end_hidden=False)


def spring_pop(target, **opts):
    """弹性弹出：控件从较小尺寸带回弹地弹出（OutBack 弹簧缓动 + 淡入）。

    用途:
        徽标、气泡、轻提示的活泼入场。
    参数:
        target: 目标 QWidget。
        from_scale: 起始缩放比例，默认 0.55。
        duration / easing: 默认 ``slow``(320) / ``spring``(OutBack)。
        fade: 是否同步淡入（默认 True）。
        remove_on_finish: 结束后摘除变换效果（默认 True）。
    返回:
        QParallelAnimationGroup。

    实现说明:
        与 :func:`zoom_in` 相同，基于快照叠加层；OutBack 缓动的
        过冲段（scale > 1）由外扩叠加层完整绘制，不会被裁剪。
    示例::

        spring_pop(badge)
    """
    opts.setdefault("duration", "slow")
    opts.setdefault("easing", "spring")
    opts.setdefault("from_scale", 0.55)
    return zoom_in(target, **opts)


def badge_pop(target, **opts):
    """角标弹入：徽标类小控件从 0 弹性放大出现。

    用途:
        消息角标、小红点、计数气泡的出现动画。
    参数:
        target: 目标 QWidget（通常为徽标控件）。
        duration / easing: 默认 ``slow``(320) / ``spring``(OutBack)。
    返回:
        QParallelAnimationGroup。
    示例::

        badge_pop(unread_badge)
    """
    opts.setdefault("from_scale", 0.0)
    return spring_pop(target, **opts)


# ---------------------------------------------------------------------------
# 预设：依次入场
# ---------------------------------------------------------------------------

def stagger_in(target, **opts):
    """交错入场：子控件按间隔依次「淡入 + 上移」。

    用途:
        列表项、卡片网格、表单行的流水式入场。
    参数:
        target: 容器 QWidget。
        children: 子控件列表；缺省取 target 的直接可见子 QWidget。
        interval: 相邻子控件启动间隔 ms，默认 60。
        distance: 起始下偏移 px，默认 24。
        duration / easing: 每个子动画时长，默认 ``normal`` / ``entrance``。
    返回:
        QParallelAnimationGroup（内部为 延迟 + 并行 的顺序组）。

    实现说明:
        每个子控件一个快照会话（隐藏 + 叠加层），由同一驱动动画按
        错峰进度更新「上移 + 淡入」；子控件几何全程不变，
        绝对定位与布局托管容器均可。
    示例::

        stagger_in(card_container, interval=80)
    """
    children = opts.get("children")
    if children is None:
        children = [c for c in target.children() if isinstance(c, QWidget) and not c.isHidden()]
    interval = int(opts.get("interval", 60))
    distance = float(opts.get("distance", 24))
    duration = _dur(opts)
    e_ent = _ease(opts, "entrance")
    e_std = _ease(opts)

    sessions = [_SnapSession(child, margin=distance + 2, end_hidden=False)
                for child in children]
    total = duration + interval * max(0, len(children) - 1)

    anim = _SnapAnimation(sessions, target)
    anim.setDuration(max(1, total))
    anim.setStartValue(0.0)
    anim.setEndValue(1.0)
    anim.setEasingCurve(QEasingCurve(QEasingCurve.Linear))

    def _apply(value):
        now = float(value) * total
        for i, session in enumerate(sessions):
            ov = session.overlay
            if ov is None:
                continue
            local = max(0.0, min(1.0, (now - i * interval) / duration))
            ov.dy = distance * (1.0 - e_ent.valueForProgress(local))
            ov.opacity = e_std.valueForProgress(local)
            ov.update()

    anim.valueChanged.connect(_apply)
    _apply(0.0)
    anim.start()
    return _own(target, anim)


# ---------------------------------------------------------------------------
# 预设：模糊与遮罩
# ---------------------------------------------------------------------------

def blur_in(target, **opts):
    """模糊进入：控件从模糊半径 radius 平滑清晰到 0（快照叠加层实现）。

    用途:
        背景图、卡片、弹层的聚焦式入场。
    参数:
        target: 目标 QWidget。
        radius: 起始模糊半径 px，默认 16。
        duration / easing: 默认 ``slow``(320) / ``standard``。
        remove_on_finish: 兼容保留参数（快照路径无效果可摘，忽略）。
    返回:
        动画句柄（可 stop() 还原）。

    实现说明:
        对快照位图按 2 的幂档位预生成「缩小 → 平滑放大」级联模糊
        位图，动画帧间在两档间交叉淡化，近似连续高斯模糊；
        不使用 QGraphicsBlurEffect，真机与离屏渲染一致。
    示例::

        blur_in(hero_image, radius=24)
    """
    radius = float(opts.get("radius", 16))
    easing = _ease(opts)

    def mapper(ov, t):
        ov.blur = radius * (1.0 - easing.valueForProgress(t))

    return _start_snap(target, _dur(opts, "slow"), mapper,
                       margin=int(math.ceil(radius)) + 2, end_hidden=False)


def mask_reveal(target, **opts):
    """遮罩揭示：把控件从一侧 / 中心逐步裁剪揭示（快照叠加层实现）。

    用途:
        图片、横幅、卡片的揭示式入场。
    参数:
        target: 目标 QWidget。
        direction: ``right``（从左向右揭示，默认）/ ``left`` / ``down`` /
            ``up`` / ``circle``（中心圆形扩散）。
        duration / easing: 默认 ``slow``(320) / ``standard``。
    返回:
        动画句柄（可 stop() 还原；目标全程不设置 mask）。

    实现说明:
        旧实现逐帧 ``setMask()`` 更新裁剪区域——在部分平台对 QSS
        控件失效；现改为快照叠加层 paintEvent 内按进度设置裁剪
        （矩形 / 椭圆），边缘为硬切，平台无关。
    示例::

        mask_reveal(banner, direction="circle", duration="slower")
    """
    direction = opts.get("direction", "right")
    if direction not in _DIRECTIONS + ("circle",):
        raise ValueError(f"未知方向: {direction!r}，应为 {_DIRECTIONS + ('circle',)} 之一")
    easing = _ease(opts)

    def mapper(ov, t):
        ov.clip_mode = direction
        ov.clip_progress = easing.valueForProgress(t)

    return _start_snap(target, _dur(opts, "slow"), mapper, margin=1,
                       end_hidden=False)


# ---------------------------------------------------------------------------
# 预设：交互反馈（事件过滤器类）
# ---------------------------------------------------------------------------

class _HoverLiftFilter(QObject):
    """hover_lift 的事件过滤器：Enter 抬升（快照叠加层 + 投影），Leave 还原。

    抬升期间目标隐藏、叠加层接管 hover 与鼠标事件（点击转发给目标）；
    不依赖 ``pos`` 动画与 ``QGraphicsDropShadowEffect``。
    """

    def __init__(self, target: QWidget, dy: int, duration: int, easing,
                 shadow_from: str, shadow_to: str, use_shadow: bool):
        super().__init__(target)
        self._target = target
        self._dy = dy
        self._duration = duration
        self._easing = easing
        self._use_shadow = use_shadow
        self._shadow_from = _shadow_spec(shadow_from) if use_shadow else None
        self._shadow_to = _shadow_spec(shadow_to) if use_shadow else None
        self._session = None
        self._anim = None
        self._k = 0.0  # 当前抬升进度 0~1

    # -- 公开 --------------------------------------------------------------
    @property
    def overlay(self):
        """当前抬升叠加层（未抬升时为 None；测试观测用）。"""
        return self._session.overlay if self._session is not None else None

    def uninstall(self) -> None:
        """卸下过滤器并立即还原目标（幂等）。"""
        try:
            self._target.removeEventFilter(self)
        except RuntimeError:
            pass
        if self._anim is not None:
            self._anim.stop()
            self._anim = None
        if self._session is not None:
            self._session.abort()
            self._session = None
        self._k = 0.0

    # ParamCard 等统一按 stop() 清理句柄
    stop = uninstall

    # -- 内部 --------------------------------------------------------------
    def _apply(self, k: float) -> None:
        self._k = k
        ov = self.overlay
        if ov is None:
            return
        ov.dy = -self._dy * k
        if self._use_shadow:
            sf, st = self._shadow_from, self._shadow_to
            ov.shadow_blur = sf["blur"] + (st["blur"] - sf["blur"]) * k
            oy = sf["offset"][1] + (st["offset"][1] - sf["offset"][1]) * k
            ov.shadow_offset = (0.0, oy)
            r, g, b, a = st["color"]
            ov.shadow_color = QColor(r, g, b)
            ov.shadow_opacity = (a / 255.0) * k
        ov.update()

    def _lift(self) -> None:
        if self._session is not None:
            return
        margin = self._dy + 6
        if self._use_shadow:
            margin += int(self._shadow_to["blur"] + abs(self._shadow_to["offset"][1]))
        session = _SnapSession(self._target, margin=margin,
                               mouse_transparent=False)
        ov = session.overlay
        ov.forward_to = self._target
        ov.on_leave = self._settle
        self._session = session
        self._k = 0.0

        anim = _SnapAnimation((), self._target)  # 不接管会话（落回动画负责还原）
        anim.setDuration(self._duration)
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)
        anim.setEasingCurve(self._easing)
        anim.valueChanged.connect(lambda v: self._apply(float(v)))
        anim.start()
        self._anim = anim

    def _settle(self, *_args) -> None:
        session, self._session = self._session, None
        if session is None:
            return
        if self._anim is not None:
            self._anim.stop()  # 抬升动画不接管会话，仅停止插值
            self._anim = None
        start_k = self._k
        if start_k <= 0.0:
            session.abort()
            return
        # 落回动画接管会话：自然结束 → 还原目标 + 移除叠加层
        self._session = session  # _apply 期间 overlay 可取
        anim = _SnapAnimation(session, self._target)
        anim.setDuration(max(40, self._duration))
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)
        anim.setEasingCurve(self._easing)
        anim.valueChanged.connect(lambda v: self._apply(start_k * (1.0 - float(v))))
        anim.finished.connect(self._clear)
        anim.start()
        self._anim = anim

    def _clear(self, *_args) -> None:
        self._session = None
        self._anim = None
        self._k = 0.0

    def eventFilter(self, obj, event) -> bool:
        if obj is self._target and event.type() == QEvent.Enter:
            self._lift()
        return False


def hover_lift(target, **opts):
    """悬停上浮：鼠标进入时控件上移 dy px 并增强阴影，离开时还原。

    用途:
        卡片、按钮的悬停立体感反馈。
    参数:
        target: 目标 QWidget（布局托管 / 绝对定位均可）。
        dy: 上移距离 px，默认 4。
        duration / easing: 默认 ``fast``(120) / ``standard``。
        shadow_from / shadow_to: 阴影级别插值，默认 ``sm`` → ``md``
            （取主题 ``shadow.*`` 令牌，叠加层自绘投影）。
        use_shadow: 是否启用阴影（默认 True；关闭后仅位移）。
    返回:
        事件过滤器对象（已 parent 到 target）；卸载调用
        ``filter.uninstall()``（别名 ``stop()``），会自动还原目标。

    实现说明:
        抬升 / 阴影全部由快照叠加层绘制（剪影模糊投影），不使用
        ``pos`` 动画与 ``QGraphicsDropShadowEffect``；抬升期间
        叠加层接管 hover（离开即落回）并把鼠标点击转发给目标控件，
        布局管理的目标也不会被布局刷新重置。静止态不再常驻 sm 阴影
        （旧实现安装即挂投影效果），需要常驻阴影请另行调用
        ``theme.apply_shadow``。
    示例::

        hover_lift(card)
        hover_lift(button, dy=2, shadow_to="lg")
    """
    dy = int(opts.get("dy", 4))
    duration = _dur(opts, "fast")
    easing = _ease(opts)
    shadow_from = opts.get("shadow_from", "sm")
    shadow_to = opts.get("shadow_to", "md")
    use_shadow = bool(opts.get("use_shadow", True))
    filt = _HoverLiftFilter(target, dy, duration, easing,
                            shadow_from, shadow_to, use_shadow)
    target.installEventFilter(filt)
    target._uik_hover_filter = filt
    return filt


def button_morph_loading(button, **opts):
    """按钮变形加载：宽度收缩为正方形 → 清空文字并禁用 → 透明度呼吸循环。

    用途:
        提交按钮点击后进入加载态（宽度 morph + 呼吸提示）。
    参数:
        button: 目标 QPushButton（或任意 QAbstractButton）。
        text: 变形后显示的文字，默认 ``""``（空，纯方块呼吸）。
        duration / easing: 变形时长，默认 ``normal`` / ``standard``。
        pulse_duration: 呼吸周期 ms，默认 900。
    返回:
        QSequentialAnimationGroup；额外挂载 ``restore()`` 方法，
        调用后停止动画并还原文字 / 宽度约束 / 可用状态。

    实现说明:
        宽度收缩通过 QPropertyAnimation 驱动 QWidget 的
        ``minimumWidth`` / ``maximumWidth`` Q_PROPERTY 实现，
        在布局中也能正确收缩（布局会按新约束重排）；收缩完成后的
        呼吸阶段改为快照叠加层透明度呼吸（按钮隐藏、快照脉动），
        不使用 QGraphicsOpacityEffect——真机上加载态不再整片消失。
    示例::

        handle = button_morph_loading(submit_btn)
        ...  # 请求完成后
        handle.restore()
    """
    orig = {
        "text": button.text(),
        "min_w": button.minimumWidth(),
        "max_w": button.maximumWidth(),
        "enabled": button.isEnabled(),
    }
    end_w = int(opts.get("width", button.height()))
    duration = _dur(opts)
    easing = _ease(opts)
    text_after = opts.get("text", "")

    morph = QParallelAnimationGroup(button)
    for prop in (b"minimumWidth", b"maximumWidth"):
        a = QPropertyAnimation(button, prop)
        a.setDuration(duration)
        a.setStartValue(button.width())
        a.setEndValue(end_w)
        a.setEasingCurve(easing)
        morph.addAnimation(a)
    button.setEnabled(False)
    morph.finished.connect(lambda: button.setText(text_after))

    # 呼吸阶段：进入 Running 时才创建快照会话（按钮已收缩到位）
    pulse_anim = _SnapAnimation((), button)
    pulse_anim.setDuration(int(opts.get("pulse_duration", 900)))
    pulse_anim.setStartValue(0.0)
    pulse_anim.setEndValue(1.0)
    pulse_anim.setEasingCurve(QEasingCurve(QEasingCurve.Linear))
    pulse_anim.setLoopCount(-1)

    def _begin_pulse(new, _old):
        if new != QAbstractAnimation.Running or pulse_anim._sessions:
            return
        session = _SnapSession(button, margin=1)
        pulse_anim._sessions.append(session)
        overlay = session.overlay

        def _breathe(value):
            if session.overlay is None:
                return
            overlay.opacity = 1.0 - 0.45 * math.sin(math.pi * float(value))
            overlay.update()

        pulse_anim.valueChanged.connect(_breathe)
        _breathe(0.0)

    pulse_anim.stateChanged.connect(_begin_pulse)

    master = QSequentialAnimationGroup(button)
    master.addAnimation(morph)
    master.addAnimation(pulse_anim)

    def restore():
        """停止动画并还原按钮初始状态。"""
        master.stop()
        button.setMinimumWidth(orig["min_w"])
        button.setMaximumWidth(orig["max_w"])
        button.setText(orig["text"])
        button.setEnabled(orig["enabled"])

    master.restore = restore
    master.start()
    return _own(button, master)


class _RippleFilter(QObject):
    """ripple 的事件过滤器：捕获按下位置并驱动扩散圆动画。"""

    def __init__(self, button: QWidget, overlay: _Overlay, duration: int,
                 easing, max_opacity: float):
        super().__init__(button)
        self._button = button
        self.overlay = overlay
        self._duration = duration
        self._easing = easing
        self._max_opacity = max_opacity
        self._anim = None

    def eventFilter(self, obj, event) -> bool:
        if obj is self._button:
            etype = event.type()
            if etype == QEvent.Resize:
                self.overlay.setGeometry(self._button.rect())
            elif etype == QEvent.MouseButtonPress:
                self.start(event.position())
        return False

    def start(self, pos: QPointF):
        """以 pos 为圆心启动一次涟漪动画（可重复触发）。"""
        if self._anim is not None:
            self._anim.stop()
        rect = self._button.rect()
        corners = (rect.topLeft(), rect.topRight(), rect.bottomLeft(), rect.bottomRight())
        max_r = max(math.hypot(pos.x() - c.x(), pos.y() - c.y()) for c in corners)
        anim = QVariantAnimation(self.overlay)
        anim.setDuration(self._duration)
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)
        anim.setEasingCurve(self._easing)
        anim.valueChanged.connect(
            lambda p: self.overlay.set_ripple(pos, max_r * float(p),
                                              self._max_opacity * (1.0 - float(p)))
        )
        anim.finished.connect(self.overlay.clear)
        anim.start()
        self._anim = anim
        return anim


def ripple(target, **opts):
    """按钮涟漪：为 QPushButton 安装事件过滤器 + 自绘叠加层，按下时扩散圆。

    用途:
        Material 风格的点击波纹反馈。
    参数:
        target: 目标按钮（QPushButton 或任意 QWidget）。
        color: 涟漪颜色；缺省时 primary/danger 变体按钮取白色，
            其余取主题 ``color.primary``。
        max_opacity: 涟漪起始不透明度，默认 0.35。
        duration / easing: 默认 ``slow``(320) / ``standard``。
        corner: 圆角裁剪半径，默认取 ``radius.md``。
    返回:
        事件过滤器对象（``filter.overlay`` 为叠加层；
        ``filter.start(pos)`` 可手动触发一次涟漪）。

    实现说明:
        叠加层为按钮子控件，``WA_TransparentForMouseEvents`` 穿透鼠标，
        paintEvent 中按圆角路径裁剪并绘制扩散圆；重复调用 ``ripple()``
        会返回已安装的过滤器，避免重复叠加。
    示例::

        ripple(ok_button)
        ripple(primary_btn, max_opacity=0.5)
    """
    existing = getattr(target, "_uik_ripple", None)
    if existing is not None:
        return existing
    color = opts.get("color")
    if color is None:
        variant = target.property("variant")
        color = "#FFFFFF" if variant in ("primary", "danger", "success") else T("color.primary")
    overlay = _Overlay(target, QColor(color), float(opts.get("corner", T("radius.md"))))
    filt = _RippleFilter(target, overlay, _dur(opts, "slow"), _ease(opts),
                         float(opts.get("max_opacity", 0.35)))
    target.installEventFilter(filt)
    target._uik_ripple = filt
    return filt


def switch_toggle(switch, **opts):
    """开关切换：按压回弹手感 + 切换选中态（适配任意 checkable 按钮）。

    用途:
        开关 / 复选框点击时的机械式反馈（缩下 → 换态 → 弹回）。
    参数:
        switch: 目标 QAbstractButton（checkable）。
        checked: 目标选中态；缺省取反当前状态。
        duration / easing: 总时长约 duration，默认 ``fast``(120)；
            回弹段固定用 ``spring``(OutBack)。
    返回:
        QSequentialAnimationGroup。

    实现说明:
        缩放由内部 ``_TransformEffect`` 完成；若目标控件自身已带
        切换动画（如组件库 Switch），可仅将其用作额外的按压反馈。
    示例::

        switch_toggle(wifi_switch)
        switch_toggle(checkbox, checked=True)
    """
    target_checked = bool(opts.get("checked", not switch.isChecked()))
    eff = _transform_effect(target=switch)
    eff._set_scale(1.0)
    half = max(_dur(opts, "fast") // 2, 40)

    down = QPropertyAnimation(eff, b"scale")
    down.setDuration(half)
    down.setStartValue(1.0)
    down.setEndValue(0.85)
    down.setEasingCurve(QEasingCurve.InQuad)
    down.finished.connect(lambda: switch.setChecked(target_checked))

    up = QPropertyAnimation(eff, b"scale")
    up.setDuration(half + 60)
    up.setStartValue(0.85)
    up.setEndValue(1.0)
    up.setEasingCurve(EASING["spring"])

    group = QSequentialAnimationGroup(switch)
    group.addAnimation(down)
    group.addAnimation(up)
    if opts.get("remove_on_finish", True):
        group.finished.connect(lambda: _maybe_remove_effect(switch, eff))
    group.start()
    return _own(switch, group)


# ---------------------------------------------------------------------------
# 预设：强调 / 循环动效
# ---------------------------------------------------------------------------

def pulse(target, **opts):
    """脉冲：缩放 1 → peak → 1 的心跳式强调（默认播放 1 次）。

    用途:
        新消息提醒、重要按钮的注意力引导。
    参数:
        target: 目标 QWidget（布局托管 / 绝对定位均可）。
        peak: 峰值缩放，默认 1.06。
        loops: 循环次数，-1 为无限，默认 1。
        duration / easing: 默认 ``slow``(320) / ``standard``。
    返回:
        动画句柄（快照叠加层缩放；可 stop() 还原）。
    示例::

        pulse(notification_icon, loops=3)
    """
    peak = float(opts.get("peak", 1.06))
    easing = _ease(opts)
    margin = int(math.ceil(max(target.width(), target.height())
                           * max(0.0, peak - 1.0) / 2.0)) + 2

    def mapper(ov, t):
        if t < 0.5:
            ov.scale = 1.0 + (peak - 1.0) * easing.valueForProgress(t * 2.0)
        else:
            ov.scale = peak + (1.0 - peak) * easing.valueForProgress((t - 0.5) * 2.0)

    return _start_snap(target, _dur(opts, "slow"), mapper, margin=margin,
                       loops=int(opts.get("loops", 1)))


def bounce(target, **opts):
    """弹跳：上移后带落地回弹（OutBounce）返回原位。

    用途:
        操作成功后的轻快感反馈、空状态插图的活泼入场。
    参数:
        target: 目标 QWidget（布局托管 / 绝对定位均可）。
        height: 弹跳高度 px，默认 12。
        loops: 循环次数，-1 为无限，默认 1。
        duration: 默认 ``slower``(480)。
    返回:
        动画句柄（快照叠加层位移；可 stop() 还原）。

    实现说明:
        不再使用 ``pos`` 属性动画——目标原位隐藏，快照叠加层
        上移（OutQuad）后回弹落下（OutBounce），结束还原，
        布局管理的目标不会被布局刷新重置。
    示例::

        bounce(success_icon)
    """
    height = float(opts.get("height", 12))
    up_e = QEasingCurve(QEasingCurve.OutQuad)
    down_e = QEasingCurve(QEasingCurve.OutBounce)

    def mapper(ov, t):
        if t < 0.4:
            ov.dy = -height * up_e.valueForProgress(t / 0.4)
        else:
            ov.dy = -height * (1.0 - down_e.valueForProgress((t - 0.4) / 0.6))

    return _start_snap(target, _dur(opts, "slower"), mapper,
                       margin=int(math.ceil(height)) + 2,
                       loops=int(opts.get("loops", 1)))


def swing(target, **opts):
    """摇摆：绕中心左右旋转衰减（±angle 收敛到 0）。

    用途:
        铃铛 / 提醒图标的晃动提醒。
    参数:
        target: 目标 QWidget（布局托管 / 绝对定位均可）。
        angle: 最大摆角（度），默认 8。
        loops: 循环次数，-1 为无限，默认 1。
        duration: 默认 ``slower``(480)。
    返回:
        动画句柄（快照叠加层旋转；可 stop() 还原）。
    示例::

        swing(bell_icon, angle=12)
    """
    a = float(opts.get("angle", 8))
    keys = [(0.0, 0.0), (0.2, a), (0.5, -a * 0.6), (0.8, a * 0.3), (1.0, 0.0)]
    w, h = target.width(), target.height()
    margin = int(math.ceil((math.hypot(w, h) - min(w, h)) / 2.0)) + 2

    def mapper(ov, t):
        ov.angle = _interp_keys(keys, t)

    return _start_snap(target, _dur(opts, "slower"), mapper, margin=margin,
                       loops=int(opts.get("loops", 1)))


def shake(target, **opts):
    """抖动：水平方向衰减振荡（表单校验失败等错误反馈）。

    用途:
        输入错误、操作被拒时的「摇头」提示。
    参数:
        target: 目标 QWidget（布局托管 / 绝对定位均可）。
        distance: 初始振幅 px，默认 6。
        loops: 循环次数，默认 1。
        duration: 默认 ``slow``(320)。
    返回:
        动画句柄（快照叠加层位移；可 stop() 还原）。
    示例::

        shake(password_edit)
    """
    d = float(opts.get("distance", 6))
    keys = [(0.0, 0.0), (0.2, -d), (0.4, d * 0.75), (0.6, -d * 0.5),
            (0.8, d * 0.25), (1.0, 0.0)]

    def mapper(ov, t):
        ov.dx = _interp_keys(keys, t)

    return _start_snap(target, _dur(opts, "slow"), mapper,
                       margin=int(math.ceil(d)) + 2,
                       loops=int(opts.get("loops", 1)))


def flash_highlight(target, **opts):
    """高亮闪烁：叠加层整面填充主题色并迅速淡出（可多次闪烁）。

    用途:
        表格行更新、表单保存成功后的定位提示。
    参数:
        target: 目标 QWidget。
        color: 高亮色，默认主题 ``color.warning``。
        max_opacity: 起始不透明度，默认 0.45。
        times: 闪烁次数，默认 1。
        duration / easing: 单次时长，默认 ``slower``(480) / ``standard``。
        corner: 圆角裁剪半径，默认取 ``radius.md``。
    返回:
        QVariantAnimation（结束后叠加层自动 deleteLater）。
    示例::

        flash_highlight(updated_row, times=2)
    """
    color = QColor(opts.get("color", T("color.warning")))
    overlay = _Overlay(target, color, float(opts.get("corner", T("radius.md"))))
    max_opacity = float(opts.get("max_opacity", 0.45))

    # 动画 parent 到 target 而非 overlay：finished 时 overlay 先 deleteLater，
    # 若动画挂在 overlay 下会连同返回句柄一起被销毁。
    anim = QVariantAnimation(target)
    anim.setDuration(_dur(opts, "slower"))
    anim.setStartValue(1.0)
    anim.setEndValue(0.0)
    anim.setEasingCurve(_ease(opts))
    anim.setLoopCount(int(opts.get("times", 1)))
    anim.valueChanged.connect(lambda p: overlay.set_fill(max_opacity * float(p)))
    anim.finished.connect(overlay.deleteLater)
    anim.start()
    return _own(target, anim)


def float_loop(target, **opts):
    """漂浮循环：控件在原位上下缓慢往复（默认无限循环）。

    用途:
        空状态插画、引导提示箭头的呼吸式漂浮。
    参数:
        target: 目标 QWidget（布局托管 / 绝对定位均可）。
        dy: 漂浮幅度 px，默认 6。
        duration: 单次往复周期 ms，默认 1600。
        loops: 循环次数，默认 -1（无限）。
    返回:
        动画句柄（快照叠加层正弦位移；``stop()`` 停止并还原）。

    实现说明:
        不再使用 ``pos`` 属性动画——目标原位隐藏，快照叠加层
        按正弦曲线上下往复；重放 / 停止均以原几何为基准，
        不存在旧实现以中途位置为新基准逐次漂移的问题。
    示例::

        anim = float_loop(empty_illustration)   # anim.stop() 停止
    """
    dy = float(opts.get("dy", 6))

    def mapper(ov, t):
        ov.dy = -dy * math.sin(math.pi * t)

    return _start_snap(target, int(opts.get("duration", 1600)), mapper,
                       margin=int(math.ceil(dy)) + 2,
                       loops=int(opts.get("loops", -1)))


def pulse_glow(target, **opts):
    """辉光呼吸：剪影光晕模糊半径在 min_blur ↔ max_blur 间呼吸。

    用途:
        主行动按钮、重点卡片的持续吸引注意。
    参数:
        target: 目标 QWidget（布局托管 / 绝对定位均可）。
        color: 辉光颜色，默认主题 ``color.primary``。
        min_blur / max_blur: 模糊半径范围 px，默认 8 ↔ 28。
        duration: 呼吸周期 ms，默认 1600。
        loops: 循环次数，默认 -1（无限）。
    返回:
        动画句柄（快照叠加层辉光；``stop()`` 停止并还原）。

    实现说明:
        旧实现挂 QGraphicsDropShadowEffect（真机可能整片不绘制）；
        现改为叠加层在内容快照之下绘制「保留 alpha 的单色剪影」
        预模糊位图并呼吸其半径，平台无关。
    示例::

        glow = pulse_glow(cta_button)   # glow.stop() 停止
    """
    color = QColor(opts.get("color", T("color.primary")))
    mn = float(opts.get("min_blur", 8))
    mx = float(opts.get("max_blur", 28))

    def mapper(ov, t):
        ov.glow_color = color
        ov.glow_radius = mn + (mx - mn) * (0.5 - 0.5 * math.cos(2.0 * math.pi * t))

    return _start_snap(target, int(opts.get("duration", 1600)), mapper,
                       margin=int(math.ceil(mx)) + 4,
                       loops=int(opts.get("loops", -1)))


def breathing(target, **opts):
    """呼吸：透明度在 1 ↔ min_opacity 间循环（正弦曲线）。

    用途:
        加载占位、录制中指示的柔和闪烁。
    参数:
        target: 目标 QWidget（布局托管 / 绝对定位均可）。
        min_opacity: 最低透明度，默认 0.5。
        duration: 呼吸周期 ms，默认 1600。
        loops: 循环次数，默认 -1（无限）。
    返回:
        动画句柄（快照叠加层透明度；``stop()`` 停止并还原）。
    示例::

        anim = breathing(recording_dot)
    """
    mn = float(opts.get("min_opacity", 0.5))

    def mapper(ov, t):
        ov.opacity = 1.0 - (1.0 - mn) * (0.5 - 0.5 * math.cos(2.0 * math.pi * t))

    return _start_snap(target, int(opts.get("duration", 1600)), mapper,
                       margin=1, loops=int(opts.get("loops", -1)))


# ---------------------------------------------------------------------------
# 预设：渐变流动
# ---------------------------------------------------------------------------

def gradient_flow(target, **opts):
    """背景渐变流动：QSS 线性渐变两端颜色沿色带循环流动。

    用途:
        会员卡片、营销横幅的流光背景。
    参数:
        target: 目标 QWidget（自动置 ``WA_StyledBackground``）。
        colors: 渐变色带（至少 2 色），默认 [primary, success]。
        duration: 流动一周时长 ms，默认 2400。
        loops: 循环次数，默认 -1（无限）。
        direction: ``horizontal``(默认) / ``vertical``。
        radius: 背景圆角 px，默认取 ``radius.md``。
    返回:
        QVariantAnimation（parent 到 target）。

    实现说明:
        QVariantAnimation 驱动相位，每帧生成
        ``qlineargradient`` QSS 赋给 target；动画结束（stop 后不会自动）
        恢复原 styleSheet 仅在 ``finished`` 时触发——无限循环时
        请自行 ``anim.stop()`` 后恢复，文档示例见下。
    示例::

        anim = gradient_flow(banner)
        ...
        anim.stop()
    """
    colors = [QColor(c) for c in opts.get("colors", [T("color.primary"), T("color.success")])]
    if len(colors) < 2:
        colors = colors * 2
    horizontal = opts.get("direction", "horizontal") == "horizontal"
    radius = int(opts.get("radius", T("radius.md")))
    x2, y2 = (1, 0) if horizontal else (0, 1)
    target.setAttribute(Qt.WA_StyledBackground, True)
    orig_sheet = target.styleSheet()

    anim = QVariantAnimation(target)
    anim.setDuration(int(opts.get("duration", 2400)))
    anim.setStartValue(0.0)
    anim.setEndValue(1.0)
    anim.setEasingCurve(QEasingCurve.Linear)
    anim.setLoopCount(int(opts.get("loops", -1)))

    def apply(p):
        ca = _lerp_gradient(colors, float(p))
        cb = _lerp_gradient(colors, float(p) + 0.5)
        target.setStyleSheet(
            f"background: qlineargradient(x1:0, y1:0, x2:{x2}, y2:{y2}, "
            f"stop:0 {ca.name()}, stop:1 {cb.name()}); "
            f"border-radius: {radius}px;"
        )

    anim.valueChanged.connect(apply)
    anim.finished.connect(lambda: target.setStyleSheet(orig_sheet))
    apply(0.0)
    anim.start()
    return _own(target, anim)


def gradient_text_flow(label, **opts):
    """文字渐变流动：逐字符着色，色相随相位沿文本方向流动。

    用途:
        标题 / 宣传语的炫彩文字效果。
    参数:
        label: 目标 QLabel。
        colors: 色带（至少 2 色），默认 [primary, success, warning]。
        text: 参与动画的文本，默认取 label 当前 text()。
        duration: 流动一周时长 ms，默认 2000。
        loops: 循环次数，默认 -1（无限）。
    返回:
        QVariantAnimation；``finished`` 时自动还原原文本。

    实现说明:
        QSS 无法表达文字渐变，本实现每帧按字符位置插值颜色并
        重建富文本（``<span style='color:...'>``）；适合短文本（标题级），
        长段落请降低刷新频率或改用自绘方案。
    示例::

        anim = gradient_text_flow(title_label)
    """
    colors = [QColor(c) for c in opts.get(
        "colors", [T("color.primary"), T("color.success"), T("color.warning")])]
    if len(colors) < 2:
        colors = colors * 2
    orig_text = label.text()
    text = opts.get("text", orig_text)

    anim = QVariantAnimation(label)
    anim.setDuration(int(opts.get("duration", 2000)))
    anim.setStartValue(0.0)
    anim.setEndValue(1.0)
    anim.setEasingCurve(QEasingCurve.Linear)
    anim.setLoopCount(int(opts.get("loops", -1)))

    def apply(p):
        n = max(len(text), 1)
        parts = []
        for i, ch in enumerate(text):
            color = _lerp_gradient(colors, (i / n) + float(p))
            parts.append(f"<span style='color:{color.name()};'>{_html_escape(ch)}</span>")
        label.setText("".join(parts))

    anim.valueChanged.connect(apply)
    anim.finished.connect(lambda: label.setText(orig_text))
    apply(0.0)
    anim.start()
    return _own(label, anim)


# ---------------------------------------------------------------------------
# 预设：过渡（QStackedWidget / 两控件间）
# ---------------------------------------------------------------------------

def _stacked_overlay(stacked: QStackedWidget) -> QWidget:
    """抓取当前页快照，作为叠加层盖在 stacked 上（用于过渡动画）。

    快照叠加层路径：纯 QPainter 绘制，透明度由叠加层自身属性驱动，
    不再向叠加层挂 QGraphicsOpacityEffect。
    """
    current = stacked.currentWidget()
    if current is None:
        return None
    return _SnapshotOverlay(current, _grab_pixmap(current), margin=1)


def cross_fade(target, **opts):
    """交叉淡化：A 淡出、B 淡入。

    用途:
        QStackedWidget 页面切换或两个重叠控件间的柔和过渡。
    参数:
        target: QStackedWidget（配合 ``index`` 参数）或源控件 A
            （配合 ``to`` 参数指定目标控件 B）。
        index: 目标页索引（target 为 QStackedWidget 时必填）。
        to: 目标控件 B（target 为普通控件时必填；B 会与 A 同几何并 show）。
        duration / easing: 默认 ``normal``(200) / ``standard``。
    返回:
        QPropertyAnimation / QParallelAnimationGroup。

    实现说明:
        QStackedWidget 分支：先抓取当前页快照叠加层，立即切换页码，
        再让叠加层自绘淡出（等效两页交叉淡化），结束后叠加层销毁。
        两控件分支：A、B 各走一个快照会话——A 淡出（hide_source=True
        时结束保持隐藏，默认），B 从隐藏快照淡入、结束显示；
        中途 stop() 两控件均还原初始可见性。全程不使用
        QGraphicsOpacityEffect。
    示例::

        cross_fade(stacked, index=1)
        cross_fade(page_a, to=page_b, duration="slow")
    """
    duration = _dur(opts)
    easing = _ease(opts)

    if isinstance(target, QStackedWidget):
        index = opts.get("index")
        if index is None:
            raise ValueError("cross_fade: target 为 QStackedWidget 时必须提供 index 参数")
        overlay = _stacked_overlay(target)
        target.setCurrentIndex(int(index))
        if overlay is None:
            # 无当前页（空栈）：直接切页，返回空驱动动画保持句柄语义
            anim = _SnapAnimation((), target)
            anim.setDuration(1)
            anim.start()
            return _own(target, anim)
        anim = _SnapAnimation((), target, overlays=[overlay])
        anim.setDuration(duration)
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)
        anim.setEasingCurve(easing)

        def _fade(value):
            if overlay is not None:
                overlay.opacity = 1.0 - float(value)
                overlay.update()

        anim.valueChanged.connect(_fade)
        _fade(0.0)
        anim.start()
        return _own(target, anim)

    other = opts.get("to")
    if other is None:
        raise ValueError("cross_fade: 普通控件间过渡必须提供 to=<目标控件> 参数")
    hide_source = bool(opts.get("hide_source", True))
    other.setGeometry(target.geometry())
    other.raise_()

    # 两控件各一个快照会话：A 淡出（结束按 hide_source 隐藏），B 淡入（结束显示）
    session_a = _SnapSession(target, margin=1, end_hidden=hide_source)
    session_b = _SnapSession(other, margin=1, end_hidden=False)
    anim = _SnapAnimation([session_a, session_b], target)
    anim.setDuration(duration)
    anim.setStartValue(0.0)
    anim.setEndValue(1.0)
    anim.setEasingCurve(easing)
    ov_a, ov_b = session_a.overlay, session_b.overlay

    def _apply(value):
        k = float(value)
        if ov_a is not None:
            ov_a.opacity = 1.0 - k
            ov_a.update()
        if ov_b is not None:
            ov_b.opacity = k
            ov_b.update()

    anim.valueChanged.connect(_apply)
    _apply(0.0)
    anim.start()
    return _own(target, anim)


def page_transition(stacked, index, kind="fade", **opts):
    """页面切换：QStackedWidget 切页过渡（淡入淡出或滑动）。

    用途:
        多页表单、向导、设置页的切换过渡。
    参数:
        stacked: 目标 QStackedWidget。
        index: 目标页索引。
        kind: ``fade``（交叉淡化，默认）或 ``slide``（滑动推入）。
        direction: kind=slide 时新页进入方向 ``left``（从右向左推入，
            默认）/ ``right`` / ``up`` / ``down``。
        duration / easing: 默认 ``slow``(320) / ``entrance``。
    返回:
        动画对象 / 动画组。
    示例::

        page_transition(stacked, 1, kind="slide", direction="left")
        page_transition(stacked, 0, kind="fade")
    """
    if not isinstance(stacked, QStackedWidget):
        raise TypeError("page_transition: target 必须是 QStackedWidget")
    if kind == "fade":
        return cross_fade(stacked, index=index, **opts)
    if kind != "slide":
        raise ValueError(f"未知过渡类型: {kind!r}，应为 fade / slide")

    direction = opts.get("direction", "left")
    if direction not in _DIRECTIONS:
        raise ValueError(f"未知方向: {direction!r}，应为 {_DIRECTIONS} 之一")
    duration = _dur(opts, "slow")
    easing = _ease(opts, "entrance")

    current = stacked.currentWidget()
    new_page = stacked.widget(int(index))
    if current is None or new_page is None or new_page is current:
        stacked.setCurrentIndex(int(index))
        anim = _SnapAnimation((), stacked)
        anim.setDuration(1)
        anim.start()
        return _own(stacked, anim)

    w = max(stacked.width(), 1)
    h = max(stacked.height(), 1)
    in_offset = _direction_offset(direction, w, h)

    # 新页快照叠加层从 direction 侧滑入（覆盖静止的旧页）；
    # 自然结束先切页（on_finalize，新页与叠加层末帧像素一致、无跳变）
    # 再移除叠加层；中途 stop() 不切页、仅移除叠加层。
    margin = max(abs(in_offset.x()), abs(in_offset.y())) + 2
    overlay = _SnapshotOverlay(current, _grab_pixmap(new_page), margin=margin)
    anim = _SnapAnimation((), stacked, overlays=[overlay])
    anim.on_finalize = lambda: stacked.setCurrentIndex(int(index))
    anim.setDuration(duration)
    anim.setStartValue(0.0)
    anim.setEndValue(1.0)
    anim.setEasingCurve(QEasingCurve(QEasingCurve.Linear))
    e_ent = easing

    def _apply(value):
        k = 1.0 - e_ent.valueForProgress(float(value))
        overlay.dx = in_offset.x() * k
        overlay.dy = in_offset.y() * k
        overlay.update()

    anim.valueChanged.connect(_apply)
    _apply(0.0)
    anim.start()
    return _own(stacked, anim)


def slide_transition(target, **opts):
    """滑动过渡：源控件滑出、目标控件滑入（或 QStackedWidget 滑动切页）。

    用途:
        步骤条驱动的内容切换、左右轮替面板。
    参数:
        target: 源控件 A 或 QStackedWidget（后者需 ``index`` 参数）。
        to: 目标控件 B（普通控件间过渡时必填）。
        index: 页索引（QStackedWidget 时必填）。
        direction: B 进入方向，默认 ``left``（从右向左推入）。
        duration / easing: 默认 ``slow``(320) / ``entrance``。
        hide_source: 结束后是否隐藏 A 并还原其位置（默认 True）。
    返回:
        QParallelAnimationGroup。
    示例::

        slide_transition(panel_a, to=panel_b)
        slide_transition(stacked, index=1, direction="right")
    """
    if isinstance(target, QStackedWidget):
        index = opts.pop("index", None)
        if index is None:
            raise ValueError("slide_transition: target 为 QStackedWidget 时必须提供 index 参数")
        return page_transition(target, index, kind="slide", **opts)

    other = opts.get("to")
    if other is None:
        raise ValueError("slide_transition: 普通控件间过渡必须提供 to=<目标控件> 参数")
    direction = opts.get("direction", "left")
    if direction not in _DIRECTIONS:
        raise ValueError(f"未知方向: {direction!r}，应为 {_DIRECTIONS} 之一")
    duration = _dur(opts, "slow")
    easing = _ease(opts, "entrance")

    w = max(target.width(), 1)
    h = max(target.height(), 1)
    offset = _direction_offset(direction, w, h)
    a_start = target.pos()

    other.setGeometry(target.geometry())
    other.move(a_start + offset)
    other.show()
    other.raise_()

    group = QParallelAnimationGroup(target)
    out_anim = QPropertyAnimation(target, b"pos")
    out_anim.setDuration(duration)
    out_anim.setStartValue(a_start)
    out_anim.setEndValue(a_start - offset)
    out_anim.setEasingCurve(easing)
    group.addAnimation(out_anim)

    in_anim = QPropertyAnimation(other, b"pos")
    in_anim.setDuration(duration)
    in_anim.setStartValue(a_start + offset)
    in_anim.setEndValue(a_start)
    in_anim.setEasingCurve(easing)
    group.addAnimation(in_anim)

    def _finish():
        if opts.get("hide_source", True):
            target.setVisible(False)
            target.move(a_start)  # 还原坐标，便于下次复用

    group.finished.connect(_finish)
    group.start()
    return _own(target, group)


# ---------------------------------------------------------------------------
# 预设：容器变形与共享元素
# ---------------------------------------------------------------------------

def container_morph(target, **opts):
    """容器变形：大小与圆角平滑过渡到目标值（可用于展开 / 收起态切换）。

    用途:
        卡片展开为面板、标签收缩为胶囊等形变过渡。
    参数:
        target: 目标 QWidget。
        size: 目标尺寸 ``(w, h)``；缺省保持当前尺寸（仅变形圆角）。
        radius: 目标圆角 px；缺省不变形圆角。
        from_radius: 起始圆角 px，默认 0。
        keep: 结束后是否保留最终尺寸约束（默认 True；
            False 时还原初始 min/max 尺寸约束与样式表）。
        duration / easing: 默认 ``slow``(320) / ``standard``。
    返回:
        QVariantAnimation，附带 ``restore()`` 方法（恢复初始约束与样式表）。

    实现说明:
        尺寸通过逐帧写 ``minimumSize`` / ``maximumSize`` 实现，
        因此在布局中也能被布局正确吸收；圆角通过逐帧重写
        styleSheet 的 ``border-radius`` 实现（自动置 ``WA_StyledBackground``）。
    示例::

        anim = container_morph(card, size=(320, 200), radius=12)
        ...
        anim.restore()
    """
    size = opts.get("size")
    radius = opts.get("radius")
    if size is None and radius is None:
        raise ValueError("container_morph: size 与 radius 至少提供一个")
    start_w, start_h = target.width(), target.height()
    end_w, end_h = (int(size[0]), int(size[1])) if size else (start_w, start_h)
    start_radius = float(opts.get("from_radius", 0))
    end_radius = float(radius) if radius is not None else None

    orig = {
        "min_w": target.minimumWidth(),
        "max_w": target.maximumWidth(),
        "min_h": target.minimumHeight(),
        "max_h": target.maximumHeight(),
        "sheet": target.styleSheet(),
    }
    base_sheet = orig["sheet"]
    if end_radius is not None:
        target.setAttribute(Qt.WA_StyledBackground, True)
        if not base_sheet:
            base_sheet = "background: palette(base);"  # 保证圆角可见的最简背景

    anim = QVariantAnimation(target)
    anim.setDuration(_dur(opts, "slow"))
    anim.setStartValue(0.0)
    anim.setEndValue(1.0)
    anim.setEasingCurve(_ease(opts))

    def apply(p):
        t = float(p)
        if size is not None:
            w = round(start_w + (end_w - start_w) * t)
            h = round(start_h + (end_h - start_h) * t)
            target.setMinimumSize(w, h)
            target.setMaximumSize(w, h)
        if end_radius is not None:
            r = start_radius + (end_radius - start_radius) * t
            target.setStyleSheet(f"{base_sheet} border-radius: {r:.1f}px;")

    anim.valueChanged.connect(apply)

    def restore():
        """恢复初始尺寸约束与样式表。"""
        anim.stop()
        target.setMinimumSize(orig["min_w"], orig["min_h"])
        target.setMaximumSize(orig["max_w"], orig["max_h"])
        target.setStyleSheet(orig["sheet"])

    anim.restore = restore
    if not opts.get("keep", True):
        anim.finished.connect(restore)
    apply(0.0)
    anim.start()
    return _own(target, anim)


def shared_element(target, **opts):
    """共享元素转场：把控件几何从当前位置平滑移动到目标位置。

    用途:
        列表缩略图放大为详情图、元素在两个容器间的「飞行」转场。
    参数:
        target: 目标 QWidget（需与目标矩形处于同一坐标系，
            通常为同一父控件下的绝对定位子控件）。
        to: 目标矩形 QRect（父控件坐标系）；或用 ``to_widget``
            指定参照控件（取其 geometry()）。
        duration / easing: 默认 ``slow``(320) / ``emphasis``。
        fade: 是否同步淡入（默认 False；True 时 0→1）。
    返回:
        QPropertyAnimation / QParallelAnimationGroup。
    示例::

        shared_element(thumb, to=QRect(240, 40, 320, 180))
        shared_element(avatar, to_widget=detail_avatar_slot)
    """
    to_rect = opts.get("to")
    to_widget = opts.get("to_widget")
    if to_rect is None and to_widget is not None:
        to_rect = to_widget.geometry()
    if to_rect is None:
        raise ValueError("shared_element: 必须提供 to=QRect 或 to_widget=<参照控件>")

    geo_anim = QPropertyAnimation(target, b"geometry", target)
    geo_anim.setDuration(_dur(opts, "slow"))
    geo_anim.setStartValue(target.geometry())
    geo_anim.setEndValue(QRect(to_rect))
    geo_anim.setEasingCurve(_ease(opts, "emphasis"))

    if not opts.get("fade", False):
        geo_anim.start()
        return _own(target, geo_anim)

    eff = _opacity_effect(target)
    eff.setOpacity(0.0)
    op_anim = QPropertyAnimation(eff, b"opacity", target)
    op_anim.setDuration(geo_anim.duration())
    op_anim.setStartValue(0.0)
    op_anim.setEndValue(1.0)

    group = QParallelAnimationGroup(target)
    group.addAnimation(geo_anim)
    group.addAnimation(op_anim)
    group.finished.connect(lambda: _maybe_remove_effect(target, eff))
    group.start()
    return _own(target, group)
