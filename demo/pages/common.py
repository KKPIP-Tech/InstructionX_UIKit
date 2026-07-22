# -*- coding: utf-8 -*-
"""Demo 演示页公共脚手架。

提供统一的「标题 + 说明 + 分区」页面骨架，以及动画卡片、色块等辅助件。
所有自绘元素均通过 ``T()`` 取令牌并在 ``theme_changed`` 时刷新，
保证亮 / 暗主题切换后无需重启即可正确换肤。
"""

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import (
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from InstructionX_UIKit.theme import T, ThemeManager, set_property
from InstructionX_UIKit.tokens import MONO_FAMILY

__all__ = [
    "make_page",
    "Section",
    "row",
    "col",
    "ColorBlock",
    "DemoCard",
    "hint_label",
    "code_label",
    "usage_section",
]


def _title_label(text: str) -> QLabel:
    """页面主标题：大字号 + 加粗，颜色随主题（QLabel 默认 text.primary）。"""
    lab = QLabel(text)
    font = QFont()
    font.setPixelSize(T("font.title.lg"))
    font.setWeight(QFont.Weight(T("font.weight.bold")))
    lab.setFont(font)
    return lab


def hint_label(text: str, role: str = "secondary") -> QLabel:
    """说明 / 提示文字：次要色，自动换行。"""
    lab = QLabel(text)
    lab.setWordWrap(True)
    set_property(lab, "role", role)
    return lab


def code_label(code: str) -> QLabel:
    """单行灰字代码标签：等宽字体 + 第三级文本色，用于展示调用示例。"""
    lab = QLabel(code)
    lab.setTextInteractionFlags(Qt.TextSelectableByMouse)
    font = QFont()
    font.setFamily(MONO_FAMILY)
    font.setPixelSize(T("font.sm"))
    lab.setFont(font)
    set_property(lab, "role", "tertiary")
    lab.setWordWrap(True)
    return lab


def usage_section(code: str) -> QGroupBox:
    """「用法」分区：展示该演示对应的最小 Kit 调用代码（单行灰字样式）。

    用法::

        page = make_page(title, desc, [usage_section('Button("确定", variant="primary")'), ...])
    """
    box = Section("用法")
    box.layout().addWidget(code_label(code))
    return box


def Section(title: str, spacing: int = 10) -> QGroupBox:
    """分区容器（QGroupBox + 垂直布局）。

    用法::

        box = Section("基础用法")
        box.layout().addWidget(some_widget)
    """
    box = QGroupBox(title)
    lay = QVBoxLayout(box)
    lay.setSpacing(spacing)
    lay.setContentsMargins(12, 20, 12, 12)
    return box


def row(*widgets, spacing: int = 10) -> QWidget:
    """水平一行（左对齐，末尾拉伸）。

    既接受 QWidget，也接受 QLayout；常用于把若干控件排成一行。
    """
    host = QWidget()
    lay = QHBoxLayout(host)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(spacing)
    for w in widgets:
        if isinstance(w, QWidget):
            lay.addWidget(w)
        elif w is not None:
            lay.addLayout(w)
    lay.addStretch(1)
    return host


def col(*widgets, spacing: int = 10) -> QWidget:
    """垂直一列（顶部对齐，末尾拉伸）。"""
    host = QWidget()
    lay = QVBoxLayout(host)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(spacing)
    for w in widgets:
        if isinstance(w, QWidget):
            lay.addWidget(w)
        elif w is not None:
            lay.addLayout(w)
    lay.addStretch(1)
    return host


def make_page(title: str, description: str, sections) -> QScrollArea:
    """组装一个完整演示页（滚动容器）。

    参数:
        title: 页面标题。
        description: 页面说明（次要色，自动换行）。
        sections: 分区控件列表（通常为 :func:`Section` 返回的 QGroupBox）。

    返回:
        QScrollArea；其 ``widget()`` 为内容根控件（供整页 grab() 截图）。
    """
    content = QWidget()
    lay = QVBoxLayout(content)
    lay.setContentsMargins(20, 18, 20, 24)
    lay.setSpacing(8)

    lay.addWidget(_title_label(title))
    if description:
        lay.addWidget(hint_label(description))
        lay.addSpacing(6)
    else:
        lay.addSpacing(4)

    for sec in sections:
        if sec is not None:
            lay.addWidget(sec)
    lay.addStretch(1)

    scroll = QScrollArea()
    scroll.setWidget(content)
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QFrame.Shape.NoFrame)
    return scroll


class ColorBlock(QWidget):
    """主题感知色块：圆角矩形 + 居中文字，常用作布局 / 动画的演示目标。

    参数:
        text: 居中显示的文字。
        color_key: 令牌键（不含 ``color.`` 前缀），如 ``"primary"``。
        size: (宽, 高)。
        text_on: 文字色令牌键，默认 ``on.primary``（深色文字场景可改）。
    """

    def __init__(self, text: str = "", color_key: str = "primary",
                 size=(120, 72), text_on: str = "on.primary", parent=None):
        super().__init__(parent)
        self._text = text
        self._key = color_key
        self._on = text_on
        self.setMinimumSize(*size)
        ThemeManager.instance().theme_changed.connect(lambda *_: self.update())

    def paintEvent(self, event):  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(T(f"color.{self._key}")))
        painter.drawRoundedRect(self.rect().adjusted(1, 1, -1, -1),
                                T("radius.lg"), T("radius.lg"))
        if self._text:
            painter.setPen(QPen(QColor(T(f"color.{self._on}"))))
            painter.drawText(self.rect(), Qt.AlignCenter, self._text)
        painter.end()


class DemoCard(QFrame):
    """动画演示卡片：标题 + 演示区 + 「播放」按钮。

    参数:
        title: 卡片标题（动画名称）。
        demo: 演示元件控件。
        play: 点击「播放」时执行的可调用对象（重发动画）。
        hint: 动画的简短说明。
        demo_height: 演示区最小高度。
    """

    def __init__(self, title: str, demo: QWidget, play, hint: str = "",
                 demo_height: int = 130, parent=None):
        super().__init__(parent)
        self.setFrameShape(QFrame.Shape.StyledPanel)  # 命中 QSS 卡片边框

        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(6)

        head = QLabel(title)
        head_font = QFont()
        head_font.setWeight(QFont.Weight(T("font.weight.semibold")))
        head.setFont(head_font)
        lay.addWidget(head)

        if hint:
            lay.addWidget(hint_label(hint, role="tertiary"))

        demo_wrap = QWidget()
        demo_lay = QVBoxLayout(demo_wrap)
        demo_lay.setContentsMargins(0, 2, 0, 2)
        demo_lay.addWidget(demo, 0, Qt.AlignCenter)
        demo_wrap.setMinimumHeight(demo_height)
        lay.addWidget(demo_wrap, 1)

        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        play_btn = QPushButton("播放")
        set_property(play_btn, "size", "sm")
        play_btn.clicked.connect(self._safe_play)
        btn_row.addWidget(play_btn)
        lay.addLayout(btn_row)

        self._play = play
        self.play_button = play_btn

    def _safe_play(self):
        """执行播放回调（吞掉异常以免打断 Demo 交互）。"""
        try:
            self._play()
        except Exception:  # noqa: BLE001
            pass
