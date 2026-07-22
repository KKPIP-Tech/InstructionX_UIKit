# -*- coding: utf-8 -*-
"""数值统计组件（SPEC §5.2 statistic）。

标题 + 大数值 + 前 / 后缀 + 趋势箭头（上升绿 / 下降红）。
趋势箭头自绘，其余交给全局 QSS，主题实时感知。
"""

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath
from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget

from InstructionX_UIKit.theme import T, ThemeManager, set_property

__all__ = ["Statistic"]


class _TrendArrow(QWidget):
    """小三角箭头（自绘，按角色取色）。"""

    def __init__(self, up: bool = True, parent=None):
        super().__init__(parent)
        self._up = up
        self._role = "success" if up else "danger"
        self.setFixedSize(QSize(10, 12))
        ThemeManager.instance().theme_changed.connect(self.update)

    def set_up(self, up: bool) -> None:
        self._up = bool(up)
        self._role = "success" if up else "danger"
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(T(f"color.{self._role}")))
        w, h = self.width(), self.height()
        path = QPainterPath()
        if self._up:
            path.moveTo(w / 2, 1)
            path.lineTo(w - 1, h - 4)
            path.lineTo(1, h - 4)
        else:
            path.moveTo(w / 2, h - 1)
            path.lineTo(w - 1, 4)
            path.lineTo(1, 4)
        path.closeSubpath()
        painter.drawPath(path)
        painter.end()


class Statistic(QWidget):
    """统计数值展示。

    参数:
        title: 标题文本。
        value: 数值（int / float），可为 None 稍后设置。
        precision: 小数位数，默认 0。
        parent: 父控件。

    示例::

        stat = Statistic("活跃用户", 12800)
        stat.set_suffix("人")
        stat.set_trend(12.5)      # 上升绿色箭头 + 12.5%
    """

    def __init__(self, title: str = "", value=None, precision: int = 0, parent=None):
        super().__init__(parent)
        self._value = 0
        self._precision = int(precision)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(T("space.1"))

        self._title_label = QLabel(title, self)
        set_property(self._title_label, "role", "secondary")
        root.addWidget(self._title_label)

        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(T("space.1"))
        self._prefix_label = QLabel(self)
        self._prefix_label.setVisible(False)
        self._value_label = QLabel(self)
        value_font = self._value_label.font()
        value_font.setPixelSize(T("font.display"))
        value_font.setWeight(QFont.Weight.DemiBold)  # 600，即 semibold
        self._value_label.setFont(value_font)
        self._suffix_label = QLabel(self)
        self._suffix_label.setVisible(False)

        self._trend_host = QWidget(self)
        trend_row = QHBoxLayout(self._trend_host)
        trend_row.setContentsMargins(T("space.2"), 0, 0, 0)
        trend_row.setSpacing(3)
        self._arrow = _TrendArrow(True, self._trend_host)
        self._trend_label = QLabel(self._trend_host)
        trend_row.addWidget(self._arrow, 0, Qt.AlignVCenter)
        trend_row.addWidget(self._trend_label, 0, Qt.AlignVCenter)
        self._trend_host.setVisible(False)

        row.addWidget(self._prefix_label, 0, Qt.AlignBottom)
        row.addWidget(self._value_label, 0, Qt.AlignBottom)
        row.addWidget(self._suffix_label, 0, Qt.AlignBottom)
        row.addWidget(self._trend_host, 0, Qt.AlignVCenter)
        row.addStretch(1)
        root.addLayout(row)

        if value is not None:
            self.set_value(value)
        else:
            self._refresh_value()
        ThemeManager.instance().theme_changed.connect(self._refresh_trend_style)

    # ------------------------------------------------------------------ 配置
    def set_title(self, title: str) -> None:
        """设置标题。"""
        self._title_label.setText(title)

    def title(self) -> str:
        return self._title_label.text()

    def set_value(self, value, precision: int = None) -> None:
        """设置数值；``precision`` 可临时指定小数位。"""
        self._value = value
        if precision is not None:
            self._precision = int(precision)
        self._refresh_value()

    def value(self):
        return self._value

    def set_prefix(self, text: str) -> None:
        """设置前缀（如 ¥）。"""
        self._prefix_label.setText(text)
        self._prefix_label.setVisible(bool(text))

    def set_suffix(self, text: str) -> None:
        """设置后缀（如 人 / 单）。"""
        self._suffix_label.setText(text)
        self._suffix_label.setVisible(bool(text))

    def set_trend(self, percent: float) -> None:
        """设置趋势百分比：>=0 上升（绿），<0 下降（红）。"""
        self._trend_percent = float(percent)
        up = percent >= 0
        self._arrow.set_up(up)
        self._trend_label.setText(f"{abs(percent):g}%")
        self._refresh_trend_style()
        self._trend_host.setVisible(True)

    def clear_trend(self) -> None:
        """隐藏趋势箭头。"""
        self._trend_host.setVisible(False)

    # ------------------------------------------------------------------ 内部
    def _refresh_value(self) -> None:
        if isinstance(self._value, float):
            text = f"{self._value:,.{self._precision}f}"
        else:
            try:
                text = f"{int(self._value):,}"
            except (TypeError, ValueError):
                text = str(self._value)
        self._value_label.setText(text)

    def _refresh_trend_style(self) -> None:
        role = "success" if self._arrow._up else "danger"
        self._trend_label.setStyleSheet(
            f"color: {T(f'color.{role}')}; background: transparent;"
        )
