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

from PySide6.QtCore import Qt
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


_HEAT_RAMP = {
    "blue": ["#EBEFF5", "#3F5E8C"],
    "warm": ["#FDF3E3", "#D6473C"],
}


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
        series["axisLine"] = {"lineStyle": {"width": 10, "color": [
            [0.6, "#3FA46A"], [0.85, "#C78A2B"], [1.0, "#E64545"]]}}
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


def create_page() -> QWidget:
    """图表演示页（InstructionX_UIKit.charts 原生引擎全系列）。"""
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
        "map 与组件综合演示（大图整行撑满）。参数修改即按新 option 重建图表。",
        [sec_cart, sec_hier, sec_rel, sec_coord,
         _comprehensive_section()])
