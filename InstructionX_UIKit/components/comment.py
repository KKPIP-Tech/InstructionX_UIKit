# -*- coding: utf-8 -*-
"""评论组件（SPEC §5.2 comment）。

头像 + 作者 + 时间 + 内容 + 操作行，支持嵌套回复
（左侧缩进参考线分隔）。
"""

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from InstructionX_UIKit.theme import T, set_property

from .avatar import Avatar

__all__ = ["CommentView"]


class CommentView(QWidget):
    """单条评论（可嵌套回复）。

    参数:
        author: 作者名。
        content: 评论正文。
        time: 时间文本（如 ``"2 小时前"``）。
        avatar: 头像来源：QPixmap / 图片路径 / 名字（文字头像）/ None。
        actions: 操作行文本列表（如 ``["回复", "赞"]``）。
        parent: 父控件。

    示例::

        c = CommentView("张三", "写得很好", "2 小时前", actions=["回复"])
        reply = CommentView("李四", "同感", "1 小时前")
        c.add_reply(reply)
    """

    #: 操作行按钮被点击，参数为操作文本
    action_triggered = Signal(str)

    def __init__(self, author: str = "", content: str = "", time: str = "",
                 avatar=None, actions=None, parent=None):
        super().__init__(parent)
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(T("space.3"))
        root.setAlignment(Qt.AlignTop)

        # 头像
        self._avatar = Avatar(size="md")
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

        # 右侧
        right = QVBoxLayout()
        right.setContentsMargins(0, 0, 0, 0)
        right.setSpacing(T("space.1"))
        root.addLayout(right, 1)

        head = QHBoxLayout()
        head.setContentsMargins(0, 0, 0, 0)
        head.setSpacing(T("space.2"))
        self._author_label = QLabel(author, self)
        author_font = self._author_label.font()
        author_font.setBold(True)
        self._author_label.setFont(author_font)
        self._time_label = QLabel(time, self)
        set_property(self._time_label, "role", "tertiary")
        head.addWidget(self._author_label)
        head.addWidget(self._time_label)
        head.addStretch(1)
        right.addLayout(head)

        self._content_label = QLabel(content, self)
        self._content_label.setWordWrap(True)
        right.addWidget(self._content_label)

        # 操作行
        self._actions_host = QWidget(self)
        self._actions_row = QHBoxLayout(self._actions_host)
        self._actions_row.setContentsMargins(0, 0, 0, 0)
        self._actions_row.setSpacing(T("space.2"))
        self._actions_host.setVisible(False)
        right.addWidget(self._actions_host)
        if actions:
            self.set_actions(actions)

        # 嵌套回复
        self._replies_host = QWidget(self)
        self._replies = QVBoxLayout(self._replies_host)
        self._replies.setContentsMargins(0, 0, 0, 0)
        self._replies.setSpacing(T("space.3"))
        self._replies_host.setVisible(False)
        right.addWidget(self._replies_host)

    # ------------------------------------------------------------------ 配置
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
            btn.clicked.connect(lambda _=False, n=str(name): self.action_triggered.emit(n))
            self._actions_row.addWidget(btn)
        self._actions_row.addStretch(1)
        self._actions_host.setVisible(True)

    def add_reply(self, reply: "CommentView") -> None:
        """添加一条嵌套回复（带左侧缩进参考线）。"""
        wrapper = QWidget(self._replies_host)
        row = QHBoxLayout(wrapper)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(T("space.3"))
        line = QFrame(wrapper)
        line.setFrameShape(QFrame.VLine)
        row.addWidget(line)
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
