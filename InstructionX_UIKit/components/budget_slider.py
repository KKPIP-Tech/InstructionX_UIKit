# -*- coding: utf-8 -*-
"""预算滑块组组件（SPEC §5.1）。

N 条滑块共享一个合计上限：每条轨道画满自身量程，组内剩余预算以
**反向色块**实时画在每条轨道上，手柄被夹取在色块右缘（上限墙）——
用户始终看到完整刻度、看到共享预算实时收缩，且物理上拖不过组预算
能支付的位置。超上限写入时按各行可削空间比例自动再分配收敛。

绘制颜色与字号全部经 ``T()`` 实时读取设计令牌（`_Theme` 实时视图，
主题切换无需重建）；主题 / 令牌变化经 ``ThemeManager.theme_changed``
与 ``TokenState.token_changed`` 内部订阅，自动身份色强制按新令牌重取。

用途:
    多项数值分配且合计有上限的场景（预算分配、资源配额、比例分配等）。

参数:
    title: 组标题（空串则不显示标题行）。
    specs: ``BudgetSpec`` 序列，一次性建行；None 建空组（显示空占位）。
    cap: 合计上限；None 表示上限 = 各行 maximum 之和（auto_cap）。
    framed: True 自绘卡片边框（圆角 ``radius.lg``）；False 透明无边框零边距。
    parent: 父控件。

示例::

    group = BudgetSliderGroup(specs=[BudgetSpec("CPU", maximum=40, value=22),
                                     BudgetSpec("内存", maximum=50, value=30)],
                              cap=60)
    group.valuesChanged.connect(print)
"""

from dataclasses import dataclass
from typing import List, Optional, Sequence

from PySide6.QtCore import (
    Property, QEasingCurve, QPointF, QPropertyAnimation, QRectF, QSize, Qt,
    Signal,
)
from PySide6.QtGui import (
    QColor, QFont, QFontMetrics, QFontMetricsF, QLinearGradient, QPainter,
    QPainterPath, QPen,
)
from PySide6.QtWidgets import (
    QAbstractSlider, QFrame, QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout,
    QWidget,
)
from shiboken6 import isValid as _shiboken_is_valid

from ..theme import T, ThemeManager
from ..tokens import TokenState

__all__ = ["BudgetSpec", "BudgetSliderGroup"]

# ---------------------------------------------------------------------------
# 模块私有常量
# ---------------------------------------------------------------------------

#: 度量（px）
_TRACK_H = 10            # 轨道高
_HANDLE_D = 20           # 手柄直径
_ROW_GAP = 10            # 行间距
_LABEL_W = 104           # 行首标签列宽默认值
_VALUE_W = 92            # 数值读数列宽下限
_CARD_PAD = 22           # 头卡内边距
_BAR_H = 12              # 堆叠分配条高
#: 行容器左右内边距（左侧为身份色点预留 26px）
_ROW_MARGIN_L, _ROW_MARGIN_R = 26, 12
_ROW_MARGIN_V = 6
#: 行内控件间距（色点列 → 标签 → 读数 → 轨道）
_ROW_SPACING = 12
#: 身份色点半径与其圆心 x（在行左内边距内）
_DOT_RADIUS, _DOT_CENTER_X = 4.0, 16.0
#: 悬停圆角
_HOVER_RADIUS = 10.0
#: 撞墙闪光动画时长（ms）
_FLASH_DURATION_MS = 420
#: 死区斜纹步进（px）
_HATCH_STEP = 6.0
#: 合计达到上限该比例即进入警示色
_WARN_RATIO = 0.90
#: 剩余徽标固定高（px）
_PILL_HEIGHT = 26
#: rebalance 收敛轮数上限（夹取→再分配，实测数轮内收敛）
_REBALANCE_ROUNDS = 8

#: 固定文案（蓝本 BudgetStrings 的通用化默认值）
_STR_SUB = "{count} 项 · 合计上限 {cap}"
_STR_REMAINING = "剩余 {value}"
_STR_TIP_CURRENT = "当前 {value} / 上限 {maximum}"
_STR_TIP_MORE = "还能再加 {room}{suffix}"
_STR_TIP_MAX = "已达该项自身上限"
_STR_TIP_EMPTY = "合计已达上限，无法再增加"


# ---------------------------------------------------------------------------
# 行声明
# ---------------------------------------------------------------------------

@dataclass
class BudgetSpec:
    """一行的声明式描述。

    参数:
        label: 行标签。
        minimum / maximum: 该行自身量程。
        value: 初始值。
        suffix: 数值后缀（如 ``"%"``）。
        decimals: 小数位数（内部计数按 ``10**decimals`` 缩放保持精确）。
        step / page_step: 键盘步进 / 翻页步进。
        color: 行身份色（``None`` 由组按五色轮自动分配，跟随主题）。
        tooltip: 追加在行 tooltip 末尾的说明文本。
    """

    label: str
    minimum: float = 0
    maximum: float = 100
    value: float = 0
    suffix: str = ""
    decimals: int = 0
    step: float = 1
    page_step: float = 10
    color: Optional[str] = None
    tooltip: str = ""

    def __post_init__(self) -> None:
        if self.maximum < self.minimum:
            raise ValueError(
                f"BudgetSpec: maximum({self.maximum}) 不能小于 "
                f"minimum({self.minimum})")
        if int(self.decimals) < 0:
            raise ValueError(f"BudgetSpec: decimals({self.decimals}) 不能为负")
        if self.step <= 0:
            raise ValueError(f"BudgetSpec: step({self.step}) 必须为正")
        if self.page_step <= 0:
            raise ValueError(
                f"BudgetSpec: page_step({self.page_step}) 必须为正")


# ---------------------------------------------------------------------------
# 令牌实时视图与绘制辅助
# ---------------------------------------------------------------------------

class _Theme:
    """绘制令牌实时视图：颜色 / 字号属性访问即 ``T()`` 读取。

    不缓存任何令牌值，主题 / 令牌切换后绘制自动取新值（仅需重烤
    富文本与 QSS 等烘焙处）。度量保留为常量（不强行映射 space.*）。
    """

    track_h = _TRACK_H
    handle_d = _HANDLE_D
    row_gap = _ROW_GAP
    value_w = _VALUE_W
    card_pad = _CARD_PAD
    bar_h = _BAR_H
    font_family = ""

    def __init__(self, label_w: int = _LABEL_W) -> None:
        self.label_w = int(label_w)

    # --- 表面 ---
    @property
    def canvas(self) -> str:
        return T("color.bg.base")

    @property
    def surface(self) -> str:
        return T("color.bg.subtle")

    @property
    def surface_alt(self) -> str:
        return T("color.bg.muted")

    @property
    def surface_hover(self) -> str:
        return T("color.bg.muted")

    @property
    def border(self) -> str:
        return T("color.border")

    # --- 文字 ---
    @property
    def text(self) -> str:
        return T("color.text.primary")

    @property
    def text_dim(self) -> str:
        return T("color.text.secondary")

    @property
    def text_faint(self) -> str:
        return T("color.text.tertiary")

    # --- 语义 ---
    @property
    def accent(self) -> str:
        return T("color.primary")

    @property
    def available(self) -> str:
        return T("color.success")

    @property
    def locked(self) -> str:
        return T("color.bg.muted")

    @property
    def locked_hatch(self) -> str:
        return T("color.text.disabled")

    @property
    def wall(self) -> str:
        return T("color.text.secondary")

    @property
    def warn(self) -> str:
        return T("color.warning")

    @property
    def danger(self) -> str:
        return T("color.danger")

    # --- 手柄 ---
    @property
    def handle(self) -> str:
        return T("color.bg.elevated")

    @property
    def handle_edge(self) -> str:
        return T("color.border.strong")

    @property
    def handle_shadow(self) -> str:
        return T("color.text.primary")

    @property
    def handle_locked(self) -> str:
        return T("color.text.disabled")

    @property
    def handle_locked_dark(self) -> str:
        return T("color.text.tertiary")

    # --- 行身份色（左色点 + 堆叠条分段），五色轮 ---
    @property
    def row_colors(self) -> tuple:
        return (T("color.text.secondary"), T("color.primary"),
                T("color.success"), T("color.warning"),
                T("color.border.strong"))

    def row_color(self, index: int) -> str:
        """按行序取身份色（超出色数取模循环，永不下标越界）。"""
        colors = self.row_colors
        return colors[index % len(colors)]

    # --- 字号 ---
    @property
    def fs_display(self) -> int:
        return int(T("font.display"))

    @property
    def fs_value(self) -> int:
        return int(T("font.title.sm"))

    @property
    def fs_label(self) -> int:
        return int(T("font.md"))

    @property
    def fs_caption(self) -> int:
        return int(T("font.xs"))


def _connect_theme_signals(widget, slot) -> None:
    """连接主题 / 令牌切换信号；组件销毁时断开（shiboken 守卫双保险）。"""
    manager = ThemeManager.instance()
    state = TokenState.instance()

    def _receiver(*_args):
        if _shiboken_is_valid(widget):
            slot()

    manager.theme_changed.connect(_receiver)
    state.token_changed.connect(_receiver)

    def _cleanup(_obj=None):
        for sig in (manager.theme_changed, state.token_changed):
            try:
                sig.disconnect(_receiver)
            except (RuntimeError, TypeError):
                pass

    widget.destroyed.connect(_cleanup)


def _font(theme: _Theme, size: int,
          weight=QFont.Weight.DemiBold) -> QFont:
    """按令牌字号生成字体；尽量开启 tabular figures 让拖拽时数字不跳动。"""
    font = QFont(theme.font_family) if theme.font_family else QFont()
    font.setPixelSize(size)
    font.setWeight(weight)
    try:
        font.setFeature(QFont.Tag("tnum"), 1)
    except (AttributeError, TypeError):
        pass
    return font


def _elide(text: str, metrics: QFontMetricsF, width: float) -> str:
    """超宽省略（右省略号）。"""
    return metrics.elidedText(text, Qt.TextElideMode.ElideRight, width)


# ---------------------------------------------------------------------------
# 单滑块（私有）
# ---------------------------------------------------------------------------

class _BudgetSlider(QAbstractSlider):
    """画满量程轨道 + 预算色块的滑块。

    用 ``QAbstractSlider`` 而非 ``QSlider``：内部计数按 ``10**decimals``
    缩放，小数量程保持精确，取值语义无歧义。键盘 / 滚轮 / 无障碍角色
    全部保留。

    信号:
        valueSettled(float): 经组夹取后的值落定。
        limitReached(float): 拖拽被预算墙拦下。
        budgetChangedForRow(): 组剩余预算变化（重画色块 / 更新 tooltip）。
    """

    valueSettled = Signal(float)
    limitReached = Signal(float)
    budgetChangedForRow = Signal()

    def __init__(self, spec: BudgetSpec, theme: _Theme,
                 parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setOrientation(Qt.Orientation.Horizontal)
        self._theme = theme
        self._decimals = int(spec.decimals)
        self._scale = 10 ** self._decimals
        self._suffix = spec.suffix
        self._label_color = (QColor(spec.color) if spec.color
                             else QColor(theme.accent))

        self.setRange(int(round(spec.minimum * self._scale)),
                      int(round(spec.maximum * self._scale)))
        self.setSingleStep(max(1, int(round(spec.step * self._scale))))
        self.setPageStep(max(1, int(round(spec.page_step * self._scale))))
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMinimumHeight(theme.handle_d + 8)
        self.setSizePolicy(QSizePolicy.Policy.Expanding,
                           QSizePolicy.Policy.Fixed)

        self._remaining_units = self.maximum()      # 初始：预算充裕
        self._settled = self.minimum()
        self._pulse = 0.0
        self._internal = False
        self._dragging = False

        self._anim = QPropertyAnimation(self, b"pulseLevel", self)
        self._anim.setDuration(_FLASH_DURATION_MS)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.valueChanged.connect(self._on_raw_value)

        self.setValue(int(round(spec.value * self._scale)))
        self._settled = self.value()

    # ---------------- 公开 ----------------

    def set_row_color(self, color: str) -> None:
        """换行身份色。"""
        self._label_color = QColor(color)
        self.update()

    @property
    def decimals(self) -> int:
        """小数位数（内部计数缩放指数）。"""
        return self._decimals

    @property
    def real_value(self) -> float:
        """当前值（还原缩放）。"""
        return self.value() / self._scale

    def real_minimum(self) -> float:
        """量程下界（还原缩放）。"""
        return self.minimum() / self._scale

    def real_maximum(self) -> float:
        """量程上界（还原缩放）。"""
        return self.maximum() / self._scale

    def real_remaining(self) -> float:
        """组剩余预算（还原缩放）。"""
        return self._remaining_units / self._scale

    def text_for(self, units: int) -> str:
        """内部计数 → 带后缀的显示文本。"""
        value = units / self._scale
        text = (f"{int(round(value))}" if self._decimals == 0
                else f"{value:.{self._decimals}f}")
        return text + self._suffix

    def set_real_value(self, value: float) -> None:
        """按真实值写入（内部换算缩放计数）。"""
        self.setValue(int(round(value * self._scale)))

    def set_budget(self, remaining_units: int) -> None:
        """把组剩余预算推进本轨道；组抽走预算时被动夹取并上报。"""
        if remaining_units == self._remaining_units:
            return
        self._remaining_units = max(0, remaining_units)
        if self._reclamp():
            # 组把地板抽走了：告知组，合计才能保持诚实
            self.valueSettled.emit(self.real_value)
        self.budgetChangedForRow.emit()
        self.update()

    def get_pulse_level(self) -> float:
        """撞墙闪光强度（QPropertyAnimation 目标属性读）。"""
        return self._pulse

    def set_pulse_level(self, value: float) -> None:
        """撞墙闪光强度（QPropertyAnimation 目标属性写）。"""
        self._pulse = value
        self.update()

    pulseLevel = Property(float, fget=get_pulse_level, fset=set_pulse_level)

    # ---------------- 预算数学 ----------------

    def _limit_from(self, base: int) -> int:
        """从 base 出发最远可达的计数。"""
        return min(self.maximum(), base + self._remaining_units)

    def wall_units(self) -> int:
        """预算块右缘 == 手柄最远可拖位置。"""
        return self._limit_from(self.value())

    def _reclamp(self) -> bool:
        """按落定值重夹；越界则收回墙内并返回 True。"""
        # 以 _settled 而非指针跳变值为基准——否则一次拖拽会冲过界，
        # 再从别的行身上偷回预算
        limit = self._limit_from(self._settled)
        if self.value() > limit:
            self._internal = True
            self.setValue(limit)
            self._internal = False
            self._settled = limit
            return True
        self._settled = self.value()
        return False

    def _on_raw_value(self, _value: int) -> None:
        """原始值变化：越墙则夹回并报 limitReached，否则落定。"""
        if self._internal:
            return
        limit = self._limit_from(self._settled)
        if self.value() > limit:
            self._internal = True
            self.setValue(limit)
            self._internal = False
            self.limitReached.emit(limit / self._scale)
        self._settled = self.value()
        self.valueSettled.emit(self.real_value)

    def flash(self) -> None:
        """撞墙提示：色块闪一下白光。"""
        self._anim.stop()
        self._anim.setStartValue(1.0)
        self._anim.setEndValue(0.0)
        self._anim.start()

    # ---------------- 几何 ----------------

    def _track_rect(self) -> QRectF:
        """轨道矩形（两端为手柄各留半个手柄的内缩）。"""
        width = self.width()
        height = self._theme.track_h
        inset = self._theme.handle_d / 2 + 1
        return QRectF(inset, (self.height() - height) / 2.0,
                      max(1.0, width - inset * 2), height)

    def _pos(self, units: int) -> float:
        """计数 → 轨道内 x 坐标。"""
        rect = self._track_rect()
        if self.maximum() == self.minimum():
            return rect.left()
        ratio = ((units - self.minimum())
                 / float(self.maximum() - self.minimum()))
        return rect.left() + ratio * rect.width()

    def _value_at(self, px: float) -> int:
        """x 坐标 → 计数（``_pos`` 的逆映射）。

        QAbstractSlider 默认按 style 的 groove 做命中映射，而本组件轨道
        两端为手柄内缩，故接管鼠标事件自行映射，保证点击与绘制严格一致。
        """
        rect = self._track_rect()
        if rect.width() <= 0:
            return self.minimum()
        ratio = (px - rect.left()) / rect.width()
        ratio = 0.0 if ratio < 0.0 else (1.0 if ratio > 1.0 else ratio)
        span = self.maximum() - self.minimum()
        return self.minimum() + int(round(ratio * span))

    # ---------------- 鼠标：按本组件轨道映射，而非 style groove ----------------

    def mousePressEvent(self, event) -> None:  # noqa: N802
        """左键按下：开始拖拽并把值设到点击处。"""
        if event.button() == Qt.MouseButton.LeftButton:
            self._dragging = True
            self.setValue(self._value_at(event.position().x()))
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        """拖拽移动：跟随指针设值（夹取在 _on_raw_value）。"""
        if self._dragging:
            self.setValue(self._value_at(event.position().x()))
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        """左键抬起：结束拖拽。"""
        if self._dragging and event.button() == Qt.MouseButton.LeftButton:
            self._dragging = False
            self.setValue(self._value_at(event.position().x()))
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802
        """双击：跳值（与单击一致）。"""
        self.setValue(self._value_at(event.position().x()))
        event.accept()

    def keyPressEvent(self, event) -> None:  # noqa: N802
        """键盘步进前后各报一次落定（组预算即时重算）。"""
        self.valueSettled.emit(self.real_value)
        super().keyPressEvent(event)
        self.valueSettled.emit(self.real_value)

    def wheelEvent(self, event) -> None:  # noqa: N802
        """滚轮步进后报一次落定。"""
        super().wheelEvent(event)
        self.valueSettled.emit(self.real_value)

    # ---------------- 绘制 ----------------

    def paintEvent(self, _event) -> None:  # noqa: N802
        """七层绘制：轨道底/死区斜纹/预算块/已占实心/撞墙闪光/上限墙/手柄。"""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        if not self.isEnabled():
            painter.setOpacity(0.5)

        theme = self._theme
        track = self._track_rect()
        radius = track.height() / 2.0

        p_min = self._pos(self.minimum())
        p_val = self._pos(self.value())
        p_max = self._pos(self.maximum())
        p_wall = self._pos(self.wall_units())

        self._paint_track(painter, track, radius)
        self._paint_dead_zone(painter, track, radius, p_wall, p_max)
        self._paint_budget_block(painter, track, radius, p_val, p_wall)
        self._paint_allocation(painter, track, radius, p_min, p_val)
        self._paint_pulse(painter, track, radius, p_val, p_wall)
        self._paint_wall(painter, track, p_wall, p_max)
        self._paint_handle(painter, p_val, track.center().y(),
                           radius, p_wall < p_max - 1.0)
        painter.end()

    def _paint_track(self, painter: QPainter, track: QRectF,
                     radius: float) -> None:
        """1. 轨道底：永远 100% 量程。"""
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(self._theme.locked))
        painter.drawRoundedRect(track, radius, radius)

    def _paint_dead_zone(self, painter: QPainter, track: QRectF,
                         radius: float, p_wall: float, p_max: float) -> None:
        """2. 死区：共享预算已支付不起的尾段，画 45° 斜纹。"""
        if p_wall >= p_max - 0.5:
            return
        dead = QRectF(p_wall, track.top(), p_max - p_wall, track.height())
        painter.save()
        painter.setClipPath(self._groove_path(track, radius))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        hatch = QPen(QColor(self._theme.locked_hatch), 1.4)
        hatch.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(hatch)
        x = dead.left() - track.height()
        while x < dead.right() + track.height():
            painter.drawLine(QPointF(x, dead.bottom()),
                             QPointF(x + track.height(), dead.top()))
            x += _HATCH_STEP
        painter.restore()

    def _paint_budget_block(self, painter: QPainter, track: QRectF,
                            radius: float, p_val: float, p_wall: float) -> None:
        """3. 反向色块 = 组剩余预算（实时收缩）。"""
        if p_wall <= p_val + 0.5:
            return
        avail = QRectF(p_val, track.top(), p_wall - p_val, track.height())
        gradient = QLinearGradient(avail.topLeft(), avail.topRight())
        color = QColor(self._theme.available)
        gradient.setColorAt(0.0, color)
        gradient.setColorAt(1.0, color.darker(112))
        painter.setBrush(gradient)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(avail, radius, radius)

    def _paint_allocation(self, painter: QPainter, track: QRectF,
                          radius: float, p_min: float, p_val: float) -> None:
        """4. 本滑块已占用量（实心主色）。"""
        if p_val <= p_min + 0.5:
            return
        fill = QRectF(p_min, track.top(), p_val - p_min, track.height())
        painter.setBrush(QColor(self._theme.accent))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(fill, radius, radius)

    def _paint_pulse(self, painter: QPainter, track: QRectF, radius: float,
                     p_val: float, p_wall: float) -> None:
        """5. 撞墙闪光：色块上扫一道白光（动画驱动）。"""
        if self._pulse <= 0.01 or p_wall <= p_val:
            return
        area = QRectF(p_val, track.top(), p_wall - p_val, track.height())
        glow = QColor(255, 255, 255, int(150 * self._pulse))
        painter.save()
        painter.setClipPath(self._groove_path(area.adjusted(0, -2, 0, 2),
                                              radius))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(glow)
        painter.drawRect(area.adjusted(0, -2, 0, 2))
        painter.restore()

    def _paint_wall(self, painter: QPainter, track: QRectF,
                    p_wall: float, p_max: float) -> None:
        """6. 上限墙：色块右缘一道竖线 = 本行真实可达最右点。"""
        if p_wall >= p_max - 1.0:
            return
        pen = QPen(QColor(self._theme.wall), 2.0)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        painter.drawLine(QPointF(p_wall, track.top() - 3),
                         QPointF(p_wall, track.bottom() + 3))

    def _groove_path(self, rect: QRectF, radius: float) -> QPainterPath:
        """圆角槽路径（斜纹 / 闪光裁剪用）。"""
        path = QPainterPath()
        path.addRoundedRect(rect, radius, radius)
        return path

    def _paint_handle(self, painter: QPainter, x: float, y: float,
                      radius: float, constrained: bool) -> None:
        """7. 手柄：预算耗尽变灰；撞墙时随闪光脉冲放大；焦点环保留。"""
        theme = self._theme
        handle_r = theme.handle_d / 2.0
        locked = self._remaining_units <= 0
        pulse = 1.0 + 0.22 * self._pulse

        shadow = QColor(theme.handle_shadow)
        shadow.setAlpha(70)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(shadow)
        painter.drawEllipse(QPointF(x, y + 1.6),
                            handle_r * pulse, handle_r * pulse)

        fill = QColor(theme.handle_locked if locked else theme.handle)
        edge = QColor(theme.handle_locked_dark if locked else theme.handle_edge)
        painter.setBrush(fill)
        painter.setPen(QPen(edge, 1.4))
        painter.drawEllipse(QPointF(x, y), handle_r * pulse, handle_r * pulse)

        if self.hasFocus():
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(QColor(theme.accent), 2.0))
            painter.drawEllipse(QPointF(x, y),
                                handle_r * pulse + 3.2, handle_r * pulse + 3.2)


# ---------------------------------------------------------------------------
# 行与堆叠分配条（私有）
# ---------------------------------------------------------------------------

class _BudgetRow(QWidget):
    """色点 + 标签 + 数值读数 + 轨道，一行。

    信号:
        valueChanged(float): 值经组夹取后落定。
        limitReached(): 拖拽被预算墙拦下（宿主可震动 / 提示音）。
    """

    valueChanged = Signal(float)
    limitReached = Signal()

    def __init__(self, spec: BudgetSpec, theme: _Theme, index: int = 0,
                 parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._theme = theme
        self._spec = spec
        self._suffix = spec.suffix
        self._row_color = QColor(spec.color or theme.row_color(index))
        #: 自动身份色标记：主题切换时强制按新令牌重取（即使颜色值没变）
        self._auto_color = False
        self._hover = False

        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self.setMouseTracking(True)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(_ROW_MARGIN_L, _ROW_MARGIN_V,
                                  _ROW_MARGIN_R, _ROW_MARGIN_V)
        layout.setSpacing(_ROW_SPACING)

        # --- 标签（固定列宽，每条轨道起点对齐同一 x；颜色走全局 QSS） ---
        self.label = QLabel(spec.label)
        self.label.setFont(_font(theme, theme.fs_label, QFont.Weight.Medium))
        self.label.setFixedWidth(theme.label_w)
        self.label.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self._label_text = spec.label
        layout.addWidget(self.label, 0)

        # --- 数值读数（单富文本标签：不会被布局挤压，右对齐保持轨道齐头） ---
        self.value_label = QLabel()
        self.value_label.setFont(
            _font(theme, theme.fs_value, QFont.Weight.Bold))
        self.value_label.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(self.value_label, 0)

        # --- 轨道 ---
        self.slider = _BudgetSlider(spec, theme, self)
        layout.addWidget(self.slider, 1)

        self.slider.valueSettled.connect(self._on_settled)
        self.slider.limitReached.connect(self._on_limit)
        self.slider.budgetChangedForRow.connect(self._update_tooltip)

        self._restyle()
        self._update_tooltip()

    # ---------------- 公开（组内部使用） ----------------

    def set_label(self, text: str) -> None:
        """重设行标签（同步省略逻辑的基准文案）。"""
        self._label_text = text
        self.label.setText(text)

    def set_row_color(self, color: str) -> None:
        """换身份色（色点 + 堆叠条分段取这里）。"""
        self._row_color = QColor(color)
        self.update()

    @property
    def row_color_hex(self) -> str:
        """当前身份色（#RRGGBB）。"""
        return self._row_color.name()

    @property
    def value(self) -> float:
        """该行当前值。"""
        return self.slider.real_value

    def setValue(self, value: float) -> None:  # noqa: N802
        """写入该行值（组夹取在 _BudgetSlider 内部完成）。"""
        self.slider.set_real_value(value)

    @property
    def spec(self) -> BudgetSpec:
        """该行声明式描述。"""
        return self._spec

    def _refresh_style(self) -> None:
        """主题 / 令牌变化：重设字体、重烤富文本读数与 tooltip。"""
        theme = self._theme
        self.label.setFont(_font(theme, theme.fs_label, QFont.Weight.Medium))
        self._restyle()
        self._update_tooltip()
        self.update()

    # ---------------- 内部 ----------------

    def _num_text(self, value: float) -> str:
        """数值 → 显示文本（按小数位）。"""
        decimals = self.slider.decimals
        return (f"{int(round(value))}" if decimals == 0
                else f"{value:.{decimals}f}")

    def _restyle(self) -> None:
        """读数重画 + 读数列宽按最宽串重算（防抖动）。"""
        theme = self._theme
        self.slider.update()
        self._paint_value()
        # 列宽按本行可能出现的最宽字符串：值被钳在 maximum 内，maximum 即最长
        value_font = _font(theme, theme.fs_value, QFont.Weight.Bold)
        caption_font = _font(theme, theme.fs_caption, QFont.Weight.Normal)
        maximum = self._num_text(self.slider.real_maximum())
        need = (QFontMetricsF(value_font).horizontalAdvance(maximum)
                + 4
                + QFontMetricsF(caption_font).horizontalAdvance(
                    f"/ {maximum}{self._suffix}")
                + 2)
        want = max(theme.value_w, int(need))
        if self.value_label.width() != want:
            self.value_label.setFixedWidth(want)

    def _paint_value(self) -> None:
        """读数：当前值主色加粗 + 上限弱化。"""
        theme = self._theme
        value = self._num_text(self.slider.real_value)
        maximum = self._num_text(self.slider.real_maximum())
        self.value_label.setText(
            f'<span style="color:{theme.text}; font-weight:700;">{value}</span>'
            f'<span style="color:{theme.text_faint};">'
            f"  / {maximum}{self._suffix}</span>")

    def _on_settled(self, value: float) -> None:
        """值落定：重画读数与 tooltip，转发宿主。"""
        self._paint_value()
        self._update_tooltip()
        self.valueChanged.emit(value)

    def _update_tooltip(self) -> None:
        """tooltip 实时显示「还能再加 N」/ 触顶原因。"""
        slider = self.slider
        room = (slider.wall_units() - slider.value()) / slider._scale
        room_text = self._num_text(room)
        if room <= 1e-9:
            tail = (_STR_TIP_MAX
                    if slider.real_value >= slider.real_maximum()
                    else _STR_TIP_EMPTY)
        else:
            tail = _STR_TIP_MORE.format(room=room_text, suffix=self._suffix)
        text = (f"{self._label_text}\n"
                + _STR_TIP_CURRENT.format(
                    value=slider.text_for(slider.value()),
                    maximum=slider.text_for(slider.maximum()))
                + f"\n{tail}")
        if self._spec.tooltip:
            text += f"\n{self._spec.tooltip}"
        for widget in (self, slider):
            widget.setToolTip(text)

    def _on_limit(self, _limit: float) -> None:
        """撞墙：轨道闪光并通知宿主。"""
        self.slider.flash()
        self.limitReached.emit()

    # ---------------- 绘制 ----------------

    def enterEvent(self, event) -> None:  # noqa: N802
        """悬停进入：画行底色。"""
        self._hover = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802
        """悬停离开：清除行底色。"""
        self._hover = False
        self.update()
        super().leaveEvent(event)

    def paintEvent(self, _event) -> None:  # noqa: N802
        """悬停底色 + 身份色点 + 标签超宽省略。"""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        if not self.isEnabled():
            painter.setOpacity(0.5)
        theme = self._theme
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)

        if self._hover:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(theme.surface_hover))
            painter.drawRoundedRect(rect, _HOVER_RADIUS, _HOVER_RADIUS)
            painter.setBrush(QColor(theme.surface_alt))
            painter.drawRoundedRect(rect.adjusted(0, 0, -3, 0),
                                    _HOVER_RADIUS, _HOVER_RADIUS)

        # 身份色点：位于行左内边距预留区
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(self._row_color))
        painter.drawEllipse(QPointF(_DOT_CENTER_X, self.height() / 2.0),
                            _DOT_RADIUS, _DOT_RADIUS)

        # 标签超宽省略（基准是 _label_text，不是 label.text()）
        metrics = QFontMetricsF(self.label.font())
        if metrics.horizontalAdvance(self._label_text) > self.label.width():
            self.label.setText(
                _elide(self._label_text, metrics, self.label.width()))
        elif self.label.text() != self._label_text:
            self.label.setText(self._label_text)
        painter.end()

    def sizeHint(self) -> QSize:  # noqa: N802
        """自然尺寸（高 = 手柄直径 + 上下余量）。"""
        return QSize(600, self._theme.handle_d + 20)


class _StackedBudgetBar(QWidget):
    """合计堆叠条：每行一段身份色 + 剩余空尾（斜纹）。"""

    def __init__(self, theme: _Theme,
                 parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._theme = theme
        self._segments: List[tuple] = []   # (颜色, 占比)
        self._tail = 1.0
        self.setFixedHeight(theme.bar_h)
        self.setSizePolicy(QSizePolicy.Policy.Expanding,
                           QSizePolicy.Policy.Fixed)

    def set_data(self, segments: Sequence[tuple], tail: float) -> None:
        """重设分段与空尾占比（0~1）。"""
        self._segments = list(segments)
        self._tail = max(0.0, min(1.0, tail))
        self.update()

    def paintEvent(self, _event) -> None:  # noqa: N802
        """底槽 → 空尾斜纹 → 各行分段（段间 2px 缝）。"""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        if not self.isEnabled():
            painter.setOpacity(0.5)
        theme = self._theme
        rect = QRectF(self.rect())
        radius = rect.height() / 2.0

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(theme.locked))
        painter.drawRoundedRect(rect, radius, radius)

        self._paint_tail(painter, rect, radius)
        self._paint_segments(painter, rect, radius)
        painter.end()

    def _paint_tail(self, painter: QPainter, rect: QRectF,
                    radius: float) -> None:
        """剩余空尾：斜纹表达「仍可用」。"""
        if self._tail <= 0.001:
            return
        tail_w = rect.width() * self._tail
        tail = QRectF(rect.right() - tail_w, rect.top(),
                      tail_w, rect.height())
        painter.save()
        painter.setClipPath(self._path(tail.adjusted(0, 0, radius, 0)))
        painter.setPen(QPen(QColor(self._theme.locked_hatch), 1.6))
        step = 8.0
        x = tail.left() - rect.height()
        while x < tail.right() + rect.height():
            painter.drawLine(QPointF(x, tail.bottom()),
                             QPointF(x + rect.height(), tail.top()))
            x += step
        painter.restore()

    def _paint_segments(self, painter: QPainter, rect: QRectF,
                        radius: float) -> None:
        """各行已占分段（占比基准是组 cap，不是各行 max，分段之和 ≤ 1）。"""
        x = rect.left()
        gap = 2.0
        count = len(self._segments)
        for index, (color, fraction) in enumerate(self._segments):
            width = rect.width() * fraction
            if width <= 0.5:
                x += width
                continue
            drawn = max(1.0, width - (0 if index == count - 1 else gap))
            segment = QRectF(x, rect.top(), drawn, rect.height())
            painter.setBrush(QColor(color))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRoundedRect(segment, radius, radius)
            x += width

    def _path(self, rect: QRectF) -> QPainterPath:
        """圆角路径（空尾斜纹裁剪用）。"""
        path = QPainterPath()
        path.addRoundedRect(rect, rect.height() / 2.0, rect.height() / 2.0)
        return path


# ---------------------------------------------------------------------------
# 头卡（私有）
# ---------------------------------------------------------------------------

class _Pill(QWidget):
    """剩余预算小徽标（圆角胶囊：淡色底 + 彩色文字）。"""

    def __init__(self, theme: _Theme,
                 parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._theme = theme
        self._color = QColor(theme.available)
        self._text = ""
        self.setFixedHeight(_PILL_HEIGHT)
        self.setFont(_font(theme, theme.fs_label))
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)

    def set_state(self, text: str, color: str) -> None:
        """重设文案与状态色。"""
        self._text = text
        self._color = QColor(color)
        self.updateGeometry()
        self.update()

    def _refresh_font(self) -> None:
        """主题 / 令牌变化：字号重取。"""
        self.setFont(_font(self._theme, self._theme.fs_label))
        self.update()

    def sizeHint(self) -> QSize:  # noqa: N802
        """按文字宽 + 左右余量。"""
        metrics = QFontMetrics(self.font())
        return QSize(metrics.horizontalAdvance(self._text) + 26, _PILL_HEIGHT)

    def paintEvent(self, _event) -> None:  # noqa: N802
        """胶囊底（状态色 38 alpha）+ 状态色文字。"""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        if not self.isEnabled():
            painter.setOpacity(0.5)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        color = QColor(self._color)
        background = QColor(color)
        background.setAlpha(38)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(background)
        painter.drawRoundedRect(rect, rect.height() / 2.0,
                                rect.height() / 2.0)
        painter.setPen(QPen(color))
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, self._text)
        painter.end()


class _BudgetSummary(QFrame):
    """头卡：合计上限、已用、剩余徽标与堆叠条。"""

    def __init__(self, theme: _Theme,
                 parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._theme = theme
        self.setObjectName("budgetSummary")
        self.setSizePolicy(QSizePolicy.Policy.Expanding,
                           QSizePolicy.Policy.Fixed)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(theme.card_pad, theme.card_pad - 4,
                                 theme.card_pad, theme.card_pad - 6)
        outer.setSpacing(14)
        outer.addLayout(self._build_top(theme))

        self.bar = _StackedBudgetBar(theme)
        outer.addWidget(self.bar)

        self._refresh_style()

    def _build_top(self, theme: _Theme) -> QHBoxLayout:
        """顶部行：左侧小计、中间剩余徽标、右侧合计大数。"""
        top = QHBoxLayout()
        top.setSpacing(12)

        self.sub_label = QLabel("")
        self.sub_label.setFont(_font(theme, theme.fs_caption))
        self.sub_label.setProperty("role", "secondary")
        top.addWidget(self.sub_label)
        top.addStretch(1)

        self.pill = _Pill(theme)
        top.addWidget(self.pill, 0, Qt.AlignmentFlag.AlignVCenter)

        right = QHBoxLayout()
        right.setSpacing(3)
        self.total_label = QLabel("0")
        self.total_label.setFont(
            _font(theme, theme.fs_display, QFont.Weight.Bold))
        self.cap_label = QLabel("/ 0")
        self.cap_label.setFont(_font(theme, theme.fs_label))
        self.cap_label.setProperty("role", "secondary")
        self.cap_label.setAlignment(
            Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignLeft)
        right.addWidget(self.total_label)
        right.addWidget(self.cap_label)
        right.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignBottom)
        top.addLayout(right)
        return top

    def _refresh_style(self) -> None:
        """主题 / 令牌变化：底色 QSS 与字号按新令牌重烤。"""
        theme = self._theme
        self.setStyleSheet(
            f"#budgetSummary{{background:{theme.surface_alt};"
            f"border:none;border-radius:{T('radius.lg')}px;}}")
        self.sub_label.setFont(_font(theme, theme.fs_caption))
        self.total_label.setFont(
            _font(theme, theme.fs_display, QFont.Weight.Bold))
        self.cap_label.setFont(_font(theme, theme.fs_label))
        self.pill._refresh_font()
        self.bar.update()

    def update_state(self, total: float, cap: float, remaining: float,
                     rows: Sequence[_BudgetRow], decimals: int = 0) -> None:
        """按最新预算状态刷新头卡（大数 / 徽标 / 小计 / 堆叠条）。"""
        theme = self._theme
        ratio = (total / cap) if cap > 0 else 1.0
        if remaining <= 1e-9:
            state_color = theme.danger
        elif ratio >= _WARN_RATIO:
            state_color = theme.warn
        else:
            state_color = theme.available
        # 大数是"用量"：保持中性，直到值得注意（绿色留给"剩余"语义）
        number_color = (theme.danger if remaining <= 1e-9 else
                        (theme.warn if ratio >= _WARN_RATIO else theme.text))

        format_number = self._formatter(decimals)
        self.total_label.setText(format_number(total))
        self.total_label.setStyleSheet(
            f"color:{number_color};background:transparent;")
        self.cap_label.setText(f"/ {format_number(cap)}")
        self.pill.set_state(
            _STR_REMAINING.format(value=format_number(remaining)),
            state_color)
        self.sub_label.setText(_STR_SUB.format(
            count=len(rows), cap=format_number(cap)))
        if cap > 0:
            segments = [(row.row_color_hex, max(0.0, row.value) / cap)
                        for row in rows]
            self.bar.set_data(segments, max(0.0, (cap - total) / cap))
        self.bar.update()

    @staticmethod
    def _formatter(decimals: int):
        """数值格式化（decimals=0 取整）。"""
        return (lambda v: f"{int(round(v))}") if decimals == 0 else (
            lambda v: f"{v:.{decimals}f}")


# ---------------------------------------------------------------------------
# 组容器（公开入口）
# ---------------------------------------------------------------------------

class BudgetSliderGroup(QFrame):
    """N 条滑块共享一个合计上限。

    参数:
        title: 组标题（空串则不显示标题行）。
        specs: ``BudgetSpec`` 序列；None / 空序列建空组（显示空占位）。
        cap: 合计上限；None 表示上限 = 各行 maximum 之和。
        framed: True 卡片边框（圆角 ``radius.lg``）；
            False 嵌套模式（透明无边框零边距）。
        parent: 父控件。

    信号:
        valueChanged(int index, float value): 用户改动某一行。
        valuesChanged(list[float]): 任一行值变化。
        budgetChanged(float total, float cap, float remaining): 预算重算后。
        limitReached(int index): 某行拖拽被上限墙拦下。
    """

    valueChanged = Signal(int, float)
    valuesChanged = Signal(list)
    budgetChanged = Signal(float, float, float)
    limitReached = Signal(int)

    def __init__(self, title: str = "预算分配",
                 specs: Optional[Sequence[BudgetSpec]] = None,
                 cap: Optional[float] = None, framed: bool = True,
                 parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._theme = _Theme()
        self._framed = bool(framed)
        self._rows: List[_BudgetRow] = []
        self._cap_override: Optional[float] = None
        self._busy = False
        self._dirty = False
        self._suspend = False
        self._placeholder: Optional[QLabel] = None

        layout = QVBoxLayout(self)
        if framed:
            layout.setContentsMargins(2, 2, 2, 8)
        else:
            layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._title_label: Optional[QLabel] = None
        if title:
            self._title_label = QLabel(title, self)
            self._title_label.setContentsMargins(14, 10, 14, 2)
            self._apply_title_font()
            layout.addWidget(self._title_label)

        self.summary = _BudgetSummary(self._theme, self)
        layout.addWidget(self.summary)

        self._rows_host = QWidget(self)
        self._rows_host.setObjectName("budgetRowsHost")
        self._rows_host.setStyleSheet(
            "#budgetRowsHost{background:transparent;border:none;}")
        self._rows_layout = QVBoxLayout(self._rows_host)
        margins = 14 if framed else 0
        self._rows_layout.setContentsMargins(margins, 16, margins, 0)
        self._rows_layout.setSpacing(self._theme.row_gap)
        layout.addWidget(self._rows_host)

        self._apply_frame_style()
        _connect_theme_signals(self, self._on_theme_changed)

        if specs:
            self.set_specs(specs)
        if cap is not None:
            self.set_cap(cap)
        self._update_placeholder()
        self._recompute()

    # ---------------- 构建 ----------------

    def set_specs(self, specs: Sequence[BudgetSpec]) -> None:
        """一次性重建全部行。"""
        for spec in specs:
            if not isinstance(spec, BudgetSpec):
                raise ValueError(
                    f"set_specs: 元素必须是 BudgetSpec，收到 {type(spec).__name__}")
        self.clear()
        for spec in specs:
            self.add_slider(spec)

    def add_slider(self, spec: BudgetSpec) -> _BudgetRow:
        """追加一行（未显式给色时按五色轮自动分配身份色）。"""
        if not isinstance(spec, BudgetSpec):
            raise ValueError(
                f"add_slider: 参数必须是 BudgetSpec，收到 {type(spec).__name__}")
        index = len(self._rows)
        auto_color = spec.color is None
        color = spec.color or self._theme.row_color(index)
        spec.color = color
        row = _BudgetRow(spec, self._theme, index, self._rows_host)
        row._auto_color = auto_color
        row.set_row_color(color)
        row.valueChanged.connect(
            lambda value, i=index: self._on_row_value(i, value))
        row.limitReached.connect(lambda i=index: self._on_row_limit(i))
        self._rows_layout.addWidget(row)
        self._rows.append(row)
        self._cap_override = None
        self._update_placeholder()
        self._recompute()
        return row

    def clear(self) -> None:
        """清空所有行（空组显示空占位）。"""
        while self._rows_layout.count():
            item = self._rows_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.setParent(None)
                widget.deleteLater()
        self._rows.clear()
        self._placeholder = None
        self._cap_override = None
        self._update_placeholder()
        self._recompute()

    # ---------------- 状态 ----------------

    @property
    def rows(self) -> List[_BudgetRow]:
        """行列表（只读引用）。"""
        return self._rows

    def row(self, index: int) -> _BudgetRow:
        """按序号取行。"""
        return self._rows[index]

    @property
    def auto_cap(self) -> float:
        """各行 maximum 之和（与生效 cap 分离，便于对比）。"""
        return sum(row.slider.real_maximum() for row in self._rows)

    @property
    def cap(self) -> float:
        """当前生效的合计上限。"""
        if self._cap_override is not None:
            return self._cap_override
        return self.auto_cap

    @property
    def total(self) -> float:
        """当前合计。"""
        return sum(row.value for row in self._rows)

    @property
    def remaining(self) -> float:
        """剩余预算（不为负）。"""
        return max(0.0, self.cap - self.total)

    def set_cap(self, cap: Optional[float]) -> None:
        """收紧（或 None 回到 Σmax）合计上限。"""
        if cap is not None and float(cap) < 0:
            raise ValueError(f"set_cap: 合计上限不能为负，收到 {cap}")
        self._cap_override = None if cap is None else float(cap)
        self._recompute()

    def values(self) -> List[float]:
        """各行当前值。"""
        return [row.value for row in self._rows]

    def set_values(self, values: Sequence[float]) -> None:
        """一次性写入各行值（顺序无关：先临时抬高预算墙再写入）。

        紧预算（cap < Σmax）下若直接逐行写入，单行夹取会按**旧剩余量**
        把先写的行钳住——同样一组值换个写入顺序结果就不同（载入草稿时
        表现为参数被莫名压低）。故先把各行剩余量临时抬到充裕再写入，
        真正的夹取与再分配统一由收尾的 ``_recompute`` 完成。
        """
        if len(values) != len(self._rows):
            raise ValueError(
                f"set_values: 期望 {len(self._rows)} 个值，收到 {len(values)} 个")
        self._suspend = True
        try:
            for row in self._rows:
                row.slider._remaining_units = row.slider.maximum()
            for row, value in zip(self._rows, values):
                row.setValue(float(value))
        finally:
            self._suspend = False
        self._recompute()

    def set_value(self, index: int, value: float) -> None:
        """单行写入。"""
        self._rows[index].setValue(float(value))
        self._recompute()

    def set_label_width(self, width: int) -> None:
        """重设行首标签列宽（px）。"""
        width = int(width)
        if width <= 0:
            raise ValueError(f"set_label_width: 列宽必须为正，收到 {width}")
        self._theme.label_w = width
        for row in self._rows:
            row.label.setFixedWidth(width)
        self.update()

    # ---------------- 主题 ----------------

    def _on_theme_changed(self) -> None:
        """主题 / 令牌变化：重烤烘焙处，自动身份色强制按新令牌重取。"""
        theme = self._theme
        for index, row in enumerate(self._rows):
            if row._auto_color:
                row.set_row_color(theme.row_color(index))
            row._refresh_style()
        self.summary._refresh_style()
        self._apply_frame_style()
        self._apply_title_font()
        if self._placeholder is not None:
            self._placeholder.setFont(
                _font(theme, theme.fs_value, QFont.Weight.Medium))
        self._recompute()
        self.update()

    def _apply_title_font(self) -> None:
        """标题字体按令牌重设（颜色走全局 QSS）。"""
        if self._title_label is not None:
            self._title_label.setFont(
                _font(self._theme, self._theme.fs_value, QFont.Weight.DemiBold))

    def _apply_frame_style(self) -> None:
        """按 framed 模式应用 / 清除卡片边框（id 限定，避免误伤子控件）。"""
        self.setObjectName("budgetGroup")
        if self._framed:
            self.setStyleSheet(
                f"#budgetGroup{{background:{self._theme.surface};"
                f"border:1px solid {self._theme.border};"
                f"border-radius:{T('radius.lg')}px;}}")
        else:
            self.setStyleSheet(
                "#budgetGroup{background:transparent;border:none;}")

    def _update_placeholder(self) -> None:
        """空组 ↔ 有行之间切换空占位。"""
        if self._rows:
            if self._placeholder is not None:
                self._rows_layout.removeWidget(self._placeholder)
                # deleteLater 在 processEvents 下不保证执行（Qt6 需
                # DeferredDeletion 标志），先 hide 保证截图 / 测试路径不可见
                self._placeholder.hide()
                self._placeholder.deleteLater()
                self._placeholder = None
        elif self._placeholder is None:
            placeholder = QLabel("暂无滑块项", self._rows_host)
            placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
            placeholder.setProperty("role", "tertiary")
            placeholder.setFont(
                _font(self._theme, self._theme.fs_value, QFont.Weight.Medium))
            placeholder.setMinimumHeight(48)
            self._rows_layout.addWidget(placeholder)
            self._placeholder = placeholder

    # ---------------- 内部 ----------------

    def _on_row_value(self, index: int, value: float) -> None:
        """行值落定：重算预算；非簿记期间转发三组信号。"""
        was_busy = self._busy
        self._recompute()
        if was_busy:
            return          # 内部簿记，非用户编辑
        self.valueChanged.emit(index, value)
        self.valuesChanged.emit(self.values())
        self.budgetChanged.emit(self.total, self.cap, self.remaining)

    def _on_row_limit(self, index: int) -> None:
        """行撞墙：非簿记期间转发。"""
        if not self._busy:
            self.limitReached.emit(index)

    def _rebalance_once(self) -> None:
        """合计超 cap 时按比例削回（幂等）。"""
        cap = self.cap
        over = self.total - cap
        if over <= 1e-9:
            return
        # 各行可削空间（到下界为止）
        pool = [(row, max(0.0, row.value - row.slider.real_minimum()))
                for row in self._rows]
        total_pool = sum(space for _row, space in pool)
        if total_pool <= 0:
            return
        for row, space in pool:
            if space <= 0:
                continue
            take = over * (space / total_pool)
            if take > 0:
                row.setValue(max(row.slider.real_minimum(), row.value - take))
                self._dirty = True
        # 第二遍兜底浮点残差
        residue = self.total - cap
        if residue > 1e-9:
            for row, space in pool:
                if space <= 0 or row.value <= row.slider.real_minimum():
                    continue
                row.setValue(max(row.slider.real_minimum(),
                                 row.value - residue))
                self._dirty = True
                break

    def _recompute(self) -> None:
        """预算重算入口（挂起 / 重入保护，收敛轮数封顶）。"""
        if self._suspend:
            return              # 批量写入进行中；由调用方收尾重算
        if self._busy:
            self._dirty = True
            return
        self._busy = True
        for _round in range(_REBALANCE_ROUNDS):
            self._dirty = False
            self._rebalance_once()
            self._recompute_once()
            if not self._dirty:
                break
        self._busy = False

    def _recompute_once(self) -> None:
        """把剩余预算推进各行轨道并刷新头卡。"""
        cap = self.cap
        total = sum(row.value for row in self._rows)
        remaining = max(0.0, cap - total)
        for row in self._rows:
            units = int(round(remaining * row.slider._scale))
            row.slider.set_budget(units)
        decimals = self._rows[0].slider.decimals if self._rows else 0
        self.summary.update_state(total, cap, remaining, self._rows, decimals)
