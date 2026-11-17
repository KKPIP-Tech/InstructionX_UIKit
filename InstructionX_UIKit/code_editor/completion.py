# -*- coding: utf-8 -*-
"""语言感知的补全候选注册表（CE_SPEC §2 / §3）。

设计目标：

- **默认按当前语言给候选**：Python 不给 JS 关键字，JSON 不给 Python
  关键字，``plain`` / ``markdown`` 默认不提供补全；
- **可被宿主完全替换**：``register_completion(language, provider)`` 注册
  语言级 provider，或调用 ``CodeEditor.set_completion_provider(fn, language=...)``
  覆盖单个语言；
- **语言级开关**：是否启用、是否输入自动触发都可以按语言单独设置，
  由 ``CodeEditor`` 的对应 API 实现；
- 不新增第三方依赖，列表规模保持轻量（关键字/常用符号级，不是语言服务器）。

Provider 签名（推荐）::

    def provider(prefix: str, line: int, column: int, language: str) -> list[dict]

返回项格式与 ``CodeEditor`` 契约一致::

    {"label": str, "kind": str, "detail": str, "insert": str}

``CodeEditor.set_completion_provider`` 仍兼容旧的 3 参数
``fn(prefix, line, col)``，由 editor 侧做签名适配。
"""

import builtins
import keyword

__all__ = [
    "completion_languages",
    "completion_provider_for",
    "register_completion",
    "unregister_completion",
]


def _words(words, kind: str, detail: str) -> list:
    """把单词列表变成补全项，按输入顺序去重。"""
    seen = set()
    items = []
    for word in words:
        word = str(word)
        if not word or word in seen:
            continue
        seen.add(word)
        items.append({
            "label": word,
            "kind": kind,
            "detail": detail,
            "insert": word,
        })
    return items


def _make_provider(*groups):
    """生成 ``provider(prefix, line, column, language)``。

    每组为 ``(words, kind, detail)``；前缀匹配大小写不敏感。
    """
    entries = []
    for words, kind, detail in groups:
        entries.extend(_words(words, kind, detail))

    def provider(prefix, line, column, language):
        p = str(prefix or "").lower()
        if not p:
            return list(entries)
        return [it for it in entries
                if it["label"].lower().startswith(p)]

    return provider


# ---------------------------------------------------------------------------
# 内置语言候选
# ---------------------------------------------------------------------------

_PY_KEYWORDS = list(getattr(keyword, "softkwlist", [])) + list(keyword.kwlist)
_PY_BUILTINS = [
    name for name in dir(builtins)
    if not name.startswith("_")
]

_CPP_KEYWORDS = [
    "alignas", "alignof", "and", "asm", "auto", "bitand", "bitor", "bool",
    "break", "case", "catch", "char", "class", "compl", "concept",
    "const", "consteval", "constexpr", "constinit", "const_cast",
    "continue", "co_await", "co_return", "co_yield", "decltype", "default",
    "delete", "do", "double", "dynamic_cast", "else", "enum", "explicit",
    "export", "extern", "false", "float", "for", "friend", "goto", "if",
    "inline", "int", "long", "mutable", "namespace", "new", "noexcept",
    "not", "nullptr", "operator", "or", "private", "protected", "public",
    "register", "reinterpret_cast", "requires", "return", "short", "signed",
    "sizeof", "static", "static_assert", "static_cast", "struct", "switch",
    "template", "this", "thread_local", "throw", "true", "try", "typedef",
    "typeid", "typename", "union", "unsigned", "using", "virtual", "void",
    "volatile", "wchar_t", "while", "xor",
]
_CPP_TYPES = [
    "std", "string", "wstring", "vector", "map", "unordered_map", "set",
    "unordered_set", "pair", "tuple", "array", "deque", "list", "queue",
    "stack", "unique_ptr", "shared_ptr", "weak_ptr", "optional", "variant",
    "size_t", "ptrdiff_t", "int8_t", "int16_t", "int32_t", "int64_t",
    "uint8_t", "uint16_t", "uint32_t", "uint64_t",
]

_JS_KEYWORDS = [
    "break", "case", "catch", "class", "const", "continue", "debugger",
    "default", "delete", "do", "else", "export", "extends", "finally",
    "for", "function", "if", "import", "in", "instanceof", "let", "new",
    "return", "super", "switch", "throw", "try", "typeof", "var", "void",
    "while", "with", "yield", "async", "await", "static", "get", "set",
    "of",
]
_JS_BUILTINS = [
    "true", "false", "null", "undefined", "NaN", "Infinity", "this",
    "arguments", "console", "window", "document", "globalThis", "Math",
    "JSON", "Object", "Array", "Number", "String", "Boolean", "Symbol",
    "Promise", "RegExp", "Error", "TypeError", "Map", "Set", "WeakMap",
    "Date", "parseInt", "parseFloat", "isNaN", "require", "module",
    "exports", "process", "fetch", "setTimeout", "setInterval",
]
_TS_KEYWORDS = [
    "interface", "type", "enum", "namespace", "implements", "readonly",
    "public", "private", "protected", "abstract", "declare", "keyof",
    "infer", "is", "satisfies", "as", "unknown", "never", "any",
]
_TS_TYPES = [
    "string", "number", "boolean", "void", "object", "bigint", "symbol",
]

_HTML_TAGS = [
    "html", "head", "body", "title", "meta", "link", "style", "script",
    "div", "span", "p", "a", "img", "input", "textarea", "button", "form",
    "label", "select", "option", "table", "thead", "tbody", "tr", "td",
    "th", "ul", "ol", "li", "section", "header", "footer", "nav", "main",
    "article", "aside", "canvas", "svg", "template",
]
_HTML_ATTRS = [
    "id", "class", "style", "href", "src", "alt", "title", "width",
    "height", "type", "name", "value", "placeholder", "disabled",
    "checked", "selected", "readonly", "required", "rel", "target",
]
_CSS_PROPERTIES = [
    "color", "background", "background-color", "background-image", "border",
    "border-color", "border-radius", "border-width", "margin", "padding",
    "display", "position", "top", "right", "bottom", "left", "width",
    "height", "min-width", "max-width", "min-height", "max-height",
    "font", "font-family", "font-size", "font-weight", "line-height",
    "text-align", "text-decoration", "overflow", "opacity", "z-index",
    "flex", "flex-direction", "align-items", "justify-content", "gap",
    "grid", "grid-template-columns", "box-shadow", "transition", "transform",
]
_QSS_PROPERTIES = _CSS_PROPERTIES + [
    "background-color", "selection-background-color", "selection-color",
    "outline", "padding-left", "padding-right", "padding-top",
    "padding-bottom", "margin-left", "margin-right", "margin-top",
    "margin-bottom", "border-style", "border-image",
]

_BUILTIN_PROVIDERS = {
    "python": _make_provider(
        (_PY_KEYWORDS, "keyword", "Python 关键字"),
        (_PY_BUILTINS, "function", "Python 内置"),
    ),
    "cpp": _make_provider(
        (_CPP_KEYWORDS, "keyword", "C/C++ 关键字"),
        (_CPP_TYPES, "type", "C/C++ 类型"),
    ),
    "js": _make_provider(
        (_JS_KEYWORDS, "keyword", "JavaScript 关键字"),
        (_JS_BUILTINS, "builtin", "JavaScript 全局对象"),
    ),
    "ts": _make_provider(
        (_JS_KEYWORDS + _TS_KEYWORDS, "keyword", "TypeScript 关键字"),
        (_TS_TYPES, "type", "TypeScript 类型"),
        (_JS_BUILTINS, "builtin", "JavaScript 全局对象"),
    ),
    "json": _make_provider(
        (["true", "false", "null"], "builtin", "JSON 字面量"),
    ),
    "html": _make_provider(
        (_HTML_TAGS, "tag", "HTML 标签"),
        (_HTML_ATTRS, "attribute", "HTML 属性"),
    ),
    "css": _make_provider(
        (_CSS_PROPERTIES, "property", "CSS 属性"),
    ),
    "qss": _make_provider(
        (_QSS_PROPERTIES, "property", "QSS 属性"),
    ),
}

#: 外部注册的 provider（覆盖内置；值为 None 表示该语言暂无自定义 provider）
_CUSTOM_PROVIDERS = {}


def completion_provider_for(language: str):
    """返回某语言的补全 provider；``plain`` / 未注册语言返回 ``None``。

    自定义 provider 优先于内置 provider。
    """
    name = str(language or "")
    return _CUSTOM_PROVIDERS.get(name) or _BUILTIN_PROVIDERS.get(name)


def register_completion(language: str, provider) -> None:
    """注册/覆盖某语言的补全 provider。

    参数:
        language: 语言名（与 ``CodeEditor.set_language`` 一致）。
        provider: ``fn(prefix, line, column, language) -> list[dict]``；
            传 ``None`` 表示移除自定义 provider，回落到内置实现。
    """
    name = str(language or "").strip()
    if not name:
        raise ValueError("语言名不能为空")
    if provider is None:
        _CUSTOM_PROVIDERS.pop(name, None)
    else:
        _CUSTOM_PROVIDERS[name] = provider


def unregister_completion(language: str) -> None:
    """移除自定义 provider，保留内置语言候选。"""
    _CUSTOM_PROVIDERS.pop(str(language or ""), None)


def completion_languages() -> list:
    """当前有补全 provider 的语言名（内置 + 自定义）。"""
    return sorted(set(_BUILTIN_PROVIDERS) | set(_CUSTOM_PROVIDERS))
