# -*- coding: utf-8 -*-
"""空状态组件（SPEC §5.2 empty）。

自绘简洁几何插画（托盘 + 纸张）+ 标题 + 描述文本 + 可选操作按钮槽；
插画颜色全部取主题令牌，亮 / 暗实时感知。

扁平化与比例（与 COMPONENT-DESIGN-CONTRACT §4 / §5 对齐）：

- **四段间距成比例**：插画→标题 ``space.4``（16）＞ 标题→说明
  ``space.1``（4，主节奏 4 的最小档，用于「同一句话的两行」）＜
  说明→操作 ``space.4``（16）。旧版三段一律 ``space.2``（8），
  插画与文字黏在一起、按钮又贴得太近，三者毫无比例关系。
- **文字层级两级**：标题 ``title.md`` + ``semibold`` + ``text.primary``，
  说明 ``md`` + ``regular`` + ``text.secondary``。旧版只有一条
  ``tertiary`` 说明，标题与说明挤成同一层灰。
- **不套框**：组件本体透明（``role="plain"``），不引入卡片边线；
  插画外圈不加装饰性圆环。
- 所有几何与间距均由令牌派生，无裸数字。
"""

from PySide6.QtCore import QRectF, QSize, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QLabel, QPushButton, QVBoxLayout, QWidget

from InstructionX_UIKit.theme import T, ThemeManager, set_font, set_property

__all__ = ["Empty"]

# ---------------------------------------------------------------------------
# 插画几何（全部由令牌派生，避免裸数字）
# ---------------------------------------------------------------------------

#: 插画画布宽 / 高（由上面的元素几何派生，见下方各常量）
# ---------------------------------------------------------------------------

#: 纸张宽（= space.12 + space.2）
_PAPER_W = T("space.12") + T("space.2")
#: 纸张高（= space.16 + space.05）
_PAPER_H = T("space.16") + T("space.05")
#: 纸张上边（画布顶到纸张顶）
_PAPER_TOP = T("space.2")
#: 纸张叠放偏移（右 / 上）
_PAPER_DX = T("space.1")
_PAPER_DY = T("space.1")
#: 托盘宽（= 2 × 纸张宽 + 2 × space.4），画布两侧各留 space.4 呼吸位
_TRAY_W = 2 * _PAPER_W + 2 * T("space.4")
#: 托盘高
_TRAY_H = T("space.8")
#: 托盘上边：与纸张底部交叠 space.1（4px），视觉上「纸压在盘上」
_TRAY_TOP = _PAPER_TOP + _PAPER_H - T("space.1")
#: 插画画布高（托盘底 + 下边距）
_ART_H = _TRAY_TOP + _TRAY_H + T("space.2")
#: 插画画布宽
_ART_W = _TRAY_W + 2 * T("space.4")
#: 托盘凹槽宽（略窄于纸张）
_NOTCH_W = _PAPER_W + T("space.1")
#: 圆角：插画内的小元素按物理尺寸取小档
_RADIUS_SM = T("radius.sm")
_RADIUS_MD = T("radius.md")


class _Illustration(QWidget):
    """空状态插画：纸张叠在托盘上的简洁几何图形。

    线条 1px、颜色全部取令牌；只有主色小图钉一处强调，不加投影。
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(QSize(_ART_W, _ART_H))
        set_property(self, "role", "plain")
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

        # 纸张（两张叠放，后一张略微右移 + 上移）
        paper_top = _PAPER_TOP
        back = QRectF(cx - _PAPER_W / 2 + _PAPER_DX, paper_top - _PAPER_DY,
                      _PAPER_W, _PAPER_H)
        painter.setPen(QPen(line))
        painter.setBrush(subtle)
        painter.drawRoundedRect(back, _RADIUS_SM, _RADIUS_SM)
        paper = QRectF(cx - _PAPER_W / 2, paper_top, _PAPER_W, _PAPER_H)
        painter.setPen(QPen(border))
        painter.setBrush(elevated)
        painter.drawRoundedRect(paper, _RADIUS_SM, _RADIUS_SM)
        # 纸上的文字行：线宽 2px = space.05，行距 space.2（4px 主节奏）
        painter.setPen(QPen(line, T("space.05"), Qt.SolidLine, Qt.RoundCap))
        line1_y = int(paper.top() + T("space.4"))
        line2_y = int(paper.top() + T("space.6"))
        inset = T("space.2")
        painter.drawLine(int(paper.left() + inset), line1_y,
                         int(paper.right() - inset), line1_y)
        painter.drawLine(int(paper.left() + inset), line2_y,
                         int(paper.right() - inset - T("space.1")), line2_y)
        # 主色小图钉（唯一强调点，半径 = space.1 / 2）
        painter.setPen(Qt.NoPen)
        painter.setBrush(primary)
        pin_r = T("space.1")
        painter.drawEllipse(
            QRectF(paper.center().x() - pin_r, paper.top() - pin_r,
                   2 * pin_r, 2 * pin_r))

        # 托盘
        tray = QRectF(cx - _TRAY_W / 2, _TRAY_TOP, _TRAY_W, _TRAY_H)
        tray_path = QPainterPath()
        tray_path.addRoundedRect(tray, _RADIUS_MD, _RADIUS_MD)
        painter.setPen(QPen(border))
        painter.setBrush(muted)
        painter.drawPath(tray_path)
        # 托盘正面凹槽（与底色同系，仅靠明度差表达层次，不加描边）
        notch_h = T("space.2")
        notch = QRectF(cx - _NOTCH_W / 2, tray.top() + 1, _NOTCH_W, notch_h)
        painter.setPen(Qt.NoPen)
        painter.setBrush(subtle)
        painter.drawRoundedRect(notch, _RADIUS_SM, _RADIUS_SM)
        painter.end()


class Empty(QWidget):
    """空状态占位。

    参数:
        description: 描述文本，默认 ``"暂无数据"``。
        title: 可选标题（为空则不显示标题行）。
        parent: 父控件。

    示例::

        empty = Empty("还没有任何订单")
        empty.set_title("订单为空")
        empty.set_action("去创建", callback=create_order)
    """

    def __init__(self, description: str = "暂无数据", title: str = "",
                 parent=None):
        super().__init__(parent)
        # 透明层：空状态是被放进卡片 / 页面里的占位，不能自己再画一块面
        set_property(self, "role", "plain")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(T("layout.card.pad_x"), T("layout.card.pad_top"),
                                  T("layout.card.pad_x"), T("layout.card.pad_bottom"))
        # 段落级间距 = 插画→标题 / 说明→操作（16）；标题→说明由独立
        # 子布局单独控制为 4，实现「成比例」而不是一律 8。
        layout.setSpacing(T("space.4"))
        layout.addStretch(1)

        self._illustration = _Illustration(self)
        layout.addWidget(self._illustration, 0, Qt.AlignHCenter)

        # 标题 + 说明：两行同一段落，间距取半档（4）
        text_host = QWidget(self)
        set_property(text_host, "role", "plain")
        text_layout = QVBoxLayout(text_host)
        text_layout.setContentsMargins(0, 0, 0, 0)
        text_layout.setSpacing(T("space.1"))

        self._title_label = QLabel(title, text_host)
        set_font(self._title_label, "title.md", "semibold")
        self._title_label.setAlignment(Qt.AlignCenter)
        self._title_label.setVisible(bool(title))
        text_layout.addWidget(self._title_label)

        self._desc_label = QLabel(description, text_host)
        set_font(self._desc_label, "md", "regular")
        set_property(self._desc_label, "role", "secondary")
        self._desc_label.setAlignment(Qt.AlignCenter)
        text_layout.addWidget(self._desc_label)
        layout.addWidget(text_host, 0)

        self._action_host = QWidget(self)
        set_property(self._action_host, "role", "plain")
        action_row = QVBoxLayout(self._action_host)
        action_row.setContentsMargins(0, 0, 0, 0)
        action_row.setSpacing(0)
        self._action_layout = action_row
        self._action_host.setVisible(False)
        layout.addWidget(self._action_host, 0, Qt.AlignHCenter)
        layout.addStretch(1)
        self.setMinimumSize(
            T("space.16") + T("space.8") + T("space.16"),
            _ART_H + T("space.4") + T("space.4"))

    # ------------------------------------------------------------------ 配置
    def set_title(self, text: str) -> None:
        """设置标题；空串隐藏标题行。"""
        self._title_label.setText(text)
        self._title_label.setVisible(bool(text))

    def title(self) -> str:
        return self._title_label.text()

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
        """用自定义控件填充操作槽（替换旧控件，旧控件销毁）。"""
        while self._action_layout.count():
            item = self._action_layout.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
        self._action_layout.addWidget(widget, 0, Qt.AlignHCenter)
        self._action_host.setVisible(True)