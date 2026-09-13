# -*- coding: utf-8 -*-
"""图表绘制视口（CHART_SPEC §7 渲染后端，GPU 加速承载层）。

``ChartWidget`` 保持 ``QWidget`` 基类与全部公共 API 不变；其自绘内容由本
模块的私有视口子控件承载，视口与图表控件 1:1 重合：

- GL 可用：``_GLViewport(QOpenGLWidget)``——``paintGL`` 中以 ``QPainter``
  执行与软件路径**同一份**绘制代码（``ChartWidget._paint_contents``），
  自动走 GL paint engine：填充 / 曲线 / 渐变由 GPU 承担，文本走字形纹理
  缓存；
- GL 不可用（offscreen / minimal 测试环境、无 GL 驱动、``UIKIT_CHART_GL=off``）：
  ``_RasterViewport(QWidget)``，行为与历史实现逐像素等价。

GL 可用性由 ``gl_available()`` 运行时探测（模块级缓存，仅探测一次）：

- 环境变量 ``UIKIT_CHART_GL``：``auto``（默认）/ ``on``（强制尝试，失败仍
  回退并记 WARNING）/ ``off``（强制软件渲染）；
- offscreen / minimal 平台直接判不可用（实测该组合下 GL 上下文无法创建，
  与 ``blueprint/viewport.py`` 的 ``UIKIT_BLUEPRINT_GL`` 同款判定）；
- 其余平台试探创建 ``QOpenGLContext`` + ``QOffscreenSurface`` 并
  ``makeCurrent``，任何一步失败即回退。

【重要限制，勿据此判断“已 GPU 化”】``QPainter`` 的 GL paint engine 仅在
目标绘制设备就是 ``QOpenGLWidget`` 自身时生效；一旦把内容绘制到
``QPixmap`` 缓冲层就完全退回 CPU 光栅，且复杂描边路径在 GL 引擎内仍要
CPU 侧展平/三角化。因此本模块只解决“绘制设备换为 GPU”，**系列几何直接
提交显卡（顶点缓冲 + GLSL）由后续的 GPU 原生渲染承载**。

实时性注意：视口每帧重绘会连同坐标轴与文字一起重画。分层缓存（静态层/
动态层/覆盖层）是后续独立阶段的工作，本模块不承担。
"""

import logging
import os

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QGuiApplication, QPainter, QSurfaceFormat
from PySide6.QtOpenGLWidgets import QOpenGLWidget
from PySide6.QtWidgets import QWidget

from ..theme import T

logger = logging.getLogger(__name__)

__all__ = ["gl_available", "create_viewport"]

#: GL 可用性探测结果（模块级缓存，``None`` 表示尚未探测）
_GL_STATE = None

#: 不支持 GL 的平台名（实测这些平台无法创建 GL 上下文）
_NO_GL_PLATFORMS = ("offscreen", "minimal", "minimalegl")


def gl_available() -> bool:
    """当前环境是否可用 GL 视口（结果缓存；受 ``UIKIT_CHART_GL`` 控制）。

    ``QApplication`` 尚未创建时不写缓存：此时探测必然为假但结论不可信
    （GL 设施随应用创建），缓存会把进程永久锁定在软件渲染。
    """
    global _GL_STATE
    if _GL_STATE is None:
        if QGuiApplication.instance() is None:
            return False
        _GL_STATE = _probe_gl()
    return _GL_STATE


def _probe_gl() -> bool:
    """实际探测：环境变量 → 平台名 → 试探创建 GL 上下文。"""
    env = os.environ.get("UIKIT_CHART_GL", "auto").strip().lower()
    if env == "off":
        return False
    app = QGuiApplication.instance()
    if app is None:
        return False
    platform = app.platformName()
    if platform in _NO_GL_PLATFORMS:
        if env == "on":
            logger.warning(
                "UIKIT_CHART_GL=on 但平台 %s 不支持 GL，回退软件渲染", platform)
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
                "UIKIT_CHART_GL=on 但 GL 探测失败（%s），回退软件渲染", exc)
        return False


class _ViewportMixin:
    """视口公共行为：持有图表引用、转发交互事件（1:1 重合，坐标一致）。"""

    def _init_viewport(self, chart) -> None:
        self._chart = chart
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setAutoFillBackground(False)
        self.setMinimumSize(0, 0)

    # -- 事件转发（Qt 覆写，保留 camelCase） --------------------------------
    def mousePressEvent(self, event) -> None:  # noqa: N802
        self._chart.mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        self._chart.mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        self._chart.mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802
        self._chart.mouseDoubleClickEvent(event)

    def wheelEvent(self, event) -> None:  # noqa: N802
        self._chart.wheelEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802
        self._chart.leaveEvent(event)

    def enterEvent(self, event) -> None:  # noqa: N802
        self._chart.enterEvent(event)

    def contextMenuEvent(self, event) -> None:  # noqa: N802
        self._chart.contextMenuEvent(event)


class _RasterViewport(_ViewportMixin, QWidget):
    """软件回退视口：普通 QWidget，``paintEvent`` 走 CPU 光栅（历史行为）。

    行为与历史实现逐像素等价——offscreen 测试与截图回归依赖这一点。
    """

    def __init__(self, chart) -> None:
        super().__init__(chart)
        self._init_viewport(chart)
        self.setAttribute(Qt.WA_OpaquePaintEvent, True)

    def paintEvent(self, event) -> None:  # noqa: N802
        p = QPainter(self)
        self._chart._paint_contents(p)
        p.end()


class _GLViewport(_ViewportMixin, QOpenGLWidget):
    """GPU 视口：QOpenGLWidget，``paintGL`` 中 QPainter 自动走 GL paint engine。

    ``samples=0``（不做 MSAA）是实测结论：Qt 的 GL paint engine 自带
    coverage 抗锯齿，叠加 MSAA 反而使与光栅路径的像素差异劣化约 14 倍
    （实测平均通道差 1.20 → 16.93）。

    GL 模式下不做脏矩形裁剪（QOpenGLWidget 默认整幅 FBO 重绘）。
    首帧缺陷规避：``showEvent`` 中强制一次 ``update()``。
    """

    def __init__(self, chart) -> None:
        super().__init__(chart)
        self._init_viewport(chart)
        fmt = QSurfaceFormat()
        fmt.setSamples(0)
        self.setFormat(fmt)

    def showEvent(self, event) -> None:  # noqa: N802
        """首次显示后强制一次重绘，规避首帧合成缺陷。"""
        super().showEvent(event)
        self.update()

    def paintGL(self) -> None:
        ctx = self.context()
        if ctx is None or not ctx.isValid():
            # 防御：上下文不可用时只铺主题底色，绝不留黑屏/花屏
            p = QPainter(self)
            p.fillRect(self.rect(), QColor(T("color.bg.base")))
            p.end()
            return
        p = QPainter(self)
        try:
            self._chart._paint_contents(p)
        finally:
            p.end()


def create_viewport(chart) -> QWidget:
    """按 GL 可用性为图表创建绘制视口（调用方负责铺满与 show）。"""
    if gl_available():
        try:
            return _GLViewport(chart)
        except Exception as exc:  # 防御：构造期异常同样回退
            logger.warning("GL 视口创建失败，回退软件渲染: %s", exc)
    return _RasterViewport(chart)
