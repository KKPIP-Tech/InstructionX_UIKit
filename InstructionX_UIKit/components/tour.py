# -*- coding: utf-8 -*-
"""漫游式引导 Tour（SPEC §5.3 tour.py）。

覆盖父窗口的引导层：半透明遮罩 + 高亮挖空 + 带箭头的步骤气泡，
支持上一步 / 下一步 / 跳过 / Esc 退出。

三层装饰的协调关系（本组件的重点）：

- **挖空**：目标控件外扩 ``space.1``，圆角取 ``radius.md``——与按钮、输入框
  自身圆角同档，高亮边界因此是「贴着控件形状的一圈」，而不是一个与控件
  无关的大圆角框；描边宽度同样取令牌（``space.05`` = 2px）。
- **箭头**：8px 高等腰三角形，底边沉入卡体 1px，与卡体合并为**同一条**
  ``QPainterPath``，一次填充一次描边，相接处无缝无黑边；箭头始终对准
  挖空中心，被窗口边界钳制时在卡体内平移跟随，并避开圆角。
- **气泡卡片**：圆角 ``radius.lg``、投影 ``shadow.md``（与 Popover 同一档），
  内边距全部取 ``layout.*`` / ``space.*`` 令牌；正文自行折行并锁定高度
  （契约 §7），不依赖 ``QLabel.setWordWrap``。
"""

from PySide6.QtCore import QEvent, QPoint, QRect, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QKeySequence, QPainter, QPainterPath, QPen, QShortcut
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..theme import T, ThemeManager, set_font, set_property
from .dialog import (
    _connect_theme,
    body_font,
    overlay_color,
    paint_soft_shadow,
    shadow_margin,
    wrap_text,
)

__all__ = ["Tour"]

#: 挖空相对目标控件的外扩量
_HOLE_PAD = T("space.1")
#: 挖空圆角：与目标控件自身圆角同档（按钮 / 输入框 = radius.md）
_HOLE_RADIUS = "radius.md"
#: 高亮描边宽度（2px，取半档令牌而非裸数字）
_HOLE_STROKE = T("space.05")
#: 箭头长度（= 箭头与卡体、挖空之间的间距）
_ARROW = T("space.2")
#: 卡片圆角与投影等级
_CARD_RADIUS = "radius.lg"
_SHADOW_LEVEL = "md"
#: 气泡距窗口边缘的最小留白
_EDGE = T("space.3")
#: 正文折行宽度（5 × space.12 = 240px）
_CONTENT_W = T("space.12") * 5
#: 气泡三段内边距：左右 16 / 上下 12，段内间距 8
_PAD_X = T("space.4")
_PAD_Y = T("space.3")
_GAP = T("layout.card.gap")


class _TourBubble(QFrame):
    """引导步骤气泡卡片：卡体 + 箭头一条路径，投影走 ``shadow.md``。"""

    skipClicked = Signal()
    prevClicked = Signal()
    nextClicked = Signal()

    def __init__(self, parent: QWidget = None):
        super().__init__(parent)
        self.setObjectName("uikTourBubble")
        # 卡体与箭头全部自绘，窗口背景必须透明：
        # 全局 QSS 的 ``QWidget { background-color }`` 会给本控件打上
        # WA_StyledBackground，从而在 paintEvent 之前把整个矩形（含投影
        # 留白与箭头预留）涂成不透明底色——这里显式关掉，只画卡体。
        self.setAttribute(Qt.WA_TranslucentBackground)
        # 与 Popover 同理：只给 WA_TranslucentBackground 不够，Qt 仍会用
        # 窗口的系统背景刷子把整个窗口矩形填成不透明色（真机上表现为
        # 一圈矩形色块）。本组件只由 paintEvent 绘制，明确交回背景控制权。
        self.setAttribute(Qt.WA_NoSystemBackground)
        self.setAttribute(Qt.WA_StyledBackground, False)
        self._placement = "bottom"
        self._anchor = None          # 箭头对准点（气泡局部坐标）
        self._shadow = shadow_margin(_SHADOW_LEVEL)

        layout = QVBoxLayout(self)
        self._layout = layout
        layout.setSpacing(_GAP)
        self._apply_margins()

        self._title = QLabel(self)
        set_font(self._title, "lg", "semibold")
        layout.addWidget(self._title)

        self._content = QLabel(self)
        self._content.setFixedWidth(_CONTENT_W)
        set_font(self._content, "md", "regular")
        layout.addWidget(self._content)

        footer = QHBoxLayout()
        footer.setSpacing(T("layout.inline.gap"))
        self._counter = QLabel(self)
        set_font(self._counter, "sm", "regular")
        set_property(self._counter, "role", "tertiary")
        footer.addWidget(self._counter, 0, Qt.AlignVCenter)
        footer.addStretch(1)
        self._skip = QPushButton("跳过", self)
        set_property(self._skip, "variant", "link")
        set_property(self._skip, "size", "sm")
        self._prev = QPushButton("上一步", self)
        set_property(self._prev, "variant", "default")
        set_property(self._prev, "size", "sm")
        self._next = QPushButton("下一步", self)
        set_property(self._next, "variant", "primary")
        set_property(self._next, "size", "sm")
        self._skip.clicked.connect(self.skipClicked.emit)
        self._prev.clicked.connect(self.prevClicked.emit)
        self._next.clicked.connect(self.nextClicked.emit)
        for btn in (self._skip, self._prev, self._next):
            footer.addWidget(btn, 0, Qt.AlignVCenter)
        layout.addLayout(footer)

        # 关闭按钮不参与布局：卡片上不摆关闭，靠「跳过 / Esc」退出
        self.setStyleSheet("QFrame#uikTourBubble { background: transparent;"
                           " border: none; }")
        _connect_theme(self, self.update)

    # -- 几何 -------------------------------------------------------------
    def set_placement(self, placement: str) -> None:
        """设置方位（决定箭头预留的边距），随后重算尺寸。"""
        if placement not in ("bottom", "top", "left", "right"):
            raise ValueError(f"未知气泡方位: {placement!r}")
        self._placement = placement
        self._apply_margins()
        self.adjustSize()
        self.update()

    def set_anchor(self, anchor: QPoint | None) -> None:
        """设置箭头对准点（气泡局部坐标）；``None`` 表示不画箭头。"""
        self._anchor = anchor
        self._apply_margins()
        self.adjustSize()
        self.update()

    def arrow_extra(self) -> tuple:
        """箭头方向对应的额外边距 (left, top, right, bottom)。"""
        if self._anchor is None:
            return (0, 0, 0, 0)
        return {
            "bottom": (0, _ARROW, 0, 0),      # 气泡在挖空下方，箭头朝上
            "top": (0, 0, 0, _ARROW),
            "left": (_ARROW, 0, 0, 0),
            "right": (0, 0, _ARROW, 0),
        }[self._placement]

    def card_offset(self) -> tuple:
        """卡体相对气泡左上角的偏移 (x, y)（含投影留白、箭头预留与内边距）。"""
        ax = self.arrow_extra()
        return (self._shadow + ax[0] + _PAD_X, self._shadow + ax[1] + _PAD_Y)

    def card_size(self) -> tuple:
        """卡体尺寸 (w, h)。

        由「布局内容尺寸 + 卡体内边距」推出，**与方位无关**——换方位只改变
        箭头留在气泡哪一侧，不改变卡体大小，因此定位可以先定方位再排版。
        注意 ``QLayout.sizeHint()`` 含边距、``contentsSize()`` 不含，两者
        混用会让卡体凭空大出一圈（多出来的部分画到气泡矩形之外）。
        """
        self._layout.activate()
        m = self._layout.contentsMargins()
        hint = self._layout.sizeHint()
        return (max(0, hint.width() - m.left() - m.right()) + _PAD_X * 2,
                max(0, hint.height() - m.top() - m.bottom()) + _PAD_Y * 2)

    def _apply_margins(self) -> None:
        ax = self.arrow_extra()
        s = self._shadow
        self._layout.setContentsMargins(
            s + ax[0] + _PAD_X, s + ax[1] + _PAD_Y,
            s + ax[2] + _PAD_X, s + ax[3] + _PAD_Y)

    def _card_rect(self) -> QRectF:
        x, y = self.card_offset()
        w, h = self.card_size()
        return QRectF(x, y, w, h)

    def _bubble_path(self, card: QRectF) -> QPainterPath:
        """卡体圆角矩形 + 箭头合并为一条路径。"""
        radius = T(_CARD_RADIUS)
        path = QPainterPath()
        path.addRoundedRect(card, radius, radius)
        if self._anchor is None:
            return path
        half = _ARROW / 2.0
        # 箭头中心距卡体边缘至少一个圆角 + 半个箭头底宽，避免顶在圆角上
        pad = radius + half
        cx = min(max(self._anchor.x(), card.left() + pad), card.right() - pad)
        if self._placement == "bottom":
            arrow = QPainterPath()
            arrow.moveTo(cx - half, card.top() + 1)
            arrow.lineTo(cx + half, card.top() + 1)
            arrow.lineTo(cx, card.top() + 1 - _ARROW)
        elif self._placement == "top":
            arrow = QPainterPath()
            arrow.moveTo(cx - half, card.bottom() - 1)
            arrow.lineTo(cx + half, card.bottom() - 1)
            arrow.lineTo(cx, card.bottom() - 1 + _ARROW)
        else:
            cy = min(max(self._anchor.y(), card.top() + pad), card.bottom() - pad)
            if self._placement == "left":
                arrow = QPainterPath()
                arrow.moveTo(card.right() - 1, cy - half)
                arrow.lineTo(card.right() - 1, cy + half)
                arrow.lineTo(card.right() - 1 + _ARROW, cy)
            else:
                arrow = QPainterPath()
                arrow.moveTo(card.left() + 1, cy - half)
                arrow.lineTo(card.left() + 1, cy + half)
                arrow.lineTo(card.left() + 1 - _ARROW, cy)
        arrow.closeSubpath()
        return path.united(arrow)

    # -- 内容 -------------------------------------------------------------
    def set_data(self, index: int, count: int, title: str,
                 content: str) -> None:
        """刷新气泡内容（步骤序号从 0 开始）。"""
        self._title.setText(title)
        self._content.setText(wrap_text(content, body_font(), _CONTENT_W))
        self._counter.setText(f"{index + 1}/{count}")
        self._prev.setEnabled(index > 0)
        self._next.setText("完成" if index >= count - 1 else "下一步")
        self.adjustSize()

    def title(self) -> QLabel:
        return self._title

    def counter(self) -> QLabel:
        return self._counter

    def next_button(self) -> QPushButton:
        return self._next

    def prev_button(self) -> QPushButton:
        return self._prev

    def skip_button(self) -> QPushButton:
        return self._skip

    # -- 绘制 -------------------------------------------------------------
    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        card = self._card_rect()
        path = self._bubble_path(card)
        paint_soft_shadow(painter, path, card, _SHADOW_LEVEL)
        c = lambda k: T(f"color.{k}")  # noqa: E731
        border = ("border.strong" if ThemeManager.instance().mode == "dark"
                  else "border")
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(c("bg.elevated")))
        painter.drawPath(path)
        painter.setBrush(Qt.NoBrush)
        pen = QPen(QColor(c(border)))
        pen.setWidthF(1.0)
        painter.setPen(pen)
        painter.drawPath(path)
        painter.end()


class Tour(QWidget):
    """漫游式引导：高亮目标控件 + 步骤气泡。

    参数:
        parent: 父窗口（引导层覆盖它的整个区域）。

    示例::

        tour = Tour(self)
        tour.add_step(save_btn, "保存", "点击这里保存更改")
        tour.start()
    """

    #: 完成全部步骤时发射
    finished = Signal()
    #: 点击「跳过」时发射
    skipped = Signal()
    #: 当前步骤变化信号（从 0 开始）
    currentChanged = Signal(int)

    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self._steps = []     # [(target, title, content)]
        self._index = -1
        self._bubble = _TourBubble(self)
        self._bubble.hide()
        self._bubble.skipClicked.connect(self.skip)
        self._bubble.prevClicked.connect(self.prev)
        self._bubble.nextClicked.connect(self.next)
        if parent is not None:
            parent.installEventFilter(self)
        # Esc 跳过：引导层本身不持有焦点，keyPressEvent 收不到按键，
        # 用 QShortcut（窗口级）保证父窗口活动时 Esc 可达。
        self._esc = QShortcut(QKeySequence(Qt.Key_Escape), self)
        self._esc.setContext(Qt.WindowShortcut)
        self._esc.activated.connect(self._on_escape)
        self.hide()
        _connect_theme(self, self.update)

    # -- 公开 API ---------------------------------------------------------
    def add_step(self, target: QWidget, title: str, content: str) -> None:
        """添加一步引导。"""
        self._steps.append((target, title, content))

    def clear_steps(self) -> None:
        """清空全部步骤。"""
        self._steps = []
        self.stop()

    def start(self, index: int = 0) -> None:
        """开始引导（非阻塞显示覆盖层）。"""
        if not self._steps or self.parent() is None:
            return
        self.setGeometry(self.parent().rect())
        self.show()
        self.raise_()
        self._goto(index)

    def next(self) -> None:
        """下一步；最后一步时完成并发射 finished。"""
        if self._index >= len(self._steps) - 1:
            self.stop()
            self.finished.emit()
        else:
            self._goto(self._index + 1)

    def prev(self) -> None:
        """上一步。"""
        if self._index > 0:
            self._goto(self._index - 1)

    def skip(self) -> None:
        """跳过引导并发射 skipped。"""
        self.stop()
        self.skipped.emit()

    def stop(self) -> None:
        """停止引导（不发射任何信号）。"""
        self._index = -1
        self._bubble.hide()
        self.hide()

    def is_running(self) -> bool:
        return self._index >= 0

    def current(self) -> int:
        return self._index

    def bubble(self) -> _TourBubble:
        """返回步骤气泡控件（供调用方微调文案 / 按钮）。"""
        return self._bubble

    # -- 内部 -------------------------------------------------------------
    def _goto(self, index: int) -> None:
        index = max(0, min(index, len(self._steps) - 1))
        self._index = index
        target, title, content = self._steps[index]
        self._bubble.set_data(index, len(self._steps), title, content)
        self._bubble.show()
        self._bubble.raise_()
        self._reposition()
        self.currentChanged.emit(index)
        self.update()

    def _target_rect(self) -> QRect:
        """目标控件矩形（外扩 ``_HOLE_PAD``）；目标不可见时返回空矩形。"""
        if not (0 <= self._index < len(self._steps)) or self.parent() is None:
            return QRect()
        target = self._steps[self._index][0]
        if target is None or not target.isVisible() or target.width() <= 0:
            return QRect()
        # Tour 几何与父窗口一致，映射到父窗口坐标即可
        top_left = target.mapTo(self.parent(), QPoint(0, 0))
        return QRect(top_left, target.size()).adjusted(
            -_HOLE_PAD, -_HOLE_PAD, _HOLE_PAD, _HOLE_PAD)

    def _reposition(self) -> None:
        """按可用空间挑方位，再把气泡钳制在窗口内并让箭头对准挖空。"""
        hole = self._target_rect()
        card_w, card_h = self._bubble.card_size()
        if not hole.isValid():
            # 目标不可见：卡片居中，不画箭头
            self._bubble.set_anchor(None)
            self._bubble.set_placement("bottom")
            x = max(_EDGE, (self.width() - self._bubble.width()) // 2)
            y = max(_EDGE, (self.height() - self._bubble.height()) // 2)
            self._bubble.move(x, y)
            return

        bounds = QRect(_EDGE, _EDGE,
                       max(0, self.width() - _EDGE * 2),
                       max(0, self.height() - _EDGE * 2))
        hx, hy = hole.center().x(), hole.center().y()
        candidates = {
            "bottom": QRect(hx - card_w // 2, hole.bottom() + _ARROW,
                            card_w, card_h),
            "top": QRect(hx - card_w // 2, hole.top() - _ARROW - card_h,
                         card_w, card_h),
            "right": QRect(hole.right() + _ARROW, hy - card_h // 2,
                           card_w, card_h),
            "left": QRect(hole.left() - _ARROW - card_w, hy - card_h // 2,
                          card_w, card_h),
        }
        # 优先「下方 → 上方 → 右侧 → 左侧」：下方是引导气泡的默认位
        placement, card = None, None
        for key in ("bottom", "top", "right", "left"):
            rect = candidates[key]
            if bounds.contains(rect):
                placement, card = key, rect
                break
        if placement is None:
            # 都放不下（窗口比气泡还小）：取与窗口重叠面积最大的一个，
            # 再把卡体左上角钳制进窗口（QRect 没有 move，只有 moveTopLeft）
            placement = max(
                candidates,
                key=lambda k: candidates[k].intersected(bounds).width()
                * candidates[k].intersected(bounds).height())
            card = candidates[placement]
            card.moveTopLeft(QPoint(
                max(bounds.left(), min(card.left(),
                                       bounds.right() - card.width() + 1)),
                max(bounds.top(), min(card.top(),
                                      bounds.bottom() - card.height() + 1))))

        # 方位决定箭头留在哪一侧 → 先切方位（气泡尺寸随之变化），再落位
        self._bubble.set_placement(placement)
        off_x, off_y = self._bubble.card_offset()
        self._bubble.move(card.left() - off_x, card.top() - off_y)
        # 箭头对准挖空中心；被边界钳制时在卡体内平移（见 _bubble_path）
        self._bubble.set_anchor(self._bubble.mapFrom(self, QPoint(hx, hy)))

    def eventFilter(self, watched, event) -> bool:
        if watched is self.parent() and self.isVisible() \
                and event.type() in (QEvent.Resize, QEvent.Move):
            self.setGeometry(self.parent().rect())
            if self.is_running():
                self._reposition()
        return super().eventFilter(watched, event)

    def mousePressEvent(self, event) -> None:
        event.accept()  # 阻断点击穿透到被遮罩的控件

    def _on_escape(self) -> None:
        """Esc 快捷键回调（仅在引导进行中生效，避免误发 skipped）。"""
        if self.is_running():
            self.skip()

    def keyPressEvent(self, event) -> None:
        # 兜底路径：引导层获得焦点时仍可 Esc 跳过
        if event.key() == Qt.Key_Escape:
            self._on_escape()
        else:
            super().keyPressEvent(event)

    def paintEvent(self, event) -> None:
        """遮罩 + 挖空 + 高亮描边。"""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        radius = T(_HOLE_RADIUS)
        full = QPainterPath()
        full.addRect(QRectF(self.rect()))
        hole = self._target_rect()
        if hole.isValid():
            hole_path = QPainterPath()
            hole_path.addRoundedRect(hole.x(), hole.y(), hole.width(),
                                     hole.height(), radius, radius)
            painter.fillPath(full.subtracted(hole_path), overlay_color())
            # 高亮描边（主色令牌，主题实时感知）
            stroke = QColor(T("color.primary"))
            stroke.setAlpha(230)
            pen = QPen(stroke)
            pen.setWidthF(_HOLE_STROKE)
            painter.setPen(pen)
            painter.setBrush(Qt.NoBrush)
            painter.drawRoundedRect(hole, radius, radius)
        else:
            painter.fillPath(full, overlay_color())
        painter.end()
