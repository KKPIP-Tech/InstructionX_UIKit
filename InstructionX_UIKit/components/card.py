# -*- coding: utf-8 -*-
"""卡片组件（SPEC §5.2 card）。

带标题 / 额外操作 / 底部槽位的容器卡片，支持 hoverable（悬停浮起）
与 bordered 变体；背景与边框自绘，亮 / 暗主题实时感知。
"""

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from InstructionX_UIKit.theme import T, ThemeManager, apply_shadow, set_property

__all__ = ["Card"]


class Card(QFrame):
    """内容卡片容器。

    参数:
        title: 标题文本（为空则不显示标题区）。
        bordered: 是否描边，默认 True。
        hoverable: 悬停时浮起（投影 + 主色描边），默认 False。
        parent: 父控件。

    示例::

        card = Card("订单概览", hoverable=True)
        card.set_extra(QPushButton("更多"))
        card.body_layout().addWidget(QLabel("正文内容"))
    """

    def __init__(self, title: str = "", bordered: bool = True,
                 hoverable: bool = False, parent=None):
        super().__init__(parent)
        self._bordered = bool(bordered)
        self._hoverable = bool(hoverable)
        self._hovered = False

        self._root = QVBoxLayout(self)
        self._root.setContentsMargins(T("space.4"), T("space.3"), T("space.4"), T("space.3"))
        self._root.setSpacing(T("space.2"))

        # 标题区：标题 + 右侧 extra 槽
        self._header = QWidget(self)
        header = QHBoxLayout(self._header)
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(T("space.2"))
        self._title_label = QLabel(title, self._header)
        title_font = self._title_label.font()
        title_font.setPixelSize(T("font.title.sm"))
        title_font.setBold(True)
        self._title_label.setFont(title_font)
        header.addWidget(self._title_label, 1)
        self._extra_slot = QHBoxLayout()
        self._extra_slot.setContentsMargins(0, 0, 0, 0)
        header.addLayout(self._extra_slot, 0)
        self._root.addWidget(self._header)
        self._header.setVisible(bool(title))

        # 正文区
        self._body = QWidget(self)
        self._body_layout = QVBoxLayout(self._body)
        self._body_layout.setContentsMargins(0, 0, 0, 0)
        self._body_layout.setSpacing(T("space.2"))
        self._root.addWidget(self._body, 1)

        # 底部槽
        self._footer = QWidget(self)
        self._footer_layout = QHBoxLayout(self._footer)
        self._footer_layout.setContentsMargins(0, T("space.2"), 0, 0)
        self._footer_layout.setSpacing(T("space.2"))
        self._footer.setVisible(False)
        self._root.addWidget(self._footer)

        set_property(self, "variant", "card")
        ThemeManager.instance().theme_changed.connect(self.update)

    # ------------------------------------------------------------------ 槽位
    def set_title(self, title: str) -> None:
        """设置标题；空串隐藏标题区。"""
        self._title_label.setText(title)
        self._header.setVisible(bool(title))

    def title(self) -> str:
        return self._title_label.text()

    def set_extra(self, widget: QWidget) -> None:
        """设置标题区右侧的额外操作控件。"""
        while self._extra_slot.count():
            item = self._extra_slot.takeAt(0)
            if item.widget() is not None:
                item.widget().setParent(None)
        self._extra_slot.addWidget(widget)
        self._header.setVisible(True)

    def body_layout(self) -> QVBoxLayout:
        """正文布局（向其中添加内容控件）。"""
        return self._body_layout

    def set_widget(self, widget: QWidget) -> None:
        """便捷方法：用单个控件填满正文区。"""
        self._body_layout.addWidget(widget)

    def set_footer(self, footer) -> None:
        """设置底部槽：控件或文本（自动包成弱化标签）。"""
        while self._footer_layout.count():
            item = self._footer_layout.takeAt(0)
            if item.widget() is not None:
                item.widget().setParent(None)
        if isinstance(footer, str):
            label = QLabel(footer, self._footer)
            set_property(label, "role", "secondary")
            footer = label
        self._footer_layout.addWidget(footer)
        self._footer.setVisible(True)

    # ------------------------------------------------------------------ 变体
    def set_bordered(self, bordered: bool) -> None:
        """是否描边。"""
        self._bordered = bool(bordered)
        self.update()

    def is_bordered(self) -> bool:
        return self._bordered

    def set_hoverable(self, hoverable: bool) -> None:
        """悬停浮起开关。"""
        self._hoverable = bool(hoverable)
        self.setAttribute(Qt.WA_Hover, hoverable)
        self.update()

    def is_hoverable(self) -> bool:
        return self._hoverable

    # ------------------------------------------------------------------ 事件
    def enterEvent(self, event) -> None:
        self._hovered = True
        if self._hoverable:
            apply_shadow(self, "md")
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._hovered = False
        if self._hoverable:
            self.setGraphicsEffect(None)
        self.update()
        super().leaveEvent(event)

    # ------------------------------------------------------------------ 绘制
    def paintEvent(self, event) -> None:
        super().paintEvent(event)  # 先让样式画 QSS 底色，再覆盖自绘卡片背景
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = self.rect().adjusted(0, 0, -1, -1)
        radius = T("radius.lg")
        path = QPainterPath()
        path.addRoundedRect(rect, radius, radius)

        painter.fillPath(path, QColor(T("color.bg.elevated")))
        if self._bordered:
            border = T("color.primary") if (self._hoverable and self._hovered) else T("color.border")
            pen = painter.pen()
            pen.setColor(QColor(border))
            pen.setWidth(1)
            painter.setPen(pen)
            painter.setBrush(Qt.NoBrush)
            painter.drawPath(path)
        painter.end()
