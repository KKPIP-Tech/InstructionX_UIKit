# -*- coding: utf-8 -*-
"""图表交互组件（CHART_SPEC §5 C4）。

本模块提供：

- ``DataZoomComponent``（option_key="dataZoom"）：inside（滚轮缩放 +
  按住拖拽平移）与 slider（底部双把手滑块，自绘）两种区域缩放；
  通过修改 GridCoord 主轴（x 轴）的可视范围实现（category 轴替换
  类别窗口、value 轴调整 vmin/vmax 并重算 nice ticks）；``restore()``
  还原初始窗口。
- ``BrushComponent``（option_key="brush"）：矩形刷选，半透明选框，
  命中数据点存入 ``self.selected_items`` 并发出 ``selected(list)`` 信号；
  支持 option ``brush.outOfBrush`` 框外降透明样式。
- ``VisualMapComponent``（option_key="visualMap"）：连续值→颜色映射，
  右下 / 底部渐变条 + 两端数值标签；``map_color(v)`` 供系列（如 map）
  经 chart.components 查找调用。
- ``ChartTimeline``（option_key="timeline"，命名避开 InstructionX_UIKit Timeline）：
  底部时间轴（节点圆点 + 年份标签 + 播放 / 暂停按钮），切换帧调用
  ``chart.update_option(option["options"][i])``，autoPlay 经 QTimer。
- ``ToolboxComponent``（option_key="toolbox"）：右上角自绘图标按钮组
  （saveAsImage / restore / dataZoom 开关）。

所有配色经 T() 实时读取，主题切换后重绘即生效。
"""

import os

from PySide6.QtCore import QEvent, QObject, QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import (
    QColor,
    QFontMetricsF,
    QGuiApplication,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
)
from PySide6.QtWidgets import QFileDialog

from ..theme import T
from .axes import GridCoord, chart_font, format_value, nice_ticks
from .core import parse_data_point, register_component

__all__ = [
    "DataZoomComponent",
    "BrushComponent",
    "VisualMapComponent",
    "ChartTimeline",
    "ToolboxComponent",
]


def _to_float(v, default=None):
    """宽松数值转换，失败返回 default。"""
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _clamp(v, lo, hi):
    return min(max(v, lo), hi)


# ---------------------------------------------------------------------------
# dataZoom
# ---------------------------------------------------------------------------

class DataZoomComponent(QObject):
    """区域缩放：inside（滚轮 + 拖拽平移）/ slider（底部双把手滑块）。

    option::

        "dataZoom": [{"type": "inside"|"slider", "xAxisIndex": 0,
                      "start": 0, "end": 100}]

    start / end 为 0-100 的百分比窗口。缩放作用于主 GridCoord 的 x 轴：
    category 轴以类别子窗口替换 ``axis.categories``，value 轴调整
    ``vmin/vmax`` 并经 nice_ticks 重算刻度；均为幂等修改（基于缓存的
    完整数据计算），每次布局重放，不污染原始 option。

    inside 的滚轮经 chart 上的事件过滤器拦截（core 未提供 wheel 钩子，
    重建时旧过滤器会被移除，不会累积）；拖拽平移与滑块拖动经
    on_mouse_press / move / release 钩子。toolbox 的 dataZoom 开关经
    ``chart.datazoom_enabled`` 属性关闭 inside 交互（slider 常可用）。
    """

    option_key = "dataZoom"

    #: 滑块条带高度
    SLIDER_H = 24.0

    def __init__(self, chart, opt):
        super().__init__()
        self.chart = chart
        entries = opt if isinstance(opt, list) else [opt]
        self.entries = [e for e in entries if isinstance(e, dict)]
        first = self.entries[0] if self.entries else {}
        self.init_start = _clamp(_to_float(first.get("start"), 0.0) or 0.0, 0, 100)
        self.init_end = _clamp(_to_float(first.get("end"), 100.0) or 100.0, 0, 100)
        if self.init_end < self.init_start:
            self.init_start, self.init_end = self.init_end, self.init_start
        self.start = self.init_start
        self.end = self.init_end
        self.has_inside = any(str(e.get("type")) == "inside" for e in self.entries)
        self.has_slider = any(str(e.get("type")) == "slider" for e in self.entries)
        if not self.has_inside and not self.has_slider and self.entries:
            self.has_inside = True  # 未指明类型时按 inside 处理
        # 完整轴数据缓存（首次布局时捕获）
        self._full_cats = None      # category 轴完整类别
        self._full_range = None     # value 轴 (vmin, vmax)
        # 拖拽状态：("start"|"end"|"move"|"pan", last_x)
        self._drag = None
        self._track = QRectF()
        self._h_start = QRectF()
        self._h_end = QRectF()
        # 滚轮事件过滤器（core 无 wheel 钩子）；重建时移除旧过滤器防累积
        if self.has_inside:
            prev = getattr(chart, "_datazoom_filter", None)
            if prev is not None and prev is not self:
                try:
                    chart.removeEventFilter(prev)
                except Exception:
                    pass
            chart.installEventFilter(self)
            chart._datazoom_filter = self

    # -- 轴窗口 ------------------------------------------------------------
    def _axis(self):
        coord = self.chart.primary_coord()
        if isinstance(coord, GridCoord):
            return coord.x_axis
        return None

    def _capture_full(self, axis) -> None:
        if axis.type == "category":
            if self._full_cats is None:
                self._full_cats = list(axis.categories)
        else:
            if self._full_range is None:
                self._full_range = (float(axis.vmin), float(axis.vmax))

    def apply(self) -> None:
        """按 start/end 幂等重放轴窗口（每次布局调用）。"""
        axis = self._axis()
        if axis is None:
            return
        self._capture_full(axis)
        start, end = self.start, self.end
        if axis.type == "category":
            full = self._full_cats or []
            n = len(full)
            if n == 0:
                return
            i0 = int(start / 100.0 * n)
            i1 = int(-(-end / 100.0 * n // 1))  # ceil
            i0 = _clamp(i0, 0, n - 1)
            i1 = _clamp(max(i1, i0 + 1), 1, n)
            axis.categories = list(full[i0:i1])
        else:
            if self._full_range is None:
                return
            lo, hi = self._full_range
            span = hi - lo
            axis.vmin = lo + start / 100.0 * span
            axis.vmax = lo + end / 100.0 * span
            if axis.vmax <= axis.vmin:
                axis.vmax = axis.vmin + max(1e-6, span * 0.01)
            _, _, ticks = nice_ticks(axis.vmin, axis.vmax)
            axis._ticks = ticks

    def restore(self) -> None:
        """还原初始窗口（toolbox restore 调用）。"""
        self.start = self.init_start
        self.end = self.init_end
        self.apply()
        self.chart.update()

    # -- 布局 / 绘制（slider） ---------------------------------------------
    def layout(self, rect: QRectF) -> None:
        if self.has_slider:
            h = self.SLIDER_H
            y = rect.bottom() - h - 2
            band = QRectF(rect.left() + 16, y, max(40.0, rect.width() - 32), h)
            track_h = 8.0
            self._track = QRectF(band.left(), y + (h - track_h) / 2,
                                 band.width(), track_h)
            self._update_handles()
        self.apply()

    def _x_of(self, pct: float) -> float:
        return self._track.left() + _clamp(pct, 0, 100) / 100.0 * self._track.width()

    def _update_handles(self) -> None:
        hw, hh = 10.0, 16.0
        cy = self._track.center().y()
        self._h_start = QRectF(self._x_of(self.start) - hw / 2, cy - hh / 2, hw, hh)
        self._h_end = QRectF(self._x_of(self.end) - hw / 2, cy - hh / 2, hw, hh)

    def paint(self, p: QPainter, anim_t: float = 1.0) -> None:
        if not self.has_slider or self._track.isNull():
            return
        p.save()
        # 轨道
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(T("color.bg.muted")))
        p.drawRoundedRect(self._track, 4, 4)
        # 选中区间
        sel = QRectF(self._x_of(self.start), self._track.top(),
                     max(2.0, self._x_of(self.end) - self._x_of(self.start)),
                     self._track.height())
        fill = QColor(T("color.primary"))
        fill.setAlpha(70)
        p.setBrush(fill)
        p.drawRoundedRect(sel, 4, 4)
        # 把手
        for r in (self._h_start, self._h_end):
            p.setPen(QPen(QColor(T("color.border.strong")), 1))
            p.setBrush(QColor(T("color.bg.elevated")))
            p.drawRoundedRect(r, 3, 3)
            p.setPen(QPen(QColor(T("color.text.tertiary")), 1))
            cx = r.center().x()
            p.drawLine(QPointF(cx - 2, r.top() + 4), QPointF(cx - 2, r.bottom() - 4))
            p.drawLine(QPointF(cx + 2, r.top() + 4), QPointF(cx + 2, r.bottom() - 4))
        # 百分比标签
        font = chart_font(T("font.xs"))
        p.setFont(font)
        fm = QFontMetricsF(font)
        p.setPen(QColor(T("color.text.tertiary")))
        ly = self._track.bottom() + 1
        p.drawText(QRectF(self._track.left(), ly, 40, fm.height()),
                   Qt.AlignLeft | Qt.AlignTop, f"{self.start:.0f}%")
        p.drawText(QRectF(self._track.right() - 40, ly, 40, fm.height()),
                   Qt.AlignRight | Qt.AlignTop, f"{self.end:.0f}%")
        p.restore()

    # -- inside 交互 ---------------------------------------------------------
    def _inside_enabled(self) -> bool:
        return self.has_inside and bool(getattr(self.chart, "datazoom_enabled", True))

    def _plot(self) -> QRectF:
        coord = self.chart.primary_coord()
        if isinstance(coord, GridCoord):
            return coord.plot
        return QRectF()

    def eventFilter(self, obj, ev) -> bool:
        if obj is self.chart and ev.type() == QEvent.Wheel \
                and self._inside_enabled():
            pos = ev.position()
            if self._plot().contains(pos):
                self._wheel_zoom(ev.angleDelta().y(), pos)
                return True
        return False

    def _wheel_zoom(self, delta_y: float, pos: QPointF) -> None:
        plot = self._plot()
        if plot.width() <= 0:
            return
        old_span = self.end - self.start
        if old_span <= 0:
            return
        new_span = old_span * (0.8 if delta_y > 0 else 1.25)
        new_span = _clamp(new_span, 4.0, 100.0)
        frac = _clamp((pos.x() - plot.left()) / plot.width(), 0.0, 1.0)
        anchor = self.start + frac * old_span
        self.start = anchor - frac * new_span
        self.end = self.start + new_span
        # 平移回 [0, 100]
        if self.start < 0:
            self.end -= self.start
            self.start = 0.0
        if self.end > 100:
            self.start -= self.end - 100
            self.end = 100.0
        self.start = _clamp(self.start, 0.0, 96.0)
        self.apply()
        self.chart.update()

    def _pan(self, dx_px: float) -> None:
        plot = self._plot()
        if plot.width() <= 0:
            return
        span = self.end - self.start
        shift = -dx_px / plot.width() * 100.0
        shift = _clamp(shift, -self.start, 100.0 - self.end)
        self.start += shift
        self.end += shift
        self.apply()
        self.chart.update()

    # -- 鼠标钩子 ------------------------------------------------------------
    def on_mouse_press(self, pos: QPointF) -> bool:
        if self.has_slider and not self._track.isNull():
            grab = 6.0
            if self._h_start.adjusted(-grab, -grab, grab, grab).contains(pos):
                self._drag = ("start", pos.x())
                return True
            if self._h_end.adjusted(-grab, -grab, grab, grab).contains(pos):
                self._drag = ("end", pos.x())
                return True
            mid = QRectF(self._h_start.right(), self._track.top() - 4,
                         max(0.0, self._h_end.left() - self._h_start.right()),
                         self._track.height() + 8)
            if mid.contains(pos):
                self._drag = ("move", pos.x())
                return True
        if self._inside_enabled() and self._plot().contains(pos):
            self._drag = ("pan", pos.x())
            return True
        return False

    def on_mouse_move(self, pos: QPointF) -> bool:
        if self._drag is None:
            return False
        kind, last_x = self._drag
        if kind in ("start", "end"):
            pct = (pos.x() - self._track.left()) / max(1.0, self._track.width()) * 100.0
            pct = _clamp(pct, 0.0, 100.0)
            if kind == "start":
                self.start = min(pct, self.end - 2.0)
            else:
                self.end = max(pct, self.start + 2.0)
            self._update_handles()
            self.apply()
            self.chart.update()
        elif kind == "move":
            dx = pos.x() - last_x
            span = self.end - self.start
            shift = dx / max(1.0, self._track.width()) * 100.0
            shift = _clamp(shift, -self.start, 100.0 - self.end)
            self.start += shift
            self.end = self.start + span
            self._update_handles()
            self.apply()
            self.chart.update()
        elif kind == "pan":
            self._pan(pos.x() - last_x)
        self._drag = (kind, pos.x())
        return True

    def on_mouse_release(self, pos: QPointF) -> bool:
        if self._drag is not None:
            self._drag = None
            return True
        return False

    def hit_test(self, pos: QPointF):
        return None


# ---------------------------------------------------------------------------
# brush
# ---------------------------------------------------------------------------

class BrushComponent(QObject):
    """矩形刷选：Grid 上拖出半透明框，命中数据点集合。

    option::

        "brush": {"toolbox": ["rect", "clear"], "outOfBrush": {"opacity": 0.4}}

    松开后命中点列表存入 ``self.selected_items``（元素为
    {"series", "dataIndex", "value", "x"}），并发出 ``selected(list)``
    信号；配置了 ``outOfBrush`` 时框外区域以背景色降透明遮罩。
    再次按下开始新一次刷选并清空旧选区。
    """

    option_key = "brush"

    #: 刷选完成信号：list[{"series","dataIndex","value","x"}]
    selected = Signal(list)

    def __init__(self, chart, opt):
        super().__init__()
        self.chart = chart
        self.opt = dict(opt or {})
        self._rect = None        # 当前选框 QRectF（None 表示无选区）
        self._anchor = None      # 拖拽起点
        self.selected_items = []

    def _plot(self) -> QRectF:
        coord = self.chart.primary_coord()
        if isinstance(coord, GridCoord):
            return coord.plot
        return QRectF()

    def on_mouse_press(self, pos: QPointF) -> bool:
        plot = self._plot()
        if plot.isNull() or not plot.contains(pos):
            return False
        self._anchor = QPointF(pos)
        self._rect = QRectF(pos, pos)
        self.selected_items = []
        self.chart.update()
        return True

    def on_mouse_move(self, pos: QPointF) -> bool:
        if self._anchor is None:
            return False
        self._rect = QRectF(self._anchor, pos).normalized()
        self.chart.update()
        return True

    def on_mouse_release(self, pos: QPointF) -> bool:
        if self._anchor is None:
            return False
        self._rect = QRectF(self._anchor, pos).normalized()
        self._anchor = None
        if self._rect is not None and self._rect.width() < 3 and self._rect.height() < 3:
            self._rect = None  # 视为单击：清除选区
            self.selected_items = []
        else:
            self._collect()
        self.chart.update()
        if self._rect is not None:
            self.selected.emit(list(self.selected_items))
        return True

    def _collect(self) -> None:
        """统计选框内的数据点（经 parse_data_point + coord 映射，通用各系列）。"""
        self.selected_items = []
        coord = self.chart.primary_coord()
        if self._rect is None or not isinstance(coord, GridCoord):
            return
        for r in self.chart.series_renderers:
            if not r.visible:
                continue
            for i, item in enumerate(r.data()):
                x, y = parse_data_point(item, i)
                if y is None:
                    continue
                try:
                    pt = coord.map_point(x, y)
                except Exception:
                    continue
                if self._rect.contains(pt):
                    self.selected_items.append({
                        "series": r.name, "dataIndex": i, "value": y, "x": x,
                    })

    def paint(self, p: QPainter, anim_t: float = 1.0) -> None:
        if self._rect is None or self._rect.isNull():
            return
        plot = self._plot()
        rect = self._rect.intersected(plot) if not plot.isNull() else self._rect
        p.save()
        # outOfBrush：框外降透明遮罩
        if self.opt.get("outOfBrush") and not plot.isNull():
            mask = QColor(T("color.bg.base"))
            op = _to_float((self.opt.get("outOfBrush") or {}).get("opacity"), 0.45)
            mask.setAlpha(int(255 * _clamp(op if op is not None else 0.45, 0.0, 1.0)))
            p.setPen(Qt.NoPen)
            p.setBrush(mask)
            p.drawRect(QRectF(plot.left(), plot.top(),
                              max(0.0, rect.left() - plot.left()), plot.height()))
            p.drawRect(QRectF(rect.right(), plot.top(),
                              max(0.0, plot.right() - rect.right()), plot.height()))
            p.drawRect(QRectF(rect.left(), plot.top(), rect.width(),
                              max(0.0, rect.top() - plot.top())))
            p.drawRect(QRectF(rect.left(), rect.bottom(), rect.width(),
                              max(0.0, plot.bottom() - rect.bottom())))
        fill = QColor(T("color.primary"))
        fill.setAlpha(36)
        p.setBrush(fill)
        pen = QPen(QColor(T("color.primary")), 1.2)
        pen.setStyle(Qt.DashLine)
        p.setPen(pen)
        p.drawRect(rect)
        p.restore()

    def layout(self, rect: QRectF) -> None:
        pass

    def hit_test(self, pos: QPointF):
        return None


# ---------------------------------------------------------------------------
# visualMap
# ---------------------------------------------------------------------------

class VisualMapComponent:
    """连续视觉映射：值 → 颜色，右下 / 底部渐变条 + 两端数值标签。

    option::

        "visualMap": {"min": 0, "max": 100,
                      "inRange": {"colors": ["#EBEFF5", "#3F5E8C"]},
                      "orient": "vertical"|"horizontal"}

    ``map_color(v)`` 为公共方法：系列（map / heatmap 等）经
    ``chart.components`` 查找本组件调用。colors 缺省为
    primary.subtle → primary（T() 实时取，主题感知）。
    """

    option_key = "visualMap"

    def __init__(self, chart, opt):
        self.chart = chart
        self.opt = dict(opt or {})
        self.min = _to_float(self.opt.get("min"), 0.0) or 0.0
        self.max = _to_float(self.opt.get("max"), 100.0)
        if self.max is None:
            self.max = 100.0
        if self.max <= self.min:
            self.max = self.min + 1.0
        self.orient = "horizontal" \
            if str(self.opt.get("orient")) == "horizontal" else "vertical"
        self._bar = QRectF()

    # -- 公共 API ----------------------------------------------------------
    def colors(self) -> list:
        """生效色带（inRange.colors 覆盖；缺省 primary.subtle→primary）。"""
        in_range = self.opt.get("inRange") or {}
        cols = in_range.get("colors") if isinstance(in_range, dict) else None
        if isinstance(cols, list) and len(cols) >= 2:
            return [str(c) for c in cols]
        return [T("color.primary.subtle"), T("color.primary")]

    def map_color(self, v) -> QColor:
        """值 → 颜色（按 min..max 归一后在色带上分段线性插值）。"""
        fv = _to_float(v)
        if fv is None:
            return QColor(T("color.bg.muted"))
        frac = _clamp((fv - self.min) / (self.max - self.min), 0.0, 1.0)
        cols = [QColor(c) for c in self.colors()]
        if len(cols) == 1:
            return cols[0]
        seg = frac * (len(cols) - 1)
        i = min(int(seg), len(cols) - 2)
        t = seg - i
        a, b = cols[i], cols[i + 1]
        return QColor(
            int(a.red() + (b.red() - a.red()) * t),
            int(a.green() + (b.green() - a.green()) * t),
            int(a.blue() + (b.blue() - a.blue()) * t),
        )

    # -- 布局 / 绘制 ---------------------------------------------------------
    def layout(self, rect: QRectF) -> None:
        if self.orient == "vertical":
            w, h = 12.0, min(120.0, max(40.0, rect.height() * 0.4))
            x = rect.right() - w - 34
            y = rect.bottom() - h - 12
        else:
            w, h = min(140.0, max(60.0, rect.width() * 0.35)), 12.0
            x = rect.center().x() - w / 2
            y = rect.bottom() - h - 18
        self._bar = QRectF(x, y, w, h)

    def paint(self, p: QPainter, anim_t: float = 1.0) -> None:
        if self._bar.isNull():
            return
        p.save()
        cols = self.colors()
        if self.orient == "vertical":
            grad = QLinearGradient(self._bar.bottomLeft(), self._bar.topLeft())
        else:
            grad = QLinearGradient(self._bar.topLeft(), self._bar.topRight())
        n = len(cols)
        for i, c in enumerate(cols):
            grad.setColorAt(i / (n - 1) if n > 1 else 0.0, QColor(c))
        path = QPainterPath()
        path.addRoundedRect(self._bar, 3, 3)
        p.setPen(QPen(QColor(T("color.border")), 1))
        p.setBrush(grad)
        p.drawPath(path)
        # 两端数值标签
        font = chart_font(T("font.xs"))
        p.setFont(font)
        fm = QFontMetricsF(font)
        p.setPen(QColor(T("color.text.secondary")))
        hi, lo = format_value(self.max), format_value(self.min)
        if self.orient == "vertical":
            p.drawText(QRectF(self._bar.right() + 4, self._bar.top() - fm.height() / 2,
                              34, fm.height()),
                       Qt.AlignLeft | Qt.AlignVCenter, hi)
            p.drawText(QRectF(self._bar.right() + 4, self._bar.bottom() - fm.height() / 2,
                              34, fm.height()),
                       Qt.AlignLeft | Qt.AlignVCenter, lo)
        else:
            p.drawText(QRectF(self._bar.left() - 38, self._bar.top() - 2,
                              34, fm.height() + 4),
                       Qt.AlignRight | Qt.AlignVCenter, lo)
            p.drawText(QRectF(self._bar.right() + 4, self._bar.top() - 2,
                              34, fm.height() + 4),
                       Qt.AlignLeft | Qt.AlignVCenter, hi)
        p.restore()

    def hit_test(self, pos: QPointF):
        return None


# ---------------------------------------------------------------------------
# timeline
# ---------------------------------------------------------------------------

class ChartTimeline(QObject):
    """图表时间轴：底部轴（节点圆点 + 标签）+ 播放 / 暂停按钮。

    option::

        "timeline": {"data": ["2024", "2025", "2026"],
                     "autoPlay": False, "playInterval": 1500}
        "options": [帧0 option, 帧1 option, ...]   # 顶层

    切换帧：``goto(i)`` → ``chart.update_option(option["options"][i])``。
    当前帧下标与播放状态挂在 chart 上（``_timeline_index`` /
    ``_timeline_playing``），update_option 触发 core 重建组件后状态不丢；
    重建时旧 QTimer 会被停止并删除，不会累积。

    命名 ``ChartTimeline`` 以避开 InstructionX_UIKit 既有 Timeline 组件。
    """

    option_key = "timeline"

    #: 底部条带高度
    BAND_H = 44.0

    def __init__(self, chart, opt):
        super().__init__()
        self.chart = chart
        self.opt = dict(opt or {})
        self.labels = [str(d) for d in (self.opt.get("data") or [])]
        self.current = int(getattr(chart, "_timeline_index", 0) or 0)
        self.current = _clamp(self.current, 0, max(0, len(self.labels) - 1))
        playing = getattr(chart, "_timeline_playing", None)
        if playing is None:
            playing = bool(self.opt.get("autoPlay", False))
        self._playing = bool(playing)
        chart._timeline_playing = self._playing
        # 定时器（父对象 chart；重建时清理旧实例防累积）
        prev = getattr(chart, "_timeline_timer", None)
        if prev is not None:
            try:
                prev.stop()
                prev.deleteLater()
            except Exception:
                pass
        self._timer = QTimer(chart)
        self._timer.setInterval(int(_to_float(self.opt.get("playInterval"), 1500) or 1500))
        self._timer.timeout.connect(self._advance)
        chart._timeline_timer = self._timer
        if self._playing:
            self._timer.start()
        self._band = QRectF()
        self._play_rect = QRectF()
        self._node_pts = []  # [QPointF]

    # -- 帧切换 --------------------------------------------------------------
    def goto(self, index: int) -> None:
        """切换到第 index 帧（经 chart.update_option 合并帧 option）。"""
        n = max(1, len(self.labels))
        index = int(index) % n
        self.current = index
        self.chart._timeline_index = index
        frames = (getattr(self.chart, "_option", {}) or {}).get("options") or []
        if 0 <= index < len(frames) and isinstance(frames[index], dict):
            self.chart.update_option(frames[index])
        else:
            self.chart.update()

    def _advance(self) -> None:
        if self.labels:
            self.goto(self.current + 1)

    def toggle_play(self) -> None:
        """播放 / 暂停切换。"""
        self._playing = not self._playing
        self.chart._timeline_playing = self._playing
        if self._playing:
            self._timer.start()
        else:
            self._timer.stop()
        self.chart.update()

    @property
    def playing(self) -> bool:
        return self._playing

    # -- 布局 / 绘制 ---------------------------------------------------------
    def layout(self, rect: QRectF) -> None:
        h = self.BAND_H
        self._band = QRectF(rect.left() + 8, rect.bottom() - h - 2,
                            max(60.0, rect.width() - 16), h)
        btn = 22.0
        self._play_rect = QRectF(self._band.left(),
                                 self._band.center().y() - btn / 2, btn, btn)
        # 节点均匀分布于按钮右侧区域
        self._node_pts = []
        n = len(self.labels)
        if n:
            x0 = self._play_rect.right() + 24
            x1 = self._band.right() - 16
            cy = self._band.center().y() - 6
            for i in range(n):
                x = x0 if n == 1 else x0 + (x1 - x0) * i / (n - 1)
                self._node_pts.append(QPointF(x, cy))

    def paint(self, p: QPainter, anim_t: float = 1.0) -> None:
        if not self.labels or not self._node_pts:
            return
        p.save()
        font = chart_font(T("font.xs"))
        p.setFont(font)
        fm = QFontMetricsF(font)
        primary = QColor(T("color.primary"))
        c_line = QColor(T("color.border.strong"))
        c_text = QColor(T("color.text.secondary"))
        # 轴线
        p.setPen(QPen(c_line, 1))
        p.drawLine(self._node_pts[0], self._node_pts[-1])
        # 节点 + 标签
        for i, (pt, label) in enumerate(zip(self._node_pts, self.labels)):
            cur = (i == self.current)
            p.setPen(QPen(primary if cur else c_line, 1.6))
            p.setBrush(primary if cur else QColor(T("color.bg.elevated")))
            r = 5.0 if cur else 4.0
            p.drawEllipse(pt, r, r)
            p.setPen(primary if cur else c_text)
            p.drawText(QRectF(pt.x() - 40, pt.y() + 8, 80, fm.height()),
                       Qt.AlignHCenter | Qt.AlignTop, label)
        # 播放 / 暂停按钮
        p.setPen(QPen(c_line, 1.2))
        p.setBrush(QColor(T("color.bg.elevated")))
        p.drawEllipse(self._play_rect)
        c = self._play_rect.center()
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(T("color.text.secondary")))
        if self._playing:
            # 暂停：双竖条
            p.drawRect(QRectF(c.x() - 5, c.y() - 5, 3.4, 10))
            p.drawRect(QRectF(c.x() + 1.6, c.y() - 5, 3.4, 10))
        else:
            # 播放：三角
            path = QPainterPath()
            path.moveTo(QPointF(c.x() - 3.5, c.y() - 5.5))
            path.lineTo(QPointF(c.x() - 3.5, c.y() + 5.5))
            path.lineTo(QPointF(c.x() + 5.5, c.y()))
            path.closeSubpath()
            p.drawPath(path)
        p.restore()

    # -- 交互 ---------------------------------------------------------------
    def on_mouse_press(self, pos: QPointF) -> bool:
        if self._play_rect.adjusted(-3, -3, 3, 3).contains(pos):
            self.toggle_play()
            return True
        for i, pt in enumerate(self._node_pts):
            if (pt.x() - pos.x()) ** 2 + (pt.y() - pos.y()) ** 2 <= 100:
                if i != self.current:
                    self.goto(i)
                return True
        return False

    def hit_test(self, pos: QPointF):
        return None


# ---------------------------------------------------------------------------
# toolbox
# ---------------------------------------------------------------------------

class ToolboxComponent:
    """右上角图标按钮组（自绘小图标）。

    option::

        "toolbox": {"feature": ["saveAsImage", "dataZoom", "restore"]}

    - saveAsImage：``chart.grab()`` 后经 QFileDialog 存 PNG；
      offscreen / 对话框不可用时降级保存到当前目录 ``chart_export.png``；
    - restore：重置全部 dataZoom 组件窗口 + 恢复所有系列显隐；
    - dataZoom：切换 inside 缩放可用状态（``chart.datazoom_enabled``）。

    可注入 ``comp.on_action = fn(name)`` 回调观察点击（测试 / 业务钩子）。
    """

    option_key = "toolbox"

    #: 按钮边长与间距
    BTN = 24.0
    GAP = 6.0

    _KNOWN = ("saveAsImage", "dataZoom", "restore")

    def __init__(self, chart, opt):
        self.chart = chart
        self.opt = dict(opt or {})
        feat = self.opt.get("feature")
        names = []
        if isinstance(feat, dict):
            names = [k for k, v in feat.items() if v]
        elif isinstance(feat, (list, tuple)):
            names = [str(f) for f in feat]
        else:
            names = list(self._KNOWN)
        self.features = [n for n in names if n in self._KNOWN] or list(self._KNOWN)
        #: 动作回调（可注入）：fn(feature_name)
        self.on_action = None
        #: 最近一次 saveAsImage 的保存路径
        self.last_saved = None
        self._buttons = []  # [(name, QRectF)]

    # -- 布局 ----------------------------------------------------------------
    def layout(self, rect: QRectF) -> None:
        self._buttons = []
        n = len(self.features)
        x = rect.right() - 8 - n * self.BTN - (n - 1) * self.GAP
        y = rect.top() + 4
        for name in self.features:
            self._buttons.append((name, QRectF(x, y, self.BTN, self.BTN)))
            x += self.BTN + self.GAP

    def button_rect(self, name: str) -> QRectF:
        """指定功能按钮的矩形（测试定位用，未找到返回空矩形）。"""
        for n, r in self._buttons:
            if n == name:
                return QRectF(r)
        return QRectF()

    # -- 动作 ----------------------------------------------------------------
    def trigger(self, name: str) -> None:
        """执行指定功能（按钮点击或外部调用）。"""
        if callable(self.on_action):
            try:
                self.on_action(name)
            except Exception:
                pass
        if name == "saveAsImage":
            self._save_image()
        elif name == "restore":
            self._restore()
        elif name == "dataZoom":
            cur = bool(getattr(self.chart, "datazoom_enabled", True))
            self.chart.datazoom_enabled = not cur
            self.chart.update()

    def _save_image(self) -> None:
        pm = self.chart.grab()
        path = None
        try:
            if QGuiApplication.platformName() == "offscreen":
                raise RuntimeError("offscreen 环境不使用文件对话框")
            path, _ = QFileDialog.getSaveFileName(
                self.chart, "保存图表", "chart.png", "PNG 图片 (*.png)")
        except Exception:
            path = None
        if not path:
            path = os.path.abspath("chart_export.png")
        try:
            pm.save(path, "PNG")
            self.last_saved = path
        except Exception:
            self.last_saved = None

    def _restore(self) -> None:
        for comp in self.chart.components:
            restore = getattr(comp, "restore", None)
            if callable(restore) and comp is not self:
                try:
                    restore()
                except Exception:
                    pass
        state = getattr(self.chart, "_series_state", {}) or {}
        for name in list(state.keys()):
            self.chart.set_series_visible(name, True)
        self.chart.update()

    # -- 交互 ----------------------------------------------------------------
    def on_mouse_press(self, pos: QPointF) -> bool:
        for name, r in self._buttons:
            if r.adjusted(-2, -2, 2, 2).contains(pos):
                self.trigger(name)
                return True
        return False

    # -- 绘制 ----------------------------------------------------------------
    def paint(self, p: QPainter, anim_t: float = 1.0) -> None:
        if not self._buttons:
            return
        p.save()
        for name, r in self._buttons:
            p.setPen(QPen(QColor(T("color.border")), 1))
            p.setBrush(QColor(T("color.bg.elevated")))
            p.drawRoundedRect(r, 4, 4)
            enabled = name != "dataZoom" or \
                bool(getattr(self.chart, "datazoom_enabled", True))
            c = QColor(T("color.text.secondary")) if enabled \
                else QColor(T("color.text.disabled"))
            pen = QPen(c, 1.5)
            pen.setCapStyle(Qt.RoundCap)
            pen.setJoinStyle(Qt.RoundJoin)
            p.setPen(pen)
            p.setBrush(Qt.NoBrush)
            cx, cy = r.center().x(), r.center().y()
            if name == "saveAsImage":
                self._icon_save(p, cx, cy)
            elif name == "restore":
                self._icon_restore(p, cx, cy)
            elif name == "dataZoom":
                self._icon_zoom(p, cx, cy)
        p.restore()

    @staticmethod
    def _icon_save(p: QPainter, cx: float, cy: float) -> None:
        # 托盘 + 向下箭头
        p.drawLine(QPointF(cx - 7, cy + 5), QPointF(cx + 7, cy + 5))
        p.drawLine(QPointF(cx - 7, cy + 5), QPointF(cx - 7, cy + 1))
        p.drawLine(QPointF(cx + 7, cy + 5), QPointF(cx + 7, cy + 1))
        p.drawLine(QPointF(cx, cy - 6), QPointF(cx, cy + 2))
        p.drawLine(QPointF(cx - 3.5, cy - 1), QPointF(cx, cy + 2.5))
        p.drawLine(QPointF(cx + 3.5, cy - 1), QPointF(cx, cy + 2.5))

    @staticmethod
    def _icon_restore(p: QPainter, cx: float, cy: float) -> None:
        # 圆弧 + 箭头
        rect = QRectF(cx - 6, cy - 6, 12, 12)
        p.drawArc(rect, 40 * 16, 290 * 16)
        p.drawLine(QPointF(cx + 6.2, cy - 2.5), QPointF(cx + 6.2, cy - 6.5))
        p.drawLine(QPointF(cx + 6.2, cy - 6.5), QPointF(cx + 2.2, cy - 6.5))

    @staticmethod
    def _icon_zoom(p: QPainter, cx: float, cy: float) -> None:
        # 放大镜
        p.drawEllipse(QPointF(cx - 1.5, cy - 1.5), 4.5, 4.5)
        p.drawLine(QPointF(cx + 1.8, cy + 1.8), QPointF(cx + 5.5, cy + 5.5))
        p.drawLine(QPointF(cx - 4, cy - 1.5), QPointF(cx + 1, cy - 1.5))
        p.drawLine(QPointF(cx - 1.5, cy - 4), QPointF(cx - 1.5, cy + 1))

    def hit_test(self, pos: QPointF):
        return None


# ---------------------------------------------------------------------------
# 注册
# ---------------------------------------------------------------------------

register_component("dataZoom", DataZoomComponent)
register_component("brush", BrushComponent)
register_component("visualMap", VisualMapComponent)
register_component("timeline", ChartTimeline)
register_component("toolbox", ToolboxComponent)
