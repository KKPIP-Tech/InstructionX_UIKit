# -*- coding: utf-8 -*-
"""图表演示页：InstructionX_UIKit.charts 原生图表引擎全系列演示（ECharts 风格 set_option）。

纯 QPainter 自绘（无 WebView / 无 QtCharts 依赖），覆盖：

- 直角坐标系列：bar / pictorialBar / line / scatter / effectScatter /
  candlestick / boxplot / heatmap（grid 与日历两式）/ parallel / themeRiver；
- 层级占比系列：pie / radar / gauge / funnel / sunburst / treemap；
- 关系流向系列：tree / sankey / graph / lines；
- 坐标系与地图：grid 多系列混合 / polar 折线 / singleAxis 散点 /
  calendar 热力 / map（内置示意地图）；
- 组件综合：markPoint + markLine + markArea + visualMap +
  dataZoom（slider + inside）+ brush + toolbox + timeline 三帧切换。

每个系列一张演示卡（``ChartDemoCard``：ChartWidget 最小约 384x264、宽度随
卡片伸缩 + 下方 ``ParamForm`` 精简参数行，每图 2-4 个有意义参数），参数
变化即按新参数 ``set_option`` 重建图表。卡片由 ``ResponsiveCardGrid``
按页面宽度以 1~3 列断点自适应排布（同排等宽、整排撑满），组件综合演示
大图整行撑满。ChartWidget 自身监听 ``theme_changed`` 实时换肤，
亮 / 暗主题切换无需重建页面。示例数据均为中文语义化数据（月度销量 /
城市天气 / 转化漏斗 / 组织架构等）。
"""

import random
import time

import numpy as np
from PySide6.QtCore import Qt, QThread, QTimer, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QSizePolicy,
    QVBoxLayout,
    QLabel,
    QWidget,
)

from InstructionX_UIKit.charts import ChartWidget
from InstructionX_UIKit.theme import T

from .common import Section, hint_label, make_page
from .playground import ParamForm, PlaygroundPanel, add_specs

__all__ = ["create_page", "ChartDemoCard", "ResponsiveCardGrid"]


# ---------------------------------------------------------------------------
# 语义化示例数据（确定性）
# ---------------------------------------------------------------------------

_MONTHS = ["1月", "2月", "3月", "4月", "5月", "6月",
           "7月", "8月", "9月", "10月", "11月", "12月"]
_CITIES = ["北京", "上海", "广州", "深圳", "杭州", "成都"]
_WEEKDAYS = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]


def _walk(n, seed, lo=2.0, hi=10.0, step=1.6):
    """确定性随机游走序列（n 点，[lo, hi]）。"""
    rnd = random.Random(seed)
    v = rnd.uniform(lo, hi * 0.6)
    out = []
    for _ in range(n):
        v = max(lo, min(hi, v + rnd.uniform(-step, step)))
        out.append(round(v, 1))
    return out


# ---------------------------------------------------------------------------
# 演示卡
# ---------------------------------------------------------------------------

class ChartDemoCard(QFrame):
    """图表演示卡：标题 + ChartWidget + 下方精简参数行。

    参数变化即 ``chart.set_option(build(opts))`` 重建图表；主题切换由
    ChartWidget 自行换肤。``build`` 签名为 ``build(opts: dict) -> dict``
    （返回完整 option）。``specs`` 复用 :func:`add_specs` 规格元组。
    """

    def __init__(self, title, build, specs, hint="", size=(384, 264),
                 auto_apply=True, parent=None):
        super().__init__(parent)
        self.setFrameShape(QFrame.Shape.StyledPanel)  # 命中 QSS 卡片边框
        self.title_text = str(title)
        self._build = build
        self.opts = {}
        # 卡片水平随网格伸缩（同排等宽、整排撑满）
        self.setSizePolicy(QSizePolicy.Policy.Expanding,
                           QSizePolicy.Policy.Preferred)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 8, 10, 10)
        lay.setSpacing(6)

        head = QLabel(self.title_text)
        font = QFont()
        font.setWeight(QFont.Weight(T("font.weight.semibold")))
        head.setFont(font)
        lay.addWidget(head)
        if hint:
            lay.addWidget(hint_label(hint, role="tertiary"))

        self.chart = ChartWidget(self)
        # size 为最小尺寸：宽度随卡片伸缩（resize 自动重排），高度固定
        self.chart.setMinimumWidth(int(size[0]))
        self.chart.setFixedHeight(int(size[1]))
        self.chart.setSizePolicy(QSizePolicy.Policy.Expanding,
                                 QSizePolicy.Policy.Fixed)
        lay.addWidget(self.chart)

        self.form = ParamForm(self)
        add_specs(self.form, self.opts, specs)
        lay.addWidget(self.form)
        self.controls = self.form.controls
        lay.addStretch(1)  # 行高不一致时内容顶对齐

        self.form.changed.connect(lambda *_: self.apply())
        if auto_apply:
            self.apply()

    def apply(self):
        """按当前参数重建 option 并 set_option（播放入场动画）。"""
        self.chart.set_option(self._build(dict(self.opts)))

    def finish_animation(self):
        """直接跳到动画末帧（测试 / 截图用）。"""
        self.chart.anim.set_progress(1.0)


class ResponsiveCardGrid(QWidget):
    """演示卡自适应网格：按可用宽度以 1~max_cols 列断点重排。

    卡片水平 Expanding，同排等宽、整排撑满（各列等拉伸，无排内空洞）；
    宽度变化触发 resizeEvent 时仅在实际列数变化时重排，避免布局抖动。
    """

    def __init__(self, cards, min_card_width=420, max_cols=3, spacing=10,
                 parent=None):
        super().__init__(parent)
        self._cards = list(cards)
        self._min_card_width = max(1, int(min_card_width))
        self._max_cols = max(1, int(max_cols))
        self._cols = -1
        grid = QGridLayout(self)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(int(spacing))
        self._grid = grid
        self._reflow()

    @property
    def cards(self) -> list:
        """网格内全部演示卡（按加入顺序）。"""
        return list(self._cards)

    @property
    def cols(self) -> int:
        """当前列数（1~max_cols，随宽度断点变化）。"""
        return self._cols

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._reflow()

    def _reflow(self) -> None:
        spacing = self._grid.spacing()
        avail = max(1, self.width())
        cols = int((avail + spacing) // (self._min_card_width + spacing))
        cols = max(1, min(self._max_cols, len(self._cards) or 1, cols))
        if cols == self._cols:
            return
        # 清空旧列拉伸（防止残留空列占位）
        for c in range(max(self._grid.columnCount(), self._cols, 0)):
            self._grid.setColumnStretch(c, 0)
        while self._grid.count():
            self._grid.takeAt(0)
        for i, card in enumerate(self._cards):
            self._grid.addWidget(card, i // cols, i % cols)
        for c in range(cols):
            self._grid.setColumnStretch(c, 1)  # 同排等宽、整排撑满
        self._cols = cols


# ---------------------------------------------------------------------------
# 直角坐标系列构建函数
# ---------------------------------------------------------------------------

def _build_bar(o):
    cat = {"type": "category", "data": _MONTHS[:6]}
    val = {"type": "value", "name": "件"}
    s1 = {"type": "bar", "name": "线下门店",
          "data": [120, 132, 101, 134, 156, 230]}
    s2 = {"type": "bar", "name": "线上商城",
          "data": [220, 182, 191, 234, 290, 330]}
    for s in (s1, s2):
        s["barWidth"] = o["barWidth"]
        s["barBorderRadius"] = o["radius"]
        if o["stack"]:
            s["stack"] = "总量"
    if o["horizontal"]:
        x_axis, y_axis = val, cat
    else:
        x_axis, y_axis = cat, val
    return {
        "tooltip": {"trigger": "axis"},
        "legend": {"show": True},
        "grid": {"left": 48, "right": 16, "top": 30, "bottom": 46},
        "xAxis": x_axis, "yAxis": y_axis,
        "series": [s1, s2],
    }


def _build_pictorial(o):
    return {
        "tooltip": {"trigger": "axis"},
        "grid": {"left": 48, "right": 16, "top": 30, "bottom": 30},
        "xAxis": {"type": "category", "data": _CITIES},
        "yAxis": {"type": "value", "name": "mm"},
        "series": [{
            "type": "pictorialBar", "name": "年降雨量",
            "symbol": o["symbol"], "symbolRepeat": o["repeat"],
            "symbolSize": o["size"],
            "data": [580, 1200, 1800, 1950, 1450, 950],
        }],
    }


def _build_line(o):
    beijing = [2, 5, 11, 19, 25, 29, 31, 30, 26, 19, 10, 4]
    shanghai = [5, 8, 12, 18, 23, 27, 31, 31, 27, 22, 15, 8]
    series = []
    for name, data in (("北京", beijing), ("上海", shanghai)):
        s = {"type": "line", "name": name, "data": data,
             "showSymbol": o["symbol"]}
        if o["step"] != "none":
            s["step"] = o["step"]
        else:
            s["smooth"] = o["smooth"]
        if o["area"]:
            s["areaStyle"] = {"opacity": 0.18}
        series.append(s)
    return {
        "tooltip": {"trigger": "axis"},
        "legend": {"show": True},
        "grid": {"left": 44, "right": 16, "top": 30, "bottom": 46},
        "xAxis": {"type": "category", "data": _MONTHS},
        "yAxis": {"type": "value", "name": "℃"},
        "series": series,
    }


def _build_scatter(o):
    rnd = random.Random(20260701)
    data = []
    for _ in range(o["n"]):
        temp = round(rnd.uniform(2, 34), 1)          # 气温
        hum = round(rnd.uniform(25, 95), 1)          # 湿度
        aqi = rnd.randint(20, 180)                   # 第三维：AQI
        data.append([temp, hum, aqi] if o["zmap"] else [temp, hum])
    series = {"type": "scatter", "name": "城市天气样本", "data": data}
    if not o["zmap"]:
        series["symbolSize"] = o["size"]
    return {
        "tooltip": {"trigger": "item"},
        "grid": {"left": 44, "right": 16, "top": 30, "bottom": 34},
        "xAxis": {"type": "value", "name": "气温℃"},
        "yAxis": {"type": "value", "name": "湿度%"},
        "series": [series],
    }


def _build_effect_scatter(o):
    pts = [[116, 40], [121, 31], [113, 23], [120, 30], [104, 31], [109, 34]]
    return {
        "tooltip": {"trigger": "item"},
        "grid": {"left": 44, "right": 16, "top": 30, "bottom": 34},
        "xAxis": {"type": "value", "name": "经度", "min": 98, "max": 126},
        "yAxis": {"type": "value", "name": "纬度", "min": 18, "max": 44},
        "series": [{
            "type": "effectScatter", "name": "热门签到城市",
            "symbolSize": o["size"],
            "rippleEffect": {"period": o["period"], "scale": o["scale"]},
            "data": pts,
        }],
    }


def _build_candlestick(o):
    rnd = random.Random(955)
    price, data = 12.0, []
    for _ in range(o["n"]):
        open_ = price
        close = max(2.0, open_ + rnd.uniform(-1.6, 1.6))
        high = max(open_, close) + rnd.uniform(0.1, 1.0)
        low = max(0.5, min(open_, close) - rnd.uniform(0.1, 1.0))
        data.append([round(open_, 2), round(close, 2),
                     round(low, 2), round(high, 2)])
        price = close
    series = {"type": "candlestick", "name": "示例股价", "data": data}
    if o["width"] > 0:
        series["barWidth"] = o["width"]
    return {
        "tooltip": {"trigger": "axis"},
        "grid": {"left": 48, "right": 16, "top": 30, "bottom": 30},
        "xAxis": {"type": "category",
                  "data": [f"{i + 1}日" for i in range(o["n"])]},
        "yAxis": {"type": "value", "name": "元"},
        "series": [series],
    }


def _build_boxplot(o):
    rnd = random.Random(451)
    groups = [f"{c}组" for c in "ABCDEF"[: o["groups"]]]
    data = []
    for gi in range(o["groups"]):
        vals = sorted(round(rnd.uniform(4, 36), 1) for _ in range(12))
        data.append([vals[0], vals[3], vals[5], vals[8], vals[-1]])
    series = {"type": "boxplot", "name": "加班工时", "data": data}
    if o["width"] > 0:
        series["barWidth"] = o["width"]
    return {
        "tooltip": {"trigger": "item"},
        "grid": {"left": 44, "right": 16, "top": 30, "bottom": 30},
        "xAxis": {"type": "category", "data": groups},
        "yAxis": {"type": "value", "name": "小时"},
        "series": [series],
    }


#: 热力图色带（数据可视化专用，故意硬编码、豁免主题令牌：色带是图表的
#: 数值编码维度，非主题语义色，亮 / 暗主题下保持同一套色带以稳定对比）
_HEAT_RAMP = {
    "blue": ["#EBEFF5", "#3F5E8C"],
    "warm": ["#FDF3E3", "#D6473C"],
}

#: 仪表盘分段色带（同 _HEAT_RAMP：数据可视化色带，豁免主题令牌）
_GAUGE_RAMP = [[0.6, "#3FA46A"], [0.85, "#C78A2B"], [1.0, "#E64545"]]


def _build_heatmap_grid(o):
    hours = [f"{h}时" for h in range(8, 20, 2)]
    rnd = random.Random(77)
    data = []
    for xi in range(len(hours)):
        for yi in range(len(_WEEKDAYS)):
            base = 30 if yi < 5 else 8
            peak = 70 if xi in (2, 3) else 0
            data.append([xi, yi, rnd.randint(0, 20) + base + peak])
    opt = {
        "tooltip": {"trigger": "item"},
        "grid": {"left": 52, "right": 16, "top": 30, "bottom": 30},
        "xAxis": {"type": "category", "data": hours},
        "yAxis": {"type": "category", "data": _WEEKDAYS},
        "series": [{"type": "heatmap", "name": "客流量", "data": data}],
    }
    if o["visualMap"]:
        opt["visualMap"] = {"min": 0, "max": 120,
                            "inRange": {"colors": _HEAT_RAMP[o["ramp"]]},
                            "orient": "vertical"}
    return opt


def _year_data(year, seed=9):
    """生成某年约 200 天的随机活跃度（日历热力数据）。"""
    import datetime as _dt
    rnd = random.Random(seed + year)
    data = []
    day = _dt.date(year, 1, 1)
    while day.year == year:
        if rnd.random() < 0.55:
            data.append([day.isoformat(), rnd.randint(1, 12)])
        day += _dt.timedelta(days=1)
    return data


def _build_heatmap_calendar(o):
    opt = {
        "tooltip": {"trigger": "item"},
        "calendar": {"year": int(o["year"]), "cellSize": o["cell"]},
        "series": [{"type": "heatmap", "name": "代码提交",
                    "coordinateSystem": "calendar",
                    "data": _year_data(int(o["year"]))}],
    }
    if o["visualMap"]:
        opt["visualMap"] = {"min": 0, "max": 12, "orient": "vertical"}
    return opt


def _build_parallel(o):
    subjects = ["语文", "数学", "英语", "物理", "化学"][: o["dims"]]
    rnd = random.Random(33)
    rows = [[rnd.randint(55, 99) for _ in subjects]
            for _ in range(o["n"])]
    return {
        "tooltip": {"trigger": "item"},
        "parallelAxis": [{"name": s, "min": 40, "max": 100}
                         for s in subjects],
        "series": [{"type": "parallel", "name": "学生成绩", "data": rows}],
    }


def _build_themeriver(o):
    topics = ["新机发布", "系统更新", "售后服务", "线下活动", "联名合作"]
    topics = topics[: o["series"]]
    rnd = random.Random(2026)
    data = []
    for mi in range(o["months"]):
        for ti, t in enumerate(topics):
            v = 6 + int(10 * (1 + mi % 3) / (ti + 1)) + rnd.randint(0, 8)
            data.append([f"2026-{mi + 1:02d}", v, t])
    return {
        "tooltip": {"trigger": "item"},
        "legend": {"show": True},
        "series": [{"type": "themeRiver", "name": "话题热度", "data": data}],
    }


# ---------------------------------------------------------------------------
# 层级占比系列构建函数
# ---------------------------------------------------------------------------

def _build_pie(o):
    series = {
        "type": "pie", "name": "部门预算",
        "data": [
            {"name": "研发", "value": 420}, {"name": "市场", "value": 260},
            {"name": "运营", "value": 180}, {"name": "设计", "value": 120},
            {"name": "行政", "value": 80},
        ],
        "label": {"show": True, "position": o["labelPos"]},
    }
    if o["donut"]:
        series["radius"] = ["42%", "72%"]
    else:
        series["radius"] = "72%"
    if o["rose"] != "none":
        series["roseType"] = o["rose"]
    return {
        "tooltip": {"trigger": "item"},
        "legend": {"show": True, "orient": "vertical", "right": 4},
        "series": [series],
    }


def _build_radar(o):
    dims = [("功能", 100), ("性能", 100), ("易用", 100),
            ("稳定", 100), ("生态", 100), ("服务", 100)]
    series = {
        "type": "radar", "name": "产品评估",
        "indicator": [{"name": n, "max": m} for n, m in dims],
        "shape": o["shape"],
        "splitNumber": o["split"],
        "data": [
            {"name": "本季度", "value": [82, 90, 70, 88, 60, 76]},
            {"name": "上季度", "value": [70, 78, 66, 80, 55, 70]},
        ],
    }
    if o["area"]:
        series["areaStyle"] = {"opacity": 0.22}
    return {
        "tooltip": {"trigger": "item"},
        "legend": {"show": True},
        "series": [series],
    }


def _build_gauge(o):
    series = {
        "type": "gauge", "name": "季度目标完成率",
        "min": 0, "max": 100,
        "data": [{"name": "完成率", "value": o["value"]}],
        "pointer": {"show": True, "length": "62%"},
        "anchor": {"show": True},
        "detail": {"show": True},
        "title": {"show": True},
    }
    if o["progress"]:
        series["progress"] = {"show": True, "width": 10}
    if o["segments"]:
        series["axisLine"] = {"lineStyle": {"width": 10, "color": _GAUGE_RAMP}}
    return {"tooltip": {"show": False}, "series": [series]}


def _build_funnel(o):
    return {
        "tooltip": {"trigger": "item"},
        "series": [{
            "type": "funnel", "name": "注册转化",
            "sort": o["sort"], "gap": o["gap"],
            "label": {"show": True, "position": o["labelPos"]},
            "data": [
                {"name": "访问落地页", "value": 100},
                {"name": "点击注册", "value": 64},
                {"name": "填写资料", "value": 42},
                {"name": "完成认证", "value": 26},
                {"name": "首次付费", "value": 12},
            ],
        }],
    }


def _build_sunburst(o):
    return {
        "tooltip": {"trigger": "item"},
        "series": [{
            "type": "sunburst", "name": "营收构成",
            "radius": ["18%", "92%"],
            "label": {"show": o["labels"], "minAngle": o["minAngle"]},
            "data": [
                {"name": "硬件", "children": [
                    {"name": "手机", "value": 46},
                    {"name": "平板", "value": 22},
                    {"name": "穿戴", "value": 14}]},
                {"name": "软件", "children": [
                    {"name": "云服务", "value": 30},
                    {"name": "应用商店", "value": 18}]},
                {"name": "内容", "children": [
                    {"name": "视频", "value": 12},
                    {"name": "音乐", "value": 8},
                    {"name": "阅读", "value": 5}]},
            ],
        }],
    }


def _build_treemap(o):
    return {
        "tooltip": {"trigger": "item"},
        "series": [{
            "type": "treemap", "name": "存储占用",
            "gapWidth": o["gap"], "label": {"show": o["labels"]},
            "breadcrumb": {"show": o["crumb"]},
            "data": [
                {"name": "视频", "children": [
                    {"name": "电影", "value": 46},
                    {"name": "剧集", "value": 30}]},
                {"name": "照片", "children": [
                    {"name": "相机相册", "value": 28},
                    {"name": "截图", "value": 6}]},
                {"name": "应用", "value": 24},
                {"name": "文档", "value": 10},
                {"name": "系统", "value": 16},
            ],
        }],
    }


# ---------------------------------------------------------------------------
# 关系流向系列构建函数
# ---------------------------------------------------------------------------

def _build_tree(o):
    return {
        "tooltip": {"trigger": "item"},
        "series": [{
            "type": "tree", "name": "组织架构",
            "orient": o["orient"], "edge": o["edge"],
            "symbolSize": o["size"],
            "label": {"show": True},
            "data": [{
                "name": "总经理", "children": [
                    {"name": "技术中心", "children": [
                        {"name": "前端组"}, {"name": "后端组"},
                        {"name": "算法组"}]},
                    {"name": "产品中心", "children": [
                        {"name": "产品组"}, {"name": "设计组"}]},
                    {"name": "运营中心", "children": [
                        {"name": "市场组"}, {"name": "客服组"}]},
                ],
            }],
        }],
    }


def _build_sankey(o):
    return {
        "tooltip": {"trigger": "item"},
        "series": [{
            "type": "sankey", "name": "能源流向",
            "nodeWidth": o["nodeWidth"], "nodeGap": o["nodeGap"],
            "layoutIterations": o["iters"],
            "label": {"show": True},
            "data": [{"name": n} for n in
                     ("煤炭", "水电", "风电", "光伏",
                      "工业", "居民", "交通", "损耗")],
            "links": [
                {"source": "煤炭", "target": "工业", "value": 46},
                {"source": "煤炭", "target": "居民", "value": 12},
                {"source": "水电", "target": "工业", "value": 18},
                {"source": "水电", "target": "居民", "value": 10},
                {"source": "风电", "target": "交通", "value": 8},
                {"source": "风电", "target": "居民", "value": 6},
                {"source": "光伏", "target": "工业", "value": 9},
                {"source": "光伏", "target": "损耗", "value": 3},
                {"source": "煤炭", "target": "损耗", "value": 8},
            ],
        }],
    }


def _build_graph(o):
    return {
        "tooltip": {"trigger": "item"},
        "series": [{
            "type": "graph", "name": "知识图谱",
            "layout": o["layout"],
            "force": {"repulsion": o["repulsion"], "seed": 42},
            "symbolSize": o["size"],
            "label": {"show": True},
            "data": [
                {"name": "芯片", "symbolSize": o["size"] + 8},
                {"name": "手机"}, {"name": "汽车"}, {"name": "家电"},
                {"name": "操作系统"}, {"name": "应用生态"},
                {"name": "云服务"}, {"name": "人工智能"},
            ],
            "links": [
                {"source": "芯片", "target": "手机"},
                {"source": "芯片", "target": "汽车"},
                {"source": "芯片", "target": "家电"},
                {"source": "操作系统", "target": "手机"},
                {"source": "操作系统", "target": "应用生态"},
                {"source": "应用生态", "target": "云服务"},
                {"source": "人工智能", "target": "云服务"},
                {"source": "人工智能", "target": "汽车"},
                {"source": "人工智能", "target": "芯片"},
            ],
        }],
    }


def _build_lines(o):
    city = {"北京": (116.4, 39.9), "上海": (121.5, 31.2),
            "广州": (113.3, 23.1), "深圳": (114.1, 22.5),
            "成都": (104.1, 30.7), "西安": (108.9, 34.3),
            "武汉": (114.3, 30.6), "昆明": (102.8, 24.9)}
    routes = [("北京", "上海"), ("北京", "广州"), ("北京", "成都"),
              ("上海", "深圳"), ("上海", "武汉"), ("广州", "昆明"),
              ("成都", "西安"), ("西安", "北京"), ("武汉", "深圳")]
    return {
        "tooltip": {"trigger": "item"},
        "grid": {"left": 44, "right": 16, "top": 30, "bottom": 34},
        "xAxis": {"type": "value", "name": "经度", "min": 98, "max": 126},
        "yAxis": {"type": "value", "name": "纬度", "min": 18, "max": 44},
        "series": [{
            "type": "lines", "name": "热门航线",
            "lineStyle": {"width": o["width"], "curveness": o["curveness"]},
            "trailEffect": {"show": o["trail"], "period": 4,
                            "symbolSize": 5},
            "data": [{"coords": [list(city[a]), list(city[b])]}
                     for a, b in routes],
        }],
    }


# ---------------------------------------------------------------------------
# 坐标系与地图构建函数
# ---------------------------------------------------------------------------

def _build_grid_mix(o):
    months = _MONTHS[:8]
    series = [
        {"type": "bar", "name": "销量",
         "data": [120, 200, 150, 260, 220, 300, 280, 340],
         "barWidth": 0.5, "barBorderRadius": 3},
        {"type": "line", "name": "均价",
         "data": [86, 92, 78, 105, 98, 120, 112, 128],
         "smooth": o["smooth"], "yAxisIndex": 0},
    ]
    if o["area"]:
        series[1]["areaStyle"] = {"opacity": 0.15}
    if o["scatter"]:
        series.append({"type": "scatter", "name": "促销节点",
                       "symbolSize": 14,
                       "data": [[1, 200], [3, 260], [5, 300], [7, 340]]})
    return {
        "tooltip": {"trigger": "axis"},
        "legend": {"show": True},
        "grid": {"left": 48, "right": 16, "top": 30, "bottom": 46},
        "xAxis": {"type": "category", "data": months},
        "yAxis": {"type": "value", "name": "量"},
        "series": series,
    }


def _build_polar(o):
    directions = ["北", "东北", "东", "东南", "南", "西南", "西", "西北"]
    freq = [12, 8, 15, 22, 18, 9, 6, 10]
    series = {
        "type": "line", "name": "风向频率", "coordinateSystem": "polar",
        "smooth": o["smooth"],
        "data": [[d, v] for d, v in zip(directions, freq)],
    }
    if o["area"]:
        series["areaStyle"] = {"opacity": 0.2}
    return {
        "tooltip": {"trigger": "item"},
        "polar": {"shape": o["shape"]},
        "angleAxis": {"type": "category", "data": directions},
        "radiusAxis": {"type": "value"},
        "series": [series],
    }


def _build_single_axis(o):
    rnd = random.Random(601)
    data = [round(rnd.gauss(75, 12), 1) for _ in range(o["n"])]
    return {
        "tooltip": {"trigger": "item"},
        "singleAxis": {"left": 40, "right": 40, "name": "分数"},
        "series": [{
            "type": "scatter", "name": "期末成绩分布",
            "coordinateSystem": "singleAxis",
            "symbolSize": o["size"],
            "data": data,
        }],
    }


def _build_calendar_coord(o):
    return {
        "tooltip": {"trigger": "item"},
        "calendar": {"year": int(o["year"]), "cellSize": o["cell"]},
        "visualMap": {"min": 0, "max": 12,
                      "inRange": {"colors": _HEAT_RAMP["warm"]},
                      "orient": "vertical"},
        "series": [{"type": "heatmap", "name": "每日步数(千)",
                    "coordinateSystem": "calendar",
                    "data": _year_data(int(o["year"]), seed=41)}],
    }


def _build_map(o):
    opt = {
        "tooltip": {"trigger": "item"},
        "series": [{
            "type": "map", "name": "区域销量", "map": "demo",
            "data": [
                {"name": "华北", "value": 82}, {"name": "东北", "value": 36},
                {"name": "华东", "value": 95}, {"name": "华南", "value": 71},
                {"name": "华中", "value": 58}, {"name": "西南", "value": 44},
                {"name": "西北", "value": 27},
            ],
        }],
    }
    if o["visualMap"]:
        opt["visualMap"] = {"min": 0, "max": 100,
                            "inRange": {"colors": _HEAT_RAMP[o["ramp"]]},
                            "orient": o["orient"]}
    return opt


# ---------------------------------------------------------------------------
# 组件综合演示
# ---------------------------------------------------------------------------

_COMP_YEARS = {
    "2024": {"bar": [150, 180, 132, 210, 190, 260, 240, 300, 280, 330, 310, 380],
             "line": [96, 102, 88, 115, 108, 130, 122, 138, 131, 145, 140, 158]},
    "2025": {"bar": [180, 210, 168, 240, 220, 290, 270, 330, 310, 360, 345, 420],
             "line": [104, 112, 98, 126, 118, 142, 133, 150, 142, 156, 150, 172]},
    "2026": {"bar": [210, 250, 200, 280, 260, 330, 310, 370, 350, 400, 390, 460],
             "line": [112, 124, 108, 138, 129, 154, 145, 163, 154, 170, 163, 186]},
}


def _comp_series(o, year):
    """综合演示某年度的完整系列定义（timeline 帧为 list 替换语义，
    帧内必须携带 type/name/标注，不能只给 data）。"""
    y = _COMP_YEARS[year]
    bar = {"type": "bar", "name": "月度销量", "data": y["bar"],
           "barWidth": 0.55, "barBorderRadius": 3}
    line = {"type": "line", "name": "月度均价", "data": y["line"],
            "smooth": True,
            "markPoint": {"data": [{"type": "max"}, {"type": "min"}]},
            "markLine": {"data": _comp_markline(o["markLine"])}}
    if o["markArea"]:
        line["markArea"] = {"data": [[{"xAxis": "3月"}, {"xAxis": "5月"}]]}
    return [bar, line]


def _build_comprehensive(o):
    """组件综合：bar+line + mark* + visualMap + dataZoom + brush + toolbox + timeline。"""
    opt = {
        "title": {"text": "年度销售总览", "subtext": "拖动时间轴切换年度"},
        "tooltip": {"trigger": "axis"},
        "legend": {"show": True},
        "grid": {"left": 52, "right": 56, "top": 56, "bottom": 108},
        "xAxis": {"type": "category", "data": _MONTHS},
        "yAxis": {"type": "value", "name": "量"},
        "series": _comp_series(o, "2024"),
        "dataZoom": [{"type": "slider", "start": 0, "end": o["zoomEnd"]},
                     {"type": "inside"}],
        "brush": {"toolbox": ["rect", "clear"],
                  "outOfBrush": {"opacity": 0.35}},
        "toolbox": {"feature": ["saveAsImage", "dataZoom", "restore"]},
        "timeline": {"data": list(_COMP_YEARS), "autoPlay": False},
        "options": [{"series": _comp_series(o, year)}
                    for year in _COMP_YEARS],
    }
    if o["visualMap"]:
        opt["visualMap"] = {"min": 60, "max": 460,
                            "inRange": {"colors": _HEAT_RAMP["warm"]},
                            "orient": "vertical"}
    return opt


def _comp_markline(kind):
    if kind == "average":
        return [{"type": "average", "name": "均值"}]
    if kind == "max":
        return [{"type": "max", "name": "峰值"}]
    return [{"yAxis": 300, "name": "警戒线"}]


# ---------------------------------------------------------------------------
# 卡片规格表：(标题, 构建函数, 参数规格, 提示)
# ---------------------------------------------------------------------------

_SYMBOL_OPTS = [("矩形", "rect"), ("圆形", "circle"), ("图钉", "pin")]
_STEP_OPTS = [("无", "none"), ("起点", "start"),
              ("中点", "middle"), ("终点", "end")]
_RAMP_OPTS = [("主题蓝", "blue"), ("暖色", "warm")]
_CELL_OPTS = [("自动", "auto"), ("小 10", 10), ("中 14", 14), ("大 18", 18)]
_YEAR_OPTS = [("2024 年", 2024), ("2025 年", 2025), ("2026 年", 2026)]

_CARTESIAN_CARDS = [
    ("bar 柱状图 · 月度销量", _build_bar,
     [("bool", "stack", "堆叠", False),
      ("float", "barWidth", "柱宽占比", 0.6, 0.2, 0.9, {"step": 0.1}),
      ("int", "radius", "圆角", 3, 0, 10),
      ("bool", "horizontal", "水平条形", False)],
     "stack / barWidth / barBorderRadius；yAxis 为 category 时自动水平"),
    ("pictorialBar 象形柱图 · 城市降雨量", _build_pictorial,
     [("choice", "symbol", "符号", "circle", list(_SYMBOL_OPTS)),
      ("bool", "repeat", "重复堆叠", True),
      ("int", "size", "符号尺寸", 12, 6, 24)],
     "symbol / symbolRepeat / symbolSize"),
    ("line 折线图 · 月均气温", _build_line,
     [("bool", "smooth", "平滑", True),
      ("bool", "area", "面积填充", False),
      ("choice", "step", "阶梯", "none", list(_STEP_OPTS)),
      ("bool", "symbol", "数据点", True)],
     "smooth / areaStyle / step / showSymbol（阶梯开启时覆盖平滑）"),
    ("scatter 散点图 · 气温×湿度", _build_scatter,
     [("int", "n", "样本数", 40, 8, 120),
      ("bool", "zmap", "第三维映射大小", True),
      ("int", "size", "固定点径", 12, 4, 24)],
     "symbolSize 固定值或按第三维（AQI）6~24px 映射"),
    ("effectScatter 涟漪散点 · 热门签到城市", _build_effect_scatter,
     [("float", "period", "涟漪周期(秒)", 3.0, 1.0, 6.0, {"step": 0.5}),
      ("float", "scale", "扩散倍数", 2.6, 1.5, 4.0, {"step": 0.1}),
      ("int", "size", "点径", 12, 6, 20)],
     "rippleEffect: {period, scale}（QTimer 驱动扩散圆）"),
    ("candlestick K线 · 示例股价", _build_candlestick,
     [("int", "n", "交易日数", 30, 10, 60),
      ("int", "width", "实体宽(0=自动)", 0, 0, 24)],
     "OHLC 数据；红涨绿跌（colorUp / colorDown 可覆盖）"),
    ("boxplot 箱线图 · 加班工时分布", _build_boxplot,
     [("int", "groups", "组数", 4, 2, 6),
      ("int", "width", "箱体宽(0=自动)", 0, 0, 28)],
     "数据 [min, Q1, 中位, Q3, max]"),
    ("heatmap 热力图(grid) · 时段×星期客流量", _build_heatmap_grid,
     [("bool", "visualMap", "视觉映射", True),
      ("choice", "ramp", "色带", "blue", list(_RAMP_OPTS))],
     "配合顶层 visualMap（inRange.colors）或默认主题色带"),
    ("heatmap 热力图(日历) · 代码提交", _build_heatmap_calendar,
     [("choice", "year", "年份", 2026, list(_YEAR_OPTS)),
      ("choice", "cell", "单元格", "auto", list(_CELL_OPTS)),
      ("bool", "visualMap", "视觉映射", False)],
     "coordinateSystem: calendar；calendar: {year, cellSize}"),
    ("parallel 平行坐标 · 学生成绩", _build_parallel,
     [("int", "dims", "维度数", 5, 3, 5),
      ("int", "n", "学生数", 6, 3, 12)],
     "parallelAxis 定义维度；每行数据一条折线穿轴"),
    ("themeRiver 主题河 · 话题热度", _build_themeriver,
     [("int", "series", "话题数", 4, 2, 5),
      ("int", "months", "月数", 8, 4, 12)],
     "数据 [时间, 值, 系列名]；流带平滑 + 居中基线"),
]

_HIERARCHY_CARDS = [
    ("pie 饼图 · 部门预算", _build_pie,
     [("bool", "donut", "环形", True),
      ("choice", "rose", "玫瑰图", "none",
       [("无", "none"), ("半径", "radius"), ("面积", "area")]),
      ("choice", "labelPos", "标签位置", "outside",
       [("外部引线", "outside"), ("内部百分比", "inside"),
        ("中心总计", "center")])],
     "radius: [内,外] 环形 / roseType 南丁格尔 / label.position"),
    ("radar 雷达图 · 产品评估", _build_radar,
     [("choice", "shape", "形状", "polygon",
       [("多边形", "polygon"), ("圆形", "circle")]),
      ("bool", "area", "面积填充", True),
      ("int", "split", "圈环数", 5, 3, 6)],
     "indicator: [{name, max}]；多系列各一个多边形"),
    ("gauge 仪表盘 · 目标完成率", _build_gauge,
     [("int", "value", "目标值(%)", 72, 0, 100),
      ("bool", "progress", "进度弧", True),
      ("bool", "segments", "分段色", True)],
     "min/max / progress / axisLine 色段 / pointer / detail"),
    ("funnel 漏斗图 · 注册转化", _build_funnel,
     [("choice", "sort", "排序", "descending",
       [("降序", "descending"), ("升序", "ascending"),
        ("原序", "none")]),
      ("int", "gap", "层间距", 2, 0, 8),
      ("choice", "labelPos", "标签", "outer",
       [("外侧", "outer"), ("层内", "inside")])],
     "sort / gap / label.position"),
    ("sunburst 旭日图 · 营收构成", _build_sunburst,
     [("bool", "labels", "旋转标签", True),
      ("int", "minAngle", "标签角阈值", 8, 0, 20)],
     "层级 data: [{name, value, children}]；radius 内孔/外半径"),
    ("treemap 矩形树图 · 存储占用", _build_treemap,
     [("bool", "crumb", "路径条", True),
      ("int", "gap", "间隙", 1, 0, 4),
      ("bool", "labels", "名称标签", True)],
     "squarified 布局；breadcrumb / gapWidth / label"),
]

_RELATION_CARDS = [
    ("tree 树图 · 组织架构", _build_tree,
     [("choice", "orient", "方向", "LR",
       [("左右", "LR"), ("上下", "TB")]),
      ("choice", "edge", "边样式", "polyline",
       [("正交折线", "polyline"), ("贝塞尔曲线", "curve")]),
      ("int", "size", "节点直径", 8, 4, 14)],
     "orient: LR/TB；edge: polyline/curve"),
    ("sankey 桑基图 · 能源流向", _build_sankey,
     [("int", "nodeWidth", "节点宽", 14, 6, 24),
      ("int", "nodeGap", "节点间距", 10, 4, 20),
      ("int", "iters", "布局迭代", 6, 0, 12)],
     "nodes/links；layoutIterations 减少流带交叉"),
    ("graph 关系图 · 知识图谱", _build_graph,
     [("choice", "layout", "布局", "force",
       [("力导", "force"), ("圆环", "circular")]),
      ("float", "repulsion", "斥力", 1.0, 0.2, 3.0, {"step": 0.2}),
      ("int", "size", "节点直径", 14, 8, 24)],
     "layout: force（确定性随机种子）/ circular"),
    ("lines 线图 · 热门航线", _build_lines,
     [("float", "curveness", "弯曲度", 0.2, 0.0, 0.5, {"step": 0.05}),
      ("bool", "trail", "移动亮点", True),
      ("int", "width", "线宽", 2, 1, 4)],
     "data: [{coords: [[x1,y1],[x2,y2]]}]；trailEffect 尾迹动画"),
]

_COORD_CARDS = [
    ("grid 坐标系 · 柱线点混合", _build_grid_mix,
     [("bool", "smooth", "折线平滑", True),
      ("bool", "area", "面积填充", False),
      ("bool", "scatter", "叠加散点", True)],
     "xAxis/yAxis + bar/line/scatter 多系列混合"),
    ("polar 坐标系 · 风向频率折线", _build_polar,
     [("choice", "shape", "形状", "polygon",
       [("多边形", "polygon"), ("圆形", "circle")]),
      ("bool", "area", "面积填充", True),
      ("bool", "smooth", "平滑", False)],
     "polar/angleAxis/radiusAxis + line(coordinateSystem=polar)"),
    ("singleAxis 坐标系 · 成绩分布散点", _build_single_axis,
     [("int", "n", "样本数", 40, 10, 100),
      ("int", "size", "点径", 10, 4, 20)],
     "singleAxis + scatter(coordinateSystem=singleAxis)"),
    ("calendar 坐标系 · 每日步数热力", _build_calendar_coord,
     [("choice", "year", "年份", 2026, list(_YEAR_OPTS)),
      ("choice", "cell", "单元格", "auto", list(_CELL_OPTS))],
     "calendar: {year, cellSize} + heatmap(coordinateSystem=calendar)"),
    ("map 地图 · 区域销量（示意数据）", _build_map,
     [("bool", "visualMap", "视觉映射", True),
      ("choice", "ramp", "色带", "blue", list(_RAMP_OPTS)),
      ("choice", "orient", "映射条方向", "vertical",
       [("纵向", "vertical"), ("横向", "horizontal")])],
     "map: \"demo\" 内置 7 大区块示意地图；可经 geo.regions 自定义多边形"),
]

_COMP_SPECS = [
    ("choice", "markLine", "标线", "average",
     [("平均线", "average"), ("最大值线", "max"), ("警戒线 300", "threshold")]),
    ("bool", "markArea", "标域(3~5月)", True),
    ("bool", "visualMap", "视觉映射", False),
    ("int", "zoomEnd", "缩放窗口(%)", 100, 20, 100),
]

_COMP_KEYS = ("涉及 option 键：series.markPoint / series.markLine / "
              "series.markArea / visualMap / dataZoom(slider+inside) / "
              "brush / toolbox / timeline(+options 三帧)。可交互："
              "滚轮缩放、滑块窗口、矩形刷选、右上角工具按钮、底部时间轴播放。")


# ---------------------------------------------------------------------------
# 页面组装
# ---------------------------------------------------------------------------

def _make_cards(specs) -> list:
    return [ChartDemoCard(title, build, spec, hint=hint)
            for title, build, spec, hint in specs]


def _comprehensive_section() -> Section:
    """组件综合演示：大图 + 右侧参数面板 + option 键说明。"""
    box = Section("组件综合演示（标注 / 视觉映射 / 缩放 / 刷选 / 工具箱 / 时间轴）")
    host = QWidget()
    lay = QGridLayout(host)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(10)

    card = ChartDemoCard("年度销售总览 · 组件综合", _build_comprehensive,
                         [], hint="", size=(560, 420), auto_apply=False)
    lay.addWidget(card, 0, 0)

    panel = PlaygroundPanel("演示参数", width=252)
    opts = card.opts
    add_specs(panel.form, opts, _COMP_SPECS)
    panel.form.changed.connect(lambda *_: card.apply())
    card.apply()
    card.panel = panel  # 便于测试访问

    side = QWidget()
    side_lay = QVBoxLayout(side)
    side_lay.setContentsMargins(0, 0, 0, 0)
    side_lay.setSpacing(8)
    side_lay.addWidget(panel)
    side_lay.addWidget(hint_label(_COMP_KEYS, role="tertiary"))
    side_lay.addStretch(1)
    lay.addWidget(side, 0, 1)
    lay.setColumnStretch(0, 1)

    box.layout().addWidget(host)
    box.card = card  # 便于测试访问
    return box


# ---------------------------------------------------------------------------
# 巨量数据综合演示
# ---------------------------------------------------------------------------

#: 巨量数据的默认点数（OpenGL 渲染的目标场景量级）
_MASSIVE_DEFAULT_N = 1_500_000

#: 点数滑块上限（数据接入本身在毫秒级，此处上限取 500 万以显示余量）
_MASSIVE_MAX_N = 5_000_000

#: 实时滚动流的生产者节奏：每 ``_LIVE_SAMPLE_INTERVAL_MS`` 毫秒推一批
#: ``_LIVE_BATCH`` 个点，合计约 ``_LIVE_RATE`` 点/秒（高速传感器量级）。
#:
#: **速率为什么不能只取 50 点/秒**：定长窗口（默认 2 万点）在 50 点/秒下要
#: 约 7 分钟才写满，演示里既看不到曲线左移、也看不到窗口丢弃最旧点——等于没
#: 演示出「滚动流」这个形态。取千点量级后窗口在一分钟内写满，滚动与丢弃都
#: 立刻可见；读数里同时给出实测与目标，口径是透明的。
_LIVE_SAMPLE_INTERVAL_MS = 30
_LIVE_BATCH = 30
_LIVE_RATE = int(_LIVE_BATCH * 1000 / _LIVE_SAMPLE_INTERVAL_MS)

#: 实时滚动流的读数刷新节奏（毫秒）。**不得设为 0**：那会让事件循环不停地
#: 堆积重绘请求，在单帧长达数秒的极端配置下会把进程拖垮。
_LIVE_INTERVAL_MS = 16

#: 实时滚动流默认保留的窗口点数（写入环形缓冲的容量上界）。
#:
#: 默认取 20,000 点（约 20 秒 / 1000 点每秒）：信号主频是 ``sin(0.9·t)``，
#: 周期约 7 秒，故 20 秒窗口里能看到约 3 个完整周期——曲线一眼可辨。窗口太小
#: （如 500 点 = 0.5 秒）只会截到相位的一小段，画出来近似一条斜线。
_LIVE_WINDOW = 20_000

#: 单帧超过该耗时（毫秒）时暂停实时滚动：此时测到的是「几秒一帧」，
#: 既无参考价值，又会把界面拖住。读数条会说明原因。
_LIVE_MAX_FRAME_MS = 120.0


class _LiveSensor(QThread):
    """模拟高速传感器：按固定周期产出一批采样点（独立线程）。

    线程只做「造数 + 发信号」，信号在 GUI 线程被投进流式会话的环形缓冲，
    因此这里不触碰任何界面对象。信号用队列连接，天然跨线程安全。
    """

    #: 一批采样点（长度 ``_LIVE_BATCH`` 的 ndarray）
    batch = Signal(object)

    def __init__(self, interval_ms: int = _LIVE_SAMPLE_INTERVAL_MS,
                 batch: int = _LIVE_BATCH, parent=None) -> None:
        super().__init__(parent)
        self._step = max(1, int(interval_ms)) / 1000.0
        self._batch = max(1, int(batch))
        self._phase = 0.0
        self._rate = self._batch / self._step        # 采样率（点/秒）

    def run(self) -> None:  # noqa: N802 - Qt 覆写
        rnd = np.random.default_rng(7)
        step = 1.0 / self._rate                      # 相邻采样点的时间间隔
        while not self.isInterruptionRequested():
            # 与 _massive_signal 同族（低频趋势 + 中频细节 + 噪声），但相位
            # 连续，故滚动窗口内是一条连续前进的曲线而非重复片段。
            t = self._phase + step * np.arange(self._batch)
            self._phase += step * self._batch
            self.batch.emit(np.sin(t * 0.9) * 45.0
                            + np.sin(t * 11.0) * 5.0
                            + rnd.normal(0.0, 0.6, self._batch))
            self.msleep(max(1, int(self._step * 1000)))

    def stop(self) -> None:
        """请求停止并等待线程退出（最长约一个采样周期）。"""
        self.requestInterruption()
        if self.isRunning():
            self.wait(2000)


def _massive_signal(n: int, seed: int = 2026):
    """生成巨量传感器风格信号（低频趋势 + 平滑高频细节 + 少量尖峰）。

    频率选择是**为了可读性**：若含高频成分（如 ``sin(i * 0.1)``），150 万点
    在每个像素列内会有数十个振荡，画出来只是一团噪声、y 轴刻度也会叠在一起，
    反而看不出渲染质量。这里让主导成分的周期远大于像素列跨度。

    纯数值向量，直接交给 `set_option`：数值序列会按**引用**持有并零拷贝摄入。
    """
    idx = np.arange(n, dtype=np.float64)
    rnd = np.random.default_rng(seed)
    # 主导低频段（约 40 万个点一个周期，全宽约 4 个周期，舒展可读）
    # + 一条缓变的中频段（约 5000 个点一个周期）+ 噪声
    ys = (np.sin(idx * 0.000016) * 45.0
          + np.sin(idx * 0.00125) * 5.0
          + rnd.normal(0.0, 0.6, n))
    for s in np.random.default_rng(seed + 1).integers(0, n, 24):
        ys[s] += rnd.uniform(60.0, 120.0)
    return ys


def _sparkline_ticks(n: int) -> list:
    """为巨量数据生成稀疏的 x 轴刻度（避免百万级类别标签拖慢文字绘制）。"""
    count = min(12, max(2, n // 50_000))
    return [int(round(i * (n - 1) / (count - 1))) for i in range(count)]


class _MassiveDataWorker(QThread):
    """后台线程生成巨量数据，经信号回到 GUI 线程入图。

    演示两个事实：**数据准备不阻塞界面**；跨线程投递只需信号，无需手动加锁。
    """

    ready = Signal(object, int)      # (ndarray, 生成耗时毫秒)

    def __init__(self, n: int, seed: int = 2026, parent=None):
        super().__init__(parent)
        self._n = int(n)
        self._seed = int(seed)

    def run(self) -> None:  # noqa: D102 - QThread 覆写
        t0 = time.perf_counter()
        ys = _massive_signal(self._n, self._seed)
        dt = (time.perf_counter() - t0) * 1000.0
        self.ready.emit(ys, int(round(dt)))


class MassiveDataDemo(QWidget):
    """巨量数据综合演示：实时滚动流 + 双路径耗时对比 + 后台线程生成。

    演示要点：

    - **点数滑块实时重建**：从 5 万到 500 万，观察「每帧成本与数据总量解耦」
      ——因为绘制点数由视口像素宽决定，与数据总量无关；
    - **GPU 原生直绘**：开启后折线顶点经 VBO + GLSL 走显卡，绕过 QPainter
      的路径构造（耗时读数会出现数量级差异）；
    - **实时滚动流**：模拟 50 点/秒的高速传感器（独立线程写入无锁环形缓冲），
      图表只保留最近 N 点并持续左移；读数报实测入图频率与采样吞吐，而不是
      重绘请求数（后者只会量到定时器节奏）；
    - **后台线程生成**：点数较大时在 QThread 中准备数据，界面不卡。

    本演示**不提供**「关闭采样」档位：采样阈值就是屏幕像素宽，超过它的点
    既看不到也点不到，关掉只会让单帧从毫秒级涨到秒级并令窗口失去响应。
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._n = _MASSIVE_DEFAULT_N
        self._ys = None
        self._worker = None
        self._busy = False
        # 实时滚动流状态（生产者线程 + 流式会话 + 实测读数）
        self._sensor = None
        self._sess = None
        self._live_halted = False
        self._live_last = 0.0
        self._live_gaps = []
        self._live_samples = 0
        self._live_target = 0

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)

        # -- 读数条 --------------------------------------------------------
        self.readout = hint_label("准备中…", role="secondary")
        self.readout.setTextInteractionFlags(Qt.TextSelectableByMouse)
        lay.addWidget(self.readout)
        lay.addWidget(hint_label(
            "「采样」不是可选项而是物理下限：绘图区只有 1000 多像素宽，150 万点里"
            "每列有上千个点落在同一个像素列上，多出来的点既看不到也点不到。"
            "引擎按「视口像素宽 × 2」设阈值并逐桶保留极值，"
            "逐像素列极值与全量直绘严格一致——所以本演示里没有「关闭采样」这一档，"
            "关掉只会白烧 CPU（单帧从毫秒级涨到秒级，界面随即失去响应）。"
            "两条路径对比的是**同一条采样后曲线**：QPainter 逐点构造路径 vs "
            "「GPU 原生直绘」把顶点交给 VBO + GLSL。数据在后台线程生成，界面不卡。"
            "打开「实时滚动流」后改为持续流：独立线程按约 1000 点/秒写入无锁环形"
            "缓冲，图表只保留最近「窗口」个点、写满丢最旧——读数报的是实测入图"
            "频率与采样吞吐，不是重绘请求数。",
            role="tertiary"))

        # -- 图表 ----------------------------------------------------------
        self.chart = ChartWidget(self)
        self.chart.setMinimumHeight(340)
        self.chart.setSizePolicy(QSizePolicy.Policy.Expanding,
                                 QSizePolicy.Policy.Expanding)
        lay.addWidget(self.chart, 1)

        # -- 参数面板 ------------------------------------------------------
        panel = PlaygroundPanel("巨量数据参数", width=280)
        form = panel.form
        form.add_int("点数", self._n, 50_000, _MASSIVE_MAX_N, self._on_points,
                     key="points", step=50_000)
        form.add_bool("GPU 原生直绘", _gl_ready(), self._on_gpu,
                      key="gpuDirect")
        form.add_bool("实时滚动流", False, self._on_live, key="live")
        form.add_choice("滚动窗口", [("500 点（约 0.5 秒）", 500),
                                 ("2,000 点（约 2 秒）", 2_000),
                                 ("20,000 点（约 20 秒）", 20_000),
                                 ("100,000 点（约 100 秒）", 100_000)],
                        _LIVE_WINDOW, self._on_window, key="window")
        form.add_bool("后台线程生成", False, self._on_threaded, key="threaded")
        lay.addWidget(panel)
        self.panel = panel
        self.form = form

        # 读数刷新计时器：只负责按节奏刷新读数条（不驱动重绘——重绘由流式
        # 会话在有新数据时发起）。间隔取 _LIVE_INTERVAL_MS，不能是 0。
        self._fps_timer = QTimer(self)
        self._fps_timer.setInterval(_LIVE_INTERVAL_MS)
        self._fps_timer.timeout.connect(self._on_fps_tick)

        self._rebuild()

    # -- 参数回调 ----------------------------------------------------------
    def _on_points(self, value) -> None:
        self._n = int(value)
        self._rebuild()

    def _on_gpu(self, enabled) -> None:
        self._rebuild()

    def _on_live(self, enabled) -> None:
        """切换实时滚动流：开则接上模拟传感器，关则回到巨量静态数据。"""
        if enabled:
            self._start_live()
        else:
            self._stop_live()
            self._rebuild()

    def _on_window(self, value) -> None:
        """滚动窗口变化：仅在流开启时立即重建会话。"""
        if self._sess is not None:
            self._start_live()

    def _window(self) -> int:
        ctrl = self.form.controls.get("window")
        try:
            return max(100, int(ctrl.currentData()))
        except Exception:  # noqa: BLE001
            return _LIVE_WINDOW

    def _on_threaded(self, _enabled) -> None:
        self._rebuild()

    def _threaded(self) -> bool:
        ctrl = self.form.controls.get("threaded")
        try:
            return bool(ctrl.isChecked())
        except Exception:  # noqa: BLE001
            return False

    def _gpu_enabled(self) -> bool:
        ctrl = self.form.controls.get("gpuDirect")
        try:
            return bool(ctrl.isChecked())
        except Exception:  # noqa: BLE001
            return False

    # -- 构建 --------------------------------------------------------------
    def _rebuild(self) -> None:
        """按当前参数准备数据并重建图表（大点数走后台线程）。"""
        n = self._n
        if n >= 500_000 and self._threaded():
            self._readout("后台线程生成 %s 点数据…" % f"{n:,}")
            self._start_worker(n)
            return
        self._apply(_massive_signal(n), 0, threaded=False)

    def _start_worker(self, n: int) -> None:
        if self._worker is not None and self._worker.isRunning():
            self._worker.ready.disconnect()
            self._worker.quit()
            self._worker.wait(2000)
        self._worker = _MassiveDataWorker(n, parent=self)
        self._worker.ready.connect(self._on_data_ready)
        self._worker.start()

    def _on_data_ready(self, ys, gen_ms: int) -> None:
        self._apply(ys, gen_ms, threaded=True)

    def _apply(self, ys, gen_ms: int, threaded: bool) -> None:
        self._ys = ys
        n = len(ys)
        series = {
            "type": "line",
            "name": "传感器信号",
            "data": ys,
            "lineStyle": {"width": 1.2},
            "showSymbol": False,
        }
        # 采样配置一律走引擎默认（视口像素宽 × 2 的 minmax 下限）：本演示不再
        # 提供「关闭采样」档位——百万点全分辨率既无可分辨的视觉收益，实测还会
        # 让单帧从毫秒级涨到秒级并令事件循环失去响应（Windows 判定 AppHang）。
        if self._gpu_enabled():
            series["gpuDirect"] = True
        option = {
            "title": {"text": f"巨量数据 · {n:,} 点"},
            # 单系列无需图例：去掉它可为绘图区腾出高度（长信号图更需要纵向空间）
            "legend": {"show": False},
            "tooltip": {"trigger": "axis"},
            "grid": {"left": 72, "right": 28, "top": 48, "bottom": 38},
            "xAxis": {"type": "value"},
            "yAxis": {"type": "value"},
            "series": [series],
        }
        t0 = time.perf_counter()
        self.chart.set_option(option)
        self.chart.anim.stop()
        self.chart.anim.set_progress(1.0)
        set_ms = (time.perf_counter() - t0) * 1000.0
        self._last_set_ms = set_ms
        self._gen_ms = gen_ms
        self._threaded_used = threaded
        # 让 GL 视口完成一次真实绘制，之后 GPU 计时才有可用的管线
        self.chart.repaint()
        QTimer.singleShot(30, self._refresh_benchmark)

    def _refresh_benchmark(self) -> None:
        """跑一次双路径测量并刷新读数（测量本身在毫秒级）。"""
        try:
            res = self.chart.benchmark(frames=6)
        except Exception as exc:  # noqa: BLE001
            self._readout(f"性能测量失败：{exc!r}")
            return
        self._res = res
        self._update_readout()

    def _update_readout(self) -> None:
        """刷新读数条：离线配置报双路径耗时，实时滚动流报实测吞吐。"""
        res = getattr(self, "_res", None)
        if self._sess is not None:
            self._live_readout()
            return
        if res is None:
            return
        n = self._n if self._ys is None else len(self._ys)
        parts = [f"数据点数 {n:,}",
                 f"实际渲染 {res['points']:,}"]
        if getattr(self, "_gen_ms", 0):
            parts.append(f"数据生成 {self._gen_ms} ms"
                         + ("（后台线程）" if getattr(self, "_threaded_used",
                                                      False) else ""))
        parts.append(f"set_option {getattr(self, '_last_set_ms', 0):.0f} ms")
        if res.get("overload"):
            # 护栏生效：此时 cpu_ms 只反映「画提示文案」，不能作为性能对比依据
            from InstructionX_UIKit.charts.gl_series import GL_MAX_POINTS
            parts.append(f"已暂停绘制（点数超过 GL 安全上限 "
                         f"{GL_MAX_POINTS:,}，请调小点数）")
            self.readout.setText(" ｜ ".join(parts))
            return
        cpu = res["cpu_ms"]
        parts.append(f"QPainter 单帧 {cpu:.2f} ms" if cpu is not None else
                     "QPainter 单帧 —")
        if res["gpu_ms"] is not None:
            parts.append(f"GPU 直绘 {res['gpu_ms']:.3f} ms")
        elif res["gpu_active"]:
            parts.append("GPU 直绘 未生效（数据超直绘上限或需 GL 后端）")
        budget = res["budget_ms"]
        flag = "达标" if res["ok"] else "未达标"
        parts.append(f"90 fps 预算 {budget:.1f} ms → {flag}")
        # GPU 相对 QPainter 的倍数：这是本区块要展示的核心结论。
        # 两条路径画的是同一条采样后曲线，倍数即「路径构造成本」的差距。
        if cpu and res["gpu_ms"]:
            parts.append(f"GPU 快 {cpu / res['gpu_ms']:.0f} 倍")
        parts.append("GL 后端 " + ("已启用" if res["gl"] else "软件回退"))
        self.readout.setText(" ｜ ".join(parts))

    def _live_readout(self) -> None:
        """实时滚动流的读数：只报**实测**量，不掺重绘请求数。

        - **入图频率 / 间隔**：会话每次把新数据写进图表的时间差。有新数据才
          刷新，故它等于「屏幕上的曲线多久前进一步」；上限受读数定时器节奏
          （1000/_LIVE_INTERVAL_MS）与合成刷新率约束，**不是**图表能力上限。
        - **采样吞吐**：生产者累计写入点数 / 运行时长，只由采集线程决定，
          与界面节奏无关——两者一起看才说明「数据没有被界面拖住」。
        - **丢弃点数**：窗口写满后覆盖掉的旧点数，即「滚动」的证据。
        """
        sess = self._sess
        if sess is None:
            return
        parts = [f"滚动窗口 {sess.ring.capacity:,} 点",
                 f"已入图 {len(sess.ring):,}"]
        gaps = self._live_gaps[-60:]
        if gaps:
            mean_ms = sum(gaps) / len(gaps)
            parts.append(f"实测入图 {1000.0 / max(mean_ms, 1e-6):.1f} Hz"
                         f"（间隔 {mean_ms:.1f} ms）")
        if self._live_target:
            rate = self._live_samples / max(self._live_elapsed(), 0.1)
            parts.append(f"采样 {rate:.0f} 点/秒（目标 {self._live_target}）")
        parts.append(f"丢弃旧点 {sess.ring.dropped:,}")
        if self._live_halted:
            parts.append("实时滚动已暂停（单帧耗时过长）")
        gl = "已启用" if _gl_ready() else "软件回退"
        parts.append("GL 后端 " + gl)
        self.readout.setText(" ｜ ".join(parts))

    def _live_elapsed(self) -> float:
        """实时滚动流已运行秒数（未开启时为 0）。"""
        return max(0.0, time.perf_counter() - getattr(self, "_live_t0", 0.0))

    def _readout(self, text: str) -> None:
        self.readout.setText(text)

    # -- 实时滚动流 --------------------------------------------------------
    def _start_live(self) -> None:
        """接上模拟传感器：生产者线程 → 环形缓冲 → 按帧入图。

        与「离线巨量数据」的区别在于这是个**持续流**：数据只增不减地写入定长
        环形缓冲，窗口满后丢最旧点，图表始终显示最近 ``window`` 个点。
        """
        self._stop_live()
        window = self._window()
        self.chart.set_option({
            "title": {"text": f"实时滚动 · 最近 {window:,} 点"},
            "legend": {"show": False},
            "tooltip": {"trigger": "axis"},
            "grid": {"left": 72, "right": 28, "top": 48, "bottom": 38},
            "xAxis": {"type": "category", "data": []},
            # 固定 y 轴而不用 auto_scale：量程固定才能看出曲线在滚动而不是被
            # 每帧重新拉伸。范围按生成器的理论极值取（两个正弦分量 ±50 与
            # ±5 叠加 + 噪声），留一点余量。
            "yAxis": {"type": "value", "min": -58, "max": 58},
            "series": [{"type": "line", "name": "传感器信号", "data": [],
                        "showSymbol": False, "lineStyle": {"width": 1.2}}],
        })
        self.chart.anim.stop()
        self.chart.anim.set_progress(1.0)
        self._sess = self.chart.stream(series="传感器信号", window=window,
                                       interval=_LIVE_INTERVAL_MS / 1000.0,
                                       auto_scale=False)
        self._live_last = 0.0
        self._live_gaps = []
        self._live_samples = 0
        self._live_target = _LIVE_RATE
        self._live_t0 = time.perf_counter()
        self._live_halted = False
        # 清掉离线配置的读数：流运行期间不再做离屏测量（实测入图本身仅
        # 0.01~0.05 ms，而 benchmark 首次调用要 220 ms 重建缓存，会把刷新
        # 节奏和读数一起带偏），故只保留流的实测值。
        self._res = None
        self._sensor = _LiveSensor(parent=self)
        self._sensor.batch.connect(self._on_sample)
        self._sensor.start()
        self._fps_timer.start()

    def _stop_live(self) -> None:
        """断开传感器并结束流式会话（可重复调用）。"""
        try:
            self._fps_timer.stop()
        except Exception:  # noqa: BLE001
            pass
        sensor, self._sensor = self._sensor, None
        if sensor is not None:
            try:
                sensor.batch.disconnect()
            except Exception:  # noqa: BLE001
                pass
            sensor.stop()
            sensor.deleteLater()
        sess, self._sess = self._sess, None
        if sess is not None:
            try:
                sess.close()
            except Exception:  # noqa: BLE001
                pass

    def _on_sample(self, values) -> None:
        """生产者信号（GUI 线程）：写入环形缓冲，入图由会话按节奏完成。"""
        sess = self._sess
        if sess is None:
            return
        try:
            sess.write(values)
        except Exception:  # noqa: BLE001 - 单次写入失败不应终止流
            return

    def _on_fps_tick(self) -> None:
        """刷新实时滚动读数：实测入图间隔、采样吞吐、单帧耗时。

        **不再把重绘请求数当帧率**：那样量到的是定时器节奏（约 1000/16 ≈ 62
        「fps」），而它与下面画的是 6 ms 的 QPainter 还是 0.29 ms 的 GPU 无关，
        两条路径读数永远一样。这里改为量两个真实量：

        - **入图间隔**：会话每次真正把新数据写进图表的时间差——只有在有新数据
          时才刷新，故它反映的是「屏幕上的曲线多久前进一步」；
        - **采样吞吐**：生产者累计写入点数 / 运行时长（与 UI 节奏无关）。

        安全阀：单帧耗时过大时停表并说明原因，避免界面被拖住。
        """
        if self._busy or self._sess is None:
            return
        self._busy = True
        try:
            res = getattr(self, "_res", None)
            if res is not None and res.get("cpu_ms") \
                    and res["cpu_ms"] > _LIVE_MAX_FRAME_MS \
                    and not res.get("gpu_ms"):
                self._fps_timer.stop()
                self._live_halted = True
                self._update_readout()
                return
            self._live_samples = self._sess.ring.total_written
            now = time.perf_counter()
            if self._live_last:
                self._live_gaps.append((now - self._live_last) * 1000.0)
                del self._live_gaps[:-240]
            self._live_last = now
            self._update_readout()
        finally:
            self._busy = False

    def stop(self) -> None:
        """停止实时滚动与后台线程（页面销毁 / 测试收尾用）。"""
        self._stop_live()
        w = self._worker
        if w is not None and w.isRunning():
            try:
                w.ready.disconnect()
            except Exception:  # noqa: BLE001
                pass
            w.quit()
            w.wait(3000)

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt 覆写
        """关闭时停掉后台线程（否则 Qt 会报线程仍在运行的销毁告警）。"""
        self.stop()
        super().closeEvent(event)

    def __del__(self) -> None:
        """析构兜底：尽力停止后台线程。

        说明：QThread 随控件一起被销毁时若仍在运行，Qt 只会打印告警而不会等待，
        因此「后台线程生成」默认**关闭**——默认路径不做跨线程生命周期管理，
        演示与测试都只走同步生成。开启该选项时应显式调用 :meth:`stop`
        （或让控件正常 close）。
        """
        try:
            self.stop()
        except Exception:  # noqa: BLE001
            pass


def _gl_ready() -> bool:
    """当前环境是否具备 GL 后端（决定 GPU 直绘开关的初值）。"""
    try:
        from InstructionX_UIKit.charts.viewport import gl_available
        return bool(gl_available())
    except Exception:  # noqa: BLE001
        return False


def _massive_data_section() -> Section:
    """巨量数据综合演示（展示 OpenGL 对图表渲染的性能）。"""
    box = Section("巨量数据综合演示（OpenGL 渲染 · 150 万点起）")
    demo = MassiveDataDemo()
    box.layout().addWidget(demo)
    box.demo = demo       # 便于测试访问
    return box


def create_page() -> QWidget:
    sec_cart = Section("直角坐标系列（11 种 · grid / 平行 / 日历）")
    sec_cart.layout().addWidget(ResponsiveCardGrid(_make_cards(_CARTESIAN_CARDS)))

    sec_hier = Section("层级占比系列（6 种）")
    sec_hier.layout().addWidget(ResponsiveCardGrid(_make_cards(_HIERARCHY_CARDS)))

    sec_rel = Section("关系流向系列（4 种）")
    sec_rel.layout().addWidget(ResponsiveCardGrid(_make_cards(_RELATION_CARDS)))

    sec_coord = Section("坐标系与地图（4 坐标系 + map 系列）")
    sec_coord.layout().addWidget(ResponsiveCardGrid(_make_cards(_COORD_CARDS)))

    return make_page(
        "图表",
        "InstructionX_UIKit.charts 原生图表引擎（纯 QPainter 自绘，无 WebView）："
        "ECharts 风格 set_option / update_option API，主题感知实时换肤。"
        "21 个系列各配演示卡（随页面宽度 1~3 列自适应排布），另设四坐标系、"
        "map、组件综合与巨量数据演示（大图整行撑满）。参数修改即按新 option "
        "重建图表。",
        [sec_cart, sec_hier, sec_rel, sec_coord,
         _comprehensive_section(), _massive_data_section()])
