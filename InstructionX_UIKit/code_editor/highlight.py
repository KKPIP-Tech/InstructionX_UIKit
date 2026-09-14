# -*- coding: utf-8 -*-
"""语法高亮基座（CE_SPEC §3）。

对外契约：

- ``HighlightRule``：单条高亮规则（正则 → scope 名）；``end_pattern`` 非空
  时表示多行规则（块注释 / 三引号字符串等），由状态机跨块跟踪。
- ``HighlightEngine``：``QSyntaxHighlighter`` 子类，持有
  ``scopes: dict[str, QTextCharFormat]``，主题切换时自动重建并重刷。
- ``SYNTAX_LIGHT`` / ``SYNTAX_DARK``：tokens 派生的低饱和语法色板
  （亮 / 暗各一套，>= 12 个 scope）。
- ``register_language(name, engine_factory, extensions)`` / 
  ``language_for_file(filename)`` / ``create_engine(document, language)``：
  语言注册表。内置 ``"plain"`` 语言（无高亮）；E2 的 languages.py 通过
  ``register_language`` 补充更多语言。

``engine_factory`` 约定：``factory(document) -> HighlightEngine | None``，
返回 ``None`` 表示该语言无语法高亮（如 plain）。
"""

import re

from PySide6.QtCore import QRegularExpression
from PySide6.QtGui import QColor, QFont, QSyntaxHighlighter, QTextCharFormat

from ..theme import ThemeManager

__all__ = [
    "HighlightRule",
    "HighlightEngine",
    "SYNTAX_LIGHT",
    "SYNTAX_DARK",
    "syntax_palette",
    "register_language",
    "unregister_language",
    "language_for_file",
    "create_engine",
    "registered_languages",
]

# ---------------------------------------------------------------------------
# 语法色板（低饱和协调配色，scope -> 颜色 hex）
# ---------------------------------------------------------------------------

#: 亮色主题语法色板
SYNTAX_LIGHT = {
    "keyword": "#6B4FA0",
    "string": "#4E7A4E",
    "comment": "#8A9199",
    "docstring": "#6A8A6A",
    "number": "#9A6A3A",
    "function": "#3A6E8F",
    "type": "#4A7A78",
    "operator": "#6E7684",
    "variable": "#46536A",
    "decorator": "#8F7B45",
    "tag": "#3F5E8C",
    "attribute": "#7A5A8C",
    "property": "#3A6E6E",
    "builtin": "#557A8C",
    "punctuation": "#8A9199",
}

#: 暗色主题语法色板
SYNTAX_DARK = {
    "keyword": "#B08FD0",
    "string": "#98C39A",
    "comment": "#6E7684",
    "docstring": "#7FA888",
    "number": "#D0A878",
    "function": "#8FB8D8",
    "type": "#7FC8BF",
    "operator": "#A6AEBB",
    "variable": "#D8DEE8",
    "decorator": "#D8C078",
    "tag": "#7C98C4",
    "attribute": "#C8A8D8",
    "property": "#88C8C0",
    "builtin": "#88B8C8",
    "punctuation": "#6E7684",
}

#: 各 scope 的附加字体样式（粗体 / 斜体），无条目则为常规
_SCOPE_STYLE = {
    "keyword": {"bold": True},
    "comment": {"italic": True},
    "docstring": {"italic": True},
    "type": {"bold": False},
}


def syntax_palette(mode: str = None) -> dict:
    """按主题模式返回语法色板副本；``mode=None`` 时取当前主题。"""
    if mode is None:
        mode = ThemeManager.instance().mode
    return dict(SYNTAX_DARK if mode == "dark" else SYNTAX_LIGHT)


# ---------------------------------------------------------------------------
# 规则
# ---------------------------------------------------------------------------

class HighlightRule:
    """单条高亮规则：正则 → scope。

    参数:
        pattern: 正则表达式（``QRegularExpression`` 语法）。
        scope: scope 名（如 ``"keyword"`` / ``"string"``），须存在于色板，
            未知 scope 回落为默认文本色（不报错）。
        end_pattern: 缺省 ``None`` 为单行规则；给定正则时成为多行规则
            （从 ``pattern`` 匹配处到 ``end_pattern`` 匹配处跨块着色）。
        state: 多行规则的块状态 id（>0）。同一引擎内多条多行规则的
            ``state`` 必须互不相同；缺省自动分配。
    """

    _next_state = 1

    def __init__(self, pattern, scope, end_pattern=None, state=None):
        self.pattern = pattern
        self.scope = scope
        self.end_pattern = end_pattern
        self.start_re = QRegularExpression(pattern)
        self.end_re = (
            QRegularExpression(end_pattern) if end_pattern is not None else None
        )
        if end_pattern is not None:
            if state is None:
                state = HighlightRule._next_state
                HighlightRule._next_state += 1
            if state <= 0:
                raise ValueError("多行规则的 state 必须为正整数")
        self.state = state or 0

    @property
    def is_multiline(self) -> bool:
        """是否为多行（跨块）规则。"""
        return self.end_re is not None

    def __repr__(self):  # pragma: no cover - 调试用
        kind = "multiline" if self.is_multiline else "inline"
        return f"HighlightRule({kind}, {self.pattern!r} -> {self.scope!r})"


# ---------------------------------------------------------------------------
# 引擎
# ---------------------------------------------------------------------------

class HighlightEngine(QSyntaxHighlighter):
    """语法高亮引擎基座（QSyntaxHighlighter）。

    参数:
        document: 目标 ``QTextDocument``。
        language: 语言名（仅记录，便于调试 / 状态展示）。
        rules: ``HighlightRule`` 序列（单行与多行规则可混排）。
        palette: scope -> 颜色映射，缺省按当前主题取 ``syntax_palette()``。

    主题切换（``ThemeManager.theme_changed``）时自动按当前模式重建
    ``scopes`` 并 ``rehighlight()``。
    """

    def __init__(self, document, language="plain", rules=(), palette=None,
                 parent=None):
        super().__init__(document)
        self._language = language
        self._rules = list(rules)
        self._inline_rules = [r for r in self._rules if not r.is_multiline]
        self._multiline_rules = sorted(
            [r for r in self._rules if r.is_multiline], key=lambda r: r.state
        )
        self._palette = dict(palette) if palette else syntax_palette()
        self._scopes = {}
        self._rebuild_formats()
        # 主题联动：切换后重建格式并重刷
        ThemeManager.instance().theme_changed.connect(self._on_theme_changed)

    # -- 属性 --------------------------------------------------------------
    @property
    def language(self) -> str:
        """当前语言名。"""
        return self._language

    @property
    def rules(self) -> list:
        """规则表副本。"""
        return list(self._rules)

    @property
    def scopes(self) -> dict:
        """``dict[str, QTextCharFormat]``：scope → 着色格式（副本）。"""
        return dict(self._scopes)

    @property
    def palette(self) -> dict:
        """当前语法色板副本。"""
        return dict(self._palette)

    # -- 配置 --------------------------------------------------------------
    def set_palette(self, palette: dict) -> None:
        """整体替换语法色板并立即重刷文档。"""
        self._palette = dict(palette)
        self._rebuild_formats()
        self.rehighlight()

    def _rebuild_formats(self) -> None:
        """由色板重建 scope -> QTextCharFormat 映射。"""
        self._scopes = {}
        for scope, color in self._palette.items():
            fmt = QTextCharFormat()
            fmt.setForeground(QColor(color))
            style = _SCOPE_STYLE.get(scope, {})
            if style.get("bold"):
                fmt.setFontWeight(QFont.Bold)
            if style.get("italic"):
                fmt.setFontItalic(True)
            self._scopes[scope] = fmt

    def _on_theme_changed(self, mode: str) -> None:
        """主题切换：取对应模式色板重刷。"""
        try:
            self._palette = syntax_palette(mode)
            self._rebuild_formats()
            self.rehighlight()
        except RuntimeError:
            pass  # 文档 / 引擎已销毁

    # -- 着色 --------------------------------------------------------------
    def _fmt(self, scope: str) -> QTextCharFormat:
        fmt = self._scopes.get(scope)
        if fmt is None:
            fmt = QTextCharFormat()  # 未知 scope：默认文本
        return fmt

    @staticmethod
    def _in_covered(pos: int, covered: list) -> bool:
        """``pos`` 是否落在已被多行规则占用的区间内。"""
        for a, b in covered:
            if a <= pos < b:
                return True
        return False

    def highlightBlock(self, text: str) -> None:  # noqa: N802 - Qt 命名
        """对单个文本块着色（多行状态机 + 单行规则）。"""
        self.setCurrentBlockState(0)
        covered = []

        # 1) 多行规则（块注释 / 三引号等），逐条按状态机推进
        for rule in self._multiline_rules:
            fmt = self._fmt(rule.scope)
            start = 0
            if self.previousBlockState() == rule.state:
                # 上一块仍处于本规则的多行区间内：先找结束
                m = rule.end_re.match(text)
                if m.hasMatch():
                    end = m.capturedEnd()
                    self.setFormat(0, end, fmt)
                    covered.append((0, end))
                    start = end
                else:
                    self.setFormat(0, len(text), fmt)
                    covered.append((0, len(text)))
                    self.setCurrentBlockState(rule.state)
                    continue  # 整行被占用
            while True:
                m = rule.start_re.match(text, start)
                if not m.hasMatch():
                    break
                s = m.capturedStart()
                if self._in_covered(s, covered):
                    start = max(m.capturedEnd(), s + 1)
                    continue
                e = rule.end_re.match(text, m.capturedEnd())
                if e.hasMatch():
                    end = e.capturedEnd()
                    self.setFormat(s, end - s, fmt)
                    covered.append((s, end))
                    start = end
                else:
                    self.setFormat(s, len(text) - s, fmt)
                    covered.append((s, len(text)))
                    self.setCurrentBlockState(rule.state)
                    break

        # 2) 单行规则（跳过被多行规则占用的区间）
        for rule in self._inline_rules:
            fmt = self._fmt(rule.scope)
            it = rule.start_re.globalMatch(text)
            while it.hasNext():
                m = it.next()
                s = m.capturedStart()
                e = m.capturedEnd()
                if e <= s:
                    continue
                if self._in_covered(s, covered):
                    continue
                self.setFormat(s, e - s, fmt)


# ---------------------------------------------------------------------------
# 语言注册表
# ---------------------------------------------------------------------------

#: name -> (engine_factory, [扩展名...])
_LANGUAGES = {}
#: 扩展名（小写，无点） -> 语言名
_EXTENSIONS = {}


def register_language(name: str, engine_factory, extensions) -> None:
    """注册语言。

    参数:
        name: 语言名（如 ``"python"``）。
        engine_factory: 可调用 ``factory(document) -> HighlightEngine | None``；
            也可以直接传 ``None``（等价 plain，无高亮）。
        extensions: 关联文件扩展名列表（可含 ``"py"`` 或 ``".py"``）。
    """
    if not name:
        raise ValueError("语言名不能为空")
    _LANGUAGES[name] = (engine_factory, list(extensions or []))
    for ext in extensions or []:
        _EXTENSIONS[str(ext).lower().lstrip(".")] = name


def unregister_language(name: str) -> None:
    """注销语言（主要供测试 / 热重载使用）。"""
    entry = _LANGUAGES.pop(name, None)
    if entry:
        for ext in entry[1]:
            _EXTENSIONS.pop(str(ext).lower().lstrip("."), None)


def registered_languages() -> list:
    """已注册语言名列表。"""
    return sorted(_LANGUAGES)


def language_for_file(filename: str) -> str:
    """按文件扩展名推断语言名；未知扩展回落 ``"plain"``。"""
    name = str(filename or "")
    if "." in name:
        ext = name.rsplit(".", 1)[-1].lower()
        if ext in _EXTENSIONS:
            return _EXTENSIONS[ext]
    return "plain"


def create_engine(document, language: str):
    """为文档创建指定语言的高亮引擎；``plain`` / 未注册语言返回 ``None``。"""
    entry = _LANGUAGES.get(language)
    if entry is None:
        return None
    factory = entry[0]
    if factory is None:
        return None
    return factory(document)


# 内置 plain 语言：无高亮
register_language("plain", None, ["txt", "text", "log", "md.txt"])
