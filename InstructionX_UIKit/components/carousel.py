# -*- coding: utf-8 -*-
"""走马灯组件（SPEC §5.2 carousel）。

内容页横向滑动切换（QPropertyAnimation 位移动画），带指示点、
左右箭头与自动播放；悬停时暂停自动播放。

密度与扁平化约定（与 COMPONENT-DESIGN-CONTRACT §1 / §4 对齐）：

- **箭头按钮压到 md 档（28px）**：旧版 32px 自定义圆钮比同页其它
  控件高一档，视觉上「浮」在内容上；尺寸改走 ``space.7`` 令牌，
  与 md 档控件（28px）等高，页面上不再出现第五种按钮尺寸。
- **导航元素只在多页时出现**，且不额外加框：箭头为半透明面色圆钮
  （常态无边框，hover 才描边），指示点为小圆角条 / 圆点，
  间距与边距全部取令牌。
- 走马灯本体不加边框、不加投影——它是内容容器，装饰交给页面骨架。
"""

from PySide6.QtCore import (
    QAbstractAnimation,
    QEasingCurve,
    QEvent,
    QParallelAnimationGroup,
    QPoint,
    QPropertyAnimation,
    QRect,
    QSize,
    Qt,
    QTimer,
    Signal,
)
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QWidget

from InstructionX_UIKit.theme import T, ThemeManager
from InstructionX_UIKit.tokens import DURATION, EASING

__all__ = ["Carousel"]

#: 箭头按钮边长：md 档控件高度（space.7 = 28），与页面其它控件同密度
_ARROW_BTN = T("space.7")
#: 箭头距走马灯左右边缘的距离
_ARROW_INSET = T("layout.card.pad_x")
#: 当前项长条宽（= space.3 + space.1 = 16px），高与圆点同径
_DOT_ACTIVE_W = T("space.3") + T("space.1")
#: 圆点直径（= space.1 + space.05 = 6px），小徽标级
_DOT_SIZE = T("space.1") + T("space.05")
#: 槽位步进 = 长条宽 + 一个半档间距（保证长条与圆点之间也有呼吸）
_DOT_PITCH = _DOT_ACTIVE_W + T("space.1")
#: 指示条自身高度：圆点直径 + 上下各一个半档
_DOT_BAR_H = _DOT_SIZE + 2 * T("space.05")
#: 指示条左右留白（同时作为命中判定的起始偏移）
_DOT_PAD_X = T("space.2")
#: 指示条距走马灯底边的距离
_DOT_INSET = T("layout.card.gap")
#: 箭头图形半宽 / 半高（令牌化的小图标尺寸）
_CHEVRON_RX = T("space.1")
_CHEVRON_RY = T("space.1") + T("space.05")


class _ArrowButton(QWidget):
    """圆形自绘箭头按钮（左 / 右）：常态半透明面色、hover 才描边。"""

    clicked = Signal()

    def __init__(self, direction: str, parent=None):
        super().__init__(parent)
        assert direction in ("left", "right")
        self._direction = direction
        self._hovered = False
        self.setFixedSize(_ARROW_BTN, _ARROW_BTN)
        self.setCursor(Qt.PointingHandCursor)
        self.setAttribute(Qt.WA_Hover)
        ThemeManager.instance().theme_changed.connect(self.update)

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
        rect = self.rect().adjusted(1, 1, -1, -1)
        bg = QColor(T("color.bg.elevated"))
        # 常态半透明：内容透出一点，箭头不与页面内容抢视觉；
        # hover 才实心 + 描边（先常后显的减法式装饰）
        bg.setAlpha(230 if self._hovered else 180)
        painter.setPen(QPen(QColor(T("color.border"))) if self._hovered
                       else QPen(Qt.NoPen))
        painter.setBrush(bg)
        painter.drawEllipse(rect)
        # 箭头
        pen = QPen(QColor(T("color.primary") if self._hovered else T("color.text.secondary")))
        pen.setWidthF(1.8)
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        cx, cy = self.width() / 2, self.height() / 2
        path = QPainterPath()
        if self._direction == "left":
            path.moveTo(cx + _CHEVRON_RX, cy - _CHEVRON_RY)
            path.lineTo(cx - _CHEVRON_RX, cy)
            path.lineTo(cx + _CHEVRON_RX, cy + _CHEVRON_RY)
        else:
            path.moveTo(cx - _CHEVRON_RX, cy - _CHEVRON_RY)
            path.lineTo(cx + _CHEVRON_RX, cy)
            path.lineTo(cx - _CHEVRON_RX, cy + _CHEVRON_RY)
        painter.drawPath(path)
        painter.end()


class _DotsBar(QWidget):
    """指示点条：当前项为长条，其余为圆点，点击切换。"""

    clicked = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._count = 0
        self._current = 0
        self.setFixedHeight(_DOT_BAR_H)
        self.setCursor(Qt.PointingHandCursor)
        ThemeManager.instance().theme_changed.connect(self.update)

    def set_count(self, count: int) -> None:
        self._count = max(0, int(count))
        self.setFixedWidth(self._count * _DOT_PITCH + 2 * _DOT_PAD_X)
        self.update()

    def set_current(self, index: int) -> None:
        self._current = int(index)
        self.update()

    def mousePressEvent(self, event) -> None:
        if self._count > 0:
            index = (int(event.position().x()) - _DOT_PAD_X) // _DOT_PITCH
            if 0 <= index < self._count:
                self.clicked.emit(index)
        super().mousePressEvent(event)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(Qt.NoPen)
        cy = self.height() / 2
        for i in range(self._count):
            x = _DOT_PAD_X + i * _DOT_PITCH
            if i == self._current:
                # 当前项：长条（与圆点同径的胶囊），首尾左缘与槽位对齐
                painter.setBrush(QColor(T("color.primary")))
                painter.drawRoundedRect(
                    QRect(x, int(cy - _DOT_SIZE / 2), _DOT_ACTIVE_W, _DOT_SIZE),
                    _DOT_SIZE / 2, _DOT_SIZE / 2)
            else:
                # 非当前项：圆点在槽位内水平居中，切换时不会左右跳
                painter.setBrush(QColor(T("color.border.strong")))
                painter.drawEllipse(
                    QRect(x + (_DOT_ACTIVE_W - _DOT_SIZE) // 2,
                          int(cy - _DOT_SIZE / 2), _DOT_SIZE, _DOT_SIZE))
        painter.end()


class Carousel(QWidget):
    """走马灯（轮播）容器。

    参数:
        autoplay: 自动播放间隔（毫秒），``0`` 关闭，默认 0。
        parent: 父控件。

    示例::

        carousel = Carousel(autoplay=3000)
        carousel.add_page(QLabel("第一屏"))
        carousel.add_page(QLabel("第二屏"))
        carousel.go_to(1)
    """

    currentChanged = Signal(int)

    def __init__(self, autoplay: int = 0, parent=None):
        super().__init__(parent)
        self._pages = []
        self._current = -1
        self._anim = None
        self._anim_dir = 1
        self._autoplay = 0
        self._hovered = False

        self._viewport = QWidget(self)
        self._prev_btn = _ArrowButton("left", self)
        self._next_btn = _ArrowButton("right", self)
        self._dots = _DotsBar(self)
        self._prev_btn.clicked.connect(self.prev)
        self._next_btn.clicked.connect(self.next)
        self._dots.clicked.connect(self.go_to)

        # 悬停暂停：走马灯表面被 viewport/页面全铺覆盖，自身
        # enter/leaveEvent 收不到事件，需对全部子控件安装事件过滤器。
        for w in (self._viewport, self._prev_btn, self._next_btn, self._dots):
            w.installEventFilter(self)

        self._timer = QTimer(self)
        self._timer.timeout.connect(self.next)
        # 离开事件后的延迟复核：在子控件间移动时先 Leave 后 Enter，
        # 需等事件序列结束再决定是否恢复自动播放。
        self._hover_check = QTimer(self)
        self._hover_check.setSingleShot(True)
        self._hover_check.setInterval(0)
        self._hover_check.timeout.connect(self._check_hover_exit)
        if autoplay:
            self.set_autoplay(autoplay)
        self._update_nav_visibility()

    # ------------------------------------------------------------------ 页面
    def add_page(self, widget: QWidget) -> int:
        """添加一页，返回页索引。"""
        widget.setParent(self._viewport)
        widget.installEventFilter(self)
        widget.hide()
        self._pages.append(widget)
        self._dots.set_count(len(self._pages))
        if self._current < 0:
            self._current = 0
            widget.show()
            self._layout_pages()
        self._update_nav_visibility()
        self._reposition_nav()  # 圆点宽度随页数变化，需重新居中
        return len(self._pages) - 1

    def page(self, index: int):
        return self._pages[index]

    def count(self) -> int:
        return len(self._pages)

    def current_index(self) -> int:
        return self._current

    # ------------------------------------------------------------------ 切换
    def go_to(self, index: int) -> None:
        """滑动切换到指定页。"""
        n = len(self._pages)
        if n == 0 or index == self._current or not (0 <= index < n):
            return
        old_index = self._current
        self._current = index
        self._dots.set_current(index)
        self.currentChanged.emit(index)
        if self._anim is not None or old_index < 0:
            # 动画进行中或首次：直接切换
            if old_index >= 0:
                self._pages[old_index].hide()
            self._pages[index].show()
            self._layout_pages()
            return

        if index == (old_index + 1) % n:
            direction = 1
        elif index == (old_index - 1) % n:
            direction = -1
        else:
            direction = 1 if index > old_index else -1
        self._anim_dir = direction

        old_page = self._pages[old_index]
        new_page = self._pages[index]
        w, h = self._viewport.width(), self._viewport.height()
        new_page.setGeometry(w * direction, 0, w, h)
        new_page.show()
        new_page.raise_()

        group = QParallelAnimationGroup(self)
        for page, start, end in (
            (old_page, QPoint(0, 0), QPoint(-w * direction, 0)),
            (new_page, QPoint(w * direction, 0), QPoint(0, 0)),
        ):
            anim = QPropertyAnimation(page, b"pos", group)
            anim.setDuration(DURATION["slow"])
            anim.setEasingCurve(EASING.get("standard", QEasingCurve.OutCubic))
            anim.setStartValue(start)
            anim.setEndValue(end)
            group.addAnimation(anim)

        def _finish():
            old_page.hide()
            self._layout_pages()
            self._anim = None

        group.finished.connect(_finish)
        self._anim = group
        group.start()

    def next(self) -> None:
        """下一页（循环）。"""
        if self._pages:
            self.go_to((self._current + 1) % len(self._pages))

    def prev(self) -> None:
        """上一页（循环）。"""
        if self._pages:
            self.go_to((self._current - 1) % len(self._pages))

    # ------------------------------------------------------------------ 自动播放
    def set_autoplay(self, interval_ms: int) -> None:
        """设置自动播放间隔（毫秒），``0`` 停止。"""
        self._autoplay = max(0, int(interval_ms))
        self._timer.stop()
        if self._autoplay and not self._hovered:
            self._timer.start(self._autoplay)

    def autoplay_interval(self) -> int:
        return self._autoplay

    def enterEvent(self, event) -> None:
        self._set_hover(True)
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._set_hover(False)
        super().leaveEvent(event)

    def eventFilter(self, watched, event) -> bool:
        # viewport / 页面 / 箭头 / 圆点统一判定悬停（自身 enter/leave 不覆盖子控件）
        if event.type() == QEvent.Enter:
            self._set_hover(True)
        elif event.type() == QEvent.Leave:
            self._set_hover(False)
        return super().eventFilter(watched, event)

    def _set_hover(self, hovered: bool) -> None:
        """悬停状态变化：进入立即暂停；离开延迟复核后再恢复。"""
        if hovered:
            self._hovered = True
            self._hover_check.stop()
            self._timer.stop()
        else:
            self._hovered = False
            self._hover_check.start()

    def _check_hover_exit(self) -> None:
        """离开事件序列结束后：若已不在走马灯内则恢复自动播放。"""
        if self._autoplay and not self._hovered:
            self._timer.start(self._autoplay)

    # ------------------------------------------------------------------ 布局
    def _update_nav_visibility(self) -> None:
        visible = len(self._pages) > 1
        self._prev_btn.setVisible(visible)
        self._next_btn.setVisible(visible)
        self._dots.setVisible(visible)

    def _layout_pages(self) -> None:
        if 0 <= self._current < len(self._pages):
            self._pages[self._current].setGeometry(self._viewport.rect())

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        w, h = self.width(), self.height()
        self._viewport.setGeometry(0, 0, w, h)
        if self._anim is not None \
                and self._anim.state() == QAbstractAnimation.Running:
            # 动画中 resize：同步双方页面几何与动画端点，避免旧页
            # 停留在旧坐标（原先只重排当前页，旧页错位）。
            self._sync_anim_geometry(w, h)
        else:
            self._layout_pages()
        self._reposition_nav()
        self._prev_btn.raise_()
        self._next_btn.raise_()
        self._dots.raise_()

    def _sync_anim_geometry(self, w: int, h: int) -> None:
        """动画进行中：按新尺寸重设两页几何并更新动画起止端点。"""
        direction = self._anim_dir
        group = self._anim
        for i in range(group.animationCount()):
            anim = group.animationAt(i)
            page = anim.targetObject()
            if page is None:
                continue
            page.setGeometry(0, 0, w, h)
            if anim.startValue() == QPoint(0, 0):
                anim.setEndValue(QPoint(-w * direction, 0))
            else:
                anim.setStartValue(QPoint(w * direction, 0))

    def _reposition_nav(self) -> None:
        """箭头与圆点跟随当前尺寸重新定位（resize 与 add_page 共用）。"""
        w, h = self.width(), self.height()
        self._prev_btn.move(_ARROW_INSET, (h - self._prev_btn.height()) // 2)
        self._next_btn.move(w - self._next_btn.width() - _ARROW_INSET,
                            (h - self._next_btn.height()) // 2)
        self._dots.move((w - self._dots.width()) // 2,
                        h - self._dots.height() - _DOT_INSET)

    def sizeHint(self) -> QSize:
        return QSize(480, 240)

    def minimumSizeHint(self) -> QSize:
        return QSize(240, 140)
