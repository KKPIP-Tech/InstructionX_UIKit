# CHART_SPEC — InstructionX_UIKit.charts 原生图表引擎契约

> 目标：类 ECharts 的图表能力，纯 PySide6（QPainter 自绘），禁止 WebView/JS。
> 本文件是 C1/C2/C3/C4/G 五个代理的唯一事实来源。文件归属严格，禁止跨文件修改。

## 1. 模块结构与文件归属

```
InstructionX_UIKit/charts/
├── __init__.py            # C1：包级导出 + 惰性导入各 series/components 模块（try/except）
├── core.py                # C1：ChartWidget、注册表、动画驱动、主题接入、Title/Legend/Tooltip 组件
├── axes.py                # C1：AxisModel、GridCoord、PolarCoord、SingleAxisCoord、CalendarCoord
├── series_cartesian.py    # C2：直角/单轴/平行/日历坐标下的系列
├── series_hierarchy.py    # C3：无坐标/层级/关系系列
├── components.py          # C4：MarkPoint/MarkLine/MarkArea、Graphic、Map（map 系列 + geo 简化）
└── interact.py            # C4：DataZoom、Brush、VisualMap、ChartTimeline、Toolbox
```

## 2. 公开 API（用户视角，ECharts 风格）

```python
from InstructionX_UIKit.charts import ChartWidget
chart = ChartWidget(parent)
chart.set_option({...})      # 全量设置（dict，schema 见 §4）
chart.update_option({...})   # 合并更新并动画过渡
chart.resize_option()        # 无需：resizeEvent 自动重排
```
- 主题感知：构造时连接 `ThemeManager.instance().theme_changed` → 重取 `T()` 配色并 `update()`。
- 入场/更新动画：core 提供 `ChartAnimation`（QVariantAnimation 0→1，DURATION.slow，EASING.standard），渲染器用 `anim_t` 插值；`update_option` 时旧→新数据插值。
- 配色：默认调色板来自 tokens：`[primary, success, warning, danger, text.secondary, primary.hover, success.hover, warning.hover]`（用 T() 实时取）；option 中 `color: [...]` 可覆盖。

## 3. 注册表与渲染器协议（core.py 提供）

```python
SERIES_REGISTRY: dict[str, type]        # "bar" -> BarSeriesRenderer
COMPONENT_REGISTRY: dict[str, type]     # "markLine" -> MarkLineComponent 等（C4 注册）
def register_series(type_name, cls)
def register_component(name, cls)

class SeriesRenderer:
    def __init__(self, chart: ChartWidget, opt: dict): ...
    def layout(self, rect: QRectF): ...             # 计算几何（坐标映射经 coord）
    def paint(self, p: QPainter, anim_t: float): ...
    def hit_test(self, pos: QPointF) -> dict|None:  # tooltip 数据 {"name","value","series"}
```
- ChartWidget 持有：title/legend/tooltip 组件实例、coords（grid/polar/single/calendar）、series 渲染器列表、interact 组件列表（C4 协议同 SeriesRenderer，另可挂 mouse 事件钩子 `on_mouse_press/move/release`）。
- 坐标协议（axes.py）：
```python
class Coord:
    def layout(self, rect: QRectF): ...
    def map_point(self, x, y) -> QPointF: ...   # 数据→像素（polar: angle/radius；calendar/single 单参）
    def paint_axes(self, p: QPainter): ...       # 轴线/刻度/网格/标签
    def paint_tooltip_marker(self, p, pos): ...  # 十字线/指示线
```
- AxisModel：类别轴（list[str]）或数值轴（自动 nice ticks，~5 段）；支持 name、min/max、axisLabel 字体取 font.xs。

## 4. Option schema（ECharts 子集）

```python
{
 "color": ["#..."],                     # 可选全局调色板
 "title": {"text": str, "subtext": str, "left": "left|center|right"},
 "legend": {"show": True, "orient": "horizontal|vertical", "bottom|top|left|right": ...},  # 点击切换系列显隐
 "tooltip": {"show": True, "trigger": "item|axis"},
 "grid": {"left":48,"right":24,"top":40,"bottom":36},
 "xAxis": {"type":"category|value","data":[...],"name":str}, "yAxis": {...},
 "polar": {}, "radiusAxis": {...}, "angleAxis": {...},
 "singleAxis": {"left":40,"right":40,"top":...,"bottom":...},
 "calendar": {"year": 2026, "cellSize": 14},
 "series": [{"type": str, "name": str, "data": [...], ...系列专属键,
             "markPoint": {...}, "markLine": {...}, "markArea": {...}}],
 "visualMap": {"min":0,"max":100,"inRange":{"colors":[...]}, "orient":...},
 "dataZoom": [{"type":"inside|slider","xAxisIndex":0,"start":0,"end":100}],
 "brush": {"toolbox":["rect","polygon","clear"]},
 "timeline": {"data":["2024","2025","2026"], "autoPlay": False},   # 切换多帧 option（options: [...]）
 "toolbox": {"feature": ["saveAsImage","dataZoom","restore"]},
 "graphic": [{"type":"circle|rect|text|line", ...}],
 "options": [...]                       # timeline 各帧 option
}
```

## 5. 系列清单与归属

### C2 series_cartesian.py（type → 说明）
- `bar` 柱状（支持 stack、barWidth、圆角 barBorderRadius、horizontal 由 yAxis category 实现）
- `pictorialBar` 象形柱图（symbol: "rect|circle|pin" 或重复次数 symbolRepeat）
- `line` 折线（smooth、areaStyle、step、symbol 大小、showSymbol）
- `scatter` 散点（symbolSize 可为函数式 (v)->px 的近似：支持 "symbolSize": int 或按第三维映射）
- `effectScatter` 涟漪散点（扩散圆动画，rippleEffect: {period, scale}）
- `candlestick` K线（OHLC，涨跌色：danger/success）
- `boxplot` 箱线（[min,Q1,med,Q3,max]）
- `heatmap` 热力（配合 visualMap 或默认色带 primary.subtle→primary）
- `parallel` 平行坐标（自带平行轴，多维度数据）
- `themeRiver` 主题河（时间×系列的流带，自带底部时间轴）

### C3 series_hierarchy.py
- `pie` 饼/环形（radius: ["40%","70%"] 环、roseType: "radius|area" 南丁格尔、label）
- `radar` 雷达（indicator: [{name,max}]，多系列，areaStyle）
- `gauge` 仪表盘（min/max、progress、axisLine 色段、pointer、detail 数值）
- `funnel` 漏斗（sort: "descending|ascending|none"、gap、label）
- `sunburst` 旭日（层级 data: [{name,value,children}]）
- `treemap` 矩形树图（squarified 布局，层级下钻可选）
- `tree` 树图（orient: "LR|TB"，正交/曲线边，可折叠可选）
- `sankey` 桑基（nodes/links，层级布局迭代）
- `graph` 关系图（nodes/links，layout: "force|none"，force 用简单斥力-引力迭代 50 轮，circular 可选）
- `lines` 线图（起终点坐标对，带 trailEffect 移动点动画）

### C4 components.py / interact.py / geomap 部分
- `markPoint`（max/min/指定坐标标注）、`markLine`（average/max/min/指定值标线，虚线）、`markArea`（标域，半透明填充）
- `graphic`（绝对定位图形元素：circle/rect/text/line/image 可选）
- `map` 系列 + `geo`：接受 {"map": "china-simple"|自定义 polygon dict}；内置极简中国轮廓（粗粒度省界多边形可简化为大区块）——若内置数据过大，改为：支持用户传入 {"name": [[(x,y),...], ...} 的 polygons，并内置一个 6-8 个简化区块的演示地图，文档注明为示意数据
- `dataZoom`（inside：滚轮缩放+拖拽平移；slider：底部滑块双把手）
- `brush`（矩形刷选，高亮选中点并发出 selected 信号）
- `visualMap`（连续：值→颜色映射，右下角渐变条；piecewise 可选）
- `timeline`（图表时间轴：底部轴+播放按钮，切换 options[i] 帧）
- `toolbox`（右上角按钮组：saveAsImage 导出 PNG、restore 重置、dataZoom 开关）

## 6. 质量要求
- 全部 QPainter 抗锯齿（RenderHint.Antialiasing）；文字用 FONT_FAMILY；数值标签 font.xs。
- 高 DPI：`paintEvent` 直接用逻辑坐标，无需手动 DPR（QPainter 处理）。
- 空数据/None 不崩溃；数值轴自动 nice ticks。
- 中文 docstring；无 emoji；无第三方依赖。
- 各代理附测试：tests/test_chart_<area>.py，offscreen 构造其负责的全部系列/组件最小 option + 一个综合 option，grab 截图 tests/shots/chart_<type>.png，非空白断言，退出码 0。
