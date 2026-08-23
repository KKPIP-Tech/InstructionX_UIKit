# -*- coding: utf-8 -*-
"""工具提示（SPEC §5.2 tooltip）。

QToolTip 的富样式由全局 QSS 统一（深色底、圆角、内边距），
本模块仅提供带可选标题的设置辅助函数。标题 / 正文在拼入 HTML 前
一律 html.escape 转义，避免 ``<`` / ``&`` 等字符被当作标签解析。
"""

import html as _html

from PySide6.QtWidgets import QWidget

__all__ = ["set_tooltip"]


def set_tooltip(widget: QWidget, text: str, title: str = None) -> QWidget:
    """为控件设置富样式工具提示。

    参数:
        widget: 目标控件。
        text: 提示正文（纯文本，自动转义）。
        title: 可选标题（加粗显示在正文上方，自动转义）。

    返回:
        传入的 ``widget``（便于链式调用）。

    示例::

        set_tooltip(save_btn, "保存当前文档", title="保存")
        set_tooltip(close_btn, "关闭窗口")
    """
    if title:
        html = (
            f'<span style="font-weight:600;">{_html.escape(title)}</span>'
            f"<br/>{_html.escape(text)}"
        )
        widget.setToolTip(html)
    else:
        widget.setToolTip(_html.escape(text))
    return widget
