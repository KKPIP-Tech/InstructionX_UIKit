# -*- coding: utf-8 -*-
"""单行输入框组件（SPEC §5.1）。

``LineEdit`` 基于 QLineEdit，提供：前缀 / 后缀图标槽（QIcon 或文本符号）、
内置清除按钮、密码可见性切换（自绘眼睛图标）、error 红色边框状态
以及 sm / md / lg 尺寸档（动态属性命中全局 QSS）。

修复要点（fix/f2）：

- **文本垂直居中**：Fusion 风格下 QLineEdit 按字体行高盒居中，行高盒的
  ascent/descent 分配使墨迹视觉中心偏下约 1px（CJK 更明显）。组件以
  ``textMargins`` 底部 +2px 抵消（实例级覆盖，不改全局 QSS），
  sm/md/lg 三档墨迹中心与控件中心偏差 <= 1px。
- **右侧槽位顺序与遮挡**：Qt 侧槽按钮宽度被 ``QLineEditPrivate`` 固定为
  ``iconSize + 6``（图标强制压入正方形），多字符后缀文本（如 ".com"）
  会被挤压不可读，且 Qt 强制清除按钮位于最左槽位。组件对放不下的文本
  符号改用**透明占位图标 + paintEvent 手工绘制**（槽位按钮仍保留，
  提供点击与宽度预留），并在 paintEvent 前把可见侧槽按钮按
  [后缀][清除 ×][眼睛] 的顺序紧凑重排，``textMargins`` 为超宽文本预留
  额外空间，各槽位墨迹互不相交。
"""

import math

from PySide6.QtCore import Qt, QPointF
from PySide6.QtGui import (
    QAction,
    QColor,
    QFontMetricsF,
    QIcon,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
)
from PySide6.QtWidgets import QLineEdit, QStyle, QStyleOptionFrame, QToolButton

from ..theme import T, ThemeManager, set_property

__all__ = ["LineEdit"]

_SIZES = ("sm", "md", "lg")

#: 各尺寸档的槽位图标边长（取间距令牌，避免魔法数）
_ICON_TOKEN = {"sm": "space.3", "md": "space.4", "lg": "space.5"}

#: textMargins 底部补偿：行高盒墨迹偏下 1px，+2 上移 1px 精确居中
_VCENTER_BOTTOM = 2
#: 手工绘制槽位文本与正文 / 槽位按钮之间的最小间隔
_SLOT_GAP = 2
#: 手工绘制文本距槽位按钮边缘的内缩
_SLOT_INSET = 3


def _icon_edge(size: str) -> int:
    """按尺寸档取图标边长（令牌值）。"""
    return int(T(_ICON_TOKEN.get(size, "space.4")))


def _render_icon(draw, color: str, size: int = 16, dpr: float = 1.0) -> QIcon:
    """把绘制函数渲染为 size x size（逻辑像素）的透明底高 DPR QIcon。

    以矢量方式直接绘制到 ``size * dpr`` 设备像素的 QPixmap 并设置
    ``devicePixelRatio``，高 DPI 下不再由 1x 位图插值放大（模糊根因）。
    """
    dpr = max(1.0, float(dpr))
    pm = QPixmap(int(round(size * dpr)), int(round(size * dpr)))
    pm.setDevicePixelRatio(dpr)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    draw(p, QColor(color), float(size))
    p.end()
    return QIcon(pm)


def _transparent_icon(size: int = 16, dpr: float = 1.0) -> QIcon:
    """边长 size 的透明占位图标（槽位按钮仍在，但不绘制任何墨迹）。"""
    dpr = max(1.0, float(dpr))
    pm = QPixmap(int(round(size * dpr)), int(round(size * dpr)))
    pm.setDevicePixelRatio(dpr)
    pm.fill(Qt.transparent)
    return QIcon(pm)


def _draw_text_symbol(text: str):
    """生成按文本符号绘制图标的函数（按墨迹盒居中，而非字体行高盒）。"""
    def fn(p: QPainter, color: QColor, s: float):
        p.setPen(color)
        font = p.font()
        font.setPixelSize(int(s * 0.8))
        p.setFont(font)
        ink = QFontMetricsF(font).tightBoundingRect(text)
        # drawText 锚点为 (left, baseline)，反向平移使墨迹中心对齐图标中心
        p.drawText(QPointF(s / 2.0 - ink.center().x(),
                           s / 2.0 - ink.center().y()), text)
    return fn


def _draw_eye(off: bool):
    """生成眼睛 / 眼睛关闭图标的绘制函数（自绘，避免引入图标资源）。"""
    def fn(p: QPainter, color: QColor, s: float):
        pen = QPen(color)
        pen.setWidthF(1.4)
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        # 杏仁形眼眶：两条二次贝塞尔曲线
        path = QPainterPath(QPointF(s * 0.10, s * 0.5))
        path.quadTo(QPointF(s * 0.5, s * 0.08), QPointF(s * 0.90, s * 0.5))
        path.quadTo(QPointF(s * 0.5, s * 0.92), QPointF(s * 0.10, s * 0.5))
        p.drawPath(path)
        # 瞳孔
        p.setBrush(color)
        p.drawEllipse(QPointF(s * 0.5, s * 0.5), s * 0.13, s * 0.13)
        if off:
            p.setBrush(Qt.NoBrush)
            p.drawLine(QPointF(s * 0.16, s * 0.86), QPointF(s * 0.86, s * 0.14))
    return fn


def _draw_clear():
    """生成清除（×）图标的绘制函数。"""
    def fn(p: QPainter, color: QColor, s: float):
        pen = QPen(color)
        pen.setWidthF(1.4)
        pen.setCapStyle(Qt.RoundCap)
        p.setPen(pen)
        m = s * 0.30
        p.drawLine(QPointF(m, m), QPointF(s - m, s - m))
        p.drawLine(QPointF(m, s - m), QPointF(s - m, m))
    return fn


class LineEdit(QLineEdit):
    """单行输入框。

    用途:
        文本录入，支持前后缀图标、清除按钮、密码可见切换与错误态。

    参数:
        text: 初始文本。
        placeholder: 占位提示。
        size: ``sm`` / ``md`` / ``lg``，高度 24 / 32 / 40。
        clearable: 是否启用内置清除按钮。
        parent: 父控件。

    示例::

        edit = LineEdit(placeholder="请输入用户名", clearable=True)
        edit.set_prefix_icon("@")
        edit.set_error(True)          # 红色边框

    备注:
        文本符号槽位若放入正方形图标会被挤压（如 ".com"），组件自动改为
        手工绘制并保留槽位按钮（点击仍触发对应 QAction）；右侧槽位视觉
        顺序固定为 [后缀][清除 ×][眼睛]。
    """

    def __init__(self, text: str = "", placeholder: str = "", size: str = "md",
                 clearable: bool = False, parent=None):
        super().__init__(text, parent)
        self._prefix_action = None
        self._suffix_action = None
        self._pwd_action = None
        self._prefix_symbol = None
        self._suffix_symbol = None
        self._prefix_manual = False   # 前缀文本符号超宽，paintEvent 手工绘制
        self._suffix_manual = False   # 后缀文本符号超宽，paintEvent 手工绘制
        self._icons_dpr = 0.0  # 已渲染图标的 DPR（0 = 未渲染）
        if placeholder:
            self.setPlaceholderText(placeholder)
        self.set_size(size)
        if clearable:
            self.setClearButtonEnabled(True)
            self._refresh_icons()
        self._apply_text_margins()
        ThemeManager.instance().theme_changed.connect(self._on_theme_changed)

    # ------------------------------------------------------------------
    # 尺寸与错误态
    # ------------------------------------------------------------------

    def set_size(self, size: str) -> None:
        """设置尺寸档：``sm`` / ``md`` / ``lg``。"""
        if size not in _SIZES:
            raise ValueError(f"未知输入框尺寸: {size!r}")
        set_property(self, "size", size)
        # 图标边长随尺寸档变化，重新分类文本符号（方形图标 / 手工绘制）
        if self._prefix_symbol is not None:
            self.set_prefix_icon(self._prefix_symbol)
        if self._suffix_symbol is not None:
            self.set_suffix_icon(self._suffix_symbol)
        self._refresh_icons()
        self._apply_text_margins()

    def size_name(self) -> str:
        """当前尺寸档名。"""
        return self.property("uiksize") or "md"

    def set_error(self, error: bool) -> None:
        """设置错误态：红色边框（QSS ``[error="true"]`` 选择器）。"""
        set_property(self, "error", "true" if error else "false")

    def has_error(self) -> bool:
        """是否处于错误态。"""
        return self.property("error") == "true"

    # ------------------------------------------------------------------
    # 前缀 / 后缀图标槽
    # ------------------------------------------------------------------

    def set_prefix_icon(self, icon) -> None:
        """设置前缀图标（QIcon 或文本符号）；传 None 移除。"""
        self._prefix_action = self._set_slot_icon(
            self._prefix_action, icon, QLineEdit.LeadingPosition,
            "_prefix_symbol", "_prefix_manual")

    def set_suffix_icon(self, icon) -> None:
        """设置后缀图标（QIcon 或文本符号）；传 None 移除。"""
        self._suffix_action = self._set_slot_icon(
            self._suffix_action, icon, QLineEdit.TrailingPosition,
            "_suffix_symbol", "_suffix_manual")

    def _set_slot_icon(self, action, icon, position, symbol_attr, manual_attr):
        """内部：安装 / 替换 / 移除前后缀 action。"""
        if action is not None:
            self.removeAction(action)
            action.deleteLater()
            action = None
        setattr(self, symbol_attr, None)
        setattr(self, manual_attr, False)
        if icon is None:
            self._apply_text_margins()
            return None
        if isinstance(icon, QIcon):
            qicon = icon
        else:
            symbol = str(icon)
            setattr(self, symbol_attr, symbol)
            qicon, manual = self._symbol_icon(symbol)
            setattr(self, manual_attr, manual)
        action = QAction(qicon, "", self)
        self.addAction(action, position)
        self._apply_text_margins()
        return action

    def _symbol_icon(self, symbol: str):
        """文本符号 -> (图标, 是否手工绘制)。

        墨迹能放入正方形槽位时渲染普通图标；放不下的多字符文本
        （如 ".com"）改用透明占位图标，文本由 paintEvent 手工绘制，
        避免被压缩进正方形图标而不可读 / 与相邻槽位重叠。
        """
        edge = _icon_edge(self.size_name())
        ink = self._symbol_ink(symbol)
        if ink.width() <= edge - 2:
            return self._render_slot_icon(_draw_text_symbol(symbol)), False
        return _transparent_icon(edge, self.devicePixelRatioF()), True

    def _symbol_ink(self, symbol: str):
        """文本符号在槽位字号下的墨迹盒（QRectF）。"""
        font = self.font()
        font.setPixelSize(max(1, int(_icon_edge(self.size_name()) * 0.8)))
        return QFontMetricsF(font).tightBoundingRect(symbol)

    # ------------------------------------------------------------------
    # 槽位布局：顺序 [后缀][清除 ×][眼睛]，文本垂直居中，超宽文本预留
    # ------------------------------------------------------------------

    def _slot_metrics(self):
        """Qt 侧槽几何参数：(margin, widgetWidth, stride)，与 Qt 私有实现一致。"""
        style = self.style()
        icon = style.pixelMetric(QStyle.PM_LineEditIconSize, None, self)
        margin = style.pixelMetric(QStyle.PM_LineEditIconMargin, None, self)
        widget_width = icon + 6
        return margin, widget_width, margin + widget_width

    def _content_side_insets(self):
        """SE_LineEditContents 相对控件左右边缘的内缩（QSS padding + 边框）。"""
        opt = QStyleOptionFrame()
        self.initStyleOption(opt)
        r = self.style().subElementRect(QStyle.SE_LineEditContents, opt, self)
        if not r.isValid() or r.width() <= 0:
            return 0, 0
        left = r.left()
        right = (self.width() - 1) - r.right()
        return max(0, left), max(0, right)

    def _apply_text_margins(self) -> None:
        """设置 textMargins：底部 +2 垂直居中；左 / 右为超宽手工符号预留。

        推导：手工绘制文本带锚定在槽位按钮内侧，可向槽位外延伸
        ``ext`` px；正文矩形已由 Qt 按可见槽位数预留 stride 宽度，
        只需补偿 ``ext + gap - 内容区内缩`` 的超出部分。
        """
        margin, widget_width, stride = self._slot_metrics()
        inset_l, inset_r = self._content_side_insets()
        tm_l = tm_r = 0
        if self._prefix_manual and self._prefix_symbol is not None:
            w = math.ceil(self._symbol_ink(self._prefix_symbol).width())
            tm_l = max(0, w + _SLOT_GAP + _SLOT_INSET + margin
                       - stride - inset_l)
        if self._suffix_manual and self._suffix_symbol is not None:
            w = math.ceil(self._symbol_ink(self._suffix_symbol).width())
            tm_r = max(0, w + _SLOT_GAP + _SLOT_INSET + margin
                       - stride - inset_r)
        margins = (tm_l, 0, tm_r, _VCENTER_BOTTOM)
        current = self.textMargins()
        if (current.left(), current.top(), current.right(),
                current.bottom()) != margins:
            self.setTextMargins(*margins)

    def _slot_button(self, action) -> QToolButton:
        """返回 action 对应的侧槽按钮（QLineEditIconButton），无则 None。"""
        if action is None:
            return None
        for b in self.findChildren(QToolButton):
            if b.parent() is self and b.defaultAction() is action:
                return b
        return None

    def _reposition_slots(self) -> None:
        """把可见右侧槽位按钮按 [后缀][清除 ×][眼睛] 顺序紧凑重排。

        Qt 私有实现强制清除按钮为最左槽位且顺序由 action 插入次序决定；
        这里在每帧绘制前校正为设计顺序（幂等，仅在位置不符时移动）。
        """
        if self.width() <= 0:
            return
        margin, widget_width, stride = self._slot_metrics()
        buttons = (self._slot_button(self._suffix_action),
                   self._slot_button(self._clear_action()),
                   self._slot_button(self._pwd_action))
        visible = [b for b in buttons if b is not None and b.isVisibleTo(self)]
        n = len(visible)
        for i, b in enumerate(visible):
            k = n - 1 - i  # 从右往左的槽位序号（眼睛恒为最右）
            x = self.width() - widget_width - margin - stride * k
            if b.x() != x:
                b.move(x, b.y())

    def _paint_slot_symbol(self, painter: QPainter, symbol: str,
                           button: QToolButton, align_right: bool) -> None:
        """在槽位按钮内侧手工绘制文本符号（按墨迹盒精确垂直居中）。"""
        font = self.font()
        font.setPixelSize(max(1, int(_icon_edge(self.size_name()) * 0.8)))
        painter.setFont(font)
        painter.setPen(QColor(T("color.text.tertiary")))
        ink = QFontMetricsF(font).tightBoundingRect(symbol)
        center_y = (self.height() - 1) / 2.0
        baseline = center_y - ink.center().y()
        if align_right:
            x = button.geometry().right() - _SLOT_INSET - ink.right()
        else:
            x = button.geometry().left() + _SLOT_INSET - ink.left()
        painter.drawText(QPointF(x, baseline), symbol)

    # ------------------------------------------------------------------
    # 图标渲染：令牌尺寸 + 令牌色 + 按设备像素比矢量重绘
    # ------------------------------------------------------------------

    def _render_slot_icon(self, draw) -> QIcon:
        """按当前尺寸档令牌与设备 DPR 渲染槽位图标。"""
        edge = _icon_edge(self.size_name())
        self._icons_dpr = self.devicePixelRatioF()
        return _render_icon(draw, T("color.text.tertiary"), edge, self._icons_dpr)

    def _clear_action(self):
        """返回内置清除按钮的 QAction（Qt 私有对象名，找不到时返回 None）。"""
        for act in self.findChildren(QAction):
            if act.objectName() == "_q_qlineeditclearaction":
                return act
        return None

    def _refresh_icons(self) -> None:
        """重绘全部自绘图标：主题 / 尺寸档 / DPR 变化后保持清晰与配色。"""
        edge = _icon_edge(self.size_name())
        dpr = self.devicePixelRatioF()
        self._icons_dpr = dpr
        color = T("color.text.tertiary")
        for action, symbol, manual in (
                (self._prefix_action, self._prefix_symbol, self._prefix_manual),
                (self._suffix_action, self._suffix_symbol, self._suffix_manual)):
            if action is not None and symbol is not None:
                if manual:
                    action.setIcon(_transparent_icon(edge, dpr))
                else:
                    action.setIcon(_render_icon(
                        _draw_text_symbol(symbol), color, edge, dpr))
        if self._pwd_action is not None:
            self._pwd_action.setIcon(
                _render_icon(_draw_eye(off=self.echoMode() == QLineEdit.Password),
                             color, edge, dpr))
        if self.isClearButtonEnabled():
            act = self._clear_action()
            if act is not None:
                act.setIcon(_render_icon(_draw_clear(), color, edge, dpr))

    def paintEvent(self, event) -> None:
        """跨屏 DPR 变化重绘图标；校正槽位顺序；手工绘制超宽文本符号。"""
        dpr = self.devicePixelRatioF()
        if dpr != self._icons_dpr and (
                self._prefix_symbol is not None
                or self._suffix_symbol is not None
                or self._pwd_action is not None
                or self.isClearButtonEnabled()):
            self._refresh_icons()
        self._reposition_slots()
        super().paintEvent(event)
        if self._prefix_manual and self._prefix_symbol is not None:
            button = self._slot_button(self._prefix_action)
            if button is not None and button.isVisibleTo(self):
                p = QPainter(self)
                self._paint_slot_symbol(p, self._prefix_symbol, button, False)
                p.end()
        if self._suffix_manual and self._suffix_symbol is not None:
            button = self._slot_button(self._suffix_action)
            if button is not None and button.isVisibleTo(self):
                p = QPainter(self)
                self._paint_slot_symbol(p, self._suffix_symbol, button, True)
                p.end()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._apply_text_margins()
        self._reposition_slots()

    # ------------------------------------------------------------------
    # 密码可见切换
    # ------------------------------------------------------------------

    def set_password_mode(self, on: bool, toggleable: bool = True) -> None:
        """设置密码模式。

        参数:
            on: True 时以密文显示（Password 回显）。
            toggleable: 是否提供眼睛图标切换可见性。
        """
        if on:
            self.setEchoMode(QLineEdit.Password)
            if toggleable and self._pwd_action is None:
                self._pwd_action = QAction(
                    self._render_slot_icon(_draw_eye(off=True)), "", self)
                self._pwd_action.triggered.connect(self._toggle_password)
                self.addAction(self._pwd_action, QLineEdit.TrailingPosition)
        else:
            self.setEchoMode(QLineEdit.Normal)
            if self._pwd_action is not None:
                self.removeAction(self._pwd_action)
                self._pwd_action = None
        self._apply_text_margins()

    def _toggle_password(self) -> None:
        """在密文 / 明文之间切换并更新眼睛图标。"""
        if self.echoMode() == QLineEdit.Password:
            self.setEchoMode(QLineEdit.Normal)
        else:
            self.setEchoMode(QLineEdit.Password)
        self._refresh_icons()

    # ------------------------------------------------------------------
    # 主题切换：重绘文本符号 / 眼睛 / 清除图标
    # ------------------------------------------------------------------

    def _on_theme_changed(self, *_args) -> None:
        self._refresh_icons()
        self._apply_text_margins()
