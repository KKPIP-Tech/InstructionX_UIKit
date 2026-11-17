# -*- coding: utf-8 -*-
"""评论组件（SPEC §5.2 comment）。

头像 + 作者 + 时间 + 内容 + 操作行，支持嵌套回复（左侧参考线分隔）。

基线与缩进约定（与 COMPONENT-DESIGN-CONTRACT §3 对齐）：

- **同一行按基线对齐**：作者名（md）与时间（xs）行高不同，用
  ``Qt.AlignBaseline`` 而不是默认的垂直居中——居中会让两个不同
  字阶的字看起来「一高一低」，这是旧版最扎眼的错位。
- **嵌套缩进走 layout 令牌**：层级缩进 = ``layout.card.pad_x``（12），
  参考线与回复内容的间距 = ``layout.icon.gap``（6），头像与正文的
  间距 = ``layout.gutter``（12）；全链路无裸数字。
- **头像层级递减**：主评论 md、嵌套回复 sm，正文左缘因此形成
  阶梯，层级一眼可辨。
- **扁平**：回复区只有一条 1px 参考线（``color.border``），
  不套框、不加底色层；操作行为 link 按钮，不画按钮框。
"""

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from InstructionX_UIKit.theme import T, set_font, set_property

from .avatar import Avatar

__all__ = ["CommentView"]

#: 嵌套回复的层级缩进（令牌：卡片左右内边距）
_THREAD_INDENT = T("layout.card.pad_x")
#: 参考线与回复内容的间距（令牌：图标与文字间距）
_THREAD_GAP = T("layout.icon.gap")


class CommentView(QWidget):
    """单条评论（可嵌套回复）。

    参数:
        author: 作者名。
        content: 评论正文。
        time: 时间文本（如 ``"2 小时前"``）。
        avatar: 头像来源：QPixmap / 图片路径 / 名字（文字头像）/ None。
        actions: 操作行文本列表（如 ``["回复", "赞"]``）。
        nested: 是否为嵌套回复（内部使用，决定头像档位）。
        parent: 父控件。

    示例::

        c = CommentView("张三", "写得很好", "2 小时前", actions=["回复"])
        reply = CommentView("李四", "同感", "1 小时前")
        c.add_reply(reply)
    """

    #: 操作行按钮被点击，参数为操作文本
    action_triggered = Signal(str)

    def __init__(self, author: str = "", content: str = "", time: str = "",
                 avatar=None, actions=None, nested: bool = False, parent=None):
        super().__init__(parent)
        self._nested = False
        self._avatar = Avatar(size="md")
        set_property(self, "role", "plain")
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(T("layout.gutter"))
        root.setAlignment(Qt.AlignTop)

        # 头像：嵌套回复用小一档，形成层级阶梯
        if isinstance(avatar, QPixmap):
            self._avatar.set_image(avatar)
        elif isinstance(avatar, str) and avatar:
            # 路径存在按图片处理，否则按名字文字头像
            import os
            if os.path.exists(avatar):
                self._avatar.set_image(avatar)
            else:
                self._avatar.set_text(avatar)
        else:
            self._avatar.set_text(author)
        root.addWidget(self._avatar, 0, Qt.AlignTop)

        # 右侧：头行（作者 + 时间）/ 正文 / 操作行 / 嵌套回复
        right = QVBoxLayout()
        right.setContentsMargins(0, 0, 0, 0)
        right.setSpacing(T("space.1"))
        root.addLayout(right, 1)

        head = QHBoxLayout()
        head.setContentsMargins(0, 0, 0, 0)
        head.setSpacing(T("space.2"))
        self._author_label = QLabel(author, self)
        set_font(self._author_label, "md", "semibold")
        self._time_label = QLabel(time, self)
        set_font(self._time_label, "xs", "regular")
        set_property(self._time_label, "role", "tertiary")
        # 关键：不同字阶按**基线**对齐（默认居中会让 md / xs 错行）
        head.addWidget(self._author_label, 0, Qt.AlignBaseline)
        head.addWidget(self._time_label, 0, Qt.AlignBaseline)
        head.addStretch(1)
        right.addLayout(head)

        self._content_label = QLabel(content, self)
        set_font(self._content_label, "md", "regular")
        self._content_label.setWordWrap(True)
        right.addWidget(self._content_label)

        # 操作行（透明容器，link 按钮本身无框）
        self._actions_host = QWidget(self)
        set_property(self._actions_host, "role", "plain")
        self._actions_row = QHBoxLayout(self._actions_host)
        self._actions_row.setContentsMargins(0, 0, 0, 0)
        self._actions_row.setSpacing(T("space.2"))
        self._actions_host.setVisible(False)
        right.addWidget(self._actions_host)
        if actions:
            self.set_actions(actions)

        # 嵌套回复
        self._replies_host = QWidget(self)
        set_property(self._replies_host, "role", "plain")
        self._replies = QVBoxLayout(self._replies_host)
        self._replies.setContentsMargins(0, 0, 0, 0)
        self._replies.setSpacing(T("layout.gutter"))
        self._replies_host.setVisible(False)
        right.addWidget(self._replies_host)
        self._set_nested(bool(nested))

    def _set_nested(self, nested: bool) -> None:
        """切换层级：头像降一档，正文左缘随之形成阶梯。"""
        self._nested = bool(nested)
        self._avatar.set_size("sm" if self._nested else "md")

    # ------------------------------------------------------------------ 配置
    def is_nested(self) -> bool:
        """是否为嵌套回复。"""
        return self._nested

    def set_actions(self, actions) -> None:
        """设置操作行按钮（link 样式，点击发出 ``action_triggered``）。"""
        while self._actions_row.count():
            item = self._actions_row.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
        for name in actions:
            btn = QPushButton(str(name), self._actions_host)
            set_property(btn, "variant", "link")
            set_property(btn, "size", "sm")
            btn.setCursor(Qt.PointingHandCursor)
            btn.clicked.connect(
                lambda _=False, n=str(name): self.action_triggered.emit(n))
            self._actions_row.addWidget(btn, 0, Qt.AlignTop)
        self._actions_row.addStretch(1)
        self._actions_host.setVisible(True)

    def add_reply(self, reply: "CommentView") -> None:
        """添加一条嵌套回复（左侧缩进参考线，缩进量取 layout 令牌）。"""
        # 层级缩进由 wrapper 的布局内边距承担，回复控件自身不再重复缩进
        reply._set_nested(True)
        wrapper = QWidget(self._replies_host)
        set_property(wrapper, "role", "plain")
        row = QHBoxLayout(wrapper)
        row.setContentsMargins(_THREAD_INDENT, 0, 0, 0)
        row.setSpacing(_THREAD_GAP)
        line = QFrame(wrapper)
        line.setFrameShape(QFrame.VLine)   # 全局 QSS 限宽 1px，色取 color.border
        row.addWidget(line, 0, Qt.AlignTop)
        row.addWidget(reply, 1)
        self._replies.addWidget(wrapper)
        self._replies_host.setVisible(True)

    def reply_count(self) -> int:
        return self._replies.count()

    def set_content(self, text: str) -> None:
        """更新评论正文。"""
        self._content_label.setText(text)

    def content(self) -> str:
        return self._content_label.text()

    def author(self) -> str:
        return self._author_label.text()