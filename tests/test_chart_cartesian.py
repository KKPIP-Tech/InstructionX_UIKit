# -*- coding: utf-8 -*-
"""chart cartesian 代理（C2）自测：10 个直角坐标系列（CHART_SPEC §5/§6）。

直接运行（无 pytest 依赖）::

    QT_QPA_PLATFORM=offscreen python tests/test_chart_cartesian.py

覆盖：
- 注册表：10 个系列全部注册，line 为 series_cartesian 完整版（覆盖 core）；
- 每个系列最小 option 出图 + hit_test 命中断言 + 非空白断言；
- bar：stack 堆叠基线、水平条（yAxis category）、update_option 数据变化动画；
- line/bar/scatter/candlestick/boxplot 的 value_at_index；
- 日历热力（coordinateSystem: calendar）；
- effectScatter 涟漪动画生命周期（QTimer 挂 ChartWidget，weakref 不泄漏）；
- 空数据 / None 不崩溃；
- grab 截图 tests/shots/chart_<type>.png（关键图亮 / 暗双主题）。
"""

import gc
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


from PySide6.QtCore import QPointF  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from InstructionX_UIKit.theme import ThemeManager  # noqa: E402
from InstructionX_UIKit.charts import SERIES_REGISTRY, ChartWidget  # noqa: E402

app = QApplication.instance() or QApplication(sys.argv)
ThemeManager.instance().apply(app)
ThemeManager.instance().set_mode("light")


def grab_image(widget):
    return widget.grab().toImage()


def count_colors(img, cap=5000):
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


def make_chart(option, w=520, h=340):
    """构造图表、跑完入场动画并完成一次 grab（强制布局 + 绘制）。"""
    chart = ChartWidget()
    chart.resize(w, h)
    chart.set_option(option)
    chart.anim.set_progress(1.0)
    img = grab_image(chart)
    return chart, img


CATS = ["一", "二", "三", "四", "五"]


# ---------------------------------------------------------------------------
# 注册表
# ---------------------------------------------------------------------------

@check("注册表：10 系列注册且 line 为完整版")
def _():
    want = ["bar", "pictorialBar", "line", "scatter", "effectScatter",
            "candlestick", "boxplot", "heatmap", "parallel", "themeRiver"]
    for t in want:
        assert_true(t in SERIES_REGISTRY, f"{t} 未注册")
    mod = SERIES_REGISTRY["line"].__module__
    assert_true(mod.endswith("series_cartesian"),
                f"line 未被完整版覆盖（{mod}）")


# ---------------------------------------------------------------------------
# bar
# ---------------------------------------------------------------------------

@check("bar：最小 option 出图 + hit_test + value_at_index")
def _():
    chart, img = make_chart({
        "title": {"text": "柱状图"},
        "xAxis": {"type": "category", "data": CATS},
        "yAxis": {"type": "value"},
        "series": [{"type": "bar", "name": "销量",
                    "data": [12, 20, 15, 28, 22],
                    "barBorderRadius": 3}],
    })
    assert_not_blank(img, "bar")
    img.save(str(SHOTS / "chart_bar.png"))
    r = chart.series_renderers[0]
    assert_eq(len(r._bars), 5, "柱数量")
    hit = r.hit_test(r._bars[2]["rect"].center())
    assert_true(hit is not None and hit["value"] == 15 and hit["name"] == "三",
                f"bar hit_test {hit}")
    info = r.value_at_index(0)
    assert_true(info and info["value"] == 12 and info.get("pos") is not None,
                "bar value_at_index")
    chart.deleteLater()


@check("bar：stack 堆叠基线与数值轴范围")
def _():
    chart, img = make_chart({
        "xAxis": {"type": "category", "data": CATS},
        "yAxis": {"type": "value"},
        "series": [
            {"type": "bar", "name": "甲", "stack": "总", "data": [10, 20, 15, 25, 20]},
            {"type": "bar", "name": "乙", "stack": "总", "data": [5, 10, 8, 12, 9]},
            {"type": "bar", "name": "丙", "data": [3, 6, 4, 8, 5]},
        ],
    })
    assert_not_blank(img, "bar stack")
    img.save(str(SHOTS / "chart_bar_stack.png"))
    a, b = chart.series_renderers[0], chart.series_renderers[1]
    assert_true(all(v == 0.0 for v in [bar["v0"] for bar in a._bars]),
                "stack 首系列基线应为 0")
    assert_eq([bar["v0"] for bar in b._bars], [10.0, 20.0, 15.0, 25.0, 20.0],
              "stack 次系列基线应为首系列值")
    coord = chart.primary_coord()
    assert_true(coord.y_axis.vmax >= 37, f"堆叠轴范围 {coord.y_axis.vmax}")
    chart.deleteLater()


@check("bar：yAxis category 自动水平条形")
def _():
    chart, img = make_chart({
        "yAxis": {"type": "category", "data": ["甲", "乙", "丙"]},
        "xAxis": {"type": "value"},
        "series": [{"type": "bar", "name": "H", "data": [10, 30, 20]}],
    })
    assert_not_blank(img, "bar horizontal")
    img.save(str(SHOTS / "chart_bar_horizontal.png"))
    r = chart.series_renderers[0]
    assert_true(r._horizontal, "未识别水平模式")
    rect = r._bars[0]["rect"]
    assert_true(rect.width() > rect.height(), "水平条应宽大于高")
    hit = r.hit_test(rect.center())
    assert_true(hit is not None and hit["value"] == 10, f"水平 hit {hit}")
    chart.deleteLater()


@check("bar：update_option 数据变化动画（prev_data 插值）")
def _():
    chart, _ = make_chart({
        "xAxis": {"type": "category", "data": CATS},
        "yAxis": {},
        "series": [{"type": "bar", "name": "A", "data": [12, 20, 15, 28, 22]}],
    })
    old_top = chart.series_renderers[0]._bars[0]["rect"].top()
    chart.update_option({"series": [{"type": "bar",
                                     "data": [30, 8, 25, 10, 26]}]})
    r = chart.series_renderers[0]
    assert_eq(r.prev_data, [12, 20, 15, 28, 22], "prev_data 未注入")
    chart.anim.set_progress(0.5)
    grab_image(chart)  # 中间帧绘制无异常
    chart.anim.set_progress(1.0)
    grab_image(chart)
    assert_true(r._bars[0]["rect"].top() != old_top, "数据未更新")
    chart.deleteLater()


# ---------------------------------------------------------------------------
# pictorialBar
# ---------------------------------------------------------------------------

@check("pictorialBar：symbol / symbolRepeat / symbolSize 出图")
def _():
    chart, img = make_chart({
        "xAxis": {"type": "category", "data": CATS},
        "yAxis": {},
        "series": [
            {"type": "pictorialBar", "name": "圆", "symbol": "circle",
             "symbolRepeat": True, "symbolSize": 12,
             "data": [30, 45, 25, 50, 40]},
            {"type": "pictorialBar", "name": "钉", "symbol": "pin",
             "symbolSize": [12, 14], "data": [20, 35, 30, 40, 28]},
        ],
    })
    assert_not_blank(img, "pictorialBar")
    img.save(str(SHOTS / "chart_pictorialbar.png"))
    r = chart.series_renderers[0]
    hit = r.hit_test(r._bars[1]["rect"].center())
    assert_true(hit is not None and hit["value"] == 45, f"pictorial hit {hit}")
    chart.deleteLater()


# ---------------------------------------------------------------------------
# line
# ---------------------------------------------------------------------------

@check("line：smooth + areaStyle + step + 虚线出图与命中")
def _():
    chart, img = make_chart({
        "title": {"text": "折线"},
        "tooltip": {"trigger": "axis"},
        "xAxis": {"type": "category", "data": CATS},
        "yAxis": {},
        "series": [
            {"type": "line", "name": "平滑", "smooth": True, "areaStyle": {},
             "data": [12, 22, 15, 28, 20]},
            {"type": "line", "name": "阶梯", "step": "middle", "showSymbol": False,
             "lineStyle": {"type": "dashed"}, "data": [8, 14, 18, 12, 24]},
        ],
    })
    assert_not_blank(img, "line")
    img.save(str(SHOTS / "chart_line.png"))
    r = chart.series_renderers[0]
    hit = r.hit_test(r._points[1])
    assert_true(hit is not None and hit["value"] == 22, f"line hit {hit}")
    info = r.value_at_index(3)
    assert_true(info and info["value"] == 28 and info.get("pos") is not None,
                "line value_at_index")
    chart.deleteLater()


# ---------------------------------------------------------------------------
# scatter
# ---------------------------------------------------------------------------

@check("scatter：固定 symbolSize 与第三维映射")
def _():
    chart, img = make_chart({
        "xAxis": {"type": "value"}, "yAxis": {},
        "series": [
            {"type": "scatter", "name": "固", "symbolSize": 14,
             "data": [[1, 3], [2, 5], [3, 4]]},
            {"type": "scatter", "name": "变",
             "data": [[1, 6, 10], [2, 8, 50], [3, 7, 30]]},
        ],
    })
    assert_not_blank(img, "scatter")
    img.save(str(SHOTS / "chart_scatter.png"))
    fixed, varied = chart.series_renderers
    assert_true(all(d["r"] == 7.0 for d in fixed._dots), "固定尺寸")
    rs = [d["r"] for d in varied._dots]
    assert_eq(rs, [3.0, 12.0, 7.5], "第三维 6~24px 线性映射")
    hit = varied.hit_test(varied._dots[1]["pt"])
    assert_true(hit is not None and hit["value"] == 8, f"scatter hit {hit}")
    info = fixed.value_at_index(0)
    assert_true(info and info["value"] == 3, "scatter value_at_index")
    chart.deleteLater()


# ---------------------------------------------------------------------------
# effectScatter
# ---------------------------------------------------------------------------

@check("effectScatter：涟漪动画出图 + 生命周期不泄漏")
def _():
    chart, img = make_chart({
        "xAxis": {"type": "value"}, "yAxis": {},
        "series": [{"type": "effectScatter", "name": "E",
                    "rippleEffect": {"period": 2, "scale": 3},
                    "data": [[1, 3], [2, 6], [3, 4]]}],
    })
    r = chart.series_renderers[0]
    assert_true(r._timer.isActive(), "涟漪 QTimer 未启动")
    r._tick()
    assert_true(0 < r._phase < 1, "相位推进")
    img2 = grab_image(chart)
    assert_not_blank(img2, "effectScatter")
    img2.save(str(SHOTS / "chart_effectscatter.png"))
    hit = r.hit_test(r._dots[0]["pt"])
    assert_true(hit is not None and hit["value"] == 3, f"effect hit {hit}")
    # 重建后旧渲染器被回收，其 QTimer 回调经 weakref 自动停止
    import weakref
    ref = weakref.ref(r)
    timer = r._timer
    chart.set_option({"xAxis": {"type": "value"}, "yAxis": {},
                      "series": [{"type": "scatter", "name": "S",
                                  "data": [[1, 1]]}]})
    chart.anim.set_progress(1.0)
    del r
    gc.collect()
    assert_true(ref() is None, "旧渲染器未被回收（weakref 泄漏）")
    timer.stop()
    timer.deleteLater()
    chart.deleteLater()


# ---------------------------------------------------------------------------
# candlestick
# ---------------------------------------------------------------------------

@check("candlestick：K线出图 + 涨跌配色 + 命中")
def _():
    chart, img = make_chart({
        "title": {"text": "K线"},
        "xAxis": {"type": "category", "data": ["一", "二", "三", "四"]},
        "yAxis": {},
        "series": [{"type": "candlestick", "name": "K",
                    "data": [[10, 15, 8, 16], [15, 12, 11, 17],
                             [12, 18, 10, 19], [18, 14, 13, 20]]}],
    })
    assert_not_blank(img, "candlestick")
    img.save(str(SHOTS / "chart_candlestick.png"))
    r = chart.series_renderers[0]
    assert_eq(len(r._items), 4, "K线数量")
    # 不同 K 应落在不同 x（类别对位）
    xs = [it["cx"] for it in r._items]
    assert_true(len(set(xs)) == 4, f"K线 x 位置 {xs}")
    coord = chart.primary_coord()
    body_mid = coord.y_axis.map((r._items[0]["open"] + r._items[0]["close"]) / 2,
                                coord.plot.bottom(), coord.plot.top())
    hit = r.hit_test(QPointF(r._items[0]["cx"], body_mid))
    assert_true(hit is not None and hit["value"][0] == 10, f"K hit {hit}")
    assert_true(hit["name"] == "一", "类别名")
    info = r.value_at_index(2)
    assert_true(info and info["value"] == 18 and info["name"] == "三",
                "candlestick value_at_index")
    # A 股红涨绿跌：colorUp/colorDown 可覆盖
    up, down = r._up_color(), r._down_color()
    assert_true(up.isValid() and down.isValid() and up != down, "涨跌配色")
    chart.deleteLater()


# ---------------------------------------------------------------------------
# boxplot
# ---------------------------------------------------------------------------

@check("boxplot：箱线出图 + 命中 + value_at_index")
def _():
    chart, img = make_chart({
        "xAxis": {"type": "category", "data": ["A", "B", "C"]},
        "yAxis": {},
        "series": [{"type": "boxplot", "name": "箱",
                    "data": [[5, 10, 15, 20, 25], [8, 12, 14, 19, 26],
                             [3, 9, 13, 17, 22]]}],
    })
    assert_not_blank(img, "boxplot")
    img.save(str(SHOTS / "chart_boxplot.png"))
    r = chart.series_renderers[0]
    assert_eq(len(r._items), 3, "箱线数量")
    hit = r.hit_test(QPointF(r._items[1]["cx"], 150))
    assert_true(hit is not None and hit["value"][2] == 14, f"box hit {hit}")
    info = r.value_at_index(0)
    assert_true(info and info["value"] == 15 and info.get("pos") is not None,
                "boxplot value_at_index")
    chart.deleteLater()


# ---------------------------------------------------------------------------
# heatmap（grid + calendar）
# ---------------------------------------------------------------------------

@check("heatmap：grid 直角热力（类别×类别）+ visualMap")
def _():
    chart, img = make_chart({
        "title": {"text": "热力"},
        "xAxis": {"type": "category", "data": ["一", "二", "三"]},
        "yAxis": {"type": "category", "data": ["上", "下"]},
        "visualMap": {"min": 0, "max": 10,
                      "inRange": {"colors": ["#EBEFF5", "#3F5E8C"]}},
        "series": [{"type": "heatmap", "name": "热",
                    "data": [[0, 0, 5], [1, 0, 9], [2, 0, 2],
                             [0, 1, 3], [1, 1, 7], [2, 1, 8]]}],
    })
    assert_not_blank(img, "heatmap grid")
    img.save(str(SHOTS / "chart_heatmap.png"))
    r = chart.series_renderers[0]
    assert_eq(len(r._cells), 6, "热力格数量")
    hit = r.hit_test(r._cells[4]["rect"].center())
    assert_true(hit is not None and hit["value"] == 7, f"heatmap hit {hit}")
    # visualMap 端点色应被采用
    assert_true(len({c["color"].rgba() for c in r._cells}) >= 4, "色带未分层")
    chart.deleteLater()


@check("heatmap：calendar 日历热力（GitHub 风格）")
def _():
    data = [["2026-01-05", 3], ["2026-02-14", 8], ["2026-04-22", 5],
            ["2026-07-09", 9], ["2026-10-01", 2], ["2026-12-31", 6]]
    chart, img = make_chart({
        "title": {"text": "提交热力"},
        "calendar": {"year": 2026, "cellSize": "auto"},
        "series": [{"type": "heatmap", "name": "提交",
                    "coordinateSystem": "calendar", "data": data}],
    }, w=680, h=240)
    assert_not_blank(img, "heatmap calendar")
    img.save(str(SHOTS / "chart_heatmap_calendar.png"))
    r = chart.series_renderers[0]
    assert_eq(len(r._cells), 6, "日历格数量")
    hit = r.hit_test(r._cells[1]["rect"].center())
    assert_true(hit is not None and hit["value"] == 8
                and hit["name"] == "2026-02-14", f"日历 hit {hit}")
    chart.deleteLater()


# ---------------------------------------------------------------------------
# parallel
# ---------------------------------------------------------------------------

@check("parallel：平行坐标出图 + 维度名 + 命中")
def _():
    chart, img = make_chart({
        "title": {"text": "成绩"},
        "parallelAxis": [{"name": "语文"}, {"name": "数学"}, {"name": "英语"}],
        "series": [{"type": "parallel", "name": "成绩",
                    "data": [[80, 90, 70], [60, 75, 88], [90, 85, 95]]}],
    })
    assert_not_blank(img, "parallel")
    img.save(str(SHOTS / "chart_parallel.png"))
    r = chart.series_renderers[0]
    assert_eq([a["name"] for a in r._axes], ["语文", "数学", "英语"], "维度名")
    assert_eq(len(r._rows), 3, "数据行")
    hit = r.hit_test(r._rows[0]["pts"][0])
    assert_true(hit is not None and hit["value"] == [80, 90, 70],
                f"parallel hit {hit}")
    chart.deleteLater()


@check("parallel：维度名取 data 第一行（字符串行）")
def _():
    chart, img = make_chart({
        "series": [{"type": "parallel", "name": "P",
                    "data": [["速度", "力量", "耐力"],
                             [7, 8, 6], [5, 9, 8]]}],
    })
    assert_not_blank(img, "parallel dims from data")
    r = chart.series_renderers[0]
    assert_eq([a["name"] for a in r._axes], ["速度", "力量", "耐力"],
              "data 首行维度名")
    assert_eq(len(r._rows), 2, "字符串首行不参与绘制")
    chart.deleteLater()


# ---------------------------------------------------------------------------
# themeRiver
# ---------------------------------------------------------------------------

@check("themeRiver：流带出图 + 居中基线 + 命中 + 时间标签")
def _():
    data = []
    times = ["2026-01", "2026-02", "2026-03", "2026-04", "2026-05", "2026-06"]
    for i, t in enumerate(times):
        data += [[t, 10 + i * 2, "甲"], [t, 20 - i, "乙"], [t, 5 + i, "丙"]]
    chart, img = make_chart({
        "title": {"text": "主题河"},
        "series": [{"type": "themeRiver", "name": "河", "data": data}],
    }, w=640, h=360)
    assert_not_blank(img, "themeRiver")
    img.save(str(SHOTS / "chart_themeriver.png"))
    r = chart.series_renderers[0]
    assert_eq([s["name"] for s in r._streams], ["甲", "乙", "丙"], "流带")
    # 居中基线：各时刻总宽关于中线对称（首流上缘 + 末流下缘 = 2*cy）
    cy = r._area.center().y()
    for i in range(len(times)):
        y0 = r._streams[0]["top"][i].y()
        y1 = r._streams[-1]["bot"][i].y()
        assert_true(abs((y0 + y1) / 2 - cy) < 1.0, f"基线未居中 col{i}")
    s1 = r._streams[1]
    mid = QPointF(s1["top"][3].x(), (s1["top"][3].y() + s1["bot"][3].y()) / 2)
    hit = r.hit_test(mid)
    assert_true(hit is not None and hit["name"] == "乙"
                and hit["x"] == "2026-04", f"themeRiver hit {hit}")
    chart.deleteLater()


# ---------------------------------------------------------------------------
# 暗色主题关键图
# ---------------------------------------------------------------------------

@check("暗色主题：bar / line / 日历热力 / 主题河截图")
def _():
    mgr = ThemeManager.instance()
    mgr.set_mode("dark")
    try:
        chart, img = make_chart({
            "title": {"text": "暗色"},
            "xAxis": {"type": "category", "data": CATS},
            "yAxis": {},
            "series": [
                {"type": "bar", "name": "A", "data": [12, 20, 15, 28, 22]},
                {"type": "line", "name": "B", "smooth": True, "areaStyle": {},
                 "data": [8, 14, 18, 12, 26]},
            ],
        })
        assert_not_blank(img, "dark bar+line")
        img.save(str(SHOTS / "chart_bar_dark.png"))
        chart.deleteLater()

        chart, img = make_chart({
            "calendar": {"year": 2026, "cellSize": "auto"},
            "series": [{"type": "heatmap", "name": "C",
                        "coordinateSystem": "calendar",
                        "data": [["2026-01-05", 3], ["2026-06-01", 9],
                                 ["2026-12-31", 5]]}],
        }, w=680, h=240)
        assert_not_blank(img, "dark calendar")
        img.save(str(SHOTS / "chart_heatmap_calendar_dark.png"))
        chart.deleteLater()

        chart, img = make_chart({
            "series": [{"type": "themeRiver", "name": "D",
                        "data": [["2026-01", 10, "甲"], ["2026-02", 14, "甲"],
                                 ["2026-03", 8, "甲"], ["2026-01", 6, "乙"],
                                 ["2026-02", 9, "乙"], ["2026-03", 12, "乙"]]}],
        }, w=640, h=360)
        assert_not_blank(img, "dark themeRiver")
        img.save(str(SHOTS / "chart_themeriver_dark.png"))
        chart.deleteLater()
    finally:
        mgr.set_mode("light")


# ---------------------------------------------------------------------------
# 空数据不崩溃
# ---------------------------------------------------------------------------

@check("空数据 / None 不崩溃（全部 10 类型）")
def _():
    types = ["bar", "pictorialBar", "line", "scatter", "effectScatter",
             "candlestick", "boxplot", "heatmap", "parallel", "themeRiver"]
    chart = ChartWidget()
    chart.resize(520, 340)
    for t in types:
        chart.set_option({
            "xAxis": {"type": "category", "data": []},
            "yAxis": {},
            "series": [{"type": t, "name": t, "data": []},
                       {"type": t, "name": t + "n", "data": [None, None]}],
        })
        chart.anim.set_progress(1.0)
        grab_image(chart)
    chart.set_option({"calendar": {"year": 2026},
                      "series": [{"type": "heatmap", "name": "h",
                                  "coordinateSystem": "calendar", "data": []}]})
    chart.anim.set_progress(1.0)
    img = grab_image(chart)
    assert_not_blank(img, "空数据重绘")
    chart.deleteLater()


print("\n==== test_chart_cartesian ====")

if _FAILURES:
    print(f"\n失败 {len(_FAILURES)} 项: {_FAILURES}")
    sys.exit(1)
print("\n全部通过")
sys.exit(0)
