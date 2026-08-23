# -*- coding: utf-8 -*-
"""图表引擎核心（CHART_SPEC §2 公开 API / §3 注册表与协议）。

对外契约（供 C2/C3/C4 与用户代码使用）：

- ``ChartWidget``：``set_option`` 全量设置 / ``update_option`` 合并更新并
  动画过渡 / resizeEvent 自动重排 / 主题感知重绘。
- 注册表：``SERIES_REGISTRY`` / ``COMPONENT_REGISTRY`` +
  ``register_series(type_name, cls)`` / ``register_component(name, cls)``。
  后注册覆盖先注册（同名键直接替换）。
- 协议基类：``SeriesRenderer``（系列）、``Coord``（坐标，见 axes.py）。
- ``ChartAnimation``：0→1 进度动画（QVariantAnimation，DURATION.slow，
  EASING.standard），渲染器经 ``anim_t`` 插值。
- 组件：``Title`` / ``Legend`` / ``Tooltip``。
- ``default_palette()``：默认调色板（T() 实时取，主题感知）。

C4 组件协议（components.py / interact.py）：
组件类需声明类属性 ``option_key``（如 ``"markLine"`` / ``"dataZoom"``），
构造签名 ``(chart, opt)``；ChartWidget 重建时扫描：
- 顶层 option 中与 ``option_key`` 同名的键 → 实例化一次，``opt`` 为该键值；
- 每个 series 字典中的同名键（markPoint/markLine/markArea）→ 每系列实例化，
  ``opt`` 为该键值，并额外设置 ``comp.series_opt`` 指向所属系列字典。
组件实现 SeriesRenderer 协议（layout/paint/hit_test），另可挂鼠标钩子
``on_mouse_press(pos)`` / ``on_mouse_move(pos)`` / ``on_mouse_release(pos)``，
返回 True 表示事件已消费。
"""

import copy

from PySide6.QtCore import (
    QObject,
    QPointF,
    QRectF,
    Qt,
    QVariantAnimation,
)
from PySide6.QtGui import QColor, QFontMetricsF, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QWidget

from ..theme import T, ThemeManager
from ..tokens import DURATION, EASING
from ._utils import warn_once
from .axes import (
    CalendarCoord,
    Coord,
    GridCoord,
    PolarCoord,
    SingleAxisCoord,
    chart_font,
    format_value,
    nice_ticks,
)

__all__ = [
    "SERIES_REGISTRY",
    "COMPONENT_REGISTRY",
    "register_series",
    "register_component",
    "default_palette",
    "nice_ticks",
    "format_value",
    "parse_data_point",
    "SeriesRenderer",
    "Coord",
    "ChartAnimation",
    "Title",
    "Legend",
    "Tooltip",
    "ChartWidget",
    "SimpleLineSeriesRenderer",
]

# ---------------------------------------------------------------------------
# 注册表（CHART_SPEC §3）
# ---------------------------------------------------------------------------

#: "bar" -> BarSeriesRenderer 等；同名后注册覆盖先注册
SERIES_REGISTRY: dict = {}

#: "markLine" -> MarkLineComponent 等（C4 注册）
COMPONENT_REGISTRY: dict = {}


def register_series(type_name: str, cls) -> None:
    """注册系列渲染器：``type_name``（如 "bar"）→ SeriesRenderer 子类。

    同名重复注册时后者覆盖前者（C2 完整版 line 即以此覆盖 core 自检版）。
    """
    if not type_name:
        raise ValueError("register_series: type_name 不能为空")
    SERIES_REGISTRY[str(type_name)] = cls


def register_component(name: str, cls) -> None:
    """注册图表组件：``name``（如 "markLine"）→ 组件类（C4 协议见模块docstring）。"""
    if not name:
        raise ValueError("register_component: name 不能为空")
    COMPONENT_REGISTRY[str(name)] = cls


#: 默认调色板令牌键（CHART_SPEC §2）。每项 (主键, 回退键)：
#: tokens 当前未定义 "color.warning.hover"（亮/暗均缺），缺失时回退主色，
#: 不回退会 KeyError；若后续 tokens 补齐该键，自动优先取用。
_PALETTE_KEYS = (
    ("color.primary", None),
    ("color.success", None),
    ("color.warning", None),
    ("color.danger", None),
    ("color.text.secondary", None),
    ("color.primary.hover", "color.primary"),
    ("color.success.hover", "color.success"),
    ("color.warning.hover", "color.warning"),
)


def default_palette() -> list:
    """默认调色板（T() 实时取，主题切换后下一次绘制自动生效）。

    令牌缺失时按 ``_PALETTE_KEYS`` 的回退键取色（容灾，不抛 KeyError）。
    """
    out = []
    for key, fallback in _PALETTE_KEYS:
        try:
            out.append(T(key))
        except KeyError:
            if fallback is None:
                raise
            out.append(T(fallback))
    return out


def parse_data_point(item, index: int = 0):
    """解析系列数据项 → ``(x, y)``。

    支持：``number``（x=index）、``[x, y]``、``{"value": ...}``；
    无法解析返回 ``(index, None)``。
    """
    if item is None:
        return index, None
    v = item.get("value") if isinstance(item, dict) else item
    if isinstance(v, (list, tuple)):
        if not v:
            return index, None
        x = v[0]
        y = v[1] if len(v) >= 2 else None
        if isinstance(y, (int, float)) and not isinstance(y, bool):
            return x, float(y)
        return x, None
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return index, float(v)
    return index, None


#: coordinateSystem 缺省（None / "cartesian2d" / "grid"）时落在 grid 直角
#: 坐标系的系列类型名单。无坐标系列（pie / radar / gauge / funnel /
#: sunburst / treemap / tree / sankey / graph / map / parallel /
#: themeRiver 等）不在其列：纯无坐标 option 不再兜底创建 GridCoord。
GRID_SERIES_TYPES = frozenset({
    "bar", "pictorialBar", "line", "scatter", "effectScatter",
    "candlestick", "boxplot", "heatmap", "lines",
})


def _needs_grid_coord(series_opts) -> bool:
    """是否存在 coordinateSystem 缺省且落在 grid 的系列（决定是否创建 GridCoord）。

    heatmap 等类型显式 ``coordinateSystem: "calendar"`` / ``"polar"`` /
    ``"singleAxis"`` 时不视为 grid 系列。
    """
    for s in series_opts or []:
        if not isinstance(s, dict):
            continue
        if s.get("coordinateSystem") not in (None, "cartesian2d", "grid"):
            continue
        if str(s.get("type") or "line") in GRID_SERIES_TYPES:
            return True
    return False


def _deep_merge(dst: dict, src: dict) -> dict:
    """递归合并 src 到 dst（dict 深合并，list / 标量整体替换），返回 dst。"""
    for k, v in (src or {}).items():
        if isinstance(v, dict) and isinstance(dst.get(k), dict):
            _deep_merge(dst[k], v)
        else:
            dst[k] = copy.deepcopy(v)
    return dst


# ---------------------------------------------------------------------------
# 系列渲染器协议
# ---------------------------------------------------------------------------

class SeriesRenderer:
    """系列渲染器协议基类（CHART_SPEC §3）。

    子类实现 ``layout(rect)`` / ``paint(p, anim_t)`` / ``hit_test(pos)``。
    坐标映射经 ``self.chart.coord_for(self.opt)`` 取得 Coord 后
    ``coord.map_point(x, y)``。

    可选扩展：
    - ``value_at_index(index)`` → dict（{"name","value","series","color"}），
      供 tooltip axis 触发取数；
    - ``self.prev_data``：update_option 前的旧 data 列表（core 自动注入），
      用于旧→新插值动画。
    """

    def __init__(self, chart: "ChartWidget", opt: dict):
        self.chart = chart
        self.opt = dict(opt or {})
        self.name = str(self.opt.get("name") or "")
        #: 系列显隐（legend 点击切换；默认显示）
        self.visible = bool(self.opt.get("selected", True))
        #: update_option 前的旧数据（core 注入，用于动画插值）
        self.prev_data = None

    # -- 协议 ------------------------------------------------------------
    def layout(self, rect: QRectF) -> None:
        """计算几何（坐标映射经 coord）。"""

    def paint(self, p: QPainter, anim_t: float) -> None:
        """绘制。anim_t ∈ [0,1]，入场 / 更新动画进度。"""
        raise NotImplementedError

    def hit_test(self, pos: QPointF):
        """命中检测 → {"name","value","series",...} 或 None。"""
        return None

    # -- 辅助 ------------------------------------------------------------
    def data(self) -> list:
        """系列原始 data 列表（None 容灾）。"""
        d = self.opt.get("data")
        return d if isinstance(d, list) else []

    def color(self) -> QColor:
        """系列主色（option color 覆盖 → 全局调色板）。"""
        return self.chart.color_for_series(self)

    def value_at_index(self, index: int):
        """tooltip axis 触发：返回 {"name","value","series","color"} 或 None。"""
        return None

    def _full_index(self, index):
        """tooltip 局部下标 → 全量数据下标（dataZoom category 窗口偏移换算）。

        ``coord.invert_x`` 返回窗口内下标；本方法经 ``AxisModel.window_offset``
        加回窗口起始偏移，使 ``value_at_index`` 按全量数据取数。
        """
        if not isinstance(index, int):
            return index
        coord = self.chart.coord_for(self.opt)
        axis = getattr(coord, "x_axis", None)
        if axis is not None and getattr(axis, "type", "") == "category":
            return index + axis.window_offset()
        return index


# ---------------------------------------------------------------------------
# 动画驱动
# ---------------------------------------------------------------------------

class ChartAnimation(QObject):
    """0→1 进度动画（QVariantAnimation，DURATION.slow，EASING.standard）。

    渲染器在 ``paint(p, anim_t)`` 中经 ``anim_t`` 插值。
    ``set_progress(v)`` 支持无事件循环环境（测试）手动推进。
    """

    def __init__(self, on_update=None, parent: QObject = None):
        super().__init__(parent)
        self._t = 0.0
        self._on_update = on_update
        self._anim = QVariantAnimation(self)
        self._anim.setStartValue(0.0)
        self._anim.setEndValue(1.0)
        self._anim.setDuration(int(DURATION["slow"]))
        self._anim.setEasingCurve(EASING["standard"])
        self._anim.valueChanged.connect(self._on_value)

    @property
    def t(self) -> float:
        """当前进度 ∈ [0,1]。"""
        return self._t

    def start(self) -> None:
        """从头播放（set_option / update_option 时调用）。"""
        self._anim.stop()
        self._anim.start()

    def stop(self) -> None:
        self._anim.stop()

    def is_running(self) -> bool:
        return self._anim.state() == QVariantAnimation.Running

    def set_progress(self, v: float) -> None:
        """手动设置进度并触发重绘回调（测试 / 无动画路径用）。"""
        self._apply(max(0.0, min(1.0, float(v))))

    def _on_value(self, v) -> None:
        self._apply(float(v))

    def _apply(self, v: float) -> None:
        self._t = v
        if callable(self._on_update):
            self._on_update()


# ---------------------------------------------------------------------------
# 标题组件
# ---------------------------------------------------------------------------

class Title:
    """标题组件：{"text": str, "subtext": str, "left": "left|center|right"}。"""

    def __init__(self, opt: dict = None):
        self.opt = dict(opt or {})

    def set_option(self, opt: dict) -> None:
        self.opt = dict(opt or {})

    @property
    def text(self) -> str:
        return str(self.opt.get("text") or "")

    @property
    def subtext(self) -> str:
        return str(self.opt.get("subtext") or "")

    def height(self) -> float:
        """标题区总高（无 text 时为 0）。"""
        if not self.text:
            return 0.0
        h = T("font.title.md") * 1.3 + 6
        if self.subtext:
            h += T("font.sm") * 1.5 + 2
        return h + 4

    def paint(self, p: QPainter, rect: QRectF) -> None:
        """在顶部条带内绘制（rect 为标题区）。"""
        if not self.text or rect.height() <= 0:
            return
        p.save()
        align = str(self.opt.get("left") or "left")
        title_font = chart_font(T("font.title.md"), T("font.weight.semibold"))
        sub_font = chart_font(T("font.sm"))
        fm_t = QFontMetricsF(title_font)
        fm_s = QFontMetricsF(sub_font)
        text_w = fm_t.horizontalAdvance(self.text)
        sub_w = fm_s.horizontalAdvance(self.subtext) if self.subtext else 0.0
        w = max(text_w, sub_w)
        if align == "center":
            x = rect.center().x() - w / 2
        elif align == "right":
            x = rect.right() - w - 8
        else:  # "left"（含数值 px 简化处理）
            try:
                x = rect.left() + float(align)
            except (TypeError, ValueError):
                x = rect.left() + 8
        y = rect.top() + 2
        p.setFont(title_font)
        p.setPen(QColor(T("color.text.primary")))
        p.drawText(QRectF(x, y, text_w + 4, fm_t.height()),
                   Qt.AlignLeft | Qt.AlignVCenter, self.text)
        if self.subtext:
            y += fm_t.height() + 2
            p.setFont(sub_font)
            p.setPen(QColor(T("color.text.secondary")))
            p.drawText(QRectF(x, y, sub_w + 4, fm_s.height()),
                       Qt.AlignLeft | Qt.AlignVCenter, self.subtext)
        p.restore()


# ---------------------------------------------------------------------------
# 图例组件
# ---------------------------------------------------------------------------

class Legend:
    """图例组件：横/纵排布、点击切换系列显隐、主题感知。

    option：{"show": True, "orient": "horizontal|vertical",
    "top|bottom|left|right": ...}。条目由 ChartWidget 按系列名注入
    （``set_items([(name, color), ...])``，color 仅为兜底值）——绘制时色块
    经 chart 实时取系列当前色，主题切换后无需重建即生效。
    """

    #: 条目点击回调：chart 注入 ``legend.on_toggle = chart.set_series_visible``
    on_toggle = None

    def __init__(self, chart: "ChartWidget", opt: dict = None):
        self.chart = chart
        self.opt = {"show": True, "orient": "horizontal"}
        self.set_option(opt)
        self._items = []       # [(name, QColor)]
        self._item_rects = []  # [QRectF] 与 _items 对齐
        self.rect = QRectF()

    def set_option(self, opt: dict) -> None:
        if isinstance(opt, dict):
            merged = {"show": True, "orient": "horizontal"}
            merged.update(opt)
            self.opt = merged
        else:
            self.opt = {"show": True, "orient": "horizontal"}

    def set_items(self, items: list) -> None:
        self._items = [(str(n), c) for n, c in (items or []) if str(n)]

    def _item_color(self, name: str):
        """条目实时色：按系列名从 chart 当前渲染器取色（主题感知），
        找不到渲染器时返回 None（调用方退回 set_items 的兜底色）。"""
        for r in self.chart.series_renderers:
            if r.name == name:
                return r.color()
        return None

    @property
    def shown(self) -> bool:
        return bool(self.opt.get("show", True)) and bool(self._items)

    @property
    def orient(self) -> str:
        return "vertical" if str(self.opt.get("orient")) == "vertical" \
            else "horizontal"

    # -- 布局 -------------------------------------------------------------
    def _entry(self, name: str):
        """单条目的 (宽, 高) 与字体。"""
        font = chart_font(T("font.xs"))
        fm = QFontMetricsF(font)
        h = max(18.0, fm.height() + 6)
        w = 14 + 6 + fm.horizontalAdvance(name) + 14  # 色块+间距+文字+条距
        return w, h

    def preferred_size(self, avail_w: float, avail_h: float):
        """按可用空间返回 (w, h)：横向为整行高度，纵向为列宽。"""
        if not self.shown:
            return 0.0, 0.0
        if self.orient == "horizontal":
            h = max((self._entry(n)[1] for n, _ in self._items), default=0.0)
            return avail_w, h + 4
        w = max((self._entry(n)[0] for n, _ in self._items), default=0.0)
        return w, avail_h

    def layout(self, rect: QRectF) -> None:
        """在已分配条带 rect 内排布条目（横向居中 / 纵向顶对齐）。"""
        self.rect = QRectF(rect)
        self._item_rects = []
        if not self.shown or rect.isNull():
            return
        font = chart_font(T("font.xs"))
        fm = QFontMetricsF(font)
        entry_h = max(18.0, fm.height() + 6)
        if self.orient == "horizontal":
            total = sum(self._entry(n)[0] for n, _ in self._items) - 14
            x = rect.left() + max(0.0, (rect.width() - total) / 2)
            y = rect.top() + (rect.height() - entry_h) / 2
            for name, _ in self._items:
                w, _ = self._entry(name)
                self._item_rects.append(QRectF(x, y, w - 14, entry_h))
                x += w
        else:
            x = rect.left() + 4
            y = rect.top() + 4
            for name, _ in self._items:
                w, _ = self._entry(name)
                self._item_rects.append(QRectF(x, y, w - 14, entry_h))
                y += entry_h + 2

    # -- 交互 -------------------------------------------------------------
    def hit_test(self, pos: QPointF):
        """命中条目名或 None。"""
        for (name, _), r in zip(self._items, self._item_rects):
            if r.contains(pos):
                return name
        return None

    def toggle(self, name: str) -> None:
        if callable(self.on_toggle):
            self.on_toggle(name, not self.chart.is_series_visible(name))

    # -- 绘制 -------------------------------------------------------------
    def paint(self, p: QPainter) -> None:
        if not self.shown or not self._item_rects:
            return
        p.save()
        font = chart_font(T("font.xs"))
        p.setFont(font)
        fm = QFontMetricsF(font)
        for (name, fallback), r in zip(self._items, self._item_rects):
            enabled = self.chart.is_series_visible(name)
            live = self._item_color(name) if enabled else None
            swatch = QColor(live) if live is not None else QColor(fallback)
            if not enabled:
                swatch = QColor(T("color.text.disabled"))
            text_c = QColor(T("color.text.primary")) if enabled \
                else QColor(T("color.text.disabled"))
            # 色块（圆角小方块）
            p.setPen(Qt.NoPen)
            p.setBrush(swatch)
            box = QRectF(r.left(), r.center().y() - 4.5, 9, 9)
            p.drawRoundedRect(box, 2, 2)
            p.setPen(text_c)
            p.drawText(QRectF(box.right() + 5, r.top(),
                              r.width() - 14, r.height()),
                       Qt.AlignLeft | Qt.AlignVCenter, name)
        p.restore()


# ---------------------------------------------------------------------------
# 提示框组件
# ---------------------------------------------------------------------------

class Tooltip:
    """提示框组件：{"show": True, "trigger": "item|axis"}。

    - trigger=item：命中单个数据点（系列 hit_test）；
    - trigger=axis：经 ``coord.invert_x`` + 系列 ``value_at_index`` 聚合，
      十字线经 ``coord.paint_tooltip_marker`` 绘制；
    - 浮层框自绘：圆角 + 近似阴影（多层低透明度扩散圆角矩形），跟随鼠标。
    """

    def __init__(self, chart: "ChartWidget", opt: dict = None):
        self.chart = chart
        self.opt = {"show": True, "trigger": "item"}
        self.set_option(opt)
        self._active = False
        self._pos = QPointF()        # 鼠标位置（跟随）
        self._marker_pos = None      # 十字线锚点（None 用 _pos）
        self._lines = []             # [(QColor, name, value_str)]

    def set_option(self, opt: dict) -> None:
        if isinstance(opt, dict):
            merged = {"show": True, "trigger": "item"}
            merged.update(opt)
            self.opt = merged
        else:
            self.opt = {"show": True, "trigger": "item"}

    @property
    def shown(self) -> bool:
        return bool(self.opt.get("show", True))

    @property
    def trigger(self) -> str:
        return "axis" if str(self.opt.get("trigger")) == "axis" else "item"

    @property
    def active(self) -> bool:
        return self._active and bool(self._lines)

    # -- 状态 -------------------------------------------------------------
    def show_at(self, pos: QPointF, lines: list, marker_pos: QPointF = None) -> None:
        """显示浮层。lines: [(color, name, value_str), ...]。"""
        self._active = True
        self._pos = QPointF(pos)
        self._marker_pos = QPointF(marker_pos) if marker_pos is not None else None
        self._lines = list(lines or [])

    def hide(self) -> None:
        self._active = False
        self._lines = []

    # -- 绘制 -------------------------------------------------------------
    def paint(self, p: QPainter) -> None:
        if not self.shown or not self.active:
            return
        # 十字线 / 指示线
        marker = self._marker_pos if self._marker_pos is not None else self._pos
        coord = self.chart.primary_coord()
        if coord is not None:
            coord.paint_tooltip_marker(p, marker)

        p.save()
        font = chart_font(T("font.xs"))
        p.setFont(font)
        fm = QFontMetricsF(font)
        pad_x, pad_y, line_gap, dot = 10.0, 8.0, 3.0, 8.0
        line_h = fm.height()
        rows = []
        for color, name, value in self._lines:
            label = f"{name}: {value}" if name else str(value)
            rows.append((color, label))
        text_w = max((fm.horizontalAdvance(t) for _, t in rows), default=0.0)
        w = pad_x * 2 + (dot + 5 if any(c is not None for c, _ in rows) else 0) + text_w
        h = pad_y * 2 + len(rows) * line_h + max(0, len(rows) - 1) * line_gap
        # 跟随鼠标：右侧偏移，越界翻转 / 收敛
        area = QRectF(0, 0, self.chart.width(), self.chart.height())
        x = self._pos.x() + 14
        y = self._pos.y() + 14
        if x + w > area.right() - 4:
            x = self._pos.x() - w - 14
        if y + h > area.bottom() - 4:
            y = self._pos.y() - h - 14
        x = min(max(x, 4.0), max(4.0, area.right() - w - 4))
        y = min(max(y, 4.0), max(4.0, area.bottom() - h - 4))
        box = QRectF(x, y, w, h)
        radius = float(T("radius.md"))
        # 近似阴影：三层外扩低透明度圆角矩形
        shadow_c = QColor(T("color.text.primary"))
        for i, alpha in ((6, 16), (4, 22), (2, 30)):
            sc = QColor(shadow_c)
            sc.setAlpha(alpha)
            p.setPen(Qt.NoPen)
            p.setBrush(sc)
            p.drawRoundedRect(box.translated(0, 2).adjusted(-i / 2, -i / 2, i / 2, i / 2),
                              radius + i / 2, radius + i / 2)
        # 浮层本体
        p.setBrush(QColor(T("color.bg.elevated")))
        p.setPen(QPen(QColor(T("color.border")), 1))
        p.drawRoundedRect(box, radius, radius)
        # 文本行（缩进仅对带圆点的行生效；标题行 color 为 None 不缩进）
        ty = box.top() + pad_y
        for color, label in rows:
            tx = box.left() + pad_x
            if color is not None:
                p.setPen(Qt.NoPen)
                p.setBrush(QColor(color))
                p.drawEllipse(QRectF(tx, ty + line_h / 2 - dot / 2, dot, dot))
                tx += dot + 5
            p.setPen(QColor(T("color.text.primary")))
            p.drawText(QRectF(tx, ty, box.right() - pad_x - tx, line_h),
                       Qt.AlignLeft | Qt.AlignVCenter, label)
            ty += line_h + line_gap
        p.restore()


# ---------------------------------------------------------------------------
# 图表主控件
# ---------------------------------------------------------------------------

class ChartWidget(QWidget):
    """类 ECharts 图表控件（CHART_SPEC §2）。

    用法::

        chart = ChartWidget(parent)
        chart.set_option({"title": {"text": "销量"},
                          "xAxis": {"type": "category", "data": ["一", "二"]},
                          "series": [{"type": "line", "name": "A", "data": [3, 5]}]})
        chart.update_option({"series": [{"data": [4, 6]}]})  # 合并 + 动画过渡

    resizeEvent 自动重排；构造时连接
    ``ThemeManager.instance().theme_changed`` → 重取 T() 配色并 update()。

    性能：``_layout_all`` 带布局缓存 + 脏标记（见 ``invalidate_layout``），
    悬停 / 无动画重绘不再全量重排；动画进行中按历史行为每帧重算。
    """

    def __init__(self, parent: QWidget = None):
        super().__init__(parent)
        self.setMouseTracking(True)
        self.setMinimumSize(200, 150)
        self._option = {}
        self._series = []        # [SeriesRenderer]
        self._coords = []        # [Coord]
        self._components = []    # [C4 组件实例]
        self._series_state = {}  # name -> bool（legend 显隐状态）
        self._opt_version = 0    # option 版本号（set_option/update_option 递增）
        self._layout_key = None  # 布局缓存键（脏标记，见 invalidate_layout）
        self.title = Title()
        self.legend = Legend(self)
        self.tooltip = Tooltip(self)
        self.legend.on_toggle = self.set_series_visible
        self.anim = ChartAnimation(self.update, self)
        # 主题连接：接收者为本控件（PySide 以接收者销毁自动断连）；另在
        # destroyed 时显式 disconnect（保守双保险，防单例信号强引用滞留）
        self._theme_slot = self._on_theme_changed
        ThemeManager.instance().theme_changed.connect(self._theme_slot)
        self.destroyed.connect(self._disconnect_theme)

    def _disconnect_theme(self, *_args) -> None:
        """销毁路径显式断开主题单例信号连接（保守处理，见 §七.21）。"""
        try:
            ThemeManager.instance().theme_changed.disconnect(self._theme_slot)
        except (RuntimeError, TypeError):
            pass

    # ------------------------------------------------------------------ API
    def set_option(self, option: dict) -> None:
        """全量设置 option（dict，schema 见 CHART_SPEC §4）并播放入场动画。"""
        self._option = copy.deepcopy(option) if isinstance(option, dict) else {}
        self._opt_version += 1
        self._rebuild()
        self.anim.start()
        self.update()

    def update_option(self, option: dict) -> None:
        """合并更新 option 并播放旧→新数据插值动画。

        合并语义：dict 深合并；**list 值（如 ``series``）整体替换**而非
        按项合并（ECharts 的按 id/name 合并为简化语义，未实现）。旧系列
        数据按 **name** 匹配注入新渲染器的 ``prev_data`` 供 anim_t 插值，
        名字匹配不到（系列被删除 / 改名）时不插值（从入场路径变形）。
        """
        if not isinstance(option, dict):
            return
        prev_by_name = {r.name: list(r.data()) for r in self._series}
        _deep_merge(self._option, option)
        self._opt_version += 1
        self._rebuild()
        # 旧数据按 name 注入新渲染器（增删 / 重排后不再序号错位）
        for r in self._series:
            r.prev_data = prev_by_name.get(r.name)
        self.anim.start()
        self.update()

    def option(self) -> dict:
        """当前 option（拷贝，公共 API 契约）。

        内部每帧热路径请用 ``_option_ref()``（无拷贝），避免逐帧 deepcopy。
        """
        return copy.deepcopy(self._option)

    def _option_ref(self) -> dict:
        """当前 option 的内部引用（无拷贝；仅 charts 包内部热路径使用）。"""
        return self._option

    @property
    def series_renderers(self) -> list:
        """系列渲染器列表（含隐藏系列，``r.visible`` 标记）。"""
        return list(self._series)

    @property
    def coords(self) -> list:
        """坐标系列表。"""
        return list(self._coords)

    @property
    def components(self) -> list:
        """C4 组件实例列表。"""
        return list(self._components)

    def palette(self) -> list:
        """当前生效调色板：option["color"] 覆盖，否则默认调色板（T() 实时取）。"""
        custom = self._option.get("color")
        if isinstance(custom, list) and custom:
            return [str(c) for c in custom]
        return default_palette()

    def color_for_series(self, series) -> QColor:
        """系列主色：series opt 的 "color" → 全局调色板按序号取色。"""
        if isinstance(series, SeriesRenderer):
            idx = self._series.index(series) if series in self._series else 0
            own = series.opt.get("color")
        else:
            idx = int(series)
            own = None
        if isinstance(own, str) and own:
            return QColor(own)
        pal = self.palette()
        return QColor(pal[idx % len(pal)])

    def primary_coord(self):
        """主坐标系（coords[0]，无则 None）。"""
        return self._coords[0] if self._coords else None

    def coord_for(self, series_opt: dict = None):
        """按 series 的 coordinateSystem 匹配坐标系（默认首个）。"""
        want = None
        if isinstance(series_opt, dict):
            want = series_opt.get("coordinateSystem")
        alias = {"cartesian2d": "grid", "grid": "grid", "polar": "polar",
                 "singleAxis": "singleAxis", "calendar": "calendar", None: None}
        want = alias.get(want, want)
        if want:
            for c in self._coords:
                if c.kind == want:
                    return c
        return self.primary_coord()

    def set_series_visible(self, name, visible: bool = None) -> None:
        """按名称设置系列显隐（legend 点击；visible 缺省为取反）。

        显隐影响堆叠基线等布局结果 → 失效布局缓存；并通知定时器驱动型
        渲染器（lines trailEffect / effectScatter）恢复或暂停动画。
        """
        name = str(name)
        if visible is None:
            visible = not self._series_state.get(name, True)
        self._series_state[name] = bool(visible)
        for r in self._series:
            if r.name == name:
                r.visible = bool(visible)
                hook = getattr(r, "_on_visible_changed", None)
                if callable(hook):
                    try:
                        hook()
                    except Exception:
                        pass
        self._layout_key = None
        self.update()

    def is_series_visible(self, name) -> bool:
        return bool(self._series_state.get(str(name), True))

    def add_component(self, comp) -> None:
        """挂接外部组件实例（C4 interact 可手动追加）。"""
        self._components.append(comp)
        self.update()

    # ------------------------------------------------------------- 内部构建
    def _rebuild(self) -> None:
        """按当前 option 重建组件 / 坐标系 / 系列渲染器（并使布局缓存失效）。"""
        opt = self._option
        self._layout_key = None
        self.title.set_option(opt.get("title") or {})
        self.legend.set_option(opt.get("legend") or {})
        self.tooltip.set_option(opt.get("tooltip") or {})
        series_opts = [s for s in (opt.get("series") or []) if isinstance(s, dict)]

        # 坐标系：calendar > polar > singleAxis > grid。grid 仅在
        # ①option 显式给出 xAxis/yAxis/grid，或 ②存在 coordinateSystem
        # 缺省且落在 grid 的直角系列（bar/line/scatter/... 见
        # GRID_SERIES_TYPES）时创建；纯无坐标 option（pie/radar/gauge/
        # sankey/...）不创建任何 Coord，不再兜底绘制轴线网格。
        # 单个坐标构造失败降级跳过并记录（坐标构造自身已对非法输入容灾）。
        self._coords = []
        if "calendar" in opt:
            c = self._make_coord(CalendarCoord, "calendar")
            if c is not None:
                self._coords.append(c)
        if "polar" in opt or "radiusAxis" in opt or "angleAxis" in opt:
            c = self._make_coord(PolarCoord, "polar")
            if c is not None:
                self._coords.append(c)
        if "singleAxis" in opt:
            c = self._make_coord(SingleAxisCoord, "singleAxis")
            if c is not None:
                self._coords.append(c)
        need_grid = ("xAxis" in opt or "yAxis" in opt or "grid" in opt
                     or _needs_grid_coord(series_opts))
        if need_grid:
            grid = self._make_coord(GridCoord, "grid")
            if grid is not None:
                self._coords.insert(0, grid)
        for c in self._coords:
            c.set_series(series_opts)

        # 系列渲染器
        self._series = []
        for i, s in enumerate(series_opts):
            type_name = str(s.get("type") or "line")
            cls = SERIES_REGISTRY.get(type_name)
            if cls is None:
                continue  # 未注册类型（C2/C3 尚未提供）安全跳过
            try:
                r = cls(self, s)
            except Exception as exc:
                # 单个系列构造失败不拖垮整图，但至少可见一次
                warn_once(f"series-ctor:{type_name}",
                          f"系列构造失败（type={type_name}）: {exc!r}")
                continue
            # 注入 option 内序号：bar 槽位等按序号定位自身，不依赖字典相等
            r._series_index = i
            if not r.name:
                r.name = f"series{i}"
                r.opt.setdefault("name", r.name)
            r.visible = self.is_series_visible(r.name)
            self._series.append(r)

        # 组件（C4 协议：类属性 option_key + 构造 (chart, opt)）
        self._components = []
        for key, cls in list(COMPONENT_REGISTRY.items()):
            option_key = getattr(cls, "option_key", key)
            if isinstance(opt.get(option_key), (dict, list)):
                self._spawn_component(cls, opt[option_key], None)
            for s in series_opts:
                if isinstance(s.get(option_key), (dict, list)):
                    self._spawn_component(cls, s[option_key], s)

        # 图例条目
        items = []
        for i, r in enumerate(self._series):
            items.append((r.name, self.color_for_series(r)))
        self.legend.set_items(items)
        self._layout_all(force=True)

    def _make_coord(self, cls, kind: str):
        """构造单个坐标系：失败降级为 None 并记录一次（不拖垮整图）。"""
        try:
            return cls(self, self._option)
        except Exception as exc:
            warn_once(f"coord-ctor:{kind}",
                      f"坐标构造失败（{kind}）: {exc!r}")
            return None

    def _spawn_component(self, cls, comp_opt, series_opt) -> None:
        try:
            comp = cls(self, comp_opt)
        except Exception as exc:
            warn_once(f"component-ctor:{getattr(cls, '__name__', cls)!r}",
                      f"组件构造失败（{getattr(cls, 'option_key', '')}）: {exc!r}")
            return
        if series_opt is not None:
            comp.series_opt = series_opt
        self._components.append(comp)

    def _content_rect(self) -> QRectF:
        """扣除标题 / 图例后的坐标系可用区。"""
        rect = QRectF(0, 0, max(1, self.width()), max(1, self.height()))
        th = self.title.height()
        content = QRectF(rect.left(), rect.top() + th,
                         rect.width(), max(1.0, rect.height() - th))
        if self.legend.shown:
            lw, lh = self.legend.preferred_size(content.width(), content.height())
            lo = self.legend.opt
            if self.legend.orient == "horizontal":
                if "top" in lo:
                    band = QRectF(content.left(), content.top(), content.width(), lh)
                    content.setTop(content.top() + lh)
                else:  # 默认 bottom
                    band = QRectF(content.left(), content.bottom() - lh,
                                  content.width(), lh)
                    content.setBottom(content.bottom() - lh)
            else:
                if "left" in lo:
                    band = QRectF(content.left(), content.top(), lw, content.height())
                    content.setLeft(content.left() + lw)
                else:  # 默认 right
                    band = QRectF(content.right() - lw, content.top(),
                                  lw, content.height())
                    content.setRight(content.right() - lw)
            self.legend.layout(band)
        return content

    def invalidate_layout(self) -> None:
        """使布局缓存失效（下次绘制 / 布局时全量重排）。

        失效来源汇总（与缓存键同构）：set_option / update_option / _rebuild
        （option 版本）、resizeEvent（视口尺寸）、主题切换、dataZoom 窗口
        交互（滚轮 / 拖拽 / restore，见 interact.py）、系列显隐（堆叠基线）。
        动画进行中不缓存（每帧重算，与历史行为一致）。
        """
        self._layout_key = None

    def _layout_cache_key(self):
        """布局缓存键：option 版本 / 视口尺寸 / 主题 / dataZoom 窗口状态。

        键命中即可安全跳过布局——所有布局输入（option、坐标 rect、dataZoom
        窗口、图例条目标题几何）都被上述成员覆盖；缓存只跳过、绝不跳过
        *已经发生变更* 的重排（保守策略：宁可缓存不生效也不可缓存陈旧结果）。
        """
        try:
            theme = ThemeManager.instance().mode
        except Exception:
            theme = None
        dz = tuple((getattr(c, "start", 0.0), getattr(c, "end", 100.0))
                   for c in self._components
                   if getattr(c, "option_key", "") == "dataZoom")
        return (self._opt_version, self.width(), self.height(), theme, dz)

    def _layout_all(self, force: bool = False) -> None:
        """全量布局：坐标系 / 系列 / 组件几何。

        布局缓存：键命中直接返回（悬停 / 无动画重绘零成本）；动画进行中
        不缓存（每帧重算，ChartAnimation 视觉行为与历史一致）。
        """
        if force:
            self._layout_key = None
        elif not self.anim.is_running():
            key = self._layout_cache_key()
            if key == self._layout_key:
                return
            self._layout_key = key
        content = self._content_rect()
        for c in self._coords:
            c.layout(content)
        for r in self._series:
            try:
                r.layout(content)
            except Exception as exc:
                warn_once(f"series-layout:{r.__class__.__name__}",
                          f"系列布局异常（{r.name}）: {exc!r}")
        for comp in self._components:
            layout = getattr(comp, "layout", None)
            if callable(layout):
                try:
                    layout(content)
                except Exception as exc:
                    warn_once(f"component-layout:{comp.__class__.__name__}",
                              f"组件布局异常（{comp.__class__.__name__}）: {exc!r}")

    # ------------------------------------------------------------- Qt 事件
    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._layout_all()
        self.update()

    def _on_theme_changed(self, _mode) -> None:
        # 配色全部经 T() 实时取，重绘即生效；主题可能影响字体度量等布局
        # 输入，保守失效布局缓存（下一次绘制全量重排一次）
        self._layout_key = None
        self.update()

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(self.rect(), QColor(T("color.bg.base")))
        self._layout_all()
        t = self.anim.t
        for c in self._coords:
            c.paint_axes(p)
        for r in self._series:
            if not r.visible:
                continue
            try:
                r.paint(p, t)
            except Exception as exc:
                # 单系列绘制异常不影响整图，但至少可见一次
                warn_once(f"series-paint:{r.__class__.__name__}",
                          f"系列绘制异常（{r.name}）: {exc!r}")
        for comp in self._components:
            paint = getattr(comp, "paint", None)
            if callable(paint):
                try:
                    paint(p, t)
                except TypeError:
                    try:
                        paint(p)
                    except Exception as exc:
                        warn_once(f"component-paint:{comp.__class__.__name__}",
                                  f"组件绘制异常（{comp.__class__.__name__}）: {exc!r}")
                except Exception as exc:
                    warn_once(f"component-paint:{comp.__class__.__name__}",
                              f"组件绘制异常（{comp.__class__.__name__}）: {exc!r}")
        self.legend.paint(p)
        title_rect = QRectF(0, 0, self.width(), self.title.height())
        self.title.paint(p, title_rect)
        self.tooltip.paint(p)
        p.end()

    # -- 鼠标：legend 点击 / tooltip 跟随 / C4 组件钩子 --------------------
    def mousePressEvent(self, event) -> None:
        pos = event.position()
        for comp in self._components:
            hook = getattr(comp, "on_mouse_press", None)
            if callable(hook) and hook(pos):
                super().mousePressEvent(event)
                return
        if self.legend.shown:
            name = self.legend.hit_test(pos)
            if name is not None:
                self.legend.toggle(name)
                self.update()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        pos = event.position()
        consumed = False
        for comp in self._components:
            hook = getattr(comp, "on_mouse_move", None)
            if callable(hook) and hook(pos):
                consumed = True
        if not consumed:
            self._update_tooltip(pos)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        pos = event.position()
        for comp in self._components:
            hook = getattr(comp, "on_mouse_release", None)
            if callable(hook) and hook(pos):
                break
        super().mouseReleaseEvent(event)

    def leaveEvent(self, event) -> None:
        self.tooltip.hide()
        self.update()
        super().leaveEvent(event)

    # -- tooltip 聚合 ------------------------------------------------------
    def _update_tooltip(self, pos: QPointF) -> None:
        if not self.tooltip.shown or not self._series:
            if self.tooltip.active:
                self.tooltip.hide()
                self.update()
            return
        if self.tooltip.trigger == "axis":
            self._tooltip_axis(pos)
        else:
            self._tooltip_item(pos)
        self.update()

    def _tooltip_item(self, pos: QPointF) -> None:
        for r in reversed(self._series):
            if not r.visible:
                continue
            hit = None
            try:
                hit = r.hit_test(pos)
            except Exception:
                hit = None
            if hit:
                name = str(hit.get("series") or hit.get("name") or r.name)
                value = format_value(hit.get("value"))
                self.tooltip.show_at(pos, [(r.color(), name, value)])
                return
        self.tooltip.hide()

    def _tooltip_axis(self, pos: QPointF) -> None:
        coord = self.primary_coord()
        lines = []
        marker = None
        anchor = None
        if coord is not None:
            try:
                anchor = coord.invert_x(pos)
            except Exception:
                anchor = None
        if anchor is not None:
            idx = int(anchor) if isinstance(anchor, (int, float)) else anchor
            for r in self._series:
                if not r.visible:
                    continue
                info = None
                try:
                    info = r.value_at_index(idx)
                except Exception:
                    info = None
                if info:
                    lines.append((r.color(), str(info.get("series") or r.name),
                                  format_value(info.get("value"))))
                    if marker is None and info.get("pos") is not None:
                        marker = info["pos"]
        else:
            # 坐标系不支持反查：退化为 item 模式
            self._tooltip_item(pos)
            return
        if not lines:
            # 退化：尝试 item 命中
            self._tooltip_item(pos)
            return
        title = None
        if isinstance(coord, GridCoord) and coord.x_axis.type == "category":
            cats = coord.x_axis.categories
            if isinstance(idx, int) and 0 <= idx < len(cats):
                title = cats[idx]
        if title:
            lines.insert(0, (None, "", title))
        self.tooltip.show_at(pos, lines, marker_pos=marker or pos)


# ---------------------------------------------------------------------------
# 内置自检用简易 line 系列
# ---------------------------------------------------------------------------

class SimpleLineSeriesRenderer(SeriesRenderer):
    """内置自检用简易 line 渲染器（核心链路自测）。

    注意：本实现刻意保持简单（直线段 + 圆点，无 smooth/areaStyle/step）。
    C2 的 ``InstructionX_UIKit.charts.series_cartesian`` 会实现完整版 line，并在其模块
    导入时调用 ``register_series("line", ...)`` 覆盖本实现 —— 注册表同名
    后注册覆盖先注册，core 无需任何改动。
    """

    def __init__(self, chart, opt):
        super().__init__(chart, opt)
        self._points = []   # [QPointF]（当前数据）
        self._prev_points = []  # [QPointF]（旧数据，update_option 动画用）
        self._entries = []  # [(x, y)] 解析后的数据

    def layout(self, rect: QRectF) -> None:
        coord = self.chart.coord_for(self.opt)
        self._prev_points = list(self._points)
        self._points = []
        self._entries = []
        if coord is None:
            return
        single = getattr(coord, "kind", "") == "singleAxis"
        for i, item in enumerate(self.data()):
            x, y = parse_data_point(item, i)
            self._entries.append((x, y))
            if y is None:
                self._points.append(None)
                continue
            try:
                if single:
                    # 单轴：数值即轴上位置（y 为解析出的数值）
                    self._points.append(coord.map_point(y))
                else:
                    self._points.append(coord.map_point(x, y))
            except Exception:
                self._points.append(None)

    def _animated_points(self, anim_t: float):
        """旧→新插值：长度一致时逐点 lerp；否则返回当前点列。"""
        cur = self._points
        prev_src = self._prev_points
        # update_option 路径：prev_data 与当前 data 等长时按数据值重映射旧点
        if self.prev_data is not None and len(self.prev_data) == len(self._entries):
            coord = self.chart.coord_for(self.opt)
            prev = []
            for i, item in enumerate(self.prev_data):
                x, y = parse_data_point(item, i)
                if y is None or coord is None:
                    prev.append(None)
                    continue
                try:
                    prev.append(coord.map_point(x, y))
                except Exception:
                    prev.append(None)
            prev_src = prev
        if len(prev_src) != len(cur):
            return cur
        out = []
        for a, b in zip(prev_src, cur):
            if a is None or b is None:
                out.append(b)
            else:
                out.append(QPointF(a.x() + (b.x() - a.x()) * anim_t,
                                   a.y() + (b.y() - a.y()) * anim_t))
        return out

    def paint(self, p: QPainter, anim_t: float) -> None:
        pts = self._animated_points(anim_t)
        valid = [pt for pt in pts if pt is not None]
        if not valid:
            return
        p.save()
        color = self.color()
        pen = QPen(color, 2)
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        # 折线（跳过 None 断点）
        seg = []
        for pt in pts:
            if pt is None:
                if len(seg) >= 2:
                    p.drawPolyline(seg)
                seg = []
            else:
                seg.append(pt)
        if len(seg) >= 2:
            p.drawPolyline(seg)
        # 数据点
        p.setBrush(QColor(T("color.bg.elevated")))
        for pt in valid:
            p.drawEllipse(pt, 3.0, 3.0)
        p.restore()

    def hit_test(self, pos: QPointF):
        best = None
        best_d = 10.0  # 命中半径 px
        for i, pt in enumerate(self._points):
            if pt is None:
                continue
            d = ((pt.x() - pos.x()) ** 2 + (pt.y() - pos.y()) ** 2) ** 0.5
            if d <= best_d:
                best_d = d
                best = i
        if best is None:
            return None
        x, y = self._entries[best]
        return {"name": self.name, "value": y, "series": self.name,
                "dataIndex": best, "x": x}

    def value_at_index(self, index: int):
        idx = self._full_index(index)  # dataZoom 窗口偏移换算
        if not isinstance(idx, int) or not (0 <= idx < len(self._entries)):
            return None
        x, y = self._entries[idx]
        if y is None:
            return None
        pos = self._points[idx] if idx < len(self._points) else None
        return {"name": self.name, "value": y, "series": self.name, "pos": pos}


#: 内置自检注册（C2 完整版 line 导入时将覆盖，见 SimpleLineSeriesRenderer docstring）
register_series("line", SimpleLineSeriesRenderer)
