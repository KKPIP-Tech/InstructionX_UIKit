# -*- coding: utf-8 -*-
"""B2 蓝图 Demo 页自测（BP_SPEC §7 / §8）。

直接运行（无 pytest 依赖）::

    QT_QPA_PLATFORM=offscreen python tests/test_blueprint_demo.py

覆盖：
- 页面构建无异常（工具条 / 画布 / 属性面板齐备）；
- ≥12 种节点类型已注册（分类含 流程/输入/处理/模型/输出/工具）；
- 预置图：6 节点、≥5 边（exec 链 + image/tensor 数据边混排）；
- 「运行」模拟（delay_range 置零加速）推进后全部节点 done 且 elapsed_ms > 0，
  状态标签显示总耗时；
- 「单步」逐节点推进；「重置」回 idle；
- 属性面板编辑与 body_builder 控件均写回 node.properties；
- 保存 / 加载 JSON（offscreen 降级 cwd 文件）与 to_dict/from_dict 往返；
- 亮 / 暗截图 tests/shots/blueprint_demo_*.png，退出码 0。
"""

import json
import os
import sys
import time
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


from PySide6.QtWidgets import QApplication, QSpinBox  # noqa: E402
from PySide6.QtCore import QPointF  # noqa: E402

app = QApplication.instance() or QApplication([])

from InstructionX_UIKit.theme import ThemeManager  # noqa: E402

ThemeManager.instance().apply(app)

from InstructionX_UIKit.blueprint import NodeRegistry  # noqa: E402
from demo.pages import blueprint as bp  # noqa: E402


def pump(ms=0):
    """推进事件循环约 ms 毫秒。"""
    deadline = time.monotonic() + ms / 1000.0
    while True:
        app.processEvents()
        if time.monotonic() >= deadline:
            break
        time.sleep(0.002)


def make_page():
    page = bp.create_page()
    page.resize(1280, 800)
    page.show()
    pump(60)
    return page


# ---------------------------------------------------------------------------
# 1. 页面构建与节点类型注册
# ---------------------------------------------------------------------------

@check("页面构建：工具条 / 画布 / 属性面板齐备")
def _():
    page = make_page()
    for attr in ("run_button", "step_button", "reset_button", "fit_button",
                 "save_button", "load_button", "status_label",
                 "canvas", "graph"):
        assert_true(getattr(page, attr, None) is not None, f"缺少 {attr}")
    assert_true(len(page.status_label.text()) > 0, "状态标签有初始文本")
    page.close()


@check("节点注册：≥12 类型，分类覆盖 流程/输入/处理/模型/输出/工具")
def _():
    reg = NodeRegistry.instance()
    specs = reg.specs()
    assert_true(len(specs) >= 12, f"已注册 {len(specs)} 种类型")
    for cat in ("流程", "输入", "处理", "模型", "输出", "工具"):
        assert_true(cat in reg.categories(), f"缺少分类 {cat}")
    for t in ("start", "load_image", "noise", "resize", "normalize",
              "gaussian_blur", "edge_detect", "cnn", "transformer",
              "fusion", "save_result", "log_output", "perf_probe"):
        assert_true(reg.spec(t) is not None, f"缺少类型 {t}")
    # ≥3 种带 body_builder
    with_body = [s.type_name for s in specs if s.body_builder is not None]
    assert_true(len(with_body) >= 3, f"body_builder 类型不足: {with_body}")


# ---------------------------------------------------------------------------
# 2. 预置图
# ---------------------------------------------------------------------------

@check("预置图：6 节点 ≥5 边（exec 链 + 数据引脚混排）")
def _():
    page = make_page()
    g = page.graph
    assert_eq(len(g.nodes()), 6, "预置节点数")
    assert_true(len(g.edges()) >= 5, "预置边数")
    exec_edges = data_edges = 0
    for e in g.edges():
        node = g.node(e.to_node)
        pin = next((p for p in node.inputs if p.id == e.to_pin), None)
        if pin is not None and pin.data_type == "exec":
            exec_edges += 1
        else:
            data_edges += 1
    assert_eq(exec_edges, 5, "exec 链 5 条边")
    assert_true(data_edges >= 4, "数据边（image/tensor 混排）")
    # exec 拓扑顺序 = 预置链
    assert_eq(bp.exec_order(g), page.preset_ids, "exec 拓扑序")
    page.close()


# ---------------------------------------------------------------------------
# 3. 运行模拟
# ---------------------------------------------------------------------------

@check("运行模拟：全部 done、elapsed_ms>0、状态标签显示总耗时")
def _():
    page = make_page()
    page.delay_range = (0, 0)  # 加速模拟
    page.run_all()
    pump(400)
    nodes = page.graph.nodes()
    assert_true(all(n.status == "done" for n in nodes),
                f"全部 done: {[n.status for n in nodes]}")
    assert_true(all(n.elapsed_ms is not None and n.elapsed_ms > 0
                    for n in nodes), "elapsed_ms>0")
    text = page.status_label.text()
    assert_true("总耗时" in text and "6" in text, f"状态标签: {text!r}")
    page.close()


@check("单步推进与重置")
def _():
    page = make_page()
    page.delay_range = (0, 0)
    page.reset_run()
    g = page.graph
    for i in range(6):
        page.step_once()
        done = [n for n in g.nodes() if n.status == "done"]
        assert_eq(len(done), i + 1, f"第 {i + 1} 步后 done 数")
        assert_true(all(n.elapsed_ms is not None for n in done), "步进耗时")
    assert_true("总耗时" in page.status_label.text(), "单步完成状态")
    page.reset_run()
    pump(50)
    assert_true(all(n.status == "idle" for n in g.nodes()), "重置回 idle")
    assert_true(all(n.elapsed_ms is None for n in g.nodes()), "重置清耗时")
    page.close()


# ---------------------------------------------------------------------------
# 4. 属性编辑写回
# ---------------------------------------------------------------------------

@check("属性面板：选中节点 → ParamForm 编辑写回 node.properties")
def _():
    page = make_page()
    cnn = next(n for n in page.graph.nodes() if n.type_name == "cnn")
    page.canvas.select_nodes([cnn.id])
    pump(30)
    assert_true(page.panel_form is not None, "属性表单已构建")
    spin = page.panel_form.controls.get("layers")
    assert_true(spin is not None, "layers 控件存在")
    spin.setValue(34)
    pump(20)
    assert_eq(cnn.properties["layers"], 34, "SpinBox 写回 properties")
    combo = page.panel_form.controls.get("channels")
    assert_true(combo is not None, "channels 控件存在")
    combo.setValue(128)
    pump(20)
    assert_eq(cnn.properties["channels"], 128, "channels 写回")
    # 取消选中 → 面板回到提示
    page.canvas.clear_selection()
    pump(20)
    assert_true(page.panel_form is None, "取消选中后面板复位")
    page.close()


@check("body_builder：节点体控件写回 node.properties")
def _():
    page = make_page()
    g = page.graph
    node = page.canvas.add_node_at("resize", QPointF(40, 560))
    pump(30)
    widget = page.canvas.node_widget(node.id)
    assert_true(widget._body is not None, "resize 有自定义节点体")
    spins = widget._body.findChildren(QSpinBox)
    assert_true(len(spins) >= 2, "宽 / 高 SpinBox 存在")
    spins[0].setValue(1024)
    pump(20)
    assert_eq(node.properties.get("width"), 1024, "body SpinBox 写回")
    g.remove_node(node.id)
    page.close()


@check("低缩放降级：zoom 0.5 隐藏节点体、zoom 1.0 恢复")
def _():
    from InstructionX_UIKit.blueprint.node_widget import BODY_MIN_ZOOM
    page = make_page()
    cnn = next(n for n in page.graph.nodes() if n.type_name == "cnn")
    widget = page.canvas.node_widget(cnn.id)
    assert_true(widget._body is not None, "cnn 有自定义节点体")
    page.canvas.set_zoom(1.0)
    pump(30)
    assert_true(widget._body.isVisible(), "zoom 1.0 体可见")
    full_h = cnn.size.height()
    page.canvas.set_zoom(0.5)  # < BODY_MIN_ZOOM
    pump(30)
    assert_true(0.5 < BODY_MIN_ZOOM, "0.5 低于阈值")
    assert_true(not widget._body.isVisible(), "zoom 0.5 体隐藏")
    assert_true(cnn.size.height() < full_h,
                "隐藏体后节点尺寸仅按标题 + 引脚计算")
    page.canvas.set_zoom(1.0)
    pump(30)
    assert_true(widget._body.isVisible(), "zoom 回升后体恢复")
    assert_true(abs(cnn.size.height() - full_h) < 1e-6, "尺寸还原")
    page.close()


# ---------------------------------------------------------------------------
# 5. 序列化：保存 / 加载 / 往返
# ---------------------------------------------------------------------------

@check("序列化：to_dict/from_dict 往返 + 保存 / 加载 JSON（offscreen 降级）")
def _():
    page = make_page()
    data = page.canvas.to_dict()
    text = json.dumps(data, ensure_ascii=False)
    page.canvas.from_dict(json.loads(text))
    pump(30)
    # 节点 size 由 NodeWidget 按字体度量重算（重建时可能微调），
    # 往返相等断言剔除 size 字段（库行为，位置 / 引脚 / 属性必须一致）。
    def _strip_size(gdata):
        return {**gdata, "nodes": [{k: v for k, v in nd.items() if k != "size"}
                                   for nd in gdata["nodes"]]}
    assert_eq(_strip_size(page.canvas.graph.to_dict()),
              _strip_size(data["graph"]), "画布图往返相等（剔除 size）")
    assert_eq(len(page.graph.nodes()), 6, "往返后节点数")

    # offscreen 降级：保存 / 加载 cwd 下 blueprint_demo.json
    path = Path.cwd() / bp.FALLBACK_JSON
    try:
        page.save_json()
        assert_true(path.exists(), "降级保存到 cwd")
        saved = json.loads(path.read_text(encoding="utf-8"))
        assert_eq(len(saved["graph"]["nodes"]), 6, "保存内容")
        page.graph.clear()
        pump(20)
        assert_eq(len(page.graph.nodes()), 0, "清空")
        page.load_json()
        pump(30)
        assert_eq(len(page.graph.nodes()), 6, "加载恢复节点")
        assert_eq(len(page.graph.edges()), 9, "加载恢复边")
    finally:
        if path.exists():
            path.unlink()
    page.close()


# ---------------------------------------------------------------------------
# 6. 截图：亮 / 暗
# ---------------------------------------------------------------------------

@check("截图：亮 / 暗 blueprint_demo_*.png 且主题差异生效")
def _():
    SHOTS.mkdir(parents=True, exist_ok=True)
    tm = ThemeManager.instance()
    tm.set_mode("light")
    tm.apply(app)
    page = make_page()
    page.delay_range = (0, 0)
    page.run_all()
    pump(300)
    # 低缩放下节点体自动隐藏（BODY_MIN_ZOOM），fit_view 全图无挤压重叠
    page.canvas.fit_view()
    pump(60)
    pm = page.grab()
    assert_true(pm.save(str(SHOTS / "blueprint_demo_light.png")), "亮截图保存")
    tm.set_mode("dark")
    tm.apply(app)
    pump(150)
    pm2 = page.grab()
    assert_true(pm2.save(str(SHOTS / "blueprint_demo_dark.png")), "暗截图保存")

    def avg_lum(pixmap):
        img = pixmap.toImage().scaled(64, 64)
        total = 0
        for x in range(img.width()):
            for y in range(img.height()):
                cc = img.pixelColor(x, y)
                total += (cc.red() + cc.green() + cc.blue()) / 3
        return total / (img.width() * img.height())

    assert_true(avg_lum(pm) - avg_lum(pm2) > 20, "亮暗主题像素差异")
    tm.set_mode("light")
    tm.apply(app)
    page.close()


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------

def main():
    print("== B2 蓝图 Demo 页自测 ==")
    print(f"\n共 {len(_FAILURES)} 项失败" if _FAILURES else "\n全部通过")
    for name in _FAILURES:
        print(f"  失败: {name}")
    return 1 if _FAILURES else 0


if __name__ == "__main__":
    sys.exit(main())
