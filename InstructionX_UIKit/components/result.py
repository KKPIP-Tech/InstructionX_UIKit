# -*- coding: utf-8 -*-
"""结果页 ResultView（SPEC §5.3 result.py）。

success / error / info / warning / 404 自绘图标 + 标题 + 副标题 + 操作区。

排版要点：

- **图标**：64px 圆形（自绘，主题感知），404 也走同一枚圆形容器，避免
  「四个有圆、��个没有」的不齐；圆角取 ``radius.lg`` 一档的观感但按物理
  尺寸收敛（半径不超过直径一半）。
- **三段间距**：图标↔标题 12 / 标题↔副标题 8 / 副标题↔操作 24，全部取
  ``space.*`` 令牌；操作区**居中**（此前是左对齐，与居中的标题副标题不齐）。
- **副标题**：自行折行并锁定高度（契约 §7），窗口变窄时按可用宽度重折，
  不依赖 ``QLabel.setWordWrap`` 的 ``minimumSizeHint``（在滚动布局里会被压扁）。
"""

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ..theme import T, set_font, set_property
from ..tokens import TokenState
from .dialog import _connect_theme, body_font, wrap_text

__all__ = ["ResultView"]

#: 状态图标边长（圆形，密度版：原 88px 在三列并排时过于抢眼）
_ICON_SIDE = T("space.16")
#: 状态图标主体半径
_ICON_RADIUS = T("space.5")
#: 404 容器半径（数字比勾 / 叉宽，单独放大一档才装得下）
_404_RADIUS = T("space.6")
#: 光晕外扩（状态色的低透明度底，用来托住主体圆）
_HALO_GAP = T("space.05")
#: 副标题折行宽度上限（超宽容器下不至于拉成一行长句）
_SUB_MAX_W = T("space.16") * 4
#: 构造期预排用的窄宽度：控件最小宽度由「最长折行 + 内边距」决定，
#: 若一上来就按 256px 排版，组件最小宽度会被撑到 288px，窄容器放不下
_SUB_NARROW_W = T("space.16") * 2


class _ResultIcon(QWidget):
    """结果页状态图标（自绘，主题感知）。"""

    def __init__(self, status: str, parent: QWidget = None):
        super().__init__(parent)
        self._status = status
        self.setFixedSize(_ICON_SIDE, _ICON_SIDE)
        _connect_theme(self, self.update)

    def set_status(self, status: str) -> None:
        self._status = status
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        c = lambda k: T(f"color.{k}")  # noqa: E731
        cx, cy = self.width() / 2.0, self.height() / 2.0
        r = float(_404_RADIUS if self._status == "404" else _ICON_RADIUS)
        painter.setPen(Qt.NoPen)
        if self._status == "404":
            # 404 与其余状态同一枚容器：底色用 muted，数字用三级文字色
            painter.setBrush(QColor(c("bg.muted")))
            painter.drawEllipse(QPointF(cx, cy), r, r)
            painter.setPen(QColor(c("text.tertiary")))
            painter.setFont(TokenState.instance().font("title.lg", "bold"))
            painter.drawText(QRectF(cx - r, cy - r, r * 2, r * 2),
                             Qt.AlignCenter, "404")
            painter.end()
            return
        main = {"success": c("success"), "error": c("danger"),
                "warning": c("warning"), "info": c("primary")}[self._status]
        # 外圈浅色光晕
        halo = QColor(main)
        halo.setAlpha(40)
        painter.setBrush(halo)
        painter.drawEllipse(QPointF(cx, cy), r + _HALO_GAP, r + _HALO_GAP)
        # 主体圆
        painter.setBrush(QColor(main))
        painter.drawEllipse(QPointF(cx, cy), r, r)
        on = QColor(c("on.primary"))
        if self._status in ("success", "error"):
            pen = QPen(on)
            pen.setWidthF(max(2.0, r / 8.0))
            pen.setCapStyle(Qt.RoundCap)
            pen.setJoinStyle(Qt.RoundJoin)
            painter.setPen(pen)
            if self._status == "success":
                painter.drawPolyline([
                    QPointF(cx - r * 0.42, cy),
                    QPointF(cx - r * 0.10, cy + r * 0.34),
                    QPointF(cx + r * 0.46, cy - r * 0.32),
                ])
            else:
                painter.drawLine(QPointF(cx - r * 0.28, cy - r * 0.28),
                                 QPointF(cx + r * 0.28, cy + r * 0.28))
                painter.drawLine(QPointF(cx + r * 0.28, cy - r * 0.28),
                                 QPointF(cx - r * 0.28, cy + r * 0.28))
        else:
            painter.setFont(TokenState.instance().font("display", "bold"))
            painter.setPen(on)
            painter.drawText(QRectF(cx - r, cy - r, r * 2, r * 2),
                             Qt.AlignCenter,
                             "i" if self._status == "info" else "!")
        painter.end()


class ResultView(QWidget):
    """结果页：操作结果的整页反馈。

    参数:
        status: ``"success"`` / ``"error"`` / ``"info"`` / ``"warning"`` /
            ``"404"``。
        title: 主标题。
        subtitle: 副标题说明。
        parent: 父控件。

    示例::

        rv = ResultView("success", "提交成功", "我们将在 2 个工作日内处理")
        rv.add_action("返回首页", lambda: print("home"), variant="primary")
        layout.addWidget(rv)
    """

    #: 合法状态
    STATUSES = ("success", "error", "info", "warning", "404")

    def __init__(self, status: str = "success", title: str = "",
                 subtitle: str = "", parent: QWidget = None):
        super().__init__(parent)
        if status not in self.STATUSES:
            raise ValueError(
                f"未知结果状态: {status!r}，应为 {self.STATUSES} 之一")
        self._subtitle_text = subtitle
        # 垂直方向可伸展：并排放置时（Demo 的三列结果页）与同排兄弟取到
        # 同一高度，图标 / 标题 / 操作区才会落在同一条水平线上
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(T("space.5"), T("space.5"),
                                  T("space.5"), T("space.5"))
        layout.setSpacing(0)
        layout.addStretch(1)          # 上下各一份，整块在容器中垂直居中

        self._icon = _ResultIcon(status, self)
        layout.addWidget(self._icon, 0, Qt.AlignHCenter)
        layout.addSpacing(T("space.3"))

        self._title = QLabel(title, self)
        set_font(self._title, "title.lg", "semibold")
        self._title.setAlignment(Qt.AlignCenter)
        layout.addWidget(self._title)
        layout.addSpacing(T("space.2"))

        self._subtitle = QLabel(self)
        set_font(self._subtitle, "md", "regular")
        set_property(self._subtitle, "role", "secondary")
        self._subtitle.setAlignment(Qt.AlignHCenter | Qt.AlignTop)
        sub_row = QHBoxLayout()
        sub_row.addStretch(1)
        sub_row.addWidget(self._subtitle)
        sub_row.addStretch(1)
        layout.addLayout(sub_row)
        layout.addSpacing(T("space.6"))

        # 操作区与标题 / 副标题同轴居中（此前左对齐，三段基线互相打架）
        self._actions = QHBoxLayout()
        self._actions.setSpacing(T("layout.inline.gap"))
        action_row = QHBoxLayout()
        action_row.addStretch(1)
        action_row.addLayout(self._actions)
        action_row.addStretch(1)
        layout.addLayout(action_row)
        layout.addStretch(1)

        self._reflow_subtitle(_SUB_NARROW_W)
        self._subtitle.setVisible(bool(subtitle))

    # -- 公开 API ---------------------------------------------------------
    def set_status(self, status: str) -> None:
        """设置结果状态。"""
        if status not in self.STATUSES:
            raise ValueError(
                f"未知结果状态: {status!r}，应为 {self.STATUSES} 之一")
        self._icon.set_status(status)

    def set_title(self, text: str) -> None:
        """设置主标题。"""
        self._title.setText(text)

    def set_subtitle(self, text: str) -> None:
        """设置副标题（为空则隐藏）。"""
        self._subtitle_text = text
        self._reflow_subtitle()
        self._subtitle.setVisible(bool(text))

    def add_action(self, text: str, callback=None,
                   variant: str = "default") -> QPushButton:
        """追加操作按钮；``variant`` 为 ``primary`` / ``default`` 等。"""
        btn = QPushButton(text, self)
        set_property(btn, "variant", variant)
        set_property(btn, "size", "md")
        if callable(callback):
            btn.clicked.connect(lambda _=False: callback())
        self._actions.addWidget(btn, 0, Qt.AlignVCenter)
        return btn

    def icon(self) -> QWidget:
        """返回状态图标控件。"""
        return self._icon

    # -- 内部 -------------------------------------------------------------
    def _subtitle_measure(self) -> int:
        """副标题折行宽度：容器宽 - 左右内边距，并限制在上限内。"""
        avail = self.width() - T("space.5") * 2
        if avail <= 0:            # 尚未布局：按上限预排，避免宽度为 0
            return _SUB_MAX_W
        return max(T("space.8"), min(avail, _SUB_MAX_W))

    def _reflow_subtitle(self, measure: int | None = None) -> None:
        """按给定（或当前容器）宽度重新折行（不用 wordWrap，见契约 §7）。

        只设**最大**宽度不设固定宽度：固定宽度会把控件最小宽度钉死在折行
        宽度上，容器再窄也缩不下去（表现为子控件越出父边界）。
        """
        if not self._subtitle_text:
            self._subtitle.setText("")
            return
        if measure is None:
            measure = self._subtitle_measure()
        self._subtitle.setMaximumWidth(measure)
        self._subtitle.setText(
            wrap_text(self._subtitle_text, body_font(), measure))

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self._subtitle_text:
            measure = self._subtitle_measure()
            if measure != self._subtitle.maximumWidth():
                self._reflow_subtitle()
