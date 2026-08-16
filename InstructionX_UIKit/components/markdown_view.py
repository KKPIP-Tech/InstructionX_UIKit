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

按设计约定不做语法高亮（依赖禁令下无法引入 Pygments 等第三方库）；
代码块文字颜色与正文一致（``color.text.primary``），仅以等宽字族 +
``bg.subtle`` 底色区分。无内容时在视口中央绘制空占位文本。

已知限制（Qt Markdown 方言为子集）：脚注 / 目录 / 内嵌 HTML 不支持；
网络图片不加载（图片语法降级为占位文本）；代码块无法绘制圆角
（Qt 富文本 CSS 子集不支持 border-radius）。
"""

from PySide6.QtCore import QUrl, Signal, Qt
from PySide6.QtGui import QColor, QDesktopServices, QPainter, QPalette
from PySide6.QtWidgets import QTextBrowser

from ..theme import T, ThemeManager, set_property
from ..tokens import FONT_FAMILY, MONO_FAMILY

__all__ = ["MarkdownView"]


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
        set_property(self, "variant", variant)
        self.setOpenLinks(False)
        self.anchorClicked.connect(self._on_anchor_clicked)
        ThemeManager.instance().theme_changed.connect(lambda *_: self._render())
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
        """渲染管线：setMarkdown → toHtml → setHtml（让令牌 CSS 生效）。

        Qt 的 Markdown 导入不应用文档默认样式表，必须先导出 HTML 再以
        HTML 方式重新导入。会话级文档体积小，全量重渲染开销可忽略。
        """
        bar = self.verticalScrollBar()
        at_bottom = bar.value() >= bar.maximum() - 4
        doc = self.document()
        doc.setDefaultStyleSheet(self._stylesheet())
        if self._raw.strip():
            doc.setMarkdown(self._raw)
            doc.setHtml(doc.toHtml())
        else:
            doc.clear()
        # 链接颜色走调色板（CSS a 选择器对部分 Qt 版本不生效，双保险）
        pal = self.palette()
        pal.setColor(QPalette.Link, QColor(T("color.primary")))
        self.setPalette(pal)
        if at_bottom:
            bar.setValue(bar.maximum())
        self.viewport().update()

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
