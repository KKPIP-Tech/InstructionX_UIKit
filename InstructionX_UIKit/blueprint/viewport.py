# -*- coding: utf-8 -*-
"""蓝图画布绘制视口（BP_SPEC §5 实现细节，GPU 加速承载层）。

``BlueprintCanvas`` 保持 ``QWidget`` 基类与全部公共 API 不变；其自绘
内容（背景 / 网格 / 选中发光 / 边 / 临时线 / 框选）由本模块的私有
视口子控件承载，视口与画布 1:1 重合：

- GL 可用：``_GLViewport(QOpenGLWidget)``——``paintGL`` 中以
  ``QPainter`` 执行与软件路径**同一份**绘制代码（
  ``BlueprintCanvas._paint_contents``），自动走 GL paint engine：
  填充 / 纹理平铺 / 曲线由 GPU 承担，文本走字形纹理缓存；
- GL 不可用（offscreen / minimal 测试环境、无 GL 驱动、
  ``UIKIT_BLUEPRINT_GL=off``）：``_RasterViewport(QWidget)``，
  行为与历史实现逐像素等价。

GL 可用性由 ``gl_available()`` 运行时探测（模块级缓存，仅探测一次）：

- 环境变量 ``UIKIT_BLUEPRINT_GL``：``auto``（默认）/ ``on``（强制
  尝试，失败仍回退并记 WARNING）/ ``off``（强制软件渲染）；
- offscreen / minimal 平台直接判不可用（实测该组合下 GL 上下文
  无法创建）；
- 其余平台试探创建 ``QOpenGLContext`` + ``QOffscreenSurface`` 并
  ``makeCurrent``，任何一步失败即回退。

节点控件（``NodeWidget`` 及其子控件）挂在视口之下：GL 模式下作为
alien 子控件由 Qt 合成叠加在 GL 内容上（已实测验证）。鼠标 / 滚轮 /
键盘事件由视口原样转发给画布既有处理器（坐标系一致，无需换算）。
"""

import logging
import os

from PySide6.QtGui import QGuiApplication, QPainter
from PySide6.QtOpenGLWidgets import QOpenGLWidget
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QWidget

logger = logging.getLogger(__name__)

__all__ = ["gl_available", "create_viewport"]

#: GL 可用性探测结果（模块级缓存，``None`` 表示尚未探测）
_GL_STATE = None


def gl_available() -> bool:
    """当前环境是否可用 GL 视口（结果缓存；受 ``UIKIT_BLUEPRINT_GL`` 控制）。"""
    global _GL_STATE
    if _GL_STATE is None:
        _GL_STATE = _probe_gl()
    return _GL_STATE


def _probe_gl() -> bool:
    """实际探测：环境变量 → 平台名 → 试探创建 GL 上下文。"""
    env = os.environ.get("UIKIT_BLUEPRINT_GL", "auto").strip().lower()
    if env == "off":
        return False
    app = QGuiApplication.instance()
    if app is None:
        return False
    platform = app.platformName()
    if platform in ("offscreen", "minimal", "minimalegl"):
        if env == "on":
            logger.warning(
                "UIKIT_BLUEPRINT_GL=on 但平台 %s 不支持 GL，回退软件渲染", platform)
        return False
    try:
        from PySide6.QtGui import QOffscreenSurface, QOpenGLContext
        ctx = QOpenGLContext()
        if not ctx.create():
            raise RuntimeError("QOpenGLContext.create 失败")
        surface = QOffscreenSurface()
        surface.setFormat(ctx.format())
        surface.create()
        if not surface.isValid():
            raise RuntimeError("QOffscreenSurface 创建失败")
        if not ctx.makeCurrent(surface):
            raise RuntimeError("QOpenGLContext.makeCurrent 失败")
        ctx.doneCurrent()
        return True
    except Exception as exc:
        if env == "on":
            logger.warning(
                "UIKIT_BLUEPRINT_GL=on 但 GL 探测失败（%s），回退软件渲染", exc)
        return False


class _ViewportMixin:
    """视口公共行为：持有画布引用、转发交互事件（1:1 重合，坐标一致）。"""

    def _init_viewport(self, canvas) -> None:
        self._canvas = canvas
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setAutoFillBackground(False)

    # -- 事件转发（Qt 覆写，保留 camelCase） --------------------------------
    def mousePressEvent(self, event) -> None:  # noqa: N802
        self._canvas.mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        self._canvas.mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        self._canvas.mouseReleaseEvent(event)

    def wheelEvent(self, event) -> None:  # noqa: N802
        self._canvas.wheelEvent(event)

    def keyPressEvent(self, event) -> None:  # noqa: N802
        self._canvas.keyPressEvent(event)

    def keyReleaseEvent(self, event) -> None:  # noqa: N802
        self._canvas.keyReleaseEvent(event)


class _RasterViewport(_ViewportMixin, QWidget):
    """软件回退视口：普通 QWidget，paintEvent 走 CPU raster（历史行为）。

    节点由真实子控件自绘（``supports_node_proxy = False``），保证
    offscreen 测试的像素级行为与历史版本一致。
    """

    #: 不支持节点位图代理（节点自行 paintEvent）
    supports_node_proxy = False

    def __init__(self, canvas) -> None:
        super().__init__(canvas)
        self._init_viewport(canvas)
        self.setAttribute(Qt.WA_OpaquePaintEvent, True)

    def paintEvent(self, event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        self._canvas._paint_contents(p, event.rect())
        p.end()


class _GLViewport(_ViewportMixin, QOpenGLWidget):
    """GPU 视口：QOpenGLWidget，paintGL 中 QPainter 自动走 GL paint engine。

    GL 模式下不做脏矩形裁剪（QOpenGLWidget 默认整幅 FBO 重绘），
    边的视口裁剪仍由 ``_paint_contents`` 按可见区域执行。

    节点位图代理（``supports_node_proxy = True``）：无可见自定义体的
    节点以 ``NodeWidget.cache_pixmap()`` 缓存位图由本视口统一绘制
    （GL 纹理采样），平移 / 缩放手势期间节点内容零重绘；节点控件
    本身保持透明，仅承担交互（引脚热区 / 拖动）与动态子控件
    （SpinnerArc）的载体。带可见 ``body_builder`` 体的节点平时回退
    为真实控件自绘（alien 子控件叠加），但视图手势期间同样临时切换
    为位图代理（``NodeWidget.begin_gesture_proxy``），避免逐帧真实
    子控件几何落位 + 重绘叠加在 GL 视口上的高额合成开销。

    首帧缺陷规避：无边框 + ``WA_TranslucentBackground`` 顶层窗口下
    QOpenGLWidget 首帧可能把旧的合成结果送上屏幕（FBO 内容完整但
    节点不显示，任意一次重绘即恢复），``showEvent`` 中强制一次
    ``update()`` 规避。
    """

    #: 支持节点位图代理绘制
    supports_node_proxy = True

    def __init__(self, canvas) -> None:
        super().__init__(canvas)
        self._init_viewport(canvas)

    def showEvent(self, event) -> None:  # noqa: N802
        """首次显示后强制一次重绘，规避半透明顶层窗口下的首帧合成缺陷。"""
        super().showEvent(event)
        self.update()

    def paintGL(self) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        self._canvas._paint_contents(p, None)
        self._paint_proxied_nodes(p)
        p.end()

    def _paint_proxied_nodes(self, p: QPainter) -> None:
        """按场景坐标实时绘制全部可见代理节点的缓存位图（节点在边之上）。

        位置直接由 ``scene_to_view(node.pos)`` 计算而非读取控件几何：
        视图手势（平移 / 滚轮缩放）期间画布会跳过逐节点几何落位
        （见 ``BlueprintCanvas._view_changed``），此处仍保证视觉正确。
        """
        from PySide6.QtCore import QRectF, QPointF
        p.setRenderHint(QPainter.SmoothPixmapTransform, True)
        canvas = self._canvas
        z = canvas._zoom
        ox, oy = canvas._offset.x(), canvas._offset.y()
        vw, vh = self.width(), self.height()
        for w in canvas._node_widgets.values():
            # uses_proxy 覆盖常规代理（无可见体）与手势代理（手势期全体）
            if not w.isVisible() or not w.uses_proxy():
                continue
            node = w.node
            # 内联浮点换算（scene_to_view 等价），避免逐节点 shiboken 开销
            tx = node.pos.x() * z + ox
            ty = node.pos.y() * z + oy
            nw = node.size.width() * z
            nh = node.size.height() * z
            if tx > vw or ty > vh or tx + nw < 0 or ty + nh < 0:
                continue
            pm = w.cache_pixmap()
            if abs(w._cache_scale - z) > 1e-3:
                # 缩放手势中：旧位图按目标矩形拉伸（GPU 纹理缩放）
                p.drawPixmap(QRectF(tx, ty, nw, nh), pm, QRectF(pm.rect()))
            else:
                p.drawPixmap(QPointF(tx, ty), pm)


def create_viewport(canvas) -> QWidget:
    """按 GL 可用性为画布创建绘制视口（调用方负责铺满与 show）。"""
    if gl_available():
        try:
            return _GLViewport(canvas)
        except Exception as exc:  # 防御：构造期异常同样回退
            logger.warning("GL 视口创建失败，回退软件渲染: %s", exc)
    return _RasterViewport(canvas)
