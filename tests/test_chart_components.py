# -*- coding: utf-8 -*-
"""chart components 代理自测：标注组件 / map 系列 / 交互组件（CHART_SPEC §5 C4）。

直接运行（无 pytest 依赖）::

    QT_QPA_PLATFORM=offscreen python tests/test_chart_components.py

覆盖：
- markPoint / markLine / markArea：综合 option（bar+line）上渲染 + 像素断言；
- graphic：circle/rect/text/line 四元素出图 + 像素断言；
- map 系列：内置示意地图出图 + 区域着色 + hit_test 命中 + 自定义 geo.regions；
- dataZoom：slider 把手拖动改变可视范围（模拟鼠标）、inside 滚轮缩放 +
  拖拽平移、restore 还原；
- brush：矩形刷选 selected 非空 + selected 信号；
- visualMap：map_color 两端值颜色 = 色带端点；
- timeline：goto 切帧更新 option、播放按钮切换；
- toolbox：按钮点击命中回调 + dataZoom 开关 + saveAsImage offscreen 降级；
- grab 截图 tests/shots/chartcomp_*.png（关键亮 / 暗），退出码 0。
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


from PySide6.QtCore import QEvent, QPoint, QPointF, QRectF, Qt  # noqa: E402
from PySide6.QtGui import QColor, QMouseEvent, QWheelEvent  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from InstructionX_UIKit.theme import T, ThemeManager  # noqa: E402
from InstructionX_UIKit.charts import (  # noqa: E402
    COMPONENT_REGISTRY,
    SERIES_REGISTRY,
    ChartWidget,
    GridCoord,
    SeriesRenderer,
    register_series,
)
from InstructionX_UIKit.charts.core import parse_data_point  # noqa: E402
from InstructionX_UIKit.charts.components import (  # noqa: E402
    DEMO_MAP,
    GraphicComponent,
    MapSeriesRenderer,
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

app = QApplication.instance() or QApplication(sys.argv)
ThemeManager.instance().apply(app)
ThemeManager.instance().set_mode("light")


# ---------------------------------------------------------------------------
# 工具
# ---------------------------------------------------------------------------

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


def color_close(c1, c2, tol=12):
    """两颜色 RGB 各通道差不超过 tol。"""
    a, b = QColor(c1), QColor(c2)
    return all(abs(x - y) <= tol for x, y in
               ((a.red(), b.red()), (a.green(), b.green()), (a.blue(), b.blue())))


def mouse_press(widget, pos):
    ev = QMouseEvent(QEvent.MouseButtonPress, QPointF(pos),
                     Qt.LeftButton, Qt.LeftButton, Qt.NoModifier)
    widget.mousePressEvent(ev)


def mouse_move(widget, pos):
    ev = QMouseEvent(QEvent.MouseMove, QPointF(pos),
                     Qt.LeftButton, Qt.LeftButton, Qt.NoModifier)
    widget.mouseMoveEvent(ev)


def mouse_release(widget, pos):
    ev = QMouseEvent(QEvent.MouseButtonRelease, QPointF(pos),
                     Qt.LeftButton, Qt.NoButton, Qt.NoModifier)
    widget.mouseReleaseEvent(ev)


def wheel(widget, pos, delta_y=120):
    g = widget.mapToGlobal(QPoint(int(pos.x()), int(pos.y())))
    ev = QWheelEvent(QPointF(pos), QPointF(g), QPoint(0, 0), QPoint(0, delta_y),
                     Qt.NoButton, Qt.NoModifier, Qt.NoScrollPhase, False)
    QApplication.sendEvent(widget, ev)


def make_chart(w=520, h=360):
    chart = ChartWidget()
    chart.resize(w, h)
    return chart


def find_comp(chart, cls):
    for c in chart.components:
        if isinstance(c, cls):
            return c
    return None


# ---------------------------------------------------------------------------
# 最小 bar 渲染器（C2 未合入时兜底，保证综合 option 含 bar+line）
# ---------------------------------------------------------------------------

class _TestBarRenderer(SeriesRenderer):
    """测试用极简 bar 渲染器（仅在本测试 SERIES_REGISTRY 缺 bar 时注册）。"""

    def __init__(self, chart, opt):
        super().__init__(chart, opt)
        self._bars = []

    def layout(self, rect):
        self._bars = []
        coord = self.chart.coord_for(self.opt)
        if not isinstance(coord, GridCoord):
            return
        bw = coord.x_axis.band_width(coord.plot.left(), coord.plot.right()) * 0.4
        for i, item in enumerate(self.data()):
            x, y = parse_data_point(item, i)
            if y is None:
                continue
            top = coord.map_point(x, y)
            base = coord.map_point(x, 0)
            self._bars.append(QRectF(top.x() - bw / 2, top.y(),
                                     bw, base.y() - top.y()))

    def paint(self, p, anim_t):
        from PySide6.QtGui import QPainter  # noqa
        p.save()
        p.setPen(Qt.NoPen)
        p.setBrush(self.color())
        for r in self._bars:
            p.drawRect(r)
        p.restore()

    def hit_test(self, pos):
        for i, r in enumerate(self._bars):
            if r.contains(pos):
                return {"name": self.name, "value": i, "series": self.name}
        return None


if "bar" not in SERIES_REGISTRY:
    register_series("bar", _TestBarRenderer)

# ---------------------------------------------------------------------------
# 综合 option（bar + line，标注挂在 line 系列上）
# ---------------------------------------------------------------------------

MARKS_OPTION = {
    "title": {"text": "标注组件综合", "left": "center"},
    "tooltip": {"show": False},
    "grid": {"left": 48, "right": 24, "top": 40, "bottom": 36},
    "xAxis": {"type": "category", "data": ["一", "二", "三", "四", "五"]},
    "yAxis": {"type": "value"},
    "series": [
        {"type": "bar", "name": "柱", "data": [8, 14, 10, 18, 13]},
        {"type": "line", "name": "线", "data": [12, 20, 15, 28, 22],
         "markPoint": {"data": [{"type": "max"}, {"type": "min"},
                                {"coord": [2, 15], "name": "中"}]},
         "markLine": {"data": [{"yAxis": 5, "name": "阈值"}]},
         "markArea": {"data": [[{"xAxis": "二"}, {"xAxis": "四"}]]}},
    ],
}


@check("组件注册齐全（mark*/graphic/dataZoom/brush/visualMap/timeline/toolbox + map 系列）")
def _():
    for key in ("markPoint", "markLine", "markArea", "graphic",
                "dataZoom", "brush", "visualMap", "timeline", "toolbox"):
        assert_true(key in COMPONENT_REGISTRY, f"{key} 未注册")
    assert_true("map" in SERIES_REGISTRY, "map 系列未注册")
    assert_true(6 <= len(DEMO_MAP) <= 8, "内置示意地图应为 6-8 个大区块")


@check("markPoint：max/min/coord 标注 + 像素断言")
def _():
    chart = make_chart()
    chart.set_option(MARKS_OPTION)
    chart.anim.set_progress(1.0)
    img = grab_image(chart)
    assert_not_blank(img, "markPoint")
    mp = find_comp(chart, MarkPointComponent)
    assert_true(mp is not None, "markPoint 组件未实例化")
    assert_eq(len(mp._marks), 3, "markPoint 标注数")
    texts = [m["text"] for m in mp._marks]
    assert_true("28" in texts and "12" in texts and "中" in texts,
                f"markPoint 文本 {texts}")
    # 最大值点：markPoint 实心圆（系列色）覆盖在系列空心点之上
    max_mark = mp._marks[0]
    pos = max_mark["pos"]
    line_renderer = chart.series_renderers[1]
    sampled = img.pixelColor(int(pos.x()), int(pos.y()))
    assert_true(color_close(sampled, line_renderer.color(), 20),
                f"max 标注点像素 {sampled.name()} 应接近系列色 "
                f"{line_renderer.color().name()}")
    # hit_test
    hit = mp.hit_test(pos)
    assert_true(hit is not None and hit["value"] == 28.0, f"markPoint 命中 {hit}")
    chart.deleteLater()


@check("markLine：指定 yAxis 虚线 + 像素断言")
def _():
    chart = make_chart()
    chart.set_option(MARKS_OPTION)
    chart.anim.set_progress(1.0)
    img = grab_image(chart)
    ml = find_comp(chart, MarkLineComponent)
    assert_true(ml is not None and len(ml._lines) == 1, "markLine 条目")
    assert_true("阈值" in ml._lines[0]["text"], "markLine 标签")
    coord = chart.primary_coord()
    plot = coord.plot
    py = coord.y_axis.map(5.0, plot.bottom(), plot.top())
    color = chart.series_renderers[1].color()
    # y=5 低于系列全部数据（min 8），该行上的系列色像素只能来自 markLine 虚线
    hits = 0
    for x in range(int(plot.left()) + 2, int(plot.right()) - 2):
        for dy in (-1, 0, 1):
            if color_close(img.pixelColor(x, int(py) + dy), color, 40):
                hits += 1
                break
    assert_true(hits >= 8, f"markLine 虚线像素过少（{hits}）")
    chart.deleteLater()


@check("markArea：区间半透明填充 + 像素断言")
def _():
    chart = make_chart()
    chart.set_option(MARKS_OPTION)
    chart.anim.set_progress(1.0)
    img = grab_image(chart)
    ma = find_comp(chart, MarkAreaComponent)
    assert_true(ma is not None and len(ma._areas) == 1, "markArea 区域数")
    area = ma._areas[0]
    assert_true(area.width() > 20 and area.height() > 40, "markArea 尺寸")
    bg = QColor(T("color.bg.base"))
    # 域内像素应比背景暗（primary 低透明度填充），域外同高度像素保持背景
    sx = int(area.center().x() + area.width() * 0.2)
    sy = int(area.top() + 5)
    inside = img.pixelColor(sx, sy)
    assert_true(inside.red() <= bg.red() - 6,
                f"markArea 域内像素 {inside.name()} 应比背景 {bg.name()} 暗")
    hit = ma.hit_test(QPointF(sx, sy))
    assert_true(hit is not None, "markArea 命中失败")
    chart.deleteLater()


@check("标注综合截图（亮 / 暗）")
def _():
    chart = make_chart()
    chart.set_option(MARKS_OPTION)
    chart.anim.set_progress(1.0)
    img = grab_image(chart)
    img.save(str(SHOTS / "chartcomp_marks_light.png"))
    mgr = ThemeManager.instance()
    mgr.set_mode("dark")
    img = grab_image(chart)
    assert_not_blank(img, "marks dark")
    img.save(str(SHOTS / "chartcomp_marks_dark.png"))
    mgr.set_mode("light")
    chart.deleteLater()


@check("graphic：circle/rect/text/line 四元素 + 像素断言")
def _():
    chart = make_chart()
    chart.set_option({
        "xAxis": {"type": "category", "data": ["A", "B"]},
        "yAxis": {"type": "value"},
        "series": [{"type": "line", "name": "L", "data": [1, 2]}],
        "graphic": [
            {"type": "circle", "left": 60, "top": 60,
             "shape": {"r": 12}, "style": {"fill": "#E64545"}},
            {"type": "rect", "left": 100, "top": 48,
             "shape": {"width": 36, "height": 20, "r": 3},
             "style": {"fill": "#3FA46A"}},
            {"type": "text", "left": 150, "top": 48,
             "style": {"text": "水印文本", "fill": "#C78A2B", "fontSize": 14}},
            {"type": "line", "left": 60, "top": 90,
             "shape": {"x1": 0, "y1": 0, "x2": 120, "y2": 0},
             "style": {"stroke": "#7A4FC0", "lineWidth": 2}},
        ],
    })
    chart.anim.set_progress(1.0)
    img = grab_image(chart)
    assert_not_blank(img, "graphic")
    gc = find_comp(chart, GraphicComponent)
    assert_true(gc is not None and len(gc.elements) == 4, "graphic 元素数")
    content_top = chart.title.height()  # 无标题 → 0，内容区即全图
    assert_eq(content_top, 0.0, "本 option 无标题")
    assert_true(color_close(img.pixelColor(60, 60), "#E64545", 30), "circle 像素")
    assert_true(color_close(img.pixelColor(112, 58), "#3FA46A", 30), "rect 像素")
    found_line = any(
        color_close(img.pixelColor(x, 90), "#7A4FC0", 40) for x in range(62, 178))
    assert_true(found_line, "line 元素像素")
    chart.deleteLater()


@check("map 系列：内置示意地图出图 + 命中 + 着色")
def _():
    chart = make_chart()
    chart.set_option({
        "title": {"text": "示意地图"},
        "visualMap": {"min": 0, "max": 100,
                      "inRange": {"colors": ["#EBEFF5", "#3F5E8C"]},
                      "orient": "vertical"},
        "series": [{
            "type": "map", "name": "销量", "map": "demo",
            "data": [{"name": "华北", "value": 80}, {"name": "华南", "value": 30},
                     {"name": "西北", "value": 55}],
        }],
    })
    chart.anim.set_progress(1.0)
    img = grab_image(chart)
    assert_not_blank(img, "map")
    r = chart.series_renderers[0]
    assert_true(isinstance(r, MapSeriesRenderer), "map 渲染器类型")
    assert_eq(len(r._polys), len(DEMO_MAP), "区域多边形数")
    polys = dict(r._polys)
    center = polys["华北"].boundingRect().center()
    hit = r.hit_test(center)
    assert_true(hit is not None and hit["name"] == "华北"
                and hit["value"] == 80.0, f"map 命中 {hit}")
    # 有值区域着色（非背景色），visualMap 端值=色带末端
    px = img.pixelColor(int(center.x()), int(center.y()))
    vm = find_comp(chart, VisualMapComponent)
    assert_true(color_close(px, vm.map_color(80), 30),
                f"华北区域像素 {px.name()} 应接近 map_color(80) "
                f"{vm.map_color(80).name()}")
    img.save(str(SHOTS / "chartcomp_map_light.png"))
    mgr = ThemeManager.instance()
    mgr.set_mode("dark")
    img = grab_image(chart)
    assert_not_blank(img, "map dark")
    img.save(str(SHOTS / "chartcomp_map_dark.png"))
    mgr.set_mode("light")
    chart.deleteLater()


@check("map 系列：自定义 geo.regions 多边形")
def _():
    chart = make_chart(400, 280)
    chart.set_option({
        "geo": {"regions": {
            "甲区": [[0, 0], [40, 0], [20, 30]],
            "乙区": [[45, 0], [85, 0], [65, 30]],
        }},
        "series": [{"type": "map", "name": "M", "map": "custom",
                    "data": [{"name": "甲区", "value": 10}]}],
    })
    chart.anim.set_progress(1.0)
    img = grab_image(chart)
    assert_not_blank(img, "custom map")
    r = chart.series_renderers[0]
    assert_eq(len(r._polys), 2, "自定义区域数")
    names = {n for n, _ in r._polys}
    assert_eq(names, {"甲区", "乙区"}, "自定义区域名")
    chart.deleteLater()


# ---------------------------------------------------------------------------
# 交互组件
# ---------------------------------------------------------------------------

def _zoom_option(entries):
    return {
        "tooltip": {"show": False},
        "xAxis": {"type": "category",
                  "data": ["一", "二", "三", "四", "五", "六", "七", "八"]},
        "yAxis": {"type": "value"},
        "series": [{"type": "line", "name": "L",
                    "data": [5, 9, 7, 12, 8, 14, 6, 11]}],
        "dataZoom": entries,
    }


@check("dataZoom slider：把手拖动改变可视范围 + restore")
def _():
    chart = make_chart()
    chart.set_option(_zoom_option([{"type": "slider", "start": 0, "end": 100}]))
    chart.anim.set_progress(1.0)
    grab_image(chart)
    dz = find_comp(chart, DataZoomComponent)
    assert_true(dz is not None and dz.has_slider, "slider 组件")
    axis = chart.primary_coord().x_axis
    assert_eq(len(axis.categories), 8, "初始类别数")
    # 拖动右把手到轨道中点：end ≈ 50 → 可视类别应减少
    start_pos = dz._h_end.center()
    target = QPointF(dz._track.left() + dz._track.width() * 0.5, start_pos.y())
    mouse_press(chart, start_pos)
    mouse_move(chart, target)
    mouse_release(chart, target)
    grab_image(chart)
    assert_true(dz.end < 70, f"拖动后 end={dz.end}")
    assert_true(len(axis.categories) < 8,
                f"可视类别未收缩: {axis.categories}")
    # 拖动左把手向右：start 增大
    hs = dz._h_start.center()
    tgt = QPointF(dz._track.left() + dz._track.width() * 0.25, hs.y())
    mouse_press(chart, hs)
    mouse_move(chart, tgt)
    mouse_release(chart, tgt)
    grab_image(chart)
    assert_true(dz.start > 5, f"拖动后 start={dz.start}")
    # restore 还原
    dz.restore()
    grab_image(chart)
    assert_true(abs(dz.start - 0) < 1e-6 and abs(dz.end - 100) < 1e-6,
                "restore 未还原窗口")
    assert_eq(len(axis.categories), 8, "restore 后类别数")
    chart.deleteLater()


@check("dataZoom inside：滚轮缩放 + 拖拽平移")
def _():
    chart = make_chart()
    chart.set_option(_zoom_option([{"type": "inside", "start": 0, "end": 100}]))
    chart.anim.set_progress(1.0)
    grab_image(chart)
    dz = find_comp(chart, DataZoomComponent)
    assert_true(dz is not None and dz.has_inside, "inside 组件")
    plot = chart.primary_coord().plot
    center = plot.center()
    # 滚轮向上：窗口收缩
    wheel(chart, center, 120)
    grab_image(chart)
    span1 = dz.end - dz.start
    assert_true(span1 < 100, f"滚轮缩放未生效（span={span1}）")
    # 滚轮向下：窗口放大
    wheel(chart, center, -120)
    wheel(chart, center, -120)
    grab_image(chart)
    assert_true(dz.end - dz.start > span1, "滚轮缩小窗口未放大")
    # 按住向左拖拽：窗口右移（start 增大）
    dz.start, dz.end = 20.0, 80.0
    dz.apply()
    grab_image(chart)
    press = QPointF(center.x(), center.y())
    mouse_press(chart, press)
    mouse_move(chart, QPointF(press.x() - 40, press.y()))
    mouse_release(chart, QPointF(press.x() - 40, press.y()))
    grab_image(chart)
    assert_true(dz.start > 20.0, f"拖拽平移未生效（start={dz.start}）")
    chart.deleteLater()


@check("brush：矩形刷选 selected 非空 + selected 信号")
def _():
    chart = make_chart()
    chart.set_option({
        "tooltip": {"show": False},
        "xAxis": {"type": "category", "data": ["一", "二", "三", "四", "五"]},
        "yAxis": {"type": "value"},
        "series": [
            {"type": "bar", "name": "柱", "data": [8, 14, 10, 18, 13]},
            {"type": "line", "name": "线", "data": [12, 20, 15, 28, 22]},
        ],
        "brush": {"outOfBrush": {"opacity": 0.4}},
    })
    chart.anim.set_progress(1.0)
    img = grab_image(chart)
    br = find_comp(chart, BrushComponent)
    assert_true(br is not None, "brush 组件")
    got = []
    br.selected.connect(got.append)
    plot = chart.primary_coord().plot
    a = plot.topLeft() + QPointF(4, 4)
    b = plot.center()
    mouse_press(chart, a)
    mouse_move(chart, b)
    grab_image(chart)  # 拖拽中的选框绘制
    mouse_release(chart, b)
    grab_image(chart)
    assert_true(len(br.selected_items) > 0, "刷选结果为空")
    assert_eq(len(got), 1, "selected 信号次数")
    assert_true(len(got[0]) == len(br.selected_items), "信号载荷")
    kinds = {item["series"] for item in br.selected_items}
    assert_true("线" in kinds or "柱" in kinds, f"刷选系列 {kinds}")
    img = grab_image(chart)
    img.save(str(SHOTS / "chartcomp_brush_light.png"))
    chart.deleteLater()


@check("visualMap：map_color 两端 = 色带端点 + 出图")
def _():
    chart = make_chart()
    chart.set_option({
        "xAxis": {"type": "category", "data": ["A", "B"]},
        "yAxis": {"type": "value"},
        "series": [{"type": "line", "name": "L", "data": [1, 2]}],
        "visualMap": {"min": 0, "max": 100,
                      "inRange": {"colors": ["#EBEFF5", "#3F5E8C"]},
                      "orient": "vertical"},
    })
    chart.anim.set_progress(1.0)
    img = grab_image(chart)
    vm = find_comp(chart, VisualMapComponent)
    assert_true(vm is not None, "visualMap 组件")
    assert_true(color_close(vm.map_color(0), "#EBEFF5", 2), "min 端颜色")
    assert_true(color_close(vm.map_color(100), "#3F5E8C", 2), "max 端颜色")
    mid = vm.map_color(50)
    lo, hi = QColor("#EBEFF5"), QColor("#3F5E8C")
    assert_true(hi.red() <= mid.red() <= lo.red(), "中间值颜色不在色带内")
    # 渐变条非空：条内像素含端点色
    bar = vm._bar
    assert_true(not bar.isNull(), "渐变条几何")
    px = img.pixelColor(int(bar.center().x()), int(bar.top() + 2))
    assert_true(color_close(px, "#3F5E8C", 40), "渐变条顶端颜色")
    img.save(str(SHOTS / "chartcomp_visualmap_light.png"))
    chart.deleteLater()


@check("timeline：切帧更新 option + 播放按钮切换")
def _():
    chart = make_chart()
    chart.set_option({
        "tooltip": {"show": False},
        "xAxis": {"type": "category", "data": ["一", "二"]},
        "yAxis": {"type": "value"},
        "series": [{"type": "line", "name": "A", "data": [1, 2]}],
        "timeline": {"data": ["2024", "2025", "2026"], "autoPlay": False},
        "options": [
            {"series": [{"data": [1, 2]}]},
            {"series": [{"data": [5, 6]}]},
            {"series": [{"data": [9, 4]}]},
        ],
    })
    chart.anim.set_progress(1.0)
    img = grab_image(chart)
    tl = find_comp(chart, ChartTimeline)
    assert_true(tl is not None, "timeline 组件")
    assert_eq(len(tl._node_pts), 3, "timeline 节点数")
    tl.goto(1)
    chart.anim.set_progress(1.0)
    grab_image(chart)
    assert_eq(chart.option()["series"][0]["data"], [5, 6], "切帧后数据")
    assert_eq(getattr(chart, "_timeline_index", None), 1, "帧下标状态")
    # 重建后的新 timeline 保持下标
    tl2 = find_comp(chart, ChartTimeline)
    assert_true(tl2 is not None and tl2.current == 1, "重建后帧下标")
    # 点击第三个节点
    pt = tl2._node_pts[2]
    mouse_press(chart, pt)
    chart.anim.set_progress(1.0)
    grab_image(chart)
    assert_eq(chart.option()["series"][0]["data"], [9, 4], "点击节点切帧")
    # 播放按钮切换
    tl3 = find_comp(chart, ChartTimeline)
    assert_true(not tl3.playing, "初始应暂停")
    mouse_press(chart, tl3._play_rect.center())
    tl4 = find_comp(chart, ChartTimeline)
    assert_true(getattr(chart, "_timeline_playing", False), "播放状态未置位")
    mouse_press(chart, tl4._play_rect.center())
    assert_true(not getattr(chart, "_timeline_playing", True), "暂停状态未置位")
    img = grab_image(chart)
    img.save(str(SHOTS / "chartcomp_timeline_light.png"))
    chart.deleteLater()


@check("toolbox：点击命中回调 + dataZoom 开关 + saveAsImage 降级")
def _():
    chart = make_chart()
    chart.set_option(_zoom_option([{"type": "inside", "start": 0, "end": 100}]) | {
        "toolbox": {"feature": ["saveAsImage", "dataZoom", "restore"]},
    })
    chart.anim.set_progress(1.0)
    grab_image(chart)
    tb = find_comp(chart, ToolboxComponent)
    assert_true(tb is not None, "toolbox 组件")
    assert_eq(len(tb._buttons), 3, "toolbox 按钮数")
    got = []
    tb.on_action = got.append
    # dataZoom 开关
    mouse_press(chart, tb.button_rect("dataZoom").center())
    assert_true("dataZoom" in got, "dataZoom 回调")
    assert_true(getattr(chart, "datazoom_enabled", True) is False,
                "dataZoom 开关未关闭")
    mouse_press(chart, tb.button_rect("dataZoom").center())
    assert_true(getattr(chart, "datazoom_enabled", False) is True,
                "dataZoom 开关未重新打开")
    # restore（同时验证 dataZoom restore 被调用）
    dz = find_comp(chart, DataZoomComponent)
    dz.start, dz.end = 10.0, 60.0
    dz.apply()
    mouse_press(chart, tb.button_rect("restore").center())
    grab_image(chart)
    assert_true("restore" in got, "restore 回调")
    assert_true(abs(dz.end - 100) < 1e-6, "restore 未重置 dataZoom")
    # saveAsImage：offscreen 降级写 cwd chart_export.png
    saved_path = None
    try:
        mouse_press(chart, tb.button_rect("saveAsImage").center())
        assert_true("saveAsImage" in got, "saveAsImage 回调")
        saved_path = tb.last_saved
        assert_true(saved_path and os.path.exists(saved_path),
                    f"降级保存未生成文件: {saved_path}")
        assert_true(saved_path.endswith("chart_export.png"), "降级文件名")
    finally:
        if saved_path and os.path.exists(saved_path):
            os.remove(saved_path)
    # 空白处点击不消费
    consumed = tb.on_mouse_press(QPointF(2, chart.height() - 2))
    assert_true(consumed is False, "空白处不应命中")
    chart.deleteLater()


@check("交互综合截图（slider + visualMap + toolbox，亮 / 暗）")
def _():
    opt = _zoom_option([{"type": "slider", "start": 10, "end": 80}]) | {
        "title": {"text": "交互综合"},
        "visualMap": {"min": 0, "max": 15, "orient": "vertical"},
        "toolbox": {"feature": ["saveAsImage", "dataZoom", "restore"]},
    }
    chart = make_chart()
    chart.set_option(opt)
    chart.anim.set_progress(1.0)
    img = grab_image(chart)
    assert_not_blank(img, "interact")
    img.save(str(SHOTS / "chartcomp_interact_light.png"))
    mgr = ThemeManager.instance()
    mgr.set_mode("dark")
    img = grab_image(chart)
    assert_not_blank(img, "interact dark")
    img.save(str(SHOTS / "chartcomp_interact_dark.png"))
    mgr.set_mode("light")
    chart.deleteLater()


@check("空 option / 组件空数据不崩溃")
def _():
    chart = make_chart()
    chart.set_option({
        "series": [{"type": "line", "name": "E", "data": [],
                    "markPoint": {"data": []}, "markLine": {"data": []},
                    "markArea": {"data": []}}],
        "graphic": [],
        "dataZoom": [{"type": "slider"}],
        "visualMap": {},
        "timeline": {"data": []},
        "toolbox": {},
        "brush": {},
    })
    chart.anim.set_progress(1.0)
    grab_image(chart)
    chart.set_option({})
    chart.anim.set_progress(1.0)
    grab_image(chart)
    chart.deleteLater()


print()
if _FAILURES:
    print(f"失败 {len(_FAILURES)} 项: {_FAILURES}")
    sys.exit(1)
print("全部通过")
sys.exit(0)
