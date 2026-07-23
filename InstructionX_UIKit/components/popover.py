# -*- coding: utf-8 -*-
"""气泡卡片组件（SPEC §5.2 popover）。

相对锚点控件弹出的浮层卡片（``Qt.Popup``，点击外部自动关闭），
支持上 / 下 / 左 / 右四个方位并绘制指向箭头；背景、边框与
箭头自绘，主题实时感知。

渲染要点（fix/f2 修订）：

- 弹出窗使用 ``Qt.FramelessWindowHint | Qt.Popup`` + ``WA_TranslucentBackground``；
  卡片圆角矩形（``radius.lg`` = 8px）与箭头合并为**一条** ``QPainterPath``
  一次填充 / 描边，相接处无缝无黑边。
- 箭头为 8px 高等腰三角形（底 14px），底边沉入主体 1px 保证无缝；
  箭头始终对准锚点中心（窗口被屏幕边缘钳制时箭头在卡体内平移跟随）。
- 阴影为 16 层二次衰减柔和投影（权重 ∝ (1-t)² 叠加模拟高斯模糊），
  颜色取 ``shadow.md`` 令牌，直接对含箭头的整体路径缩放外扩，
  无分层感且箭头也有阴影；不使用 ``QGraphicsDropShadowEffect``，
  避免含透明区域弹出窗的黑块 / 双影。
- 暗色主题下描边升级为 ``border.strong``，增强边缘层次。
- 弹出带 120ms 淡入 + 轻微上移入场动画（QPropertyAnimation
  windowOpacity / pos，OutCubic），避免生硬瞬间出现。
"""

from PySide6.QtCore import (
    QEasingCurve,
    QPoint,
    QPropertyAnimation,
    QRectF,
    Qt,
)
from PySide6.QtGui import QColor, QGuiApplication, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from InstructionX_UIKit.theme import T, ThemeManager

__all__ = ["Popover"]

_SHADOW = 12      # 四边预留的阴影空间（>= 最大外扩 + 最大纵向偏移）
_ARROW_H = 8      # 箭头高度（8px 等腰三角形）
_ARROW_BASE = 14  # 箭头底边宽
_SHADOW_LAYERS = 16   # 阴影层数（权重二次衰减叠加模拟柔和投影）
_SHADOW_SPREAD = 7    # 阴影最大外扩幅度
_SHADOW_OFFSET_Y = 2.0  # 阴影整体下沉的最大纵向偏移
_ENTER_MS = 120   # 入场动画时长（淡入 + 轻微上移）
_ENTER_DY = 4     # 入场起点的纵向偏移（上移到位的距离）


class Popover(QWidget):
    """气泡卡片浮层。

    参数:
        title: 标题（为空则不显示标题行）。
        content: 内容：控件或文本（自动包成换行标签）。
        parent: 父控件。

    示例::

        pop = Popover("筛选", "这里是气泡内容")
        pop.show_for(anchor_button, placement="bottom")
    """

    def __init__(self, title: str = "", content=None, parent=None):
        super().__init__(parent, Qt.Popup | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAutoFillBackground(False)
        # 全局基座 QSS「QWidget { background: bg.base }」会在绘制链中给
        # 弹出窗整个矩形（含透明的阴影边距区）涂上不透明底色（暗色
        # #15181E，真机上即"黑色方框"）。实例级覆盖为透明：弹出窗只由
        # paintEvent 绘制圆角卡体 + 箭头 + 阴影，其余区域保持真透明。
        self.setStyleSheet("background: transparent;")
        self._placement = "top"
        self._anchor_center = None  # 锚点中心（全局坐标），用于箭头的对齐
        self._anim_opacity = None
        self._anim_pos = None

        self._layout = QVBoxLayout(self)
        self._layout.setSpacing(T("space.1"))
        self._apply_margins()

        self._title_label = QLabel(title, self)
        title_font = self._title_label.font()
        title_font.setBold(True)
        self._title_label.setFont(title_font)
        self._title_label.setVisible(bool(title))
        self._layout.addWidget(self._title_label)

        self._content_host = QWidget(self)
        # 全局 QSS 给所有 QWidget 刷 bg.base，暗色下会盖住卡体 bg.elevated
        # 造成箭头与主体色差；实例级覆盖为透明（不动全局 QSS）
        self._content_host.setStyleSheet("background-color: transparent;")
        self._content_layout = QVBoxLayout(self._content_host)
        self._content_layout.setContentsMargins(0, 0, 0, 0)
        self._layout.addWidget(self._content_host)
        if content is not None:
            self.set_content(content)
        ThemeManager.instance().theme_changed.connect(self.update)

    # ------------------------------------------------------------------ 内容
    def set_title(self, title: str) -> None:
        """设置标题；空串隐藏标题行。"""
        self._title_label.setText(title)
        self._title_label.setVisible(bool(title))

    def set_content(self, content) -> None:
        """设置内容：控件或文本。"""
        while self._content_layout.count():
            item = self._content_layout.takeAt(0)
            if item.widget() is not None:
                item.widget().setParent(None)
        if isinstance(content, str):
            label = QLabel(content, self._content_host)
            label.setWordWrap(True)
            label.setMaximumWidth(240)
            content = label
        self._content_layout.addWidget(content)

    # ------------------------------------------------------------------ 弹出
    def show_for(self, anchor: QWidget, placement: str = "top") -> None:
        """相对锚点控件弹出。

        参数:
            anchor: 锚点控件。
            placement: ``"top"`` / ``"bottom"`` / ``"left"`` / ``"right"``，
                       指气泡出现在锚点的哪一侧；空间不足时自动翻转。
        """
        if placement not in ("top", "bottom", "left", "right"):
            raise ValueError(f"未知方位: {placement!r}")
        self._placement = placement
        self._anchor_center = anchor.mapToGlobal(anchor.rect().center())
        self._apply_margins()
        self.adjustSize()
        pos = self._compute_pos(anchor, placement)
        self.move(pos)
        self.show()
        self.raise_()
        self._start_enter_animation(pos)

    def placement(self) -> str:
        return self._placement

    def hideEvent(self, event) -> None:
        self._stop_enter_animation()
        super().hideEvent(event)

    # ------------------------------------------------------------------ 内部
    def _arrow_extra(self):
        """各边为箭头预留的额外边距（left, top, right, bottom）。"""
        return {
            "top": (0, 0, 0, _ARROW_H),
            "bottom": (0, _ARROW_H, 0, 0),
            "left": (0, 0, _ARROW_H, 0),
            "right": (_ARROW_H, 0, 0, 0),
        }[self._placement]

    def _apply_margins(self) -> None:
        ax = self._arrow_extra()
        self._layout.setContentsMargins(
            _SHADOW + ax[0], _SHADOW + ax[1], _SHADOW + ax[2], _SHADOW + ax[3])

    def _card_rect(self) -> QRectF:
        """卡片主体矩形（不含箭头，四边预留完整阴影空间）。"""
        ax = self._arrow_extra()
        r = QRectF(self.rect())
        return r.adjusted(_SHADOW + ax[0], _SHADOW + ax[1],
                          -_SHADOW - ax[2], -_SHADOW - ax[3])

    def _start_enter_animation(self, pos: QPoint) -> None:
        """120ms 淡入 + 轻微上移入场（OutCubic），避免生硬瞬间出现。"""
        self._stop_enter_animation()
        self.setWindowOpacity(0.0)
        self._anim_opacity = QPropertyAnimation(self, b"windowOpacity", self)
        self._anim_opacity.setDuration(_ENTER_MS)
        self._anim_opacity.setStartValue(0.0)
        self._anim_opacity.setEndValue(1.0)
        self._anim_opacity.setEasingCurve(QEasingCurve.OutCubic)
        self._anim_pos = QPropertyAnimation(self, b"pos", self)
        self._anim_pos.setDuration(_ENTER_MS)
        self._anim_pos.setStartValue(pos + QPoint(0, _ENTER_DY))
        self._anim_pos.setEndValue(pos)
        self._anim_pos.setEasingCurve(QEasingCurve.OutCubic)
        self._anim_opacity.finished.connect(self._on_enter_finished)
        self._anim_opacity.start()
        self._anim_pos.start()

    def _stop_enter_animation(self) -> None:
        for anim in (self._anim_opacity, self._anim_pos):
            if anim is not None:
                anim.stop()
        self._anim_opacity = None
        self._anim_pos = None
        self.setWindowOpacity(1.0)

    def _on_enter_finished(self) -> None:
        self.setWindowOpacity(1.0)

    def _compute_pos(self, anchor: QWidget, placement: str) -> QPoint:
        rect = anchor.rect()
        center = anchor.mapToGlobal(rect.center())
        top_left = anchor.mapToGlobal(rect.topLeft())
        w, h = self.width(), self.height()
        aw, ah = rect.width(), rect.height()

        candidates = {
            "top": QPoint(center.x() - w // 2, top_left.y() - h),
            "bottom": QPoint(center.x() - w // 2, top_left.y() + ah),
            "left": QPoint(top_left.x() - w, center.y() - h // 2),
            "right": QPoint(top_left.x() + aw, center.y() - h // 2),
        }
        pos = candidates[placement]
        # 屏幕边界检查：超出则尝试翻转
        screen = QGuiApplication.screenAt(center) or QGuiApplication.primaryScreen()
        if screen is not None:
            area = screen.availableGeometry()
            opposite = {"top": "bottom", "bottom": "top",
                        "left": "right", "right": "left"}
            out = (
                pos.x() < area.left() or pos.x() + w > area.right() + 1
                or pos.y() < area.top() or pos.y() + h > area.bottom() + 1
            )
            if out:
                flipped = opposite[placement]
                alt = candidates[flipped]
                still_out = (
                    alt.x() < area.left() or alt.x() + w > area.right() + 1
                    or alt.y() < area.top() or alt.y() + h > area.bottom() + 1
                )
                if not still_out:
                    self._placement = flipped
                    self._apply_margins()
                    pos = alt
            # 最终钳制在屏幕内
            pos.setX(max(area.left(), min(pos.x(), area.right() - w + 1)))
            pos.setY(max(area.top(), min(pos.y(), area.bottom() - h + 1)))
        return pos

    # ------------------------------------------------------------------ 绘制
    def _bubble_path(self, card: QRectF) -> QPainterPath:
        """卡片圆角矩形 + 箭头合并为一条路径（填充 / 描边一次成型）。

        箭头为 8px 高等腰三角形，底边沉入卡片 1px，united 后相接处无缝；
        箭头中心对准锚点中心（窗口被钳制时在卡体内平移跟随）。
        """
        radius = T("radius.lg")
        path = QPainterPath()
        path.addRoundedRect(card, radius, radius)

        half = _ARROW_BASE / 2.0
        pad = radius + half + 1  # 箭头中心距卡体边缘的最小距离（避开圆角）
        cx, cy = card.center().x(), card.center().y()
        if self._anchor_center is not None:
            local = self.mapFromGlobal(self._anchor_center)
            cx, cy = local.x(), local.y()
        cx = min(max(cx, card.left() + pad), card.right() - pad)
        cy = min(max(cy, card.top() + pad), card.bottom() - pad)

        arrow = QPainterPath()
        if self._placement == "top":  # 气泡在锚点上方，箭头朝下
            arrow.moveTo(cx - half, card.bottom() - 1)
            arrow.lineTo(cx + half, card.bottom() - 1)
            arrow.lineTo(cx, card.bottom() - 1 + _ARROW_H)
        elif self._placement == "bottom":
            arrow.moveTo(cx - half, card.top() + 1)
            arrow.lineTo(cx + half, card.top() + 1)
            arrow.lineTo(cx, card.top() + 1 - _ARROW_H)
        elif self._placement == "left":
            arrow.moveTo(card.right() - 1, cy - half)
            arrow.lineTo(card.right() - 1, cy + half)
            arrow.lineTo(card.right() - 1 + _ARROW_H, cy)
        else:
            arrow.moveTo(card.left() + 1, cy - half)
            arrow.lineTo(card.left() + 1, cy + half)
            arrow.lineTo(card.left() + 1 - _ARROW_H, cy)
        arrow.closeSubpath()
        return path.united(arrow)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        card = self._card_rect()
        bg = QColor(T("color.bg.elevated"))
        # 暗色主题下以 border.strong 增强边缘层次
        border_token = ("color.border.strong"
                        if ThemeManager.instance().mode == "dark"
                        else "color.border")
        border = QColor(T(border_token))

        bubble = self._bubble_path(card)

        # -- 多层柔和阴影：权重 ∝ (1-t)² 二次衰减（近似高斯），对含箭头的
        #    整体路径绕卡体中心外扩，无分层感且箭头同样带阴影
        sr, sg, sb, sa = T("shadow.md")["color"]
        n = _SHADOW_LAYERS
        weights = [(1.0 - (j + 0.5) / n) ** 2 for j in range(n)]
        wsum = sum(weights)
        painter.setPen(Qt.NoPen)
        cx, cy = card.center().x(), card.center().y()
        for j in range(n - 1, -1, -1):  # 外层 -> 内层
            t = (n - j) / n  # 1 -> 1/n
            grow = t * _SHADOW_SPREAD
            dy = 0.5 + t * _SHADOW_OFFSET_Y
            alpha = round(sa * weights[j] / wsum)
            if alpha <= 0:
                continue
            painter.save()
            painter.translate(cx, cy + dy)
            painter.scale((card.width() + 2 * grow) / card.width(),
                          (card.height() + 2 * grow) / card.height())
            painter.translate(-cx, -cy)
            painter.setBrush(QColor(sr, sg, sb, alpha))
            painter.drawPath(bubble)
            painter.restore()

        # -- 气泡本体（圆角矩形 + 箭头一条路径，箭头与底色一致、边缘无接缝）
        painter.setPen(Qt.NoPen)
        painter.setBrush(bg)
        painter.drawPath(bubble)
        painter.setBrush(Qt.NoBrush)
        pen = QPen(border)
        pen.setWidthF(1.0)
        painter.setPen(pen)
        painter.drawPath(bubble)
        painter.end()
