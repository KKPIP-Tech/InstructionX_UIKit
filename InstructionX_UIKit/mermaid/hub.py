# -*- coding: utf-8 -*-
"""Mermaid 渲染中枢（MermaidRenderHub）：WebEngine + mermaid.js 主渲染，自绘降级。

主渲染路径（SPEC 的禁 WebView/JS 约束经用户显式豁免，**仅限本子包内部**）：

- 隐藏的 ``QWebEnginePage`` 内联加载官方 mermaid.js v10（UMD 构建
  ``mermaid.min.js`` 随包分发），``mermaid.render`` 产出 SVG 并注入页面
  容器，随后在 **Chromium 内部**完成光栅化：SVG 序列化 → Blob URL →
  ``Image`` → 画进 2x ``canvas`` → ``toDataURL('image/png')`` 回传
  base64 PNG，Python 解码为透明底 ``QImage``（DPR=2）。
  排版与光栅化同一引擎，字体度量天然一致——不要改回「导出 SVG 字符串 +
  QSvgRenderer 光栅化」：QSvgRenderer 只实现 SVG Tiny 子集（流式 style、
  裸 ID 选择器、浮点 hsl()、foreignObject 等一串坑），且 Qt 字体度量与
  Chromium 不一致，mermaid 在 Chromium 里量字、Qt 里画字必然错位
  （实机确认过 flowchart 边/箭头/边标签、sequence 生命线/自消息回环、
  gantt 刻度全面错位）；
- WebEngine 渲染必须在 **GUI 线程** 进行：请求进入串行队列，空闲时取一个
  job 调 ``runJavaScript``。注意 Qt 的 ``runJavaScript`` **不等待 Promise
  决议**，且 JS 对象 / null / undefined 均映射为空串，故采用「启动 + 轮询」
  两段式：JS 侧把 ``JSON.stringify`` 的结果写入 ``window.__uikMJobs`` 槽位
  （Promise 决议后连尺寸带 PNG 一并落入），Python 侧每 15ms 轮询取出
  （带超时兜底），回调里 PNG → QImage → 写缓存 → 发射 ``image_ready`` →
  取下一个；
- 隐藏 page 惰性创建（首次请求时）；页面为临时 HTML 文件，经
  ``page.load(file://)`` 加载并引用随包分发的 mermaid.min.js
  （``setHtml`` 有约 2MB 内容上限，无法内联 3.3MB 的 JS）。

降级路径（WebEngine 不可用：ImportError / page 加载失败 / 超时）：

- 打印一次中文 stderr 提示并**永久降级**为 ``render.render_diagram``
  自绘渲染器（纯 QPainter，仅支持 flowchart/sequenceDiagram/pie 子集），
  经 daemon worker 线程渲染（QImage 离线绘制线程安全），语义不变。

公共契约：LRU 缓存 256 条、失败哨兵 + 10s 重试间隔、失败日志按键去重
（sys.stderr 中文）、``aboutToQuit`` 自动关停。全部公开方法须在 GUI 线程调用。
"""

import base64
import json
import os
import queue
import sys
import threading
import time
from collections import OrderedDict, deque

from PySide6.QtCore import (
    QCoreApplication,
    QEventLoop,
    QObject,
    QTimer,
    Signal,
)
from PySide6.QtGui import QImage

from .render import _PIE_COLORS
from .render import render_diagram as _render_fallback

__all__ = ["MermaidRenderHub", "render_diagram"]

#: LRU 缓存容量（条）
_CACHE_CAP = 256
#: 渲染失败后的重试间隔（秒）
_FAIL_RETRY_TTL = 10.0
#: 失败日志去重集合容量上限
_FAIL_LOG_CAP = 256
#: 超采样倍率（高 DPI 清晰度；视图尊重 QImage 的 DPR）
_SS = 2
#: 图表逻辑宽度上限（超出在 canvas 光栅化时等比缩小；视图侧已做宽度适配）
_MAX_WIDTH = 1600.0
#: WebEngine 页面加载 / 单图渲染的超时（毫秒）
_LOAD_TIMEOUT_MS = 10000
_RENDER_TIMEOUT_MS = 15000

#: 渲染失败占位（缓存中区别于 QImage 的哨兵）
_FAILED = object()

#: mermaid.min.js 全文缓存（读一次）
_mermaid_js_cache = None
#: 临时渲染页路径缓存（写一次）
_page_file = None


def _mermaid_js_path() -> str:
    """随包分发的 mermaid.min.js（UMD 构建）绝对路径。"""
    return os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "mermaid.min.js")


def _page_file_path() -> str:
    """隐藏渲染页 HTML 的临时文件路径（写一次后复用）。

    注意：``QWebEnginePage.setHtml`` 有约 2MB 内容上限，mermaid.min.js 约
    3.3MB 无法内联，故改为临时 HTML 文件 + ``page.load(file://)``；
    页面本身为 file:// 源，引用同源的 mermaid.min.js 不受安全策略限制。
    """
    from PySide6.QtCore import QUrl

    global _page_file
    if _page_file is None:
        import tempfile
        directory = os.path.join(tempfile.gettempdir(), "uik_mermaid")
        os.makedirs(directory, exist_ok=True)
        js_url = QUrl.fromLocalFile(_mermaid_js_path()).toString()
        html = ("<!DOCTYPE html><html><head><meta charset=\"utf-8\">"
                "<style>html,body{margin:0;padding:0;background:transparent;}"
                # 隐藏 page 视口为 0x0：gantt 等按容器宽度定宽的图型依赖
                # body 的实际宽度，显式给定避免算出 0 宽
                "body{width:1600px;}</style>"
                f"<script src=\"{js_url}\"></script>"
                "</head><body><div id=\"container\"></div></body></html>")
        _page_file = os.path.join(directory, "render.html")
        with open(_page_file, "w", encoding="utf-8") as f:
            f.write(html)
    return _page_file


def _theme_variables(style: dict, pt: float) -> dict:
    """把 style 字典映射为 mermaid themeVariables（theme: 'base'）。"""
    variables = {
        "background": "transparent",
        "mainBkg": "transparent",
        # 节点底色 / 边框 / 文字
        "primaryColor": style["node_fill"],
        "secondaryColor": style["node_fill"],
        "tertiaryColor": style["node_fill"],
        "primaryBorderColor": style["node_border"],
        "secondaryBorderColor": style["node_border"],
        "tertiaryBorderColor": style["node_border"],
        "primaryTextColor": style["text"],
        "secondaryTextColor": style["text"],
        "tertiaryTextColor": style["text"],
        "textColor": style["text"],
        "titleColor": style["text"],
        "nodeBorder": style["node_border"],
        "clusterBkg": "transparent",
        # 连线与边标签
        "lineColor": style["line"],
        "edgeLabelBackground": style["label_bg"],
        # 字体（pt → px 按 96dpi 换算；font_family 为 QSS 字族串，可直接用于 CSS）
        "fontFamily": style["font_family"],
        "fontSize": f"{pt * 96.0 / 72.0:.1f}px",
        # 时序图
        "actorBkg": style["node_fill"],
        "actorBorder": style["node_border"],
        "actorTextColor": style["text"],
        "signalColor": style["line"],
        "signalTextColor": style["text"],
        "labelBoxBkgColor": style["label_bg"],
        "labelTextColor": style["text"],
        "loopTextColor": style["text"],
        "noteBkgColor": style["label_bg"],
        "noteTextColor": style["text"],
        "noteBorderColor": style["node_border"],
        # 状态图（不显式指定时 stateBkg 回退 mainBkg=transparent，
        # stateLabelColor 再回退 stateBkg，暗色下文字不可读）
        "stateBkg": style["node_fill"],
        "stateBorder": style["node_border"],
        "stateLabelColor": style["text"],
        # ER 图属性行（缺省派生自 background，暗色下会算出近白底色、
        # 亮灰文字不可读；奇偶行统一为节点底色）
        "attributeBackgroundColorOdd": style["node_fill"],
        "attributeBackgroundColorEven": style["node_fill"],
        # mindmap 根节点复用 gitGraph 的 git0 / gitBranchLabel0 变量
        # （缺省派生出 hsl(...) 纯黑，暗色下根圆不可读）
        "git0": style["node_fill"],
        "gitBranchLabel0": style["text"],
        # 甘特图
        "gridColor": style["line"],
        "taskBkgColor": style["node_fill"],
        "taskBorderColor": style["node_border"],
        "taskTextColor": style["text"],
        "taskTextOutsideColor": style["text"],
        # 条内文字颜色（缺省派生的深色在暗色主题下压暗条不可读，
        # 亮/暗两套都显式给主题文本色；darkTextColor 是 base 主题
        # 计算 taskTextDarkColor 缺省值的来源，一并固定）
        "darkTextColor": style["text"],
        "taskTextDarkColor": style["text"],
        "taskTextLightColor": style["text"],
        "sectionBkgColor": "transparent",
        "altSectionBkgColor": "transparent",
        # 饼图文字尺寸（mermaid 默认 25px 标题 / 17px 切片文字，偏大）
        "pieTitleTextSize": f"{pt * 96.0 / 72.0 + 2:.0f}px",
        "pieSectionTextSize": f"{pt * 96.0 / 72.0:.0f}px",
        "pieLegendTextSize": f"{pt * 96.0 / 72.0:.0f}px",
        "pieTitleTextColor": style["text"],
        "pieLegendTextColor": style["text"],
        "pieSectionTextColor": "#ffffff",
        "pieStrokeColor": style["label_bg"],
    }
    # 饼图调色板（沿用自绘后端的 ECharts 风 6 色，mermaid 支持 pie1..pie12）
    for i in range(12):
        variables[f"pie{i + 1}"] = _PIE_COLORS[i % len(_PIE_COLORS)]
        # mindmap 等按 cScale 取色的图型（缺省回退 primaryColor，暗色下会
        # 衍生出纯黑节点）
        variables[f"cScale{i}"] = _PIE_COLORS[i % len(_PIE_COLORS)]
    return variables


def _job_start_js(code: str, style: dict, pt: float) -> str:
    """生成单个渲染 job 的启动 JS：mermaid.render → 注入容器 → canvas 光栅化。

    Qt 的 ``runJavaScript`` 不等待 Promise 决议，且 JS 对象 / null / undefined
    会被映射为空串，因此采用「启动 + 轮询」两段式：本脚本启动渲染并立即返回
    job id；整条 Promise 链（渲染 → 量尺寸 → 2x canvas → PNG dataURL）落定后
    把 ``JSON.stringify`` 的结果写入 ``window.__uikMJobs[jid]``，由 Python 侧
    轮询取出再 ``json.loads``。成功结果为 ``{ok, w, h, png}``（w/h 为逻辑
    px，宽超 ``_MAX_WIDTH`` 时已在 canvas 侧等比缩小）。

    光栅化在 Chromium 内完成（SVG → Blob URL → Image → canvas），排版与
    光栅化同一引擎、字体度量一致；canvas 未绘制区域天然透明。
    失败时清理 mermaid 插入 DOM 的错误元素（``d<id>`` 与 ``<id>``），
    否则影响后续渲染。
    """
    code_json = json.dumps(code, ensure_ascii=False)
    theme_json = json.dumps(_theme_variables(style, pt), ensure_ascii=False)
    return f"""(() => {{
  window.__uikMJobs = window.__uikMJobs || {{}};
  const jid = 'j' + (window.__uikMSeq = (window.__uikMSeq || 0) + 1);
  const done = (obj) => {{ window.__uikMJobs[jid] = JSON.stringify(obj); }};
  const cleanup = () => {{
    for (const junk of ['d' + jid + 'n', jid + 'n']) {{
      const el = document.getElementById(junk);
      if (el) el.remove();
    }}
  }};
  mermaid.initialize({{startOnLoad: false, securityLevel: 'strict',
                     theme: 'base', useMaxWidth: false,
                     // SVG-as-image 对 foreignObject 支持受限，且文字由
                     // Chromium 亲自度量与光栅化，无需 HTML 标签
                     htmlLabels: false, flowchart: {{htmlLabels: false}},
                     // 固定宽度图型按典型内容宽度排版：过宽会被视图侧
                     // 宽度适配缩得过小，文字不可读
                     gantt: {{useWidth: 760}}, c4: {{useWidth: 760}},
                     xyChart: {{useWidth: 760}}, requirement: {{useWidth: 760}},
                     themeVariables: {theme_json}}});
  mermaid.render(jid + 'n', {code_json}).then(res => {{
    cleanup();  // 清掉 mermaid 留在 body 的原始元素，容器内重新注入
    const host = document.getElementById('container');
    host.innerHTML = res.svg;
    const svg = host.querySelector('svg');
    if (!svg) {{ done({{ok: false, error: 'mermaid 未产出 SVG 元素'}}); return; }}
    const r = svg.getBoundingClientRect();
    if (r.width <= 0 || r.height <= 0) {{
      done({{ok: false, error: 'mermaid 产出 SVG 尺寸为零'}}); return;
    }}
    // 宽超上限等比缩小（canvas 侧缩放，报告缩放后的逻辑尺寸）
    const f = Math.min(1.0, {_MAX_WIDTH:.0f} / r.width);
    const w = Math.max(1, Math.ceil(r.width * f));
    const h = Math.max(1, Math.ceil(r.height * f));
    // SVG 作为 Image 载入需显式宽高（部分图型只给 width="100%" + viewBox）
    svg.setAttribute('width', w);
    svg.setAttribute('height', h);
    const xml = new XMLSerializer().serializeToString(svg);
    const blob = new Blob([xml], {{type: 'image/svg+xml;charset=utf-8'}});
    const url = URL.createObjectURL(blob);
    const im = new Image();
    im.onload = () => {{
      const cv = document.createElement('canvas');
      cv.width = w * {_SS}; cv.height = h * {_SS};
      cv.getContext('2d').drawImage(im, 0, 0, cv.width, cv.height);
      URL.revokeObjectURL(url);
      done({{ok: true, w, h, png: cv.toDataURL('image/png')}});
    }};
    im.onerror = () => {{
      URL.revokeObjectURL(url);
      done({{ok: false, error: 'SVG 装入 Image 失败（光栅化中断）'}});
    }};
    im.src = url;
  }}).catch(err => {{
    cleanup();
    done({{ok: false,
      error: err && err.message ? err.message : String(err)}});
  }});
  return jid;
}})()"""


def _job_poll_js(jid: str) -> str:
    """轮询 job 结果（取走即删槽位；未就绪返回空串）。"""
    jid_json = json.dumps(jid)
    return (f"(() => {{ const v = (window.__uikMJobs || {{}})[{jid_json}] || ''; "
            f"if (v) delete window.__uikMJobs[{jid_json}]; return v; }})()")


def _png_to_image(data_url: str, w: int, h: int):
    """canvas ``toDataURL`` 的 PNG dataURL → 透明底 ``QImage``（DPR=2）。"""
    if not data_url.startswith("data:image/png;base64,"):
        return None
    try:
        raw = base64.b64decode(data_url.split(",", 1)[1])
    except ValueError:
        return None
    img = QImage.fromData(raw, "PNG")
    if img.isNull() or img.width() <= 0 or img.height() <= 0:
        return None
    # 以实际像素 / 报告逻辑尺寸定 DPR（正常恰为 2.0，防御取整差异）
    img.setDevicePixelRatio(img.width() / max(1, w))
    return img


class MermaidRenderHub(QObject):
    """Mermaid 渲染中枢（单例）：LRU 缓存 + GUI 线程串行 WebEngine 渲染。

    用法::

        hub = MermaidRenderHub.instance()
        key = MermaidRenderHub.key_for(code, style, pt)
        img = hub.get(key)                    # 命中返回 QImage，未命中返回 None
        if img is None and not hub.is_failed(key):
            hub.request(key, code, style, pt)  # 异步渲染
        hub.image_ready.connect(...)          # 完成后再次 get 即命中
    """

    #: 某键渲染完成并写入缓存后发射（参数为缓存键）
    image_ready = Signal(str)

    #: 降级 worker → GUI 线程的内部传递信号（键, QImage | None）
    _rendered = Signal(str, object)

    _instance = None
    _lock = threading.Lock()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._cache = OrderedDict()      # key -> QImage | _FAILED
        self._failed_ts = {}             # 失败键 -> 时间戳（供有限重试）
        self._errors = {}                # 失败键 -> 错误消息（供同步 API 抛出）
        self._logged_failures = set()    # 已记录异常的键（去重、有界）
        self._pending = set()            # 已入队未完成的 key
        self._jobs = deque()             # 待渲染 job（GUI 线程串行消费）
        self._busy = False               # 是否有 job 正在 WebEngine 中渲染
        self._current = None             # 渲染中的 job（含启动重试计数）
        # ---- WebEngine 状态（惰性）----
        self._page = None
        self._web_ready = False          # 页面加载完成可执行 JS
        self._web_failed = False         # WebEngine 不可用，永久降级
        # ---- 降级 worker（仅在 WebEngine 不可用时启动）----
        self._fb_queue = None
        self._fb_worker = None
        self._rendered.connect(self._on_rendered)
        app = QCoreApplication.instance()
        if app is not None:
            # 应用退出时停止降级 worker，避免退出期 emit 踩已销毁对象
            app.aboutToQuit.connect(self.shutdown)

    @classmethod
    def instance(cls) -> "MermaidRenderHub":
        """返回全局唯一实例（须在 GUI 线程首次调用）。"""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    # ------------------------------------------------------------------ 键
    @staticmethod
    def key_for(code: str, style: dict, pt: float) -> str:
        """计算缓存键（含全部渲染参数：源码、样式、字号）。"""
        style_part = "|".join(f"{k}={style[k]}" for k in sorted(style))
        return f"{pt:.2f}|{style_part}|{code}"

    # ------------------------------------------------------------------ 查询
    def get(self, key: str):
        """查缓存：命中返回 ``QImage``；渲染失败返回 None 且 ``is_failed`` 可查。"""
        if key in self._cache:
            self._cache.move_to_end(key)
            value = self._cache[key]
            return None if value is _FAILED else value
        return None

    def is_failed(self, key: str) -> bool:
        """该键是否已渲染失败（调用方应回退为源码文本显示）。"""
        return self._cache.get(key) is _FAILED

    def last_error(self, key: str) -> str:
        """失败键的错误消息（未知键返回空串）。"""
        return self._errors.get(key, "")

    def clear_cache(self) -> None:
        """清空全部缓存（含失败条目与失败日志去重集合）。

        清空后失败过的图表可立即重新请求渲染（无需等待重试间隔）。
        """
        self._cache.clear()
        self._failed_ts.clear()
        self._errors.clear()
        self._logged_failures.clear()

    # ------------------------------------------------------------------ 请求
    def request(self, key: str, code: str, style: dict, pt: float) -> None:
        """请求渲染（已缓存 / 已入队的请求自动去重）。

        失败条目超过重试间隔后允许重新入队（有限重试）。
        """
        if key in self._cache:
            if self._cache.get(key) is not _FAILED:
                return
            if time.time() - self._failed_ts.get(key, 0.0) < _FAIL_RETRY_TTL:
                return
        if key in self._pending:
            return
        self._pending.add(key)
        self._jobs.append((key, code, dict(style), pt))
        self._pump()

    def shutdown(self, timeout: float = 2.0) -> None:
        """停止降级 worker（哨兵退出 + join 超时；退出前经 aboutToQuit 调用）。

        WebEngine page 由 Qt 随应用退出自行销毁，不做显式 delete
        （offscreen 环境已验证这样退出无崩溃）。
        """
        if self._fb_worker is not None and self._fb_worker.is_alive():
            self._fb_queue.put(None)
            self._fb_worker.join(timeout)

    # ------------------------------------------------------------- 串行泵
    def _pump(self) -> None:
        """空闲且页面就绪时取下一个 job 送 WebEngine。"""
        if self._busy or not self._jobs:
            return
        if self._web_failed:
            self._ensure_fallback_worker()
            while self._jobs:
                self._fb_queue.put(self._jobs.popleft())
            return
        if self._page is None:
            self._create_page()
            return  # 页面加载完成后经 _on_page_loaded 继续泵
        if not self._web_ready:
            return  # 页面仍在加载
        key, code, style, pt = self._jobs.popleft()
        self._busy = True
        self._current = (key, code, style, pt, 0)
        self._start_current()

    def _start_current(self) -> None:
        """启动当前 job（空 job id 时由 ``_begin_poll`` 有限重试回本方法）。"""
        key, code, style, pt, _attempt = self._current
        self._page.runJavaScript(
            _job_start_js(code, style, pt),
            lambda jid, k=key: self._begin_poll(k, str(jid or "")))

    # ------------------------------------------------------------- 轮询
    def _begin_poll(self, key: str, jid: str) -> None:
        """启动后每 15ms 轮询一次 JS 结果槽位（带总超时兜底）。

        页面高负载时 ``runJavaScript`` 偶发返回空 job id（回归 churn 实测），
        属瞬态，重试启动最多 2 次再判失败。
        """
        if not jid:
            k, code, style, pt, attempt = self._current
            if k == key and attempt < 2:
                self._current = (k, code, style, pt, attempt + 1)
                QTimer.singleShot(60, self._start_current)
                return
            self._busy = False
            self._finish_job(key, None, "mermaid job 启动失败（未取得 job id）")
            self._pump()
            return
        self._poll_deadline = time.time() + _RENDER_TIMEOUT_MS / 1000.0
        self._poll_once(key, jid)

    def _poll_once(self, key: str, jid: str) -> None:
        if time.time() > self._poll_deadline:
            self._busy = False
            self._finish_job(key, None, "mermaid 渲染超时")
            self._pump()
            return
        self._page.runJavaScript(
            _job_poll_js(jid),
            lambda raw, k=key, j=jid: self._on_poll(k, j, raw))

    def _on_poll(self, key: str, jid: str, raw) -> None:
        if not isinstance(raw, str) or not raw:
            QTimer.singleShot(15, lambda: self._poll_once(key, jid))
            return
        self._busy = False
        img = None
        error = ""
        try:
            result = json.loads(raw)
        except ValueError:
            result = None
        if isinstance(result, dict) and result.get("ok"):
            try:
                img = _png_to_image(str(result.get("png") or ""),
                                    int(result.get("w") or 0),
                                    int(result.get("h") or 0))
            except Exception as exc:
                error = f"PNG 解码失败: {exc!r}"
        elif isinstance(result, dict):
            error = str(result.get("error") or "未知 mermaid 错误")
        else:
            error = f"mermaid 结果反序列化失败: {raw[:200]!r}"
        if img is None and not error:
            error = "canvas 光栅化失败（PNG 数据无效）"
        self._finish_job(key, img, error)
        self._pump()

    # ------------------------------------------------------------- WebEngine
    def _create_page(self) -> None:
        """惰性创建隐藏渲染页（失败则永久降级）。"""
        try:
            # QtWebEngineWidgets 必须在首个 QWebEnginePage 前导入以完成初始化
            import PySide6.QtWebEngineWidgets  # noqa: F401
            from PySide6.QtWebEngineCore import QWebEnginePage
        except ImportError as exc:
            self._enter_fallback(f"PySide6 WebEngine 组件不可用: {exc!r}")
            return
        # offscreen / 无 GPU 环境下的稳妥参数（仅当宿主未显式设置时）：
        # --no-sandbox 避免某些受限环境沙箱进程创建失败，--disable-gpu 强制
        # 软件渲染，--log-level=3 屏蔽 GPU 初始化失败的 ERROR 刷屏
        # （gpu_channel_manager.cc 的 kFatalFailure 等，软件渲染下无害）
        os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS",
                              "--no-sandbox --disable-gpu --log-level=3")
        try:
            from PySide6.QtCore import QUrl
            self._page = QWebEnginePage(self)
            self._page.loadFinished.connect(self._on_page_loaded)
            self._page.load(QUrl.fromLocalFile(_page_file_path()))
            # 加载超时兜底：超时仍未就绪则降级
            QTimer.singleShot(_LOAD_TIMEOUT_MS, self._on_load_timeout)
        except Exception as exc:
            self._page = None
            self._enter_fallback(f"WebEngine 渲染页创建失败: {exc!r}")

    def _on_page_loaded(self, ok: bool) -> None:
        if self._web_ready or self._web_failed:
            return
        if not ok:
            self._enter_fallback("WebEngine 渲染页加载失败（loadFinished(False)）")
            return
        self._web_ready = True
        self._pump()

    def _on_load_timeout(self) -> None:
        if self._page is not None and not self._web_ready and not self._web_failed:
            self._enter_fallback("WebEngine 渲染页加载超时")

    # ------------------------------------------------------------- 降级路径
    def _enter_fallback(self, reason: str) -> None:
        """永久降级为自绘渲染器（提示只打印一次）。"""
        if self._web_failed:
            return
        self._web_failed = True
        self._web_ready = False
        if self._page is not None:
            self._page.deleteLater()
            self._page = None
        print(f"[MermaidRenderHub] {reason}，降级为内置自绘渲染器"
              f"（仅支持 flowchart/sequenceDiagram/pie 子集）", file=sys.stderr)
        self._ensure_fallback_worker()
        while self._jobs:
            self._fb_queue.put(self._jobs.popleft())

    def _ensure_fallback_worker(self) -> None:
        if self._fb_worker is not None:
            return
        self._fb_queue = queue.Queue()
        self._fb_worker = threading.Thread(target=self._fb_worker_loop,
                                           name="uik-mermaid-render", daemon=True)
        self._fb_worker.start()

    def _fb_worker_loop(self) -> None:
        while True:
            item = self._fb_queue.get()
            if item is None:  # 退出哨兵
                break
            key, code, style, pt = item
            try:
                img = _render_fallback(code, style, pt)
                error = ""
            except Exception as exc:
                img = None
                error = str(exc)
                self._log_failure(key, error)
            try:
                self._rendered.emit(key, (img, error))
            except RuntimeError:
                return  # 应用退出期：接收端（GUI 对象）已销毁

    def _on_rendered(self, key: str, payload) -> None:
        """GUI 线程：降级 worker 结果写缓存并广播完成信号。"""
        img, error = payload
        self._finish_job(key, img, error)

    # ------------------------------------------------------------- 公共收尾
    def _finish_job(self, key: str, img, error: str) -> None:
        self._pending.discard(key)
        if isinstance(img, QImage) and not img.isNull():
            self._cache[key] = img
        else:
            self._cache[key] = _FAILED
            self._failed_ts[key] = time.time()
            self._errors[key] = error
            self._log_failure(key, error)
        while len(self._cache) > _CACHE_CAP:
            self._cache.popitem(last=False)
        try:
            self.image_ready.emit(key)
        except RuntimeError:
            pass  # 应用退出期：接收端已销毁

    def _log_failure(self, key: str, error: str) -> None:
        """渲染异常记录一次（按键去重，sys.stderr）。"""
        if key in self._logged_failures:
            return
        self._logged_failures.add(key)
        while len(self._logged_failures) > _FAIL_LOG_CAP:
            self._logged_failures.pop()
        print(f"[MermaidRenderHub] 图表渲染失败（回退为源码占位）: "
              f"key={key!r} error={error}", file=sys.stderr)

    # ------------------------------------------------------------- 同步 API
    def render_sync(self, code: str, style: dict, pt: float):
        """同步渲染（探针 / 测试用）：复用串行队列，局部事件循环等待结果。

        :raises ValueError: 渲染失败或超时（中文 / mermaid 错误消息）
        """
        key = self.key_for(code, style, pt)
        hit = self.get(key)
        if hit is not None:
            return hit
        loop = QEventLoop()

        def on_ready(k: str) -> None:
            if k == key:
                loop.quit()

        self.image_ready.connect(on_ready)
        try:
            self.request(key, code, style, pt)
            QTimer.singleShot(_RENDER_TIMEOUT_MS, loop.quit)
            loop.exec()
        finally:
            self.image_ready.disconnect(on_ready)
        img = self.get(key)
        if img is None:
            detail = self._errors.get(key) or "渲染超时或事件循环异常退出"
            raise ValueError(f"mermaid 渲染失败: {detail}")
        return img


def render_diagram(code: str, style: dict, pt: float) -> QImage:
    """同步渲染一张 Mermaid 图为透明底 ``QImage``（2x 超采样，DPR=2）。

    WebEngine 可用时经官方 mermaid.js 渲染（支持全部图型），
    不可用时自动降级为 ``render.render_diagram`` 自绘子集渲染。
    供探针 / 测试使用；视图侧请走 ``MermaidRenderHub`` 异步路径。

    :raises ValueError: 解析失败或不支持的语法（中文 / mermaid 错误消息）
    """
    return MermaidRenderHub.instance().render_sync(code, style, pt)
