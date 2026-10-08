# -*- coding: utf-8 -*-
"""工具提示（SPEC §5.2 tooltip）。

QToolTip 的外观由全局 QSS 统一（深色底、圆角、内边距），本模块负责
**内容构造**：转义、可选标题、多行换行与字数上限。

内容规则：

- 标题 / 正文在拼入 HTML 前一律 ``html.escape`` 转义，避免 ``<`` /
  ``&`` 等字符被当作标签解析；
- ``\\n`` 按真实换行渲染（旧版把 ``\\n`` 原样塞进富文本，QToolTip
  不认换行，多行提示会挤成一行）；
- 正文超过 ``max_chars`` 时在词边界省略并补省略号，避免一条超长
  提示横跨整个屏幕（这正是「浮层尺寸失控」的常见来源）。

> 外观（底色 / 圆角 / 内边距 / 描边）属全局 QSS 管辖范围，见
> ``theme._qss_base`` 的 ``QToolTip`` 规则；本模块不做实例级覆盖
> ——``QToolTip`` 是顶层窗口，控件级样式表对它无效，强行覆盖反而会
> 产生「只有部分提示有样式」的不一致。
"""

import html as _html

from PySide6.QtWidgets import QWidget

__all__ = ["set_tooltip"]

#: 正文默认字数上限：超出后省略，避免提示横跨整屏
DEFAULT_MAX_CHARS = 80


def _escape_lines(text: str) -> str:
    """逐行转义，``\\n`` 转成 ``<br/>``（QToolTip 认 ``<br/>`` 不认 ``\\n``）。"""
    parts = [_html.escape(line) for line in str(text).split("\n")]
    return "<br/>".join(parts)


def _elide(text: str, limit: int) -> str:
    """按字数上限截断（保持原有换行结构）。"""
    if limit <= 0 or len(text) <= limit:
        return text
    clipped = text[:max(0, limit - 1)]
    # 尽量断在最后一个空白处，避免把一个词劈成两半
    cut = clipped.rfind(" ")
    if cut > limit // 2:
        clipped = clipped[:cut]
    return clipped.rstrip() + "…"


def set_tooltip(widget: QWidget, text: str, title: str = None,
                 max_chars: int = DEFAULT_MAX_CHARS) -> QWidget:
    """为控件设置富样式工具提示。

    参数:
        widget: 目标控件。
        text: 提示正文（纯文本，自动转义；``\\n`` 换行）。
        title: 可选标题（加粗显示在正文上方，自动转义）。
        max_chars: 正文字数上限，超出省略；``0`` 表示不限制。

    返回:
        传入的 ``widget``（便于链式调用）。

    示例::

        set_tooltip(save_btn, "保存当前文档\\n支持 Ctrl+S", title="保存")
        set_tooltip(close_btn, "关闭窗口")
    """
    body = _elide("" if text is None else str(text), max_chars)
    if title:
        html = (f'<span style="font-weight:600;">{_html.escape(str(title))}</span>'
                f"{'<br/>' if body else ''}{_escape_lines(body)}")
    else:
        html = _escape_lines(body)
    widget.setToolTip(html)
    return widget