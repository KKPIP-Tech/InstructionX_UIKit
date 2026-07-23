# -*- coding: utf-8 -*-
"""B1 蓝图组件库自测（BP_SPEC §8）。

直接运行（无 pytest 依赖）::

    QT_QPA_PLATFORM=offscreen python tests/test_blueprint.py

覆盖：
- 图模型增删改查；
- 边校验矩阵（类型不兼容拒绝 / any 通配 / 方向 / 自连 / 重复 / 单连接替换）；
- 图与画布序列化往返相等；
- 注册表：注册 / 搜索 / 分类 / create / body_builder 注入 / 引脚类型注册；
- 画布：add_node_at 位置、程序建边边部件几何、模拟引脚拖拽建边、
  橡皮筋框选、Delete 删除连带边、fit_view、缩放夹取、center_on；
- execution：start→running、finish→done + 耗时徽标像素断言、fail→error、
  reset 还原、路径高亮 flowing；
- NodeCreationMenu 搜索过滤与分类、兼容过滤；NodeContextMenu 动作信号；
- 亮 / 暗截图 tests/shots/blueprint_*.png（含多节点连线综合图）。
"""

import json
import os
import sys
import traceback
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

SHOTS = ROOT / "tests" / "shots"

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
        raise AssertionError(f"断言失败 {msg}")


def assert_eq(actual, expected, msg=""):
    if actual != expected:
        raise AssertionError(f"{msg} 期望 {expected!r}，实际 {actual!r}")


# ---------------------------------------------------------------------------
# 应用与公共装置
# ---------------------------------------------------------------------------

from PySide6.QtWidgets import QApplication, QLabel  # noqa: E402
from PySide6.QtCore import QPoint, QPointF, Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402

app = QApplication.instance() or QApplication([])

from InstructionX_UIKit.theme import ThemeManager, T  # noqa: E402

ThemeManager.instance().apply(app)

from InstructionX_UIKit.blueprint import (  # noqa: E402
    PIN_COLORS,
    BlueprintCanvas,
    BlueprintGraph,
    BlueprintNode,
    NodeContextMenu,
    NodeCreationMenu,
    NodeRegistry,
    NodeSpec,
    PinDirection,
    format_elapsed,
    pin_color,
    register_node_type,
    register_pin_type,
    types_compatible,
)


def _build_resize_body(node, container):
    """测试用自定义节点体：注入一个带 objectName 的 QLabel。"""
    label = QLabel(f"宽度: {node.properties.get('width', 512)}")
    label.setObjectName("resizeBodyLabel")
    container.layout().addWidget(label)


def register_test_types():
    """注册测试节点类型（重复调用安全：同 type_name 覆盖）。"""
    register_node_type(
        "load_image", "加载图像", "输入",
        outputs=[{"id": "img", "name": "图像", "data_type": "image"}],
        accent="primary", description="从磁盘加载图像",
    )
    register_node_type(
        "resize", "Resize", "处理",
        inputs=[{"id": "in", "name": "进入", "data_type": "exec"},
                {"id": "img", "name": "图像", "data_type": "image"}],
        outputs=[{"id": "out", "name": "退出", "data_type": "exec"},
                 {"id": "img", "name": "图像", "data_type": "image"}],
        accent="warning", body_builder=_build_resize_body,
        description="调整图像尺寸",
    )
    register_node_type(
        "infer", "模型推理", "模型",
        inputs=[{"id": "in", "name": "进入", "data_type": "exec"},
                {"id": "img", "name": "图像", "data_type": "image"}],
        outputs=[{"id": "out", "name": "退出", "data_type": "exec"},
                 {"id": "tensor", "name": "张量", "data_type": "tensor"}],
        accent="danger", description="运行模型推理",
    )
    register_node_type(
        "probe", "性能探针", "工具",
        inputs=[{"id": "any_in", "name": "任意", "data_type": "any", "multi": True}],
        outputs=[{"id": "any_out", "name": "任意", "data_type": "any"}],
        description="多连接 any 输入",
    )


def make_canvas(w=960, h=640):
    graph = BlueprintGraph()
    canvas = BlueprintCanvas(graph)
    canvas.resize(w, h)
    canvas.show()
    app.processEvents()
    return graph, canvas


# ---------------------------------------------------------------------------
# 1. 图模型增删改查
# ---------------------------------------------------------------------------

@check("图模型：节点 / 引脚 / 边增删查")
def _():
    graph = BlueprintGraph()
    a = BlueprintNode("start", "开始")
    a.add_output("out", "开始", "exec")
    b = BlueprintNode("infer", "推理")
    b.add_input("in", "进入", "exec")
    b.add_input("img", "图像", "image")
    b.add_output("tensor", "张量", "tensor")
    graph.add_node(a)
    graph.add_node(b)
    assert_true(graph.node(a.id) is a, "node()")
    assert_true(b.pin("img").data_type == "image", "pin()")
    edge = graph.add_edge(a.id, "out", b.id, "in")
    assert_true(edge is not None, "add_edge 应成功")
    assert_eq(len(graph.edges_of(b.id)), 1, "edges_of")
    seen = {"added": 0, "removed": 0, "enode": None}
    graph.edge_removed.connect(lambda _i: seen.__setitem__("removed", seen["removed"] + 1))
    graph.node_removed.connect(lambda i: seen.__setitem__("enode", i))
    graph.remove_node(b.id)
    assert_eq(seen["removed"], 1, "remove_node 应连带移除边")
    assert_eq(seen["enode"], b.id, "node_removed 信号")
    assert_eq(len(graph.edges()), 0, "边已清空")
    graph.clear()
    assert_eq(len(graph.nodes()), 0, "clear")


# ---------------------------------------------------------------------------
# 2. 边校验矩阵
# ---------------------------------------------------------------------------

@check("边校验矩阵：类型 / 方向 / 自连 / 重复 / 单连接替换 / multi")
def _():
    graph = BlueprintGraph()
    src = BlueprintNode("load_image", "加载")
    src.add_output("img", "图像", "image")
    src.add_output("any_o", "任意", "any")
    exe = BlueprintNode("start", "开始")
    exe.add_output("out", "开始", "exec")
    dst = BlueprintNode("infer", "推理")
    dst.add_input("in", "进入", "exec")
    dst.add_input("img", "图像", "image")
    dst.add_input("tensor", "张量", "tensor")
    dst.add_input("multi_in", "任意多", "any", multi=True)
    dst.add_output("out", "退出", "exec")
    for n in (src, exe, dst):
        graph.add_node(n)

    # 类型不兼容拒绝
    assert_true(graph.add_edge(src.id, "img", dst.id, "tensor") is None,
                "image→tensor 应拒绝")
    assert_true(graph.add_edge(exe.id, "out", dst.id, "img") is None,
                "exec→image 应拒绝")
    # any 通配（双向）
    assert_true(graph.add_edge(src.id, "any_o", dst.id, "img") is not None,
                "any→image 应通过")
    assert_true(graph.add_edge(src.id, "img", dst.id, "multi_in") is not None,
                "image→any(multi) 应通过")
    # 方向校验
    assert_true(graph.add_edge(dst.id, "in", src.id, "img") is None,
                "输入当输出应拒绝")
    assert_true(graph.add_edge(src.id, "img", dst.id, "out") is None,
                "输出当输入应拒绝")
    # 自连拒绝
    assert_true(graph.add_edge(dst.id, "out", dst.id, "in") is None,
                "自连应拒绝")
    # 重复拒绝
    e1 = graph.add_edge(exe.id, "out", dst.id, "in")
    assert_true(e1 is not None, "exec 首次应成功")
    assert_true(graph.add_edge(exe.id, "out", dst.id, "in") is None,
                "完全重复应拒绝")
    # 单连接替换：非 multi 输入接新边时旧边自动移除
    removed = []
    graph.edge_removed.connect(removed.append)
    src2 = BlueprintNode("start", "开始2")
    src2.add_output("out", "开始", "exec")
    graph.add_node(src2)
    e2 = graph.add_edge(src2.id, "out", dst.id, "in")
    assert_true(e2 is not None, "替换边应成功")
    assert_true(e1.id in removed, "旧边应被自动移除")
    assert_true(graph.edge(e1.id) is None and graph.edge(e2.id) is not None,
                "单连接替换结果")
    # multi 输入允许第二条
    e3 = graph.add_edge(src.id, "any_o", dst.id, "multi_in")
    assert_true(e3 is not None, "multi 第二连接应允许")
    # 不存在的节点 / 引脚
    assert_true(graph.add_edge("nope", "x", dst.id, "in") is None, "坏节点")
    assert_true(graph.add_edge(src.id, "nope", dst.id, "in") is None, "坏引脚")


# ---------------------------------------------------------------------------
# 3. 序列化往返
# ---------------------------------------------------------------------------

@check("序列化：graph 与 canvas 往返相等")
def _():
    graph = BlueprintGraph()
    a = BlueprintNode("load_image", "加载图像")
    a.add_output("img", "图像", "image")
    a.pos = QPointF(10.5, 20.25)
    a.properties["path"] = "/tmp/a.png"
    b = BlueprintNode("infer", "推理")
    b.add_input("img", "图像", "image")
    b.add_output("tensor", "张量", "tensor")
    b.pos = QPointF(300.0, 40.0)
    graph.add_node(a)
    graph.add_node(b)
    graph.add_edge(a.id, "img", b.id, "img")
    text = json.dumps(graph.to_dict(), ensure_ascii=False)
    graph2 = BlueprintGraph.from_dict(json.loads(text))
    assert_eq(graph2.to_dict(), graph.to_dict(), "graph 往返应相等")

    # 画布视图状态
    register_test_types()
    g1, c1 = make_canvas()
    n1 = c1.add_node_at("load_image", QPointF(60, 80))
    n2 = c1.add_node_at("infer", QPointF(420, 200))
    g1.add_edge(n1.id, "img", n2.id, "img")
    c1.set_zoom(1.5)
    data = c1.to_dict()
    c1.from_dict(json.loads(json.dumps(data, ensure_ascii=False)))
    assert_true(abs(c1.zoom() - 1.5) < 1e-6, "zoom 还原")
    assert_eq(c1.graph.to_dict(), data["graph"], "画布图往返相等")
    c1.close()


# ---------------------------------------------------------------------------
# 4. 注册表
# ---------------------------------------------------------------------------

@check("注册表：注册 / 搜索 / 分类 / create / body_builder / 引脚类型")
def _():
    register_test_types()
    reg = NodeRegistry.instance()
    assert_true(reg.spec("start") is not None, "内置 start 应存在")
    assert_true("流程" in reg.categories() and "处理" in reg.categories(),
                "categories")
    hits = reg.search("resize")
    assert_true(any(s.type_name == "resize" for s in hits), "search 命中类型名")
    hits = reg.search("图像")
    assert_true(any(s.type_name == "load_image" for s in hits), "search 命中描述")
    assert_true(all(s.category == "模型" for s in reg.specs("模型")),
                "specs(category)")
    node = reg.create("infer")
    assert_eq([p.id for p in node.inputs], ["in", "img"], "create 输入引脚")
    assert_eq(node.accent, "danger", "create accent")
    # body_builder 注入
    g, c = make_canvas()
    rb = c.add_node_at("resize", QPointF(100, 100))
    w = c.node_widget(rb.id)
    assert_true(w._body is not None, "body 容器应存在")
    assert_true(w._body.findChild(QLabel, "resizeBodyLabel") is not None,
                "body_builder 注入的 QLabel 应存在")
    c.close()
    # 引脚类型注册
    register_pin_type("audio", "#E0A030")
    assert_eq(PIN_COLORS["audio"], "#E0A030", "register_pin_type")
    assert_eq(pin_color("audio"), "#E0A030", "pin_color hex")
    assert_true(pin_color("int") == str(T("color.success")), "pin_color 令牌键")
    assert_true(types_compatible("any", "image") and not types_compatible("int", "str"),
                "types_compatible")


# ---------------------------------------------------------------------------
# 5. 画布：add_node_at / 边部件几何
# ---------------------------------------------------------------------------

@check("画布：add_node_at 位置与程序建边边部件几何")
def _():
    register_test_types()
    g, c = make_canvas()
    a = c.add_node_at("load_image", QPointF(80, 120))
    b = c.add_node_at("infer", QPointF(460, 240))
    assert_eq((a.pos.x(), a.pos.y()), (80.0, 120.0), "node.pos")
    wa = c.node_widget(a.id)
    tl = wa.geometry().topLeft()
    expect = c.scene_to_view(a.pos)
    assert_true(abs(tl.x() - expect.x()) < 2 and abs(tl.y() - expect.y()) < 2,
                "控件几何应与视图变换一致")
    edge = g.add_edge(a.id, "img", b.id, "img")
    assert_true(edge is not None, "建边")
    ew = c.edge_widget(edge.id)
    assert_true(ew is not None, "边部件存在")
    src = c.pin_scene_pos(a.id, "img")
    tgt = c.pin_scene_pos(b.id, "img")
    assert_true((ew.source_pos() - src).manhattanLength() < 0.01
                and (ew.target_pos() - tgt).manhattanLength() < 0.01,
                "边端点应等于引脚场景坐标")
    br = ew.bounding_rect()
    assert_true(br.contains(src) and br.contains(tgt), "外接矩形含端点")
    assert_true(ew.contains((src + tgt) / 2, tol=40), "中点附近命中")
    c.close()


# ---------------------------------------------------------------------------
# 6. 画布：模拟引脚拖拽建边
# ---------------------------------------------------------------------------

@check("画布：QTest 模拟引脚拖拽建边（临时线 + 磁吸）")
def _():
    register_test_types()
    g, c = make_canvas()
    a = c.add_node_at("load_image", QPointF(80, 120))
    b = c.add_node_at("resize", QPointF(520, 120))
    c.fit_view()
    app.processEvents()
    wa, wb = c.node_widget(a.id), c.node_widget(b.id)
    h_out = wa.pin_widget("img", PinDirection.Output)
    h_in = wb.pin_widget("img", PinDirection.Input)
    assert_true(h_out is not None and h_in is not None, "引脚热区存在")
    QTest.mousePress(h_out, Qt.LeftButton, pos=h_out.rect().center())
    assert_true(c._wire is not None, "按下引脚应出现临时线")
    target_view = h_in.mapTo(c, h_in.rect().center())
    mid = QPoint((h_out.mapTo(c, h_out.rect().center()).x() + target_view.x()) // 2,
                 target_view.y())
    QTest.mouseMove(c, mid)
    QTest.mouseMove(c, target_view)
    app.processEvents()
    assert_true(c._wire_target is not None, "磁吸应命中兼容引脚")
    QTest.mouseRelease(c, Qt.LeftButton, pos=target_view)
    app.processEvents()
    assert_eq(len(g.edges()), 1, "拖拽松开应建边")
    edge = g.edges()[0]
    assert_eq((edge.from_node, edge.from_pin, edge.to_node, edge.to_pin),
              (a.id, "img", b.id, "img"), "边端点正确")
    c.close()


# ---------------------------------------------------------------------------
# 7. 画布：橡皮筋框选 / Ctrl 多选 / Delete
# ---------------------------------------------------------------------------

@check("画布：橡皮筋框选选中、Delete 删除连带边")
def _():
    register_test_types()
    g, c = make_canvas()
    a = c.add_node_at("load_image", QPointF(80, 120))
    b = c.add_node_at("resize", QPointF(420, 120))
    d = c.add_node_at("infer", QPointF(760, 120))
    g.add_edge(a.id, "img", b.id, "img")
    g.add_edge(b.id, "img", d.id, "img")
    assert_eq(len(g.edges()), 2, "同名 id 进/出引脚建边（方向特定查找）")
    c.set_zoom(1.0)
    app.processEvents()

    def vp(sp):
        p = c.scene_to_view(QPointF(*sp))
        return QPoint(int(p.x()), int(p.y()))

    # 框选覆盖 a 与 b（不含 d）
    QTest.mousePress(c, Qt.LeftButton, pos=vp((40, 60)))
    QTest.mouseMove(c, vp((700, 320)))
    app.processEvents()
    assert_true(c._band is not None, "框选进行中")
    QTest.mouseRelease(c, Qt.LeftButton, pos=vp((700, 320)))
    app.processEvents()
    assert_eq(set(c.selected_nodes()), {a.id, b.id}, "框选应选中 a/b")

    # Ctrl 点选 d 追加
    wd = c.node_widget(d.id)
    QTest.mouseClick(wd, Qt.LeftButton, Qt.ControlModifier,
                     pos=QPoint(int(wd.width() / 2), 8))
    assert_eq(set(c.selected_nodes()), {a.id, b.id, d.id}, "Ctrl 多选")

    # Delete 删除：3 节点 + 2 边全清
    c.setFocus()
    QTest.keyClick(c, Qt.Key_Delete)
    app.processEvents()
    assert_eq(len(g.nodes()), 0, "Delete 删除节点")
    assert_eq(len(g.edges()), 0, "连带边删除")
    c.close()


# ---------------------------------------------------------------------------
# 8. 画布：缩放 / fit_view / center_on
# ---------------------------------------------------------------------------

@check("画布：缩放夹取、fit_view、center_on")
def _():
    register_test_types()
    g, c = make_canvas()
    a = c.add_node_at("load_image", QPointF(0, 0))
    b = c.add_node_at("infer", QPointF(1200, 800))
    c.set_zoom(0.1)
    assert_true(abs(c.zoom() - 0.25) < 1e-6, "缩放下限")
    c.set_zoom(9.0)
    assert_true(abs(c.zoom() - 2.5) < 1e-6, "缩放上限")
    c.fit_view()
    app.processEvents()
    assert_true(0.25 <= c.zoom() <= 2.5, "fit_view 缩放合法")
    for nid in (a.id, b.id):
        w = c.node_widget(nid)
        assert_true(w.geometry().intersects(c.rect()), "fit_view 后节点可见")
    c.center_on(a.id)
    app.processEvents()
    center_scene = c.view_to_scene(QPointF(c.width() / 2, c.height() / 2))
    na = c.graph.node(a.id)
    node_center = na.pos + QPointF(na.size.width() / 2, na.size.height() / 2)
    assert_true((center_scene - node_center).manhattanLength() < 4.0,
                "center_on 对准节点中心")
    c.close()


# ---------------------------------------------------------------------------
# 9. execution 运行指示
# ---------------------------------------------------------------------------

@check("execution：start/finish/fail/reset 与耗时徽标像素")
def _():
    register_test_types()
    g, c = make_canvas()
    a = c.add_node_at("start", QPointF(60, 100))
    b = c.add_node_at("resize", QPointF(360, 100))
    d = c.add_node_at("infer", QPointF(660, 100))
    g.add_edge(a.id, "out", b.id, "in")
    g.add_edge(b.id, "out", d.id, "in")
    ex = c.execution()
    fired = {"finished": 0, "nf": []}
    ex.finished.connect(lambda: fired.__setitem__("finished", fired["finished"] + 1))
    ex.node_finished.connect(lambda i, ms: fired["nf"].append((i, ms)))

    # start → running
    ex.start(a.id)
    app.processEvents()
    assert_eq(a.status, "running", "running 状态")
    wa = c.node_widget(a.id)
    assert_true(wa._spinner.isVisible(), "running 旋转圈可见")

    # finish → done + 徽标
    ex.finish(a.id, 12.0)
    app.processEvents()
    assert_eq(a.status, "done", "done 状态")
    assert_eq(wa.elapsed_text(), "12 ms", "耗时徽标文本")
    assert_true(fired["nf"] and abs(fired["nf"][0][1] - 12.0) < 1e-6,
                "node_finished 信号")
    assert_eq(format_elapsed(1200), "1.2 s", "秒格式")

    # 耗时徽标像素存在：徽标矩形内应有文字色像素
    img = wa.grab().toImage()
    scale = wa.width() / wa.node.size.width()
    br = wa.badge_rect()
    assert_true(not br.isNull(), "徽标矩形存在")
    from PySide6.QtGui import QColor
    text_c = QColor(str(T("color.text.secondary")))
    found = 0
    for x in range(int(br.x() * scale), min(img.width(), int((br.x() + br.width()) * scale))):
        for y in range(int(br.y() * scale), min(img.height(), int((br.y() + br.height()) * scale))):
            pc = img.pixelColor(x, y)
            if pc.alpha() > 200 and abs(pc.red() - text_c.red()) < 40 \
                    and abs(pc.green() - text_c.green()) < 40 \
                    and abs(pc.blue() - text_c.blue()) < 40:
                found += 1
    assert_true(found >= 2, f"徽标文字像素应存在（实测 {found}）")

    # 路径高亮
    ex.set_path([a.id, b.id, d.id])
    app.processEvents()
    flowing = [ew.edge.id for ew in c._edge_widgets.values() if ew.flowing]
    assert_eq(len(flowing), 2, "路径两条边应 flowing")
    assert_true(c._flow_timer.isActive(), "流动定时器应启动")

    # fail → error
    ex.start(b.id)
    ex.fail(b.id, "模拟失败")
    app.processEvents()
    assert_eq(b.status, "error", "error 状态")
    assert_true("模拟失败" in c.node_widget(b.id).toolTip(), "error tooltip")

    # finished 信号：active 清空后触发
    assert_true(fired["finished"] >= 1, "finished 信号")

    # reset → 全部 idle、耗时清空、路径取消
    ex.reset()
    app.processEvents()
    assert_true(all(n.status == "idle" for n in g.nodes()), "reset 回 idle")
    assert_true(all(n.elapsed_ms is None for n in g.nodes()), "reset 清耗时")
    assert_true(all(not ew.flowing for ew in c._edge_widgets.values()),
                "reset 取消路径")
    c.close()


# ---------------------------------------------------------------------------
# 10. NodeCreationMenu / NodeContextMenu
# ---------------------------------------------------------------------------

@check("菜单：创建菜单搜索 / 分类 / 兼容过滤，节点菜单动作信号")
def _():
    register_test_types()
    g, c = make_canvas()
    menu = NodeCreationMenu(c)
    chosen = []
    menu.type_chosen.connect(chosen.append)
    menu.popup_at(QPoint(50, 50))
    app.processEvents()
    all_types = menu.matching_types()
    for t in ("start", "load_image", "resize", "infer", "probe"):
        assert_true(t in all_types, f"创建菜单应含 {t}")
    # 分类头存在（列表项多于可选类型数）
    assert_true(menu.list.count() > len(all_types), "分类头应占行")
    # 搜索过滤
    menu.search_edit.setText("resize")
    app.processEvents()
    assert_eq(menu.matching_types(), ["resize"], "搜索过滤")
    # 兼容过滤：只留拥有 Input 且兼容 image 引脚的类型
    menu.search_edit.clear()
    menu._compatible = (PinDirection.Input, "image")
    menu._rebuild()
    compat = menu.matching_types()
    assert_true("resize" in compat and "infer" in compat, "兼容过滤保留")
    assert_true("start" not in compat and "load_image" not in compat,
                "兼容过滤剔除")
    # 回车创建第一项
    menu._compatible = None
    menu.search_edit.setText("probe")
    app.processEvents()
    menu.search_edit.returnPressed.emit()
    app.processEvents()
    assert_eq(chosen, ["probe"], "回车应选第一项")
    menu.close()

    # 节点右键菜单
    fired = []
    nmenu = NodeContextMenu("node-x", c)
    nmenu.delete_requested.connect(fired.append)
    nmenu.add_custom_action("自定义", lambda nid: fired.append("custom:" + nid))
    texts = [a.text() for a in nmenu.actions()]
    for t in ("重命名", "复制", "断开所有连线", "删除", "自定义"):
        assert_true(any(t in x for x in texts), f"动作 {t} 应存在")
    for a in nmenu.actions():
        if a.text() == "删除":
            a.trigger()
        if a.text() == "自定义":
            a.trigger()
    assert_true("node-x" in fired and "custom:node-x" in fired, "动作信号")
    c.close()


# ---------------------------------------------------------------------------
# 11. 截图：亮 / 暗 / 多节点综合
# ---------------------------------------------------------------------------

def build_showcase():
    """构建综合展示图：开始→加载→预处理→推理→保存，多类型引脚混排。"""
    register_node_type(
        "preprocess", "预处理", "处理",
        inputs=[{"id": "in", "name": "进入", "data_type": "exec"},
                {"id": "img", "name": "图像", "data_type": "image"}],
        outputs=[{"id": "out", "name": "退出", "data_type": "exec"},
                 {"id": "img", "name": "图像", "data_type": "image"}],
        accent="warning", description="归一化 / 裁剪",
    )
    register_node_type(
        "save", "保存结果", "输出",
        inputs=[{"id": "in", "name": "进入", "data_type": "exec"},
                {"id": "tensor", "name": "张量", "data_type": "tensor"}],
        accent="success", description="写出到磁盘",
    )
    register_test_types()
    g, c = make_canvas(1100, 680)
    n_start = c.add_node_at("start", QPointF(40, 90))
    n_load = c.add_node_at("load_image", QPointF(40, 300))
    n_pre = c.add_node_at("preprocess", QPointF(360, 180))
    n_infer = c.add_node_at("infer", QPointF(680, 180))
    n_save = c.add_node_at("save", QPointF(950, 240))
    n_probe = c.add_node_at("probe", QPointF(680, 460))
    g.add_edge(n_start.id, "out", n_pre.id, "in")
    g.add_edge(n_load.id, "img", n_pre.id, "img")
    g.add_edge(n_pre.id, "out", n_infer.id, "in")
    g.add_edge(n_pre.id, "img", n_infer.id, "img")
    g.add_edge(n_infer.id, "out", n_save.id, "in")
    g.add_edge(n_infer.id, "tensor", n_save.id, "tensor")
    g.add_edge(n_infer.id, "tensor", n_probe.id, "any_in")
    ex = c.execution()
    ex.set_path([n_start.id, n_pre.id, n_infer.id, n_save.id])
    ex.start(n_start.id)
    ex.finish(n_start.id, 12.0)
    ex.start(n_pre.id)
    ex.finish(n_pre.id, 45.0)
    ex.start(n_infer.id)      # running
    n_probe.properties["note"] = "示例属性"
    n_probe.changed.emit()
    c.select_nodes([n_pre.id])
    c.fit_view()
    app.processEvents()
    return g, c


@check("截图：亮 / 暗 / 多节点综合图")
def _():
    SHOTS.mkdir(parents=True, exist_ok=True)
    ThemeManager.instance().set_mode("light")
    app.processEvents()
    g, c = build_showcase()
    pm = c.grab()
    assert_true(pm.save(str(SHOTS / "blueprint_light.png")), "亮截图保存")
    pm2 = c.grab()
    assert_true(pm2.save(str(SHOTS / "blueprint_overview.png")), "综合图保存")
    ThemeManager.instance().set_mode("dark")
    app.processEvents()
    QTest.qWait(120)
    pm3 = c.grab()
    assert_true(pm3.save(str(SHOTS / "blueprint_dark.png")), "暗截图保存")
    # 主题切换真实生效：两图平均亮度应显著不同
    def avg_lum(pixmap):
        img = pixmap.toImage().scaled(64, 64)
        total = 0
        for x in range(img.width()):
            for y in range(img.height()):
                cc = img.pixelColor(x, y)
                total += (cc.red() + cc.green() + cc.blue()) / 3
        return total / (img.width() * img.height())
    assert_true(avg_lum(pm) - avg_lum(pm3) > 20, "亮暗主题像素差异")
    ThemeManager.instance().set_mode("light")
    app.processEvents()
    c.close()


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------

def main():
    print("== B1 蓝图组件库自测 ==")
    # 触发所有 @check（模块加载时已执行，此处仅汇总）
    print(f"\n共 {len(_FAILURES)} 项失败" if _FAILURES else "\n全部通过")
    for name in _FAILURES:
        print(f"  失败: {name}")
    return 1 if _FAILURES else 0


if __name__ == "__main__":
    sys.exit(main())
