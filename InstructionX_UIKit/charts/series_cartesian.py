# -*- coding: utf-8 -*-
"""直角坐标系列（CHART_SPEC §5 C2，共 10 个）。

本模块导入时经 ``register_series`` 注册：bar / pictorialBar / line（完整版，
覆盖 core 自检版）/ scatter / effectScatter / candlestick / boxplot /
heatmap / parallel / themeRiver。

通用约定：
- 坐标映射经 ``self.chart.coord_for(self.opt)``；柱 / K线 / 箱线 / 热力为
  支持「yAxis 为 category」（水平条 / 双类别轴），直接用 AxisModel 双向映射，
  不走 ``GridCoord.map_point``（其 y 只按数值处理）。
- 数值轴范围：core 只按单点值统计，stack 柱 / K线高低 / 箱线极值会溢出，
  故这些渲染器在 ``layout`` 中用 ``_grid_value_extent`` 重设数值轴范围
  （幂等，多次布局结果一致）。
- 涨跌配色（candlestick）遵循 A 股习惯：红涨绿跌 —— 涨用
  ``color.danger``、跌用 ``color.success``，可用 option 的
  ``colorUp`` / ``colorDown`` 覆盖。
- 全部配色经 ``T()`` 实时取；空数据 / None 不崩溃。
"""

import math
import weakref

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import (
    QColor,
    QFontMetricsF,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
)

from ..theme import T
from .axes import CalendarCoord, GridCoord, chart_font, format_value
from .core import SeriesRenderer, parse_data_point, register_series

__all__ = [
    "BarSeriesRenderer",
    "PictorialBarSeriesRenderer",
    "LineSeriesRenderer",
    "ScatterSeriesRenderer",
    "EffectScatterSeriesRenderer",
    "CandlestickSeriesRenderer",
    "BoxplotSeriesRenderer",
    "HeatmapSeriesRenderer",
    "ParallelSeriesRenderer",
    "ThemeRiverSeriesRenderer",
]


# ---------------------------------------------------------------------------
# 小工具
# ---------------------------------------------------------------------------

def _to_float(v, default=None):
    """宽松转 float；失败返回 default。"""
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _lerp(a, b, t):
    return a + (b - a) * t


def _with_alpha(color, alpha):
    c = QColor(color)
    c.setAlpha(max(0, min(255, int(alpha))))
    return c


def _ramp_color(colors, t):
    """多色带插值：colors 为颜色列表，t∈[0,1] → QColor。"""
    cols = [QColor(c) for c in (colors or []) if c]
    if not cols:
        return QColor(T("color.primary"))
    if len(cols) == 1:
        return cols[0]
    t = max(0.0, min(1.0, float(t)))
    pos = t * (len(cols) - 1)
    i = min(int(pos), len(cols) - 2)
    f = pos - i
    a, b = cols[i], cols[i + 1]
    return QColor(
        int(_lerp(a.red(), b.red(), f)),
        int(_lerp(a.green(), b.green(), f)),
        int(_lerp(a.blue(), b.blue(), f)),
        int(_lerp(a.alpha(), b.alpha(), f)),
    )


def _smooth_path(points, smooth=0.5):
    """Catmull-Rom → 三次贝塞尔平滑路径。points: [QPointF]（≥2）。"""
    path = QPainterPath()
    n = len(points)
    if n == 0:
        return path
    path.moveTo(points[0])
    if n == 1:
        return path
    k = max(0.0, min(1.0, float(smooth)))
    for i in range(n - 1):
        p0 = points[max(i - 1, 0)]
        p1 = points[i]
        p2 = points[i + 1]
        p3 = points[min(i + 2, n - 1)]
        c1 = QPointF(p1.x() + (p2.x() - p0.x()) * k / 6.0,
                     p1.y() + (p2.y() - p0.y()) * k / 6.0)
        c2 = QPointF(p2.x() - (p3.x() - p1.x()) * k / 6.0,
                     p2.y() - (p3.y() - p1.y()) * k / 6.0)
        path.cubicTo(c1, c2, p2)
    return path


def _dist_to_segment(pos, a, b):
    """点 pos 到线段 a-b 的距离。"""
    ax, ay = a.x(), a.y()
    bx, by = b.x(), b.y()
    dx, dy = bx - ax, by - ay
    length_sq = dx * dx + dy * dy
    if length_sq == 0:
        return math.hypot(pos.x() - ax, pos.y() - ay)
    t = ((pos.x() - ax) * dx + (pos.y() - ay) * dy) / length_sq
    t = max(0.0, min(1.0, t))
    return math.hypot(pos.x() - (ax + t * dx), pos.y() - (ay + t * dy))


def _datum_list(item):
    """取数据项的数值列表：[...] 或 {"value": [...]} → list[float]|None。"""
    v = item.get("value") if isinstance(item, dict) else item
    if not isinstance(v, (list, tuple)):
        return None
    out = []
    for x in v:
        f = _to_float(x)
        if f is None:
            return None
        out.append(f)
    return out


def _grid_series_opts(chart):
    """当前 option 中落在 grid 坐标系的系列 option 列表。"""
    out = []
    for s in chart.option().get("series") or []:
        if not isinstance(s, dict):
            continue
        if s.get("coordinateSystem") in (None, "cartesian2d", "grid"):
            out.append(s)
    return out


def _grid_value_extent(chart):
    """grid 数值轴真实范围（类型感知）：stack 柱按堆叠和、K线按低/高、
    箱线按 min/max，其余按单点值。返回 (dmin, dmax) 或 None。"""
    dmin = None
    dmax = None

    def feed(v):
        nonlocal dmin, dmax
        if v is None:
            return
        dmin = v if dmin is None else min(dmin, v)
        dmax = v if dmax is None else max(dmax, v)

    stack_pos = {}
    stack_neg = {}
    for s in _grid_series_opts(chart):
        stype = str(s.get("type") or "line")
        data = s.get("data") or []
        if stype == "bar" and s.get("stack"):
            key = str(s.get("stack"))
            for i, item in enumerate(data):
                _, y = parse_data_point(item, i)
                if y is None:
                    continue
                if y >= 0:
                    stack_pos[(key, i)] = stack_pos.get((key, i), 0.0) + y
                else:
                    stack_neg[(key, i)] = stack_neg.get((key, i), 0.0) + y
        elif stype == "candlestick":
            for item in data:
                nums = _datum_list(item)
                if nums and len(nums) >= 4:
                    feed(min(nums[2], nums[0], nums[1]))
                    feed(max(nums[3], nums[0], nums[1]))
        elif stype == "boxplot":
            for item in data:
                nums = _datum_list(item)
                if nums and len(nums) >= 5:
                    feed(nums[0])
                    feed(nums[4])
        else:
            for i, item in enumerate(data):
                _, y = parse_data_point(item, i)
                feed(y)
    for v in stack_pos.values():
        feed(v)
    for v in stack_neg.values():
        feed(v)
    if dmin is None:
        return None
    return dmin, dmax


def _axis_label(axis, x):
    """类别轴标签（x 为类别名或下标）；数值轴退回 format_value。"""
    if axis is not None and axis.type == "category" and axis.categories:
        idx = axis.category_index(x)
        if 0 <= idx < len(axis.categories):
            return axis.categories[idx]
    return format_value(x)


def _fix_value_axis(axis, chart):
    """按 ``_grid_value_extent`` 重设数值轴范围（category 轴自动跳过）。"""
    if axis is None or axis.type != "value":
        return
    ext = _grid_value_extent(chart)
    if ext is not None:
        axis.set_extent(ext[0], ext[1])


# ---------------------------------------------------------------------------
# bar 柱状图
# ---------------------------------------------------------------------------

class BarSeriesRenderer(SeriesRenderer):
    """柱状图（CHART_SPEC §5 C2）。

    option 键：
    - ``stack``: str，同名堆叠（正值向上累加、负值向下累加）；
    - ``barWidth``: 像素（>1）或占槽位比例（0~1]）；
    - ``barBorderRadius``: 圆角 px（数值或数值列表，取最大）；
    - yAxis 为 ``category`` 时自动切换为水平条形；
    - ``anim_t`` 高度生长动画；``update_option`` 时 prev_data 逐柱插值。
    """

    def __init__(self, chart, opt):
        super().__init__(chart, opt)
        self._bars = []        # [dict]，最终几何（anim_t=1）
        self._horizontal = False
        self._plot = QRectF()

    # -- 布局 -------------------------------------------------------------
    def layout(self, rect: QRectF) -> None:
        self._bars = []
        coord = self.chart.coord_for(self.opt)
        if not isinstance(coord, GridCoord):
            return
        self._horizontal = coord.y_axis.type == "category"
        cat_axis = coord.y_axis if self._horizontal else coord.x_axis
        val_axis = coord.x_axis if self._horizontal else coord.y_axis
        _fix_value_axis(val_axis, self.chart)
        self._plot = coord.plot

        # 槽位：grid 内全部 bar 系列按 stack 名 / 自身序号分槽
        slot_keys = []
        series_opts = self.chart.option().get("series") or []
        for idx, s in enumerate(series_opts):
            if not isinstance(s, dict) or str(s.get("type") or "") != "bar":
                continue
            if s.get("coordinateSystem") not in (None, "cartesian2d", "grid"):
                continue
            key = ("stack", str(s.get("stack"))) if s.get("stack") \
                else ("own", idx)
            if key not in slot_keys:
                slot_keys.append(key)
        my_index = 0
        for idx, s in enumerate(series_opts):
            if isinstance(s, dict) and s == self.opt:
                my_index = idx
                break
        my_key = ("stack", str(self.opt.get("stack"))) \
            if self.opt.get("stack") else ("own", my_index)
        slot_idx = slot_keys.index(my_key) if my_key in slot_keys else 0
        n_slots = max(1, len(slot_keys))

        if self._horizontal:
            c0, c1 = coord.plot.top(), coord.plot.bottom()
        else:
            c0, c1 = coord.plot.left(), coord.plot.right()
        band = cat_axis.band_width(c0, c1)
        if band <= 0:
            band = abs(c1 - c0) / max(1, len(self.data()))
        group_w = band * 0.8
        slot_w = group_w / n_slots
        bar_w = self._resolve_bar_width(slot_w)

        # 堆叠基线：同 stack 且排在我之前的可见 bar 系列的同号值累加
        bases = self._stack_bases()
        prev = self.prev_data if isinstance(self.prev_data, list) else None
        radius = self.opt.get("barBorderRadius", 0)
        if isinstance(radius, (list, tuple)):
            radius = max((_to_float(r, 0.0) for r in radius), default=0.0)
        radius = _to_float(radius, 0.0)

        for i, item in enumerate(self.data()):
            x, y = parse_data_point(item, i)
            if y is None:
                continue
            v0 = bases.get(i, 0.0)
            v1 = v0 + y
            center = cat_axis.map(x, c0, c1)
            slot_center = center - group_w / 2 + slot_w * (slot_idx + 0.5)
            if self._horizontal:
                pa = val_axis.map(v0, coord.plot.left(), coord.plot.right())
                pb = val_axis.map(v1, coord.plot.left(), coord.plot.right())
                r = QRectF(min(pa, pb), slot_center - bar_w / 2,
                           abs(pb - pa), bar_w)
            else:
                pa = val_axis.map(v0, coord.plot.bottom(), coord.plot.top())
                pb = val_axis.map(v1, coord.plot.bottom(), coord.plot.top())
                r = QRectF(slot_center - bar_w / 2, min(pa, pb),
                           bar_w, abs(pb - pa))
            prev_y = None
            if prev is not None and i < len(prev):
                _, prev_y = parse_data_point(prev[i], i)
            label = self._cat_label(cat_axis, x, i)
            self._bars.append({
                "index": i, "rect": r, "v0": v0, "y": y, "prev_y": prev_y,
                "center": slot_center, "w": bar_w, "label": label,
                "radius": radius,
            })

    def _resolve_bar_width(self, slot_w):
        bw = _to_float(self.opt.get("barWidth"))
        if bw is None:
            return max(2.0, slot_w * 0.75)
        if 0 < bw <= 1:
            return max(2.0, slot_w * bw)
        return max(2.0, min(bw, slot_w))

    def _stack_bases(self):
        """同 stack 前序可见 bar 系列的逐点同号累加基线 {index: base}。"""
        bases = {}
        stack = self.opt.get("stack")
        if not stack:
            return bases
        for r in self.chart.series_renderers:
            if r is self:
                break
            if not isinstance(r, BarSeriesRenderer) or not r.visible:
                continue
            if str(r.opt.get("stack") or "") != str(stack):
                continue
            for i, item in enumerate(r.data()):
                _, y = parse_data_point(item, i)
                if y is None:
                    continue
                bases[i] = bases.get(i, 0.0) + y
        return bases

    @staticmethod
    def _cat_label(cat_axis, x, i):
        if cat_axis.type == "category" and cat_axis.categories:
            idx = cat_axis.category_index(x)
            if 0 <= idx < len(cat_axis.categories):
                return cat_axis.categories[idx]
        return format_value(x)

    # -- 绘制 -------------------------------------------------------------
    def _animated_value(self, bar, anim_t):
        y, prev_y = bar["y"], bar["prev_y"]
        if prev_y is not None and anim_t < 1.0:
            return _lerp(prev_y, y, anim_t)
        if anim_t < 1.0 and prev_y is None:
            return y * anim_t
        return y

    def paint(self, p: QPainter, anim_t: float) -> None:
        if not self._bars:
            return
        coord = self.chart.coord_for(self.opt)
        if not isinstance(coord, GridCoord):
            return
        val_axis = coord.x_axis if self._horizontal else coord.y_axis
        p.save()
        p.setClipRect(coord.plot)
        p.setPen(Qt.NoPen)
        p.setBrush(self.color())
        for bar in self._bars:
            y_t = self._animated_value(bar, anim_t)
            v1 = bar["v0"] + y_t
            w = bar["w"]
            if self._horizontal:
                pa = val_axis.map(bar["v0"], coord.plot.left(), coord.plot.right())
                pb = val_axis.map(v1, coord.plot.left(), coord.plot.right())
                r = QRectF(min(pa, pb), bar["center"] - w / 2, abs(pb - pa), w)
            else:
                pa = val_axis.map(bar["v0"], coord.plot.bottom(), coord.plot.top())
                pb = val_axis.map(v1, coord.plot.bottom(), coord.plot.top())
                r = QRectF(bar["center"] - w / 2, min(pa, pb), w, abs(pb - pa))
            if r.width() <= 0 or r.height() <= 0:
                continue
            radius = min(bar["radius"], r.width() / 2, r.height() / 2)
            if radius > 0.5:
                p.drawRoundedRect(r, radius, radius)
            else:
                p.drawRect(r)
        p.restore()

    # -- 交互 -------------------------------------------------------------
    def hit_test(self, pos: QPointF):
        for bar in self._bars:
            r = bar["rect"].adjusted(-2, -2, 2, 2)
            if r.contains(pos):
                return {"name": bar["label"], "value": bar["y"],
                        "series": self.name, "dataIndex": bar["index"]}
        return None

    def value_at_index(self, index: int):
        for bar in self._bars:
            if bar["index"] == index:
                r = bar["rect"]
                if self._horizontal:
                    pos = QPointF(r.right(), r.center().y())
                else:
                    pos = QPointF(r.center().x(), r.top())
                return {"name": bar["label"], "value": bar["y"],
                        "series": self.name, "pos": pos}
        return None


# ---------------------------------------------------------------------------
# pictorialBar 象形柱图
# ---------------------------------------------------------------------------

class PictorialBarSeriesRenderer(BarSeriesRenderer):
    """象形柱图：以小图形（symbol）填充柱体。

    option 键：
    - ``symbol``: "rect" | "circle" | "pin"（默认 "rect"）；
    - ``symbolRepeat``: True 时按 symbolSize 沿柱方向重复堆叠小图形直至
      柱顶；整数时为固定重复次数（在柱长内均布）；
    - ``symbolSize``: 数值（边长）或 [宽, 高]。
    不支持 stack（同名槽位逻辑退化为各占一槽）。
    """

    def _stack_bases(self):  # 象形柱不堆叠
        return {}

    def _symbol_size(self):
        ss = self.opt.get("symbolSize", 10)
        if isinstance(ss, (list, tuple)) and ss:
            w = _to_float(ss[0], 10.0)
            h = _to_float(ss[1], w) if len(ss) > 1 else w
            return max(2.0, w), max(2.0, h)
        v = _to_float(ss, 10.0)
        return max(2.0, v), max(2.0, v)

    def _draw_symbol(self, p, cx, cy, w, h):
        """以 (cx, cy) 为中心绘制一个小图形（w×h 外接框）。"""
        kind = str(self.opt.get("symbol") or "rect")
        r = min(w, h) / 2
        if kind == "circle":
            p.drawEllipse(QPointF(cx, cy), w / 2, h / 2)
        elif kind == "pin":
            path = QPainterPath()
            path.addEllipse(QPointF(cx, cy - h * 0.12), r, r)
            path.moveTo(cx - r * 0.55, cy + h * 0.12)
            path.lineTo(cx, cy + h * 0.52)
            path.lineTo(cx + r * 0.55, cy + h * 0.12)
            path.closeSubpath()
            p.drawPath(path)
        else:  # rect
            p.drawRoundedRect(QRectF(cx - w / 2, cy - h / 2, w, h), 2, 2)

    def paint(self, p: QPainter, anim_t: float) -> None:
        if not self._bars:
            return
        coord = self.chart.coord_for(self.opt)
        if not isinstance(coord, GridCoord):
            return
        val_axis = coord.x_axis if self._horizontal else coord.y_axis
        sw, sh = self._symbol_size()
        repeat = self.opt.get("symbolRepeat", False)
        p.save()
        p.setClipRect(coord.plot)
        p.setPen(Qt.NoPen)
        p.setBrush(self.color())
        for bar in self._bars:
            y_t = self._animated_value(bar, anim_t)
            v1 = bar["v0"] + y_t
            if self._horizontal:
                pa = val_axis.map(bar["v0"], coord.plot.left(), coord.plot.right())
                pb = val_axis.map(v1, coord.plot.left(), coord.plot.right())
                along, cross = sw, sh
            else:
                pa = val_axis.map(bar["v0"], coord.plot.bottom(), coord.plot.top())
                pb = val_axis.map(v1, coord.plot.bottom(), coord.plot.top())
                along, cross = sh, sw
            direction = 1.0 if pb >= pa else -1.0
            total = abs(pb - pa)
            if total <= 0:
                continue
            if repeat is True:
                n = max(1, int(total // max(1.0, along)))
                offsets = [(k + 0.5) * along for k in range(n)]
                offsets = [o for o in offsets if o <= total] or [total / 2]
            elif repeat:
                n = max(1, int(_to_float(repeat, 1)))
                offsets = [(k + 0.5) * total / n for k in range(n)]
            else:
                offsets = [max(along / 2, total - along / 2)]
            for off in offsets:
                d = pa + direction * off
                if self._horizontal:
                    self._draw_symbol(p, d, bar["center"], along, cross)
                else:
                    self._draw_symbol(p, bar["center"], d, cross, along)
        p.restore()


# ---------------------------------------------------------------------------
# line 折线（完整版，覆盖 core 自检版）
# ---------------------------------------------------------------------------

class LineSeriesRenderer(SeriesRenderer):
    """折线图（完整版，注册时覆盖 core 的 SimpleLineSeriesRenderer）。

    option 键：
    - ``smooth``: bool 或 0~1 平滑系数（Catmull-Rom → 贝塞尔）；
    - ``areaStyle``: dict 或真值，面积填充（透明渐变），
      ``areaStyle.opacity`` 可调（默认 0.22）；
    - ``step``: "start" | "middle" | "end" 阶梯线；
    - ``showSymbol``: 是否绘制数据点（默认 True）；
    - ``symbolSize``: 数据点直径 px（默认 6）；
    - ``lineStyle``: {"type": "solid|dashed|dotted", "width": px, "color": ...}；
    - 支持 grid / polar（闭合）/ singleAxis 坐标系；
    - ``update_option`` 旧→新数据逐点插值。
    """

    def __init__(self, chart, opt):
        super().__init__(chart, opt)
        self._points = []        # [QPointF|None]
        self._prev_points = []   # 上一次布局的点（同长度时用于兜底插值）
        self._entries = []       # [(x, y)]

    # -- 布局 -------------------------------------------------------------
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
                    self._points.append(coord.map_point(y))
                else:
                    self._points.append(coord.map_point(x, y))
            except Exception:
                self._points.append(None)

    def _animated_points(self, anim_t):
        """旧→新插值：长度一致时逐点 lerp；否则返回当前点列。"""
        cur = self._points
        prev_src = self._prev_points
        if self.prev_data is not None and len(self.prev_data) == len(self._entries):
            coord = self.chart.coord_for(self.opt)
            single = getattr(coord, "kind", "") == "singleAxis" if coord else False
            prev = []
            for i, item in enumerate(self.prev_data):
                x, y = parse_data_point(item, i)
                if y is None or coord is None:
                    prev.append(None)
                    continue
                try:
                    prev.append(coord.map_point(y) if single
                                else coord.map_point(x, y))
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
                out.append(QPointF(_lerp(a.x(), b.x(), anim_t),
                                   _lerp(a.y(), b.y(), anim_t)))
        return out

    # -- 路径构建 ---------------------------------------------------------
    def _line_path(self, seg):
        """按 smooth / step 构建一段折线路径。seg: [QPointF]（≥1）。"""
        step = str(self.opt.get("step") or "")
        smooth = self.opt.get("smooth", False)
        if step in ("start", "middle", "end") and len(seg) >= 2:
            pts = [seg[0]]
            for a, b in zip(seg, seg[1:]):
                if step == "start":
                    pts.append(QPointF(a.x(), b.y()))
                elif step == "end":
                    pts.append(QPointF(b.x(), a.y()))
                else:  # middle
                    pts.append(QPointF((a.x() + b.x()) / 2, a.y()))
                    pts.append(QPointF((a.x() + b.x()) / 2, b.y()))
                pts.append(b)
            path = QPainterPath(pts[0])
            for pt in pts[1:]:
                path.lineTo(pt)
            return path, pts
        if smooth and len(seg) >= 2:
            k = smooth if isinstance(smooth, (int, float)) \
                and not isinstance(smooth, bool) else 0.5
            return _smooth_path(seg, k), seg
        path = QPainterPath(seg[0])
        for pt in seg[1:]:
            path.lineTo(pt)
        return path, seg

    def _baseline_y(self, coord):
        """面积填充基线（grid：0 值线收敛到 plot 内）。"""
        if isinstance(coord, GridCoord):
            ax = coord.y_axis
            v = min(max(0.0, ax.vmin), ax.vmax) if ax.type == "value" else 0.0
            return ax.map(v, coord.plot.bottom(), coord.plot.top())
        return None

    # -- 绘制 -------------------------------------------------------------
    def paint(self, p: QPainter, anim_t: float) -> None:
        pts = self._animated_points(anim_t)
        valid = [pt for pt in pts if pt is not None]
        if not valid:
            return
        coord = self.chart.coord_for(self.opt)
        color = self.color()
        ls = self.opt.get("lineStyle") or {}
        width = _to_float(ls.get("width"), 2.0)
        if isinstance(ls.get("color"), str) and ls["color"]:
            color = QColor(ls["color"])

        # 分段（None 断点切开）
        segs = []
        seg = []
        for pt in pts:
            if pt is None:
                if seg:
                    segs.append(seg)
                    seg = []
            else:
                seg.append(pt)
        if seg:
            segs.append(seg)

        p.save()
        if isinstance(coord, GridCoord):
            p.setClipRect(coord.plot)
        polar = getattr(coord, "kind", "") == "polar"

        # 面积填充（先填充后描线）
        area = self.opt.get("areaStyle")
        if area:
            opacity = 0.22
            if isinstance(area, dict):
                opacity = _to_float(area.get("opacity"), 0.22)
            base_y = self._baseline_y(coord)
            for seg_pts in segs:
                if len(seg_pts) < 2:
                    continue
                path, spine = self._line_path(seg_pts)
                if polar:
                    path.lineTo(coord.center)
                    path.closeSubpath()
                    p.setPen(Qt.NoPen)
                    p.setBrush(_with_alpha(color, 255 * opacity))
                    p.drawPath(path)
                elif base_y is not None:
                    fill = QPainterPath(path)
                    fill.lineTo(QPointF(spine[-1].x(), base_y))
                    fill.lineTo(QPointF(spine[0].x(), base_y))
                    fill.closeSubpath()
                    top = min(pt.y() for pt in spine)
                    grad = QLinearGradient(QPointF(0, top), QPointF(0, base_y))
                    grad.setColorAt(0.0, _with_alpha(color, 255 * opacity))
                    grad.setColorAt(1.0, _with_alpha(color, 0))
                    p.setPen(Qt.NoPen)
                    p.setBrush(grad)
                    p.drawPath(fill)

        # 折线本体
        pen = QPen(color, width)
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        lt = str(ls.get("type") or "solid")
        if lt in ("dashed", "dash"):
            pen.setStyle(Qt.DashLine)
        elif lt in ("dotted", "dot"):
            pen.setStyle(Qt.DotLine)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        for seg_pts in segs:
            if len(seg_pts) < 2:
                continue
            path, _ = self._line_path(seg_pts)
            if polar:
                path.closeSubpath()
            p.drawPath(path)

        # 数据点
        if bool(self.opt.get("showSymbol", True)):
            r = max(1.0, _to_float(self.opt.get("symbolSize"), 6.0) / 2)
            r *= max(0.2, anim_t)
            p.setPen(QPen(color, 1.5))
            p.setBrush(QColor(T("color.bg.elevated")))
            for pt in valid:
                p.drawEllipse(pt, r, r)
        p.restore()

    # -- 交互 -------------------------------------------------------------
    def hit_test(self, pos: QPointF):
        best = None
        best_d = 10.0  # 命中半径 px
        for i, pt in enumerate(self._points):
            if pt is None:
                continue
            d = math.hypot(pt.x() - pos.x(), pt.y() - pos.y())
            if d <= best_d:
                best_d = d
                best = i
        if best is None:
            return None
        x, y = self._entries[best]
        return {"name": self.name, "value": y, "series": self.name,
                "dataIndex": best, "x": x}

    def value_at_index(self, index: int):
        if not isinstance(index, int) or not (0 <= index < len(self._entries)):
            return None
        x, y = self._entries[index]
        if y is None:
            return None
        pos = self._points[index] if index < len(self._points) else None
        return {"name": self.name, "value": y, "series": self.name, "pos": pos}


# ---------------------------------------------------------------------------
# scatter 散点
# ---------------------------------------------------------------------------

class ScatterSeriesRenderer(SeriesRenderer):
    """散点图。

    option 键：
    - ``symbolSize``: 数值 → 固定直径 px；缺省且数据带第三维时按第三维
      在本系列内线性映射到 6~24px；否则默认 8px。
    数据项：数值 / [x, y] / [x, y, size] / {"value": [...]}。
    支持 grid / polar / singleAxis 坐标系。
    """

    def __init__(self, chart, opt):
        super().__init__(chart, opt)
        self._dots = []      # [dict(pt=QPointF, r=float, value, index, x)]

    # -- 布局 -------------------------------------------------------------
    def _third_dim(self, item):
        v = item.get("value") if isinstance(item, dict) else item
        if isinstance(v, (list, tuple)) and len(v) >= 3:
            return _to_float(v[2])
        return None

    def layout(self, rect: QRectF) -> None:
        self._dots = []
        coord = self.chart.coord_for(self.opt)
        if coord is None:
            return
        single = getattr(coord, "kind", "") == "singleAxis"
        fixed = _to_float(self.opt.get("symbolSize"))
        thirds = [self._third_dim(it) for it in self.data()]
        known = [t for t in thirds if t is not None]
        zmin = min(known) if known else 0.0
        zmax = max(known) if known else 1.0
        for i, item in enumerate(self.data()):
            x, y = parse_data_point(item, i)
            if y is None:
                continue
            try:
                pt = coord.map_point(y) if single else coord.map_point(x, y)
            except Exception:
                continue
            if fixed is not None:
                r = max(1.0, fixed / 2)
            elif thirds[i] is not None:
                span = zmax - zmin
                f = 0.5 if span == 0 else (thirds[i] - zmin) / span
                r = _lerp(6.0, 24.0, f) / 2
            else:
                r = 4.0
            self._dots.append({"pt": pt, "r": r, "value": y,
                               "index": i, "x": x})

    # -- 绘制 -------------------------------------------------------------
    def paint(self, p: QPainter, anim_t: float) -> None:
        if not self._dots:
            return
        p.save()
        coord = self.chart.coord_for(self.opt)
        if isinstance(coord, GridCoord):
            p.setClipRect(coord.plot)
        color = self.color()
        p.setPen(QPen(_with_alpha(color, 230), 1))
        p.setBrush(_with_alpha(color, 190))
        scale = max(0.0, anim_t)
        for d in self._dots:
            r = d["r"] * scale
            if r <= 0:
                continue
            p.drawEllipse(d["pt"], r, r)
        p.restore()

    # -- 交互 -------------------------------------------------------------
    def hit_test(self, pos: QPointF):
        best = None
        best_d = 1e9
        for d in self._dots:
            dist = math.hypot(d["pt"].x() - pos.x(), d["pt"].y() - pos.y())
            if dist <= max(d["r"], 4.0) + 3 and dist < best_d:
                best_d = dist
                best = d
        if best is None:
            return None
        return {"name": self.name, "value": best["value"],
                "series": self.name, "dataIndex": best["index"], "x": best["x"]}

    def value_at_index(self, index: int):
        for d in self._dots:
            if d["index"] == index:
                return {"name": self.name, "value": d["value"],
                        "series": self.name, "pos": d["pt"]}
        return None


# ---------------------------------------------------------------------------
# effectScatter 涟漪散点
# ---------------------------------------------------------------------------

class EffectScatterSeriesRenderer(ScatterSeriesRenderer):
    """涟漪散点：散点 + QTimer 驱动的扩散圆动画。

    option 键：
    - ``rippleEffect``: {"period": 秒（默认 3）, "scale": 扩散倍数（默认 2.6）}；
    - 其余同 scatter（symbolSize / 第三维映射）。

    动画生命周期：QTimer 以 chart（ChartWidget）为 parent，随控件销毁；
    回调经 weakref 持有渲染器，渲染器被替换（update_option 重建）后回调
    自动停止并 deleteLater，不泄漏。
    """

    _TICK_MS = 40

    def __init__(self, chart, opt):
        super().__init__(chart, opt)
        self._phase = 0.0
        ripple = self.opt.get("rippleEffect") or {}
        self._period = max(0.2, _to_float(ripple.get("period"), 3.0))
        self._scale = max(1.2, _to_float(ripple.get("scale"), 2.6))
        self_ref = weakref.ref(self)
        timer = QTimer(chart)  # parent 挂 ChartWidget，随控件销毁
        timer.setInterval(self._TICK_MS)

        def _on_timeout(timer_ref=weakref.ref(timer)):
            self_obj = self_ref()
            t = timer_ref()
            if self_obj is None or t is None:
                if t is not None:
                    t.stop()
                    t.deleteLater()
                return
            self_obj._tick()

        timer.timeout.connect(_on_timeout)
        timer.start()
        self._timer = timer

    def _tick(self):
        """推进涟漪相位并请求重绘（测试可手动调用）。"""
        self._phase = (self._phase + self._TICK_MS / (self._period * 1000.0)) % 1.0
        self.chart.update()

    def paint(self, p: QPainter, anim_t: float) -> None:
        super().paint(p, anim_t)
        if not self._dots:
            return
        color = self.color()
        p.save()
        coord = self.chart.coord_for(self.opt)
        if isinstance(coord, GridCoord):
            p.setClipRect(coord.plot)
        p.setBrush(Qt.NoBrush)
        for d in self._dots:
            r0 = max(d["r"], 3.0)
            rr = r0 * (1.0 + self._phase * (self._scale - 1.0))
            alpha = 140 * (1.0 - self._phase)
            p.setPen(QPen(_with_alpha(color, alpha), 1.6))
            p.drawEllipse(d["pt"], rr, rr)
        p.restore()


# ---------------------------------------------------------------------------
# candlestick K线
# ---------------------------------------------------------------------------

class CandlestickSeriesRenderer(SeriesRenderer):
    """K线（OHLC）。数据项：[开, 收, 最低, 最高]（或 {"value": [...]}）。

    配色遵循 A 股习惯：红涨绿跌 —— 涨（收 ≥ 开）用 ``color.danger``，
    跌用 ``color.success``；可用 option 键 ``colorUp`` / ``colorDown``
    覆盖（如美股习惯可传 colorUp=绿色、colorDown=红色）。

    option 键：``barWidth``（实体宽 px，缺省为 band 的 60%，上限 24）、
    ``colorUp`` / ``colorDown``；``update_option`` 同长度数据逐值插值。
    """

    def __init__(self, chart, opt):
        super().__init__(chart, opt)
        self._items = []   # [dict(cx, open, close, low, high, w, x, index, prev)]

    # -- 布局 -------------------------------------------------------------
    def layout(self, rect: QRectF) -> None:
        self._items = []
        coord = self.chart.coord_for(self.opt)
        if not isinstance(coord, GridCoord):
            return
        _fix_value_axis(coord.y_axis, self.chart)
        band = coord.x_axis.band_width(coord.plot.left(), coord.plot.right())
        if band <= 0:
            band = coord.plot.width() / max(1, len(self.data()))
        w = _to_float(self.opt.get("barWidth"))
        w = max(3.0, min(w, band * 0.9)) if w else min(band * 0.6, 24.0)
        prev = self.prev_data if isinstance(self.prev_data, list) else None
        for i, item in enumerate(self.data()):
            nums = _datum_list(item)
            if not nums or len(nums) < 4:
                continue
            o, c, lo, hi = nums[0], nums[1], nums[2], nums[3]
            x = i  # OHLC 数组不含类别，按下标对位 xAxis 类别
            cx = coord.x_axis.map(x, coord.plot.left(), coord.plot.right())
            prev_nums = None
            if prev is not None and i < len(prev):
                prev_nums = _datum_list(prev[i])
            self._items.append({
                "cx": cx, "open": o, "close": c, "low": lo, "high": hi,
                "w": w, "x": x, "index": i,
                "prev": prev_nums[:4] if prev_nums and len(prev_nums) >= 4 else None,
            })

    # -- 配色 -------------------------------------------------------------
    def _up_color(self):
        c = self.opt.get("colorUp")
        return QColor(c) if isinstance(c, str) and c else QColor(T("color.danger"))

    def _down_color(self):
        c = self.opt.get("colorDown")
        return QColor(c) if isinstance(c, str) and c else QColor(T("color.success"))

    # -- 绘制 -------------------------------------------------------------
    def paint(self, p: QPainter, anim_t: float) -> None:
        if not self._items:
            return
        coord = self.chart.coord_for(self.opt)
        if not isinstance(coord, GridCoord):
            return
        ax = coord.y_axis
        up, down = self._up_color(), self._down_color()
        p.save()
        p.setClipRect(coord.plot)
        for it in self._items:
            if it["prev"] is not None and anim_t < 1.0:
                o, c, lo, hi = (
                    _lerp(it["prev"][k], v, anim_t)
                    for k, v in enumerate((it["open"], it["close"],
                                           it["low"], it["high"]))
                )
            elif anim_t < 1.0:
                # 入场：自开盘价向四周生长
                o = it["open"]
                c = _lerp(it["open"], it["close"], anim_t)
                lo = _lerp(it["open"], it["low"], anim_t)
                hi = _lerp(it["open"], it["high"], anim_t)
            else:
                o, c, lo, hi = it["open"], it["close"], it["low"], it["high"]
            yo = ax.map(o, coord.plot.bottom(), coord.plot.top())
            yc = ax.map(c, coord.plot.bottom(), coord.plot.top())
            yl = ax.map(lo, coord.plot.bottom(), coord.plot.top())
            yh = ax.map(hi, coord.plot.bottom(), coord.plot.top())
            rising = c >= o
            color = up if rising else down
            cx, w = it["cx"], it["w"]
            # 影线
            p.setPen(QPen(color, 1.2))
            p.drawLine(QPointF(cx, yh), QPointF(cx, yl))
            # 实体
            body = QRectF(cx - w / 2, min(yo, yc), w, max(1.0, abs(yc - yo)))
            p.setPen(QPen(color, 1))
            p.setBrush(color)
            p.drawRect(body)
        p.restore()

    # -- 交互 -------------------------------------------------------------
    def hit_test(self, pos: QPointF):
        coord = self.chart.coord_for(self.opt)
        if not isinstance(coord, GridCoord):
            return None
        ax = coord.y_axis
        for it in self._items:
            yl = ax.map(it["low"], coord.plot.bottom(), coord.plot.top())
            yh = ax.map(it["high"], coord.plot.bottom(), coord.plot.top())
            if abs(pos.x() - it["cx"]) <= max(it["w"] / 2, 4.0) + 2 \
                    and yh - 3 <= pos.y() <= yl + 3:
                return {"name": _axis_label(coord.x_axis, it["x"]),
                        "value": [it["open"], it["close"], it["low"], it["high"]],
                        "series": self.name, "dataIndex": it["index"]}
        return None

    def value_at_index(self, index: int):
        coord = self.chart.coord_for(self.opt)
        for it in self._items:
            if it["index"] == index:
                pos = None
                if isinstance(coord, GridCoord):
                    yc = coord.y_axis.map(it["close"], coord.plot.bottom(),
                                          coord.plot.top())
                    pos = QPointF(it["cx"], yc)
                return {"name": _axis_label(coord.x_axis, it["x"]),
                        "value": it["close"],
                        "series": self.name, "pos": pos}
        return None


# ---------------------------------------------------------------------------
# boxplot 箱线
# ---------------------------------------------------------------------------

class BoxplotSeriesRenderer(SeriesRenderer):
    """箱线图。数据项：[min, Q1, 中位, Q3, max]（或 {"value": [...]}）。

    option 键：``barWidth``（箱体宽 px，缺省 band 的 50%，上限 28）。
    绘制：箱体（Q1~Q3 半透明填充 + 描边）+ 中位线 + 上下须线（含端帽）。
    """

    def __init__(self, chart, opt):
        super().__init__(chart, opt)
        self._items = []   # [dict(cx, w, vals=[5], x, index)]

    def layout(self, rect: QRectF) -> None:
        self._items = []
        coord = self.chart.coord_for(self.opt)
        if not isinstance(coord, GridCoord):
            return
        _fix_value_axis(coord.y_axis, self.chart)
        band = coord.x_axis.band_width(coord.plot.left(), coord.plot.right())
        if band <= 0:
            band = coord.plot.width() / max(1, len(self.data()))
        w = _to_float(self.opt.get("barWidth"))
        w = max(4.0, min(w, band * 0.9)) if w else min(band * 0.5, 28.0)
        for i, item in enumerate(self.data()):
            nums = _datum_list(item)
            if not nums or len(nums) < 5:
                continue
            x = i  # 五元数组不含类别，按下标对位 xAxis 类别
            cx = coord.x_axis.map(x, coord.plot.left(), coord.plot.right())
            self._items.append({"cx": cx, "w": w, "vals": nums[:5],
                                "x": x, "index": i})

    def paint(self, p: QPainter, anim_t: float) -> None:
        if not self._items:
            return
        coord = self.chart.coord_for(self.opt)
        if not isinstance(coord, GridCoord):
            return
        ax = coord.y_axis
        color = self.color()
        p.save()
        p.setClipRect(coord.plot)
        for it in self._items:
            vmin, q1, med, q3, vmax = it["vals"]
            mid = (q1 + q3) / 2
            if anim_t < 1.0:  # 入场：自箱体中线向两端展开
                vmin = _lerp(mid, vmin, anim_t)
                vmax = _lerp(mid, vmax, anim_t)
                q1 = _lerp(mid, q1, anim_t)
                q3 = _lerp(mid, q3, anim_t)
                med = _lerp(mid, med, anim_t)
            y_min = ax.map(vmin, coord.plot.bottom(), coord.plot.top())
            y_q1 = ax.map(q1, coord.plot.bottom(), coord.plot.top())
            y_med = ax.map(med, coord.plot.bottom(), coord.plot.top())
            y_q3 = ax.map(q3, coord.plot.bottom(), coord.plot.top())
            y_max = ax.map(vmax, coord.plot.bottom(), coord.plot.top())
            cx, w = it["cx"], it["w"]
            # 须线 + 端帽
            p.setPen(QPen(color, 1.2))
            p.setBrush(Qt.NoBrush)
            p.drawLine(QPointF(cx, y_max), QPointF(cx, y_min))
            p.drawLine(QPointF(cx - w / 4, y_min), QPointF(cx + w / 4, y_min))
            p.drawLine(QPointF(cx - w / 4, y_max), QPointF(cx + w / 4, y_max))
            # 箱体
            box = QRectF(cx - w / 2, min(y_q1, y_q3), w, max(1.0, abs(y_q3 - y_q1)))
            p.setPen(QPen(color, 1.4))
            p.setBrush(_with_alpha(color, 60))
            p.drawRect(box)
            # 中位线
            p.setPen(QPen(color, 2))
            p.drawLine(QPointF(cx - w / 2, y_med), QPointF(cx + w / 2, y_med))
        p.restore()

    def hit_test(self, pos: QPointF):
        coord = self.chart.coord_for(self.opt)
        if not isinstance(coord, GridCoord):
            return None
        ax = coord.y_axis
        for it in self._items:
            y_min = ax.map(it["vals"][0], coord.plot.bottom(), coord.plot.top())
            y_max = ax.map(it["vals"][4], coord.plot.bottom(), coord.plot.top())
            if abs(pos.x() - it["cx"]) <= it["w"] / 2 + 3 \
                    and y_max - 3 <= pos.y() <= y_min + 3:
                return {"name": format_value(it["x"]), "value": it["vals"],
                        "series": self.name, "dataIndex": it["index"]}
        return None

    def value_at_index(self, index: int):
        coord = self.chart.coord_for(self.opt)
        for it in self._items:
            if it["index"] == index:
                pos = None
                if isinstance(coord, GridCoord):
                    y_med = coord.y_axis.map(it["vals"][2], coord.plot.bottom(),
                                             coord.plot.top())
                    pos = QPointF(it["cx"], y_med)
                return {"name": _axis_label(coord.x_axis, it["x"]),
                        "value": it["vals"][2],
                        "series": self.name, "pos": pos}
        return None


# ---------------------------------------------------------------------------
# heatmap 热力（grid 直角 + calendar 日历）
# ---------------------------------------------------------------------------

class HeatmapSeriesRenderer(SeriesRenderer):
    """热力图。

    - Grid 直角热力：xAxis / yAxis 均为 category，数据项 [x, y, value]
      （x/y 为类别名或下标），按 band 填格；
    - 日历热力：``coordinateSystem: "calendar"``，数据项 [日期, value]，
      GitHub 风格逐格填充（圆角小格）。

    色带：默认 ``color.primary.subtle`` → ``color.primary`` 按值线性插值；
    option 含 ``visualMap``（顶层，经 ``chart.option().get("visualMap")``
    读取）时按 ``visualMap.min/max`` 与 ``visualMap.inRange.colors`` 映射。
    """

    def __init__(self, chart, opt):
        super().__init__(chart, opt)
        self._cells = []   # [dict(rect, value, label)]
        self._calendar = False

    # -- 数据 -------------------------------------------------------------
    def _parse_items(self):
        """→ [(x, y, value)]（日历模式 y 为 None，x 为日期）。"""
        out = []
        for item in self.data():
            v = item.get("value") if isinstance(item, dict) else item
            if not isinstance(v, (list, tuple)) or len(v) < 2:
                continue
            if self._calendar:
                val = _to_float(v[1])
                if val is not None:
                    out.append((v[0], None, val))
            else:
                if len(v) < 3:
                    continue
                val = _to_float(v[2])
                if val is not None:
                    out.append((v[0], v[1], val))
        return out

    def _colors_and_range(self, items):
        """→ (colors, vmin, vmax)：visualMap 优先，否则默认色带 + 数据范围。"""
        vm = self.chart.option().get("visualMap")
        colors = None
        vmin = vmax = None
        if isinstance(vm, dict):
            in_range = vm.get("inRange") or {}
            if isinstance(in_range.get("colors"), list) \
                    and in_range["colors"]:
                colors = in_range["colors"]
            vmin = _to_float(vm.get("min"))
            vmax = _to_float(vm.get("max"))
        if colors is None:
            colors = [T("color.primary.subtle"), T("color.primary")]
        vals = [v for _, _, v in items]
        if vmin is None:
            vmin = min(vals) if vals else 0.0
        if vmax is None:
            vmax = max(vals) if vals else 1.0
        return colors, vmin, vmax

    # -- 布局 -------------------------------------------------------------
    def layout(self, rect: QRectF) -> None:
        self._cells = []
        coord = self.chart.coord_for(self.opt)
        self._calendar = isinstance(coord, CalendarCoord)
        items = self._parse_items()
        if not items or coord is None:
            return
        colors, vmin, vmax = self._colors_and_range(items)
        span = vmax - vmin
        for x, y, val in items:
            t = 0.5 if span == 0 else (val - vmin) / span
            color = _ramp_color(colors, t)
            if self._calendar:
                r = coord.cell_rect(x)
                if r.isNull():
                    continue
                label = str(x)
                cell = r.adjusted(1, 1, -1, -1)
            else:
                if not isinstance(coord, GridCoord):
                    continue
                px = coord.x_axis.map(x, coord.plot.left(), coord.plot.right())
                py = coord.y_axis.map(y, coord.plot.bottom(), coord.plot.top())
                bw = coord.x_axis.band_width(coord.plot.left(), coord.plot.right()) or 10.0
                bh = coord.y_axis.band_width(coord.plot.bottom(), coord.plot.top()) or 10.0
                label = f"{_axis_label(coord.x_axis, x)}, {_axis_label(coord.y_axis, y)}"
                cell = QRectF(px - bw / 2 + 1, py - bh / 2 + 1,
                              bw - 2, bh - 2)
            self._cells.append({"rect": cell, "value": val,
                                "label": label, "color": color})

    # -- 绘制 -------------------------------------------------------------
    def paint(self, p: QPainter, anim_t: float) -> None:
        if not self._cells:
            return
        p.save()
        coord = self.chart.coord_for(self.opt)
        if isinstance(coord, GridCoord):
            p.setClipRect(coord.plot)
        p.setPen(Qt.NoPen)
        radius = 2.0 if self._calendar else 0.0
        for cell in self._cells:
            c = QColor(cell["color"])
            c.setAlpha(int(255 * max(0.15, anim_t)))
            p.setBrush(c)
            if radius:
                p.drawRoundedRect(cell["rect"], radius, radius)
            else:
                p.drawRect(cell["rect"])
        p.restore()

    # -- 交互 -------------------------------------------------------------
    def hit_test(self, pos: QPointF):
        for cell in self._cells:
            if cell["rect"].adjusted(-1, -1, 1, 1).contains(pos):
                return {"name": cell["label"], "value": cell["value"],
                        "series": self.name}
        return None


# ---------------------------------------------------------------------------
# parallel 平行坐标
# ---------------------------------------------------------------------------

class ParallelSeriesRenderer(SeriesRenderer):
    """平行坐标：自带多条垂直轴，每行数据一条折线穿轴，半透明多系列。

    维度名来源：顶层 option ``parallelAxis``（[{"name":..,"min":..,"max":..}
    或字符串列表]）；缺省时若本系列 data 第一行全为字符串则取其为维度名
    （该行不参与绘制），否则自动生成 dim0..dimN。
    数据：每行一个等长数值列表。
    """

    def __init__(self, chart, opt):
        super().__init__(chart, opt)
        self._axes = []    # [dict(name, x, vmin, vmax)]（vmin/vmax 数据范围）
        self._rows = []    # [dict(pts=[QPointF], values=[float], index)]
        self._area = QRectF()

    # -- 维度 -------------------------------------------------------------
    def _raw_rows(self):
        rows = []
        for item in self.data():
            nums = _datum_list(item)
            if nums is not None:
                rows.append(nums)
                continue
            v = item.get("value") if isinstance(item, dict) else item
            if isinstance(v, (list, tuple)) and v \
                    and all(isinstance(x, str) for x in v):
                rows.append(list(v))  # 字符串行：候选维度名
        return rows

    def _dims(self, rows):
        pa = self.chart.option().get("parallelAxis")
        dims = []
        if isinstance(pa, list) and pa:
            for d in pa:
                if isinstance(d, dict):
                    dims.append({"name": str(d.get("name") or f"dim{len(dims)}"),
                                 "min": _to_float(d.get("min")),
                                 "max": _to_float(d.get("max"))})
                else:
                    dims.append({"name": str(d), "min": None, "max": None})
            return dims, rows
        if rows and all(isinstance(x, str) for x in rows[0]):
            names = rows[0]
            return [{"name": n, "min": None, "max": None} for n in names], rows[1:]
        n = max((len(r) for r in rows), default=0)
        return [{"name": f"dim{i}", "min": None, "max": None} for i in range(n)], rows

    # -- 布局 -------------------------------------------------------------
    def layout(self, rect: QRectF) -> None:
        self._axes = []
        self._rows = []
        rows = self._raw_rows()
        dims, rows = self._dims(rows)
        rows = [r for r in rows if all(_to_float(x) is not None for x in r)]
        if not dims or not rows:
            return
        n = len(dims)
        self._area = QRectF(rect.left() + 40, rect.top() + 34,
                            max(40.0, rect.width() - 80),
                            max(30.0, rect.height() - 34 - 26))
        for j, dim in enumerate(dims):
            x = self._area.left() + (self._area.width() * j / (n - 1) if n > 1
                                     else self._area.width() / 2)
            col = [r[j] for r in rows if j < len(r)]
            lo = dim["min"] if dim["min"] is not None else (min(col) if col else 0.0)
            hi = dim["max"] if dim["max"] is not None else (max(col) if col else 1.0)
            if lo == hi:
                hi = lo + 1.0
            self._axes.append({"name": dim["name"], "x": x,
                               "vmin": lo, "vmax": hi})
        for i, r in enumerate(rows):
            pts = []
            for j, ax in enumerate(self._axes):
                v = r[j] if j < len(r) else ax["vmin"]
                f = (v - ax["vmin"]) / (ax["vmax"] - ax["vmin"])
                f = max(0.0, min(1.0, f))
                pts.append(QPointF(ax["x"],
                                   self._area.bottom() - f * self._area.height()))
            self._rows.append({"pts": pts, "values": list(r), "index": i})

    # -- 绘制 -------------------------------------------------------------
    def paint(self, p: QPainter, anim_t: float) -> None:
        if not self._axes:
            return
        p.save()
        # 兜底 grid 坐标系对平行坐标无意义，覆盖其轴线背景
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(T("color.bg.base")))
        p.drawRect(QRectF(self._area.left() - 40, self._area.top() - 34,
                          self._area.width() + 80, self._area.height() + 60))
        color = self.color()
        # 数据线（半透明，多条重叠可见）
        pen = QPen(_with_alpha(color, 110), 1.6)
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        reveal = max(0.0, min(1.0, anim_t))
        for row in self._rows:
            pts = row["pts"]
            if len(pts) < 2:
                continue
            if reveal < 1.0:
                # 入场：按进度自左向右揭示
                total = len(pts) - 1
                upto = reveal * total
                seg = []
                for k, pt in enumerate(pts):
                    if k <= int(upto):
                        seg.append(pt)
                    elif k == int(upto) + 1:
                        f = upto - int(upto)
                        seg.append(QPointF(_lerp(pts[k - 1].x(), pt.x(), f),
                                           _lerp(pts[k - 1].y(), pt.y(), f)))
                if len(seg) >= 2:
                    p.drawPolyline(seg)
            else:
                p.drawPolyline(pts)
        # 轴 + 标签
        c_axis = QColor(T("color.border.strong"))
        c_text = QColor(T("color.text.secondary"))
        font = chart_font(T("font.xs"))
        p.setFont(font)
        fm = QFontMetricsF(font)
        for ax in self._axes:
            p.setPen(QPen(c_axis, 1))
            p.drawLine(QPointF(ax["x"], self._area.top()),
                       QPointF(ax["x"], self._area.bottom()))
            p.setPen(c_text)
            p.drawText(QRectF(ax["x"] - 50, self._area.top() - fm.height() - 6,
                              100, fm.height()),
                       Qt.AlignHCenter | Qt.AlignBottom, ax["name"])
            p.drawText(QRectF(ax["x"] - 50, self._area.top() + 2, 100, fm.height()),
                       Qt.AlignHCenter | Qt.AlignTop, format_value(ax["vmax"]))
            p.drawText(QRectF(ax["x"] - 50,
                              self._area.bottom() - fm.height() - 2, 100, fm.height()),
                       Qt.AlignHCenter | Qt.AlignBottom, format_value(ax["vmin"]))
        p.restore()

    # -- 交互 -------------------------------------------------------------
    def hit_test(self, pos: QPointF):
        best = None
        best_d = 6.0
        for row in self._rows:
            pts = row["pts"]
            for a, b in zip(pts, pts[1:]):
                d = _dist_to_segment(pos, a, b)
                if d <= best_d:
                    best_d = d
                    best = row
        if best is None:
            return None
        return {"name": f"{self.name} #{best['index']}",
                "value": best["values"], "series": self.name,
                "dataIndex": best["index"]}


# ---------------------------------------------------------------------------
# themeRiver 主题河
# ---------------------------------------------------------------------------

class ThemeRiverSeriesRenderer(SeriesRenderer):
    """主题河：时间 × 系列的流带图。

    数据：``[[时间, 值, 系列名], ...]``（时间为字符串，ISO 日期可排序）。
    流带平滑（贝塞尔）、居中基线（各时刻总宽关于绘图区中线对称），
    自带底部时间轴标签（约 5 个均布刻度）。
    """

    def __init__(self, chart, opt):
        super().__init__(chart, opt)
        self._streams = []   # [dict(name, top=[QPointF], bot=[QPointF], color_idx)]
        self._times = []
        self._matrix = {}    # (name, t_idx) -> value
        self._area = QRectF()

    # -- 数据 -------------------------------------------------------------
    def _parse(self):
        times = []
        names = []
        matrix = {}
        for item in self.data():
            v = item.get("value") if isinstance(item, dict) else item
            if not isinstance(v, (list, tuple)) or len(v) < 3:
                continue
            t, val, name = v[0], _to_float(v[1]), str(v[2])
            if val is None:
                continue
            t = str(t)
            if t not in times:
                times.append(t)
            if name not in names:
                names.append(name)
            matrix[(name, t)] = matrix.get((name, t), 0.0) + val
        times.sort()
        return times, names, matrix

    # -- 布局 -------------------------------------------------------------
    def layout(self, rect: QRectF) -> None:
        self._streams = []
        self._times = []
        self._matrix = {}
        times, names, matrix = self._parse()
        if not times or not names:
            return
        self._times = times
        self._matrix = matrix
        self._area = QRectF(rect.left() + 24, rect.top() + 20,
                            max(40.0, rect.width() - 48),
                            max(30.0, rect.height() - 20 - 30))
        n = len(times)
        xs = [self._area.left() + self._area.width() * (i + 0.5) / n
              for i in range(n)]
        totals = [sum(matrix.get((name, t), 0.0) for name in names)
                  for t in times]
        max_total = max(totals) if totals else 1.0
        scale = (self._area.height() * 0.9) / max(1e-9, max_total)
        cy = self._area.center().y()
        for k, name in enumerate(names):
            top = []
            bot = []
            for i, t in enumerate(times):
                base_cum = sum(matrix.get((names[j], t), 0.0) for j in range(k))
                v = matrix.get((name, t), 0.0)
                y0 = cy - totals[i] * scale / 2 + base_cum * scale
                y1 = y0 + v * scale
                top.append(QPointF(xs[i], y0))
                bot.append(QPointF(xs[i], y1))
            self._streams.append({"name": name, "top": top, "bot": bot,
                                  "color_idx": k})

    # -- 绘制 -------------------------------------------------------------
    def paint(self, p: QPainter, anim_t: float) -> None:
        if not self._streams:
            return
        p.save()
        # 覆盖兜底 grid 轴线背景
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(T("color.bg.base")))
        p.drawRect(QRectF(self._area.left() - 24, self._area.top() - 20,
                          self._area.width() + 48, self._area.height() + 50))
        palette = self.chart.palette()
        grow = max(0.0, min(1.0, anim_t))
        for s in self._streams:
            color = QColor(palette[s["color_idx"] % len(palette)])
            top = []
            bot = []
            for a, b in zip(s["top"], s["bot"]):
                mid = (a.y() + b.y()) / 2
                top.append(QPointF(a.x(), mid + (a.y() - mid) * grow))
                bot.append(QPointF(b.x(), mid + (b.y() - mid) * grow))
            if len(top) >= 2:
                path = _smooth_path(top, 0.5)
                bottom_path = _smooth_path(bot, 0.5)
                # 反向拼接下缘
                rev = QPainterPath()
                elems = [bottom_path.elementAt(i)
                         for i in range(bottom_path.elementCount())]
                rev.moveTo(elems[-1].x, elems[-1].y)
                i = len(elems) - 1
                while i >= 3:  # 贝塞尔段逆放（控制点交换）
                    rev.cubicTo(QPointF(elems[i - 1].x, elems[i - 1].y),
                                QPointF(elems[i - 2].x, elems[i - 2].y),
                                QPointF(elems[i - 3].x, elems[i - 3].y))
                    i -= 3
                path.connectPath(rev)
                path.closeSubpath()
            else:
                path = QPainterPath()
            p.setPen(QPen(_with_alpha(color, 200), 1))
            p.setBrush(_with_alpha(color, 150))
            if not path.isEmpty():
                p.drawPath(path)
        # 底部时间轴标签（约 5 个均布）
        n = len(self._times)
        font = chart_font(T("font.xs"))
        p.setFont(font)
        fm = QFontMetricsF(font)
        p.setPen(QColor(T("color.text.secondary")))
        tick_n = min(5, n)
        for k in range(tick_n):
            i = round(k * (n - 1) / max(1, tick_n - 1))
            x = self._area.left() + self._area.width() * (i + 0.5) / n
            p.drawText(QRectF(x - 60, self._area.bottom() + 8, 120, fm.height()),
                       Qt.AlignHCenter | Qt.AlignTop, self._times[i])
        p.restore()

    # -- 交互 -------------------------------------------------------------
    def hit_test(self, pos: QPointF):
        if not self._streams or not self._times:
            return None
        n = len(self._times)
        # 最近时间列
        best_i = None
        best_dx = 1e9
        for i in range(n):
            x = self._area.left() + self._area.width() * (i + 0.5) / n
            if abs(pos.x() - x) < best_dx:
                best_dx = abs(pos.x() - x)
                best_i = i
        if best_i is None or best_dx > self._area.width() / n:
            return None
        for s in self._streams:
            y0 = s["top"][best_i].y()
            y1 = s["bot"][best_i].y()
            if min(y0, y1) - 2 <= pos.y() <= max(y0, y1) + 2 and y1 > y0:
                return {"name": s["name"],
                        "value": self._matrix.get((s["name"],
                                                   self._times[best_i]), 0.0),
                        "series": self.name,
                        "x": self._times[best_i]}
        return None


# ---------------------------------------------------------------------------
# 注册（line 完整版覆盖 core 自检版：同名后注册覆盖先注册）
# ---------------------------------------------------------------------------

register_series("bar", BarSeriesRenderer)
register_series("pictorialBar", PictorialBarSeriesRenderer)
register_series("line", LineSeriesRenderer)
register_series("scatter", ScatterSeriesRenderer)
register_series("effectScatter", EffectScatterSeriesRenderer)
register_series("candlestick", CandlestickSeriesRenderer)
register_series("boxplot", BoxplotSeriesRenderer)
register_series("heatmap", HeatmapSeriesRenderer)
register_series("parallel", ParallelSeriesRenderer)
register_series("themeRiver", ThemeRiverSeriesRenderer)
