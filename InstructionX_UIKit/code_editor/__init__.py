# -*- coding: utf-8 -*-
"""代码编辑器包（CE_SPEC §1）。

公共导出：

- ``CodeEditor``：主控件（editor.py）；
- ``HighlightEngine`` / ``HighlightRule`` / ``SYNTAX_LIGHT`` / ``SYNTAX_DARK``
  / ``syntax_palette`` / ``register_language`` / ``unregister_language``
  / ``language_for_file`` / ``create_engine`` / ``registered_languages``
  （highlight.py）；
- ``RegionManager`` / ``SEVERITY_COLORS`` / ``DIAGNOSTIC_SEVERITIES``
  （regions.py）；
- ``Gutter`` / ``MiniMap`` / ``FindReplaceBar`` / ``CompletionPopup``
  / ``HoverBubble``。

``languages``（E2，导入即注册内置语言包）与 ``diff_editor.DiffEditor``（E3）
均为惰性导入：存在即导出，缺失不影响核心可用。
"""

from .editor import CodeEditor
from .gutter import Gutter
from .highlight import (
    HighlightEngine,
    HighlightRule,
    SYNTAX_DARK,
    SYNTAX_LIGHT,
    create_engine,
    language_for_file,
    register_language,
    registered_languages,
    syntax_palette,
    unregister_language,
)
from .minimap import MiniMap
from .panels import CompletionPopup, FindReplaceBar, HoverBubble
from .regions import DIAGNOSTIC_SEVERITIES, SEVERITY_COLORS, RegionManager

__all__ = [
    "CodeEditor",
    "HighlightEngine",
    "HighlightRule",
    "SYNTAX_LIGHT",
    "SYNTAX_DARK",
    "syntax_palette",
    "register_language",
    "unregister_language",
    "language_for_file",
    "create_engine",
    "registered_languages",
    "RegionManager",
    "SEVERITY_COLORS",
    "DIAGNOSTIC_SEVERITIES",
    "Gutter",
    "MiniMap",
    "FindReplaceBar",
    "CompletionPopup",
    "HoverBubble",
    "DiffEditor",  # E3 惰性导出
]

# E2 语言包：导入即注册内置语言（缺失时核心仍可工作）
try:
    from . import languages as _languages  # noqa: F401
except ImportError:
    pass

# E3 DiffEditor：惰性导出
_LAZY = {"DiffEditor": ("diff_editor", "DiffEditor")}


def __getattr__(name):
    if name in _LAZY:
        mod_name, attr = _LAZY[name]
        import importlib

        mod = importlib.import_module(f".{mod_name}", __name__)
        value = getattr(mod, attr)
        globals()[name] = value
        return value
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
