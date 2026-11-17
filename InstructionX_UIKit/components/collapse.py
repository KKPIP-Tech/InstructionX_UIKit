# -*- coding: utf-8 -*-
"""折叠面板组件（SPEC §5.2 collapse）。

点击标题栏展开 / 收起内容区，展开高度以 QPropertyAnimation
动画过渡；支持手风琴模式（同时仅展开一个面板）。

扁平化约定（与 COMPONENT-DESIGN-CONTRACT §4 对齐）：

- **展开时只有一层**：标题栏与内容区都是透明容器，靠 1px 细线分区，
  不再给标题栏铺 ``bg.subtle`` 灰块（那层底色 + 内容区底色叠加后在暗色
  主题下就是「双层框」的观感来源）；hover 才给标题栏一层极淡底色。
- **分隔线走 ``color.border``（1px）**，不使用 ``border.strong``，
  也不使用投影——普通控件禁用投影。
- **行高压到 30px**（``layout.nav.row_h``，与导航行同级），
  标题字阶用正文 ``md`` + ``regular``：折叠标题不是区块标题，
  加粗 13px 是旧版的「装饰层」写法。
- **内容左缘与标题文字左缘严格对齐**（箭头占位 + 文字内缩都是令牌），
  展开后不会出现「标题缩进、内容顶格」的错位。
"""

from PySide6.QtCore import QEasingCurve, QPropertyAnimation, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from InstructionX_UIKit.components._mixin import QWIDGETSIZE_MAX
from InstructionX_UIKit.theme import T, ThemeManager, set_property
from InstructionX_UIKit.tokens import DURATION, EASING

__all__ = ["Collapse"]

#: 标题栏行高（令牌：导航行高，折叠行与导航行同密度）
_HEADER_H = T("layout.nav.row_h")
#: 箭头图形中心到卡片左缘的距离（令牌：卡片左右内边距）
_CHEVRON_X = T("layout.card.pad_x")
#: 箭头图形中心到标题文字左缘的距离（令牌：图标与文字间距）
_CHEVRON_TEXT_GAP = T("layout.icon.gap")
#: 箭头绘制半径（令牌：小徽标级圆角，半档）
_CHEVRON_R = T("space.1")
#: 内容区最小可视高度（低于此值动画会出现「塌陷」观感）
_MIN_CONTENT_H = T("layout.nav.row_h")


def _qfont_weight(name: str) -> QFont.Weight:
    """``font.weight.*`` 令牌 → ``QFont.Weight``（自绘场景用）。

    自绘控件没有控件级样式表可依赖，只能拿到 QFont；字重仍走令牌，
    不写字面数字（700 / 600 …）。
    """
    return QFont.Weight(T(f"font.weight.{name}"))


class _PanelHeader(QWidget):
    """面板标题栏（自绘：箭头 / 标题 / 1px 分隔线）。

    底色默认透明——只有 hover 才铺 ``bg.subtle``，这是「先删装饰，
    按需再加」的直接落地。
    """

    clicked = Signal()

    def __init__(self, title: str, parent=None):
        super().__init__(parent)
        self._title = title
        self._expanded = False
        self._hovered = False
        self.setFixedHeight(_HEADER_H)
        self.setCursor(Qt.PointingHandCursor)
        self.setAttribute(Qt.WA_Hover)
        ThemeManager.instance().theme_changed.connect(self.update)

    def set_expanded(self, expanded: bool) -> None:
        self._expanded = bool(expanded)
        self.update()

    def enterEvent(self, event) -> None:
        self._hovered = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._hovered = False
        self.update()
        super().leaveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.LeftButton and self.rect().contains(event.position().toPoint()):
            self.clicked.emit()
        super().mouseReleaseEvent(event)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = self.rect()

        if self._hovered:
            # 仅悬停态给一层极淡底色（提示可点击），常态不加装饰层
            painter.fillRect(rect, QColor(T("color.bg.subtle")))

        # 箭头：展开朝下、收起朝右，绘制尺寸全部来自令牌
        pen = QPen(QColor(T("color.text.secondary")))
        pen.setWidthF(1.6)
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        cy = rect.height() / 2
        ax = _CHEVRON_X
        path = QPainterPath()
        if self._expanded:
            path.moveTo(ax - _CHEVRON_R, cy - _CHEVRON_R / 2)
            path.lineTo(ax + _CHEVRON_R / 2, cy + _CHEVRON_R / 2)
            path.lineTo(ax + _CHEVRON_R, cy - _CHEVRON_R / 2)
        else:
            path.moveTo(ax - _CHEVRON_R / 2, cy - _CHEVRON_R)
            path.lineTo(ax + _CHEVRON_R / 2, cy)
            path.lineTo(ax - _CHEVRON_R / 2, cy + _CHEVRON_R)
        painter.drawPath(path)

        # 标题：正文字阶 + 常规字重（折叠标题是行，不是区块标题）
        painter.setPen(QColor(T("color.text.primary")))
        font = painter.font()
        font.setPixelSize(T("font.md"))
        font.setWeight(_qfont_weight("regular"))
        painter.setFont(font)
        text_x = ax + _CHEVRON_TEXT_GAP + _CHEVRON_R
        painter.drawText(
            QRectF(text_x, 0, rect.width() - text_x - _CHEVRON_X, rect.height()),
            Qt.AlignVCenter | Qt.AlignLeft,
            self._title,
        )

        # 底部分隔线：1px、令牌色，唯一的内部线条
        painter.setPen(QPen(QColor(T("color.border"))))
        painter.drawLine(rect.bottomLeft(), rect.bottomRight())
        painter.end()


class _Panel(QWidget):
    """单个折叠面板：标题栏 + 可动画伸缩的内容区。"""

    toggled = Signal(bool)

    def __init__(self, title: str, content, parent=None):
        super().__init__(parent)
        self._expanded = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        set_property(self, "role", "plain")

        self._header = _PanelHeader(title, self)
        self._header.clicked.connect(lambda: self.set_expanded(not self._expanded))
        layout.addWidget(self._header)

        if isinstance(content, str):
            label = QLabel(content, self)
            label.setWordWrap(True)
            set_property(label, "role", "secondary")
            content = label
        self._content = content
        self._content_area = QWidget(self)
        set_property(self._content_area, "role", "plain")
        area_layout = QVBoxLayout(self._content_area)
        # 左内边距 = 箭头中心 + 箭头半径 + 图标文字间距 → 内容左缘
        # 与标题文字左缘严格一致（契约 §3「文字左缘必须严格一致」）
        content_indent = _CHEVRON_X + _CHEVRON_R + _CHEVRON_TEXT_GAP
        area_layout.setContentsMargins(content_indent, T("layout.card.gap"),
                                       T("layout.card.pad_x"),
                                       T("layout.card.pad_top"))
        area_layout.addWidget(content)
        layout.addWidget(self._content_area)

        self._anim = QPropertyAnimation(self._content_area, b"maximumHeight", self)
        self._anim.setDuration(DURATION["normal"])
        self._anim.setEasingCurve(EASING.get("standard", QEasingCurve.OutCubic))
        self._anim.finished.connect(self._on_anim_finished)

        self._apply_collapsed_state(animate=False)

    # ------------------------------------------------------------------ 状态
    def is_expanded(self) -> bool:
        return self._expanded

    def set_expanded(self, expanded: bool, animate: bool = True) -> None:
        expanded = bool(expanded)
        if expanded == self._expanded:
            return
        self._expanded = expanded
        self._apply_collapsed_state(animate=animate)
        self.toggled.emit(expanded)

    def content_widget(self):
        return self._content

    # ------------------------------------------------------------------ 动画
    def _apply_collapsed_state(self, animate: bool) -> None:
        self._anim.stop()
        self._header.set_expanded(self._expanded)
        area = self._content_area
        area.layout().activate()
        full_h = max(area.sizeHint().height(), _MIN_CONTENT_H)
        if self._expanded:
            area.setVisible(True)
            if animate:
                self._anim.setStartValue(0)
                self._anim.setEndValue(full_h)
                self._anim.start()
            else:
                area.setMaximumHeight(QWIDGETSIZE_MAX)
        else:
            if animate:
                area.setVisible(True)
                self._anim.setStartValue(max(area.height(), 0))
                self._anim.setEndValue(0)
                self._anim.start()
            else:
                area.setMaximumHeight(0)
                area.setVisible(False)

    def _on_anim_finished(self) -> None:
        if self._expanded:
            # 展开完成后放开上限，允许内容随布局再变化
            self._content_area.setMaximumHeight(QWIDGETSIZE_MAX)
        else:
            self._content_area.setVisible(False)
        self._content_area.updateGeometry()
        self.updateGeometry()


class Collapse(QWidget):
    """折叠面板容器。

    参数:
        accordion: 手风琴模式（同时只展开一个面板），默认 False。
        parent: 父控件。

    示例::

        col = Collapse(accordion=True)
        col.add_panel("第一章", "第一章内容", expanded=True)
        col.add_panel("第二章", QLabel("第二章内容"))
    """

    #: 面板展开状态变化信号，参数为 (索引, 是否展开)
    panel_toggled = Signal(int, bool)

    def __init__(self, accordion: bool = False, parent=None):
        super().__init__(parent)
        self._accordion = bool(accordion)
        self._panels = []
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(0)
        self._layout.addStretch(1)
        # 容器本身是透明层：面板之间的 1px 细线就是唯一的结构，
        # 不再叠一层容器边框（那是旧版「双层框」的另一半）
        set_property(self, "role", "plain")

    # ------------------------------------------------------------------ 面板
    def add_panel(self, title: str, content, expanded: bool = False) -> int:
        """添加面板，``content`` 为控件或多行文本，返回面板索引。"""
        panel = _Panel(title, content, self)
        index = len(self._panels)
        self._panels.append(panel)
        self._layout.insertWidget(self._layout.count() - 1, panel)
        panel.toggled.connect(lambda exp, i=index: self._on_panel_toggled(i, exp))
        if expanded:
            panel.set_expanded(True, animate=False)
        return index

    def panel_count(self) -> int:
        return len(self._panels)

    def set_expanded(self, index: int, expanded: bool) -> None:
        """展开 / 收起指定面板（带动画）。"""
        self._panels[index].set_expanded(expanded)

    def is_expanded(self, index: int) -> bool:
        return self._panels[index].is_expanded()

    def set_accordion(self, accordion: bool) -> None:
        """切换手风琴模式。"""
        self._accordion = bool(accordion)

    def is_accordion(self) -> bool:
        return self._accordion

    # ------------------------------------------------------------------ 内部
    def _on_panel_toggled(self, index: int, expanded: bool) -> None:
        if expanded and self._accordion:
            for i, panel in enumerate(self._panels):
                if i != index and panel.is_expanded():
                    panel.set_expanded(False)
        self.panel_toggled.emit(index, expanded)