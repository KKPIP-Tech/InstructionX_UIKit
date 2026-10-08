# -*- coding: utf-8 -*-
"""卡片组件（SPEC §5.2 card）。

带标题 / 额外操作 / 底部槽位的容器卡片，支持 hoverable（悬停主色描边
高亮，自绘实现，不使用 QGraphicsDropShadowEffect——项目红线）与
bordered 变体；背景与边框自绘，亮 / 暗主题实时感知。

扁平化约定（与 COMPONENT-DESIGN-CONTRACT §4 对齐）：

- **内部只有一层框**：卡片自身是唯一有边框的层；标题区 / 正文区 /
  底部区都是透明容器，彼此之间只用留白（间距令牌）分区，不再各自套框。
- **底部槽用一条 1px 细线分隔**（``color.border``，非 ``border.strong``），
  这是唯一的内部线条；不使用投影——普通控件禁用投影（§4）。
- **内边距全部走令牌**：左右 ``layout.card.pad_x``，上 ``layout.card.pad_top``，
  下 ``layout.card.pad_bottom``；段落间距 ``layout.card.gap``，
  标题与 extra 之间 ``layout.icon.gap``。
- **字阶走 ``set_font``**：全局 ``QWidget { font-size }`` 会覆盖 ``setFont``，
  标题必须用实例级 QSS 才能拿到 ``title.sm`` 字阶（§6）。
"""

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from InstructionX_UIKit.theme import T, ThemeManager, set_font, set_property

__all__ = ["Card"]


class Card(QFrame):
    """内容卡片容器。

    参数:
        title: 标题文本（为空则不显示标题区）。
        bordered: 是否描边，默认 True。
        hoverable: 悬停时主色描边高亮，默认 False。
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
        self._root.setContentsMargins(
            T("layout.card.pad_x"), T("layout.card.pad_top"),
            T("layout.card.pad_x"), T("layout.card.pad_bottom"))
        self._root.setSpacing(T("layout.card.gap"))

        # 标题区：标题 + 右侧 extra 槽（透明容器，无独立边框）
        self._header = QWidget(self)
        set_property(self._header, "role", "plain")
        header = QHBoxLayout(self._header)
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(T("layout.icon.gap"))
        self._title_label = QLabel(title, self._header)
        set_font(self._title_label, "title.sm", "semibold")
        header.addWidget(self._title_label, 1)
        self._extra_slot = QHBoxLayout()
        self._extra_slot.setContentsMargins(0, 0, 0, 0)
        self._extra_slot.setSpacing(T("layout.icon.gap"))
        header.addLayout(self._extra_slot, 0)
        self._root.addWidget(self._header)
        self._header.setVisible(bool(title))

        # 正文区
        self._body = QWidget(self)
        set_property(self._body, "role", "plain")
        self._body_layout = QVBoxLayout(self._body)
        self._body_layout.setContentsMargins(0, 0, 0, 0)
        self._body_layout.setSpacing(T("layout.card.gap"))
        self._root.addWidget(self._body, 1)

        # 底部槽（上方一条 1px 细线，其余靠留白）
        self._footer = QWidget(self)
        set_property(self._footer, "role", "plain")
        self._footer_layout = QHBoxLayout(self._footer)
        self._footer_layout.setContentsMargins(0, T("layout.card.gap"), 0, 0)
        self._footer_layout.setSpacing(T("layout.card.gap"))
        self._footer.setVisible(False)
        self._root.addWidget(self._footer)

        ThemeManager.instance().theme_changed.connect(self.update)

    # ------------------------------------------------------------------ 槽位
    def set_title(self, title: str) -> None:
        """设置标题；空串隐藏标题区。"""
        self._title_label.setText(title)
        self._header.setVisible(bool(title))

    def title(self) -> str:
        return self._title_label.text()

    def set_extra(self, widget: QWidget) -> None:
        """设置标题区右侧的额外操作控件（替换旧控件，旧控件销毁）。"""
        while self._extra_slot.count():
            item = self._extra_slot.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
        self._extra_slot.addWidget(widget, 0, Qt.AlignVCenter)
        self._header.setVisible(True)

    def body_layout(self) -> QVBoxLayout:
        """正文布局（向其中添加内容控件）。"""
        return self._body_layout

    def set_widget(self, widget: QWidget) -> None:
        """便捷方法：用单个控件填满正文区。"""
        self._body_layout.addWidget(widget)

    def set_footer(self, footer) -> None:
        """设置底部槽：控件或文本（自动包成次级色标签）。

        替换旧内容，旧控件销毁。
        """
        while self._footer_layout.count():
            item = self._footer_layout.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
        if isinstance(footer, str):
            label = QLabel(footer, self._footer)
            set_font(label, "sm", "regular")
            set_property(label, "role", "secondary")
            footer = label
        self._footer_layout.addWidget(footer, 0, Qt.AlignVCenter)
        self._footer_layout.addStretch(1)
        self._footer.setVisible(True)
        self.update()

    # ------------------------------------------------------------------ 变体
    def set_bordered(self, bordered: bool) -> None:
        """是否描边。"""
        self._bordered = bool(bordered)
        self.update()

    def is_bordered(self) -> bool:
        return self._bordered

    def set_hoverable(self, hoverable: bool) -> None:
        """悬停高亮开关（主色描边，自绘实现）。"""
        self._hoverable = bool(hoverable)
        self.setAttribute(Qt.WA_Hover, hoverable)
        self.update()

    def is_hoverable(self) -> bool:
        return self._hoverable

    # ------------------------------------------------------------------ 事件
    def enterEvent(self, event) -> None:
        self._hovered = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._hovered = False
        self.update()
        super().leaveEvent(event)

    # ------------------------------------------------------------------ 绘制
    def paintEvent(self, event) -> None:
        # 背景 / 边框 / 底部槽细线全部自绘：全局基座 QSS 给 QFrame 的
        # 「底色 + 边框」与这里重复一层会形成双框，故先擦掉样式底再画一次，
        # 保证卡片只有一层圆角矩形轮廓。
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = self.rect().adjusted(0, 0, -1, -1)
        radius = T("radius.lg")
        path = QPainterPath()
        path.addRoundedRect(rect, radius, radius)

        painter.fillPath(path, QColor(T("color.bg.base")))
        if self._bordered:
            border = T("color.primary") if (self._hoverable and self._hovered) \
                else T("color.border")
            pen = QPen(QColor(border))
            pen.setWidth(1)
            painter.setPen(pen)
            painter.setBrush(Qt.NoBrush)
            painter.drawPath(path)
        else:
            painter.setPen(Qt.NoPen)

        # 底部槽与正文之间：一条 1px 细线（唯一的内部线条）
        if self._footer.isVisible():
            line_y = self._footer.y() - T("layout.card.gap") // 2
            pen = QPen(QColor(T("color.border")))
            pen.setWidth(1)
            painter.setPen(pen)
            radius_in = T("layout.card.pad_x")
            painter.drawLine(radius_in, line_y, rect.right() - radius_in, line_y)
        painter.end()