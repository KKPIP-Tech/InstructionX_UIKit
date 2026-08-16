# -*- coding: utf-8 -*-
"""Markdown 渲染组件（SPEC §5.2 markdown_view）。

``MarkdownView`` 基于 QTextBrowser，使用 Qt 内置 Markdown 引擎
（``QTextDocument.setMarkdown``，CommonMark + 部分 GFM：表格 / 任务列表 /
删除线 / 代码围栏）原生渲染 Markdown 文本，并针对 AI 对话场景提供
``append_markdown`` 流式追加。

样式全面令牌化：Qt 的 Markdown 导入不应用文档默认样式表（实测），
因此组件采用「setMarkdown → toHtml → setHtml」管线，让由令牌生成的
CSS 生效（正文字族 / 字阶 / 颜色、标题字阶、代码块 ``bg.subtle`` 底色
+ ``MONO_FAMILY``、表格边框、链接 ``color.primary``）。主题切换时重新
生成样式表并重渲染，无需重启。

按设计约定不做语法高亮；代码块文字颜色与正文一致
（``color.text.primary``），仅以等宽字族 + ``bg.subtle`` 底色区分。
无内容时在视口中央绘制空占位文本。

**数学公式**：支持 LaTeX 数学公式（``$...$`` 行内、``$$...$$`` /
``\\[...\\]`` / ``\\begin{equation}`` 块级），由 matplotlib mathtext
引擎渲染（依赖例外，见 math_render.py），2x 超采样清晰输出；渲染经
LRU 缓存 + 后台异步执行，流式追加时已渲染公式零开销，未完成的公式
先以源码占位、渲染完成后自动替换。主题切换后公式自动按新文本色重绘。

已知限制（Qt Markdown 方言为子集）：脚注 / 目录 / 内嵌 HTML 不支持；
网络图片不加载（图片语法降级为占位文本）；代码块无法绘制圆角
（Qt 富文本 CSS 子集不支持 border-radius）；mathtext 为 LaTeX 子集，
不支持 ``\\newcommand`` 宏与外部宏包。
"""

import re
from html import escape as _html_escape

from PySide6.QtCore import QUrl, Signal, Qt
from PySide6.QtGui import QColor, QDesktopServices, QPainter, QPalette, QTextDocument
from PySide6.QtWidgets import QTextBrowser

from ..theme import T, ThemeManager, set_property
from ..tokens import FONT_FAMILY, MONO_FAMILY
from .math_render import MathRenderHub

__all__ = ["MarkdownView"]

#: 公式占位标记（纯字母数字，可安全穿过 Markdown → HTML 管线）
_MATH_MARK = "uikmathmark{}z"


def _scan_inline_math(line: str, maths: list) -> str:
    """扫描一行内的行内公式（``$...$`` / ``\\(...\\)`` / 同行 ``$$...$$``）。

    反引号行内代码段原样保留；``\\$`` 视为转义。``$`` 配对遵循 Pandoc
    规则（开 ``$`` 后非空白，闭 ``$`` 前非空白且其后非数字），降低
    货币写法（如「$5 与 $10」）误判率。
    """
    result = []
    i, n = 0, len(line)
    while i < n:
        c = line[i]
        if c == "`":
            j = i
            while j < n and line[j] == "`":
                j += 1
            ticks = line[i:j]
            end = line.find(ticks, j)
            if end == -1:
                result.append(line[i:])
                return "".join(result)
            result.append(line[i:end + len(ticks)])
            i = end + len(ticks)
            continue
        if c == "\\" and i + 1 < n and line[i + 1] == "$":
            result.append("\\$")
            i += 2
            continue
        if c == "\\" and i + 1 < n and line[i + 1] in "([":
            close = "\\)" if line[i + 1] == "(" else "\\]"
            end = line.find(close, i + 2)
            if end != -1:
                maths.append((line[i + 2:end], close == "\\]"))
                result.append(_MATH_MARK.format(len(maths) - 1))
                i = end + 2
                continue
            result.append(c)
            i += 1
            continue
        if line.startswith("$$", i):
            end = line.find("$$", i + 2)
            if end != -1:
                maths.append((line[i + 2:end], True))
                result.append(_MATH_MARK.format(len(maths) - 1))
                i = end + 2
                continue
            result.append("$$")
            i += 2
            continue
        if c == "$" and i + 1 < n and not line[i + 1].isspace():
            matched = False
            j = i + 1
            while True:
                end = line.find("$", j)
                if end == -1:
                    break
                if line[end - 1].isspace() or (end + 1 < n and line[end + 1].isdigit()):
                    j = end + 1
                    continue
                maths.append((line[i + 1:end], False))
                result.append(_MATH_MARK.format(len(maths) - 1))
                i = end + 1
                matched = True
                break
            if matched:
                continue
            result.append("$")
            i += 1
            continue
        result.append(c)
        i += 1
    return "".join(result)


#: 多行块级公式环境（\begin{...} 形式，星号变体同支持）
_MATH_ENVS = ("equation", "align", "gather", "multline", "displaymath", "math")


def _extract_math(text: str):
    """从 Markdown 源文中提取数学公式并替换为占位标记。

    返回:
        ``(处理后的文本, [(latex, display), ...])``；代码围栏内的内容
        不提取。多行 ``$$`` / ``\\[`` 块与 ``\\begin{equation}`` 等环境
        按块级公式处理（align 系列降级：去对齐符与换行符）。
    """
    maths = []
    lines = text.split("\n")
    out = []
    in_fence = False
    fence_mark = ""
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        if in_fence:
            out.append(line)
            if stripped.startswith(fence_mark):
                in_fence = False
            i += 1
            continue
        if stripped.startswith("```") or stripped.startswith("~~~"):
            in_fence = True
            fence_mark = stripped[:3]
            out.append(line)
            i += 1
            continue
        # 多行块级公式入口
        closer = None
        env_m = re.match(r"\\begin\{(\w+\*?)\}\s*$", stripped)
        if stripped in ("$$", "\\["):
            closer = stripped if stripped == "$$" else "\\]"
        elif env_m and env_m.group(1).rstrip("*") in _MATH_ENVS:
            closer = "\\end{" + env_m.group(1) + "}"
        if closer is not None:
            body = []
            i += 1
            while i < len(lines) and lines[i].strip() != closer:
                body.append(lines[i])
                i += 1
            i += 1  # 跳过闭合行
            latex = "\n".join(body).strip()
            if closer.startswith("\\end"):
                latex = latex.replace("&", " ").replace("\\\\", " ")
            if latex:
                maths.append((latex, True))
                out.append("")
                out.append(_MATH_MARK.format(len(maths) - 1))
                out.append("")
            continue
        out.append(_scan_inline_math(line, maths))
        i += 1
    return "\n".join(out), maths


class MarkdownView(QTextBrowser):
    """Markdown 富文本渲染视图。

    用途:
        原生渲染 Markdown 文本（标题 / 列表 / 代码块 / 表格 / 引用 /
        链接等），支持流式追加，适配 AI 人机对话场景。

    参数:
        markdown: 初始 Markdown 文本，空字符串显示空占位。
        variant: ``"card"``（默认，继承全局 QSS 卡片边框）或
            ``"plain"``（透明无边框，嵌入气泡 / 列表时使用）。
        parent: 父控件。

    信号:
        linkActivated(str): 点击链接时发射（url 字符串）。

    示例::

        view = MarkdownView("# 你好\\n\\n**加粗** 与 `代码`")
        view.append_markdown("\\n\\n- 流式追加的一项")
        view.linkActivated.connect(print)
    """

    #: 点击链接时发射（url 字符串）
    linkActivated = Signal(str)

    _VARIANTS = ("card", "plain")

    def __init__(self, markdown: str = "", variant: str = "card", parent=None):
        super().__init__(parent)
        if variant not in self._VARIANTS:
            raise ValueError(f"未知 MarkdownView 变体: {variant!r}，应为 {self._VARIANTS} 之一")
        self._raw = ""
        self._links_enabled = True
        self._empty_text = "暂无内容"
        self._render_seq = 0            # 渲染代次（公式资源 URL 命名空间）
        self._pending_math = set()      # 等待异步渲染的公式缓存键
        set_property(self, "variant", variant)
        self.setOpenLinks(False)
        self.anchorClicked.connect(self._on_anchor_clicked)
        ThemeManager.instance().theme_changed.connect(lambda *_: self._render())
        MathRenderHub.instance().image_ready.connect(self._on_math_ready)
        if markdown:
            self.set_markdown(markdown)

    # ------------------------------------------------------------------ 内容
    def set_markdown(self, markdown: str) -> None:
        """全量替换 Markdown 内容并重新渲染。"""
        if not isinstance(markdown, str):
            raise TypeError(f"markdown 应为 str，收到 {type(markdown).__name__}")
        self._raw = markdown
        self._render()

    def append_markdown(self, chunk: str) -> None:
        """流式追加 Markdown 片段（AI 逐 token 输出场景）。

        滚动条在底部时追加后自动跟随；用户上翻后不打断阅读位置。
        """
        if not isinstance(chunk, str):
            raise TypeError(f"chunk 应为 str，收到 {type(chunk).__name__}")
        self._raw += chunk
        self._render()

    def clear(self) -> None:
        """清空内容，回到空占位状态。"""
        self._raw = ""
        self._render()

    def markdown(self) -> str:
        """当前 Markdown 源文本。"""
        return self._raw

    # ------------------------------------------------------------------ 配置
    def set_links_enabled(self, enabled: bool) -> None:
        """设置点击链接是否用系统浏览器打开（http/https）。"""
        self._links_enabled = bool(enabled)

    def links_enabled(self) -> bool:
        return self._links_enabled

    def set_empty_text(self, text: str) -> None:
        """设置空状态占位文本。"""
        self._empty_text = str(text)
        self.viewport().update()

    def empty_text(self) -> str:
        return self._empty_text

    # ------------------------------------------------------------------ 渲染
    def _stylesheet(self) -> str:
        """由当前主题令牌生成文档 CSS。"""
        return f"""
body {{ font-family: {FONT_FAMILY}; font-size: {T("font.md")}px;
       color: {T("color.text.primary")}; }}
h1 {{ font-size: {T("font.title.lg")}px; font-weight: 600; color: {T("color.text.primary")}; }}
h2 {{ font-size: {T("font.title.md")}px; font-weight: 600; color: {T("color.text.primary")}; }}
h3 {{ font-size: {T("font.title.sm")}px; font-weight: 600; color: {T("color.text.primary")}; }}
h4, h5, h6 {{ font-size: {T("font.lg")}px; font-weight: 600; color: {T("color.text.primary")}; }}
code {{ font-family: {MONO_FAMILY}; color: {T("color.text.primary")}; }}
pre {{ font-family: {MONO_FAMILY}; color: {T("color.text.primary")};
      background-color: {T("color.bg.subtle")}; }}
blockquote {{ color: {T("color.text.secondary")}; margin-left: {T("space.3")}px; }}
table {{ border: 1px solid {T("color.border")}; }}
td, th {{ border: 1px solid {T("color.border")};
         padding: {T("space.1")}px {T("space.2")}px; }}
a {{ color: {T("color.primary")}; }}
"""

    def _render(self) -> None:
        """渲染管线：公式提取 → setMarkdown → toHtml → 公式嵌入 → setHtml。

        Qt 的 Markdown 导入不应用文档默认样式表，必须先导出 HTML 再以
        HTML 方式重新导入。公式经 MathRenderHub 异步渲染 + LRU 缓存：
        命中缓存直接嵌入图片；未命中先以源码占位并入队后台渲染，
        完成后经 image_ready 信号触发本方法重排。
        """
        bar = self.verticalScrollBar()
        at_bottom = bar.value() >= bar.maximum() - 4
        doc = self.document()
        doc.setDefaultStyleSheet(self._stylesheet())
        if self._raw.strip():
            processed, maths = _extract_math(self._raw)
            doc.setMarkdown(processed)
            html = doc.toHtml()
            if maths:
                html = self._embed_math(doc, html, maths)
            doc.setHtml(html)
        else:
            doc.clear()
        # 链接颜色走调色板（CSS a 选择器对部分 Qt 版本不生效，双保险）
        pal = self.palette()
        pal.setColor(QPalette.Link, QColor(T("color.primary")))
        self.setPalette(pal)
        if at_bottom:
            bar.setValue(bar.maximum())
        self.viewport().update()

    def _embed_math(self, doc, html: str, maths: list) -> str:
        """把 HTML 中的公式占位标记替换为渲染图片（或源码占位）。

        命中缓存的公式注册为文档资源并生成 ``<img>``；未命中的公式
        以 ``<code>`` 源码占位并请求后台异步渲染。
        """
        hub = MathRenderHub.instance()
        color = T("color.text.primary")
        pt = T("font.md") * 0.75  # px → pt（96dpi 下 1pt ≈ 1.333px）
        self._render_seq += 1
        self._pending_math = set()
        for i, (latex, display) in enumerate(maths):
            eff_pt = pt * (1.15 if display else 1.0)
            key = hub.key_for(latex, color, eff_pt)
            marker = _MATH_MARK.format(i)
            img = hub.get(key)
            if img is not None:
                url = f"uik-math://{self._render_seq}/{i}"
                doc.addResource(QTextDocument.ImageResource, QUrl(url), img)
                tag = f'<img src="{url}" />'
            else:
                if not hub.is_failed(key):
                    self._pending_math.add(key)
                    hub.request(key, latex, color, eff_pt, display)
                # 渲染中 / 渲染失败：以公式源码占位（等宽样式）
                tag = f"<code>{_html_escape(latex)}</code>"
            if display:
                # 独占段落的块级公式居中
                html, n = re.subn(
                    r"<p[^>]*>\s*" + re.escape(marker) + r"\s*</p>",
                    lambda _m: f'<p align="center">{tag}</p>', html)
                if n == 0:
                    html = html.replace(marker, tag)
            else:
                html = html.replace(marker, tag)
        return html

    def _on_math_ready(self, key: str) -> None:
        """后台公式渲染完成：若属于本视图待渲染集合则重排。"""
        if key in self._pending_math:
            self._render()

    def _on_anchor_clicked(self, url: QUrl) -> None:
        self.linkActivated.emit(url.toString())
        if self._links_enabled and url.scheme() in ("http", "https"):
            QDesktopServices.openUrl(url)

    # ------------------------------------------------------------------ 空态
    def paintEvent(self, event) -> None:  # noqa: N802
        super().paintEvent(event)
        if self._raw.strip():
            return
        painter = QPainter(self.viewport())
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(QColor(T("color.text.tertiary")))
        font = painter.font()
        font.setPixelSize(T("font.md"))
        painter.setFont(font)
        painter.drawText(self.viewport().rect(), Qt.AlignCenter, self._empty_text)
        painter.end()
