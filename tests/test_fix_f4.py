# -*- coding: utf-8 -*-
"""F4 修订自测：无坐标系列不再兜底出轴 + 图表演示卡宽度自适应。

直接运行（无 pytest 依赖）::

    QT_QPA_PLATFORM=offscreen python tests/test_fix_f4.py

覆盖：
- 纯 pie/radar/gauge/sankey 等无坐标 option：``chart.coords == []``，
  且截图 plot 区无规则灰线（行 / 列扫描 border 色长连续段）；
- 检测器阳性对照：bar(grid) option 能检出轴线长段；
- 显式 xAxis/yAxis/grid 键、缺省类型（line）、bar 裸系列仍创建 GridCoord；
- parallel / themeRiver 修复后无轴可遮，仍正常自绘（非空白、几何非空）；
- heatmap coordinateSystem="calendar" 仍由 CalendarCoord 工作；
- 混合 pie+bar option 仍创建 GridCoord；
- 图表页 ResponsiveCardGrid：1000/1400/1800 三档宽度断点列数、
  同排卡等宽、排内无空洞，组件综合大图整行撑满；三档整页截图。
"""

import os
import sys
import traceback
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

SHOTS = ROOT / "tests" / "shots"
SHOTS.mkdir(parents=True, exist_ok=True)

_FAILURES = []


def check(name):
    """装饰器：登记一项检查，异常即记为失败。"""

    def deco(fn):
        try:
            fn()
            print(f"  [通过] {name}")
        except Exception:
            _FAILURES.append(name)
            print(f"  [失败] {name}")
            traceback.print_exc()

    return deco


def assert_true(cond, msg=""):
    if not cond:
        raise AssertionError(msg or "断言失败")


def assert_eq(actual, expected, msg=""):
    if actual != expected:
        raise AssertionError(f"{msg} 期望 {expected!r}，实际 {actual!r}")


from PySide6.QtGui import QColor  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from InstructionX_UIKit.theme import T, ThemeManager  # noqa: E402
from InstructionX_UIKit.charts import CalendarCoord, ChartWidget, GridCoord  # noqa: E402

app = QApplication.instance() or QApplication(sys.argv)
ThemeManager.instance().apply(app)
ThemeManager.instance().set_mode("light")


def make_chart(w=480, h=320):
    chart = ChartWidget()
    chart.resize(w, h)
    return chart


def grab_image(widget):
    return widget.grab().toImage()


def count_colors(img, cap=2000, step=3):
    colors = set()
    for y in range(0, img.height(), step):
        for x in range(0, img.width(), step):
            colors.add(img.pixelColor(x, y).rgba())
            if len(colors) > cap:
                return len(colors)
    return len(colors)


def assert_not_blank(img, msg=""):
    n = count_colors(img)
    assert_true(n > 8, f"{msg} 图像疑似空白（颜色数 {n}）")


# ---------------------------------------------------------------------------
# 轴线像素扫描（border / border.strong 及其与白底的抗锯齿混合色）
# ---------------------------------------------------------------------------

def _near(c: QColor, targets, tol):
    for t in targets:
        if (abs(c.red() - t.red()) <= tol
                and abs(c.green() - t.green()) <= tol
                and abs(c.blue() - t.blue()) <= tol):
            return True
    return False


def axis_line_counts(img, tol=10):
    """统计含 border 系颜色长连续段的行数 / 列数（长 = 60% 图宽 / 图高）。

    GridCoord.paint_axes 无条件绘制底部 x 轴线（横向整宽）与左侧 y 轴线
    （纵向整高），故"同时存在长灰行与长灰列"是兜底轴线网格的可靠特征；
    sankey 流带（仅长行无长列）、tree 边（仅长行）、雷达环弦（短）等均
    不满足该特征。
    """
    c_border = QColor(T("color.border"))
    c_strong = QColor(T("color.border.strong"))
    c_bg = QColor(T("color.bg.base"))

    def blend(a, b):
        return QColor((a.red() + b.red()) // 2,
                      (a.green() + b.green()) // 2,
                      (a.blue() + b.blue()) // 2)

    targets = [c_border, c_strong, blend(c_border, c_bg), blend(c_strong, c_bg)]
    w, h = img.width(), img.height()
    row_thr, col_thr = 0.6 * w, 0.6 * h
    rows = cols = 0
    for y in range(h):
        run = best = 0
        for x in range(w):
            run = run + 1 if _near(img.pixelColor(x, y), targets, tol) else 0
            best = max(best, run)
        if best >= row_thr:
            rows += 1
    for x in range(w):
        run = best = 0
        for y in range(h):
            run = run + 1 if _near(img.pixelColor(x, y), targets, tol) else 0
            best = max(best, run)
        if best >= col_thr:
            cols += 1
    return rows, cols


def assert_no_axis_lines(img, msg=""):
    """断言截图无规则灰轴线（无长灰行+长灰列组合）。"""
    rows, cols = axis_line_counts(img)
    assert_true(not (rows > 0 and cols > 0),
                f"{msg} 检出疑似轴线（长灰行 {rows} / 长灰列 {cols}）")


# ---------------------------------------------------------------------------
# 无坐标 option：coords == [] 且截图无轴线
# ---------------------------------------------------------------------------

PIE_OPTION = {
    "tooltip": {"trigger": "item"},
    "legend": {"show": True, "orient": "vertical", "right": 4},
    "series": [{
        "type": "pie", "name": "部门预算", "radius": ["42%", "72%"],
        "data": [{"name": "研发", "value": 420}, {"name": "市场", "value": 260},
                 {"name": "运营", "value": 180}, {"name": "设计", "value": 120}],
    }],
}

RADAR_OPTION = {
    "tooltip": {"trigger": "item"},
    "legend": {"show": True},
    "series": [{
        "type": "radar", "name": "产品评估",
        "indicator": [{"name": n, "max": 100}
                      for n in ("功能", "性能", "易用", "稳定", "生态", "服务")],
        "data": [{"name": "本季度", "value": [82, 90, 70, 88, 60, 76]}],
    }],
}

GAUGE_OPTION = {
    "tooltip": {"show": False},
    "series": [{
        "type": "gauge", "name": "完成率", "min": 0, "max": 100,
        "data": [{"name": "完成率", "value": 72}],
        "progress": {"show": True, "width": 10},
    }],
}

SANKEY_OPTION = {
    "tooltip": {"trigger": "item"},
    "series": [{
        "type": "sankey", "name": "能源流向",
        "data": [{"name": n} for n in ("煤炭", "水电", "工业", "居民")],
        "links": [{"source": "煤炭", "target": "工业", "value": 46},
                  {"source": "水电", "target": "工业", "value": 18},
                  {"source": "水电", "target": "居民", "value": 10}],
    }],
}

FUNNEL_OPTION = {
    "tooltip": {"trigger": "item"},
    "series": [{
        "type": "funnel", "name": "转化", "label": {"show": True},
        "data": [{"name": "访问", "value": 100}, {"name": "注册", "value": 64},
                 {"name": "付费", "value": 12}],
    }],
}

SUNBURST_OPTION = {
    "tooltip": {"trigger": "item"},
    "series": [{
        "type": "sunburst", "name": "营收",
        "data": [{"name": "硬件", "children": [
            {"name": "手机", "value": 46}, {"name": "平板", "value": 22}]},
            {"name": "软件", "value": 30}],
    }],
}

TREEMAP_OPTION = {
    "tooltip": {"trigger": "item"},
    "series": [{
        "type": "treemap", "name": "存储",
        "data": [{"name": "视频", "value": 46}, {"name": "照片", "value": 28},
                 {"name": "应用", "value": 24}],
    }],
}

TREE_OPTION = {
    "tooltip": {"trigger": "item"},
    "series": [{
        "type": "tree", "name": "组织",
        "data": [{"name": "总经理", "children": [
            {"name": "技术"}, {"name": "产品"}]}],
    }],
}

GRAPH_OPTION = {
    "tooltip": {"trigger": "item"},
    "series": [{
        "type": "graph", "name": "图谱", "layout": "circular",
        "data": [{"name": "甲"}, {"name": "乙"}, {"name": "丙"}],
        "links": [{"source": "甲", "target": "乙"},
                  {"source": "乙", "target": "丙"}],
    }],
}

MAP_OPTION = {
    "tooltip": {"trigger": "item"},
    "series": [{
        "type": "map", "name": "区域销量", "map": "demo",
        "data": [{"name": "华北", "value": 82}, {"name": "华东", "value": 95}],
    }],
}

NO_COORD_OPTIONS = [
    ("pie", PIE_OPTION), ("radar", RADAR_OPTION), ("gauge", GAUGE_OPTION),
    ("sankey", SANKEY_OPTION), ("funnel", FUNNEL_OPTION),
    ("sunburst", SUNBURST_OPTION), ("treemap", TREEMAP_OPTION),
    ("tree", TREE_OPTION), ("graph", GRAPH_OPTION), ("map", MAP_OPTION),
]


@check("纯无坐标 option：coords == [] 且截图无轴线像素")
def _():
    for label, opt in NO_COORD_OPTIONS:
        chart = make_chart()
        chart.set_option(opt)
        chart.anim.set_progress(1.0)
        assert_eq(chart.coords, [], f"{label} 不应创建任何 Coord")
        img = grab_image(chart)
        assert_not_blank(img, label)
        assert_no_axis_lines(img, label)
        img.save(str(SHOTS / f"fixf4_noaxis_{label}.png"))
        chart.deleteLater()


@check("空 option / 仅 tooltip 的 option：coords == []")
def _():
    chart = make_chart()
    chart.set_option({})
    assert_eq(chart.coords, [], "空 option 不应有 Coord")
    chart.set_option({"tooltip": {"show": True}})
    assert_eq(chart.coords, [], "无轴无系列 option 不应有 Coord")
    chart.anim.set_progress(1.0)
    grab_image(chart)
    chart.deleteLater()


# ---------------------------------------------------------------------------
# 需要 grid 的场景仍创建 GridCoord（含检测器阳性对照）
# ---------------------------------------------------------------------------

GRID_BAR_OPTION = {
    "tooltip": {"trigger": "axis"},
    "grid": {"left": 48, "right": 24, "top": 40, "bottom": 36},
    "xAxis": {"type": "category", "data": ["一", "二", "三", "四", "五"]},
    "yAxis": {"type": "value"},
    "series": [{"type": "bar", "name": "销量",
                "data": [120, 200, 150, 260, 220]}],
}


@check("bar(grid) option：GridCoord 存在且检测器能检出轴线（阳性对照）")
def _():
    chart = make_chart()
    chart.set_option(GRID_BAR_OPTION)
    chart.anim.set_progress(1.0)
    assert_true(isinstance(chart.primary_coord(), GridCoord), "应为 GridCoord")
    img = grab_image(chart)
    assert_not_blank(img, "bar")
    rows, cols = axis_line_counts(img)
    assert_true(rows > 0 and cols > 0,
                f"检测器未检出 bar 轴线（行 {rows} / 列 {cols}），像素扫描不可信")
    chart.deleteLater()


@check("grid 创建条件：显式键 / 缺省类型 / 裸直角系列 / 混合系列")
def _():
    # ① 显式键
    for keys in ({"xAxis": {}}, {"yAxis": {}}, {"grid": {}}):
        chart = make_chart()
        chart.set_option(dict(keys))
        assert_true(any(isinstance(c, GridCoord) for c in chart.coords),
                    f"显式键 {list(keys)} 应创建 GridCoord")
        chart.deleteLater()
    # ② 裸直角系列（无显式轴键）
    for stype in ("bar", "line", "scatter", "effectScatter",
                  "candlestick", "boxplot", "heatmap", "lines"):
        data = {"candlestick": [[10, 12, 9, 13]],
                "boxplot": [[4, 8, 12, 16, 20]],
                "lines": [{"coords": [[0, 0], [1, 1]]}],
                "heatmap": [[0, 0, 5]]}.get(stype, [1, 2, 3])
        chart = make_chart()
        chart.set_option({"series": [{"type": stype, "data": data}]})
        assert_true(any(isinstance(c, GridCoord) for c in chart.coords),
                    f"裸系列 {stype} 应创建 GridCoord")
        chart.deleteLater()
    # 缺省类型按 line 处理
    chart = make_chart()
    chart.set_option({"series": [{"data": [1, 2, 3]}]})
    assert_true(any(isinstance(c, GridCoord) for c in chart.coords),
                "缺省类型系列应创建 GridCoord")
    chart.deleteLater()
    # 混合：无坐标系列 + 直角系列 → 仍创建 grid
    chart = make_chart()
    chart.set_option({
        "series": [PIE_OPTION["series"][0],
                   {"type": "bar", "name": "B", "data": [1, 2]}]})
    assert_true(any(isinstance(c, GridCoord) for c in chart.coords),
                "混合系列应创建 GridCoord")
    chart.deleteLater()
    # 非 grid coordinateSystem 不触发 grid
    chart = make_chart()
    chart.set_option({"polar": {},
                      "series": [{"type": "line", "coordinateSystem": "polar",
                                  "data": [["a", 1], ["b", 2]]}]})
    assert_true(not any(isinstance(c, GridCoord) for c in chart.coords),
                "polar 系列不应创建 GridCoord")
    chart.deleteLater()


# ---------------------------------------------------------------------------
# parallel / themeRiver：无轴可遮仍正常自绘
# ---------------------------------------------------------------------------

@check("parallel 平行坐标：无 GridCoord 且自绘正常")
def _():
    chart = make_chart()
    chart.set_option({
        "tooltip": {"trigger": "item"},
        "parallelAxis": [{"name": s, "min": 0, "max": 100}
                         for s in ("语文", "数学", "英语")],
        "series": [{"type": "parallel", "name": "成绩",
                    "data": [[80, 90, 70], [60, 75, 88], [95, 62, 81]]}],
    })
    chart.anim.set_progress(1.0)
    assert_eq(chart.coords, [], "parallel 不应创建 Coord")
    r = chart.series_renderers[0]
    assert_true(len(r._axes) == 3 and len(r._rows) == 3, "parallel 几何未生成")
    img = grab_image(chart)
    assert_not_blank(img, "parallel")
    # parallel 自带 3 条竖轴，属系列自绘而非兜底 grid
    assert_true(any(abs(r._axes[j]["x"] - r._axes[0]["x"]) > 1e-6
                    for j in range(1, 3)), "parallel 竖轴未排开")
    # 自绘竖轴为长列但无配套长灰行，不满足兜底轴线特征，不误判
    assert_no_axis_lines(img, "parallel")
    img.save(str(SHOTS / "fixf4_parallel.png"))
    chart.deleteLater()


@check("themeRiver 主题河：无 GridCoord 且自绘正常")
def _():
    data = []
    for mi in range(6):
        for t in ("甲", "乙", "丙"):
            data.append([f"2026-{mi + 1:02d}", 5 + mi + len(t), t])
    chart = make_chart()
    chart.set_option({
        "tooltip": {"trigger": "item"},
        "legend": {"show": True},
        "series": [{"type": "themeRiver", "name": "热度", "data": data}],
    })
    chart.anim.set_progress(1.0)
    assert_eq(chart.coords, [], "themeRiver 不应创建 Coord")
    r = chart.series_renderers[0]
    assert_true(len(r._streams) == 3 and len(r._times) == 6,
                "themeRiver 流带未生成")
    img = grab_image(chart)
    assert_not_blank(img, "themeRiver")
    assert_no_axis_lines(img, "themeRiver")
    img.save(str(SHOTS / "fixf4_themeriver.png"))
    chart.deleteLater()


# ---------------------------------------------------------------------------
# heatmap coordinateSystem="calendar" 仍由 CalendarCoord 工作
# ---------------------------------------------------------------------------

@check("calendar 热力：仅 CalendarCoord，无 GridCoord")
def _():
    chart = make_chart(640, 240)
    chart.set_option({
        "tooltip": {"trigger": "item"},
        "calendar": {"year": 2026, "cellSize": "auto"},
        "series": [{"type": "heatmap", "name": "提交",
                    "coordinateSystem": "calendar",
                    "data": [["2026-01-05", 3], ["2026-06-01", 5],
                             ["2026-12-31", 2]]}],
    })
    chart.anim.set_progress(1.0)
    kinds = [c.kind for c in chart.coords]
    assert_eq(kinds, ["calendar"], f"坐标系组合异常 {kinds}")
    coord = chart.primary_coord()
    assert_true(isinstance(coord, CalendarCoord), "应为 CalendarCoord")
    pt = coord.map_point("2026-06-01")
    assert_true(coord.cell_rect("2026-06-01").contains(pt), "cell 映射异常")
    img = grab_image(chart)
    assert_not_blank(img, "calendar heatmap")
    img.save(str(SHOTS / "fixf4_calendar_heatmap.png"))
    chart.deleteLater()


# ---------------------------------------------------------------------------
# 图表页：卡片宽度自适应（1000 / 1400 / 1800 断点）
# ---------------------------------------------------------------------------

from demo.pages import charts as charts_page  # noqa: E402
from demo.pages.charts import ChartDemoCard, ResponsiveCardGrid  # noqa: E402

PAGE = None
_PAGE_WIDTH = 0


def _settle(width):
    """把页面（滚动区）调到目标宽度并等待重排稳定，返回整页内容截图。"""
    global _PAGE_WIDTH
    if _PAGE_WIDTH != width:
        _PAGE_WIDTH = width
        PAGE.resize(width, 900)
    # 滚动区 → 内容 → 网格逐级布局，列数变化会再触发一轮重排
    for _ in range(4):
        app.processEvents()
    return PAGE.widget().grab()


@check("图表页实例化：4 个 ResponsiveCardGrid + 综合演示卡")
def _():
    global PAGE
    PAGE = charts_page.create_page()
    PAGE.resize(1400, 900)
    PAGE.show()  # offscreen：隐藏控件不激活布局，必须 show
    app.processEvents()
    content = PAGE.widget()
    grids = content.findChildren(ResponsiveCardGrid)
    assert_eq(len(grids), 4, f"ResponsiveCardGrid 数量 {len(grids)}")
    cards = content.findChildren(ChartDemoCard)
    assert_true(len(cards) >= 25, f"演示卡数量 {len(cards)}")


@check("三档宽度断点：1000→2 列，1400/1800→3 列；同排等宽、排内无空洞")
def _():
    grids = PAGE.widget().findChildren(ResponsiveCardGrid)
    for width, expect_cols in ((1000, 2), (1400, 3), (1800, 3)):
        pm = _settle(width)
        assert_true(pm.save(str(SHOTS / f"fixf4_page_{width}.png")),
                    f"{width}px 整页截图保存失败")
        for gi, grid in enumerate(grids):
            assert_eq(grid.cols, expect_cols,
                      f"{width}px 网格{gi} 列数")
            cards = grid.cards
            # 按行分组校验：同排等宽、水平紧贴（spacing 间隔，无空洞）
            spacing = grid.layout().spacing()
            for row_start in range(0, len(cards), expect_cols):
                row = cards[row_start:row_start + expect_cols]
                widths = [c.geometry().width() for c in row]
                assert_true(max(widths) - min(widths) <= 2,
                            f"{width}px 网格{gi} 第{row_start // expect_cols}排"
                            f"卡宽不齐 {widths}")
                for a, b in zip(row, row[1:]):
                    gap = b.geometry().x() - (
                        a.geometry().x() + a.geometry().width())
                    assert_true(abs(gap - spacing) <= 2,
                                f"{width}px 网格{gi} 排内出现空洞/重叠 gap={gap}")
                # 排首左齐；满排时排尾抵网格右缘（末排不足列数属正常尾排）
                assert_true(row[0].geometry().x() <= 2,
                            f"{width}px 网格{gi} 排首未左齐")
                if len(row) == expect_cols:
                    right = row[-1].geometry().x() + row[-1].geometry().width()
                    assert_true(abs(right - grid.width()) <= 2,
                                f"{width}px 网格{gi} 排尾未撑满 "
                                f"right={right} grid={grid.width()}")
                # 卡内 ChartWidget 随卡伸缩
                for c in row:
                    assert_true(c.chart.width() >= c.chart.minimumWidth(),
                                f"{width}px {c.title_text} 图未达最小宽")


@check("窄宽 600px 退化为单列")
def _():
    grids = PAGE.widget().findChildren(ResponsiveCardGrid)
    _settle(600)
    for gi, grid in enumerate(grids):
        assert_eq(grid.cols, 1, f"600px 网格{gi} 应单列")
    _settle(1400)  # 还原


@check("组件综合演示大图整行撑满（随页宽伸缩）")
def _():
    comp = None
    for c in PAGE.widget().findChildren(ChartDemoCard):
        if "组件综合" in c.title_text:
            comp = c
            break
    assert_true(comp is not None, "未找到组件综合演示卡")
    widths = []
    for width in (1000, 1400, 1800):
        _settle(width)
        # ChartWidget 水平充满卡片（扣除卡片内边距）
        assert_true(comp.chart.width() >= comp.width() - 24,
                    f"{width}px 综合图未充满卡片 "
                    f"chart={comp.chart.width()} card={comp.width()}")
        assert_true(comp.chart.width() >= 560,
                    f"{width}px 综合图未达最小宽")
        widths.append(comp.chart.width())
    assert_true(widths[2] > widths[0],
                f"综合图未随页宽伸缩 {widths}")


print("\n==== test_fix_f4 ====")

if _FAILURES:
    print(f"\n失败 {len(_FAILURES)} 项: {_FAILURES}")
    sys.exit(1)
print("\n全部通过")
sys.exit(0)
