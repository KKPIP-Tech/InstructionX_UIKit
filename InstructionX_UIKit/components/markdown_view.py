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
生成样式表并重渲染，无需重启（实测 toHtml 把样式烘入内联 span，
仅换默认样式表无法重着色，必须重渲染）。代码块 / 表格与正文段落
之间带令牌间距（margin）；代码块经单元格表格包裹获得内边距
（Qt 富文本不支持块级 padding，且 ``insertHtml`` 不解析默认样式表，
间距与内边距均以行内属性烘焙，详见 ``_polish_block_spacing``）。

按设计约定不做语法高亮；代码块文字颜色与正文一致
（``color.text.primary``），仅以等宽字族 + ``bg.subtle`` 底色区分。
无内容时在视口中央绘制空占位文本。

**数学公式**：支持 LaTeX 数学公式（``$...$`` 行内、``$$...$$`` /
``\\[...\\]`` / ``\\begin{equation}`` 块级），由 matplotlib mathtext
引擎渲染（依赖例外，见 math_render.py），2x 超采样清晰输出；渲染经
LRU 缓存 + 后台异步执行，流式追加时已渲染公式零开销，未完成的公式
先以源码占位图显示；渲染完成后经 ``QTextDocument.addResource`` 资源
替换**就地更新**（不重解析文档、不触碰流式增量状态，因此与流式追加
任意交错都安全）。主题切换后公式自动按新文本色重绘。

**Mermaid 图表**：闭合的 ```mermaid 代码围栏渲染为图表图片（块级
居中，按视口可用宽度的 80% 适配缩放，视口尺寸变化时自动重适配），
由 ``InstructionX_UIKit.mermaid`` 子包渲染：默认经 QWebEnginePage
执行官方 mermaid.js（项目内唯一破例使用 Web 技术的位置，用户批准），
排版与光栅化都在 Chromium 内完成（SVG → canvas 2x → PNG dataURL →
QImage，透明底），官方全量图型可用且与官方渲染逐像素一致；WebEngine 不可用时自动降级为内置 QPainter 自绘渲染器
（flowchart / sequenceDiagram / pie 子集）。主题令牌着色；与公式
共享同一套 LRU 缓存 + 后台异步渲染 + 就地资源替换管线。流式追加中
未闭合的 mermaid 围栏按普通代码围栏降级显示，闭合后重排为图表；
语法错误时显示失败占位图。

**流式追加（增量渲染）**：逐 token 追加不再全量重解析——纯文本 /
常规 markdown 以 ``QTextCursor`` 增量插入（软换行按 Qt 的空白折叠
表示）；未闭合的代码围栏与块级公式（``$$`` / ``\\[`` / ``\\begin``）
降级显示并缓冲（围栏以等宽代码块风格显示且不显示开行，公式原样
文本显示），闭合后按最终结构重排；缓冲状态异常时回退全量重渲染。
逐 token 追加与一次性 ``set_markdown`` 的最终纯文本渲染逐字符一致；
未闭合围栏内容始终可见（不会因缓冲被吞掉）。已知取舍：跨空行的
同型列表若按流式分块冲刷，列表宽松/紧凑间距可能与一次性渲染略有
差异（纯文本一致）；超长尾段段落的重解析按间隔节流，收尾少数
token 的富样式可能延迟自愈。

已知限制（Qt Markdown 方言为子集）：脚注 / 目录 / 内嵌 HTML 不支持；
网络图片不加载（图片语法降级为占位文本）；代码块无法绘制圆角
（Qt 富文本 CSS 子集不支持 border-radius）；mathtext 为 LaTeX 子集，
不支持 ``\\newcommand`` 宏与外部宏包；Mermaid 的 ``erDiagram``
中文实体名 / 关系标签需加双引号；WebEngine 首次渲染有页面加载
延迟（后续走 LRU 缓存）。
"""

import hashlib
import math
import re

from PySide6.QtCore import QTimer, QUrl, Signal, Qt
from PySide6.QtGui import (
    QColor,
    QDesktopServices,
    QFont,
    QFontMetricsF,
    QImage,
    QPainter,
    QPalette,
    QTextBlockFormat,
    QTextCharFormat,
    QTextCursor,
    QTextDocument,
)
from PySide6.QtWidgets import QTextBrowser

from ..theme import T, ThemeManager, set_property
from ..tokens import FONT_FAMILY, MONO_FAMILY
from .math_render import MathRenderHub

__all__ = ["MarkdownView"]


def _mermaid_hub():
    """惰性导入 Mermaid 渲染中枢（包不存在时降级为不支持）。"""
    try:
        from ..mermaid import MermaidRenderHub
        return MermaidRenderHub.instance()
    except ImportError:
        return None

#: 滚动跟随判定余量（像素）
_SCROLL_MARGIN = 4

#: 行内 Markdown 敏感字符（出现即需重解析以恢复富样式）
_INLINE_SIG = set("*_`~$[]()|\\<>&!")

#: 行首块级标记（标题 / 列表 / 引用 / 分割线等）
_BLOCK_MARK_RE = re.compile(r"^[ \t]*(?:[-+*>]|#{1,6}|\d+[.)])\s")

#: 段落级重解析的规模保护阈值（字符），超过后按间隔节流
_RERENDER_SIZE_LIMIT = 4096
#: 大段落重解析的最小间隔（追加次数）
_RERENDER_MIN_GAP = 4

#: 软换行显示折叠：空格环绕的换行折叠为单个空格（与 Qt Markdown 导入一致，
#: 实测 "x \\ny" / "x\\n  y" 均为 'x y'；制表符不参与折叠）
_DISPLAY_SUB = re.compile(r" *\n *")

#: 构造前缀（可能成为围栏 / 块级公式开启行的行内容）：流式中该行尚未
#: 完整，须保留在缓冲里待扫描器判定，避免把「```」逐字拆进段落
_CONSTRUCT_PREFIX_RE = re.compile(
    r"^(?:`{1,3}|~{1,3}|\${1,2}|\\[A-Za-z]*|\\begin\{[\w*]*)$")


def _display_text(text: str) -> str:
    """源文本 → 增量显示文本（软换行折叠，与 Qt Markdown 导入一致）。"""
    return _DISPLAY_SUB.sub(" ", text).replace("\n", " ")


def _is_paired_closer(line: str, segment: str) -> bool:
    """尾行（构造前缀形态）是否闭合了同段内更早的开启行。

    仅在扫描器已判定整段干净（无未闭合构造）时调用：此时尾行的
    ``` / ~~~ / $$ 若与段内更早的开启行配对，则它是闭合行而非
    新构造的前缀。按行模拟开合状态（围栏 / 块级公式均不嵌套）。
    """
    stripped = line.strip()
    body = segment.rsplit("\n", 1)[0] if "\n" in segment else ""
    if stripped in ("```", "~~~"):
        in_construct = False
        for prev in body.split("\n"):
            if prev.strip().startswith(stripped):
                in_construct = not in_construct
        return in_construct
    if stripped == "$$":
        in_construct = False
        for prev in body.split("\n"):
            if prev.strip() == "$$":
                in_construct = not in_construct
        return in_construct
    return False


def _strip_construct_prefix(commit: str, segment: str = "") -> str:
    """若提交文本的最后一行仍是构造前缀，保留该行在尾缓冲。

    行内容可能在后续追加中成为围栏 / 块级公式开启行（或证伪），
    提前提交会把构造拆散并显示错误；留待行完整后由扫描器判定。
    例外：该行若闭合了同段内更早的开启行，则必须提交——残留会
    在后续追加时被误判为新的开启行，吞掉其后全部内容。
    """
    if commit.endswith("\n"):
        return commit
    line = commit.rsplit("\n", 1)[-1]
    if _CONSTRUCT_PREFIX_RE.match(line):
        if _is_paired_closer(line, segment or commit):
            return commit
        return commit[:-len(line)]
    return commit


def _block_mark_line(text: str) -> bool:
    """text 的最后一行是否匹配行首块级标记（列表 / 引用 / 标题等）。"""
    return bool(_BLOCK_MARK_RE.match(text.rsplit("\n", 1)[-1]))


#: 反斜杠转义（Qt Markdown：\ + ASCII 标点 → 标点本身）
_UNESCAPE_SUB = re.compile(r"\\([!-/:-@\[-`{-~])")


def _unescape_display(text: str) -> str:
    """按 Qt Markdown 的转义语义折叠反斜杠（公式降级显示用）。"""
    return _UNESCAPE_SUB.sub(r"\1", text)


#: <body> 标签（大小写不敏感）
_BODY_TAG_RE = re.compile(r"<body[^>]*>", re.IGNORECASE)


#: 连续 <pre> 行组（Qt 把围栏导出为每行一个 <pre>，行间仅空白分隔）
_PRE_RUN_RE = re.compile(r"(?:<pre\b[^>]*>.*?</pre>\s*)+", re.S)

#: 数据表格标签（Qt 导出的 margin 已烘焙为 0，需按令牌替换）
_TABLE_TAG_RE = re.compile(r"<table\b[^>]*>")


def _polish_block_spacing(html: str) -> str:
    """烘焙代码块与表格的间距 / 内边距（令牌驱动）。

    - 连续 ``<pre>`` 行组包进全宽单元格表格：Qt 富文本 CSS 子集不支持
      块级 padding，QTextBlockFormat 边距会连同背景一起缩进（实测），
      ``td`` 的 padding / background 是唯一可用的内边距手段；包裹后
      代码块在文档结构上等价于单列表格，增量插入走既有表格路径。
    - 数据表格的 ``margin-top/bottom:0px`` 替换为令牌间距。

    所有样式必须以行内属性烘焙进 HTML：``insertHtml`` 导入片段时不解析
    文档默认样式表（实测），类选择器 CSS 仅对 ``setHtml`` 全量路径生效。
    """
    gap = T("space.2")
    pad_v, pad_h = T("space.2"), T("space.3")
    bg = T("color.bg.subtle")

    def _table_tag(m):
        return (m.group(0)
                .replace("margin-top:0px", f"margin-top:{gap}px")
                .replace("margin-bottom:0px", f"margin-bottom:{gap}px"))

    html = _TABLE_TAG_RE.sub(_table_tag, html)
    codeblock_open = (
        f'<table border="0" width="100%" cellspacing="0" cellpadding="0" '
        f'style="margin-top:{gap}px; margin-bottom:{gap}px;">'
        f'<tr><td bgcolor="{bg}" style="padding: {pad_v}px {pad_h}px;">')
    return _PRE_RUN_RE.sub(
        lambda m: codeblock_open + m.group(0).rstrip() + "</td></tr></table>",
        html)


def _insert_fresh_block(cur: QTextCursor) -> None:
    """在光标处另起一个纯文本新块。

    必须显式传默认块格式：无参 ``insertBlock`` 会继承前一块的块格式
    （列表成员 / 标题级别），实测在列表末尾另起段落时新块会被并入
    列表，导致后续文本 / 标题渲染为列表项。
    """
    cur.insertBlock(QTextBlockFormat(), QTextCharFormat())


def _fragment_starts_with_table(html: str) -> bool:
    """片段 HTML 的 body 后首个元素是否为表格。

    表格元素在文档中需要一个前置块：全量渲染中表格紧随段落时共用
    该段落的块，而独立解析的片段会带一个前导空块，插入时需按元素
    类型分别处理（QTextDocument 会把表格前导空块并入表格结构，
    事后删除块会连带删除整行）。
    """
    m = _BODY_TAG_RE.search(html)
    if not m:
        return False
    tail = html[m.end():].lstrip()
    return tail.startswith("<table")


def _scan_inline_math(line: str, maths: list, mark: str) -> str:
    """扫描一行内的行内公式（``$...$`` / ``\\(...\\)`` / 同行 ``$$...$$``）。

    反引号行内代码段原样保留；``\\$`` 视为转义。``$`` 配对遵循 Pandoc
    规则（开 ``$`` 后非空白，闭 ``$`` 前非空白且其后非数字），降低
    货币写法（如「$5 与 $10」）误判率。``mark`` 为实例级占位模板。
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
                result.append(mark.format(len(maths) - 1))
                i = end + 2
                continue
            result.append(c)
            i += 1
            continue
        if line.startswith("$$", i):
            end = line.find("$$", i + 2)
            if end != -1:
                maths.append((line[i + 2:end], True))
                result.append(mark.format(len(maths) - 1))
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
                result.append(mark.format(len(maths) - 1))
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


def _line_opens_construct(stripped: str) -> bool:
    """判断一行（已 strip）是否为围栏 / 块级公式的开启行。"""
    if stripped.startswith(("```", "~~~")):
        return True
    if stripped in ("$$", "\\["):
        return True
    m = re.match(r"\\begin\{(\w+\*?)\}\s*$", stripped)
    return bool(m and m.group(1).rstrip("*") in _MATH_ENVS)


def _pending_info(pend: str):
    """未闭合结构的类型与闭合符（pend 首行为开启行）。"""
    first = pend.split("\n", 1)[0].strip()
    if first.startswith(("```", "~~~")):
        return "fence", first[:3]
    if first == "$$":
        return "math", "$$"
    if first == "\\[":
        return "math", "\\]"
    m = re.match(r"\\begin\{(\w+\*?)\}\s*$", first)
    return "math", "\\end{" + m.group(1) + "}"


def _extract_math(text: str, mark: str, mermaid_mark: str = None):
    """从 Markdown 源文中提取数学公式与 Mermaid 图表并替换为占位标记。

    返回:
        ``(处理后的文本, [(latex, display), ...], [mermaid 源码, ...])``；
        代码围栏内的内容不提取。多行 ``$$`` / ``\\[`` 块与
        ``\\begin{equation}`` 等环境按块级公式处理（align 系列降级：
        去对齐符与换行符）。闭合的 ```mermaid 围栏整体替换为图表占位标记。

    未找到闭合符的块级公式 / Mermaid 围栏**不吞内容**：开启行与中间行
    原样输出（行内公式仍可提取），与流式增量路径的降级显示语义一致。
    """
    maths = []
    diagrams = []
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
            mark3 = stripped[:3]
            if mermaid_mark is not None and stripped[3:].strip().lower() == "mermaid":
                # 闭合的 mermaid 围栏 → 图表占位标记；未闭合则走普通围栏路径
                body = []
                j = i + 1
                while j < len(lines) and not lines[j].strip().startswith(mark3):
                    body.append(lines[j])
                    j += 1
                if j < len(lines):
                    code = "\n".join(body).strip()
                    if code:
                        diagrams.append(code)
                        out.append("")
                        out.append(mermaid_mark.format(len(diagrams) - 1))
                        out.append("")
                    i = j + 1
                    continue
            in_fence = True
            fence_mark = mark3
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
            if i < len(lines):  # 找到闭合行
                i += 1  # 跳过闭合行
                latex = "\n".join(body).strip()
                if closer.startswith("\\end"):
                    latex = latex.replace("&", " ").replace("\\\\", " ")
                if latex:
                    maths.append((latex, True))
                    out.append("")
                    out.append(mark.format(len(maths) - 1))
                    out.append("")
                continue
            # 未闭合：开启行与中间行原样按行处理，不吞后续内容
            out.append(_scan_inline_math(line, maths, mark))
            for b in body:
                out.append(_scan_inline_math(b, maths, mark))
            continue
        out.append(_scan_inline_math(line, maths, mark))
        i += 1
    return "\n".join(out), maths, diagrams


def _para_sig(text: str, prev_src: str) -> bool:
    """文本是否含 Markdown 敏感内容（行内符号或行首块标记）。

    块标记检测覆盖跨分片补全的行（如「1.」分片为 1 / . / 空格时，
    以累计行内容判定）。
    """
    if not _INLINE_SIG.isdisjoint(text):
        return True
    lines = text.split("\n")
    if not prev_src or prev_src.endswith("\n"):
        fresh = lines
    else:
        fresh = lines[1:]
        if _block_mark_line(prev_src + text):
            return True
    return any(_BLOCK_MARK_RE.match(ln) for ln in fresh)


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
        self._pending_math = set()      # 等待异步渲染的公式缓存键
        # 实例级公式占位标记（含内存地址，跨实例零碰撞；结尾字母 q 是
        # 终止符：避免 "…z1" 成为 "…z10" 的前缀导致 replace 误替换）
        self._math_mark = f"uikmath{id(self):x}z{{}}q"
        self._mermaid_mark = f"uikmermaid{id(self):x}z{{}}q"
        self._pending_diagrams = set()  # 等待异步渲染的图表缓存键
        self._diagram_keys = set()      # 文档中全部图表缓存键（resize 重适配用）
        # resize 重适配防抖：拖动缩放期间不逐帧重排
        self._fit_timer = QTimer(self)
        self._fit_timer.setSingleShot(True)
        self._fit_timer.setInterval(120)
        self._fit_timer.timeout.connect(self._refit_diagrams)
        self._reset_incremental()
        set_property(self, "variant", variant)
        self.setOpenLinks(False)
        self.anchorClicked.connect(self._on_anchor_clicked)
        ThemeManager.instance().theme_changed.connect(lambda *_: self._render())
        MathRenderHub.instance().image_ready.connect(self._on_math_ready)
        mermaid_hub = _mermaid_hub()
        if mermaid_hub is not None:
            mermaid_hub.image_ready.connect(self._on_diagram_ready)
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

        增量渲染：逐 token 追加不再全量重解析；未闭合的代码围栏与
        块级公式缓冲（降级显示），闭合后按最终结构重排。逐 token
        追加与一次性 set_markdown 的最终纯文本渲染逐字符一致。
        滚动条在底部时追加后自动跟随；用户上翻后保持阅读位置。
        """
        if not isinstance(chunk, str):
            raise TypeError(f"chunk 应为 str，收到 {type(chunk).__name__}")
        bar = self.verticalScrollBar()
        old_value, old_max = bar.value(), bar.maximum()
        at_bottom = old_value >= old_max - _SCROLL_MARGIN
        self._raw += chunk
        try:
            self._append_incremental(chunk)
        except Exception:
            # 缓冲状态复杂 / 意外异常：回退全量重渲染（重置增量状态）
            self._render()
        if at_bottom:
            bar.setValue(bar.maximum())
        else:
            bar.setValue(min(old_value, bar.maximum()))
        self.viewport().update()

    def clear(self) -> None:
        """清空内容，回到空占位状态。"""
        self._raw = ""
        self._pending_math = set()  # 残留键不再触发无谓重渲染
        self._pending_diagrams = set()
        self._diagram_keys = set()
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
pre {{ font-family: {MONO_FAMILY}; color: {T("color.text.primary")}; }}
blockquote {{ color: {T("color.text.secondary")}; margin-left: {T("space.3")}px; }}
table {{ border: 1px solid {T("color.border")}; }}
td, th {{ border: 1px solid {T("color.border")};
         padding: {T("space.1")}px {T("space.2")}px; }}
a {{ color: {T("color.primary")}; }}
"""

    def _render(self) -> None:
        """全量渲染管线：公式提取 → setMarkdown → toHtml → 公式嵌入 → setHtml。

        渲染前记录滚动位置，重渲染后恢复：原本在底部则跟随到底，
        否则保持原值（钳制到新范围）。任何全量重渲染路径之后重置
        流式增量状态。
        """
        bar = self.verticalScrollBar()
        old_value, old_max = bar.value(), bar.maximum()
        at_bottom = old_value >= old_max - _SCROLL_MARGIN
        doc = self.document()
        doc.setDefaultStyleSheet(self._stylesheet())
        self._pending_math = set()
        self._pending_diagrams = set()
        self._diagram_keys = set()
        if self._raw.strip():
            processed, maths, diagrams = _extract_math(
                self._raw, self._math_mark, self._mermaid_mark)
            doc.setMarkdown(processed)
            html = doc.toHtml()
            if maths:
                html = self._embed_math(doc, html, maths, self._pending_math)
            if diagrams:
                html = self._embed_diagrams(doc, html, diagrams,
                                            self._pending_diagrams)
            doc.setHtml(_polish_block_spacing(html))
        else:
            doc.clear()
        # 链接颜色走调色板（CSS a 选择器对部分 Qt 版本不生效，双保险）
        pal = self.palette()
        pal.setColor(QPalette.Link, QColor(T("color.primary")))
        self.setPalette(pal)
        self._reset_incremental()
        if at_bottom:
            bar.setValue(bar.maximum())
        else:
            bar.setValue(min(old_value, bar.maximum()))
        self.viewport().update()

    @staticmethod
    def _math_url(key: str) -> str:
        """公式缓存键 → 文档资源 URL（键含主题色与字号，天然区分渲染代次）。

        同一公式在同一代次内多次嵌入共享同一 URL（资源去重）；
        异步渲染完成后按 URL 替换资源即可就地更新全部出现位置。
        """
        digest = hashlib.md5(key.encode("utf-8")).hexdigest()
        return f"uik-math://{digest}"

    def _math_placeholder(self, latex: str, display: bool) -> QImage:
        """待渲染公式的源码占位图（等宽字体，观感对齐原 ``<code>`` 占位）。

        2x 超采样 + devicePixelRatio，与正式渲染产物排版尺寸一致。
        """
        text = " ".join(latex.split())
        font = QFont(MONO_FAMILY)
        font.setPointSizeF(T("font.md") * 0.75 * (1.15 if display else 1.0))
        fm = QFontMetricsF(font)
        text = fm.elidedText(text, Qt.ElideMiddle, 480)
        w = max(1, math.ceil(fm.horizontalAdvance(text)))
        h = max(1, math.ceil(fm.height()))
        img = QImage(w * 2, h * 2, QImage.Format_ARGB32_Premultiplied)
        img.fill(Qt.transparent)
        painter = QPainter(img)
        painter.scale(2, 2)
        painter.setFont(font)
        painter.setPen(QColor(T("color.text.secondary")))
        painter.drawText(0, fm.ascent(), text)
        painter.end()
        img.setDevicePixelRatio(2)
        return img

    def _embed_math(self, doc, html: str, maths: list, pending: set,
                    centered_urls: set = None) -> str:
        """把 HTML 中的公式占位标记替换为公式图片。

        命中缓存的公式直接注册渲染产物；未命中的公式先注册源码占位图，
        键加入 ``pending`` 并请求后台异步渲染（失败键的重试节奏由
        MathRenderHub 控制），完成后经资源替换就地更新。
        ``centered_urls`` 非 None 时收集块级公式图片的 URL——
        ``insertHtml`` 会丢失片段的 ``align`` 属性，调用方需在插入后
        用块格式显式居中。
        """
        hub = MathRenderHub.instance()
        color = T("color.text.primary")
        pt = T("font.md") * 0.75  # px → pt（96dpi 下 1pt ≈ 1.333px）
        for i, (latex, display) in enumerate(maths):
            eff_pt = pt * (1.15 if display else 1.0)
            key = hub.key_for(latex, color, eff_pt)
            marker = self._math_mark.format(i)
            url = self._math_url(key)
            img = hub.get(key)
            if img is not None:
                pending.discard(key)
            else:
                pending.add(key)
                hub.request(key, latex, color, eff_pt, display)
                # 渲染中 / 渲染失败：以公式源码占位图显示
                img = self._math_placeholder(latex, display)
            doc.addResource(QTextDocument.ImageResource, QUrl(url), img)
            tag = f'<img src="{url}" />'
            if display and centered_urls is not None:
                centered_urls.add(url)
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
        """后台公式渲染完成：就地替换文档中的占位图资源（不重解析）。

        资源替换 + ``markContentsDirty`` 触发局部重排，文档结构与流式
        增量状态完全不受影响——因此与流式追加任意交错都安全，无需
        全量重渲染。渲染失败（缓存中无图）时保留源码占位图。
        """
        if key not in self._pending_math:
            return
        img = MathRenderHub.instance().get(key)
        if img is None:
            return  # 渲染失败：保留源码占位图
        self._pending_math.discard(key)
        bar = self.verticalScrollBar()
        at_bottom = bar.value() >= bar.maximum() - _SCROLL_MARGIN
        doc = self.document()
        doc.addResource(QTextDocument.ImageResource,
                        QUrl(self._math_url(key)), img)
        doc.markContentsDirty(0, doc.characterCount())
        if at_bottom:
            bar.setValue(bar.maximum())
        self.viewport().update()

    @staticmethod
    def _mermaid_url(key: str) -> str:
        """图表缓存键 → 文档资源 URL（与公式资源 URL 同构、互不相同）。"""
        digest = hashlib.md5(key.encode("utf-8")).hexdigest()
        return f"uik-mermaid://{digest}"

    @staticmethod
    def _mermaid_style() -> dict:
        """由当前主题令牌生成 Mermaid 渲染样式表。"""
        return {
            "text": T("color.text.primary"),
            "line": T("color.border.strong"),
            "node_fill": T("color.bg.subtle"),
            "node_border": T("color.border.strong"),
            "label_bg": T("color.bg.base"),
            "font_family": FONT_FAMILY,
        }

    def _diagram_placeholder(self, failed: bool) -> QImage:
        """待渲染 / 渲染失败的图表占位图（等宽字体，2x 超采样）。"""
        text = "Mermaid 图表渲染中…" if not failed else \
            "Mermaid 图表语法不受支持或渲染失败"
        font = QFont(MONO_FAMILY)
        font.setPointSizeF(T("font.md") * 0.75)
        fm = QFontMetricsF(font)
        w = max(1, math.ceil(fm.horizontalAdvance(text)))
        h = max(1, math.ceil(fm.height()))
        img = QImage(w * 2, h * 2, QImage.Format_ARGB32_Premultiplied)
        img.fill(Qt.transparent)
        painter = QPainter(img)
        painter.scale(2, 2)
        painter.setFont(font)
        painter.setPen(QColor(T("color.text.secondary")))
        painter.drawText(0, fm.ascent(), text)
        painter.end()
        img.setDevicePixelRatio(2)
        return img

    def _diagram_fit(self, img: QImage) -> QImage:
        """图表图片按视口可用宽度的 80% 适配（保持纵横比）。

        1080P 等宽视口下按自然尺寸显示会过小，故统一缩放至视口宽度
        （扣除文档边距）的 80%；源图为 2x 超采样，适度放大仍清晰。
        视口尚未布局（宽度为 0）时返回原图。
        """
        avail = self.viewport().width() - 2 * self.document().documentMargin()
        if avail <= 0:
            return img
        dpr = img.devicePixelRatio() or 1.0
        target = avail * 0.8
        if abs(img.width() / dpr - target) < 1:
            return img
        scaled = img.scaledToWidth(max(1, round(target * dpr)),
                                   Qt.SmoothTransformation)
        scaled.setDevicePixelRatio(dpr)
        return scaled

    def _embed_diagrams(self, doc, html: str, diagrams: list, pending: set,
                        centered_urls: set = None) -> str:
        """把 HTML 中的 Mermaid 占位标记替换为图表图片（块级居中）。

        缓存命中直接注册渲染产物（经 ``_diagram_fit`` 适配宽度）；未命中
        注册占位图并请求后台异步渲染（失败键注册失败占位图，重试节奏由
        MermaidRenderHub 控制）。图表一律按块级居中处理，
        ``centered_urls`` 语义与 ``_embed_math`` 相同。
        """
        hub = _mermaid_hub()
        style = self._mermaid_style()
        pt = T("font.md") * 0.75
        for i, code in enumerate(diagrams):
            marker = self._mermaid_mark.format(i)
            if hub is None:
                img = self._diagram_placeholder(failed=True)
                url = self._mermaid_url(code)
            else:
                key = hub.key_for(code, style, pt)
                url = self._mermaid_url(key)
                self._diagram_keys.add(key)  # resize 时按新宽度重适配
                img = hub.get(key)
                if img is not None:
                    pending.discard(key)
                    img = self._diagram_fit(img)
                else:
                    pending.add(key)
                    hub.request(key, code, style, pt)
                    img = self._diagram_placeholder(failed=hub.is_failed(key))
            doc.addResource(QTextDocument.ImageResource, QUrl(url), img)
            tag = f'<img src="{url}" />'
            if centered_urls is not None:
                centered_urls.add(url)
            html, n = re.subn(
                r"<p[^>]*>\s*" + re.escape(marker) + r"\s*</p>",
                lambda _m: f'<p align="center">{tag}</p>', html)
            if n == 0:
                html = html.replace(marker, tag)
        return html

    def _on_diagram_ready(self, key: str) -> None:
        """后台图表渲染完成：就地替换文档中的占位图资源（不重解析）。

        语义与 ``_on_math_ready`` 完全一致；渲染失败时把占位图替换为
        失败占位图。
        """
        if key not in self._pending_diagrams:
            return
        hub = _mermaid_hub()
        if hub is None:
            return
        img = hub.get(key)
        if img is None and not hub.is_failed(key):
            return  # 理论上不发生：就绪信号时缓存必有图或已标记失败
        self._pending_diagrams.discard(key)
        if img is None:
            img = self._diagram_placeholder(failed=True)
        else:
            img = self._diagram_fit(img)
        bar = self.verticalScrollBar()
        at_bottom = bar.value() >= bar.maximum() - _SCROLL_MARGIN
        doc = self.document()
        doc.addResource(QTextDocument.ImageResource,
                        QUrl(self._mermaid_url(key)), img)
        doc.markContentsDirty(0, doc.characterCount())
        if at_bottom:
            bar.setValue(bar.maximum())
        self.viewport().update()

    def _refit_diagrams(self) -> None:
        """视口宽度变化后，按新宽度重新适配全部图表图片（就地替换资源）。

        源图始终取缓存中的 2x 原图，避免在已缩放产物上反复缩放损失
        清晰度；未完成的键跳过（就绪回调里会按当时宽度适配）。
        """
        if not self._diagram_keys:
            return
        hub = _mermaid_hub()
        if hub is None:
            return
        bar = self.verticalScrollBar()
        at_bottom = bar.value() >= bar.maximum() - _SCROLL_MARGIN
        doc = self.document()
        dirty = False
        for key in self._diagram_keys:
            img = hub.get(key)
            if img is None:
                continue
            doc.addResource(QTextDocument.ImageResource,
                            QUrl(self._mermaid_url(key)),
                            self._diagram_fit(img))
            dirty = True
        if not dirty:
            return
        doc.markContentsDirty(0, doc.characterCount())
        if at_bottom:
            bar.setValue(bar.maximum())
        self.viewport().update()

    def resizeEvent(self, event) -> None:  # noqa: N802
        """视口尺寸变化：防抖后重新适配图表宽度（80% 视口宽度）。"""
        super().resizeEvent(event)
        if self._diagram_keys:
            self._fit_timer.start()

    def _on_anchor_clicked(self, url: QUrl) -> None:
        self.linkActivated.emit(url.toString())
        if self._links_enabled and url.scheme() in ("http", "https"):
            QDesktopServices.openUrl(url)

    # ------------------------------------------------------------ 流式增量渲染
    def _reset_incremental(self) -> None:
        """重置流式增量状态（任何全量重渲染路径之后调用）。"""
        self._tail = ""                 # 未提交的源文本
        self._tail_line0_fresh = False  # 尾缓冲首行是否为全新块行
        self._para_src = ""             # 当前尾段段落已提交的源码
        self._para_mode = "none"        # "none" 块边界 | "open" 段落中
        self._para_dirty = False        # 尾段段落含敏感内容，需重解析
        self._para_rich = False         # 尾段段落最近一次提交为重解析结果
        self._para_trail_space = False  # 尾段段落显示文本以空格结尾
        self._para_pos = 0              # 尾段段落起始文档位置
        self._para_renders = 0          # 距上次段落重解析的追加次数（节流）
        self._pending_type = None       # None | "fence" | "math"（未闭合结构）
        self._pending_src = ""          # 未闭合结构的源码缓冲
        self._pending_pos = 0           # 降级提交起始文档位置（闭合后删除）
        self._pending_first = True      # 首次降级提交（需块设置）
        self._pending_nl_tail = ""      # 围栏降级：待提交的悬空换行
        self._pending_skip_nl = False   # 围栏降级：开启行终止符待跳过
        self._pending_suspend = 0       # 公式降级：待结算的悬空换行数
        self._pending_trail_space = False  # 公式降级：显示文本以空格结尾
        self._pending_mark = ""         # 围栏开行标记（"```" / "~~~"）
        self._pending_closer = ""       # 公式闭合符
        self._pending_line_start = 0    # 闭合检测的增量行起点
        self._scan_reset()

    def _doc_end(self) -> int:
        return self.document().characterCount() - 1

    def _body_format(self) -> QTextCharFormat:
        """正文字符格式（增量纯文本插入用，与样式表正文一致）。"""
        fmt = QTextCharFormat()
        fmt.setFontFamily(FONT_FAMILY)
        fmt.setFontPointSize(T("font.md") * 0.75)  # px → pt
        fmt.setForeground(QColor(T("color.text.primary")))
        return fmt

    def _fence_formats(self):
        """围栏降级显示的字符 / 块格式（等宽 + bg.subtle，对齐 pre 样式）。"""
        fmt = QTextCharFormat()
        fmt.setFontFamily(MONO_FAMILY)
        fmt.setFontPointSize(T("font.md") * 0.75)
        fmt.setForeground(QColor(T("color.text.primary")))
        bfmt = QTextBlockFormat()
        bfmt.setBackground(QColor(T("color.bg.subtle")))
        return fmt, bfmt

    # ------------------------------------------------------------ 扫描（未闭合结构）
    def _scan_tail(self):
        """全量扫描 _tail：返回 (首个未闭合结构起始偏移, 闭合提示符)。

        仅「全新块行」可作为结构起点；_para_mode 非 none 时 tail 首行
        延续已提交段落，不作为块行。闭合判定与 _extract_math 一致。
        """
        tail = self._tail
        if not tail:
            return 0, None
        lines = tail.split("\n")
        offs = [0]
        for ln in lines[:-1]:
            offs.append(offs[-1] + len(ln) + 1)
        i = 1 if (self._para_mode != "none"
                  and not self._tail_line0_fresh) else 0
        while i < len(lines):
            stripped = lines[i].strip()
            if stripped.startswith(("```", "~~~")):
                mark = stripped[:3]
                j = i + 1
                while j < len(lines) and not lines[j].strip().startswith(mark):
                    j += 1
                if j >= len(lines):
                    return offs[i], mark
                i = j + 1
                continue
            if stripped in ("$$", "\\["):
                if i == len(lines) - 1:
                    # 末行尚不完整：可能是多行块开启行，也可能是单行
                    # $$...$$ 的前缀（单行形式由段落重解析处理），
                    # 留待行完整后判定，避免误判为未闭合块吞掉后续内容
                    i += 1
                    continue
                closer = "$$" if stripped == "$$" else "\\]"
                j = i + 1
                while j < len(lines) and lines[j].strip() != closer:
                    j += 1
                if j >= len(lines):
                    return offs[i], closer
                i = j + 1
                continue
            m = re.match(r"\\begin\{(\w+\*?)\}\s*$", stripped)
            if m and m.group(1).rstrip("*") in _MATH_ENVS:
                if i == len(lines) - 1:
                    # 同上：不完整的 \begin{...} 行不做开启判定
                    i += 1
                    continue
                closer = "\\end{" + m.group(1) + "}"
                j = i + 1
                while j < len(lines) and lines[j].strip() != closer:
                    j += 1
                if j >= len(lines):
                    return offs[i], closer
                i = j + 1
                continue
            i += 1
        return len(tail), None

    def _scan_full(self) -> None:
        self._scan_len = len(self._tail)
        self._scan_clean_end, self._scan_hint = self._scan_tail()

    def _scan_reset(self) -> None:
        self._scan_len = -1
        self._scan_clean_end = 0
        self._scan_hint = None

    def _scan_update(self, chunk: str, tail_before: str) -> bool:
        """增量维护扫描缓存：返回 True 表示需要全量重扫。

        - 已有未闭合结构：仅当新内容可能补全闭合行时重扫；
        - 无未闭合结构：仅当新内容可能带来开启行（含跨块补全整行）时重扫。
        """
        if self._scan_hint is not None:
            tail_end = tail_before.rsplit("\n", 1)[-1] if tail_before else ""
            return (tail_end + chunk).find(self._scan_hint) != -1
        lines = chunk.split("\n")
        first_fresh = ((not tail_before)
                       and (self._para_mode == "none"
                            or self._tail_line0_fresh)) \
            or (bool(tail_before) and tail_before.endswith("\n"))
        if first_fresh:
            start = 0
        else:
            start = 1
            base = tail_before.rsplit("\n", 1)[-1]
            if _line_opens_construct((base + lines[0]).strip()):
                return True
        for i in range(start, len(lines)):
            if _line_opens_construct(lines[i].strip()):
                return True
        return False

    # ------------------------------------------------------------ 增量提交
    def _append_incremental(self, chunk: str) -> None:
        """流式增量渲染主路径（未闭合结构缓冲，状态复杂时由调用方回退）。"""
        if self._pending_type is not None:
            self._pending_append(chunk)
            if self._pending_type is not None:
                return
            first_fresh = True  # 闭合后按最终结构重排，触发判定从宽
        else:
            tail_before = self._tail
            self._tail += chunk
            if self._scan_len < 0:
                self._scan_full()
            elif self._scan_update(chunk, tail_before):
                self._scan_full()
            else:
                self._scan_len = len(self._tail)
                if self._scan_hint is None:
                    self._scan_clean_end = len(self._tail)
            first_fresh = ((not tail_before)
                           and (self._para_mode == "none"
                                or self._tail_line0_fresh)) \
                or (bool(tail_before) and tail_before.endswith("\n"))
        if self._scan_clean_end < len(self._tail):
            clean = self._tail[:self._scan_clean_end]
            pend = self._tail[self._scan_clean_end:]
            self._tail = clean
            self._flush_clean()
            # 段落重解析先于未闭合结构降级提交：避免误删降级区域
            self._maybe_rerender(chunk, first_fresh)
            self._para_renders += 1
            leftover = self._tail
            self._tail = ""
            ptype, closer = _pending_info(pend)
            self._enter_pending(pend, ptype, closer, leftover)
        else:
            self._flush_clean()
            self._maybe_rerender(chunk, first_fresh)
            self._para_renders += 1

    def _flush_clean(self) -> None:
        """把 _tail（干净区，无未闭合结构）增量提交到文档末尾。

        尾随换行保留在 _tail 中延迟解析：其含义（软换行 / 空行分隔 /
        块结构起始）取决于后续内容，一次性消费无法保证与全量渲染
        逐字符一致。换行前的尾随空格随换行一并延迟（行尾空白被
        Qt 折叠），段落结束时按全量渲染语义剥离。
        """
        tail = self._tail
        if self._para_mode != "none":
            idx = tail.find("\n\n")
            c0 = tail if idx == -1 else tail[:idx]
            commit = c0.rstrip("\n")
            if idx != -1:
                # 段落结束：行尾空格被折叠，剥离后与全量渲染一致
                commit = commit.rstrip(" ")
            elif c0.endswith("\n"):
                # 末行完整：行尾空格随换行一并延迟
                commit = commit.rstrip(" ")
            else:
                # 中段：构造前缀行延迟（逐字到达的围栏 / 块级公式开行）；
                # 前缀剥离后暴露的换行与空格一并延迟（语义待定）。
                # 仅当末行不完整时才可能是前缀——完整行（如围栏 / 块级
                # 公式的闭合行）内容恰为 ``` 或 $$，剥离会产生幻影开启行；
                # 与同段开启行配对的闭合行同理必须提交
                commit = _strip_construct_prefix(commit, c0)
                if commit.endswith("\n") or c0[len(commit):]:
                    commit = commit.rstrip("\n").rstrip(" ")
            if commit:
                self._commit_paragraph_text(commit)
            tail = c0[len(commit):] + tail[len(c0):]
        idx = tail.rfind("\n\n")
        if idx == -1:
            f, p = "", tail
        else:
            f, p = tail[:idx + 2], tail[idx + 2:]
        if f:
            # 段落收尾：脏段落先按最终结构重排（纯文本提交无法恢复富样式）
            if self._para_dirty and self._para_src:
                self._render_paragraph(keep_trailing=False)
            if f.strip():
                self._insert_parsed(f)
            self._para_mode = "none"
            self._para_src = ""
            self._para_dirty = False
            self._para_rich = False
            self._para_trail_space = False
            self._para_pos = self._doc_end()
        if p:
            commit = p.rstrip("\n")
            if p.endswith("\n"):
                # 末行完整：行尾空格随换行一并延迟；完整行内容恰为
                # ``` 或 $$ 时是构造的闭合行，不可按前缀剥离
                commit = commit.rstrip(" ")
            else:
                # 末行不完整才可能是构造前缀；与同段开启行配对的
                # 闭合行（``` / $$ 等）必须提交，否则残留为幻影开启行
                commit = _strip_construct_prefix(commit, p)
                if commit.endswith("\n") or p[len(commit):]:
                    commit = commit.rstrip("\n").rstrip(" ")
            if commit:
                self._commit_paragraph_text(commit)
            self._tail = p[len(commit):]
        else:
            self._tail = ""
        # 尾缓冲首行是否为全新块行（非空且不以换行开头 = 延迟的构造行）
        self._tail_line0_fresh = bool(self._tail) \
            and not self._tail.startswith("\n")
        self._scan_reset()

    def _commit_paragraph_text(self, text: str) -> None:
        """以正文格式增量插入段落文本（软换行按 Qt 表示折叠为空格）。"""
        if self._para_mode == "none":
            self._para_src = ""
            cur = self.textCursor()
            cur.movePosition(QTextCursor.End)
            if self.document().characterCount() > 1:
                # 仅空文档可直接填充；有内容时必须另起新块（含表格
                # 尾随空块——它属于表格结构，填充会吞掉分隔换行）
                _insert_fresh_block(cur)
            self._para_pos = cur.position()
            self._para_mode = "open"
            self._para_dirty = False
            self._para_rich = False
            self._para_trail_space = False
        prev = self._para_src
        self._para_src += text
        cur = self.textCursor()
        cur.movePosition(QTextCursor.End)
        if text.startswith("\n") and self._para_trail_space:
            # 软换行折叠行尾空格（Qt 导入 "x \ny" → 'x y'）
            cur.deletePreviousChar()
        display = _display_text(text)
        cur.setCharFormat(self._body_format())
        cur.insertText(display)
        self.setTextCursor(cur)
        self._para_trail_space = display.endswith(" ")
        if not self._para_dirty and _para_sig(text, prev):
            self._para_dirty = True
        if self._para_rich and "\n" in text:
            # 重解析后的段落可能含块结构：换行可能改变块归属
            self._para_dirty = True

    def _maybe_rerender(self, chunk: str, first_fresh: bool) -> None:
        """脏段落的重解析触发：闭合符 / 换行 / 行首块标记到达时按需重排。

        大段落按间隔节流（纯文本一致性不受影响，富样式延迟自愈）。
        """
        if not self._para_dirty:
            return
        if _INLINE_SIG.isdisjoint(chunk) and "\n" not in chunk:
            lines = chunk.split("\n")
            fresh = lines if first_fresh else lines[1:]
            if not (any(_BLOCK_MARK_RE.match(ln) for ln in fresh)
                    or _block_mark_line(self._para_src)):
                return
        if (len(self._para_src) > _RERENDER_SIZE_LIMIT
                and 0 < self._para_renders < _RERENDER_MIN_GAP):
            return
        self._para_renders = 0
        self._render_paragraph()

    def _render_paragraph(self, keep_trailing: bool = True) -> None:
        """重解析当前尾段段落（缓冲状态收敛时按最终结构重排）。

        ``keep_trailing`` 为 True 时（中段触发）把源文尾随空格在解析
        后以纯文本补回——Markdown 往返会剥离输入末尾的空白，而中段
        尾随空格属于段落内容，需保持显示；为 False 时（段落收尾）
        按全量渲染语义剥离。
        """
        src = self._para_src
        core = src.rstrip(" ")
        tail_spaces = src[len(core):]
        cur = self.textCursor()
        cur.setPosition(self._para_pos)
        cur.movePosition(QTextCursor.End, QTextCursor.KeepAnchor)
        cur.removeSelectedText()
        html, centered = self._parse_html(core)
        if cur.block().text() == "":
            # 删除后的残留空块仍带旧块格式（列表成员 / 标题级别）：
            # 不重置会让 insertHtml 片段首块并入旧列表，有序列表
            # 编号从 1 重头开始（实测）；重置为默认格式再插入
            cur.setBlockFormat(QTextBlockFormat())
        if _fragment_starts_with_table(html) and self._para_pos > 0:
            # 表格需前置块：纯文本段落删除后残留清空块，移除后使表格
            # 紧接上一块（对齐全量渲染）；若删除的是既有表格，Qt 会连
            # 同前置关系一并移除、光标落入上一块末尾，此时不可再删
            if cur.block().text() == "":
                cur.deletePreviousChar()
        first_block = cur.blockNumber()
        cur.insertHtml(html)
        if centered:
            self._apply_math_alignment(first_block, centered)
        if keep_trailing and tail_spaces:
            cur.movePosition(QTextCursor.End)
            cur.setCharFormat(self._body_format())
            cur.insertText(tail_spaces)
        self.setTextCursor(cur)
        self._para_dirty = False
        self._para_rich = True
        self._para_trail_space = bool(keep_trailing and tail_spaces)

    def _parse_html(self, text: str):
        """文本 → (样式化 HTML, 居中图片 URL 集合)（与全量渲染同管线）。

        居中 URL 集合含块级公式与 Mermaid 图表图片，用于插入后显式
        居中（``insertHtml`` 会丢失片段的 ``align`` 属性）。
        """
        processed, maths, diagrams = _extract_math(
            text, self._math_mark, self._mermaid_mark)
        scratch = QTextDocument()
        scratch.setDefaultStyleSheet(self._stylesheet())
        scratch.setMarkdown(processed)
        html = scratch.toHtml()
        centered = set()
        if maths:
            html = self._embed_math(self.document(), html, maths,
                                    self._pending_math, centered)
        if diagrams:
            html = self._embed_diagrams(self.document(), html, diagrams,
                                        self._pending_diagrams, centered)
        return _polish_block_spacing(html), centered

    def _apply_math_alignment(self, first_block: int, centered: set) -> None:
        """把新插入区域中含块级公式 / 图表图片的段落设为居中。"""
        doc = self.document()
        for n in range(max(0, first_block), doc.blockCount()):
            block = doc.findBlockByNumber(n)
            it = block.begin()
            while not it.atEnd():
                fmt = it.fragment().charFormat()
                if fmt.isImageFormat() and fmt.toImageFormat().name() in centered:
                    cur = QTextCursor(block)
                    bfmt = cur.blockFormat()
                    bfmt.setAlignment(Qt.AlignHCenter)
                    cur.setBlockFormat(bfmt)
                    break
                it += 1

    def _insert_parsed(self, text: str) -> None:
        """把一段自含文本按完整管线解析后插入文档末尾（块级冲刷）。

        表格片段直接插入上一块末尾（表格自带前置块需求，额外
        insertBlock 会留下并入表格结构的空块）；其余片段先建块。
        """
        html, centered = self._parse_html(text)
        cur = self.textCursor()
        cur.movePosition(QTextCursor.End)
        first_block = self.document().blockCount() - 1
        if (not _fragment_starts_with_table(html)
                and self.document().characterCount() > 1):
            _insert_fresh_block(cur)
        cur.insertHtml(html)
        if centered:
            self._apply_math_alignment(first_block, centered)
        self.setTextCursor(cur)

    def _delete_from(self, pos: int) -> None:
        """删除文档中 pos 之后的内容（撤销未闭合结构的降级提交）。"""
        cur = self.textCursor()
        cur.setPosition(pos)
        cur.movePosition(QTextCursor.End, QTextCursor.KeepAnchor)
        cur.removeSelectedText()
        self.setTextCursor(cur)

    # ------------------------------------------------------------ 未闭合结构缓冲
    def _enter_pending(self, pend: str, ptype: str, closer: str,
                       leftover: str) -> None:
        """进入未闭合结构缓冲：降级提交既有内容（闭合后删除并按最终结构重排）。

        - 围栏：开行不显示，内容以等宽 + bg.subtle 块显示；
        - 块级公式：原样文本显示（未闭合语义与一次性渲染一致）。
        ``leftover`` 为干净区冲刷后遗留的尾随换行，公式降级以软换行
        （空格）与上文衔接。
        """
        self._pending_type = ptype
        self._pending_src = pend
        self._pending_pos = self._doc_end()
        self._pending_first = True
        self._pending_nl_tail = ""
        self._pending_suspend = 0
        self._pending_trail_space = False
        if leftover and self._para_mode != "none":
            # 被延迟的行终止符属于段落源（重解析时恢复块结构），
            # 仅显示层不提交
            self._para_src += leftover
        self._para_trail_space = False  # 文档末尾不再是段落末尾
        first_nl = pend.find("\n")
        if ptype == "fence":
            self._pending_mark = closer
            self._pending_line_start = (first_nl + 1) if first_nl != -1 else len(pend)
            # 开启行尚未携带行终止符时，首个到达的换行是开启行的
            # 终止符（不计入围栏内容），须跳过
            self._pending_skip_nl = (first_nl == -1)
            body = pend[first_nl + 1:] if first_nl != -1 else ""
            self._commit_pending_text(body)
        else:
            self._pending_closer = closer
            self._pending_line_start = (first_nl + 1) if first_nl != -1 else len(pend)
            if leftover and self._para_mode != "none":
                self._pending_suspend = 1
            self._commit_pending_text(pend)

    def _pending_append(self, chunk: str) -> None:
        """未闭合结构缓冲期的新增内容：闭合检测 → 闭合后重排 / 降级提交。"""
        self._pending_src += chunk
        if self._pending_close_found():
            self._pending_type = None
            src = self._pending_src
            self._pending_src = ""
            self._delete_from(self._pending_pos)
            self._tail = src
            self._tail_line0_fresh = True  # 构造源码以开启行起始（全新块行）
            self._scan_full()
        else:
            self._commit_pending_text(chunk)

    def _pending_close_found(self) -> bool:
        """增量检查缓冲源码是否已出现闭合行（仅查新增部分，含收尾行）。"""
        src = self._pending_src
        start = self._pending_line_start
        while True:
            nl = src.find("\n", start)
            if nl == -1:
                self._pending_line_start = start
                line = src[start:].strip()
                if self._pending_type == "fence":
                    return line.startswith(self._pending_mark)
                return line == self._pending_closer
            line = src[start:nl].strip()
            if self._pending_type == "fence":
                if line.startswith(self._pending_mark):
                    return True
            elif line == self._pending_closer:
                return True
            start = nl + 1

    def _commit_pending_text(self, text: str) -> None:
        """降级增量提交未闭合结构内容（fence：代码块风格；math：原样文本）。"""
        cur = self.textCursor()
        cur.movePosition(QTextCursor.End)
        if self._pending_type == "fence":
            if self._pending_first and self.document().characterCount() > 1:
                _insert_fresh_block(cur)
            fmt, bfmt = self._fence_formats()
            cur.setCharFormat(fmt)
            cur.setBlockFormat(bfmt)
            if self._pending_skip_nl and text.startswith("\n"):
                text = text[1:]  # 开启行的行终止符不计入内容
                self._pending_skip_nl = False
            # 仅延迟一个尾随换行（行终止符，Qt 导入在输入末尾丢弃）；
            # 更多换行是围栏内的空行，须立即成块（与一次性渲染一致）
            combined = self._pending_nl_tail + text
            if combined.endswith("\n"):
                commit = combined[:-1]
                self._pending_nl_tail = "\n"
            else:
                commit = combined
                self._pending_nl_tail = ""
            if commit:
                cur.insertText(commit)
        else:
            self._commit_math_text(text)
        self.setTextCursor(cur)
        self._pending_first = False

    def _commit_math_text(self, text: str) -> None:
        """块级公式的降级提交：原样文本，换行语义延迟结算。

        尾随换行的含义（软换行 / 空行块断）取决于后续内容，延迟到
        下一次提交结算，保证与一次性渲染的未闭合语义逐字符一致。
        """
        lead = len(text) - len(text.lstrip("\n"))
        body = text[lead:].rstrip("\n")
        tail_nl = len(text[lead:]) - len(body)
        cur = self.textCursor()
        cur.movePosition(QTextCursor.End)
        cur.setCharFormat(self._body_format())
        if body:
            total = min(self._pending_suspend, 2) + (1 if lead else 0)
            if total >= 2:
                if self._pending_trail_space:
                    # 行尾空格在空行分隔前被折叠（Qt 导入剥离行尾空白）
                    cur.deletePreviousChar()
                if self.document().characterCount() > 1:
                    _insert_fresh_block(cur)
            elif total == 1:
                if not self._pending_trail_space:
                    # 行尾空格 + 软换行折叠为单个空格（"x \ny" → 'x y'）
                    cur.insertText(" ")
            elif self._pending_first and self._para_mode == "none":
                if self.document().characterCount() > 1:
                    _insert_fresh_block(cur)
            display = _display_text(_unescape_display(body))
            cur.insertText(display)
            self._pending_trail_space = display.endswith(" ")
        if body:
            self._pending_suspend = min(tail_nl, 2)
        else:
            self._pending_suspend = min(
                self._pending_suspend + (1 if lead else 0), 2)

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
