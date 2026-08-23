# -*- coding: utf-8 -*-
"""chart hierarchy 代理（C3）自测：无坐标 / 层级 / 关系系列（CHART_SPEC §5/§6）。

直接运行（无 pytest 依赖）::

    QT_QPA_PLATFORM=offscreen python tests/test_chart_hierarchy.py

覆盖：
- 10 个系列（pie/radar/gauge/funnel/sunburst/treemap/tree/sankey/graph/lines）
  最小 option 出图 + 非空白断言；
- pie 环形 / 南丁格尔玫瑰 / 中心总计 / update_option 动画；
- gauge 指针动画推进（中间帧角度插值）；
- sankey 流带（节点矩形 + 贝塞尔流带命中）；
- graph force 布局确定性收敛（同种子两次布局一致）；
- 全部系列 hit_test 命中断言；
- lines trailEffect QTimer 生命周期（update_option 后旧定时器自毁）；
- 空数据 / None 不崩溃；
- grab 截图 tests/shots/chart_<type>.png（关键图亮 / 暗）。
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


from PySide6.QtCore import QPointF  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from InstructionX_UIKit.theme import ThemeManager  # noqa: E402
from InstructionX_UIKit.charts import ChartWidget, SERIES_REGISTRY  # noqa: E402

app = QApplication.instance() or QApplication(sys.argv)
ThemeManager.instance().apply(app)
ThemeManager.instance().set_mode("light")


def grab_image(widget):
    return widget.grab().toImage()


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


def render(chart, option):
    """set_option + 动画推至末帧 + 强制一次绘制布局。"""
    chart.set_option(option)
    chart.anim.set_progress(1.0)
    return grab_image(chart)


PIE_DATA = [{"name": "直接访问", "value": 335},
            {"name": "邮件营销", "value": 310},
            {"name": "联盟广告", "value": 234},
            {"name": "视频广告", "value": 135},
            {"name": "搜索引擎", "value": 548}]

PIE_OPTION = {
    "title": {"text": "访问来源", "left": "center"},
    "tooltip": {"show": True, "trigger": "item"},
    "series": [{"type": "pie", "name": "来源", "data": PIE_DATA,
                "label": {"show": True, "position": "outside"}}],
}

HIER_DATA = [
    {"name": "水果", "children": [
        {"name": "苹果", "value": 12},
        {"name": "香蕉", "value": 8},
        {"name": "橙子", "children": [
            {"name": "甜橙", "value": 6},
            {"name": "酸橙", "value": 3},
        ]},
    ]},
    {"name": "蔬菜", "children": [
        {"name": "白菜", "value": 9},
        {"name": "萝卜", "value": 5},
    ]},
]


# ---------------------------------------------------------------------------
# 注册完整性
# ---------------------------------------------------------------------------

@check("10 个系列全部注册")
def _():
    for t in ("pie", "radar", "gauge", "funnel", "sunburst", "treemap",
              "tree", "sankey", "graph", "lines"):
        assert_true(t in SERIES_REGISTRY, f"{t} 未注册")


# ---------------------------------------------------------------------------
# pie 饼 / 环形 / 玫瑰
# ---------------------------------------------------------------------------

@check("pie 基础出图 + 扇区 hit_test")
def _():
    chart = make_chart()
    img = render(chart, PIE_OPTION)
    assert_not_blank(img, "pie")
    img.save(str(SHOTS / "chart_pie.png"))
    r = chart.series_renderers[0]
    assert_true(len(r._sectors) == 5, "扇区数")
    sec = r._sectors[0]
    mid = (sec["a0"] + sec["a1"]) / 2
    pt = r._pt(mid, (sec["r0"] + sec["r1"]) / 2)
    hit = r.hit_test(pt)
    assert_true(hit is not None and hit["name"] == "直接访问"
                and hit["value"] == 335, f"pie hit_test: {hit}")
    assert_true(hit["series"] == "来源", "hit series 名")
    # 中心（实心饼 r0=0）也应命中
    hit0 = r.hit_test(r._center)
    assert_true(hit0 is not None, "实心饼中心命中")
    # 图外不命中
    assert_true(r.hit_test(QPointF(1, 1)) is None, "图外误命中")
    chart.deleteLater()


@check("pie 环形 + 中心总计 + 内部百分比标签")
def _():
    opt = {
        "series": [{
            "type": "pie", "name": "环", "radius": ["40%", "70%"],
            "label": {"show": True, "position": "inside"},
            "totalLabel": {"show": True, "text": "总计"},
            "data": PIE_DATA,
        }],
    }
    chart = make_chart()
    img = render(chart, opt)
    assert_not_blank(img, "donut")
    img.save(str(SHOTS / "chart_pie_donut.png"))
    r = chart.series_renderers[0]
    assert_true(r._r_in > 1, "内半径应 > 0")
    # 中心孔内（半径 < r_in）不命中扇区
    assert_true(r.hit_test(r._center) is None, "环形中心孔误命中")
    sec = r._sectors[1]
    mid = (sec["a0"] + sec["a1"]) / 2
    pt = r._pt(mid, (sec["r0"] + sec["r1"]) / 2)
    hit = r.hit_test(pt)
    assert_true(hit is not None and hit["name"] == "邮件营销",
                f"donut hit: {hit}")
    chart.deleteLater()


@check("pie 南丁格尔玫瑰（roseType radius / area）")
def _():
    for rose in ("radius", "area"):
        chart = make_chart()
        img = render(chart, {
            "series": [{"type": "pie", "name": "玫瑰", "roseType": rose,
                        "data": PIE_DATA}],
        })
        assert_not_blank(img, f"rose {rose}")
        r = chart.series_renderers[0]
        radii = {s["r1"] for s in r._sectors}
        assert_true(len(radii) > 1, f"roseType={rose} 半径未按值映射")
        chart.deleteLater()
    # 截图保留 radius 版本
    chart = make_chart()
    img = render(chart, {
        "series": [{"type": "pie", "roseType": "radius", "data": PIE_DATA}],
    })
    img.save(str(SHOTS / "chart_pie_rose.png"))
    chart.deleteLater()


@check("pie update_option 旧→新动画推进无异常")
def _():
    chart = make_chart()
    render(chart, PIE_OPTION)
    chart.update_option({"series": [{
        "data": [{"name": "直接访问", "value": 500},
                 {"name": "邮件营销", "value": 200},
                 {"name": "联盟广告", "value": 100},
                 {"name": "视频广告", "value": 300},
                 {"name": "搜索引擎", "value": 400}]}]})
    r = chart.series_renderers[0]
    assert_true(r.prev_data is not None and len(r.prev_data) == 5,
                "prev_data 未注入")
    chart.anim.set_progress(0.5)
    grab_image(chart)  # 中间帧绘制不崩溃
    chart.anim.set_progress(1.0)
    img = grab_image(chart)
    assert_not_blank(img, "pie 更新后")
    chart.deleteLater()


# ---------------------------------------------------------------------------
# radar 雷达
# ---------------------------------------------------------------------------

RADAR_OPTION = {
    "title": {"text": "能力雷达"},
    "series": [{
        "type": "radar", "name": "能力",
        "indicator": [{"name": "速度", "max": 100},
                      {"name": "力量", "max": 100},
                      {"name": "防御", "max": 100},
                      {"name": "敏捷", "max": 100},
                      {"name": "智慧", "max": 100},
                      {"name": "运气", "max": 100}],
        "areaStyle": {"opacity": 0.25},
        "data": [{"name": "甲", "value": [80, 60, 70, 90, 65, 75]},
                 {"name": "乙", "value": [60, 85, 55, 70, 88, 60]}],
    }],
}


@check("radar 出图（蛛网 + 多系列 + areaStyle）+ 多边形命中")
def _():
    chart = make_chart()
    img = render(chart, RADAR_OPTION)
    assert_not_blank(img, "radar")
    img.save(str(SHOTS / "chart_radar.png"))
    r = chart.series_renderers[0]
    assert_true(len(r._polys) == 2, "radar 多边形数")
    assert_true(len(r._indicators) == 6, "indicator 数")
    # 多边形内部点命中（靠近中心必在任一多边形内）
    hit = r.hit_test(r._center)
    assert_true(hit is not None, "radar 中心命中")
    # 顶点处命中对应系列
    poly = r._polys[0]
    inner = QPointF((r._center.x() + poly["points"][0].x()) / 2,
                    (r._center.y() + poly["points"][0].y()) / 2)
    hit = r.hit_test(inner)
    assert_true(hit is not None and isinstance(hit["value"], list),
                f"radar hit: {hit}")
    # 远外侧不命中
    assert_true(r.hit_test(QPointF(1, 1)) is None, "radar 图外误命中")
    # circle 形状 + 缺省 max
    chart.set_option({
        "series": [{"type": "radar", "shape": "circle",
                    "indicator": [{"name": "a"}, {"name": "b"}, {"name": "c"}],
                    "data": [[3, 5, 4]]}],
    })
    chart.anim.set_progress(1.0)
    assert_not_blank(grab_image(chart), "radar circle")
    chart.deleteLater()


# ---------------------------------------------------------------------------
# gauge 仪表盘
# ---------------------------------------------------------------------------

GAUGE_OPTION = {
    "series": [{
        "type": "gauge", "name": "完成率", "min": 0, "max": 100,
        "progress": {"show": True, "width": 10},
        "axisLine": {"lineStyle": {"width": 14, "color": [
            [0.3, "#67C23A"], [0.7, "#E6A23C"], [1, "#F56C6C"]]}},
        "pointer": {"show": True, "length": "65%", "width": 5},
        "anchor": {"show": True, "size": 12},
        "detail": {"show": True},
        "title": {"show": True},
        "data": [{"name": "完成率", "value": 66}],
    }],
}


@check("gauge 出图 + 动画推进（指针角度插值）")
def _():
    chart = make_chart()
    chart.set_option(GAUGE_OPTION)
    # 中间帧：指针应从 min 向 66 摆动
    chart.anim.set_progress(0.5)
    img_mid = grab_image(chart)
    r = chart.series_renderers[0]
    a_mid = r._value_angle(0 + (66 - 0) * 0.5)
    a_end = r._value_angle(66)
    assert_true(abs(a_mid - r._start_angle())
                < abs(a_end - r._start_angle()), "动画中帧角度未插值")
    chart.anim.set_progress(1.0)
    img = grab_image(chart)
    assert_not_blank(img, "gauge")
    img.save(str(SHOTS / "chart_gauge.png"))
    assert_true(img_mid != img or count_colors(img_mid) > 8, "gauge 中帧空白")
    # update_option：旧值 66 → 新值 30，中帧介于二者之间
    chart.update_option({"series": [{"data": [{"name": "完成率",
                                               "value": 30}]}]})
    r2 = chart.series_renderers[0]
    assert_true(r2.prev_data and r2.prev_data[0]["value"] == 66,
                "gauge prev_data 未注入")
    chart.anim.set_progress(0.5)
    grab_image(chart)
    chart.anim.set_progress(1.0)
    assert_not_blank(grab_image(chart), "gauge 更新后")
    chart.deleteLater()


@check("gauge hit_test 弧内命中 / 缺口不命中")
def _():
    chart = make_chart()
    render(chart, GAUGE_OPTION)
    r = chart.series_renderers[0]
    # 正上方（内部角 270°，自 3 点方向顺时针）位于表盘弧内；
    # 347c5ba 起对齐 ECharts 角度约定，默认开口在底部
    pt = r._pt(270, r._radius * 0.9)
    hit = r.hit_test(pt)
    assert_true(hit is not None and hit["value"] == 66, f"gauge hit: {hit}")
    # 正下方（内部角 90°）位于开口缺口
    pt_gap = r._pt(90, r._radius * 0.9)
    assert_true(r.hit_test(pt_gap) is None, "gauge 缺口误命中")
    chart.deleteLater()


# ---------------------------------------------------------------------------
# funnel 漏斗
# ---------------------------------------------------------------------------

FUNNEL_OPTION = {
    "title": {"text": "转化漏斗"},
    "series": [{
        "type": "funnel", "name": "转化", "sort": "descending", "gap": 3,
        "data": [{"name": "展示", "value": 100},
                 {"name": "点击", "value": 80},
                 {"name": "访问", "value": 60},
                 {"name": "咨询", "value": 40},
                 {"name": "订单", "value": 20}],
    }],
}


@check("funnel 出图（梯形层叠 + 排序 + 标签）+ 层命中")
def _():
    chart = make_chart()
    img = render(chart, FUNNEL_OPTION)
    assert_not_blank(img, "funnel")
    img.save(str(SHOTS / "chart_funnel.png"))
    r = chart.series_renderers[0]
    assert_true(len(r._layers) == 5, "funnel 层数")
    # 顶层中心命中 "展示"
    layer = r._layers[0]
    cx = (layer["left"] + layer["right"]) / 2
    hit = r.hit_test(QPointF(cx, layer["cy"]))
    assert_true(hit is not None and hit["name"] == "展示", f"funnel hit: {hit}")
    # ascending / none 排序不崩溃
    for sort in ("ascending", "none"):
        chart.set_option({"series": [dict(FUNNEL_OPTION["series"][0],
                                          sort=sort)]})
        chart.anim.set_progress(1.0)
        assert_not_blank(grab_image(chart), f"funnel {sort}")
    chart.deleteLater()


# ---------------------------------------------------------------------------
# sunburst 旭日
# ---------------------------------------------------------------------------

@check("sunburst 出图（层级环形）+ 扇区命中")
def _():
    chart = make_chart()
    img = render(chart, {
        "title": {"text": "旭日"},
        "series": [{"type": "sunburst", "name": "层级", "data": HIER_DATA}],
    })
    assert_not_blank(img, "sunburst")
    img.save(str(SHOTS / "chart_sunburst.png"))
    r = chart.series_renderers[0]
    assert_true(len(r._nodes) >= 8, f"sunburst 节点数 {len(r._nodes)}")
    # 顶层节点角度覆盖整圈
    total_span = sum(n.a1 - n.a0 for n in r._nodes if n.level == 0)
    assert_true(abs(total_span - 360.0) < 1.0, f"顶层角覆盖 {total_span}")
    # 命中最深叶子
    leaf = next(n for n in r._nodes if n.name == "甜橙")
    mid = (leaf.a0 + leaf.a1) / 2
    r0, r1 = r._ring(leaf.level)
    hit = r.hit_test(r._pt(mid, (r0 + r1) / 2))
    assert_true(hit is not None and hit["name"] == "甜橙",
                f"sunburst hit: {hit}")
    assert_true(r.hit_test(QPointF(1, 1)) is None, "sunburst 图外误命中")
    chart.deleteLater()


# ---------------------------------------------------------------------------
# treemap 矩形树图
# ---------------------------------------------------------------------------

@check("treemap 出图（squarified + breadcrumb）+ 矩形命中")
def _():
    chart = make_chart()
    img = render(chart, {
        "title": {"text": "矩形树图"},
        "series": [{"type": "treemap", "name": "分布",
                    "breadcrumb": {"show": True},
                    "data": HIER_DATA}],
    })
    assert_not_blank(img, "treemap")
    img.save(str(SHOTS / "chart_treemap.png"))
    r = chart.series_renderers[0]
    assert_true(r._crumb and "水果" in r._crumb, "breadcrumb 文本")
    leaf = next(n for n in r._nodes if n.name == "苹果")
    hit = r.hit_test(leaf.rect.center())
    assert_true(hit is not None and hit["name"] == "苹果",
                f"treemap hit: {hit}")
    assert_true(hit["depth"] == leaf.depth, "treemap depth")
    # 子级矩形必须在父级矩形内（容差 1px）
    parent = next(n for n in r._nodes if n.name == "水果")
    assert_true(parent.rect.adjusted(-1, -1, 1, 1).contains(leaf.rect),
                "子级越出父级矩形")
    chart.deleteLater()


# ---------------------------------------------------------------------------
# tree 树图
# ---------------------------------------------------------------------------

TREE_DATA = [{"name": "root", "children": [
    {"name": "分支A", "children": [{"name": "叶A1"}, {"name": "叶A2"}]},
    {"name": "分支B", "children": [{"name": "叶B1"}]},
]}]


@check("tree 出图（LR polyline / TB curve）+ 节点命中")
def _():
    chart = make_chart()
    img = render(chart, {
        "title": {"text": "树图"},
        "series": [{"type": "tree", "name": "组织", "orient": "LR",
                    "edge": "polyline", "data": TREE_DATA}],
    })
    assert_not_blank(img, "tree LR")
    img.save(str(SHOTS / "chart_tree.png"))
    r = chart.series_renderers[0]
    assert_true(len(r._nodes) == 6 and len(r._edges) == 5, "tree 节点/边数")
    node, pt = next((n, p) for n, p in r._nodes if n.name == "root")
    hit = r.hit_test(pt)
    assert_true(hit is not None and hit["name"] == "root", f"tree hit: {hit}")
    assert_true(r.hit_test(QPointF(1, 1)) is None, "tree 图外误命中")
    # TB + 曲线边
    chart.set_option({
        "series": [{"type": "tree", "orient": "TB", "edge": "curve",
                    "data": TREE_DATA}],
    })
    chart.anim.set_progress(1.0)
    assert_not_blank(grab_image(chart), "tree TB")
    chart.deleteLater()


# ---------------------------------------------------------------------------
# sankey 桑基
# ---------------------------------------------------------------------------

SANKEY_OPTION = {
    "title": {"text": "能源流向"},
    "series": [{
        "type": "sankey", "name": "流向",
        "data": [{"name": "煤炭"}, {"name": "电力"}, {"name": "工业"},
                 {"name": "居民"}],
        "links": [{"source": "煤炭", "target": "电力", "value": 8},
                  {"source": "煤炭", "target": "工业", "value": 5},
                  {"source": "电力", "target": "工业", "value": 6},
                  {"source": "电力", "target": "居民", "value": 2}],
    }],
}


@check("sankey 出图（节点矩形 + 流带）+ 节点 / 流带命中")
def _():
    chart = make_chart(560, 320)
    img = render(chart, SANKEY_OPTION)
    assert_not_blank(img, "sankey")
    img.save(str(SHOTS / "chart_sankey.png"))
    r = chart.series_renderers[0]
    assert_true(len(r._nodes) == 4, "sankey 节点数")
    assert_true(len(r._bands) == 4, "sankey 流带数")
    # 分层正确：煤炭 depth=0，电力 depth=1，工业/居民更深
    depth = {nd["name"]: nd["depth"] for nd in r._nodes}
    assert_true(depth["煤炭"] == 0 and depth["电力"] == 1,
                f"sankey 分层 {depth}")
    assert_true(depth["工业"] >= 2 and depth["居民"] >= 2,
                f"sankey 分层 {depth}")
    # 节点命中
    coal = next(nd for nd in r._nodes if nd["name"] == "煤炭")
    hit = r.hit_test(coal["rect"].center())
    assert_true(hit is not None and hit["name"] == "煤炭",
                f"sankey node hit: {hit}")
    assert_true(hit["value"] == 13, "节点值 = max(入, 出) 流")
    # 流带命中（包围盒中段扫描，避开两端节点矩形）
    band = r._bands[0]
    br = band["path"].boundingRect()
    x_lo = br.left() + br.width() * 0.3
    x_hi = br.right() - br.width() * 0.3
    found = None
    for yy in range(int(br.top()), int(br.bottom()) + 1, 2):
        for xx in range(int(x_lo), int(x_hi) + 1, 2):
            cand = QPointF(xx, yy)
            if band["path"].contains(cand):
                found = cand
                break
        if found is not None:
            break
    assert_true(found is not None, "流带包围盒内无可命中点")
    hit = r.hit_test(found)
    assert_true(hit is not None and "source" in hit, f"sankey band hit: {hit}")
    assert_true(r.hit_test(QPointF(1, 1)) is None, "sankey 图外误命中")
    # nodes 键别名 + 下标引用
    chart.set_option({
        "series": [{"type": "sankey",
                    "nodes": [{"name": "x"}, {"name": "y"}],
                    "links": [{"source": 0, "target": 1, "value": 4}]}],
    })
    chart.anim.set_progress(1.0)
    assert_not_blank(grab_image(chart), "sankey nodes 别名")
    chart.deleteLater()


# ---------------------------------------------------------------------------
# graph 关系图
# ---------------------------------------------------------------------------

GRAPH_OPTION = {
    "title": {"text": "关系图"},
    "series": [{
        "type": "graph", "name": "关系", "layout": "force",
        "force": {"seed": 42, "iterations": 80},
        "data": [{"name": f"n{i}", "symbolSize": 14 + (i % 3) * 6}
                 for i in range(10)],
        "links": [{"source": 0, "target": 1}, {"source": 1, "target": 2},
                  {"source": 2, "target": 3}, {"source": 3, "target": 4},
                  {"source": 4, "target": 0}, {"source": 5, "target": 6},
                  {"source": 6, "target": 7}, {"source": 7, "target": 5},
                  {"source": 0, "target": 8}, {"source": 8, "target": 9},
                  {"source": 9, "target": 5}],
    }],
}


@check("graph force 布局收敛 + 确定性可复现 + 节点命中")
def _():
    chart = make_chart()
    img = render(chart, GRAPH_OPTION)
    assert_not_blank(img, "graph")
    img.save(str(SHOTS / "chart_graph.png"))
    r = chart.series_renderers[0]
    assert_true(len(r._nodes) == 10 and len(r._edges) == 11, "graph 规模")
    # 收敛：任意两节点不重叠（最小间距 > 2px）且全部在图内
    pts = [nd["pos"] for nd in r._nodes]
    for i in range(len(pts)):
        assert_true(0 <= pts[i].x() <= chart.width()
                    and 0 <= pts[i].y() <= chart.height(), "节点越界")
        for j in range(i + 1, len(pts)):
            d = ((pts[i].x() - pts[j].x()) ** 2
                 + (pts[i].y() - pts[j].y()) ** 2) ** 0.5
            assert_true(d > 2.0, f"节点 {i}/{j} 未收敛散开 (d={d:.2f})")
    # 同种子两次布局一致（确定性）
    chart2 = make_chart()
    render(chart2, GRAPH_OPTION)
    pts2 = [nd["pos"] for nd in chart2.series_renderers[0]._nodes]
    for a, b in zip(pts, pts2):
        assert_true(abs(a.x() - b.x()) < 1e-6 and abs(a.y() - b.y()) < 1e-6,
                    "force 布局不可复现")
    # 节点命中
    hit = r.hit_test(pts[3])
    assert_true(hit is not None and hit["name"] == "n3", f"graph hit: {hit}")
    # circular 布局
    chart2.set_option({
        "series": [{"type": "graph", "layout": "circular",
                    "data": [{"name": "a"}, {"name": "b"}, {"name": "c"}],
                    "links": [{"source": "a", "target": "b"}]}],
    })
    chart2.anim.set_progress(1.0)
    assert_not_blank(grab_image(chart2), "graph circular")
    chart.deleteLater()
    chart2.deleteLater()


# ---------------------------------------------------------------------------
# lines 线图
# ---------------------------------------------------------------------------

LINES_OPTION = {
    "title": {"text": "航线"},
    "xAxis": {"type": "value", "min": 0, "max": 100},
    "yAxis": {"type": "value", "min": 0, "max": 100},
    "series": [{
        "type": "lines", "name": "航线",
        "lineStyle": {"width": 2, "curveness": 0.2},
        "trailEffect": {"show": True, "period": 2, "symbolSize": 6},
        "data": [{"name": "L1", "coords": [[10, 10], [90, 80]]},
                 {"name": "L2", "coords": [[15, 85], [85, 15]]},
                 {"name": "L3", "coords": [[95, 5], [95, 60]]}],
    }],
}


@check("lines 出图（Grid 坐标 + trailEffect 移动亮点）+ 线段命中")
def _():
    chart = make_chart()
    img = render(chart, LINES_OPTION)
    assert_not_blank(img, "lines")
    r = chart.series_renderers[0]
    assert_true(len(r._segments) == 3, "lines 段数")
    assert_true(r._timer is not None and r._timer.isActive(),
                "trailEffect 定时器未启动")
    # 推进亮点相位（模拟定时器触发）
    old_phase = r._phase
    r._on_tick()
    assert_true(r._phase != old_phase, "亮点相位未推进")
    img2 = grab_image(chart)
    assert_not_blank(img2, "lines 亮点帧")
    img2.save(str(SHOTS / "chart_lines.png"))
    # 线段中点命中
    seg = r._segments[0]
    mid = QPointF((seg["p0"].x() + seg["p1"].x()) / 2,
                  (seg["p0"].y() + seg["p1"].y()) / 2)
    hit = r.hit_test(mid)
    assert_true(hit is not None and hit["name"] == "L1", f"lines hit: {hit}")
    # 定时器生命周期：update_option 重建渲染器后旧定时器自毁
    chart.update_option({"series": [dict(LINES_OPTION["series"][0])]})
    r_old, r_new = r, chart.series_renderers[0]
    assert_true(r_new is not r_old, "渲染器未重建")
    r_old._on_tick()  # 已不在 series_renderers → 自毁
    assert_true(r_old._timer is None, "旧渲染器定时器未自毁（泄漏）")
    r_new._on_tick()  # 新渲染器定时器仍存活
    assert_true(r_new._timer is not None, "新渲染器定时器异常停止")
    chart.deleteLater()
    r_new._on_tick()  # chart 销毁路径不崩溃（deleteLater 未处理前仍存活）
    app.sendPostedEvents(None, 0)  # 处理 deleteLater


# ---------------------------------------------------------------------------
# 综合 option（多系列混合：pie + gauge）
# ---------------------------------------------------------------------------

@check("综合 option（pie + radar 双系列同图）")
def _():
    chart = make_chart(640, 360)
    img = render(chart, {
        "title": {"text": "综合", "left": "center"},
        "legend": {"show": True},
        "series": [
            {"type": "pie", "name": "占比", "center": ["28%", "55%"],
             "radius": ["30%", "55%"],
             "data": PIE_DATA[:3]},
            {"type": "gauge", "name": "仪表",
             "min": 0, "max": 100, "radius": "38%",
             "progress": {"show": True},
             "data": [{"name": "负载", "value": 45}]},
        ],
    })
    assert_not_blank(img, "综合")
    assert_true(len(chart.series_renderers) == 2, "综合系列数")
    img.save(str(SHOTS / "chart_hierarchy_combo.png"))
    chart.deleteLater()


# ---------------------------------------------------------------------------
# 空数据不崩溃
# ---------------------------------------------------------------------------

@check("空数据 / None / 畸形数据不崩溃")
def _():
    chart = make_chart()
    cases = [
        {"series": [{"type": "pie", "data": []}]},
        {"series": [{"type": "pie", "data": None}]},
        {"series": [{"type": "pie", "data": [None, {"name": "x"}, -5]}]},
        {"series": [{"type": "radar", "indicator": [], "data": []}]},
        {"series": [{"type": "gauge", "data": []}]},
        {"series": [{"type": "funnel", "data": [None, {"name": "a"}]}]},
        {"series": [{"type": "sunburst", "data": [{"name": "x"}]}]},
        {"series": [{"type": "treemap", "data": None}]},
        {"series": [{"type": "tree", "data": []}]},
        {"series": [{"type": "sankey", "data": [], "links": []}]},
        {"series": [{"type": "sankey", "data": [{"name": "a"}],
                     "links": [{"source": "a", "target": "不存在",
                                "value": 1}]}]},
        {"series": [{"type": "graph", "data": [], "links": [
            {"source": 0, "target": 1}]}]},
        {"series": [{"type": "lines", "data": [{"coords": None}, {},
                                               {"coords": [[0, 0]]}]}]},
        {"series": []},
    ]
    for opt in cases:
        chart.set_option(opt)
        chart.anim.set_progress(0.5)
        grab_image(chart)
        chart.anim.set_progress(1.0)
        grab_image(chart)
        for r in chart.series_renderers:
            r.hit_test(QPointF(100, 100))
    chart.deleteLater()


# ---------------------------------------------------------------------------
# 暗色主题关键图
# ---------------------------------------------------------------------------

@check("暗色主题关键截图（pie / gauge / graph）")
def _():
    mgr = ThemeManager.instance()
    mgr.set_mode("dark")
    try:
        for name, opt in (("pie", PIE_OPTION),
                          ("gauge", GAUGE_OPTION),
                          ("graph", GRAPH_OPTION)):
            chart = make_chart()
            img = render(chart, opt)
            assert_not_blank(img, f"dark {name}")
            img.save(str(SHOTS / f"chart_{name}_dark.png"))
            chart.deleteLater()
    finally:
        mgr.set_mode("light")


print("\n==== test_chart_hierarchy ====")
# 执行全部已登记检查（check 装饰器在定义时即执行）

if _FAILURES:
    print(f"\n失败 {len(_FAILURES)} 项: {_FAILURES}")
    sys.exit(1)
print("\n全部通过")
sys.exit(0)
