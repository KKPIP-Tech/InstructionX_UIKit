# -*- coding: utf-8 -*-
"""坐标系与轴模型（CHART_SPEC §3 坐标协议 / §4 schema）。

对外契约（供 C2/C3/C4 使用）：

- ``Coord``：坐标系协议基类，子类实现
  ``layout(rect)`` / ``map_point(x, y)`` / ``paint_axes(p)`` /
  ``paint_tooltip_marker(p, pos)``；可选 ``set_series(series_opts)``、
  ``invert_x(pos)``（tooltip axis 触发用）。
- ``AxisModel``：category / value 轴模型，支持 name、min/max、nice ticks。
- ``GridCoord``：直角坐标（grid 边距 + x/y 轴 + 刻度网格线）。
- ``PolarCoord``：极坐标（radiusAxis/angleAxis，多边形/圆形网格）。
- ``SingleAxisCoord``：横向单轴。
- ``CalendarCoord``：GitHub 式 周(列)×星期(行) 年历网格。
- ``nice_ticks(vmin, vmax, segments=5)``：数值轴 nice ticks 工具函数。

构造约定：``Coord`` 子类签名为 ``(chart, option)``，``option`` 为完整
图表 option 字典，各坐标系自取所需键（如 ``grid`` / ``xAxis`` …）。
所有配色经 ``T()`` 实时读取，主题切换后重绘即生效。
"""

import math
from datetime import date, timedelta

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QPainter, QPainterPath, QPen

from ..theme import T
from ..tokens import FONT_FAMILY

__all__ = [
    "nice_ticks",
    "format_value",
    "chart_font",
    "Coord",
    "AxisModel",
    "GridCoord",
    "PolarCoord",
    "SingleAxisCoord",
    "CalendarCoord",
]


# ---------------------------------------------------------------------------
# 工具：字体 / 数值格式化 / nice ticks
# ---------------------------------------------------------------------------

def _font_families() -> list:
    """把 FONT_FAMILY 字符串解析为字族列表（剔除 generic 族）。"""
    generic = {"sans-serif", "serif", "monospace", "cursive", "fantasy"}
    result = []
    for item in FONT_FAMILY.split(","):
        name = item.strip().strip('"').strip("'")
        if name and name.lower() not in generic:
            result.append(name)
    return result


def chart_font(px: int = None, weight: int = None) -> QFont:
    """构造图表用字体（FONT_FAMILY 字族；px 默认 font.xs）。"""
    font = QFont()
    font.setFamilies(_font_families())
    font.setStyleHint(QFont.SansSerif)
    font.setPixelSize(int(px if px else T("font.xs")))
    if weight:
        font.setWeight(QFont.Weight(int(weight)))
    return font


def format_value(v) -> str:
    """数值标签格式化：整数不带小数点，其余保留至多两位小数。"""
    if v is None:
        return ""
    if isinstance(v, bool):
        return str(v)
    if isinstance(v, (int, float)):
        if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
            return ""
        if float(v).is_integer() and abs(v) < 1e15:
            return str(int(v))
        return f"{v:.2f}".rstrip("0").rstrip(".")
    return str(v)


def nice_ticks(vmin: float, vmax: float, segments: int = 5):
    """数值轴 nice ticks。

    参数:
        vmin/vmax: 数据范围。
        segments: 目标段数，约 5 段。

    返回:
        ``(nice_min, nice_max, ticks)``，ticks 为含端点的刻度值列表。
    """
    vmin = float(vmin)
    vmax = float(vmax)
    if vmin > vmax:
        vmin, vmax = vmax, vmin
    if not math.isfinite(vmin) or not math.isfinite(vmax):
        vmin, vmax = 0.0, 1.0
    if vmin == vmax:
        if vmin == 0:
            vmax = 1.0
        else:
            pad = abs(vmin) * 0.5
            vmin -= pad
            vmax += pad
    segments = max(1, int(segments))
    span = vmax - vmin
    step0 = span / segments
    mag = 10 ** math.floor(math.log10(step0)) if step0 > 0 else 1.0
    step = mag
    for m in (1.0, 2.0, 5.0, 10.0):
        if m * mag >= step0 - 1e-12:
            step = m * mag
            break
    nice_min = math.floor(vmin / step) * step
    nice_max = math.ceil(vmax / step) * step
    if nice_min == nice_max:
        nice_max = nice_min + step
    # 用整数计数避免浮点累积误差
    n = int(round((nice_max - nice_min) / step))
    ticks = []
    for i in range(n + 1):
        t = nice_min + i * step
        ticks.append(0.0 if abs(t) < step * 1e-9 else t)
    return nice_min, nice_max, ticks


# ---------------------------------------------------------------------------
# 坐标协议基类
# ---------------------------------------------------------------------------

class Coord:
    """坐标系协议基类（CHART_SPEC §3）。

    子类必须实现 ``layout`` / ``map_point`` / ``paint_axes`` /
    ``paint_tooltip_marker``。可选：
    ``set_series(series_opts)`` 接收原始系列 option 列表用于范围统计；
    ``invert_x(pos)`` 由像素反推主轴数据值（tooltip axis 触发用）。
    """

    #: 坐标系种类名（"grid" / "polar" / "singleAxis" / "calendar"），
    #: 供 ChartWidget.coord_for 按 series.coordinateSystem 匹配。
    kind = ""

    def __init__(self, chart=None, option: dict = None):
        self.chart = chart
        self.option = dict(option or {})
        self.rect = QRectF()

    # -- 协议 ------------------------------------------------------------
    def layout(self, rect: QRectF) -> None:
        """按可用矩形完成几何布局。"""
        self.rect = QRectF(rect)

    def map_point(self, x, y=None) -> QPointF:
        """数据 → 像素。polar 为 (angle, radius)；calendar/single 单参。"""
        raise NotImplementedError

    def paint_axes(self, p: QPainter) -> None:
        """绘制轴线 / 刻度 / 网格 / 标签（主题感知，T() 实时取色）。"""
        raise NotImplementedError

    def paint_tooltip_marker(self, p: QPainter, pos: QPointF) -> None:
        """绘制十字线 / 指示线。"""
        raise NotImplementedError

    # -- 可选 ------------------------------------------------------------
    def set_series(self, series_opts: list) -> None:
        """接收原始系列 option 列表（布局前调用，用于数值范围统计）。"""

    def invert_x(self, pos: QPointF):
        """像素 → 主轴数据值（默认不支持，返回 None）。"""
        return None


# ---------------------------------------------------------------------------
# 轴模型
# ---------------------------------------------------------------------------

def _iter_data_values(data):
    """从系列 data 中迭代全部数值（支持 number / [x, y] / {"value": v}）。"""
    for item in data or []:
        if item is None:
            continue
        v = item
        if isinstance(item, dict):
            v = item.get("value")
        if isinstance(v, (list, tuple)):
            for sub in v:
                if isinstance(sub, (int, float)) and not isinstance(sub, bool):
                    yield float(sub)
        elif isinstance(v, (int, float)) and not isinstance(v, bool):
            yield float(v)


class AxisModel:
    """坐标轴模型：category（list[str]）或 value（自动 nice ticks）。

    参数:
        opt: option 中 ``xAxis`` / ``yAxis`` / ``radiusAxis`` 等子字典，
            支持 ``type`` / ``data`` / ``name`` / ``min`` / ``max``。
            axisLabel 字体统一取 font.xs（见 ``label_font()``）。
        default_type: opt 未给 ``type`` 时的兜底。
    """

    def __init__(self, opt: dict = None, default_type: str = "value"):
        opt = dict(opt or {})
        self.opt = opt
        self.type = str(opt.get("type") or default_type)
        self.name = str(opt.get("name") or "")
        self.categories = [str(c) for c in (opt.get("data") or [])]
        self.min = opt.get("min")
        self.max = opt.get("max")
        # value 轴：布局前由 set_extent 填充
        self.vmin = 0.0
        self.vmax = 1.0
        self._ticks = [0.0, 1.0]

    # -- 范围 ------------------------------------------------------------
    def set_extent(self, data_min: float = None, data_max: float = None,
                   segments: int = 5) -> None:
        """按数据范围计算 value 轴 nice ticks（min/max 可覆盖端点）。"""
        if self.type != "value":
            return
        lo = 0.0 if data_min is None else float(data_min)
        hi = 1.0 if data_max is None else float(data_max)
        # 数据全为正时基线取 0、全为负时顶取 0，更符合常规图表观感
        if self.min is None and lo > 0:
            lo = 0.0
        if self.max is None and hi < 0:
            hi = 0.0
        if self.min is not None:
            lo = float(self.min)
        if self.max is not None:
            hi = float(self.max)
        self.vmin, self.vmax, self._ticks = nice_ticks(lo, hi, segments)
        if self.min is not None:
            self.vmin = float(self.min)
        if self.max is not None:
            self.vmax = float(self.max)

    def ticks(self) -> list:
        """刻度列表：category 返回类别字符串，value 返回数值列表。"""
        if self.type == "category":
            return list(self.categories)
        return list(self._ticks)

    # -- 映射（一维：start→end 像素区间） ----------------------------------
    def map(self, value, start: float, end: float) -> float:
        """数据值 → [start, end] 区间内的像素坐标。"""
        if self.type == "category":
            idx = self.category_index(value)
            n = max(1, len(self.categories))
            band = (end - start) / n
            return start + band * (min(max(idx, 0), n - 1) + 0.5)
        v = _to_float(value, self.vmin)
        span = self.vmax - self.vmin
        frac = 0.0 if span == 0 else (v - self.vmin) / span
        return start + (end - start) * frac

    def band_width(self, start: float, end: float) -> float:
        """category 轴单个 band 的像素宽度（value 轴返回 0）。"""
        if self.type != "category" or not self.categories:
            return 0.0
        return abs(end - start) / len(self.categories)

    def category_index(self, value) -> int:
        """类别值（名字或序号）→ 下标。"""
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return int(value)
        s = str(value)
        if s in self.categories:
            return self.categories.index(s)
        return 0

    def invert(self, px: float, start: float, end: float):
        """像素 → 数据值（category 返回下标，越界收敛）。"""
        if end == start:
            return 0
        frac = (px - start) / (end - start)
        if self.type == "category":
            n = max(1, len(self.categories))
            return min(max(int(frac * n), 0), n - 1)
        return self.vmin + frac * (self.vmax - self.vmin)

    # -- 外观 ------------------------------------------------------------
    def label_font(self) -> QFont:
        """axisLabel 字体（font.xs）。"""
        return chart_font(T("font.xs"))


def _to_float(v, default=0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return float(default)


# ---------------------------------------------------------------------------
# 直角坐标系
# ---------------------------------------------------------------------------

class GridCoord(Coord):
    """直角坐标系：grid 边距 + x/y 轴 + 刻度网格线。

    option 键：``grid`` {left,right,top,bottom}（默认 48/24/40/36）、
    ``xAxis`` / ``yAxis``。``map_point(x, y)``：x 为类别名/下标或数值，
    y 为数值。``invert_x(pos)`` 供 tooltip axis 触发。
    """

    kind = "grid"

    def __init__(self, chart=None, option: dict = None):
        super().__init__(chart, option)
        xopt = dict(self.option.get("xAxis") or {})
        yopt = dict(self.option.get("yAxis") or {})
        x_default = "category" if xopt.get("data") else "value"
        self.x_axis = AxisModel(xopt, x_default)
        self.y_axis = AxisModel(yopt, "value")
        grid = dict(self.option.get("grid") or {})
        self.m_left = float(grid.get("left", 48))
        self.m_right = float(grid.get("right", 24))
        self.m_top = float(grid.get("top", 40))
        self.m_bottom = float(grid.get("bottom", 36))
        self.plot = QRectF()  # 绘图区（扣除边距）

    # -- 数据范围 ---------------------------------------------------------
    def set_series(self, series_opts: list) -> None:
        ys = []
        for s in series_opts or []:
            if not isinstance(s, dict):
                continue
            if s.get("coordinateSystem") not in (None, "cartesian2d", "grid"):
                continue
            for item in s.get("data") or []:
                y = _datum_y(item)
                if y is not None:
                    ys.append(y)
        if ys:
            self.y_axis.set_extent(min(ys), max(ys))
        else:
            self.y_axis.set_extent(0.0, 1.0)
        if self.x_axis.type == "value":
            xs = []
            for s in series_opts or []:
                if not isinstance(s, dict):
                    continue
                for item in s.get("data") or []:
                    x = _datum_x(item)
                    if isinstance(x, (int, float)) and not isinstance(x, bool):
                        xs.append(float(x))
            if xs:
                self.x_axis.set_extent(min(xs), max(xs))
            else:
                self.x_axis.set_extent(0.0, 1.0)

    # -- 协议 -------------------------------------------------------------
    def layout(self, rect: QRectF) -> None:
        super().layout(rect)
        self.plot = QRectF(
            rect.left() + self.m_left,
            rect.top() + self.m_top,
            max(10.0, rect.width() - self.m_left - self.m_right),
            max(10.0, rect.height() - self.m_top - self.m_bottom),
        )

    def map_point(self, x, y=None) -> QPointF:
        px = self.x_axis.map(x, self.plot.left(), self.plot.right())
        py = self.y_axis.map(_to_float(y), self.plot.bottom(), self.plot.top())
        return QPointF(px, py)

    def invert_x(self, pos: QPointF):
        return self.x_axis.invert(pos.x(), self.plot.left(), self.plot.right())

    def paint_axes(self, p: QPainter) -> None:
        p.save()
        font = self.x_axis.label_font()
        p.setFont(font)
        fm = QFontMetricsF(font)
        c_grid = QColor(T("color.border"))
        c_axis = QColor(T("color.border.strong"))
        c_text = QColor(T("color.text.secondary"))
        c_name = QColor(T("color.text.tertiary"))

        # y 轴：水平网格线 + 刻度标签
        for tv in self.y_axis.ticks():
            py = self.y_axis.map(tv, self.plot.bottom(), self.plot.top())
            p.setPen(QPen(c_grid, 1))
            p.drawLine(QPointF(self.plot.left(), py), QPointF(self.plot.right(), py))
            p.setPen(c_text)
            p.drawText(
                QRectF(self.rect.left(), py - fm.height() / 2,
                       max(8.0, self.plot.left() - self.rect.left() - 6),
                       fm.height()),
                Qt.AlignRight | Qt.AlignVCenter, format_value(tv))
        # x 轴：类别标签 / 数值刻度 + 纵向网格线
        if self.x_axis.type == "category":
            for i, cat in enumerate(self.x_axis.categories):
                px = self.x_axis.map(i, self.plot.left(), self.plot.right())
                p.setPen(QPen(c_grid, 1))
                p.drawLine(QPointF(px, self.plot.top()), QPointF(px, self.plot.bottom()))
                p.setPen(c_text)
                p.drawText(QRectF(px - 40, self.plot.bottom() + 4, 80, fm.height()),
                           Qt.AlignHCenter | Qt.AlignTop, str(cat))
        else:
            for tv in self.x_axis.ticks():
                px = self.x_axis.map(tv, self.plot.left(), self.plot.right())
                p.setPen(QPen(c_grid, 1))
                p.drawLine(QPointF(px, self.plot.top()), QPointF(px, self.plot.bottom()))
                p.setPen(c_text)
                p.drawText(QRectF(px - 40, self.plot.bottom() + 4, 80, fm.height()),
                           Qt.AlignHCenter | Qt.AlignTop, format_value(tv))
        # 轴线（下 / 左）
        p.setPen(QPen(c_axis, 1))
        p.drawLine(self.plot.bottomLeft(), self.plot.bottomRight())
        p.drawLine(self.plot.bottomLeft(), self.plot.topLeft())
        # 轴名称
        if self.x_axis.name:
            p.setPen(c_name)
            p.drawText(
                QRectF(self.plot.right() - 80,
                       self.plot.bottom() + 4 + fm.height(), 80, fm.height()),
                Qt.AlignRight | Qt.AlignTop, self.x_axis.name)
        if self.y_axis.name:
            p.setPen(c_name)
            p.drawText(
                QRectF(self.rect.left(), self.plot.top() - fm.height() - 4,
                       120, fm.height()),
                Qt.AlignLeft | Qt.AlignBottom, self.y_axis.name)
        p.restore()

    def paint_tooltip_marker(self, p: QPainter, pos: QPointF) -> None:
        p.save()
        pen = QPen(QColor(T("color.border.strong")), 1)
        pen.setStyle(Qt.DashLine)
        p.setPen(pen)
        x = min(max(pos.x(), self.plot.left()), self.plot.right())
        y = min(max(pos.y(), self.plot.top()), self.plot.bottom())
        p.drawLine(QPointF(x, self.plot.top()), QPointF(x, self.plot.bottom()))
        p.drawLine(QPointF(self.plot.left(), y), QPointF(self.plot.right(), y))
        p.restore()


def _datum_y(item):
    """取数据项的 y 值：number / [x, y] / {"value": ...}。"""
    if item is None:
        return None
    v = item.get("value") if isinstance(item, dict) else item
    if isinstance(v, (list, tuple)):
        if len(v) >= 2 and isinstance(v[1], (int, float)):
            return float(v[1])
        if len(v) == 1 and isinstance(v[0], (int, float)):
            return float(v[0])
        return None
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return float(v)
    return None


def _datum_x(item):
    """取数据项的 x 值（无则 None，调用方用下标代替）。"""
    if item is None:
        return None
    v = item.get("value") if isinstance(item, dict) else item
    if isinstance(v, (list, tuple)) and v:
        return v[0]
    return None


# ---------------------------------------------------------------------------
# 极坐标系
# ---------------------------------------------------------------------------

class PolarCoord(Coord):
    """极坐标系：radiusAxis（value）+ angleAxis（category/value）。

    option 键：``polar`` {"shape": "polygon"|"circle"}、``radiusAxis``、
    ``angleAxis``。``map_point(angle, radius)``：angle 为类别名/下标或数值，
    radius 为数值；角度自正上方起顺时针。
    """

    kind = "polar"

    def __init__(self, chart=None, option: dict = None):
        super().__init__(chart, option)
        polar = dict(self.option.get("polar") or {})
        self.shape = str(polar.get("shape") or "polygon")
        aopt = dict(self.option.get("angleAxis") or {})
        a_default = "category" if aopt.get("data") else "value"
        self.angle_axis = AxisModel(aopt, a_default)
        self.radius_axis = AxisModel(dict(self.option.get("radiusAxis") or {}), "value")
        self.center = QPointF()
        self.radius = 1.0

    def set_series(self, series_opts: list) -> None:
        rs = []
        for s in series_opts or []:
            if not isinstance(s, dict) or s.get("coordinateSystem") != "polar":
                continue
            for item in s.get("data") or []:
                r = _datum_y(item)
                if r is not None:
                    rs.append(r)
        if rs:
            self.radius_axis.set_extent(0.0, max(rs))
        else:
            self.radius_axis.set_extent(0.0, 1.0)
        if self.angle_axis.type == "value":
            self.angle_axis.set_extent(0.0, 360.0, segments=4)

    def layout(self, rect: QRectF) -> None:
        super().layout(rect)
        margin = 28.0  # 外圈类别标签预留
        self.center = rect.center()
        self.radius = max(10.0, min(rect.width(), rect.height()) / 2 - margin)

    def _angle_frac(self, angle) -> float:
        ax = self.angle_axis
        if ax.type == "category":
            n = max(1, len(ax.categories))
            return (ax.category_index(angle) % n) / n
        span = ax.vmax - ax.vmin
        return 0.0 if span == 0 else (_to_float(angle) - ax.vmin) / span

    def map_point(self, x, y=None) -> QPointF:
        """(angle, radius) → 像素。angle 类别/数值；radius 数值。"""
        frac = self._angle_frac(x)
        theta = -math.pi / 2 + frac * 2 * math.pi  # 正上方起顺时针
        r_span = self.radius_axis.vmax - self.radius_axis.vmin
        r_frac = 0.0 if r_span == 0 else \
            (_to_float(y) - self.radius_axis.vmin) / r_span
        r_frac = min(max(r_frac, 0.0), 1.0)
        r = self.radius * r_frac
        return QPointF(self.center.x() + r * math.cos(theta),
                       self.center.y() + r * math.sin(theta))

    def _ring_path(self, frac: float) -> QPainterPath:
        r = self.radius * frac
        path = QPainterPath()
        if self.shape == "circle" or self.angle_axis.type != "category" \
                or not self.angle_axis.categories:
            path.addEllipse(self.center, r, r)
            return path
        n = len(self.angle_axis.categories)
        for i in range(n):
            theta = -math.pi / 2 + i / n * 2 * math.pi
            pt = QPointF(self.center.x() + r * math.cos(theta),
                         self.center.y() + r * math.sin(theta))
            if i == 0:
                path.moveTo(pt)
            else:
                path.lineTo(pt)
        path.closeSubpath()
        return path

    def paint_axes(self, p: QPainter) -> None:
        p.save()
        c_grid = QColor(T("color.border"))
        c_text = QColor(T("color.text.secondary"))
        font = self.radius_axis.label_font()
        p.setFont(font)
        fm = QFontMetricsF(font)
        ticks = self.radius_axis.ticks()
        span = self.radius_axis.vmax - self.radius_axis.vmin
        # 环形网格（多边形 / 圆形）
        for tv in ticks[1:]:
            frac = 1.0 if span == 0 else (tv - self.radius_axis.vmin) / span
            p.setPen(QPen(c_grid, 1))
            p.drawPath(self._ring_path(frac))
        # 角轴辐条 + 外圈类别标签
        if self.angle_axis.type == "category" and self.angle_axis.categories:
            n = len(self.angle_axis.categories)
            for i, cat in enumerate(self.angle_axis.categories):
                theta = -math.pi / 2 + i / n * 2 * math.pi
                outer = QPointF(self.center.x() + self.radius * math.cos(theta),
                                self.center.y() + self.radius * math.sin(theta))
                p.setPen(QPen(c_grid, 1))
                p.drawLine(self.center, outer)
                lx = self.center.x() + (self.radius + 14) * math.cos(theta)
                ly = self.center.y() + (self.radius + 14) * math.sin(theta)
                p.setPen(c_text)
                p.drawText(QRectF(lx - 40, ly - fm.height() / 2, 80, fm.height()),
                           Qt.AlignCenter, str(cat))
        # 半径刻度标签（沿正上方辐条）
        for tv in ticks[1:]:
            frac = 1.0 if span == 0 else (tv - self.radius_axis.vmin) / span
            p.setPen(c_text)
            p.drawText(
                QRectF(self.center.x() + 2,
                       self.center.y() - self.radius * frac - fm.height() / 2,
                       48, fm.height()),
                Qt.AlignLeft | Qt.AlignVCenter, format_value(tv))
        p.restore()

    def paint_tooltip_marker(self, p: QPainter, pos: QPointF) -> None:
        p.save()
        pen = QPen(QColor(T("color.border.strong")), 1)
        pen.setStyle(Qt.DashLine)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        p.drawLine(self.center, pos)
        r = math.hypot(pos.x() - self.center.x(), pos.y() - self.center.y())
        if r > 1:
            p.drawEllipse(self.center, r, r)
        p.restore()


# ---------------------------------------------------------------------------
# 单轴坐标系
# ---------------------------------------------------------------------------

class SingleAxisCoord(Coord):
    """横向单轴坐标系（一行数值轴，系列在其上排布）。

    option 键：``singleAxis`` {left,right,top,bottom,type,min,max,name}
    （left/right 默认 40；top/bottom 不给时取可用区垂直居中）。
    ``map_point(value)`` 单参调用，返回轴线上像素点。
    """

    kind = "singleAxis"

    def __init__(self, chart=None, option: dict = None):
        super().__init__(chart, option)
        sopt = dict(self.option.get("singleAxis") or {})
        self.axis = AxisModel(sopt, "value")
        self.m_left = float(sopt.get("left", 40))
        self.m_right = float(sopt.get("right", 40))
        self.m_top = sopt.get("top")
        self.m_bottom = sopt.get("bottom")
        self.line_y = 0.0
        self.plot = QRectF()

    def set_series(self, series_opts: list) -> None:
        vs = []
        for s in series_opts or []:
            if not isinstance(s, dict) or s.get("coordinateSystem") != "singleAxis":
                continue
            vs.extend(_iter_data_values(s.get("data")))
        if vs:
            self.axis.set_extent(min(vs), max(vs))
        else:
            self.axis.set_extent(0.0, 1.0)

    def layout(self, rect: QRectF) -> None:
        super().layout(rect)
        left = rect.left() + self.m_left
        right = rect.right() - self.m_right
        if self.m_top is not None:
            y = rect.top() + float(self.m_top)
        elif self.m_bottom is not None:
            y = rect.bottom() - float(self.m_bottom)
        else:
            y = rect.center().y()
        self.line_y = y
        self.plot = QRectF(left, y, max(10.0, right - left), 0.0)

    def map_point(self, x, y=None) -> QPointF:
        px = self.axis.map(x, self.plot.left(), self.plot.right())
        return QPointF(px, self.line_y)

    def invert_x(self, pos: QPointF):
        return self.axis.invert(pos.x(), self.plot.left(), self.plot.right())

    def paint_axes(self, p: QPainter) -> None:
        p.save()
        c_axis = QColor(T("color.border.strong"))
        c_grid = QColor(T("color.border"))
        c_text = QColor(T("color.text.secondary"))
        font = self.axis.label_font()
        p.setFont(font)
        fm = QFontMetricsF(font)
        p.setPen(QPen(c_axis, 1))
        p.drawLine(QPointF(self.plot.left(), self.line_y),
                   QPointF(self.plot.right(), self.line_y))
        for tv in self.axis.ticks():
            px = self.axis.map(tv, self.plot.left(), self.plot.right())
            p.setPen(QPen(c_grid, 1))
            p.drawLine(QPointF(px, self.line_y - 4), QPointF(px, self.line_y + 4))
            p.setPen(c_text)
            p.drawText(QRectF(px - 40, self.line_y + 6, 80, fm.height()),
                       Qt.AlignHCenter | Qt.AlignTop, format_value(tv))
        if self.axis.name:
            p.setPen(QColor(T("color.text.tertiary")))
            p.drawText(
                QRectF(self.plot.right() + 6, self.line_y - fm.height() / 2,
                       80, fm.height()),
                Qt.AlignLeft | Qt.AlignVCenter, self.axis.name)
        p.restore()

    def paint_tooltip_marker(self, p: QPainter, pos: QPointF) -> None:
        p.save()
        pen = QPen(QColor(T("color.border.strong")), 1)
        pen.setStyle(Qt.DashLine)
        p.setPen(pen)
        x = min(max(pos.x(), self.plot.left()), self.plot.right())
        p.drawLine(QPointF(x, self.rect.top() + 8),
                   QPointF(x, self.rect.bottom() - 8))
        p.restore()


# ---------------------------------------------------------------------------
# 日历坐标系
# ---------------------------------------------------------------------------

_WEEKDAY_LABELS = {0: "Mon", 2: "Wed", 4: "Fri"}  # 行下标 -> 标签
_MONTH_LABELS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                 "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


class CalendarCoord(Coord):
    """日历坐标系：GitHub 式 周(列)×星期(行) 年历网格。

    option 键：``calendar`` {"year": int, "cellSize": px 或 "auto",
    "range": ["YYYY-MM-DD", "YYYY-MM-DD"]（可选，默认全年）}。
    行 = 星期（0=周一 … 6=周日），列 = 周序（首列为 start 所在周的周一）。
    ``map_point(date)`` 单参：日期（"YYYY-MM-DD" / datetime.date / (y,m,d)）
    → 单元格中心；``cell_rect(date)`` → 单元格矩形；``date_at(pos)`` 反查。
    """

    kind = "calendar"

    def __init__(self, chart=None, option: dict = None):
        super().__init__(chart, option)
        cal = dict(self.option.get("calendar") or {})
        self.cal_opt = cal
        self.year = int(cal.get("year") or date.today().year)
        self.cell_size_opt = cal.get("cellSize", 14)
        rng = cal.get("range")
        if isinstance(rng, (list, tuple)) and len(rng) >= 2:
            self.start = self._parse_date(rng[0]) or date(self.year, 1, 1)
            self.end = self._parse_date(rng[1]) or date(self.year, 12, 31)
        else:
            self.start = date(self.year, 1, 1)
            self.end = date(self.year, 12, 31)
        if self.end < self.start:
            self.start, self.end = self.end, self.start
        self._cell = 14.0
        self._origin = QPointF()  # 第一列（周）左上角
        self._weeks = 1

    # -- 日期工具 ---------------------------------------------------------
    @staticmethod
    def _parse_date(v):
        """"YYYY-MM-DD" / date / (y, m, d) → datetime.date（失败 None）。"""
        if isinstance(v, date):
            return v
        if isinstance(v, (list, tuple)) and len(v) >= 3:
            try:
                return date(int(v[0]), int(v[1]), int(v[2]))
            except (TypeError, ValueError):
                return None
        if isinstance(v, str):
            try:
                parts = v.strip().split("-")
                return date(int(parts[0]), int(parts[1]), int(parts[2]))
            except (TypeError, ValueError, IndexError):
                return None
        return None

    def _first_monday(self) -> date:
        return self.start - timedelta(days=self.start.weekday())

    # -- 协议 -------------------------------------------------------------
    def layout(self, rect: QRectF) -> None:
        super().layout(rect)
        label_top = 16.0   # 月份标签高度
        label_left = 28.0  # 星期标签宽度
        first = self._first_monday()
        self._weeks = max(1, (self.end - first).days // 7 + 1)
        avail_w = max(20.0, rect.width() - label_left - 4)
        avail_h = max(20.0, rect.height() - label_top - 4)
        if str(self.cell_size_opt).lower() == "auto":
            self._cell = max(3.0, min(avail_w / self._weeks, avail_h / 7.0))
        else:
            self._cell = max(3.0, _to_float(self.cell_size_opt, 14.0))
        # 水平居中
        grid_w = self._cell * self._weeks
        ox = rect.left() + label_left + max(0.0, (avail_w - grid_w) / 2)
        self._origin = QPointF(ox, rect.top() + label_top)

    def cell_rect(self, day) -> QRectF:
        """日期 → 单元格矩形（无法解析 / 范围外返回空矩形）。"""
        d = self._parse_date(day)
        if d is None or d < self.start or d > self.end:
            return QRectF()
        first = self._first_monday()
        delta = (d - first).days
        col = delta // 7
        row = d.weekday()
        return QRectF(self._origin.x() + col * self._cell,
                      self._origin.y() + row * self._cell,
                      self._cell, self._cell)

    def map_point(self, x, y=None) -> QPointF:
        """日期 → 单元格中心。"""
        r = self.cell_rect(x)
        if r.isNull():
            return QPointF(self._origin)
        return r.center()

    def cell_size(self) -> float:
        """当前单元格边长（px）。"""
        return self._cell

    def weeks(self) -> int:
        """总列数（周数）。"""
        return self._weeks

    def paint_axes(self, p: QPainter) -> None:
        p.save()
        c_text = QColor(T("color.text.tertiary"))
        font = chart_font(T("font.xs"))
        p.setFont(font)
        fm = QFontMetricsF(font)
        p.setPen(c_text)
        # 星期标签（Mon/Wed/Fri 三行）
        for row, label in _WEEKDAY_LABELS.items():
            y = self._origin.y() + row * self._cell
            p.drawText(QRectF(self.rect.left(), y,
                              max(8.0, self._origin.x() - self.rect.left() - 4),
                              self._cell),
                       Qt.AlignRight | Qt.AlignVCenter, label)
        # 月份标签：每月 1 日所在列（去重，避免相邻列重复绘制）
        first = self._first_monday()
        last_col = -1
        for month in range(self.start.month, 13):
            d = date(self.year, month, 1)
            if d > self.end:
                break
            anchor = d if d >= self.start else self.start
            col = (anchor - first).days // 7
            if col == last_col:
                continue
            last_col = col
            x = self._origin.x() + col * self._cell
            p.drawText(QRectF(x, self.rect.top(), 40, fm.height()),
                       Qt.AlignLeft | Qt.AlignVCenter, _MONTH_LABELS[month - 1])
        p.restore()

    def paint_tooltip_marker(self, p: QPainter, pos: QPointF) -> None:
        p.save()
        d = self.date_at(pos)
        if d is not None:
            r = self.cell_rect(d)
            pen = QPen(QColor(T("color.primary")), 1.4)
            p.setPen(pen)
            p.setBrush(Qt.NoBrush)
            p.drawRect(r.adjusted(0.5, 0.5, -0.5, -0.5))
        p.restore()

    def date_at(self, pos: QPointF):
        """像素 → 日期（网格外返回 None）。"""
        if self._cell <= 0:
            return None
        col = int((pos.x() - self._origin.x()) // self._cell)
        row = int((pos.y() - self._origin.y()) // self._cell)
        if col < 0 or col >= self._weeks or row < 0 or row > 6:
            return None
        d = self._first_monday() + timedelta(days=col * 7 + row)
        if d < self.start or d > self.end:
            return None
        return d
