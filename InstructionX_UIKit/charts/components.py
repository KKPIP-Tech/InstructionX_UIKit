# -*- coding: utf-8 -*-
"""图表标注组件与 map 系列（CHART_SPEC §5 C4）。

本模块提供：

- ``MarkPointComponent``（option_key="markPoint"，系列级）：
  最大 / 最小值或指定坐标的圆点 + 值文本标注。
- ``MarkLineComponent``（option_key="markLine"，系列级）：
  平均值 / 最大 / 最小或指定 yAxis / xAxis 的虚线标线 + 端部标签。
- ``MarkAreaComponent``（option_key="markArea"，系列级）：
  xAxis / yAxis 区间对的半透明标域（T("color.primary") 低透明度填充）。
- ``GraphicComponent``（option_key="graphic"，顶层）：
  绝对定位图形元素（circle / rect / text / line）。
- ``MapSeriesRenderer``（经 ``register_series("map", ...)`` 注册）：
  简化地图系列，区域多边形着色 + 名称标签 + 命中检测。

内置演示地图 ``DEMO_MAP`` 为 7 个大区块的**示意轮廓**，坐标为自定的
平面示意坐标（非真实地理数据，不表示任何真实行政区划边界），仅用于
功能演示；真实使用请经 ``option["geo"]["regions"]`` 传入自定义多边形。
所有配色经 T() 实时读取，主题切换后重绘即生效。
"""

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFontMetricsF, QPainter, QPainterPath, QPen, QPolygonF

from ..theme import T
from .axes import GridCoord, chart_font, format_value
from .core import (
    SeriesRenderer,
    parse_data_point,
    register_component,
    register_series,
)

__all__ = [
    "MarkPointComponent",
    "MarkLineComponent",
    "MarkAreaComponent",
    "GraphicComponent",
    "MapSeriesRenderer",
    "DEMO_MAP",
    "lerp_color",
]


def lerp_color(c1, c2, t: float) -> QColor:
    """两种颜色按 t ∈ [0,1] 线性插值（RGB 空间）。"""
    t = min(max(float(t), 0.0), 1.0)
    a, b = QColor(c1), QColor(c2)
    return QColor(
        int(a.red() + (b.red() - a.red()) * t),
        int(a.green() + (b.green() - a.green()) * t),
        int(a.blue() + (b.blue() - a.blue()) * t),
    )


def _to_float(v, default=None):
    """宽松数值转换，失败返回 default。"""
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


# ---------------------------------------------------------------------------
# 系列级标注组件基类
# ---------------------------------------------------------------------------

class _SeriesMarkBase:
    """markPoint / markLine / markArea 的公共基类。

    core 重建时对每个含同名键的 series 字典实例化一次，并注入
    ``comp.series_opt``（指向所属系列 option 字典）。本基类负责反查
    对应的系列渲染器与坐标系。构造时 ``series_opt`` 尚未注入，相关解析
    一律推迟到 layout / paint。
    """

    option_key = ""

    def __init__(self, chart, opt):
        self.chart = chart
        self.opt = dict(opt or {})
        #: 所属系列 option（core 注入；顶层实例化为 None）
        self.series_opt = None

    # -- 反查 ------------------------------------------------------------
    def _renderer(self):
        """所属系列的渲染器（找不到返回 None）。"""
        chart = self.chart
        s = getattr(self, "series_opt", None)
        if s is None:
            return None
        series_opts = getattr(chart, "_option", {}).get("series") or []
        idx = None
        for i, d in enumerate(series_opts):
            if d is s:
                idx = i
                break
        name = str(s.get("name") or (f"series{idx}" if idx is not None else ""))
        for r in chart.series_renderers:
            if r.name == name:
                return r
        for r in chart.series_renderers:  # 兜底：字典相等匹配
            if r.opt == s:
                return r
        return None

    def _coord(self):
        """所属系列的坐标系（默认主坐标系）。"""
        s = getattr(self, "series_opt", None) or {}
        return self.chart.coord_for(s)

    def _points(self):
        """系列数据解析为 ``[(x, y)]``（跳过 None 值）。"""
        r = self._renderer()
        if r is None:
            return []
        out = []
        for i, item in enumerate(r.data()):
            x, y = parse_data_point(item, i)
            if y is not None:
                out.append((x, y))
        return out

    def _color(self) -> QColor:
        """标注主色：跟随系列色（无系列时取 primary）。"""
        r = self._renderer()
        if r is not None:
            return r.color()
        return QColor(T("color.primary"))

    def _visible(self) -> bool:
        r = self._renderer()
        return r is not None and r.visible


# ---------------------------------------------------------------------------
# markPoint
# ---------------------------------------------------------------------------

class MarkPointComponent(_SeriesMarkBase):
    """数据点标注：最大 / 最小值或指定坐标，圆点（小旗式插针）+ 值文本。

    option（系列级）::

        "markPoint": {"data": [{"type": "max"|"min"},
                               {"coord": [x, y], "value": v, "name": "..."}]}

    标注样式：系列色实心圆点 + 向上短引线 + 值文本（font.xs）。
    """

    option_key = "markPoint"

    def __init__(self, chart, opt):
        super().__init__(chart, opt)
        self._marks = []  # [{"pos": QPointF, "text": str, "x": x, "y": y}]

    def layout(self, rect: QRectF) -> None:
        self._marks = []
        if not self._visible():
            return
        coord = self._coord()
        if coord is None:
            return
        pts = self._points()
        data = self.opt.get("data") or []
        if not isinstance(data, list):
            return
        for item in data:
            if not isinstance(item, dict):
                continue
            x = y = None
            typ = item.get("type")
            if typ in ("max", "min") and pts:
                key = (lambda p: p[1])
                x, y = (max if typ == "max" else min)(pts, key=key)
            elif isinstance(item.get("coord"), (list, tuple)) \
                    and len(item["coord"]) >= 2:
                x = item["coord"][0]
                y = _to_float(item["coord"][1])
                if y is None:
                    y = _to_float(item.get("value"))
            if y is None:
                continue
            try:
                pos = coord.map_point(x, y)
            except Exception:
                continue
            label = item.get("name")
            if label is None:
                label = format_value(_to_float(item.get("value"), y))
            self._marks.append({"pos": pos, "text": str(label), "x": x, "y": y})

    def paint(self, p: QPainter, anim_t: float = 1.0) -> None:
        if not self._marks or not self._visible():
            return
        p.save()
        color = self._color()
        font = chart_font(T("font.xs"))
        p.setFont(font)
        fm = QFontMetricsF(font)
        for m in self._marks:
            pos = m["pos"]
            # 圆点（小旗式：实心圆 + 向上引线 + 值文本）
            p.setPen(QPen(QColor(T("color.bg.elevated")), 1.4))
            p.setBrush(color)
            p.drawEllipse(pos, 4.2, 4.2)
            top = QPointF(pos.x(), pos.y() - 14)
            p.setPen(QPen(color, 1.4))
            p.drawLine(QPointF(pos.x(), pos.y() - 4.5), top)
            p.setPen(QColor(T("color.text.primary")))
            tw = fm.horizontalAdvance(m["text"])
            p.drawText(QRectF(pos.x() - tw / 2 - 2, top.y() - fm.height() - 2,
                              tw + 4, fm.height()),
                       Qt.AlignHCenter | Qt.AlignVCenter, m["text"])
        p.restore()

    def hit_test(self, pos: QPointF):
        for m in self._marks:
            mp = m["pos"]
            if (mp.x() - pos.x()) ** 2 + (mp.y() - pos.y()) ** 2 <= 64:
                r = self._renderer()
                return {"name": m["text"], "value": m["y"],
                        "series": r.name if r is not None else "markPoint"}
        return None


# ---------------------------------------------------------------------------
# markLine
# ---------------------------------------------------------------------------

_TYPE_LABELS = {"average": "平均值", "max": "最大值", "min": "最小值"}


class MarkLineComponent(_SeriesMarkBase):
    """参考标线：平均值 / 最大 / 最小或指定 yAxis / xAxis，虚线 + 端部标签。

    option（系列级）::

        "markLine": {"data": [{"type": "average"|"max"|"min", "name": "..."},
                              {"yAxis": v}, {"xAxis": v}]}

    仅作用于 GridCoord 直角坐标（其他坐标系静默跳过）。
    """

    option_key = "markLine"

    def __init__(self, chart, opt):
        super().__init__(chart, opt)
        # [{"orient": "h"|"v", "value": ..., "text": str}]
        self._lines = []

    def layout(self, rect: QRectF) -> None:
        self._lines = []
        if not self._visible():
            return
        coord = self._coord()
        if not isinstance(coord, GridCoord):
            return
        pts = self._points()
        data = self.opt.get("data") or []
        if not isinstance(data, list):
            return
        for item in data:
            if not isinstance(item, dict):
                continue
            orient = value = None
            default_label = ""
            typ = item.get("type")
            if typ in _TYPE_LABELS and pts:
                vals = [y for _, y in pts]
                if typ == "average":
                    value = sum(vals) / len(vals)
                elif typ == "max":
                    value = max(vals)
                else:
                    value = min(vals)
                orient = "h"
                default_label = _TYPE_LABELS[typ]
            elif "yAxis" in item:
                value = _to_float(item.get("yAxis"))
                orient = "h"
            elif "xAxis" in item:
                value = item.get("xAxis")
                orient = "v"
            if orient is None or value is None:
                continue
            name = str(item.get("name") or default_label)
            vtxt = format_value(value) if isinstance(value, (int, float)) \
                else str(value)
            text = f"{name} {vtxt}" if name else vtxt
            self._lines.append({"orient": orient, "value": value, "text": text})

    def paint(self, p: QPainter, anim_t: float = 1.0) -> None:
        if not self._lines or not self._visible():
            return
        coord = self._coord()
        if not isinstance(coord, GridCoord):
            return
        plot = coord.plot
        p.save()
        color = self._color()
        pen = QPen(color, 1.4)
        pen.setStyle(Qt.DashLine)
        font = chart_font(T("font.xs"))
        p.setFont(font)
        fm = QFontMetricsF(font)
        for ln in self._lines:
            if ln["orient"] == "h":
                py = coord.y_axis.map(_to_float(ln["value"], 0.0),
                                      plot.bottom(), plot.top())
                p.setPen(pen)
                p.drawLine(QPointF(plot.left(), py), QPointF(plot.right(), py))
                p.setPen(color)
                p.drawText(QRectF(plot.right() - 120, py - fm.height() - 3,
                                  118, fm.height()),
                           Qt.AlignRight | Qt.AlignVCenter, ln["text"])
            else:
                px = coord.x_axis.map(ln["value"], plot.left(), plot.right())
                p.setPen(pen)
                p.drawLine(QPointF(px, plot.top()), QPointF(px, plot.bottom()))
                p.setPen(color)
                p.drawText(QRectF(px + 4, plot.top() + 3, 120, fm.height()),
                           Qt.AlignLeft | Qt.AlignVCenter, ln["text"])
        p.restore()

    def hit_test(self, pos: QPointF):
        coord = self._coord()
        if not isinstance(coord, GridCoord):
            return None
        plot = coord.plot
        for ln in self._lines:
            if ln["orient"] == "h":
                py = coord.y_axis.map(_to_float(ln["value"], 0.0),
                                      plot.bottom(), plot.top())
                if abs(pos.y() - py) <= 4 and plot.left() <= pos.x() <= plot.right():
                    r = self._renderer()
                    return {"name": ln["text"], "value": ln["value"],
                            "series": r.name if r is not None else "markLine"}
            else:
                px = coord.x_axis.map(ln["value"], plot.left(), plot.right())
                if abs(pos.x() - px) <= 4 and plot.top() <= pos.y() <= plot.bottom():
                    r = self._renderer()
                    return {"name": ln["text"], "value": ln["value"],
                            "series": r.name if r is not None else "markLine"}
        return None


# ---------------------------------------------------------------------------
# markArea
# ---------------------------------------------------------------------------

class MarkAreaComponent(_SeriesMarkBase):
    """区间标域：xAxis / yAxis 值对的半透明填充区域。

    option（系列级）::

        "markArea": {"data": [[{"xAxis": a}, {"xAxis": b}],
                              [{"yAxis": a}, {"yAxis": b}]]}

    填充取 T("color.primary") 低透明度；category 轴向两侧各扩半个 band。
    """

    option_key = "markArea"

    def __init__(self, chart, opt):
        super().__init__(chart, opt)
        self._areas = []  # [QRectF]

    def layout(self, rect: QRectF) -> None:
        self._areas = []
        if not self._visible():
            return
        coord = self._coord()
        if not isinstance(coord, GridCoord):
            return
        plot = coord.plot
        data = self.opt.get("data") or []
        if not isinstance(data, list):
            return
        for pair in data:
            if not isinstance(pair, (list, tuple)) or len(pair) < 2:
                continue
            a, b = pair[0], pair[1]
            if not isinstance(a, dict) or not isinstance(b, dict):
                continue
            area = None
            if "xAxis" in a and "xAxis" in b:
                x0 = coord.x_axis.map(a["xAxis"], plot.left(), plot.right())
                x1 = coord.x_axis.map(b["xAxis"], plot.left(), plot.right())
                if coord.x_axis.type == "category":
                    half = coord.x_axis.band_width(plot.left(), plot.right()) / 2
                    x0, x1 = x0 - half, x1 + half
                area = QRectF(min(x0, x1), plot.top(),
                              abs(x1 - x0), plot.height())
            elif "yAxis" in a and "yAxis" in b:
                y0 = coord.y_axis.map(_to_float(a["yAxis"], 0.0),
                                      plot.bottom(), plot.top())
                y1 = coord.y_axis.map(_to_float(b["yAxis"], 0.0),
                                      plot.bottom(), plot.top())
                area = QRectF(plot.left(), min(y0, y1),
                              plot.width(), abs(y1 - y0))
            if area is not None:
                self._areas.append(area.intersected(plot))

    def paint(self, p: QPainter, anim_t: float = 1.0) -> None:
        if not self._areas or not self._visible():
            return
        p.save()
        fill = QColor(T("color.primary"))
        fill.setAlpha(28)
        p.setPen(Qt.NoPen)
        p.setBrush(fill)
        for area in self._areas:
            p.drawRect(area)
        p.restore()

    def hit_test(self, pos: QPointF):
        for area in self._areas:
            if area.contains(pos):
                r = self._renderer()
                return {"name": "markArea", "value": None,
                        "series": r.name if r is not None else "markArea"}
        return None


# ---------------------------------------------------------------------------
# graphic（绝对定位图形元素）
# ---------------------------------------------------------------------------

class GraphicComponent:
    """绝对定位图形元素：circle / rect / text / line。

    option（顶层）::

        "graphic": [
            {"type": "circle", "left": 40, "top": 40,
             "shape": {"cx": 0, "cy": 0, "r": 20},
             "style": {"fill": "#3F5E8C", "stroke": "#..."}},
            {"type": "rect", "left": "center", "top": 20,
             "shape": {"x": -40, "y": 0, "width": 80, "height": 24, "r": 4},
             "style": {"fill": "#..."}},
            {"type": "text", "left": 12, "top": 12,
             "style": {"text": "水印", "fill": "#98A0AC", "fontSize": 14}},
            {"type": "line", "left": 0, "top": 0,
             "shape": {"x1": 0, "y1": 0, "x2": 100, "y2": 40},
             "style": {"stroke": "#...", "lineWidth": 2}},
        ]

    ``left`` / ``top`` 为相对图表内容区的像素偏移，或 ``"center"``
    （水平 / 垂直居中锚点）；shape 内坐标相对该锚点。
    """

    option_key = "graphic"

    def __init__(self, chart, opt):
        self.chart = chart
        if isinstance(opt, dict):
            opt = [opt]
        self.elements = [e for e in (opt or []) if isinstance(e, dict)]
        self.rect = QRectF()

    def layout(self, rect: QRectF) -> None:
        self.rect = QRectF(rect)

    def _anchor(self, el: dict) -> QPointF:
        left = el.get("left", 0)
        top = el.get("top", 0)
        if str(left) == "center":
            x = self.rect.center().x()
        else:
            x = self.rect.left() + (_to_float(left, 0.0) or 0.0)
        if str(top) == "center":
            y = self.rect.center().y()
        else:
            y = self.rect.top() + (_to_float(top, 0.0) or 0.0)
        return QPointF(x, y)

    def paint(self, p: QPainter, anim_t: float = 1.0) -> None:
        if not self.elements:
            return
        p.save()
        for el in self.elements:
            typ = str(el.get("type") or "")
            shape = el.get("shape") or {}
            style = el.get("style") or {}
            base = self._anchor(el)
            try:
                self._paint_element(p, typ, shape, style, base)
            except Exception:
                continue  # 单元素异常不影响其他元素
        p.restore()

    def _paint_element(self, p: QPainter, typ: str, shape: dict,
                       style: dict, base: QPointF) -> None:
        if typ == "circle":
            cx = base.x() + (_to_float(shape.get("cx"), 0.0) or 0.0)
            cy = base.y() + (_to_float(shape.get("cy"), 0.0) or 0.0)
            r = _to_float(shape.get("r"), 20.0) or 20.0
            self._apply_brush(p, style, default_fill=T("color.primary"))
            p.drawEllipse(QPointF(cx, cy), r, r)
        elif typ == "rect":
            x = base.x() + (_to_float(shape.get("x"), 0.0) or 0.0)
            y = base.y() + (_to_float(shape.get("y"), 0.0) or 0.0)
            w = _to_float(shape.get("width"), 40.0) or 40.0
            h = _to_float(shape.get("height"), 24.0) or 24.0
            radius = _to_float(shape.get("r"), 0.0) or 0.0
            self._apply_brush(p, style, default_fill=T("color.primary.subtle"))
            if radius > 0:
                p.drawRoundedRect(QRectF(x, y, w, h), radius, radius)
            else:
                p.drawRect(QRectF(x, y, w, h))
        elif typ == "text":
            text = str(style.get("text") or "")
            if not text:
                return
            size = int(_to_float(style.get("fontSize"), T("font.xs")) or T("font.xs"))
            p.setFont(chart_font(size))
            p.setPen(QColor(style.get("fill") or T("color.text.primary")))
            p.setBrush(Qt.NoBrush)
            fm = QFontMetricsF(p.font())
            x = base.x() + (_to_float(shape.get("x"), 0.0) or 0.0)
            y = base.y() + (_to_float(shape.get("y"), 0.0) or 0.0)
            p.drawText(QRectF(x, y, fm.horizontalAdvance(text) + 4, fm.height() + 2),
                       Qt.AlignLeft | Qt.AlignTop, text)
        elif typ == "line":
            x1 = base.x() + (_to_float(shape.get("x1"), 0.0) or 0.0)
            y1 = base.y() + (_to_float(shape.get("y1"), 0.0) or 0.0)
            x2 = base.x() + (_to_float(shape.get("x2"), 40.0) or 40.0)
            y2 = base.y() + (_to_float(shape.get("y2"), 0.0) or 0.0)
            stroke = QColor(style.get("stroke") or T("color.border.strong"))
            width = _to_float(style.get("lineWidth"), 2.0) or 2.0
            p.setPen(QPen(stroke, width))
            p.setBrush(Qt.NoBrush)
            p.drawLine(QPointF(x1, y1), QPointF(x2, y2))

    @staticmethod
    def _apply_brush(p: QPainter, style: dict, default_fill) -> None:
        fill = style.get("fill")
        stroke = style.get("stroke")
        if fill == "none" or fill is False:
            p.setBrush(Qt.NoBrush)
        else:
            p.setBrush(QColor(fill or default_fill))
        if stroke:
            p.setPen(QPen(QColor(stroke), _to_float(style.get("lineWidth"), 1.0) or 1.0))
        else:
            p.setPen(Qt.NoPen)

    def hit_test(self, pos: QPointF):
        return None


# ---------------------------------------------------------------------------
# map 系列（geo 简化）
# ---------------------------------------------------------------------------

#: 内置演示地图：7 个大区块的示意多边形（自定义平面示意坐标系，
#: 非真实地理数据，不表示任何真实行政区划），仅供功能演示。
DEMO_MAP = {
    "华北": [(30, 18), (48, 14), (55, 24), (50, 34), (36, 32)],
    "东北": [(56, 4), (74, 6), (78, 20), (62, 26), (55, 18)],
    "华东": [(52, 36), (66, 34), (70, 48), (56, 52), (50, 44)],
    "华南": [(46, 56), (62, 54), (66, 68), (50, 72), (42, 64)],
    "华中": [(36, 36), (50, 36), (48, 52), (34, 50)],
    "西南": [(16, 40), (34, 38), (32, 58), (14, 60), (10, 48)],
    "西北": [(4, 10), (28, 12), (34, 34), (16, 38), (6, 28)],
}


class MapSeriesRenderer(SeriesRenderer):
    """简化地图系列（type="map"）。

    option::

        {"type": "map", "map": "demo"|自定义名, "nameProperty": "name",
         "data": [{"name": "华北", "value": 120}, ...]}

    - ``map`` 为 ``"demo"``（或缺省）时使用内置示意地图 ``DEMO_MAP``
      （非真实地理数据，见模块 docstring）；
    - 自定义地图经 ``option["geo"]["regions"] = {"名称": [[x, y], ...]}``
      传入多边形顶点列表（任意平面坐标，自动等比缩放到绘图区）；
    - 区域着色：优先经 chart.components 中 visualMap 组件的
      ``map_color(v)``，否则按 primary.subtle → primary 色带插值；
    - ``nameProperty``：区域标签取自 data 项的该键（缺省 "name"），
      无对应 data 项时使用区域名；
    - ``hit_test(pos)``：命中区域返回 {"name","value","series"}。
    """

    def __init__(self, chart, opt):
        super().__init__(chart, opt)
        self._polys = []   # [(region_name, QPolygonF)]
        self._rect = QRectF()

    # -- 数据 ------------------------------------------------------------
    def _regions(self) -> dict:
        """当前生效的 {名称: [[x, y], ...]} 多边形字典。"""
        name = str(self.opt.get("map") or "demo")
        geo = (getattr(self.chart, "_option", {}) or {}).get("geo") or {}
        custom = geo.get("regions") if isinstance(geo, dict) else None
        if name not in ("demo", "china-simple") \
                and isinstance(custom, dict) and custom:
            out = {}
            for k, poly in custom.items():
                pts = []
                for pt in poly or []:
                    if isinstance(pt, (list, tuple)) and len(pt) >= 2:
                        px = _to_float(pt[0])
                        py = _to_float(pt[1])
                        if px is not None and py is not None:
                            pts.append((px, py))
                if len(pts) >= 3:
                    out[str(k)] = pts
            if out:
                return out
        return {k: [tuple(pt) for pt in v] for k, v in DEMO_MAP.items()}

    def _value_map(self) -> dict:
        """data [{name, value}] → {区域名: 数值}（nameProperty 可改键）。"""
        key = str(self.opt.get("nameProperty") or "name")
        out = {}
        for item in self.data():
            if not isinstance(item, dict):
                continue
            nm = item.get(key, item.get("name"))
            v = _to_float(item.get("value"))
            if nm is not None:
                out[str(nm)] = v
        return out

    # -- 协议 ------------------------------------------------------------
    def layout(self, rect: QRectF) -> None:
        self._rect = QRectF(rect)
        self._polys = []
        regions = self._regions()
        if not regions:
            return
        xs = [pt[0] for pts in regions.values() for pt in pts]
        ys = [pt[1] for pts in regions.values() for pt in pts]
        if not xs or not ys:
            return
        x0, x1 = min(xs), max(xs)
        y0, y1 = min(ys), max(ys)
        span_x = max(1e-6, x1 - x0)
        span_y = max(1e-6, y1 - y0)
        margin = 18.0
        avail_w = max(10.0, rect.width() - margin * 2)
        avail_h = max(10.0, rect.height() - margin * 2)
        scale = min(avail_w / span_x, avail_h / span_y)
        ox = rect.left() + (rect.width() - span_x * scale) / 2
        oy = rect.top() + (rect.height() - span_y * scale) / 2
        for name, pts in regions.items():
            poly = QPolygonF([QPointF(ox + (px - x0) * scale,
                                      oy + (py - y0) * scale)
                              for px, py in pts])
            self._polys.append((name, poly))

    def _fill_color(self, name: str, values: dict, vmin: float,
                    vmax: float, vm) -> QColor:
        v = values.get(name)
        if v is None:
            return QColor(T("color.bg.muted"))
        if vm is not None:
            try:
                return QColor(vm.map_color(v))
            except Exception:
                pass
        span = vmax - vmin
        frac = 0.5 if span == 0 else (v - vmin) / span
        return lerp_color(T("color.primary.subtle"), T("color.primary"), frac)

    def paint(self, p: QPainter, anim_t: float = 1.0) -> None:
        if not self._polys:
            return
        values = self._value_map()
        vals = [v for v in values.values() if v is not None]
        vmin = min(vals) if vals else 0.0
        vmax = max(vals) if vals else 1.0
        vm = None
        for c in self.chart.components:
            if hasattr(c, "map_color") and callable(getattr(c, "map_color")):
                vm = c
                break
        p.save()
        font = chart_font(T("font.xs"))
        p.setFont(font)
        border = QPen(QColor(T("color.border.strong")), 1)
        for name, poly in self._polys:
            fill = self._fill_color(name, values, vmin, vmax, vm)
            p.setPen(border)
            p.setBrush(fill)
            p.drawPolygon(poly)
            # 区域名称标签（多边形包围盒中心，按底色亮度选文字色）
            c = poly.boundingRect().center()
            if fill.lightness() < 130:
                p.setPen(QColor("#FFFFFF"))
            else:
                p.setPen(QColor(T("color.text.primary")))
            label = name
            p.drawText(QRectF(c.x() - 40, c.y() - 8, 80, 16),
                       Qt.AlignCenter, label)
        p.restore()

    def hit_test(self, pos: QPointF):
        values = self._value_map()
        for name, poly in reversed(self._polys):
            if poly.containsPoint(pos, Qt.OddEvenFill):
                return {"name": name, "value": values.get(name),
                        "series": self.name}
        return None

    def value_at_index(self, index: int):
        return None


# ---------------------------------------------------------------------------
# 注册
# ---------------------------------------------------------------------------

register_component("markPoint", MarkPointComponent)
register_component("markLine", MarkLineComponent)
register_component("markArea", MarkAreaComponent)
register_component("graphic", GraphicComponent)
register_series("map", MapSeriesRenderer)
