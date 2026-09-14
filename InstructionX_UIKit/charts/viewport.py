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

    静态层（底色/坐标轴/图例/标题）命中缓存时以位图直接贴回，跳过整段
    轴刻度文字的重排与绘制；未命中则走 ``_paint_contents`` 全量绘制。
    """

    def __init__(self, chart) -> None:
        super().__init__(chart)
        self._init_viewport(chart)
        self.setAttribute(Qt.WA_OpaquePaintEvent, True)

    def paintEvent(self, event) -> None:  # noqa: N802
        p = QPainter(self)
        try:
            chart = self._chart
            if chart.static_layer_valid(p):
                if not p.testRenderHint(QPainter.Antialiasing):
                    p.setRenderHint(QPainter.Antialiasing)
                p.drawPixmap(0, 0, chart._static_pixmap_cache)
                chart._paint_dynamic(p)
            else:
                chart._paint_contents(p)
        finally:
            p.end()


class _GLViewport(_ViewportMixin, QOpenGLWidget):
    """GPU 视口：QOpenGLWidget，``paintGL`` 中 QPainter 自动走 GL paint engine。

    ``samples=0``（不做 MSAA）是实测结论：Qt 的 GL paint engine 自带
    coverage 抗锯齿，叠加 MSAA 反而使与光栅路径的像素差异劣化约 14 倍
    （实测平均通道差 1.20 → 16.93）。

    GL 模式下不做脏矩形裁剪（QOpenGLWidget 默认整幅 FBO 重绘）。
    首帧缺陷规避：``showEvent`` 中强制一次 ``update()``。
    静态层命中缓存时，位图作为纹理上传并由 GPU 贴回。
    """

    def __init__(self, chart) -> None:
        super().__init__(chart)
        self._init_viewport(chart)
        self._gpu_pipe = None      # GPU 原生系列管线（惰性创建，随上下文）
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
            chart = self._chart
            # 兜底护栏：单系列几何点数超上限时不绘制超长路径，改给提示文案
            # （理由与实测数据见 ChartWidget.overload_limited）。
            if chart.overload_limited():
                chart.set_gpu_owner(None)
                chart._paint_overload_notice(p)
                return
            # GPU 接管的系列**先认领再绘制**：认领后 QPainter 就不再画它们
            # （见 ChartWidget.gpu_claims），避免同一条曲线画两遍。实测
            # 1400x500 / DPR 1.5（物理 2100x750）/ 采样后 2656 点：光栅化一次
            # 要 24 ms，而 GPU 直绘整条 2 万点曲线 0.3 ms——叠加画两遍是纯浪费。
            chart.prefer_raster_series = True
            chart.set_gpu_owner(self._claim_gpu_series(ctx))
            if chart.static_layer_valid(p):
                if not p.testRenderHint(QPainter.Antialiasing):
                    p.setRenderHint(QPainter.Antialiasing)
                p.drawPixmap(0, 0, chart._static_pixmap_cache)
                chart._paint_dynamic(p)
            else:
                chart._paint_contents(p)
            # GPU 原生直绘：QPainter 绘制结束后、其上叠加由 VBO+GLSL 直绘的
            # 系列。必须放在 QPainter 之后——GL 调用与 QPainter 的 GL 引擎
            # 共用同一上下文，交错提交状态会互相干扰。
            self._draw_gpu_series(ctx)
            chart.set_gpu_owner(None)
        finally:
            p.end()

    def _claim_gpu_series(self, ctx):
        """本帧**确实能**用 GPU 直绘的系列（上传失败/坐标不支持的不认领）。

        只认领「管线就绪 + 顶点已上传（``vertex_count >= 2``）+ 变换可用」的
        系列；任一条不满足就返回不含它，该系列仍由 QPainter 绘制，因此**不会
        出现两条路径都不画的情况**。

        **不在这里 makeCurrent**：本方法只在 ``paintGL`` 内调用，那里上下文
        已经是 current 的；再调一次 ``makeCurrent`` 会崩（实测首次绘制即
        访问违例 ``0xC0000005``）。需要在 ``paintGL`` 之外测量时请用
        ``ensure_gpu_pipeline`` + ``with viewport``（见其 docstring）。
        """
        chart = self._chart
        cands = [r for r in chart.series_renderers
                 if getattr(r, "gpu_direct", False) and r.visible]
        if not cands:
            return None
        pipe = self.ensure_gpu_pipeline()
        if pipe is None:
            return None
        claimed = []
        for r in cands:
            try:
                info = r.gpu_vertex_data()
                if info is None:
                    continue
                pipe.set_vertices(info["vertices"], version=info["version"])
                if pipe.vertex_count < 2:
                    continue
                if r.gpu_transform(chart.coord_for(r.opt)) is None:
                    continue
                claimed.append(r)
            except Exception:  # noqa: BLE001 - 单个系列失败不影响其他
                continue
        return claimed or None

    def ensure_gpu_pipeline(self):
        """确保 GPU 直绘管线可用，返回它或 ``None``（供 benchmark 调用）。

        **为什么需要这个钩子**：管线原本只在 ``paintGL`` 中惰性创建，而位于
        长页面底部的图表可能长期被 ``QScrollArea`` 裁剪、**从未被绘制**——
        此时从外部调用 :meth:`ChartWidget.benchmark` 会拿不到管线，读数显示
        「GPU 不可用」，而实际环境完全支持。本方法让测量不依赖「是否已滚动到
        可见区域」。

        内部会 makeCurrent；调用方负责在结束后 ``doneCurrent``（见
        ``__enter__`` / ``__exit__``）。
        """
        ctx = self.context()
        if ctx is None or not ctx.isValid():
            return None
        pipe = self._gpu_pipe
        if pipe is not None and pipe.ready:
            return pipe
        from .gl_series import GLSeriesPipeline
        pipe = GLSeriesPipeline()
        if not pipe.ensure(ctx):
            logger.warning("GPU 原生直绘管线建立失败，回退 QPainter 路径")
            return None
        self._gpu_pipe = pipe
        return pipe

    def __enter__(self):
        """上下文管理：让视口上下文 current（测量 GPU 前必须）。"""
        try:
            self.makeCurrent()
            self._ctx_entered = True
        except Exception:  # noqa: BLE001
            self._ctx_entered = False
        return self

    def __exit__(self, *exc) -> bool:
        if getattr(self, "_ctx_entered", False):
            try:
                self.doneCurrent()
            except Exception:  # noqa: BLE001
                pass
            self._ctx_entered = False
        return False

    def _draw_gpu_series(self, ctx) -> None:
        """把开启 ``gpuDirect`` 的系列用 VBO + GLSL 直接绘制。

        仅在 GL 视口内调用；任何失败都记录一次并退回（该系列在 QPainter
        阶段已按常规路径绘制，故不会缺图）。绘制顺序为「静态层 → QPainter
        动态层 → GPU 系列」，与纯 QPainter 路径的遮挡关系一致。
        """
        chart = self._chart
        series = [r for r in chart.series_renderers
                  if getattr(r, "gpu_direct", False) and r.visible]
        if not series:
            return
        pipe = self.ensure_gpu_pipeline()
        if pipe is None:
            return
        try:
            dpr = float(self.devicePixelRatioF())
        except Exception:  # noqa: BLE001
            dpr = 1.0
        chart._layout_all()
        for r in series:
            try:
                self._draw_one_gpu_series(ctx, pipe, r, dpr)
            except Exception:  # noqa: BLE001 - 单系列失败不影响整图
                continue

    def _draw_one_gpu_series(self, ctx, pipe, renderer, dpr) -> None:
        """绘制单个系列：数据坐标顶点 + 数据区间 → 绘图区像素的变换。"""
        from .gl_series import build_mvp
        coord = self._chart.coord_for(renderer.opt)
        info = renderer.gpu_vertex_data()
        if info is None:
            return
        # 版本不变则命中 VBO 缓存（不重传）
        pipe.set_vertices(info["vertices"], version=info["version"])
        if pipe.vertex_count < 2:
            return
        tr = renderer.gpu_transform(coord)
        if tr is None:
            return
        x0, x1, y0, y1, plot = tr
        # 变换一次性算好：数据区间 → 绘图区在视口内的 NDC 子区域。
        # 用**逻辑像素**表达 plot 与 viewport（GL 视口的 NDC 与物理像素无关），
        # 因此不需要 devicePixelRatio。
        mvp = build_mvp(x0, x1, y0, y1,
                        plot=(plot.width(), plot.height(),
                              plot.left(), plot.top()),
                        viewport=(self.width(), self.height()))
        if mvp is None:
            return
        w = self.width() * dpr
        h = self.height() * dpr
        if w <= 0 or h <= 0:
            return
        f = ctx.functions()
        f.glViewport(0, 0, int(w), int(h))
        color = renderer.color()
        pipe.draw(ctx, mvp, color, mode="line_strip",
                  width=float(renderer.opt.get("lineWidth", 2.0) or 2.0))


def create_viewport(chart) -> QWidget:
    """按 GL 可用性为图表创建绘制视口（调用方负责铺满与 show）。"""
    if gl_available():
        try:
            return _GLViewport(chart)
        except Exception as exc:  # 防御：构造期异常同样回退
            logger.warning("GL 视口创建失败，回退软件渲染: %s", exc)
    return _RasterViewport(chart)
