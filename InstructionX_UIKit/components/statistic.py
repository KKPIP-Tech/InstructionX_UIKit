# -*- coding: utf-8 -*-
"""数值统计组件（SPEC §5.2 statistic）。

标题 + 大数值 + 前 / 后缀 + 趋势箭头（上升绿 / 下降红）。

对齐要点（本轨重点）：

- **数字与前后缀共用一条基线**：前缀（¥）、数字、后缀（人）用
  ``Qt.AlignBaseline`` 加入同一行——用 ``AlignBottom`` 时小字的前后缀
  会吊在大字底边，视觉上「浮」起来；用 ``AlignVCenter`` 则基线随字号漂。
  趋势百分比同样按基线对齐，箭头按几何中心与趋势文字对齐。
- **字号走 ``set_font``（实例级 QSS）而不是 ``setFont()``**：全局
  ``QWidget { font-size }`` 优先级更高，``setFont`` 设的 ``font.display``
  会被静默覆盖成正文 13px——「统计数值」看上去和标题一样大，层级全塌了。
- 趋势组不再套一层容器 widget：直接进同一行，少一层嵌套、也少一次
  可见性切换带来的几何抖动。
"""

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath
from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget

from InstructionX_UIKit.theme import T, ThemeManager, set_font, set_property

__all__ = ["Statistic"]

#: 趋势箭头尺寸（px）：字形尺寸，非版面度量
_ARROW_W = 10
_ARROW_H = 12


class _TrendArrow(QWidget):
    """小三角箭头（自绘，按角色取色）。"""

    def __init__(self, up: bool = True, parent=None):
        super().__init__(parent)
        self._up = up
        self._role = "success" if up else "danger"
        self.setFixedSize(QSize(_ARROW_W, _ARROW_H))
        ThemeManager.instance().theme_changed.connect(self.update)

    def set_up(self, up: bool) -> None:
        self._up = bool(up)
        self._role = "success" if up else "danger"
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt 回调
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
        self._trend_percent = 0.0
        set_property(self, "role", "plain")

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(T("space.05"))

        self._title_label = QLabel(title, self)
        set_property(self._title_label, "role", "secondary")
        set_font(self._title_label, "md")
        root.addWidget(self._title_label)

        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(T("space.05"))
        self._prefix_label = QLabel(self)
        set_font(self._prefix_label, "lg")
        self._prefix_label.setVisible(False)
        self._value_label = QLabel(self)
        # 数字强调：display 字阶 + semibold 字重（契约 §6：数字强调用 medium /
        # semibold）。必须走 set_font，setFont 会被全局 QSS 覆盖。
        set_font(self._value_label, "display", "semibold")
        self._suffix_label = QLabel(self)
        set_font(self._suffix_label, "lg")
        self._suffix_label.setVisible(False)

        self._arrow = _TrendArrow(True, self)
        self._arrow.setVisible(False)
        self._trend_label = QLabel(self)
        set_font(self._trend_label, "sm", "medium")
        self._trend_label.setVisible(False)

        # 前缀 / 数字 / 后缀 / 趋势百分比共用一条基线；箭头按几何中心与
        # 趋势文字对齐（箭头不是文字，没有基线可言）
        row.addWidget(self._prefix_label, 0, Qt.AlignBaseline)
        row.addWidget(self._value_label, 0, Qt.AlignBaseline)
        row.addWidget(self._suffix_label, 0, Qt.AlignBaseline)
        # 趋势组与数值组之间留一格，趋势箭头排在百分比之前（读作「↑ 12.5%」）
        row.addSpacing(T("space.1"))
        row.addWidget(self._arrow, 0, Qt.AlignVCenter)
        row.addWidget(self._trend_label, 0, Qt.AlignBaseline)
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
        self._arrow.setVisible(True)
        self._trend_label.setVisible(True)

    def clear_trend(self) -> None:
        """隐藏趋势箭头。"""
        self._arrow.setVisible(False)
        self._trend_label.setVisible(False)

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
        # 注意顺序：``setStyleSheet`` 是整体替换，先 ``set_font`` 写入字号 /
        # 字重，再把语义色**追加**到同一条样式里——反过来写会把 set_font
        # 设的字阶抹掉（这是「实例级 QSS 也是单一来源」的常见坑）。
        set_font(self._trend_label, "sm", "medium")
        self._trend_label.setStyleSheet(
            self._trend_label.styleSheet()
            + f"color: {T(f'color.{role}')}; background: transparent;"
        )