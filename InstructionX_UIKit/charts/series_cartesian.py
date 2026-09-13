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
import numbers
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
from ._utils import dist_point_segment, to_float as _to_float, with_alpha
from .axes import CalendarCoord, GridCoord, chart_font, format_value
from .core import SeriesRenderer, parse_data_point, register_series
from .data import NumericBuffer
from .sampling import (
    bucket_count,
    column_aggregate,
    sample_entries,
    sampling_options,
    visible_threshold,
)

try:  # pragma: no cover - 环境相关分支（无 numpy 时走纯 Python 路径）
    import numpy as _np
except Exception:  # noqa: BLE001
    _np = None

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
# 小工具（数值 / 几何工具统一见 charts._utils：_to_float / with_alpha /
# dist_point_segment，语义以过滤 NaN/Inf 版为准）
# ---------------------------------------------------------------------------

#: 历史别名（统一实现见 charts._utils.with_alpha）
_with_alpha = with_alpha


def _lerp(a, b, t):
    return a + (b - a) * t


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
    """点 pos 到线段 a-b 的距离（统一语义见 charts._utils）。"""
    return dist_point_segment(pos, a, b)


def _datum_list(item):
    """取数据项的数值列表：[...] 或 {"value": [...]} → list[float]|None。"""
    v = item.get("value") if isinstance(item, dict) else item
    if not isinstance(v, (list, tuple)):
        return None
    out = []
    for x in v:
        f = _to_float(x, None)
        if f is None:
            return None
        out.append(f)
    return out


def _grid_series_opts(chart):
    """当前 option 中落在 grid 坐标系的系列 option 列表。

    内部引用路径：经 ``chart._option_ref()`` 直接读取（无 deepcopy），
    布局每帧调用零拷贝；公共 API ``chart.option()`` 的拷贝语义不变。
    """
    out = []
    for s in chart._option_ref().get("series") or []:
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
    """类别轴标签（x 为类别名或下标；dataZoom 窗口外经全量类别解析）；
    数值轴退回 format_value。"""
    if axis is not None and axis.type == "category" and axis.categories:
        idx = axis.category_index(x)
        if 0 <= idx < len(axis.categories):
            return axis.categories[idx]
        all_cats = getattr(axis, "_all_categories", None) or []
        if 0 <= idx < len(all_cats):
            return all_cats[idx]
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

        # 槽位：grid 内全部 bar 系列按 stack 名 / 自身序号分槽。
        # 自身定位优先用 core 注入的 ``_series_index``（对象语义，未命名 /
        # 内容相同系列不碰撞）；兜底回退字典相等扫描（手工构造路径）。
        slot_keys = []
        series_opts = self.chart._option_ref().get("series") or []
        for idx, s in enumerate(series_opts):
            if not isinstance(s, dict) or str(s.get("type") or "") != "bar":
                continue
            if s.get("coordinateSystem") not in (None, "cartesian2d", "grid"):
                continue
            key = ("stack", str(s.get("stack"))) if s.get("stack") \
                else ("own", idx)
            if key not in slot_keys:
                slot_keys.append(key)
        my_index = getattr(self, "_series_index", None)
        if not isinstance(my_index, int) or not (0 <= my_index < len(series_opts)):
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

        # 堆叠基线：同 stack 且排在我之前的可见 bar 系列按正负分桶累加
        pos_bases, neg_bases = self._stack_bases()
        prev = self.prev_data if isinstance(self.prev_data, list) else None
        radius = self.opt.get("barBorderRadius", 0)
        if isinstance(radius, (list, tuple)):
            radius = max((_to_float(r, 0.0) for r in radius), default=0.0)
        radius = _to_float(radius, 0.0)

        for i, item in enumerate(self.data()):
            x, y = parse_data_point(item, i)
            if y is None:
                continue
            v0 = (pos_bases if y >= 0 else neg_bases).get(i, 0.0)
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
        bw = _to_float(self.opt.get("barWidth"), None)
        if bw is None:
            return max(2.0, slot_w * 0.75)
        if 0 < bw <= 1:
            return max(2.0, slot_w * bw)
        return max(2.0, min(bw, slot_w))

    def _stack_bases(self):
        """同 stack 前序可见 bar 系列的逐点基线 ``(pos, neg)`` 双桶。

        与 ``_grid_value_extent`` 同构：正值 / 负值**分桶**累加（互不抵消），
        负值柱自 0 向下、正值柱自 0 向上，正负同桶不再叠加。
        """
        pos, neg = {}, {}
        stack = self.opt.get("stack")
        if not stack:
            return pos, neg
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
                bucket = pos if y >= 0 else neg
                bucket[i] = bucket.get(i, 0.0) + y
        return pos, neg

    @staticmethod
    def _cat_label(cat_axis, x, i):
        if cat_axis.type == "category" and cat_axis.categories:
            idx = cat_axis.category_index(x)
            if 0 <= idx < len(cat_axis.categories):
                return cat_axis.categories[idx]
            all_cats = getattr(cat_axis, "_all_categories", None) or []
            if 0 <= idx < len(all_cats):
                return all_cats[idx]
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
        idx = self._full_index(index)  # dataZoom 窗口偏移换算
        for bar in self._bars:
            if bar["index"] == idx:
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
        return {}, {}

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

def _can_gpu_vertices(data) -> bool:
    """数据是否为可直传 GPU 的数值序列（抽样判别，覆盖首尾）。

    含字典项 / 嵌套列表 / 非数值的序列不能用「下标作 x、值作 y」的简单形式
    表达，交由采样路径处理。
    """
    if isinstance(data, NumericBuffer):
        return True
    if _np is not None and isinstance(data, _np.ndarray):
        return data.ndim == 1
    if not isinstance(data, (list, tuple)):
        return False
    n = len(data)
    if n == 0:
        return False
    idxs = set(range(min(24, n)))
    step = max(1, n // 16)
    idxs.update(range(0, n, step))
    idxs.update(range(max(0, n - 24), n))
    for i in sorted(idxs):
        v = data[i]
        if v is None:
            continue
        if isinstance(v, numbers.Real) and not isinstance(v, bool):
            continue
        return False
    return True


def _to_data_vertices(data):
    """数值序列 → ``float32 [n,2]`` 数据坐标顶点（x 为下标）。

    含 ``None``（缺值）的序列返回 ``None``：直绘路径不做断点处理，
    交由采样路径按段绘制。
    """
    if _np is None:
        return None
    n = len(data)
    if n < 2:
        return None
    try:
        raw = data.raw if isinstance(data, NumericBuffer) else data
        ys = _np.asarray(raw, dtype=_np.float64)
    except (TypeError, ValueError):
        return None
    if ys.ndim != 1 or ys.size != n:
        return None
    if bool(_np.isnan(ys).any()):
        return None
    out = _np.empty((n, 2), dtype=_np.float32)
    out[:, 0] = _np.arange(n, dtype=_np.float32)
    out[:, 1] = ys.astype(_np.float32)
    return out


def _has_own_x(data) -> bool:
    """数据是否自带 x（``[x, y]`` 结构型序列）。"""
    from .axes import _x_extent
    return _x_extent(data) is not None


def _own_x_extent(data):
    """结构型数据的 x 区间；标量数据返回 ``None``。"""
    from .axes import _x_extent
    return _x_extent(data)


def _pin_endpoints(entries, data, xs):
    """把数据首尾端点并入采样结果，并保持 x 升序。

    ``entries`` 为 ``[(x, y), ...]``；``xs`` 为数值 x 轴下的真实 x 列表，
    为 ``None`` 时按「x 即下标」处理。返回新的列表。
    """
    try:
        n = len(data)
    except TypeError:
        return entries
    if n < 2:
        return entries
    first_y = _to_float(data[0], None)
    last_y = _to_float(data[n - 1], None)
    extra = []
    if first_y is not None:
        extra.append((0 if xs is None else xs[0], first_y))
    if last_y is not None:
        extra.append((n - 1 if xs is None else xs[n - 1], last_y))
    if not extra:
        return entries
    merged = list(entries)
    have = {e[0] for e in merged}
    for e in extra:
        if e[0] not in have:
            merged.append(e)
    merged.sort(key=lambda e: e[0])
    return merged


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
        # GPU 直绘（CHART_SPEC §7.2）：开启时本系列不经 QPainter 绘制，改由
        # GL 视口上传全分辨率顶点并用着色器变换。默认关闭——默认的采样路径
        # 实测已达标（150 万点 5.0 ms / 198 fps），而全分辨率上传有一次性成本。
        self._gpu_direct = bool(opt.get("gpuDirect", False))
        self._gpu_version = None

    # -- GPU 直绘（供 GL 视口调用） ----------------------------------------
    @property
    def gpu_direct(self) -> bool:
        return self._gpu_direct

    def gpu_vertex_data(self):
        """返回 GPU 直绘所需的数据（无需 VBO 时返回 ``None``）。

        ``None`` 的三种情形：未开启直绘、数据形态不适合（非数值序列）、
        数据不足两点。返回 ``{"vertices": float32[n,2], "version": ...}``，
        顶点为**数据坐标**（着色器负责变换，故缩放/平移无需重算 CPU 侧坐标）。

        ``version`` 只由**数据对象身份与长度**派生，**不得**在方法内改写任何
        状态：版本每次调用都变会让 VBO 缓存永远失效、每帧重传（本方法曾被
        写成自增计数器，实测导致「同版本上传被跳过」的断言失败）。
        数据对象由 ``self.opt`` 长期持有，故 ``id`` 在渲染器生命周期内稳定。
        """
        if not self._gpu_direct:
            return None
        data = self.data_view()
        try:
            n = len(data)
        except TypeError:
            return None
        if n < 2 or not _can_gpu_vertices(data):
            return None
        verts = _to_data_vertices(data)
        if verts is None:
            return None
        return {"vertices": verts, "version": (id(data), n)}

    def gpu_transform(self, coord):
        """GPU 直绘的坐标变换参数（数据坐标区间 → 绘图区像素）。

        返回 ``(x0, x1, y0, y1, plot)``；``None`` 表示当前坐标系不支持
        （如 polar/singleAxis 的 x 语义不同）。
        """
        if not self._gpu_direct or coord is None:
            return None
        if not isinstance(coord, GridCoord):
            return None
        x_axis = getattr(coord, "x_axis", None)
        y_axis = getattr(coord, "y_axis", None)
        if x_axis is None or y_axis is None:
            return None
        data = self.data_view()
        n = len(data)
        if n < 2:
            return None
        if str(getattr(x_axis, "type", "")) == "category" or not _has_own_x(data):
            x0, x1 = 0.0, float(n - 1)
        else:
            xext = _own_x_extent(data)
            if xext is None:
                return None
            x0, x1 = xext
        y0, y1 = float(y_axis.vmin), float(y_axis.vmax)
        if x1 <= x0 or y1 <= y0:
            return None
        return (x0, x1, y0, y1, coord.plot)

    def _line_viewport_px(self, coord, rect):
        """采样阈值所用的视口像素宽（优先绘图区宽度）。

        注意：``QRectF.width`` 是**方法**，必须取调用结果而非方法对象——
        直接 ``getattr(...)`` 拿到的是绑定方法，真值判断恒为真，随后在
        ``float()`` 处抛异常并被上游的容错分支吞掉，表现为「采样静默失效、
        全量点照旧渲染」。
        """
        if rect is None:
            return None
        plot_rect = getattr(coord, "plot", None)
        w = None
        if plot_rect is not None:
            getter = getattr(plot_rect, "width", None)
            if callable(getter):
                w = getter()
            elif isinstance(getter, (int, float)):
                w = getter
        if not isinstance(w, (int, float)) or w <= 0:
            w = rect.width() if callable(getattr(rect, "width", None)) \
                else rect.width
        return w if isinstance(w, (int, float)) and w > 0 else None

    def _auto_x_limit(self) -> int:
        """数值 x 轴的 x 提取扫描上限（避免百万级下标逐点解析开销）。"""
        return 200_000

    def _line_x_values(self, coord, single):
        """数值 x 轴下各数据点的真实 x 列表；category 轴返回 ``None``。

        这一步是**必需的**：category 轴与 singleAxis 下 x 就是数据下标，
        直接用下标采样即可；但**数值 x 轴下 x 是真实数据坐标**，若仍拿下标
        当 x 传给采样器，0..n-1 会被当成 x 坐标，曲线会缩到坐标轴左端的一小
        段里（实测首点 x 由 48 变成 644688，只覆盖约 4% 图宽）。

        性能：数值序列（``NumericBuffer`` / ``ndarray``）没有任何元素携带
        自己的 x，x 即下标，于是直接用 numpy 生成——逐点调 ``parse_data_point``
        解析百万级元素要 60 ms 以上，而这里只要微秒级。
        """
        if single:
            return None
        x_axis = getattr(coord, "x_axis", None)
        if getattr(x_axis, "type", "") != "value":
            return None
        data = self.data_view()
        n = len(data)
        if n == 0:
            return None
        # 快路径：数值序列的 x 恒为下标（Python list 的 int 项同理）
        if isinstance(data, NumericBuffer) or (
                _np is not None and isinstance(data, _np.ndarray)):
            if _np is not None:
                return _np.arange(n, dtype=_np.float64)
            return list(range(n))
        lim = min(n, self._auto_x_limit())
        out = []
        for i in range(lim):
            x, _y = parse_data_point(data[i], i)
            out.append(x if isinstance(x, (int, float))
                       and not isinstance(x, bool) else i)
        if lim < n:
            # 超出扫描上限：其余点按下标处理（极端大数据下的保守退化）
            out.extend(range(lim, n))
        return out

    def _sample_line(self, coord, single, rect):
        """在渲染器内完成采样，显式区分 category / 数值 x 两种语义。

        返回 ``[(x, y), ...]`` 或 ``None``（未采样）。
        """
        opts = sampling_options(self.opt)
        if not opts.enabled:
            return None
        viewport_px = self._line_viewport_px(coord, rect)
        if not viewport_px:
            return None
        n = len(self.data_view())
        threshold = visible_threshold(viewport_px, opts.safety)
        if threshold < 2 or n <= threshold:
            return None
        buckets = bucket_count(viewport_px)
        xs = self._line_x_values(coord, single)
        if xs is None:
            entries, sampled = sample_entries(self.data_view(), threshold,
                                              buckets)
        else:
            entries, sampled = sample_entries(self.data_view(), threshold,
                                              buckets, x_values=xs)
        if not sampled or not entries:
            return None
        # 强制保留数据首尾端点：逐桶取极值时，末尾不足一桶的零头点可能完全
        # 落不进任何桶的 min/max（实测 150 万点下首点 x=0 与末点被丢掉），
        # 曲线两端会凭空少一截。折线采样必须钉住端点。
        return _pin_endpoints(entries, self.data_view(), xs)

    # -- 布局 -------------------------------------------------------------
    def layout(self, rect: QRectF) -> None:
        coord = self.chart.coord_for(self.opt)
        self._prev_points = list(self._points)
        self._points = []
        self._entries = []
        if coord is None:
            return
        single = getattr(coord, "kind", "") == "singleAxis"
        # 运行时降采样（§8.2 保真承诺）：可见点数超过视口像素量级时才启用。
        # 阈值用**绘图区像素宽**（GridCoord.plot.width）而非坐标区宽：两者
        # 相差左右边距（实测 480 的坐标区里绘图区只有 408），用坐标区宽会
        # 多产出约 18% 的点，既浪费也削弱「逐像素列一桶」的对齐关系。
        sampled = self._sample_line(coord, single, rect)
        if sampled is not None:
            for x, y in sampled:
                self._entries.append((x, y))
                try:
                    self._points.append(coord.map_point(y) if single
                                        else coord.map_point(x, y))
                except Exception:
                    self._points.append(None)
            return
        for i, item in enumerate(self.data_view()):
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
        idx = self._full_index(index)  # dataZoom 窗口偏移换算
        if not isinstance(idx, int) or not (0 <= idx < len(self._entries)):
            return None
        x, y = self._entries[idx]
        if y is None:
            return None
        pos = self._points[idx] if idx < len(self._points) else None
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
        #: 是否走了 large 像素桶聚合（聚合后每桶一个图元，语义见 sampling.py）
        self._aggregated = False

    def _large_enabled(self) -> bool:
        """是否启用 large 像素桶聚合。

        ``large: true`` 显式开启；``large: "auto"``（或未给出但 sampling
        开启）时按点数与视口宽度自动判定。判定统一走「保真承诺」的阈值：
        可见点数未超视口像素量级 → 不聚合。
        """
        raw = self.opt.get("large", "auto")
        if raw is False:
            return False
        opts = sampling_options(self.opt)
        return bool(raw) or opts.enabled

    def _large_x_values(self, coord, single):
        """``large`` 聚合所需的 x 序列；无需显式 x 时返回 ``None``。

        标量数据（``NumericBuffer`` / 数值列表）在数值 x 轴下的 x 即**下标**。
        若误用「桶中点下标」当 x，下标量级（0..n-1）会远超实际 x 轴范围
        （标量数据的 x 轴范围是 [0,1]），点会被全部映射到坐标区之外——
        实测百万散点整幅**空白**。故此处与折线同样按下标取值。
        """
        if single:
            return None
        data = self.data_view()
        n = len(data)
        if n == 0:
            return None
        if isinstance(data, NumericBuffer) or (
                _np is not None and isinstance(data, _np.ndarray)):
            if _np is not None:
                return _np.arange(n, dtype=_np.float64)
            return list(range(n))
        # 结构型数据（[x, y] 对）：取各点的真实 x
        out = []
        for i in range(n):
            x, _y = parse_data_point(data[i], i)
            out.append(x if isinstance(x, (int, float))
                       and not isinstance(x, bool) else i)
        return out

    def _large_dots(self, coord, rect):
        """按像素桶聚合散点，返回 ``[dot, ...]`` 或 ``None``（未聚合）。"""
        if rect is None:
            return None
        plot_rect = getattr(coord, "plot", None)
        px = None
        getter = getattr(plot_rect, "width", None)
        if callable(getter):
            px = getter()
        if not isinstance(px, (int, float)) or px <= 0:
            px = rect.width() if callable(getattr(rect, "width", None)) \
                else rect.width
        if not isinstance(px, (int, float)) or px <= 0:
            return None
        opts = sampling_options(self.opt)
        data = self.data_view()
        n = len(data)
        threshold = visible_threshold(px, opts.safety)
        if threshold < 2 or n <= threshold:
            return None
        single = getattr(coord, "kind", "") == "singleAxis"
        xs = self._large_x_values(coord, single)
        buckets, done = column_aggregate(data, bucket_count(px),
                                         x_values=xs)
        if not done or not buckets:
            return None
        dots = []
        for b in buckets:
            try:
                pt = coord.map_point(b["value"]) if single \
                    else coord.map_point(b["x"], b["value"])
            except Exception:
                continue
            dots.append({"pt": pt, "r": 3.0, "value": b["value"],
                         "index": int(b["x"]) if not isinstance(b["x"], float)
                         or b["x"].is_integer() else -1,
                         "x": b["x"], "count": b["count"],
                         "min": b["min"], "max": b["max"]})
        return dots or None

    # -- 布局 -------------------------------------------------------------
    def _third_dim(self, item):
        v = item.get("value") if isinstance(item, dict) else item
        if isinstance(v, (list, tuple)) and len(v) >= 3:
            return _to_float(v[2], None)
        return None

    def layout(self, rect: QRectF) -> None:
        self._dots = []
        self._aggregated = False
        coord = self.chart.coord_for(self.opt)
        if coord is None:
            return
        single = getattr(coord, "kind", "") == "singleAxis"
        fixed = _to_float(self.opt.get("symbolSize"), None)
        # large 模式：百万级散点逐点绘制既不可行也无意义（远超屏幕可分辨
        # 能力），改为按像素桶聚合，每桶一个图元。阈值与折线同源：可见点数
        # 未超视口像素量级时不聚合。
        if self._large_enabled() and not single:
            agg = self._large_dots(coord, rect)
            if agg is not None:
                self._dots = agg
                self._aggregated = True
                return
        thirds = [self._third_dim(it) for it in self.data_view()]
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
        if self._aggregated:
            # 聚合模式：每像素桶一个方块，桶内点数越多越不透明——这是密度
            # 语义，与逐点绘制大小无关；尺寸取像素级 2px 保证列间不重叠。
            p.setPen(Qt.NoPen)
            scale = max(0.0, anim_t)
            for d in self._dots:
                # 桶内点数越多越不透明（密度语义），上限 235 留出叠加余地
                alpha = 90 + min(145, 12 * int(math.log2(max(1, d["count"]))))
                p.setBrush(_with_alpha(color, alpha))
                pt = d["pt"]
                side = 2.0 * scale
                if side <= 0:
                    continue
                p.drawRect(QRectF(pt.x() - side / 2, pt.y() - side / 2,
                                  side, side))
            p.restore()
            return
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
        idx = self._full_index(index)  # dataZoom 窗口偏移换算
        for d in self._dots:
            if d["index"] == idx:
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
    自动停止并 deleteLater，不泄漏。仅系列可见时推进（隐藏后定时器暂停、
    重新显示时经 ``_on_visible_changed`` 恢复，不空转）。
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
            try:
                alive = self_obj in self_obj.chart.series_renderers
            except RuntimeError:
                alive = False  # chart 已销毁
            if not alive:
                t.stop()
                t.deleteLater()
                return
            if not self_obj.visible:
                if t.isActive():
                    t.stop()  # 隐藏不空转；重新显示经 _on_visible_changed 恢复
                return
            if not t.isActive():
                t.start()
            self_obj._tick()

        timer.timeout.connect(_on_timeout)
        timer.start()
        self._timer = timer

    def _tick(self):
        """推进涟漪相位并请求重绘（测试可手动调用）。"""
        self._phase = (self._phase + self._TICK_MS / (self._period * 1000.0)) % 1.0
        self.chart.update()

    def _on_visible_changed(self):
        """显隐变化钩子（core.set_series_visible 调用）：显示恢复时重启定时器。"""
        if self.visible and self._timer is not None and not self._timer.isActive():
            self._timer.start()

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
        w = _to_float(self.opt.get("barWidth"), None)
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
        idx = self._full_index(index)  # dataZoom 窗口偏移换算
        for it in self._items:
            if it["index"] == idx:
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
        w = _to_float(self.opt.get("barWidth"), None)
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
        idx = self._full_index(index)  # dataZoom 窗口偏移换算
        for it in self._items:
            if it["index"] == idx:
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
    option 含 ``visualMap``（顶层，经 chart 内部 option 引用读取）时按
    ``visualMap.min/max`` 与 ``visualMap.inRange.colors`` 映射。
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
                val = _to_float(v[1], None)
                if val is not None:
                    out.append((v[0], None, val))
            else:
                if len(v) < 3:
                    continue
                val = _to_float(v[2], None)
                if val is not None:
                    out.append((v[0], v[1], val))
        return out

    def _colors_and_range(self, items):
        """→ (colors, vmin, vmax)：visualMap 优先，否则默认色带 + 数据范围。"""
        vm = self.chart._option_ref().get("visualMap")
        colors = None
        vmin = vmax = None
        if isinstance(vm, dict):
            in_range = vm.get("inRange") or {}
            if isinstance(in_range.get("colors"), list) \
                    and in_range["colors"]:
                colors = in_range["colors"]
            vmin = _to_float(vm.get("min"), None)
            vmax = _to_float(vm.get("max"), None)
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
        pa = self.chart._option_ref().get("parallelAxis")
        dims = []
        if isinstance(pa, list) and pa:
            for d in pa:
                if isinstance(d, dict):
                    dims.append({"name": str(d.get("name") or f"dim{len(dims)}"),
                                 "min": _to_float(d.get("min"), None),
                                 "max": _to_float(d.get("max"), None)})
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
        rows = [r for r in rows if all(_to_float(x, None) is not None for x in r)]
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
            t, val, name = v[0], _to_float(v[1], None), str(v[2])
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
