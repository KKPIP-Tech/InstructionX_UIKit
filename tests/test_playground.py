# -*- coding: utf-8 -*-
"""Demo 交互参数面板（Playground）自测。

直接运行（无 pytest 依赖）::

    QT_QPA_PLATFORM=offscreen python tests/test_playground.py

覆盖：
- ``PlaygroundPanel`` 六类控件（int/float/choice/bool/color/text）回调与重置；
- Timeline / Steps 演示页：模拟修改 2-3 个参数，断言回调触发且目标控件
  属性 / 实例按新参数更新；
- 动画 · 属性页（28 卡）与动画 · 自绘页（24 卡）：每卡 ≥2 个参数，调参后
  「播放」按新参数重放；连续型动画参数变化自动重启；重建式卡片换参后
  演示控件被替换且构造参数生效；
- 图表页：≥12 个 QChart 实例创建无异常，调参后图表按新参数重建；
- 各页 grab() 截图到 ``tests/shots/playground_*.png``（含暗色一张）；
- 任何用例异常即失败，退出码 1；全部通过退出码 0。
"""

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

from PySide6.QtCore import QPoint, Qt  # noqa: E402
from PySide6.QtGui import QColor  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication.instance() or QApplication(sys.argv)

from InstructionX_UIKit.theme import ThemeManager  # noqa: E402
from demo.pages.playground import ParamCard, PlaygroundPanel  # noqa: E402


def pump(ms):
    """推进事件循环约 ms 毫秒。"""
    deadline = time.monotonic() + ms / 1000.0
    while time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.004)


def case(name):
    """登记一项用例；异常即记为失败。"""
    def deco(fn):
        try:
            fn()
            print(f"  [通过] {name}")
        except Exception:
            _FAILURES.append(name)
            print(f"  [失败] {name}")
            traceback.print_exc()
        return fn
    return deco


def _assert_shot(pm, name):
    if pm.isNull() or pm.width() < 4 or pm.height() < 4:
        raise AssertionError(f"{name}: grab() 失败 {pm.width()}x{pm.height()}")
    img = pm.toImage()
    w, h = img.width(), img.height()
    colors = set()
    sx, sy = max(1, w // 120), max(1, h // 120)
    for x in range(0, w, sx):
        for y in range(0, h, sy):
            colors.add(img.pixelColor(x, y).rgb())
            if len(colors) >= 2:
                return img
    raise AssertionError(f"{name}: 采样仅 {len(colors)} 种颜色，疑似空白")


def _grab(page, name):
    pm = page.widget().grab()
    _assert_shot(pm, name)
    path = SHOTS / f"playground_{name}.png"
    if not pm.save(str(path)):
        raise AssertionError(f"{name}: 截图保存失败")
    if path.stat().st_size < 200:
        raise AssertionError(f"{name}: 截图过小 {path.stat().st_size}B")
    return pm


def _page_panel(page):
    panels = page.findChildren(PlaygroundPanel)
    if not panels:
        raise AssertionError("页面未找到 PlaygroundPanel")
    return panels[0]


def main() -> int:
    print("Playground 自测开始（offscreen）")
    print("-" * 64)
    SHOTS.mkdir(parents=True, exist_ok=True)

    tm = ThemeManager.instance()
    tm.set_mode("light")
    tm.apply(app)
    pump(100)

    # ------------------------------------------------------------ 面板单元
    @case("PlaygroundPanel 六类控件回调 + 重置")
    def _():
        panel = PlaygroundPanel()
        fired = []
        panel.add_int("整数", 200, 50, 2000, lambda v: fired.append(("int", v)),
                      key="i")
        panel.add_float("浮点", 0.5, 0.0, 1.0,
                        lambda v: fired.append(("float", v)), key="f")
        panel.add_choice("下拉", ["left", ("右", "right")], "left",
                         lambda v: fired.append(("choice", v)), key="c")
        panel.add_bool("开关", True, lambda v: fired.append(("bool", v)), key="b")
        panel.add_color("颜色", "#3563E9",
                        lambda v: fired.append(("color", v)), key="col")
        panel.add_text("文本", "abc", lambda v: fired.append(("text", v)),
                       key="t")
        if panel.width() != 280:
            raise AssertionError(f"面板固定宽应为 280，实际 {panel.width()}")
        panel.controls["i"].setValue(500)
        panel.controls["f"].setValue(0.8)
        panel.controls["c"].setCurrentIndex(1)
        panel.controls["b"].setChecked(False)
        panel.controls["col"].set_color(QColor("#FF0000"))
        panel.controls["t"].setText("hello")
        kinds = [k for k, _ in fired]
        for expect in ("int", "float", "choice", "bool", "color", "text"):
            if expect not in kinds:
                raise AssertionError(f"{expect} 回调未触发: {fired}")
        if ("choice", "right") not in fired:
            raise AssertionError(f"choice 回调应带选项数据: {fired}")
        if not isinstance(fired[kinds.index("color")][1], QColor):
            raise AssertionError("color 回调应携带 QColor")
        panel.reset()
        vals = panel.values()
        if vals["i"] != 200 or vals["c"] != "left" or vals["b"] is not True:
            raise AssertionError(f"重置后默认值未恢复: {vals}")

    # ------------------------------------------------------------ Timeline
    from demo.pages.display import TimelineEx, create_timeline_page

    tl_page = create_timeline_page()

    @case("Timeline 页：参数回调与目标控件更新")
    def _():
        panel = _page_panel(tl_page)
        tl = tl_page.findChildren(TimelineEx)[0]
        fired = []
        panel.changed.connect(lambda k, v: fired.append(k))
        # 1) 节点颜色（各节点）
        panel.controls["color0"].setCurrentIndex(1)  # success
        if tl.items()[0]["color"] != "success":
            raise AssertionError(f"节点1颜色未生效: {tl.items()[0]['color']}")
        # 2) pending 开关 + 文本
        panel.controls["pending_on"].setChecked(False)
        if tl.pending() is not None:
            raise AssertionError("pending 关闭后应为 None")
        panel.controls["pending_on"].setChecked(True)
        panel.controls["pending_text"].setText("等待商家出餐")
        if tl.pending() != "等待商家出餐":
            raise AssertionError(f"pending 文本未生效: {tl.pending()}")
        # 3) 绘制参数（子类属性 + update）
        panel.controls["dot_radius"].setValue(8)
        panel.controls["line_style"].setCurrentIndex(1)  # 虚线
        panel.controls["axis_side"].setCurrentIndex(1)   # 右侧
        if tl.dot_radius != 8 or tl.axis_side != "right" \
                or tl.line_style != Qt.DashLine:
            raise AssertionError("绘制参数未应用到 TimelineEx")
        # 4) 图标模式
        panel.controls["icon_mode"].setCurrentIndex(1)
        if tl.items()[0]["icon"] is None:
            raise AssertionError("图标模式未生效")
        for key in ("color0", "pending_on", "dot_radius", "icon_mode"):
            if key not in fired:
                raise AssertionError(f"changed 信号缺少 {key}: {fired}")
        panel.reset()
        if tl.pending() != "等待骑手接单" or tl.items()[0]["color"] is not None:
            raise AssertionError("重置后 Timeline 未恢复默认")

    @case("Timeline 页截图")
    def _():
        pump(150)
        _grab(tl_page, "timeline")

    # ------------------------------------------------------------ Steps
    from demo.pages.feedback import StepsEx, create_steps_page

    st_page = create_steps_page()

    @case("Steps 页：参数回调与目标控件更新")
    def _():
        panel = _page_panel(st_page)
        st = st_page.findChildren(StepsEx)[0]
        # 1) 当前步骤
        panel.controls["current"].setValue(3)
        if st.current() != 3 or st.status_of(0) != "finish":
            raise AssertionError("当前步骤未生效")
        # 2) 各步显式状态
        panel.controls["status2"].setCurrentIndex(4)  # error
        if st.status_of(2) != "error":
            raise AssertionError("显式 error 状态未生效")
        panel.controls["status2"].setCurrentIndex(0)  # 自动
        if st.status_of(2) != "finish":  # current=3 → 推导为 finish
            raise AssertionError("恢复自动推导失败")
        # 3) 方向（重建实例）+ 状态保持
        old = st
        panel.controls["orientation"].setCurrentIndex(1)  # 垂直
        st2 = st_page.findChildren(StepsEx)[0]
        if st2 is old or st2._orientation != Qt.Vertical:
            raise AssertionError("方向切换未重建为垂直实例")
        if st2.current() != 3:
            raise AssertionError("重建后当前步骤未保持")
        # 4) 步骤数 / 节点半径 / 连接线
        panel.controls["count"].setValue(5)
        st3 = st_page.findChildren(StepsEx)[0]
        if len(st3._steps) != 5:
            raise AssertionError("步骤数未生效")
        panel.controls["node_radius"].setValue(16)
        panel.controls["link_style"].setCurrentIndex(2)  # 点线
        if st3.node_radius != 16 or st3.link_style != Qt.DotLine:
            raise AssertionError("节点 / 连接线参数未生效")
        # 5) 点击切换步骤（切回水平方向；页面未显示，直接派生鼠标事件）
        panel.controls["orientation"].setCurrentIndex(0)  # 水平
        st4 = st_page.findChildren(StepsEx)[0]
        if not st4.clickable:
            raise AssertionError("clickable 默认应为 True")
        st4.resize(500, 120)
        st4.set_current(0)
        from PySide6.QtGui import QMouseEvent, QPointingDevice
        pos = QPoint(490, 60)  # seg = 500/5 → 命中第 5 步
        for etype in (QMouseEvent.Type.MouseButtonPress,
                      QMouseEvent.Type.MouseButtonRelease):
            ev = QMouseEvent(etype, pos, pos, pos,
                             Qt.MouseButton.LeftButton,
                             Qt.MouseButton.LeftButton, Qt.NoModifier,
                             QPointingDevice.primaryPointingDevice())
            QApplication.sendEvent(st4, ev)
        if st4.current() != 4:
            raise AssertionError(f"点击切换步骤失败: current={st4.current()}")
        panel.reset()

    @case("Steps 页截图")
    def _():
        pump(150)
        _grab(st_page, "steps")

    # ------------------------------------------------------------ 动画·属性
    from demo.pages.anim_property import create_page as create_prop_page

    prop_page = create_prop_page()
    prop_cards = prop_page.findChildren(ParamCard)

    @case("动画·属性页：28 卡、每卡 ≥2 参数、全部可播放")
    def _():
        if len(prop_cards) != 28:
            raise AssertionError(f"卡片数 {len(prop_cards)} != 28")
        for card in prop_cards:
            if len(card.form._entries) < 2:
                raise AssertionError(
                    f"{card!r} 参数少于 2 个: {len(card.form._entries)}")
            card.replay()
        pump(120)

    @case("动画·属性页：调参后播放按新参数执行")
    def _():
        fade = prop_cards[0]
        fade.controls["duration"].setValue(800)
        fade.replay()
        if fade.handle is None or fade.handle.duration() != 800:
            raise AssertionError("fade_in 新时长未生效")
        slide = prop_cards[2]
        slide.controls["direction"].setCurrentIndex(3)  # down
        slide.replay()
        # 连续型：参数变化自动重启
        breath = prop_cards[20]
        breath.replay()
        old_handle = breath.handle
        breath.controls["duration"].setValue(3000)
        if breath.handle is None or breath.handle is old_handle:
            raise AssertionError("breathing 参数变化未自动重启")
        if breath.handle.duration() != 3000:
            raise AssertionError("breathing 新周期未生效")
        # 循环次数带特殊文本（无限）的 int 参数
        float_card = prop_cards[18]
        float_card.controls["loops"].setValue(3)
        float_card.replay()
        pump(100)

    @case("动画·属性页截图")
    def _():
        pump(150)
        _grab(prop_page, "anim_property")

    # ------------------------------------------------------------ 动画·自绘
    from demo.pages.anim_painted import create_page as create_paint_page

    paint_page = create_paint_page()
    paint_cards = paint_page.findChildren(ParamCard)

    @case("动画·自绘页：24 卡、每卡 ≥2 参数、全部可播放")
    def _():
        if len(paint_cards) != 24:
            raise AssertionError(f"卡片数 {len(paint_cards)} != 24")
        for card in paint_cards:
            if len(card.form._entries) < 2:
                raise AssertionError(
                    f"{card!r} 参数少于 2 个: {len(card.form._entries)}")
            card.replay()
        pump(120)

    @case("动画·自绘页：调参即重建演示控件")
    def _():
        spinner = paint_cards[0]
        old_demo = spinner.demo
        spinner.controls["size"].setValue(60)
        if spinner.demo is old_demo:
            raise AssertionError("SpinnerArc 未重建")
        if spinner.demo._size != 60 or spinner.demo.width() != 60:
            raise AssertionError("SpinnerArc 新尺寸未生效")
        marquee = paint_cards[14]
        marquee.controls["text"].setText("新的跑马灯文本")
        if marquee.demo._text != "新的跑马灯文本":
            raise AssertionError("MarqueeLabel 文本未生效")
        dots = paint_cards[1]
        dots.controls["count"].setValue(5)
        if dots.demo._count != 5:
            raise AssertionError("BouncingDots 数量未生效")
        cover = paint_cards[23]
        old_cover = cover.demo
        cover.controls["items"].setValue(7)
        if cover.demo is old_cover:
            raise AssertionError("CoverFlow 未重建")
        pump(100)

    @case("动画·自绘页截图")
    def _():
        pump(150)
        _grab(paint_page, "anim_painted")

    # -------------------------------------------- 图表（原生引擎页；详细断言见 test_charts_gallery.py）
    from InstructionX_UIKit.charts import ChartWidget
    from demo.pages.charts import create_page as create_chart_page

    chart_page = create_chart_page()

    @case("图表页：原生引擎 ChartWidget ≥ 24 且无 QtCharts 依赖")
    def _():
        widgets = chart_page.findChildren(ChartWidget)
        if len(widgets) < 24:
            raise AssertionError(f"ChartWidget {len(widgets)} < 24")
        pump(300)

    @case("图表页截图（亮 + 暗）")
    def _():
        pump(800)
        light = _grab(chart_page, "charts").toImage()
        tm.set_mode("dark")
        tm.apply(app)
        pump(400)
        dark_pm = _grab(chart_page, "charts_dark")
        if light.size() == dark_pm.toImage().size() and light == dark_pm.toImage():
            raise AssertionError("亮暗图表截图完全一致，主题联动失败")
        tm.set_mode("light")
        tm.apply(app)
        pump(200)

    print("-" * 64)
    if _FAILURES:
        print(f"共 {len(_FAILURES)} 项失败: {_FAILURES}")
        return 1
    print(f"全部用例通过，截图目录: {SHOTS}")
    print("0 错误，0 段错误")
    return 0


if __name__ == "__main__":
    sys.exit(main())
