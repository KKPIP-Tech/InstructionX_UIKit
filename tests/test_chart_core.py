# -*- coding: utf-8 -*-
"""chart core 代理自测：图表引擎核心与四坐标系（CHART_SPEC §2/§3/§6）。

直接运行（无 pytest 依赖）::

    QT_QPA_PLATFORM=offscreen python tests/test_chart_core.py

覆盖：
- 注册表 / 协议（SERIES_REGISTRY / COMPONENT_REGISTRY / register_*）；
- Grid / Polar / SingleAxis / Calendar 四坐标系出图（内置 line + 测试渲染器）；
- title / legend / tooltip 显示（tooltip 用模拟鼠标移动触发），legend 点击切换显隐；
- update_option 旧→新动画推进无异常；
- 主题切换后重绘配色变化；
- nice_ticks 单测；空 series 不崩溃；
- grab 截图 tests/shots/chartcore_*.png（亮 / 暗）。
"""

import os
import sys
import traceback
import warnings
from pathlib import Path

# 模拟 QMouseEvent 构造在 Qt 6.11 标记 deprecated（功能正常），静默之
warnings.filterwarnings("ignore", category=DeprecationWarning)

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


from PySide6.QtCore import QEvent, QPointF, Qt  # noqa: E402
from PySide6.QtGui import QColor, QMouseEvent  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from InstructionX_UIKit.theme import T, ThemeManager  # noqa: E402
from InstructionX_UIKit.tokens import DURATION  # noqa: E402
from InstructionX_UIKit.charts import (  # noqa: E402
    COMPONENT_REGISTRY,
    SERIES_REGISTRY,
    AxisModel,
    CalendarCoord,
    ChartWidget,
    Coord,
    GridCoord,
    PolarCoord,
    SeriesRenderer,
    SingleAxisCoord,
    default_palette,
    nice_ticks,
    register_component,
    register_series,
)
from InstructionX_UIKit.charts.core import parse_data_point  # noqa: E402

app = QApplication.instance() or QApplication(sys.argv)
ThemeManager.instance().apply(app)
ThemeManager.instance().set_mode("light")


def grab_image(widget):
    pm = widget.grab()
    return pm.toImage()


def count_colors(img, cap=5000):
    """统计图像颜色种数（抽样上限 cap）。"""
    colors = set()
    for y in range(0, img.height(), 2):
        for x in range(0, img.width(), 2):
            colors.add(img.pixelColor(x, y).rgba())
            if len(colors) > cap:
                return len(colors)
    return len(colors)


def assert_not_blank(img, msg=""):
    n = count_colors(img)
    assert_true(n > 8, f"{msg} 图像疑似空白（颜色数 {n}）")


def make_chart(w=480, h=320):
    chart = ChartWidget()
    chart.resize(w, h)
    return chart


GRID_OPTION = {
    "title": {"text": "周销量", "subtext": "core 自检", "left": "center"},
    "legend": {"show": True, "orient": "horizontal"},
    "tooltip": {"show": True, "trigger": "axis"},
    "grid": {"left": 48, "right": 24, "top": 40, "bottom": 36},
    "xAxis": {"type": "category", "data": ["一", "二", "三", "四", "五"], "name": "星期"},
    "yAxis": {"type": "value", "name": "件"},
    "series": [
        {"type": "line", "name": "甲", "data": [12, 20, 15, 28, 22]},
        {"type": "line", "name": "乙", "data": [8, 14, 18, 12, 26]},
    ],
}


# ---------------------------------------------------------------------------
# 注册表 / 协议
# ---------------------------------------------------------------------------

@check("注册表与协议可用")
def _():
    assert_true("line" in SERIES_REGISTRY, "内置 line 未注册")

    class DummySeries(SeriesRenderer):
        def paint(self, p, anim_t):
            pass

    register_series("__dummy", DummySeries)
    assert_true(SERIES_REGISTRY["__dummy"] is DummySeries, "register_series 失败")

    class DummyComp:
        option_key = "__dummyComp"

        def __init__(self, chart, opt):
            self.chart, self.opt = chart, opt

    register_component("__dummyComp", DummyComp)
    assert_true(COMPONENT_REGISTRY["__dummyComp"] is DummyComp, "register_component 失败")
    # 协议方法存在
    for m in ("layout", "paint", "hit_test"):
        assert_true(hasattr(SeriesRenderer, m), f"SeriesRenderer 缺 {m}")
    for m in ("layout", "map_point", "paint_axes", "paint_tooltip_marker"):
        assert_true(hasattr(Coord, m), f"Coord 缺 {m}")
    pal = default_palette()
    assert_eq(len(pal), 8, "默认调色板长度")
    assert_true(all(isinstance(c, str) and c.startswith("#")
                    or c.startswith("rgb") for c in pal), "调色板格式")
    # parse_data_point
    assert_eq(parse_data_point(5, 0), (0, 5.0))
    assert_eq(parse_data_point([2, 7], 0), (2, 7.0))
    assert_eq(parse_data_point({"value": 9}, 1), (1, 9.0))
    assert_eq(parse_data_point(None, 3), (3, None))


# ---------------------------------------------------------------------------
# nice ticks
# ---------------------------------------------------------------------------

@check("nice_ticks 数值轴约 5 段")
def _():
    lo, hi, ticks = nice_ticks(3, 87)
    assert_true(lo <= 3 and hi >= 87, "nice 范围未包住数据")
    assert_true(4 <= len(ticks) <= 8, f"段数异常: {ticks}")
    assert_eq(ticks[0], lo)
    assert_eq(ticks[-1], hi)
    lo, hi, ticks = nice_ticks(0, 1)
    assert_true(len(ticks) >= 2, "退化范围")
    lo, hi, ticks = nice_ticks(5, 5)
    assert_true(lo < hi, "相等值未展开")
    lo, hi, ticks = nice_ticks(10, -10)
    assert_true(lo <= -10 and hi >= 10, "颠倒输入")
    lo, hi, ticks = nice_ticks(0.13, 0.97)
    assert_true(all(lo <= t <= hi for t in ticks), "ticks 越界")
    # AxisModel 集成
    ax = AxisModel({"type": "value", "min": 0, "max": 100})
    ax.set_extent(3, 87)
    assert_eq(ax.vmin, 0.0)
    assert_eq(ax.vmax, 100.0)


# ---------------------------------------------------------------------------
# Grid 坐标系出图 + title / legend
# ---------------------------------------------------------------------------

@check("Grid 坐标系出图（title/legend/axis）")
def _():
    chart = make_chart()
    chart.set_option(GRID_OPTION)
    chart.anim.set_progress(1.0)
    img = grab_image(chart)
    assert_not_blank(img, "grid")
    assert_true(isinstance(chart.primary_coord(), GridCoord), "主坐标系类型")
    chart.set_option({})  # 清空不崩溃
    chart.anim.set_progress(1.0)
    grab_image(chart)
    chart.deleteLater()


# ---------------------------------------------------------------------------
# Polar / SingleAxis / Calendar
# ---------------------------------------------------------------------------

@check("Polar 坐标系出图（内置 line, coordinateSystem=polar）")
def _():
    chart = make_chart()
    chart.set_option({
        "title": {"text": "能力雷达底图"},
        "polar": {"shape": "polygon"},
        "angleAxis": {"type": "category",
                      "data": ["速", "力", "防", "敏", "智", "运"]},
        "radiusAxis": {"type": "value"},
        "series": [{
            "type": "line", "name": "A", "coordinateSystem": "polar",
            "data": [["速", 80], ["力", 60], ["防", 70],
                     ["敏", 90], ["智", 65], ["运", 75]],
        }],
    })
    chart.anim.set_progress(1.0)
    img = grab_image(chart)
    assert_not_blank(img, "polar")
    coord = chart.primary_coord()
    assert_true(isinstance(coord, PolarCoord), "polar 坐标系类型")
    pt = coord.map_point("速", 50)
    assert_true(0 < pt.x() < chart.width() and 0 < pt.y() < chart.height(),
                "polar map_point 越界")
    img.save(str(SHOTS / "chartcore_polar_light.png"))
    chart.deleteLater()


@check("SingleAxis 坐标系出图")
def _():
    chart = make_chart()
    chart.set_option({
        "title": {"text": "单轴"},
        "singleAxis": {"left": 40, "right": 40, "name": "分"},
        "series": [{
            "type": "line", "name": "S", "coordinateSystem": "singleAxis",
            "data": [10, 40, 25, 70, 55],
        }],
    })
    chart.anim.set_progress(1.0)
    img = grab_image(chart)
    assert_not_blank(img, "singleAxis")
    assert_true(isinstance(chart.primary_coord(), SingleAxisCoord), "single 类型")
    img.save(str(SHOTS / "chartcore_single_light.png"))
    chart.deleteLater()


@check("Calendar 坐标系出图 + map_point/date_at")
def _():
    chart = make_chart(640, 240)
    data = [["2026-01-05", 3], ["2026-02-14", 8], ["2026-06-01", 5],
            ["2026-11-20", 9], ["2026-12-31", 2]]
    chart.set_option({
        "title": {"text": "提交热力底图"},
        "calendar": {"year": 2026, "cellSize": "auto"},
        "series": [{
            "type": "line", "name": "C", "coordinateSystem": "calendar",
            "data": data,
        }],
    })
    chart.anim.set_progress(1.0)
    img = grab_image(chart)
    assert_not_blank(img, "calendar")
    coord = chart.primary_coord()
    assert_true(isinstance(coord, CalendarCoord), "calendar 类型")
    center = coord.map_point("2026-06-01")
    assert_true(coord.cell_rect("2026-06-01").contains(center), "cell 中心不在格内")
    d = coord.date_at(center)
    assert_true(d is not None and d.month == 6 and d.day == 1, f"date_at 反查 {d}")
    assert_true(coord.weeks() >= 52, "周数")
    img.save(str(SHOTS / "chartcore_calendar_light.png"))
    chart.deleteLater()


# ---------------------------------------------------------------------------
# 测试渲染器经注册表挂载（协议链路）
# ---------------------------------------------------------------------------

@check("自定义测试渲染器经注册表出图")
def _():
    class DotRenderer(SeriesRenderer):
        def __init__(self, chart, opt):
            super().__init__(chart, opt)
            self.pts = []

        def layout(self, rect):
            coord = self.chart.coord_for(self.opt)
            self.pts = []
            for i, item in enumerate(self.data()):
                x, y = parse_data_point(item, i)
                if y is not None and coord is not None:
                    self.pts.append(coord.map_point(x, y))

        def paint(self, p, anim_t):
            p.save()
            p.setPen(Qt.NoPen)
            p.setBrush(self.color())
            for pt in self.pts:
                p.drawEllipse(pt, 6 * anim_t, 6 * anim_t)
            p.restore()

        def hit_test(self, pos):
            for i, pt in enumerate(self.pts):
                if (pt - pos).manhattanLength() < 12:
                    return {"name": self.name, "value": i, "series": self.name}
            return None

    register_series("__dots", DotRenderer)
    chart = make_chart()
    chart.set_option({
        "xAxis": {"type": "category", "data": ["a", "b", "c"]},
        "yAxis": {},
        "series": [{"type": "__dots", "name": "D", "data": [3, 7, 5]}],
    })
    chart.anim.set_progress(1.0)
    img = grab_image(chart)
    assert_not_blank(img, "dots")
    r = chart.series_renderers[0]
    assert_true(len(r.pts) == 3, "layout 未生成点")
    hit = r.hit_test(r.pts[1])
    assert_true(hit is not None and hit["value"] == 1, "hit_test 失败")
    chart.deleteLater()


# ---------------------------------------------------------------------------
# tooltip（模拟鼠标移动）
# ---------------------------------------------------------------------------

def mouse_move(widget, x, y):
    ev = QMouseEvent(QEvent.MouseMove, QPointF(x, y),
                     Qt.NoButton, Qt.NoButton, Qt.NoModifier)
    widget.mouseMoveEvent(ev)


def mouse_press(widget, pos):
    ev = QMouseEvent(QEvent.MouseButtonPress, QPointF(pos),
                     Qt.LeftButton, Qt.LeftButton, Qt.NoModifier)
    widget.mousePressEvent(ev)


@check("tooltip axis 触发（模拟鼠标移动 + 十字线浮层）")
def _():
    chart = make_chart()
    chart.set_option(GRID_OPTION)
    chart.anim.set_progress(1.0)
    grab_image(chart)  # 强制完成一次布局
    coord = chart.primary_coord()
    anchor = coord.map_point(2, 15)
    mouse_move(chart, anchor.x(), anchor.y())
    assert_true(chart.tooltip.active, "tooltip 未激活")
    assert_true(len(chart.tooltip._lines) >= 2, "axis 聚合行数")
    img = grab_image(chart)
    assert_not_blank(img, "tooltip")
    img.save(str(SHOTS / "chartcore_tooltip_light.png"))
    chart.deleteLater()


@check("tooltip item 触发 + 空白处隐藏")
def _():
    opt = dict(GRID_OPTION)
    opt["tooltip"] = {"show": True, "trigger": "item"}
    chart = make_chart()
    chart.set_option(opt)
    chart.anim.set_progress(1.0)
    grab_image(chart)
    r = chart.series_renderers[0]
    pt = r._points[1]
    mouse_move(chart, pt.x(), pt.y())
    assert_true(chart.tooltip.active, "item tooltip 未激活")
    mouse_move(chart, 3, chart.height() - 3)  # 角落空白
    assert_true(not chart.tooltip.active, "tooltip 未隐藏")
    chart.deleteLater()


# ---------------------------------------------------------------------------
# legend 点击切换系列显隐
# ---------------------------------------------------------------------------

@check("legend 点击切换系列显隐")
def _():
    chart = make_chart()
    chart.set_option(GRID_OPTION)
    chart.anim.set_progress(1.0)
    grab_image(chart)
    assert_true(chart.legend.shown, "legend 未显示")
    assert_true(len(chart.legend._item_rects) == 2, "legend 条目数")
    target = chart.legend._item_rects[0].center()
    name0 = chart.series_renderers[0].name
    assert_true(chart.is_series_visible(name0), "初始应可见")
    mouse_press(chart, target)
    assert_true(not chart.is_series_visible(name0), "点击后未隐藏")
    assert_true(not chart.series_renderers[0].visible, "渲染器 visible 未同步")
    mouse_press(chart, target)
    assert_true(chart.is_series_visible(name0), "再次点击未恢复")
    chart.deleteLater()


# ---------------------------------------------------------------------------
# update_option 动画推进
# ---------------------------------------------------------------------------

@check("update_option 合并 + 旧→新动画推进无异常")
def _():
    chart = make_chart()
    chart.set_option(GRID_OPTION)
    chart.anim.set_progress(1.0)
    grab_image(chart)
    old_pts = list(chart.series_renderers[0]._points)
    chart.update_option({"series": [{"data": [24, 10, 26, 12, 30]}]})
    assert_true(chart.series_renderers[0].prev_data == [12, 20, 15, 28, 22],
                "prev_data 未注入")
    # 手动推进中间帧
    chart.anim.set_progress(0.5)
    grab_image(chart)
    # 合并语义：title 保持不变、series data 已替换
    assert_eq(chart.option()["title"]["text"], "周销量", "深合并丢 title")
    new_pts = chart.series_renderers[0]._points
    assert_true(len(new_pts) == len(old_pts), "点位数量变化异常")
    assert_true(new_pts[0].y() != old_pts[0].y(), "数据未更新")
    chart.deleteLater()


@check("动画真实播放至 t=1")
def _():
    from PySide6.QtTest import QTest
    chart = make_chart()
    chart.set_option(GRID_OPTION)
    chart.anim.start()
    QTest.qWait(int(DURATION["slow"]) + 150)
    assert_true(abs(chart.anim.t - 1.0) < 1e-6, f"动画未收敛 t={chart.anim.t}")
    grab_image(chart)
    chart.deleteLater()


# ---------------------------------------------------------------------------
# 主题切换重绘配色变化
# ---------------------------------------------------------------------------

@check("主题切换后重绘配色变化")
def _():
    mgr = ThemeManager.instance()
    mgr.set_mode("light")
    chart = make_chart()
    chart.set_option(GRID_OPTION)
    chart.anim.set_progress(1.0)
    img_light = grab_image(chart)
    img_light.save(str(SHOTS / "chartcore_grid_light.png"))
    mgr.set_mode("dark")
    img_dark = grab_image(chart)
    img_dark.save(str(SHOTS / "chartcore_grid_dark.png"))
    assert_not_blank(img_dark, "dark")
    c_light = img_light.pixelColor(10, 10)
    c_dark = img_dark.pixelColor(10, 10)
    assert_true(c_light != c_dark, "主题切换背景未变化")
    # 调色板实时取色验证
    assert_true(default_palette()[0] == T("color.primary"), "调色板未随主题更新")
    mgr.set_mode("light")
    chart.deleteLater()


# ---------------------------------------------------------------------------
# 空数据不崩溃
# ---------------------------------------------------------------------------

@check("空 series / None 数据不崩溃")
def _():
    chart = make_chart()
    chart.set_option({"series": []})
    chart.anim.set_progress(1.0)
    grab_image(chart)
    chart.set_option({
        "xAxis": {"type": "category", "data": []},
        "series": [{"type": "line", "name": "E", "data": []},
                   {"type": "line", "name": "N", "data": [None, None]},
                   {"type": "未注册类型", "name": "U", "data": [1, 2]}],
    })
    chart.anim.set_progress(1.0)
    img = grab_image(chart)
    assert_not_blank(img, "空数据重绘")
    chart.update_option({"series": [{"data": None}]})
    chart.anim.set_progress(1.0)
    grab_image(chart)
    mouse_move(chart, 100, 100)
    chart.deleteLater()


print("\n==== test_chart_core ====")
# 执行全部已登记检查（check 装饰器在定义时即执行）

if _FAILURES:
    print(f"\n失败 {len(_FAILURES)} 项: {_FAILURES}")
    sys.exit(1)
print("\n全部通过")
sys.exit(0)
