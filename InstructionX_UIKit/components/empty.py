# -*- coding: utf-8 -*-
"""空状态组件（SPEC §5.2 empty）。

自绘简洁几何插画（托盘 + 纸张）+ 描述文本 + 可选操作按钮槽；
插画颜色全部取主题令牌，亮 / 暗实时感知。
"""

from PySide6.QtCore import QRectF, QSize, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QLabel, QPushButton, QVBoxLayout, QWidget

from InstructionX_UIKit.theme import T, ThemeManager, set_property

__all__ = ["Empty"]


class _Illustration(QWidget):
    """空状态插画：纸张叠在托盘上的简洁几何图形。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(QSize(200, 120))
        ThemeManager.instance().theme_changed.connect(self.update)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        cx = self.width() / 2

        border = QColor(T("color.border.strong"))
        line = QColor(T("color.border"))
        subtle = QColor(T("color.bg.subtle"))
        muted = QColor(T("color.bg.muted"))
        elevated = QColor(T("color.bg.elevated"))
        primary = QColor(T("color.primary"))

        # 纸张（两张叠放）
        back = QRectF(cx - 26, 10, 56, 66)
        painter.setPen(QPen(line))
        painter.setBrush(subtle)
        painter.drawRoundedRect(back.translated(6, -4), 5, 5)
        paper = QRectF(cx - 32, 14, 56, 66)
        painter.setPen(QPen(border))
        painter.setBrush(elevated)
        painter.drawRoundedRect(paper, 5, 5)
        # 纸上的文字行
        painter.setPen(QPen(line, 2, Qt.SolidLine, Qt.RoundCap))
        painter.drawLine(int(paper.left() + 10), int(paper.top() + 18),
                         int(paper.right() - 10), int(paper.top() + 18))
        painter.drawLine(int(paper.left() + 10), int(paper.top() + 30),
                         int(paper.right() - 20), int(paper.top() + 30))
        # 主色小图钉
        painter.setPen(Qt.NoPen)
        painter.setBrush(primary)
        painter.drawEllipse(QRectF(paper.center().x() - 4, paper.top() - 4, 8, 8))

        # 托盘
        tray = QRectF(cx - 74, 74, 148, 34)
        tray_path = QPainterPath()
        tray_path.addRoundedRect(tray, 6, 6)
        painter.setPen(QPen(border))
        painter.setBrush(muted)
        painter.drawPath(tray_path)
        # 托盘凹槽
        notch = QRectF(cx - 30, tray.top() + 1, 60, 12)
        notch_path = QPainterPath()
        notch_path.addRoundedRect(notch, 0, 0)
        painter.setPen(QPen(border))
        painter.setBrush(subtle)
        painter.drawRoundedRect(notch, 4, 4)
        painter.fillRect(QRectF(notch.left(), notch.top(), notch.width(), 5), subtle)
        painter.end()


class Empty(QWidget):
    """空状态占位。

    参数:
        description: 描述文本，默认 ``"暂无数据"``。
        parent: 父控件。

    示例::

        empty = Empty("还没有任何订单")
        empty.set_action("去创建", callback=create_order)
    """

    def __init__(self, description: str = "暂无数据", parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(T("space.4"), T("space.4"),
                                  T("space.4"), T("space.4"))
        layout.setSpacing(T("space.2"))
        layout.addStretch(1)

        self._illustration = _Illustration(self)
        layout.addWidget(self._illustration, 0, Qt.AlignHCenter)

        self._desc_label = QLabel(description, self)
        set_property(self._desc_label, "role", "tertiary")
        self._desc_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self._desc_label)

        self._action_host = QWidget(self)
        action_row = QVBoxLayout(self._action_host)
        action_row.setContentsMargins(0, T("space.1"), 0, 0)
        action_row.setSpacing(0)
        self._action_layout = action_row
        self._action_host.setVisible(False)
        layout.addWidget(self._action_host, 0, Qt.AlignHCenter)
        layout.addStretch(1)
        self.setMinimumSize(240, 210)

    # ------------------------------------------------------------------ 配置
    def set_description(self, text: str) -> None:
        """设置描述文本。"""
        self._desc_label.setText(text)

    def description(self) -> str:
        return self._desc_label.text()

    def set_action(self, text: str, callback=None) -> QPushButton:
        """设置主操作按钮（primary 变体），返回该按钮。"""
        btn = QPushButton(text, self._action_host)
        set_property(btn, "variant", "primary")
        if callback is not None:
            btn.clicked.connect(callback)
        self.set_action_widget(btn)
        return btn

    def set_action_widget(self, widget: QWidget) -> None:
        """用自定义控件填充操作槽。"""
        while self._action_layout.count():
            item = self._action_layout.takeAt(0)
            if item.widget() is not None:
                item.widget().setParent(None)
        self._action_layout.addWidget(widget, 0, Qt.AlignHCenter)
        self._action_host.setVisible(True)
