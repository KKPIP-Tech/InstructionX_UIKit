# -*- coding: utf-8 -*-
"""内置语言高亮包（CE_SPEC §3，E2）。

导入本模块即通过 ``register_language`` 注册全部内置语言：

- ``python``    .py / .pyw / .pyi
- ``cpp``       .c / .cc / .cpp / .cxx / .h / .hh / .hpp / .hxx（C/C++ 共用）
- ``js``        .js / .mjs / .cjs / .jsx
- ``ts``        .ts / .tsx / .mts / .cts
- ``json``      .json
- ``html``      .html / .htm / .xhtml
- ``css``       .css
- ``markdown``  .md / .markdown / .mdown
- ``qss``       .qss（Qt 样式表，复用 CSS 规则并扩展 QWidget 类型）
- ``plain``     已在 highlight.py 内注册（无高亮）

实现说明：

- 每条语言 = 一组 ``HighlightRule``；多行规则（python 三引号 / 文档串、
  块注释、js 模板字符串、cpp raw string、markdown 围栏代码块）交给
  ``HighlightEngine`` 的状态机跨块跟踪。
- 单行规则按列表顺序应用，**后者覆盖前者**。因此统一采用如下顺序：
  运算符 → 数字 → 函数名 → 关键字 → 类型 → 内置量 → 装饰器 → 行注释 →
  字符串。数字紧随运算符，可覆盖科学计数指数内的符号；字符串 / 注释
  靠后即可覆盖掉其内部误中的关键字、数字等。
- C++ raw string 仅支持 ``R"( ... )"`` 常见定界形式（跨块两条独立正则
  无法回引任意分隔符）。

主题切换由 ``HighlightEngine`` 基座处理，本模块无需干预。
"""

from .highlight import HighlightRule, register_language

__all__ = [
    "PYTHON_RULES",
    "CPP_RULES",
    "JS_RULES",
    "TS_RULES",
    "JSON_RULES",
    "HTML_RULES",
    "CSS_RULES",
    "MARKDOWN_RULES",
    "QSS_RULES",
]


def _words(words) -> str:
    """单词列表 → 带词边界的交替正则。"""
    return r"\b(?:" + "|".join(words) + r")\b"


def _factory(language, rules):
    """生成 ``factory(document) -> HighlightEngine``。"""

    def create(document):
        from .highlight import HighlightEngine

        return HighlightEngine(document, language, rules=rules)

    return create


# ---------------------------------------------------------------------------
# Python
# ---------------------------------------------------------------------------

_PY_STR_PREFIX = r"(?:\b[rRbBuUfF]{1,2})?"

PYTHON_RULES = [
    # -- 多行：行首（可缩进）三引号 = 文档串；其余三引号 = 字符串 -------------
    HighlightRule(r'^[ \t]*' + _PY_STR_PREFIX + r'"""', "docstring",
                  end_pattern=r'"""'),
    HighlightRule(r"^[ \t]*" + _PY_STR_PREFIX + r"'''", "docstring",
                  end_pattern=r"'''"),
    HighlightRule(_PY_STR_PREFIX + r'"""', "string", end_pattern=r'"""'),
    HighlightRule(_PY_STR_PREFIX + r"'''", "string", end_pattern=r"'''"),
    # -- 单行（顺序即覆盖优先级） --------------------------------------------
    HighlightRule(r"[-+*/%@&|^~<>=!:~]+", "operator"),
    HighlightRule(
        r"\b(?:0[xX][0-9a-fA-F_]+|0[bB][01_]+|0[oO][0-7_]+"
        r"|\d[\d_]*(?:\.\d[\d_]*)?(?:[eE][+-]?\d+)?[jJ]?)\b",
        "number"),
    HighlightRule(r"\b[A-Za-z_]\w*(?=[ \t]*\()", "function"),
    HighlightRule(_words([
        "def", "class", "return", "if", "elif", "else", "for", "while",
        "import", "from", "as", "with", "try", "except", "finally", "raise",
        "lambda", "pass", "break", "continue", "and", "or", "not", "in",
        "is", "del", "global", "nonlocal", "yield", "assert", "async",
        "await", "match", "case",
    ]), "keyword"),
    HighlightRule(r"\b[A-Z][A-Za-z0-9_]*\b", "type"),
    HighlightRule(_words([
        "True", "False", "None", "self", "cls", "print", "len", "range",
        "int", "str", "float", "bool", "list", "dict", "set", "tuple",
        "type", "object", "isinstance", "issubclass", "enumerate", "zip",
        "map", "filter", "sorted", "reversed", "sum", "min", "max", "abs",
        "open", "super", "Exception", "ValueError", "TypeError", "KeyError",
        "IndexError", "RuntimeError", "StopIteration", "NotImplemented",
        "Ellipsis", "__name__", "__main__", "__init__", "__file__",
    ]), "builtin"),
    HighlightRule(r"@[A-Za-z_][\w.]*", "decorator"),
    HighlightRule(r"#[^\"'\n]*", "comment"),
    HighlightRule(_PY_STR_PREFIX + r'"(?:\\.|[^"\\\n])*"', "string"),
    HighlightRule(_PY_STR_PREFIX + r"'(?:\\.|[^'\\\n])*'", "string"),
]

# ---------------------------------------------------------------------------
# C / C++
# ---------------------------------------------------------------------------

CPP_RULES = [
    # -- 多行：文档块注释须在普通块注释之前创建（状态 id 更小，先匹配） ------
    HighlightRule(r"/\*\*", "docstring", end_pattern=r"\*/"),
    HighlightRule(r"/\*", "comment", end_pattern=r"\*/"),
    HighlightRule(r"\bR\"\(", "string", end_pattern=r"\)\""),  # raw string
    # -- 单行 ---------------------------------------------------------------
    HighlightRule(r"[-+*/%&|^~<>=!:~]+", "operator"),
    HighlightRule(
        r"\b(?:0[xX][0-9a-fA-F']+|0[bB][01']+|\d[\d']*(?:\.\d[\d']*)?"
        r"(?:[eE][+-]?\d+)?[fFuUlL]*)\b",
        "number"),
    # #include <...> 整行先着 string，稍后关键字规则覆盖指令名
    HighlightRule(r"^[ \t]*#[ \t]*include[ \t]*<[^>\n]*>", "string"),
    HighlightRule(r"\b[A-Za-z_]\w*(?=[ \t]*\()", "function"),
    HighlightRule(_words([
        "alignas", "asm", "break", "case", "catch", "class", "const",
        "constexpr", "continue", "decltype", "default", "delete", "do",
        "else", "enum", "explicit", "export", "extern", "for", "friend",
        "goto", "if", "inline", "mutable", "namespace", "new", "noexcept",
        "operator", "private", "protected", "public", "register", "return",
        "sizeof", "static", "static_assert", "struct", "switch", "template",
        "this", "throw", "try", "typedef", "typename", "union", "using",
        "virtual", "while", "volatile", "override", "final", "concept",
        "requires", "co_await", "co_return", "co_yield",
    ]), "keyword"),
    HighlightRule(r"^[ \t]*#[ \t]*[A-Za-z]+", "keyword"),  # 预处理器指令
    HighlightRule(_words([
        "int", "char", "short", "long", "float", "double", "bool", "void",
        "unsigned", "signed", "auto", "wchar_t", "char16_t", "char32_t",
        "size_t", "ptrdiff_t", "string", "wstring", "vector", "map", "set",
        "pair", "unique_ptr", "shared_ptr", "istream", "ostream",
    ]), "type"),
    HighlightRule(r"\b[A-Z][A-Za-z0-9_]*\b", "type"),
    HighlightRule(_words([
        "true", "false", "nullptr", "NULL", "std", "cout", "cin", "endl",
        "printf", "scanf", "malloc", "free", "memcpy", "strlen",
    ]), "builtin"),
    HighlightRule(r"//[^\"'\n]*", "comment"),
    HighlightRule(r"//[/!][^\n]*", "docstring"),  # /// 或 //! 文档行注释
    HighlightRule(r'"(?:\\.|[^"\\\n])*"', "string"),
    HighlightRule(r"'(?:\\.|[^'\\\n])*'", "string"),
]

# ---------------------------------------------------------------------------
# JavaScript / TypeScript
# ---------------------------------------------------------------------------

# 多行规则对象可安全跨语言共享（状态在引擎实例内）
JS_DOC_BLOCK = HighlightRule(r"/\*\*", "docstring", end_pattern=r"\*/")
JS_BLOCK_COMMENT = HighlightRule(r"/\*", "comment", end_pattern=r"\*/")
JS_TEMPLATE = HighlightRule(r"`", "string", end_pattern=r"(?<!\\)`")

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

JS_RULES = [
    JS_DOC_BLOCK, JS_BLOCK_COMMENT, JS_TEMPLATE,
    HighlightRule(r"[-+*/%&|^~<>=!:?~]+", "operator"),
    HighlightRule(
        r"\b(?:0[xX][0-9a-fA-F_]+|0[bB][01_]+|0[oO][0-7_]+"
        r"|\d[\d_]*(?:\.\d[\d_]*)?(?:[eE][+-]?\d+)?n?)\b",
        "number"),
    HighlightRule(r"\b[A-Za-z_$][\w$]*(?=[ \t]*\()", "function"),
    HighlightRule(_words(_JS_KEYWORDS), "keyword"),
    HighlightRule(r"\b[A-Z][A-Za-z0-9_]*\b", "type"),
    HighlightRule(_words(_JS_BUILTINS), "builtin"),
    HighlightRule(r"//[^\"'`\n]*", "comment"),
    HighlightRule(r'"(?:\\.|[^"\\\n])*"', "string"),
    HighlightRule(r"'(?:\\.|[^'\\\n])*'", "string"),
]

TS_RULES = [
    JS_DOC_BLOCK, JS_BLOCK_COMMENT, JS_TEMPLATE,
    HighlightRule(r"[-+*/%&|^~<>=!:?~]+", "operator"),
    HighlightRule(
        r"\b(?:0[xX][0-9a-fA-F_]+|0[bB][01_]+|0[oO][0-7_]+"
        r"|\d[\d_]*(?:\.\d[\d_]*)?(?:[eE][+-]?\d+)?n?)\b",
        "number"),
    HighlightRule(r"\b[A-Za-z_$][\w$]*(?=[ \t]*\()", "function"),
    HighlightRule(_words(_JS_KEYWORDS + [
        "interface", "type", "enum", "namespace", "implements", "readonly",
        "public", "private", "protected", "abstract", "declare", "keyof",
        "infer", "is", "satisfies", "as",
    ]), "keyword"),
    HighlightRule(_words([
        "string", "number", "boolean", "any", "void", "never", "unknown",
        "object", "bigint", "symbol",
    ]), "type"),
    HighlightRule(r"\b[A-Z][A-Za-z0-9_]*\b", "type"),
    HighlightRule(_words(_JS_BUILTINS), "builtin"),
    HighlightRule(r"@[A-Za-z_][\w.]*", "decorator"),  # TS 装饰器
    HighlightRule(r"//[^\"'`\n]*", "comment"),
    HighlightRule(r'"(?:\\.|[^"\\\n])*"', "string"),
    HighlightRule(r"'(?:\\.|[^'\\\n])*'", "string"),
]

# ---------------------------------------------------------------------------
# JSON
# ---------------------------------------------------------------------------

JSON_RULES = [
    HighlightRule(r"-?\b(?:0|[1-9]\d*)(?:\.\d+)?(?:[eE][+-]?\d+)?\b",
                  "number"),
    HighlightRule(_words(["true", "false", "null"]), "builtin"),
    # 字符串值：仅当引号紧随 : / , / [ 之后（避免跨越键名的误匹配）
    HighlightRule(r'(?<=[:,\[])[ \t]*"(?:\\.|[^"\\\n])*"', "string"),
    HighlightRule(r'"(?:\\.|[^"\\\n])*"(?=[ \t]*:)', "property"),  # 键名
    HighlightRule(r"[{}\[\],:]", "punctuation"),
]

# ---------------------------------------------------------------------------
# HTML
# ---------------------------------------------------------------------------

HTML_RULES = [
    HighlightRule(r"<!--", "comment", end_pattern=r"-->"),
    HighlightRule(r"=", "operator"),
    HighlightRule(r"&[A-Za-z0-9#]+;", "builtin"),  # 实体
    HighlightRule(r"</?[A-Za-z][\w-]*", "tag"),
    HighlightRule(r"[A-Za-z_:][\w.:-]*(?=[ \t]*=)", "attribute"),
    HighlightRule(r"/?>", "punctuation"),
    HighlightRule(r'"(?:\\.|[^"\\\n])*"', "string"),
    HighlightRule(r"'(?:\\.|[^'\\\n])*'", "string"),
    HighlightRule(r"<![A-Za-z][^>\n]*", "builtin"),  # DOCTYPE（置末覆盖）
]

# ---------------------------------------------------------------------------
# CSS / QSS
# ---------------------------------------------------------------------------

_CSS_COMMENT = HighlightRule(r"/\*", "comment", end_pattern=r"\*/")

_CSS_VALUE_WORDS = [
    "auto", "none", "solid", "dashed", "dotted", "bold", "normal",
    "center", "left", "right", "top", "bottom", "middle", "transparent",
    "white", "black", "red", "green", "blue", "gray", "block", "inline",
    "flex", "grid", "absolute", "relative", "fixed", "hidden", "inherit",
    "no-repeat", "repeat", "cover", "contain", "pointer", "default",
]

CSS_RULES = [
    _CSS_COMMENT,
    HighlightRule(r"\b\d+(?:\.\d+)?(?:px|em|rem|%|vh|vw|vmin|vmax|s|ms"
                  r"|deg|fr|ch|ex|pt|cm|mm)?\b", "number"),
    HighlightRule(r"\b[a-zA-Z-][\w-]*(?=[ \t]*\()", "function"),  # rgb()/url()
    HighlightRule(r"@[\w-]+", "keyword"),          # @media 等 at 规则
    HighlightRule(r"!\s*important", "keyword"),
    HighlightRule(r"\.[A-Za-z_][\w-]*", "type"),   # 类选择器
    HighlightRule(r"#[A-Za-z_][\w-]*", "builtin"),  # id 选择器
    HighlightRule(r"#[0-9a-fA-F]{3,8}\b", "number"),  # 颜色值（覆盖同形 id）
    HighlightRule(r":{1,2}[a-zA-Z-]+", "decorator"),  # 伪类 / 伪元素
    HighlightRule(_words(_CSS_VALUE_WORDS), "builtin"),
    HighlightRule(r"^[ \t]*[A-Za-z][\w-]*", "tag"),  # 元素选择器
    HighlightRule(r"^[ \t]+[A-Za-z-][\w-]*(?=[ \t]*:)", "property"),  # 属性名
    HighlightRule(r'"(?:\\.|[^"\\\n])*"', "string"),
    HighlightRule(r"'(?:\\.|[^'\\\n])*'", "string"),
]

QSS_RULES = CSS_RULES[:-2] + [  # 在字符串规则前插入 QWidget 类型规则
    HighlightRule(r"\b[A-Z][A-Za-z0-9_]*\b", "type"),  # QPushButton 等
    HighlightRule(r"::[a-zA-Z-]+", "decorator"),       # 子控件
] + CSS_RULES[-2:]

# ---------------------------------------------------------------------------
# Markdown
# ---------------------------------------------------------------------------

MARKDOWN_RULES = [
    # -- 多行：围栏代码块 -----------------------------------------------------
    HighlightRule(r"^[ \t]*```.*", "string", end_pattern=r"^[ \t]*```[ \t]*$"),
    HighlightRule(r"^[ \t]*~~~.*", "string", end_pattern=r"^[ \t]*~~~[ \t]*$"),
    # -- 单行 ---------------------------------------------------------------
    HighlightRule(r"^[ \t]*#{1,6}[ \t]+[^\n]*", "keyword"),     # 标题
    HighlightRule(r"^[ \t]*>[^\n]*", "comment"),                # 引用块
    HighlightRule(r"^[ \t]*(?:[-*+]|\d+\.)[ \t]+", "operator"),  # 列表标记
    HighlightRule(r"\*\*[^*\n]+\*\*", "type"),                  # 加粗
    HighlightRule(r"(?<!\*)\*[^*\n]+\*(?!\*)", "attribute"),    # 斜体
    HighlightRule(r"`[^`\n]+`", "string"),                      # 行内代码
    HighlightRule(r"\[[^\]\n]*\]\([^)\n]*\)", "function"),      # 链接
]

# ---------------------------------------------------------------------------
# 注册
# ---------------------------------------------------------------------------

register_language("python", _factory("python", PYTHON_RULES),
                  ["py", "pyw", "pyi"])
register_language("cpp", _factory("cpp", CPP_RULES),
                  ["c", "cc", "cpp", "cxx", "h", "hh", "hpp", "hxx"])
register_language("js", _factory("js", JS_RULES),
                  ["js", "mjs", "cjs", "jsx"])
register_language("ts", _factory("ts", TS_RULES),
                  ["ts", "tsx", "mts", "cts"])
register_language("json", _factory("json", JSON_RULES), ["json"])
register_language("html", _factory("html", HTML_RULES),
                  ["html", "htm", "xhtml"])
register_language("css", _factory("css", CSS_RULES), ["css"])
register_language("markdown", _factory("markdown", MARKDOWN_RULES),
                  ["md", "markdown", "mdown"])
register_language("qss", _factory("qss", QSS_RULES), ["qss"])
