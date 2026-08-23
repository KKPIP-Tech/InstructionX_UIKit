# -*- coding: utf-8 -*-
"""MermaidView：可交互 Mermaid 图查看器（SPEC 禁 WebView/JS 约束经用户显式豁免，仅限本子包内部）。

与 ``hub`` 的「渲染成静态 QImage」不同，本控件内嵌**实时渲染**的
``QWebEngineView``（每个实例一个隐藏加载 viewer 页面）：mermaid 渲染出的
SVG 放进页面 wrapper div，缩放 / 平移用 CSS transform 作用于 wrapper，
交互（拖动平移、Ctrl+滚轮以光标为中心缩放、双击复位）全部在 JS 内完成，
排版与交互同一引擎，行为对齐 GitHub / mermaid.live。

- 右上角悬浮工具条：放大 / 缩小 / 复位 / 适应宽度四个按钮。
  主路径下工具条**画在 viewer HTML 页面内**（QWebEngineView 是原生窗口
  控件，永远压在 alien 兄弟控件之上，Qt 悬浮工具条会被 web 视图盖住而
  点不到），主题色由 Qt 侧经 ``setChrome`` 注入为 CSS 变量；降级画布
  没有原生控件遮挡问题，保留 Qt 自绘工具条（``_Toolbar``）。
- **滚轮放行**：控件会内嵌进 MarkdownView 等滚动宿主，普通滚轮必须留给
  宿主滚动页面——事件过滤器吃掉不带 Ctrl 的 wheel 并手工转发给最近的
  ``QAbstractScrollArea`` 祖先；Ctrl+wheel 放行给 WebEngine 做 JS 缩放。
- 主题热切换：连接 ``ThemeManager.theme_changed``，用新令牌重算
  themeVariables（复用 ``hub._theme_variables``）重新渲染。
- 降级路径（WebEngine 不可用）：经 ``hub`` 的自绘后端拿 QImage，
  ``_FallbackCanvas`` 以 QPainter scale/translate 绘制，交互行为一致
  （仅支持 flowchart/sequenceDiagram/pie 子集，与 hub 降级后端相同）。

公共契约见类 docstring；全部公开方法须在 GUI 线程调用。
"""

import json
import os
import sys
import time

from PySide6.QtCore import (
    QCoreApplication,
    QEvent,
    QPointF,
    QRectF,
    QSize,
    Qt,
    QTimer,
    QUrl,
    Signal,
)
from PySide6.QtGui import (
    QColor,
    QMouseEvent,
    QPainter,
    QWheelEvent,
)
from PySide6.QtWidgets import (
    QAbstractScrollArea,
    QHBoxLayout,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..icons import get_icon
from ..theme import T, ThemeManager, set_property
from ..tokens import FONT_FAMILY
from .hub import MermaidRenderHub, _theme_variables

__all__ = ["MermaidView"]

#: 缩放倍率上下限
_MIN_SCALE = 0.05
_MAX_SCALE = 8.0
#: 单步缩放倍率（工具条按钮）
_ZOOM_STEP = 1.25
#: 渲染结果轮询间隔 / 超时（毫秒）
_POLL_MS = 15
_RENDER_TIMEOUT_MS = 15000
#: viewer 页面路径缓存（写一次）
_viewer_file = None

#: WebEngine 可用性缓存（模块级判定一次）
_webengine_ok = None


def _webengine_available() -> bool:
    """QWebEngineView 是否可用（缓存判定结果）。"""
    global _webengine_ok
    if _webengine_ok is None:
        try:
            import PySide6.QtWebEngineWidgets  # noqa: F401
            from PySide6.QtWebEngineWidgets import QWebEngineView  # noqa: F401
            _webengine_ok = True
        except ImportError:
            _webengine_ok = False
    return _webengine_ok


def _viewer_file_path() -> str:
    """viewer 页面 HTML 的临时文件路径（写一次后复用）。

    与 hub 的 render.html 不同，本页面是可交互的：SVG 放进 wrapper div，
    CSS transform（translate + scale，origin 0 0）承载缩放 / 平移，
    拖动 / Ctrl+滚轮 / 双击在 JS 内处理；``window.__uikViewer`` 暴露给
    Qt 侧 runJavaScript 调用。页面为 file:// 源，引用同源的
    mermaid.min.js 不受安全策略限制（setHtml 有约 2MB 上限，无法内联）。
    """
    from .hub import _mermaid_js_path

    global _viewer_file
    if _viewer_file is None:
        import tempfile
        directory = os.path.join(tempfile.gettempdir(), "uik_mermaid")
        os.makedirs(directory, exist_ok=True)
        js_url = QUrl.fromLocalFile(_mermaid_js_path()).toString()
        html = _VIEWER_HTML.replace("__MERMAID_JS_URL__", js_url)
        _viewer_file = os.path.join(directory, "viewer.html")
        with open(_viewer_file, "w", encoding="utf-8") as f:
            f.write(html)
    return _viewer_file


#: viewer 页面模板（__MERMAID_JS_URL__ 为占位符）。
#: 交互要点：pointerdown/move/up + setPointerCapture 拖动平移；
#: wheel 监听 {passive:false} 且仅响应 ctrlKey（普通滚轮在 Qt 侧已被
#: 事件过滤器吃掉转发宿主，不会到达页面）；dblclick 复位为适应宽度。
#: 右上角工具条在 HTML 内（原生窗口遮挡，见模块 docstring），配色经
#: CSS 变量（--uik-tb-*）由 Qt 侧 setChrome 注入。
_VIEWER_HTML = """<!DOCTYPE html><html><head><meta charset="utf-8">
<style>
html,body{margin:0;padding:0;background:transparent;overflow:hidden;
          user-select:none;-webkit-user-select:none;}
#viewport{position:absolute;left:0;top:0;width:100%;height:100%;
          overflow:hidden;cursor:grab;}
#viewport:active{cursor:grabbing;}
#wrapper{position:absolute;left:0;top:0;transform-origin:0 0;}
#wrapper svg{display:block;}
#toolbar{position:absolute;top:8px;right:8px;z-index:10;
         display:flex;align-items:center;gap:2px;padding:2px 4px;
         border-radius:var(--uik-tb-radius,6px);
         background:var(--uik-tb-bg,rgba(255,255,255,0.86));
         border:1px solid var(--uik-tb-border,rgba(0,0,0,0.3));
         font-family:var(--uik-tb-font,sans-serif);}
#toolbar button{border:0;margin:0;padding:2px 7px;border-radius:4px;
                background:transparent;cursor:pointer;
                color:var(--uik-tb-text,#222);font-family:inherit;
                font-size:12px;line-height:16px;}
#toolbar button:hover{background:var(--uik-tb-hover,rgba(0,0,0,0.08));}
</style>
<script src="__MERMAID_JS_URL__"></script>
</head><body><div id="viewport"><div id="wrapper"></div></div>
<div id="toolbar"><button id="tb-zoom-in" title="放大">+</button
><button id="tb-zoom-out" title="缩小">−</button
><button id="tb-reset" title="复位">复位</button
><button id="tb-fit" title="适应宽度">适宽</button></div>
<script>
(function () {
  const viewport = document.getElementById('viewport');
  const wrapper = document.getElementById('wrapper');
  const MIN_S = 0.05, MAX_S = 8.0, STEP = 1.25;
  let scale = 1, tx = 0, ty = 0;
  let contentW = 0, contentH = 0;
  let code = '', themeVars = {};
  let renderSeq = 0;

  function apply() {
    wrapper.style.transform = 'translate(' + tx + 'px,' + ty + 'px)' +
                              ' scale(' + scale + ')';
  }
  function fitWidth() {
    if (contentW <= 0) return;
    const vw = viewport.clientWidth;
    if (vw <= 0) return;
    // 放大不设低上限（上限取全局 MAX_S）：初始观感须与宿主的
    // 「放大到视口 80% 宽」静态 PNG 一致，小图换透明底后无跳变
    scale = Math.min(MAX_S, vw / contentW);
    tx = (vw - contentW * scale) / 2;  // 水平居中，顶部对齐
    ty = 0;
    interacted = false;  // 复位后回到「随宿主宽度自适应」状态
    apply();
  }
  let interacted = false;  // 用户手动缩放/拖动过后，宿主 resize 不再重适配
  function zoomAt(cx, cy, factor) {
    const ns = Math.min(MAX_S, Math.max(MIN_S, scale * factor));
    if (ns === scale) return;
    const k = ns / scale;
    tx = cx - (cx - tx) * k;
    ty = cy - (cy - ty) * k;
    scale = ns;
    apply();
  }

  // ---- 拖动平移 ----
  let dragging = false, lx = 0, ly = 0;
  viewport.addEventListener('pointerdown', (e) => {
    if (e.button !== 0) return;  // 仅左键拖动（与降级画布一致）
    dragging = true; interacted = true; lx = e.clientX; ly = e.clientY;
    viewport.setPointerCapture(e.pointerId);
  });
  viewport.addEventListener('pointermove', (e) => {
    if (!dragging) return;
    tx += e.clientX - lx; ty += e.clientY - ly;
    lx = e.clientX; ly = e.clientY;
    apply();
  });
  const stop = () => { dragging = false; };
  viewport.addEventListener('pointerup', stop);
  viewport.addEventListener('pointercancel', stop);

  // ---- Ctrl+滚轮缩放（以光标为中心）；普通滚轮由 Qt 侧转发给宿主 ----
  viewport.addEventListener('wheel', (e) => {
    if (!e.ctrlKey) return;
    e.preventDefault();
    interacted = true;
    const r = viewport.getBoundingClientRect();
    zoomAt(e.clientX - r.left, e.clientY - r.top, e.deltaY < 0 ? STEP : 1 / STEP);
  }, {passive: false});
  viewport.addEventListener('dblclick', fitWidth);
  // Chromium 视口尺寸变化（宿主控件 resize）由页面自己感知——Qt 侧
  // resizeEvent 触发时 compositor 尚未更新 clientWidth（实测拿到旧宽度），
  // window resize 事件才能保证量到新尺寸
  window.addEventListener('resize', () => { if (!interacted) fitWidth(); });

  // ---- 渲染 ----
  function doRender() {
    const seq = ++renderSeq;
    window.__uikViewResult = '';
    mermaid.initialize({startOnLoad: false, securityLevel: 'strict',
                       theme: 'base', useMaxWidth: false,
                       htmlLabels: false, flowchart: {htmlLabels: false},
                       gantt: {useWidth: 760}, c4: {useWidth: 760},
                       xyChart: {useWidth: 760}, requirement: {useWidth: 760},
                       themeVariables: themeVars});
    const rid = 'mv' + seq;
    const cleanup = () => {
      for (const junk of ['d' + rid, rid]) {
        const el = document.getElementById(junk);
        if (el) el.remove();
      }
    };
    mermaid.render(rid, code).then((res) => {
      cleanup();
      if (seq !== renderSeq) return;  // 只采纳最后一次渲染：过期结果不得覆盖 DOM
      wrapper.innerHTML = res.svg;
      // 测量前必须复位变换：getBoundingClientRect 返回 transform 之后的
      // 尺寸，上一张图 fitWidth 留下的 scale 会污染本次测量（实测翻倍）
      scale = 1; tx = 0; ty = 0; apply();
      const svg = wrapper.querySelector('svg');
      if (!svg) {
        window.__uikViewResult = JSON.stringify(
          {ok: false, error: 'mermaid 未产出 SVG 元素'});
        return;
      }
      const r = svg.getBoundingClientRect();
      let w = r.width, h = r.height;
      // width="100%" 的 svg（gantt 等定宽图型）在 shrink-to-fit 的 wrapper
      // 里百分比无法解析，会退化为 300px 默认宽——此时以 viewBox 为准，
      // 再套 mermaid 给出的 max-width（useWidth 上限）
      const widthAttr = svg.getAttribute('width') || '';
      if (widthAttr.endsWith('%') && svg.viewBox && svg.viewBox.baseVal) {
        const vb = svg.viewBox.baseVal;
        if (vb.width > 0 && vb.height > 0) {
          const mw = parseFloat(getComputedStyle(svg).maxWidth);
          w = Math.min(vb.width, isFinite(mw) ? mw : vb.width);
          h = w * vb.height / vb.width;
        }
      }
      if (w <= 0 || h <= 0) {
        window.__uikViewResult = JSON.stringify(
          {ok: false, error: 'mermaid 产出 SVG 尺寸为零'});
        return;
      }
      contentW = Math.ceil(w);
      contentH = Math.ceil(h);
      // 显式宽高，避免 width:100% 的 svg 随 transform 计算异常
      svg.setAttribute('width', contentW);
      svg.setAttribute('height', contentH);
      svg.style.maxWidth = 'none';
      fitWidth();
      window.__uikViewResult = JSON.stringify({ok: true, w: contentW,
                                               h: contentH});
    }).catch((err) => {
      cleanup();
      if (seq === renderSeq) {
        window.__uikViewResult = JSON.stringify(
          {ok: false,
           error: err && err.message ? err.message : String(err)});
      }
    });
  }

  window.__uikViewResult = '';
  const api = {
    zoomIn() {
      interacted = true;
      const r = viewport.getBoundingClientRect();
      zoomAt(r.width / 2, r.height / 2, STEP);
    },
    zoomOut() {
      interacted = true;
      const r = viewport.getBoundingClientRect();
      zoomAt(r.width / 2, r.height / 2, 1 / STEP);
    },
    reset() { fitWidth(); },
    fitWidth() { fitWidth(); },
    // 宿主控件 resize 时调用：仅在用户未手动变换过时重适应宽度
    // （辅助通道；主通道是 window resize 监听，Qt 侧 resizeEvent 触发时
    //   Chromium 视口可能尚未更新，此处量到的可能是旧宽度，幂等无害）
    onHostResize() { if (!interacted) fitWidth(); },
    setTheme(varsJson) {
      themeVars = JSON.parse(varsJson);
      if (code) doRender();
    },
    render(codeJson, varsJson) {
      code = JSON.parse(codeJson);
      themeVars = JSON.parse(varsJson);
      doRender();
    },
    // Qt 侧注入工具条配色（CSS 变量 --uik-tb-*）
    setChrome(varsJson) {
      const v = JSON.parse(varsJson);
      const s = document.documentElement.style;
      s.setProperty('--uik-tb-bg', v.bg);
      s.setProperty('--uik-tb-border', v.border);
      s.setProperty('--uik-tb-text', v.text);
      s.setProperty('--uik-tb-hover', v.hover);
      s.setProperty('--uik-tb-font', v.font);
      s.setProperty('--uik-tb-radius', v.radius);
    },
    // 诊断用：返回当前变换与内容尺寸（JSON 字符串）
    state() {
      return JSON.stringify({scale, tx, ty, contentW, contentH});
    },
  };
  window.__uikViewer = api;

  // ---- 工具条按钮接线（toolbar 是 viewport 的兄弟，不会触发拖动）----
  const wire = (id, fn) => document.getElementById(id)
    .addEventListener('click', (e) => { e.stopPropagation(); fn(); });
  wire('tb-zoom-in', api.zoomIn);
  wire('tb-zoom-out', api.zoomOut);
  wire('tb-reset', api.reset);
  wire('tb-fit', api.fitWidth);
})();
</script></body></html>"""


def _mermaid_style() -> dict:
    """由当前主题令牌生成 Mermaid 渲染样式表（与 MarkdownView 的映射一致）。"""
    return {
        "text": T("color.text.primary"),
        "line": T("color.border.strong"),
        "node_fill": T("color.bg.subtle"),
        "node_border": T("color.border.strong"),
        "label_bg": T("color.bg.base"),
        "font_family": FONT_FAMILY,
    }


def _pt() -> float:
    """Mermaid 渲染字号（与 MarkdownView 一致：正文 0.75 倍）。"""
    return T("font.md") * 0.75


def _chrome_vars() -> dict:
    """由当前主题令牌生成 HTML 工具条配色（注入为 CSS 变量 --uik-tb-*）。"""
    bg = QColor(T("color.bg.elevated"))
    fg = QColor(T("color.text.primary"))
    return {
        "bg": f"rgba({bg.red()},{bg.green()},{bg.blue()},0.86)",
        "border": T("color.border.strong"),
        "text": T("color.text.primary"),
        "hover": f"rgba({fg.red()},{fg.green()},{fg.blue()},0.10)",
        "font": FONT_FAMILY,
        "radius": f"{T('radius.md')}px",
    }


class _Toolbar(QWidget):
    """右上角悬浮工具条：半透明圆角底衬 + 四个小按钮。"""

    def __init__(self, parent: QWidget):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 2, 4, 2)
        layout.setSpacing(2)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)
        self._make_buttons(layout)

    def _make_buttons(self, layout: QHBoxLayout) -> None:
        view = self.parentWidget()
        specs = [
            ("zoom_in", "放大"), ("zoom_out", "缩小"),
            ("reset", "复位"), ("fit", "适应宽度"),
        ]
        for name, tip in specs:
            btn = QPushButton(self)
            set_property(btn, "variant", "text")
            set_property(btn, "size", "sm")
            btn.setToolTip(tip)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            if name == "zoom_in":
                btn.setIcon(get_icon("plus", 14, T("color.text.primary")))
                btn.setText("")
            elif name == "zoom_out":
                btn.setText("−")  # U+2212，极简文字按钮（图标集无 minus）
            elif name == "reset":
                btn.setText("复位")
            else:
                btn.setText("适宽")
            btn.clicked.connect(getattr(view, f"_on_tb_{name}"))
            setattr(self, f"btn_{name}", btn)
            layout.addWidget(btn)
        self.adjustSize()

    def paintEvent(self, event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        bg = QColor(T("color.bg.elevated"))
        bg.setAlpha(220)  # 半透明底衬，不遮死下方图内容
        p.setBrush(bg)
        p.setPen(QColor(T("color.border.strong")))
        p.drawRoundedRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5),
                          T("radius.md"), T("radius.md"))
        p.end()


class _FallbackCanvas(QWidget):
    """WebEngine 不可用时的自绘画布：QImage + 缩放 / 平移变换。

    交互与主路径一致：拖动平移、Ctrl+滚轮以光标为中心缩放、双击复位；
    普通滚轮 ``ignore()`` 自然传播给父级滚动（普通 QWidget 无需转发）。
    """

    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self._img = None          # QImage（DPR=2）
        self._scale = 1.0
        self._offset = QPointF(0, 0)
        self._drag_last = None
        # 用户手动缩放/拖动过后，宿主 resize 不再重适配（与 JS 侧一致）
        self._interacted = False
        self.setMouseTracking(False)
        self.setCursor(Qt.CursorShape.OpenHandCursor)

    # -------------------------------------------------------------- 内容
    def set_image(self, img) -> None:
        self._img = img
        self.fit_width()
        self.update()

    def logical_size(self) -> QSize:
        if self._img is None or self._img.isNull():
            return QSize()
        dpr = self._img.devicePixelRatio() or 1.0
        return QSize(round(self._img.width() / dpr),
                     round(self._img.height() / dpr))

    # -------------------------------------------------------------- 变换
    def fit_width(self) -> None:
        size = self.logical_size()
        if size.width() <= 0 or self.width() <= 0:
            return
        # 放大不设低上限（与 JS 侧 fitWidth 一致，见 _VIEWER_HTML 注释）
        self._scale = min(_MAX_SCALE, self.width() / size.width())
        # 水平居中，顶部对齐（与 JS 侧 fitWidth 一致）
        self._offset = QPointF((self.width() - size.width() * self._scale) / 2,
                               0)
        self._interacted = False  # 复位后回到「随宿主宽度自适应」状态
        self.update()

    def on_host_resize(self) -> None:
        """宿主控件 resize：仅在用户未手动变换过时重适应宽度。"""
        if not self._interacted:
            self.fit_width()

    def _zoom_at(self, center: QPointF, factor: float) -> None:
        ns = min(_MAX_SCALE, max(_MIN_SCALE, self._scale * factor))
        if ns == self._scale:
            return
        k = ns / self._scale
        self._offset = QPointF(center.x() - (center.x() - self._offset.x()) * k,
                               center.y() - (center.y() - self._offset.y()) * k)
        self._scale = ns
        self.update()

    def zoom_in(self) -> None:
        self._interacted = True  # 与 wheelEvent / JS 侧一致：缩放记为用户交互
        self._zoom_at(QPointF(self.width() / 2, self.height() / 2), _ZOOM_STEP)

    def zoom_out(self) -> None:
        self._interacted = True
        self._zoom_at(QPointF(self.width() / 2, self.height() / 2),
                      1 / _ZOOM_STEP)

    # -------------------------------------------------------------- 事件
    def paintEvent(self, event) -> None:  # noqa: N802
        p = QPainter(self)
        if self._img is not None and not self._img.isNull():
            p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
            p.translate(self._offset)
            p.scale(self._scale, self._scale)
            p.drawImage(0, 0, self._img)
        p.end()

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_last = event.position()
            self._interacted = True
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if self._drag_last is not None:
            self._offset += event.position() - self._drag_last
            self._drag_last = event.position()
            self.update()
            event.accept()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_last = None
            self.setCursor(Qt.CursorShape.OpenHandCursor)
            event.accept()

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        self.fit_width()
        event.accept()

    def wheelEvent(self, event: QWheelEvent) -> None:  # noqa: N802
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            factor = _ZOOM_STEP if event.angleDelta().y() > 0 else 1 / _ZOOM_STEP
            self._interacted = True
            self._zoom_at(event.position(), factor)
            event.accept()
        else:
            event.ignore()  # 普通滚轮留给宿主滚动

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        # 宿主（MermaidView）尺寸变化且用户未手动变换过时，重适应宽度
        if self._img is not None:
            self.on_host_resize()


class MermaidView(QWidget):
    """可交互 Mermaid 图查看器：内嵌实时渲染，支持缩放与拖动平移。

    用法::

        view = MermaidView("flowchart TD\\n    A[开始] --> B([结束])\\n")
        view.rendered.connect(lambda: view.resize(
            view.width(), view.natural_size().height()))
        view.render_failed.connect(lambda msg: ...)

    只读属性 ``web_active`` 标识 WebEngine 交互路径是否激活（宿主可据此
    在 ``rendered`` 后把底层静态 PNG 换为透明图，避免双层重影）。
    """

    #: 渲染失败（mermaid 语法错误等），参数为中文错误消息
    render_failed = Signal(str)
    #: 渲染成功（尺寸可能变化，宿主可据此调整高度）
    rendered = Signal()

    def __init__(self, code: str = "", parent: QWidget = None):
        super().__init__(parent)
        self._code = ""
        self._natural = QSize()
        # ---- 内容区：主路径 WebEngine / 降级自绘画布 ----
        self._web = None           # QWebEngineView（主路径）
        self._canvas = None        # _FallbackCanvas（降级路径）
        self._canvas_key = None    # 降级路径当前请求的 hub 缓存键
        self._web_ready = False    # viewer 页面加载完成
        self._pending_render = False  # 页面就绪前收到过渲染请求
        self._poll_timer = None
        self._poll_deadline = 0.0
        self._render_gen = 0   # 渲染代际：set_code 递增，用于丢弃迟到回调
        self._poll_gen = -1    # 本轮轮询启动时的代际快照（-1 = 无有效轮询）
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        # ---- 右上角悬浮工具条（仅降级路径创建；主路径工具条在 HTML 内，
        #      QWebEngineView 原生窗口会压住 alien 兄弟控件导致点不到）----
        self._toolbar = None
        # ---- 主题热切换 ----
        ThemeManager.instance().theme_changed.connect(self._on_theme_changed)
        # ---- 渲染路径选择 ----
        if _webengine_available():
            self._create_web()
        else:
            self._enter_canvas("PySide6 WebEngine 组件不可用")
        if code:
            self.set_code(code)

    # ------------------------------------------------------------- 契约
    def set_code(self, code: str) -> None:
        """设置 Mermaid 源码并重新渲染。"""
        self._code = code
        self._natural = QSize()
        self._render_gen += 1  # 源码变更后，旧渲染的迟到回调一律丢弃
        if self._web is not None:
            if not self._web_ready:
                self._pending_render = True
                return
            self._start_web_render()
        elif self._canvas is not None:
            self._request_canvas_render()

    def code(self) -> str:
        """当前 Mermaid 源码。"""
        return self._code

    def natural_size(self) -> QSize:
        """最近一次渲染的图内容逻辑尺寸（未渲染 / 渲染失败为无效 QSize）。"""
        return self._natural

    @property
    def web_active(self) -> bool:
        """WebEngine 交互路径是否激活（页面就绪为 True；降级画布为 False）。

        宿主（MarkdownView）据此在 ``rendered`` 后把底层静态 PNG 换成
        透明图，消除「PNG 底层 + 透明查看器」叠两层的重影。
        """
        return self._web is not None and self._web_ready

    def reset_view(self) -> None:
        """复位缩放与平移（适应控件宽度）。"""
        if self._web is not None and self._web_ready:
            self._web.page().runJavaScript("window.__uikViewer.reset()")
        elif self._canvas is not None:
            self._canvas.fit_width()

    # ------------------------------------------------------------- 尺寸
    def sizeHint(self) -> QSize:  # noqa: N802
        if self._natural.isValid():
            return self._natural
        return QSize(400, 200)

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._place_toolbar()
        # 用户未手动变换过时，内容跟随宽度重适配
        if self._web is not None and self._web_ready:
            self._web.page().runJavaScript(
                "window.__uikViewer.onHostResize()")

    def _place_toolbar(self) -> None:
        """降级路径的 Qt 工具条悬浮于右上角（与内容边缘留 8px 间距）。"""
        if self._toolbar is not None:
            self._toolbar.move(
                self.width() - self._toolbar.width() - 8, 8)

    # ------------------------------------------------------- 工具条槽
    def _on_tb_zoom_in(self) -> None:
        if self._web is not None and self._web_ready:
            self._web.page().runJavaScript("window.__uikViewer.zoomIn()")
        elif self._canvas is not None:
            self._canvas.zoom_in()

    def _on_tb_zoom_out(self) -> None:
        if self._web is not None and self._web_ready:
            self._web.page().runJavaScript("window.__uikViewer.zoomOut()")
        elif self._canvas is not None:
            self._canvas.zoom_out()

    def _on_tb_reset(self) -> None:
        self.reset_view()

    def _on_tb_fit(self) -> None:
        self.reset_view()

    # ------------------------------------------------------------- 主题
    def _on_theme_changed(self, _mode: str) -> None:
        """主题切换：重算 themeVariables 并重新渲染。"""
        if self._web is not None and self._web_ready:
            self._apply_chrome()  # HTML 工具条配色随令牌刷新（与有无 code 无关）
            if self._code:
                vars_json = json.dumps(
                    _theme_variables(_mermaid_style(), _pt()), ensure_ascii=False)
                self._web.page().runJavaScript(
                    f"window.__uikViewer.setTheme({json.dumps(vars_json)})")
                self._poll_start()
        elif self._canvas is not None and self._code:
            self._request_canvas_render()
        if self._toolbar is not None:
            # 图标颜色随令牌刷新（按钮文字色由全局 QSS 自动处理）
            self._toolbar.btn_zoom_in.setIcon(
                get_icon("plus", 14, T("color.text.primary")))
            self._toolbar.update()

    # ================================================== WebEngine 主路径
    def _create_web(self) -> None:
        try:
            import PySide6.QtWebEngineWidgets  # noqa: F401
            from PySide6.QtWebEngineWidgets import QWebEngineView
        except ImportError:
            self._enter_canvas("PySide6 WebEngine 组件不可用")
            return
        try:
            self._web = QWebEngineView(self)
            # 与 hub 一致的 offscreen/minimal 兜底参数（实机不设，仅当宿主
            # 未显式设置时；--log-level=3 屏蔽 Chromium 噪音日志）
            platform = os.environ.get("QT_QPA_PLATFORM", "").lower()
            if "offscreen" in platform or "minimal" in platform:
                os.environ.setdefault(
                    "QTWEBENGINE_CHROMIUM_FLAGS",
                    "--no-sandbox --disable-gpu --log-level=3")
            # 透明底：图表直接浮在宿主底色上
            self._web.page().setBackgroundColor(
                Qt.GlobalColor.transparent)
            self._web.page().loadFinished.connect(self._on_web_loaded)
            self._web.page().load(QUrl.fromLocalFile(_viewer_file_path()))
            # 普通滚轮吃掉并转发宿主，Ctrl+wheel 放行给 JS 缩放
            self._web.installEventFilter(self)
            self._layout.addWidget(self._web)
            QTimer.singleShot(10000, self._on_web_load_timeout)
        except Exception as exc:
            if self._web is not None:
                self._web.deleteLater()
                self._web = None
            self._enter_canvas(f"WebEngine 视图创建失败: {exc!r}")

    def _on_web_loaded(self, ok: bool) -> None:
        if self._web is None:
            return
        if not ok:
            self._teardown_web()
            self._enter_canvas("WebEngine viewer 页加载失败")
            return
        self._web_ready = True
        self._apply_chrome()  # 页面就绪后先注入工具条配色
        if self._pending_render or self._code:
            self._pending_render = False
            self._start_web_render()

    def _apply_chrome(self) -> None:
        """把工具条配色（CSS 变量）注入 viewer 页面。"""
        if self._web is None or not self._web_ready:
            return
        payload = json.dumps(
            json.dumps(_chrome_vars(), ensure_ascii=False))
        self._web.page().runJavaScript(
            f"window.__uikViewer.setChrome({payload})")

    def _on_web_load_timeout(self) -> None:
        if self._web is not None and not self._web_ready:
            self._teardown_web()
            self._enter_canvas("WebEngine viewer 页加载超时")

    def _teardown_web(self) -> None:
        self._web.removeEventFilter(self)
        self._layout.removeWidget(self._web)
        self._web.deleteLater()
        self._web = None
        self._web_ready = False

    def _start_web_render(self) -> None:
        """把当前源码与主题变量发给 viewer 页面，启动渲染并轮询结果。"""
        if not self._code.strip():
            self._web.page().runJavaScript(
                "document.getElementById('wrapper').innerHTML=''")
            return
        vars_json = json.dumps(
            _theme_variables(_mermaid_style(), _pt()), ensure_ascii=False)
        code_json = json.dumps(self._code, ensure_ascii=False)
        js = (f"window.__uikViewer.render({json.dumps(code_json)},"
              f" {json.dumps(vars_json)})")
        self._web.page().runJavaScript(js)
        self._poll_start()

    # ---- 结果轮询（runJavaScript 不等待 Promise，沿用 hub 的槽位思路）----
    def _poll_start(self) -> None:
        self._poll_deadline = time.time() + _RENDER_TIMEOUT_MS / 1000.0
        self._poll_gen = self._render_gen  # 记录本轮轮询对应的渲染代际
        if self._poll_timer is None:
            self._poll_timer = QTimer(self)
            self._poll_timer.setInterval(_POLL_MS)
            self._poll_timer.timeout.connect(self._poll_once)
        self._poll_timer.start()

    def _poll_once(self) -> None:
        if self._web is None:
            self._poll_timer.stop()
            return
        if time.time() > self._poll_deadline:
            self._poll_timer.stop()
            self._poll_gen = -1  # 令超时前发出的在途回调失配丢弃
            self.render_failed.emit("mermaid 渲染超时")
            return
        gen = self._poll_gen  # 捕获本次请求所属代际，回调里比对
        self._web.page().runJavaScript(
            "(() => { const v = window.__uikViewResult || '';"
            " if (v) window.__uikViewResult = ''; return v; })()",
            lambda raw, g=gen: self._on_poll_result(raw, g))

    def _on_poll_result(self, raw, gen: int = -1) -> None:
        # 迟到回调（超时后 / 源码已变更 / 新一轮轮询已启动）直接丢弃，
        # 不得在 render_failed 之后补发 rendered 或采纳旧尺寸
        if gen != self._poll_gen or gen != self._render_gen:
            return
        if not isinstance(raw, str) or not raw:
            return
        self._poll_timer.stop()
        try:
            result = json.loads(raw)
        except ValueError:
            self.render_failed.emit(f"mermaid 结果反序列化失败: {raw[:200]!r}")
            return
        if result.get("ok"):
            self._natural = QSize(int(result.get("w") or 0),
                                  int(result.get("h") or 0))
            self.updateGeometry()
            self.rendered.emit()
        else:
            self._natural = QSize()
            self.render_failed.emit(
                f"mermaid 渲染失败: {result.get('error') or '未知错误'}")

    # ---- 滚轮放行：普通滚轮转发宿主，Ctrl+wheel 放行 WebEngine ----
    def eventFilter(self, obj, event) -> bool:  # noqa: N802
        if obj is self._web and event.type() == QEvent.Type.Wheel:
            if not (event.modifiers() & Qt.KeyboardModifier.ControlModifier):
                if self._forward_wheel(event):
                    return True  # 已转发宿主：吃掉，不交给 WebEngine（否则页面吃掉滚动）
                return False  # 无滚动区祖先：放行（与降级路径 ignore() 传播一致）
        return False

    def _forward_wheel(self, event: QWheelEvent) -> bool:
        """把普通滚轮事件转发给最近的滚动区祖先（其 viewport）；返回是否已转发。"""
        target = self.parentWidget()
        while (target is not None
               and not isinstance(target, QAbstractScrollArea)):
            target = target.parentWidget()
        if target is None:
            return False
        dest = target.viewport()
        pos = dest.mapFromGlobal(event.globalPosition().toPoint())
        forward = QWheelEvent(
            QPointF(pos), event.globalPosition(), event.pixelDelta(),
            event.angleDelta(), event.buttons(), event.modifiers(),
            event.phase(), event.inverted())
        QCoreApplication.sendEvent(dest, forward)
        return True

    # ==================================================== 降级自绘路径
    def _enter_canvas(self, reason: str) -> None:
        """切换为自绘画布路径（每个实例切换时打印一次提示，经 hub 的降级后端取图）。"""
        if self._canvas is not None:
            return
        print(f"[MermaidView] {reason}，降级为静态图画布（缩放/平移交互一致，"
              f"渲染能力随 MermaidRenderHub 后端）", file=sys.stderr)
        self._canvas = _FallbackCanvas(self)
        self._layout.addWidget(self._canvas)
        # 降级路径没有原生窗口遮挡，用 Qt 自绘工具条
        self._toolbar = _Toolbar(self)
        self._toolbar.raise_()
        self._place_toolbar()
        self._toolbar.show()
        hub = MermaidRenderHub.instance()
        hub.image_ready.connect(self._on_canvas_ready)
        if self._code:
            self._request_canvas_render()

    def _request_canvas_render(self) -> None:
        """经 hub（其自身也处于降级模式时走自绘 worker）异步取图。"""
        hub = MermaidRenderHub.instance()
        style = _mermaid_style()
        pt = _pt()
        key = hub.key_for(self._code, style, pt)
        self._canvas_key = key
        img = hub.get(key)
        if img is not None:
            self._on_canvas_image(key)
            return
        if hub.is_failed(key):
            self._natural = QSize()
            self.render_failed.emit(
                f"mermaid 渲染失败: {hub.last_error(key)}")
            return
        hub.request(key, self._code, style, pt)

    def _on_canvas_ready(self, key: str) -> None:
        """hub 渲染完成广播：只响应本画布当前请求的键（常驻连接）。"""
        if key != self._canvas_key or self._canvas is None:
            return
        hub = MermaidRenderHub.instance()
        img = hub.get(key)
        if img is None:
            self._natural = QSize()
            self.render_failed.emit(
                f"mermaid 渲染失败: {hub.last_error(key) or '未知错误'}")
            return
        self._on_canvas_image(key)

    def _on_canvas_image(self, key: str) -> None:
        img = MermaidRenderHub.instance().get(key)
        if img is None or self._canvas is None:
            return
        self._canvas.set_image(img)
        self._natural = self._canvas.logical_size()
        self.updateGeometry()
        self.rendered.emit()
