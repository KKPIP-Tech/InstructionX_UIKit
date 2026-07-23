# -*- coding: utf-8 -*-
"""节点外观（BP_SPEC §4）。

``NodeWidget`` 是 ``BlueprintNode`` 的可视化：

- 标题栏（accent 色带 + 标题 + 状态图标区）；
- 引脚区：左输入右输出，引脚 = 彩色圆点 + 名称，``multi`` 引脚双环；
- 自定义体区：``NodeSpec.body_builder`` 注入；缺省显示 properties 键值；
- 状态视觉：running = 标题栏 SpinnerArc + accent 脉冲描边；
  done = success 2px 描边 + 耗时徽标胶囊；error = danger 描边 + 错误图标；
  选中 = primary 2px 描边 + shadow.md。

实现要点（供维护者参考）：

- 全部内容以「逻辑坐标」自绘，画布缩放时控件几何 = 逻辑矩形 × zoom，
  ``paintEvent`` 里 ``painter.scale`` 同步缩放（高 DPI / 任意缩放清晰）；
- 引脚热区 ``PinHandle`` 是真实子控件（透明），``pin_widget(pin_id)``
  返回它，画布据其全局坐标画线、并以其接收鼠标按下；
- 本项目全局 QSS 有 ``QWidget { background: bg.base }`` 基座规则，
  本控件与全部子控件均 ``setAutoFillBackground(False)`` + 实例级
  ``background: transparent``（透明前科规避）。
"""

import math

from PySide6.QtCore import QPointF, QRectF, QSizeF, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QFrame, QVBoxLayout, QWidget

from ..anim.painted import SpinnerArc
from ..theme import T, ThemeManager, apply_shadow
from .model import BlueprintNode, PinDirection
from .registry import NodeRegistry, pin_color

__all__ = ["NodeWidget", "PinHandle", "format_elapsed"]

#: 逻辑尺寸常量（px，缩放由画布视图系数负责）
TITLE_H = 28.0
PIN_ROW_H = 24.0
PIN_DOT_R = 5.0
PIN_HANDLE = 18.0
PAD_X = 10.0
PAD_BOTTOM = 8.0
BODY_LINE_H = 20.0
MIN_W = 160.0
SPINNER_SIZE = 14.0
#: 节点体（body_builder 注入的真实子控件）可见的最低画布缩放。
#: 低于该缩放时体区几何被压缩、控件最小像素高度会导致挤压重叠，
#: 故整体隐藏体容器（仅保留标题栏 + 引脚），回升后自动恢复。
BODY_MIN_ZOOM = 0.8


def _transparent(widget: QWidget) -> None:
    """让控件背景真正透明（规避全局 QSS 的 QWidget 底色规则）。"""
    widget.setAutoFillBackground(False)
    widget.setStyleSheet("background: transparent;")


def safe_slot(fn):
    """包装信号槽：目标控件已销毁时静默忽略。

    主题切换等全局广播信号可能在控件销毁后仍触发已连接的 lambda
    （PySide 对 Python 可调用对象不自动断开），包装后避免
    ``RuntimeError: Internal C++ object already deleted`` 噪音。
    """

    def wrapper(*args):
        try:
            fn(*args)
        except RuntimeError:
            pass

    return wrapper


def _resolve_color(value, fallback_key: str) -> QColor:
    """把令牌键 / hex / None 解析为 QColor（实时取色，主题感知）。"""
    if not value:
        return QColor(str(T(f"color.{fallback_key}")))
    text = str(value)
    if text.startswith("#") or text.startswith("rgb"):
        return QColor(text)
    return QColor(str(T(f"color.{text}")))


def _text_on(color: QColor) -> QColor:
    """按底色亮度选择黑 / 白前景色。"""
    lum = 0.299 * color.red() + 0.587 * color.green() + 0.114 * color.blue()
    return QColor("#1C2330") if lum > 150 else QColor("#FFFFFF")


def format_elapsed(ms) -> str:
    """把毫秒格式化为耗时徽标文本：``"12 ms"`` / ``"1.2 s"``。

    规则：小于 1000 毫秒取整显示 ``ms``，否则保留一位小数显示 ``s``。
    """
    if ms is None:
        return ""
    ms = float(ms)
    if ms < 1000.0:
        return f"{ms:.0f} ms"
    return f"{ms / 1000.0:.1f} s"


class PinHandle(QWidget):
    """引脚热区控件（透明小方块，居中于引脚圆点）。

    画布对它安装事件过滤器以捕获按下拖线；``pin`` 为 ``Pin`` 数据对象，
    ``node_widget`` 回指所属节点控件。
    """

    def __init__(self, node_widget: "NodeWidget", pin):
        super().__init__(node_widget)
        self.node_widget = node_widget
        self.pin = pin
        self.setAttribute(Qt.WA_TransparentForMouseEvents, False)
        self.setCursor(Qt.CrossCursor)
        self.setToolTip(f"{pin.name} ({pin.data_type})")
        _transparent(self)

    def logical_center(self) -> QPointF:
        """引脚圆心的节点逻辑坐标。"""
        return self.node_widget.pin_logical_center(self.pin)

    def scene_center(self) -> QPointF:
        """引脚圆心的场景坐标（节点 pos + 逻辑偏移）。"""
        return self.node_widget.node.pos + self.logical_center()


class NodeWidget(QFrame):
    """蓝图节点控件（绑定 ``BlueprintNode``）。

    参数:
        node: 数据节点（引脚 / 标题 / 属性 / 状态变化会自动反映到外观）。

    供画布使用的接口：
        ``pin_widget(pin_id)``：取引脚热区控件（用于全局坐标 / 事件）；
        ``set_selected(bool)``：选中态（primary 描边 + shadow.md）；
        ``apply_view(scene_pos, scale)``：由画布按视图变换放置；
        ``badge_rect()``：done 耗时徽标的逻辑矩形（测试像素断言用）；
        ``elapsed_text()``：当前耗时徽标文本。
    """

    def __init__(self, node: BlueprintNode, parent=None):
        super().__init__(parent)
        self.node = node
        self._selected = False
        self._scale = 1.0
        self._handles = {}
        self._body = None
        self._spinner = None
        self._pulse = 0.0
        self._body_h = 0.0
        _transparent(self)
        self.setAttribute(Qt.WA_StyledBackground, False)
        self.setMouseTracking(True)

        # 引脚热区（键 = (方向, 引脚 id)：输入 / 输出允许同名 id）
        for pin in node.inputs + node.outputs:
            self._handles[(pin.direction, pin.id)] = PinHandle(self, pin)

        # 自定义体 / 缺省 properties 展示
        spec = NodeRegistry.instance().spec(node.type_name)
        if spec is not None and spec.body_builder is not None:
            self._body = QWidget(self)
            _transparent(self._body)
            lay = QVBoxLayout(self._body)
            lay.setContentsMargins(0, 0, 0, 0)
            lay.setSpacing(int(T("space.1")))
            spec.body_builder(node, self._body)

        # running 旋转圈（标题栏状态图标区）
        self._spinner = SpinnerArc(size=int(SPINNER_SIZE), line_width=2, parent=self)
        _transparent(self._spinner)
        self._spinner.hide()

        # running 脉冲描边定时器（DURATION.slow 一拍）
        self._pulse_timer = QTimer(self)
        self._pulse_timer.setInterval(33)
        self._pulse_timer.timeout.connect(self._tick_pulse)

        node.changed.connect(self._on_node_changed)
        node.status_changed.connect(self._on_status_changed)
        ThemeManager.instance().theme_changed.connect(
            safe_slot(lambda *_: self.update()))

        self._relayout()
        self._on_status_changed(node.status)

    # ------------------------------------------------------------------
    # 布局（逻辑坐标）
    # ------------------------------------------------------------------
    def _title_font(self) -> QFont:
        f = QFont(self.font())
        f.setPixelSize(int(T("font.sm")))
        f.setWeight(QFont.DemiBold)
        return f

    def _pin_font(self) -> QFont:
        f = QFont(self.font())
        f.setPixelSize(int(T("font.xs")))
        return f

    def _body_visible(self) -> bool:
        """当前缩放下节点体是否可见（低于 ``BODY_MIN_ZOOM`` 隐藏）。

        节点体是真实子控件，几何随缩放压缩而控件自身有最小像素高度，
        低缩放会挤压重叠；隐藏后节点尺寸仅按标题栏 + 引脚计算。
        """
        return self._body is not None and self._scale >= BODY_MIN_ZOOM

    def _relayout(self) -> None:
        """按内容重算逻辑尺寸并写回 ``node.size``，再重排子控件。"""
        fm_title = self.fontMetrics()
        title_font = self._title_font()
        from PySide6.QtGui import QFontMetrics
        tw = QFontMetrics(title_font).horizontalAdvance(self.node.title) + 64.0
        pin_font = self._pin_font()
        pfm = QFontMetrics(pin_font)
        rows = max(len(self.node.inputs), len(self.node.outputs))
        pin_w = 0.0
        for i in range(rows):
            lw = pfm.horizontalAdvance(self.node.inputs[i].name) if i < len(self.node.inputs) else 0
            rw = pfm.horizontalAdvance(self.node.outputs[i].name) if i < len(self.node.outputs) else 0
            pin_w = max(pin_w, float(lw + rw) + 72.0)
        body_w = 0.0
        self._body_h = 0.0
        if self._body is not None:
            visible = self._body_visible()
            if self._body.isVisible() != visible:
                self._body.setVisible(visible)
            if visible:
                hint = self._body.sizeHint()
                body_w = float(max(hint.width(), 0)) + 2 * PAD_X
                self._body_h = float(max(hint.height(), 0)) + 8.0
        elif self.node.properties:
            keys = list(self.node.properties.items())
            for k, v in keys:
                body_w = max(body_w, float(pfm.horizontalAdvance(f"{k}: {v}")) + 2 * PAD_X)
            self._body_h = BODY_LINE_H * len(keys) + 6.0
        w = max(MIN_W, tw, pin_w, body_w)
        h = TITLE_H + rows * PIN_ROW_H + self._body_h + PAD_BOTTOM
        self.node.size = QSizeF(w, h)
        self._arrange_children()

    def _arrange_children(self) -> None:
        """把子控件（引脚热区 / 自定义体 / 旋转圈）按视图系数落位。"""
        s = self._scale
        hs = max(8.0, PIN_HANDLE * s)
        for handle in self._handles.values():
            c = self.pin_logical_center(handle.pin)
            handle.setGeometry(int(c.x() * s - hs / 2), int(c.y() * s - hs / 2),
                               int(hs), int(hs))
        if self._body is not None and self._body.isVisible():
            y = (TITLE_H + max(len(self.node.inputs), len(self.node.outputs)) * PIN_ROW_H + 4.0) * s
            self._body.setGeometry(int(PAD_X * s), int(y),
                                   max(10, int(self.width() - 2 * PAD_X * s)),
                                   max(10, int(self._body_h * s - 8)))
        ss = max(8.0, SPINNER_SIZE * s)
        self._spinner.setGeometry(int(self.width() - ss - 7 * s),
                                  int((TITLE_H * s - ss) / 2), int(ss), int(ss))

    def pin_logical_center(self, pin) -> QPointF:
        """引脚圆心的节点逻辑坐标（输入在左缘、输出在右缘）。"""
        w = self.node.size.width()
        if pin.direction is PinDirection.Input:
            idx = self.node.inputs.index(pin)
            return QPointF(0.0, TITLE_H + idx * PIN_ROW_H + PIN_ROW_H / 2)
        idx = self.node.outputs.index(pin)
        return QPointF(w, TITLE_H + idx * PIN_ROW_H + PIN_ROW_H / 2)

    def pin_widget(self, pin_id: str, direction=None):
        """返回引脚热区控件（供画布取全局坐标 / 命中检测）。

        参数:
            pin_id: 引脚 id。
            direction: 可选 ``PinDirection``。输入 / 输出同名 id 时必须
                指定方向；省略时按先输入后输出返回首个命中。
        """
        if direction is not None:
            return self._handles.get((direction, pin_id))
        return (self._handles.get((PinDirection.Input, pin_id))
                or self._handles.get((PinDirection.Output, pin_id)))

    # ------------------------------------------------------------------
    # 视图放置（由画布调用）
    # ------------------------------------------------------------------
    def apply_view(self, scene_pos: QPointF, scale: float) -> None:
        """按场景坐标与缩放系数放置控件（几何 = 逻辑矩形 × scale）。

        缩放跨过 ``BODY_MIN_ZOOM`` 时触发一次 ``_relayout``：隐藏 / 恢复
        节点体并把节点逻辑尺寸收窄为标题栏 + 引脚（或还原）。
        """
        self._scale = max(0.05, float(scale))
        if self._body is not None and self._body.isVisible() != self._body_visible():
            self._relayout()
        self.setGeometry(int(scene_pos.x()), int(scene_pos.y()),
                         max(20, int(self.node.size.width() * self._scale)),
                         max(20, int(self.node.size.height() * self._scale)))
        self._arrange_children()
        self.update()

    # ------------------------------------------------------------------
    # 选中 / 状态
    # ------------------------------------------------------------------
    def set_selected(self, on: bool) -> None:
        """设置选中态：primary 2px 描边 + shadow.md（取消时移除阴影）。"""
        on = bool(on)
        if on == self._selected:
            return
        self._selected = on
        if on:
            apply_shadow(self, "md")
        else:
            self.setGraphicsEffect(None)
        self.update()

    def is_selected(self) -> bool:
        """当前是否选中。"""
        return self._selected

    def elapsed_text(self) -> str:
        """当前耗时徽标文本（done 状态有值，其余为空串）。"""
        if self.node.status == "done" and self.node.elapsed_ms is not None:
            return format_elapsed(self.node.elapsed_ms)
        return ""

    def badge_rect(self) -> QRectF:
        """done 耗时徽标的节点逻辑矩形（无徽标时返回空矩形）。"""
        text = self.elapsed_text()
        if not text:
            return QRectF()
        f = QFont(self.font())
        f.setPixelSize(int(T("font.xs")))
        from PySide6.QtGui import QFontMetrics
        tw = QFontMetrics(f).horizontalAdvance(text)
        bw, bh = tw + 14.0, 18.0
        return QRectF(self.node.size.width() - bw - 6.0,
                      (TITLE_H - bh) / 2, bw, bh)

    def accent_color(self) -> QColor:
        """标题栏强调色（令牌键 / hex 实时解析，缺省灰）。"""
        return _resolve_color(self.node.accent, "text.tertiary")

    # ------------------------------------------------------------------
    # 状态切换
    # ------------------------------------------------------------------
    def _on_status_changed(self, status: str) -> None:
        running = status == "running"
        self._spinner.setVisible(running)
        if running:
            self._spinner.start()
            self._pulse_timer.start()
        else:
            self._spinner.stop()
            self._pulse_timer.stop()
            self._pulse = 0.0
        if status == "error" and self.node.error_message:
            self.setToolTip(self.node.error_message)
        else:
            self.setToolTip("")
        self.update()

    def _on_node_changed(self) -> None:
        self._relayout()
        parent = self.parentWidget()
        if parent is not None and hasattr(parent, "_node_layout_changed"):
            parent._node_layout_changed(self)
        self.update()

    def _tick_pulse(self) -> None:
        self._pulse += 0.033
        self.update()

    # ------------------------------------------------------------------
    # 绘制
    # ------------------------------------------------------------------
    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.TextAntialiasing)
        s = self._scale
        p.scale(s, s)
        w, h = self.node.size.width(), self.node.size.height()
        radius = float(T("radius.lg"))
        accent = self.accent_color()
        status = self.node.status

        # 底
        rect = QRectF(1.0, 1.0, w - 2.0, h - 2.0)
        path = QPainterPath()
        path.addRoundedRect(rect, radius, radius)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(str(T("color.bg.elevated"))))
        p.drawPath(path)

        # 标题栏（accent 色带，上圆角）
        band = QPainterPath()
        band.addRoundedRect(QRectF(1.0, 1.0, w - 2.0, TITLE_H + radius),
                            radius, radius)
        clip = QPainterPath()
        clip.addRect(QRectF(1.0, 1.0, w - 2.0, TITLE_H))
        p.setPen(Qt.NoPen)
        p.setBrush(accent)
        p.drawPath(band.intersected(clip))
        # 标题栏分隔线
        p.setPen(QPen(QColor(str(T("color.border"))), 1.0))
        p.drawLine(QPointF(1.0, TITLE_H), QPointF(w - 1.0, TITLE_H))

        # 标题文本
        p.setFont(self._title_font())
        p.setPen(_text_on(accent))
        title_rect = QRectF(PAD_X, 0.0, w - 2 * PAD_X - 24.0, TITLE_H)
        p.drawText(title_rect, Qt.AlignVCenter | Qt.AlignLeft, self.node.title)

        # 状态图标区（标题右侧）
        if status == "done":
            text = self.elapsed_text()
            if text:
                br = self.badge_rect()
                p.setPen(Qt.NoPen)
                p.setBrush(QColor(str(T("color.bg.muted"))))
                p.drawRoundedRect(br, br.height() / 2, br.height() / 2)
                f = QFont(self.font())
                f.setPixelSize(int(T("font.xs")))
                p.setFont(f)
                p.setPen(QColor(str(T("color.text.secondary"))))
                p.drawText(br, Qt.AlignCenter, text)
        elif status == "error":
            cx = w - 6.0 - SPINNER_SIZE / 2
            cy = TITLE_H / 2
            r = SPINNER_SIZE / 2
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(str(T("color.danger"))))
            p.drawEllipse(QPointF(cx, cy), r, r)
            p.setPen(QPen(QColor("#FFFFFF"), 1.8, Qt.SolidLine, Qt.RoundCap))
            d = r * 0.42
            p.drawLine(QPointF(cx - d, cy - d), QPointF(cx + d, cy + d))
            p.drawLine(QPointF(cx - d, cy + d), QPointF(cx + d, cy - d))

        # 引脚区
        self._draw_pins(p)

        # 缺省体：properties 键值
        if self._body is None and self.node.properties:
            f = self._pin_font()
            p.setFont(f)
            y = TITLE_H + max(len(self.node.inputs), len(self.node.outputs)) * PIN_ROW_H + 4.0
            for k, v in self.node.properties.items():
                p.setPen(QColor(str(T("color.text.tertiary"))))
                p.drawText(QRectF(PAD_X, y, w - 2 * PAD_X, BODY_LINE_H),
                           Qt.AlignVCenter | Qt.AlignLeft, f"{k}: {v}")
                y += BODY_LINE_H

        # 描边（选中 > 状态 > 普通）
        border_color = QColor(str(T("color.border")))
        border_w = 1.2
        if status == "done":
            border_color = QColor(str(T("color.success")))
            border_w = 2.0
        elif status == "error":
            border_color = QColor(str(T("color.danger")))
            border_w = 2.0
        elif status == "running":
            pulse = 0.55 + 0.45 * math.sin(self._pulse * 2 * math.pi / 0.32)
            border_color = QColor(accent)
            border_color.setAlpha(int(120 + 135 * pulse))
            border_w = 2.0
        if self._selected:
            border_color = QColor(str(T("color.primary")))
            border_w = 2.0
        p.setPen(QPen(border_color, border_w))
        p.setBrush(Qt.NoBrush)
        p.drawPath(path)
        p.end()

    def _draw_pins(self, p: QPainter) -> None:
        """绘制引脚行：彩色圆点（multi 双环）+ 名称。"""
        f = self._pin_font()
        p.setFont(f)
        w = self.node.size.width()
        text_color = QColor(str(T("color.text.secondary")))
        for pin in self.node.inputs:
            c = self.pin_logical_center(pin)
            color = QColor(pin_color(pin.data_type))
            p.setPen(Qt.NoPen)
            p.setBrush(color)
            p.drawEllipse(c, PIN_DOT_R, PIN_DOT_R)
            if pin.multi:  # 双环
                p.setPen(QPen(color, 1.4))
                p.setBrush(Qt.NoBrush)
                p.drawEllipse(c, PIN_DOT_R + 3.0, PIN_DOT_R + 3.0)
            p.setPen(text_color)
            p.drawText(QRectF(c.x() + 10.0, c.y() - PIN_ROW_H / 2,
                              w / 2, PIN_ROW_H),
                       Qt.AlignVCenter | Qt.AlignLeft, pin.name)
        for pin in self.node.outputs:
            c = self.pin_logical_center(pin)
            color = QColor(pin_color(pin.data_type))
            p.setPen(Qt.NoPen)
            p.setBrush(color)
            p.drawEllipse(c, PIN_DOT_R, PIN_DOT_R)
            if pin.multi:
                p.setPen(QPen(color, 1.4))
                p.setBrush(Qt.NoBrush)
                p.drawEllipse(c, PIN_DOT_R + 3.0, PIN_DOT_R + 3.0)
            p.setPen(text_color)
            p.drawText(QRectF(c.x() - 10.0 - w / 2, c.y() - PIN_ROW_H / 2,
                              w / 2, PIN_ROW_H),
                       Qt.AlignVCenter | Qt.AlignRight, pin.name)

    # ------------------------------------------------------------------
    # 事件
    # ------------------------------------------------------------------
    def refresh_theme(self) -> None:
        """主题切换时重排并重绘（画布 / 测试可直接调用）。"""
        self._relayout()
        self.update()
