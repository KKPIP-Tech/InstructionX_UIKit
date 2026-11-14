# -*- coding: utf-8 -*-
"""气泡卡片组件（SPEC §5.2 popover）。

相对锚点控件弹出的浮层卡片（``Qt.Popup``，点击外部自动关闭），
支持上 / 下 / 左 / 右四个方位并绘制指向箭头；背景、边框与
箭头自绘，主题实时感知。

渲染要点（fix/f2 修订 + 扁平化收敛）：

- 弹出窗使用 ``Qt.FramelessWindowHint | Qt.Popup`` + ``WA_TranslucentBackground``；
  卡片圆角矩形（``radius.lg`` = 12px）与箭头合并为**一条** ``QPainterPath``
  一次填充 / 描边，相接处无缝无黑边。
- 箭头为 8px 高等腰三角形（底 14px），底边沉入主体 1px 保证无缝；
  箭头始终对准锚点中心（窗口被屏幕边缘钳制时箭头在卡体内平移跟随）。
- **不画阴影**。层次完全由 1px 实线描边承担（暗色下升级为
  ``border.strong``），符合扁平化规范。曾用 16 层不同 alpha 的圆角路径
  叠加模拟柔和投影，卡体外围形成一圈半透明过渡带；真机合成器如何处理这圈
  alpha 无法在离屏环境保证，实测在 Windows 上表现为卡体外一圈矩形色块。
  去掉投影后卡体与箭头全部不透明铺到窗口边缘，根除该类问题。
- 弹出带 120ms 淡入 + 轻微上移入场动画（QPropertyAnimation
  windowOpacity / pos，OutCubic），避免生硬瞬间出现。

浮层内边距：

- 布局内边距 = **描边预留（2px）+ 箭头预留（8px）**。内容内边距另由
  ``layout.inset.*`` 承担，两段解耦：外层几何变化不会把文字挤到卡体边缘。
- 因为没有投影，外层只需容纳 1px 描边与箭头，窗口里除箭头周围外全部被
  不透明卡体铺满，不存在半透明过渡带。
- 内容区自身也是透明容器，不会在卡体上再叠一层 ``bg.base`` 底色。
"""

import math

from PySide6.QtCore import (
    QEasingCurve,
    QPoint,
    QPropertyAnimation,
    QRectF,
    Qt,
)
from PySide6.QtGui import QColor, QGuiApplication, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from InstructionX_UIKit.theme import T, ThemeManager, set_property

__all__ = ["Popover"]

_ARROW_H = 8      # 箭头高度（8px 等腰三角形）
_ARROW_BASE = 14  # 箭头底边宽
_BORDER_W = 1.0   # 卡体描边宽度（1px 实线承担层次，符合扁平化规范）
_BORDER_M = 2     # 四边边距：容纳 1px 描边（描边跨在路径上，半宽 0.5px）

# 三个纯布局容器（窗口本身 + 卡体宿主 + 内容宿主）必须真透明。
# 用 ID 选择器压过全局基座 QSS 的「QWidget { background-color: bg.base }」，
# 见 Popover._reload_style 的说明。
_ROOT_ID = "uikPopoverRoot"
_CARD_HOST_ID = "uikPopoverCardHost"
_CONTENT_HOST_ID = "uikPopoverContentHost"


_ENTER_MS = 120   # 入场动画时长（淡入 + 轻微上移）
_ENTER_DY = 4     # 入场起点的纵向偏移（上移到位的距离）

#: 卡体内容内边距（令牌：浮层内部按控件内边距走 inset 档）
_PAD_X = T("layout.inset.pad_x")
_PAD_Y = T("layout.inset.pad_y")
#: 内容宽度上限：防止一行长文本把浮层拉成整屏宽的横幅
_CONTENT_MAX_W = T("layout.card.pad_x") * T("space.10") // 2


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
        self.setObjectName(_ROOT_ID)
        self.setAttribute(Qt.WA_TranslucentBackground)
        # Windows 上只给 WA_TranslucentBackground 不够：Qt 仍会用窗口的
        # 系统背景刷子把整个窗口矩形（含箭头周围）填成不透明色，
        # 于是真机上看到一圈矩形色块。WA_NoSystemBackground 明确告诉 Qt
        # 「背景我自己管，别碰」，本组件只由 paintEvent 绘制。
        # 离屏平台（offscreen）不体现这个差异，必须靠它保证真机正确。
        self.setAttribute(Qt.WA_NoSystemBackground)
        self.setAutoFillBackground(False)
        self._placement = "top"
        self._anchor_center = None  # 锚点中心（全局坐标），用于箭头的对齐
        self._anim_opacity = None
        self._anim_pos = None

        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(0)
        self._apply_margins()

        # 卡体内容宿主：透明层，只承担「描边 / 箭头预留」与
        # 「内容内边距」的解耦——外层管几何，内层管 inset，
        # 这样两段间距各自都是纯令牌值（改外层几何不会挤到文字）。
        self._card_host = QWidget(self)
        self._card_host.setObjectName(_CARD_HOST_ID)
        self._card_layout = QVBoxLayout(self._card_host)
        self._card_layout.setContentsMargins(_PAD_X, _PAD_Y, _PAD_X, _PAD_Y)
        self._card_layout.setSpacing(T("layout.card.title_gap"))
        self._layout.addWidget(self._card_host)

        self._title_label = QLabel(title, self._card_host)
        set_property(self._title_label, "uikPh", "popTitle")
        self._title_label.setVisible(bool(title))
        self._card_layout.addWidget(self._title_label)

        self._content_host = QWidget(self._card_host)
        self._content_host.setObjectName(_CONTENT_HOST_ID)
        self._content_layout = QVBoxLayout(self._content_host)
        self._content_layout.setContentsMargins(0, 0, 0, 0)
        self._card_layout.addWidget(self._content_host)
        if content is not None:
            self.set_content(content)
        self._reload_style()
        ThemeManager.instance().theme_changed.connect(self._reload_style)

    # ------------------------------------------------------------------ 内容
    def set_title(self, title: str) -> None:
        """设置标题；空串隐藏标题行。"""
        self._title_label.setText(title)
        self._title_label.setVisible(bool(title))

    def set_content(self, content) -> None:
        """设置内容：控件或文本（替换旧内容，旧控件销毁）。"""
        while self._content_layout.count():
            item = self._content_layout.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
        if isinstance(content, str):
            label = QLabel(content, self._content_host)
            set_property(label, "uikPh", "popBody")
            label.setWordWrap(True)
            label.setMaximumWidth(_CONTENT_MAX_W)
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
        # 先置透明再显示：慢机上避免 show 后闪一帧全不透明
        self.setWindowOpacity(0.0)
        self.show()
        self.raise_()
        self._start_enter_animation(pos)

    def placement(self) -> str:
        return self._placement

    def hideEvent(self, event) -> None:
        self._stop_enter_animation()
        super().hideEvent(event)

    def _reload_style(self) -> None:
        """窗口级样式表：透明底 + 标题 / 正文字阶。

        **为什么不在每个标签上用 ``set_font``**：``QToolTip`` 之外的
        透明无边框弹出窗（``Qt.Popup | FramelessWindowHint`` +
        ``WA_TranslucentBackground``）里，控件级 ``font-size`` 样式表会
        让标签的字体度量缓存失效——离屏渲染实测文字被竖向拉伸约 3 倍
        （同一份内容改用窗口级样式表则完全正常）。所以这里统一把字阶
        挂在窗口样式表上，用 ``uikPh`` 属性选择器区分标题与正文，
        令牌仍然只从 ``T()`` 取，且随 ``theme_changed`` 重建。

        **透明底必须用 ID 选择器，不能写成无选择器的
        ``background: transparent``**：全局基座 QSS 里有
        ``QWidget {{ background-color: bg.base }}``，特异度 ``(0,0,1)``；
        而实例样式表里裸写的 ``background: transparent`` 等价于通配选择器
        ``*``，特异度 ``(0,0,0)``，**比不过全局规则**——窗口和两个宿主
        控件会被刷上不透明底色。真机上表现为卡体外一圈矩形色块（暗色
        就是最初反馈的"黑色方框"）。改用 ``QWidget#id`` 后特异度
        ``(0,1,1)``，稳压全局规则，且只命中本组件自己的三个容器。
        标题 / 正文标签同理：全局 ``QWidget`` 规则也会给 QLabel 刷
        bg.base（暗色下会在卡体上留下比卡体更暗的矩形），这里用后代
        选择器一并清掉。
        """
        self.setStyleSheet(f"""
        QWidget#{_ROOT_ID},
        QWidget#{_CARD_HOST_ID},
        QWidget#{_CONTENT_HOST_ID},
        QWidget#{_ROOT_ID} QLabel {{
            background: transparent;
        }}
        QLabel[uikPh="popTitle"] {{
            font-size: {T("font.md")}px;
            font-weight: {T("font.weight.semibold")};
            color: {T("color.text.primary")};
        }}
        QLabel[uikPh="popBody"] {{
            font-size: {T("font.sm")}px;
            color: {T("color.text.secondary")};
        }}
        """)
        self.update()

    # ------------------------------------------------------------------ 内部
    def _margins(self) -> tuple:
        """窗口四边为「描边 + 箭头」预留的边距 (left, top, right, bottom)。

        只剩两件事要预留：容纳 1px 描边（描边跨在路径上，向外多出 0.5px），
        以及箭头所在那一侧的箭头自身长度。**没有阴影，也就不需要为投影
        预留任何半透明过渡带**——窗口里除了箭头周围，其余像素全部由不透明
        的卡体铺满，不存在可能被合成器显示成色块的半透明区域。
        """
        side = {"top": "bottom", "bottom": "top",
                "left": "left", "right": "right"}[self._placement]
        margins = {"left": _BORDER_M, "top": _BORDER_M,
                   "right": _BORDER_M, "bottom": _BORDER_M}
        margins[side] = _BORDER_M + _ARROW_H
        return (margins["left"], margins["top"],
                margins["right"], margins["bottom"])

    def _apply_margins(self) -> None:
        """外层布局内边距 = 描边宽度 + 箭头长度。

        内容内边距由内层 ``_card_layout`` 的 ``_PAD_X / _PAD_Y`` 承担，
        两段解耦：外层几何变化不会把文字挤到卡体边缘。
        """
        self._layout.setContentsMargins(*self._margins())

    def _card_rect(self) -> QRectF:
        """卡片主体矩形（不含箭头）。"""
        left, top, right, bottom = self._margins()
        return QRectF(self.rect()).adjusted(left, top, -right, -bottom)

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

        # -- 卡体本体：圆角矩形 + 箭头合成一条路径，一次成型
        #    （箭头与底色同色、相接处无接缝）
        #
        #    **不画阴影**。此前用 16 层不同 alpha 的圆角路径叠加模拟柔和
        #    投影，卡体外围形成一圈半透明过渡带；真机合成器如何处理这圈
        #    alpha 无法在离屏环境保证，实测在 Windows 上表现为卡体外一圈
        #    矩形色块。改为 1px 实线描边承担层次（符合扁平化规范），
        #    卡体与箭头全部不透明铺满窗口边缘，不再有半透明过渡带。
        painter.setPen(Qt.NoPen)
        painter.setBrush(bg)
        painter.drawPath(bubble)
        painter.setBrush(Qt.NoBrush)
        pen = QPen(border)
        pen.setWidthF(_BORDER_W)
        painter.setPen(pen)
        painter.drawPath(bubble)
        painter.end()
