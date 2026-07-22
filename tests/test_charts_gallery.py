# -*- coding: utf-8 -*-
"""Demo 图表页（InstructionX_UIKit.charts 原生引擎演示页）自测。

直接运行（无 pytest 依赖）::

    QT_QPA_PLATFORM=offscreen python tests/test_charts_gallery.py

覆盖：
- 页面实例化：ChartWidget 数量 >= 24（21 系列演示卡 + 4 坐标系/map +
  组件综合大图，共 27）；
- 逐图 set_option 无异常、grab 非空白（抽样像素）；
- 参数面板修改 2-3 个参数生效（bar 堆叠/柱宽、pie 环形/标签位置、
  gauge 目标值、综合演示标线切换）；
- 综合演示图 markPoint/markLine/markArea/dataZoom(slider+inside)/brush/
  toolbox/timeline 组件存在，timeline 三帧切换更新数据；
- 亮 / 暗整页截图 tests/shots/chartgallery_*.png；
- 任何失败退出码 1，全部通过退出码 0。
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


from PySide6.QtWidgets import QApplication  # noqa: E402

from InstructionX_UIKit.theme import ThemeManager  # noqa: E402
from InstructionX_UIKit.charts import ChartWidget  # noqa: E402
from InstructionX_UIKit.charts.components import (  # noqa: E402
    MarkAreaComponent,
    MarkLineComponent,
    MarkPointComponent,
)
from InstructionX_UIKit.charts.interact import (  # noqa: E402
    BrushComponent,
    ChartTimeline,
    DataZoomComponent,
    ToolboxComponent,
    VisualMapComponent,
)
from demo.pages import charts as charts_page  # noqa: E402
from demo.pages.charts import ChartDemoCard  # noqa: E402

app = QApplication.instance() or QApplication(sys.argv)
ThemeManager.instance().apply(app)
ThemeManager.instance().set_mode("light")

PAGE = None
CARDS = []


def grab_image(widget):
    return widget.grab().toImage()


def count_colors(img, cap=2000, step=4):
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


def card_by_title(keyword):
    for c in CARDS:
        if keyword in c.title_text:
            return c
    raise AssertionError(f"未找到演示卡: {keyword}")


def find_comp(chart, cls):
    for c in chart.components:
        if isinstance(c, cls):
            return c
    return None


# ---------------------------------------------------------------------------
# 页面实例化
# ---------------------------------------------------------------------------

@check("页面实例化：>= 24 个 ChartWidget")
def _():
    global PAGE, CARDS
    PAGE = charts_page.create_page()
    CARDS = PAGE.findChildren(ChartDemoCard)
    charts = PAGE.findChildren(ChartWidget)
    assert_true(len(charts) >= 24, f"ChartWidget 数量 {len(charts)} < 24")
    assert_eq(len(charts), len(CARDS), "每张演示卡应对应一个 ChartWidget")
    print(f"    演示卡 {len(CARDS)} 张，ChartWidget {len(charts)} 个")


# ---------------------------------------------------------------------------
# 逐图 set_option + 非空白
# ---------------------------------------------------------------------------

@check("逐图 set_option 无异常且非空白（抽样像素）")
def _():
    assert_true(PAGE is not None, "页面未实例化")
    for card in CARDS:
        card.apply()               # 重新 set_option 不抛异常
        card.finish_animation()
        img = grab_image(card.chart)
        assert_not_blank(img, card.title_text)


# ---------------------------------------------------------------------------
# 参数面板修改生效
# ---------------------------------------------------------------------------

@check("参数生效：bar 堆叠 / 柱宽 / 圆角")
def _():
    card = card_by_title("bar 柱状图")
    card.controls["stack"].setChecked(True)
    card.controls["barWidth"].setValue(0.9)
    card.controls["radius"].setValue(8)
    opt = card.chart.option()
    assert_eq(opt["series"][0].get("stack"), "总量", "stack 未生效")
    assert_true(abs(opt["series"][0]["barWidth"] - 0.9) < 1e-6,
                "barWidth 未生效")
    assert_eq(opt["series"][0]["barBorderRadius"], 8, "圆角未生效")
    card.finish_animation()
    assert_not_blank(grab_image(card.chart), "bar 参数修改后")


@check("参数生效：pie 环形 / 玫瑰 / 标签位置")
def _():
    card = card_by_title("pie 饼图")
    card.controls["donut"].setChecked(False)
    card.controls["rose"].setCurrentIndex(1)   # radius
    card.controls["labelPos"].setCurrentIndex(1)  # inside
    opt = card.chart.option()
    series = opt["series"][0]
    assert_eq(series.get("radius"), "72%", "取消环形未生效")
    assert_eq(series.get("roseType"), "radius", "玫瑰图未生效")
    assert_eq(series["label"]["position"], "inside", "标签位置未生效")
    card.controls["donut"].setChecked(True)
    opt = card.chart.option()
    assert_eq(opt["series"][0].get("radius"), ["42%", "72%"], "环形未恢复")
    card.finish_animation()
    assert_not_blank(grab_image(card.chart), "pie 参数修改后")


@check("参数生效：gauge 目标值 / graph 布局 / 综合演示标线")
def _():
    g = card_by_title("gauge 仪表盘")
    g.controls["value"].setValue(88)
    opt = g.chart.option()
    assert_eq(opt["series"][0]["data"][0]["value"], 88, "gauge 目标值未生效")

    gr = card_by_title("graph 关系图")
    gr.controls["layout"].setCurrentIndex(1)   # circular
    assert_eq(gr.chart.option()["series"][0]["layout"], "circular",
              "graph 布局未生效")

    comp = card_by_title("组件综合")
    comp.panel.controls["markLine"].setCurrentIndex(2)  # 警戒线 300
    ml = comp.chart.option()["series"][1]["markLine"]["data"]
    assert_eq(ml, [{"yAxis": 300, "name": "警戒线"}], "综合标线未生效")
    comp.finish_animation()
    assert_not_blank(grab_image(comp.chart), "综合演示参数修改后")


# ---------------------------------------------------------------------------
# 综合演示组件存在 + timeline 三帧切换
# ---------------------------------------------------------------------------

@check("综合演示：mark*/dataZoom/brush/toolbox/timeline/visualMap 组件存在")
def _():
    comp = card_by_title("组件综合")
    comp.apply()  # 还原默认参数（markArea 默认开）
    comp.finish_animation()
    chart = comp.chart
    for cls, key in ((MarkPointComponent, "markPoint"),
                     (MarkLineComponent, "markLine"),
                     (MarkAreaComponent, "markArea"),
                     (BrushComponent, "brush"),
                     (ToolboxComponent, "toolbox"),
                     (ChartTimeline, "timeline")):
        assert_true(find_comp(chart, cls) is not None, f"{key} 组件缺失")
    dz = find_comp(chart, DataZoomComponent)
    assert_true(dz is not None and dz.has_slider and dz.has_inside,
                "dataZoom 应同时含 slider 与 inside")
    # 开启 visualMap 后组件出现
    comp.panel.controls["visualMap"].setChecked(True)
    assert_true(find_comp(comp.chart, VisualMapComponent) is not None,
                "visualMap 组件缺失")
    comp.panel.controls["visualMap"].setChecked(False)


@check("综合演示：timeline 三帧切换更新数据")
def _():
    comp = card_by_title("组件综合")
    comp.apply()
    comp.finish_animation()
    chart = comp.chart
    years = charts_page._COMP_YEARS
    assert_eq(chart.option()["series"][0]["data"], years["2024"]["bar"],
              "初始帧应为 2024")
    tl = find_comp(chart, ChartTimeline)
    tl.goto(1)
    chart.anim.set_progress(1.0)
    assert_eq(chart.option()["series"][0]["data"], years["2025"]["bar"],
              "第二帧数据")
    assert_eq(chart.option()["series"][0].get("name"), "月度销量",
              "切帧后系列名应保留（帧携带完整系列定义）")
    assert_eq(chart.option()["series"][0].get("type"), "bar",
              "切帧后系列类型应保留")
    tl = find_comp(chart, ChartTimeline)  # 切帧后组件重建
    tl.goto(2)
    chart.anim.set_progress(1.0)
    assert_eq(chart.option()["series"][0]["data"], years["2026"]["bar"],
              "第三帧数据")
    assert_eq(chart.option()["series"][1]["data"], years["2026"]["line"],
              "第三帧折线数据")
    find_comp(chart, ChartTimeline).goto(0)  # 还原首帧
    chart.anim.set_progress(1.0)


# ---------------------------------------------------------------------------
# 亮 / 暗主题截图
# ---------------------------------------------------------------------------

def _grab_page():
    """整页内容截图（滚动区取内容控件，先按 sizeHint 调整尺寸）。"""
    content = PAGE.widget()
    hint = content.sizeHint()
    content.resize(max(hint.width(), 800), max(hint.height(), 400))
    return content.grab()


@check("亮 / 暗主题整页截图 chartgallery_*.png")
def _():
    mgr = ThemeManager.instance()
    mgr.set_mode("light")
    # 截图前恢复全部默认参数（前面检查修改过若干控件）
    for card in CARDS:
        card.form.reset()
        panel = getattr(card, "panel", None)
        if panel is not None:
            panel.reset()
        card.finish_animation()
    pm = _grab_page()
    img_light = pm.toImage()
    assert_not_blank(img_light, "亮主题整页")
    assert_true(pm.save(str(SHOTS / "chartgallery_light.png")), "亮图保存")

    comp = card_by_title("组件综合")
    comp.finish_animation()
    comp.chart.grab().save(str(SHOTS / "chartgallery_comprehensive.png"))

    mgr.set_mode("dark")
    pm_dark = _grab_page()
    img_dark = pm_dark.toImage()
    assert_not_blank(img_dark, "暗主题整页")
    assert_true(pm_dark.save(str(SHOTS / "chartgallery_dark.png")), "暗图保存")
    comp.chart.grab().save(str(SHOTS / "chartgallery_comprehensive_dark.png"))

    # 抽样比对：亮 / 暗背景应不同
    c_light = img_light.pixelColor(30, 30)
    c_dark = img_dark.pixelColor(30, 30)
    assert_true(c_light != c_dark, "主题切换背景未变化")
    mgr.set_mode("light")


print("\n==== test_charts_gallery ====")

if _FAILURES:
    print(f"\n失败 {len(_FAILURES)} 项: {_FAILURES}")
    sys.exit(1)
print("\n全部通过")
sys.exit(0)
