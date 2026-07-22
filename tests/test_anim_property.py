# -*- coding: utf-8 -*-
"""anim-A 自测：属性类动画预设（SPEC §7.1 / §9）。

直接运行（无 pytest 依赖）::

    QT_QPA_PLATFORM=offscreen python tests/test_anim_property.py

覆盖 SPEC §7.1 列出的全部动画预设函数：
fade_in, fade_out, slide_in, zoom_in, spring_pop, stagger_in, blur_in,
mask_reveal, hover_lift, button_morph_loading, ripple, switch_toggle,
pulse, bounce, swing, shake, flash_highlight, float_loop, pulse_glow,
breathing, gradient_flow, gradient_text_flow, cross_fade, page_transition,
slide_transition, container_morph, shared_element, badge_pop

每个函数在离屏演示控件上触发 1 次，驱动事件循环约 650ms，
期间 grab() 中间帧与结束帧到 ``tests/shots/animprop_<name>.png`` /
``animprop_<name>_end.png``；断言无异常、动画对象存活（可访问 state()），
并对若干函数断言最终状态（切页索引 / checked 翻转 / 宽度收缩等）。
任何异常即失败，退出码 1。
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


def check(name):
    """装饰器：登记一项检查并立即执行，异常即记为失败。"""

    def deco(fn):
        try:
            fn()
            print(f"  [通过] {name}")
        except Exception:
            _FAILURES.append(name)
            print(f"  [失败] {name}")
            traceback.print_exc()

    return deco


# ---------------------------------------------------------------------------
# 引导：先建 QApplication + 应用主题（@check 在模块定义阶段即执行）
# ---------------------------------------------------------------------------

def _bootstrap():
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    from InstructionX_UIKit.theme import ThemeManager

    ThemeManager.instance().set_mode("light")
    ThemeManager.instance().apply(app)
    SHOTS.mkdir(parents=True, exist_ok=True)
    return app


_APP = _bootstrap()


# ---------------------------------------------------------------------------
# 测试基础设施
# ---------------------------------------------------------------------------

def pump(ms: int) -> None:
    """驱动事件循环 ms 毫秒（属性动画依赖定时器与事件分发）。"""
    from PySide6.QtCore import QElapsedTimer
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    timer = QElapsedTimer()
    timer.start()
    while timer.elapsed() < ms:
        app.processEvents()
        time.sleep(0.004)


def assert_alive(anim, name: str) -> None:
    """断言动画对象存活（C++ 侧未被删除）。"""
    if anim is None:
        raise AssertionError(f"{name}: 返回句柄为 None")
    try:
        anim.state()
    except RuntimeError as exc:
        raise AssertionError(f"{name}: 动画对象已被 GC 销毁: {exc}") from exc
    except AttributeError as exc:
        raise AssertionError(f"{name}: 返回对象不是动画: {exc}") from exc


def assert_state(anim, expect_running: bool, name: str) -> None:
    """断言动画处于 Running / Stopped。"""
    from PySide6.QtCore import QAbstractAnimation

    state = anim.state()
    if expect_running and state != QAbstractAnimation.Running:
        raise AssertionError(f"{name}: 期望 Running，实际 {state}")
    if not expect_running and state != QAbstractAnimation.Stopped:
        raise AssertionError(f"{name}: 期望 Stopped，实际 {state}")


def save_shot(widget, name: str, suffix: str = "") -> None:
    """grab() 控件并保存截图，断言文件有效。"""
    pm = widget.grab()
    if pm.isNull() or pm.width() < 10:
        raise AssertionError(f"{name}: grab() 失败")
    path = SHOTS / f"animprop_{name}{suffix}.png"
    if not pm.save(str(path)):
        raise AssertionError(f"{name}: 截图保存失败 {path}")
    if path.stat().st_size < 1024:
        raise AssertionError(f"{name}: 截图过小 {path}")


class DemoStage:
    """单项动画的演示舞台：独立小窗口 + 绝对定位演示控件（避开布局干扰）。"""

    def __init__(self, w=340, h=240):
        from PySide6.QtWidgets import QFrame, QLabel, QPushButton, QWidget

        from InstructionX_UIKit.theme import T

        self.win = QWidget()
        self.win.resize(w, h)
        self.button = QPushButton("演示按钮", self.win)
        self.button.setProperty("variant", "primary")
        self.button.setGeometry(24, 24, 128, 36)
        self.label = QLabel("动画演示文本", self.win)
        self.label.setGeometry(24, 76, 200, 28)
        self.frame = QFrame(self.win)
        self.frame.setGeometry(200, 24, 110, 70)
        self.frame.setStyleSheet(
            f"background: {T('color.primary')}; border-radius: 8px;")

    def __enter__(self):
        self.win.show()
        pump(60)
        return self

    def __exit__(self, *exc):
        self.win.close()
        self.win.deleteLater()
        pump(20)
        return False

    def run(self, name, anim, mid_ms=280, end_ms=380, running=False):
        """公共流程：推进时间线、抓中间帧 / 结束帧、断言动画存活与状态。"""
        pump(mid_ms)
        save_shot(self.win, name)
        assert_alive(anim, name)
        pump(end_ms)
        save_shot(self.win, name, suffix="_end")
        assert_alive(anim, name)
        assert_state(anim, running, name)
        if running:
            anim.stop()
        return anim


# ---------------------------------------------------------------------------
# 各预设函数检查
# ---------------------------------------------------------------------------

@check("fade_in / fade_out")
def _():
    from InstructionX_UIKit.anim.property import fade_in, fade_out

    with DemoStage() as stage:
        anim = fade_in(stage.frame, duration=200)
        stage.run("fade_in", anim, mid_ms=100, end_ms=250)
        if stage.frame.graphicsEffect() is not None:
            raise AssertionError("fade_in 结束后应摘除不透明度效果")

    with DemoStage() as stage:
        anim = fade_out(stage.button, duration=200)
        stage.run("fade_out", anim, mid_ms=100, end_ms=250)
        # 快照叠加路径下 fade_out 结束等价为 setVisible(False)（见实现说明）
        if stage.button.isVisible():
            raise AssertionError("fade_out 结束后目标应隐藏（setVisible(False)）")


@check("slide_in 四方向")
def _():
    from InstructionX_UIKit.anim.property import slide_in

    with DemoStage() as stage:
        end_pos = stage.frame.pos()
        anim = slide_in(stage.frame, direction="left", distance=60, duration=240)
        stage.run("slide_in", anim, mid_ms=120, end_ms=260)
        if stage.frame.pos() != end_pos:
            raise AssertionError(f"slide_in(left) 结束未回到原位: {stage.frame.pos()}")
    for direction in ("right", "up", "down"):
        with DemoStage() as stage:
            end_pos = stage.frame.pos()
            anim = slide_in(stage.frame, direction=direction, distance=60, duration=200)
            pump(320)
            assert_alive(anim, f"slide_in({direction})")
            if stage.frame.pos() != end_pos:
                raise AssertionError(f"slide_in({direction}) 结束未回到原位")
    # 非法方向应报错
    with DemoStage() as stage:
        try:
            slide_in(stage.frame, direction="north")
        except ValueError:
            pass
        else:
            raise AssertionError("非法方向必须抛 ValueError")


@check("zoom_in")
def _():
    from InstructionX_UIKit.anim.property import zoom_in

    with DemoStage() as stage:
        anim = zoom_in(stage.frame, from_scale=0.5, duration=240)
        stage.run("zoom_in", anim, mid_ms=120, end_ms=260)
        if stage.frame.graphicsEffect() is not None:
            raise AssertionError("zoom_in 结束后应摘除变换效果")


@check("spring_pop")
def _():
    from InstructionX_UIKit.anim.property import spring_pop

    with DemoStage() as stage:
        anim = spring_pop(stage.button, duration=320)
        stage.run("spring_pop", anim, mid_ms=160, end_ms=300)


@check("stagger_in")
def _():
    from PySide6.QtWidgets import QPushButton, QWidget

    from InstructionX_UIKit.anim.property import stagger_in

    win = QWidget()
    win.resize(340, 200)
    children = []
    for i in range(4):
        btn = QPushButton(f"条目 {i + 1}", win)
        btn.setGeometry(24, 20 + i * 42, 140, 32)
        children.append(btn)
    win.show()
    pump(60)
    anim = stagger_in(win, children=children, interval=80, duration=200)
    pump(250)
    save_shot(win, "stagger_in")
    assert_alive(anim, "stagger_in")
    pump(500)  # 尾项延迟 3*80 + 时长 200，留足余量
    save_shot(win, "stagger_in", suffix="_end")
    assert_state(anim, False, "stagger_in")
    win.close()
    win.deleteLater()
    pump(20)


@check("blur_in")
def _():
    from InstructionX_UIKit.anim.property import blur_in

    with DemoStage() as stage:
        anim = blur_in(stage.frame, radius=16, duration=320)
        stage.run("blur_in", anim, mid_ms=150, end_ms=330)
        if stage.frame.graphicsEffect() is not None:
            raise AssertionError("blur_in 结束后应摘除模糊效果")


@check("mask_reveal 多方向")
def _():
    from InstructionX_UIKit.anim.property import mask_reveal

    with DemoStage() as stage:
        anim = mask_reveal(stage.frame, direction="right", duration=320)
        stage.run("mask_reveal", anim, mid_ms=150, end_ms=340)
        if not stage.frame.mask().isEmpty():
            raise AssertionError("mask_reveal 结束后应 clearMask")
    for direction in ("left", "up", "down", "circle"):
        with DemoStage() as stage:
            anim = mask_reveal(stage.frame, direction=direction, duration=240)
            pump(360)
            assert_alive(anim, f"mask_reveal({direction})")
            if not stage.frame.mask().isEmpty():
                raise AssertionError(f"mask_reveal({direction}) 结束后应 clearMask")


@check("hover_lift 事件过滤器")
def _():
    from PySide6.QtCore import QEvent
    from PySide6.QtWidgets import QApplication, QGraphicsDropShadowEffect

    from InstructionX_UIKit.anim.property import hover_lift

    with DemoStage() as stage:
        btn = stage.button
        filt = hover_lift(btn, dy=4)
        if filt is None or filt.parent() is not btn:
            raise AssertionError("hover_lift 应返回 parent 到目标的事件过滤器")
        QApplication.instance().sendEvent(btn, QEvent(QEvent.Enter))
        pump(200)
        save_shot(stage.win, "hover_lift")
        # 快照叠加路径：抬升由叠加层绘制（ov.dy == -dy），目标本身不移动、
        # 也不安装 QGraphicsDropShadowEffect（见实现说明）
        ov = filt.overlay
        if ov is None:
            raise AssertionError("hover 后应存在抬升叠加层")
        if abs(ov.dy - (-4)) > 0.5:
            raise AssertionError(f"hover 后叠加层应上移 4px，实际 {-ov.dy}")
        QApplication.instance().sendEvent(ov, QEvent(QEvent.Leave))
        pump(300)
        save_shot(stage.win, "hover_lift", suffix="_end")
        if filt.overlay is not None:
            raise AssertionError("leave 后叠加层应移除（目标还原）")


@check("button_morph_loading 变形 + restore")
def _():
    from InstructionX_UIKit.anim.property import button_morph_loading

    with DemoStage() as stage:
        btn = stage.button
        orig_w = btn.width()
        orig_text = btn.text()
        anim = button_morph_loading(btn, duration=200)
        pump(300)
        save_shot(stage.win, "button_morph_loading")
        if btn.width() >= orig_w:
            raise AssertionError(f"变形后宽度应收缩: {btn.width()} >= {orig_w}")
        if btn.isEnabled():
            raise AssertionError("加载态应禁用按钮")
        pump(400)
        save_shot(stage.win, "button_morph_loading", suffix="_end")
        assert_alive(anim, "button_morph_loading")
        assert_state(anim, True, "button_morph_loading")  # 呼吸为无限循环
        anim.restore()
        pump(60)
        if btn.text() != orig_text or not btn.isEnabled() or btn.maximumWidth() < 1000000:
            raise AssertionError("restore 后应还原文字 / 可用态 / 宽度约束")


@check("ripple 点击涟漪")
def _():
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from InstructionX_UIKit.anim.property import ripple

    with DemoStage() as stage:
        btn = stage.button
        filt = ripple(btn)
        if filt is None or filt.parent() is not btn:
            raise AssertionError("ripple 应返回 parent 到按钮的事件过滤器")
        if ripple(btn) is not filt:
            raise AssertionError("重复调用 ripple 应返回同一过滤器")
        QTest.mousePress(btn, Qt.LeftButton, pos=btn.rect().center())
        pump(140)
        save_shot(stage.win, "ripple")
        if filt._anim is None:
            raise AssertionError("按下后应启动涟漪动画")
        assert_alive(filt._anim, "ripple 动画")
        QTest.mouseRelease(btn, Qt.LeftButton, pos=btn.rect().center())
        pump(320)
        save_shot(stage.win, "ripple", suffix="_end")
        # 再次点击应能重复触发
        QTest.mouseClick(btn, Qt.LeftButton, pos=btn.rect().center())
        pump(100)
        assert_alive(filt._anim, "ripple 重复触发")


@check("switch_toggle 状态翻转")
def _():
    from PySide6.QtWidgets import QCheckBox

    from InstructionX_UIKit.anim.property import switch_toggle

    with DemoStage() as stage:
        cb = QCheckBox("开关选项", stage.win)
        cb.setGeometry(24, 120, 140, 28)
        cb.show()
        pump(30)
        anim = switch_toggle(cb)
        pump(120)
        save_shot(stage.win, "switch_toggle")
        pump(260)
        save_shot(stage.win, "switch_toggle", suffix="_end")
        assert_alive(anim, "switch_toggle")
        if not cb.isChecked():
            raise AssertionError("switch_toggle 后应置为选中")
        anim2 = switch_toggle(cb, checked=False)
        pump(360)
        if cb.isChecked():
            raise AssertionError("指定 checked=False 应取消选中")


@check("pulse")
def _():
    from InstructionX_UIKit.anim.property import pulse

    with DemoStage() as stage:
        anim = pulse(stage.button, peak=1.12, duration=320)
        stage.run("pulse", anim, mid_ms=150, end_ms=340)


@check("bounce")
def _():
    from InstructionX_UIKit.anim.property import bounce

    with DemoStage() as stage:
        p0 = stage.frame.pos()
        anim = bounce(stage.frame, height=14)
        stage.run("bounce", anim, mid_ms=220, end_ms=330)
        if stage.frame.pos() != p0:
            raise AssertionError("bounce 结束应回到原位")


@check("swing")
def _():
    from InstructionX_UIKit.anim.property import swing

    with DemoStage() as stage:
        anim = swing(stage.button, angle=10)
        stage.run("swing", anim, mid_ms=200, end_ms=360)


@check("shake")
def _():
    from InstructionX_UIKit.anim.property import shake

    with DemoStage() as stage:
        p0 = stage.frame.pos()
        anim = shake(stage.frame, distance=8)
        stage.run("shake", anim, mid_ms=150, end_ms=310)
        if stage.frame.pos() != p0:
            raise AssertionError("shake 结束应回到原位")


@check("flash_highlight")
def _():
    from InstructionX_UIKit.anim.property import flash_highlight

    with DemoStage() as stage:
        anim = flash_highlight(stage.frame, times=1, duration=400)
        stage.run("flash_highlight", anim, mid_ms=150, end_ms=400)


@check("float_loop 无限循环")
def _():
    from InstructionX_UIKit.anim.property import float_loop

    with DemoStage() as stage:
        anim = float_loop(stage.frame, dy=6, duration=800)
        stage.run("float_loop", anim, mid_ms=300, end_ms=360, running=True)


@check("pulse_glow 无限循环")
def _():
    from InstructionX_UIKit.anim.property import pulse_glow

    with DemoStage() as stage:
        anim = pulse_glow(stage.button, duration=900)
        stage.run("pulse_glow", anim, mid_ms=300, end_ms=360, running=True)


@check("breathing 无限循环")
def _():
    from InstructionX_UIKit.anim.property import breathing

    with DemoStage() as stage:
        anim = breathing(stage.frame, duration=900)
        stage.run("breathing", anim, mid_ms=300, end_ms=360, running=True)


@check("gradient_flow 背景渐变流动")
def _():
    from InstructionX_UIKit.anim.property import gradient_flow

    with DemoStage() as stage:
        orig_sheet = stage.frame.styleSheet()
        anim = gradient_flow(stage.frame, duration=1200)
        pump(320)
        save_shot(stage.win, "gradient_flow")
        sheet_mid = stage.frame.styleSheet()
        pump(360)
        save_shot(stage.win, "gradient_flow", suffix="_end")
        assert_alive(anim, "gradient_flow")
        assert_state(anim, True, "gradient_flow")
        if "qlineargradient" not in sheet_mid:
            raise AssertionError("gradient_flow 应写入 qlineargradient QSS")
        anim.stop()
        pump(40)
        if stage.frame.styleSheet() != orig_sheet:
            raise AssertionError("gradient_flow 结束后应还原原始样式表")


@check("gradient_text_flow 文字渐变流动")
def _():
    from InstructionX_UIKit.anim.property import gradient_text_flow

    with DemoStage() as stage:
        orig = stage.label.text()
        anim = gradient_text_flow(stage.label, duration=1200)
        pump(320)
        save_shot(stage.win, "gradient_text_flow")
        html_mid = stage.label.text()
        pump(360)
        save_shot(stage.win, "gradient_text_flow", suffix="_end")
        assert_alive(anim, "gradient_text_flow")
        assert_state(anim, True, "gradient_text_flow")
        if "span" not in html_mid or "color" not in html_mid:
            raise AssertionError("gradient_text_flow 应生成逐字着色的富文本")
        anim.stop()
        pump(40)
        if stage.label.text() != orig:
            raise AssertionError("gradient_text_flow 结束后应还原原文本")


@check("cross_fade 堆叠页交叉淡化")
def _():
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QLabel, QStackedWidget

    from InstructionX_UIKit.anim.property import cross_fade
    from InstructionX_UIKit.theme import T

    with DemoStage() as stage:
        st = QStackedWidget(stage.win)
        st.setGeometry(24, 120, 220, 100)
        p1 = QLabel("第一页")
        p1.setAlignment(Qt.AlignCenter)
        p1.setStyleSheet(f"background: {T('color.primary.subtle')};")
        p2 = QLabel("第二页")
        p2.setAlignment(Qt.AlignCenter)
        p2.setStyleSheet(f"background: {T('color.success.subtle')};")
        st.addWidget(p1)
        st.addWidget(p2)
        st.show()
        pump(40)
        anim = cross_fade(st, index=1, duration=240)
        stage.run("cross_fade", anim, mid_ms=120, end_ms=300)
        if st.currentIndex() != 1:
            raise AssertionError("cross_fade 后应切到目标页")


@check("page_transition slide / fade 切页")
def _():
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QLabel, QStackedWidget

    from InstructionX_UIKit.anim.property import page_transition
    from InstructionX_UIKit.theme import T

    with DemoStage() as stage:
        st = QStackedWidget(stage.win)
        st.setGeometry(24, 120, 220, 100)
        for i, color in enumerate((T("color.warning.subtle"), T("color.danger.subtle"))):
            page = QLabel(f"页面 {i + 1}")
            page.setAlignment(Qt.AlignCenter)
            page.setStyleSheet(f"background: {color};")
            st.addWidget(page)
        st.show()
        pump(40)
        anim = page_transition(st, 1, kind="slide", direction="left", duration=300)
        stage.run("page_transition", anim, mid_ms=150, end_ms=350)
        if st.currentIndex() != 1:
            raise AssertionError("page_transition 后应切到目标页")
        # kind=fade 走 cross_fade 分支，快速验证不抛异常
        anim2 = page_transition(st, 0, kind="fade", duration=200)
        pump(320)
        assert_alive(anim2, "page_transition(fade)")
        if st.currentIndex() != 0:
            raise AssertionError("page_transition(fade) 后应切到目标页")


@check("slide_transition 两控件滑动")
def _():
    from PySide6.QtWidgets import QFrame

    from InstructionX_UIKit.anim.property import slide_transition
    from InstructionX_UIKit.theme import T

    with DemoStage() as stage:
        a = QFrame(stage.win)
        a.setGeometry(24, 120, 160, 80)
        a.setStyleSheet(f"background: {T('color.primary')}; border-radius: 8px;")
        b = QFrame(stage.win)
        b.setStyleSheet(f"background: {T('color.success')}; border-radius: 8px;")
        a.show()
        pump(40)
        anim = slide_transition(a, to=b, direction="left", duration=300)
        stage.run("slide_transition", anim, mid_ms=150, end_ms=350)
        if a.isVisible():
            raise AssertionError("slide_transition 后源控件应隐藏")
        if not b.isVisible() or b.pos() != a.pos():
            raise AssertionError("slide_transition 后目标控件应位于源控件位置")


@check("container_morph 大小 + 圆角变形")
def _():
    from InstructionX_UIKit.anim.property import container_morph
    from InstructionX_UIKit.theme import T

    with DemoStage() as stage:
        fr = stage.frame
        fr.setStyleSheet(f"background: {T('color.primary')};")
        anim = container_morph(fr, size=(150, 100), radius=20, duration=300)
        stage.run("container_morph", anim, mid_ms=150, end_ms=350)
        if fr.size().width() != 150 or fr.size().height() != 100:
            raise AssertionError(f"container_morph 结束尺寸异常: {fr.size()}")
        if "border-radius" not in fr.styleSheet():
            raise AssertionError("container_morph 应写入 border-radius")
        anim.restore()
        pump(40)


@check("shared_element 几何迁移")
def _():
    from PySide6.QtCore import QRect

    from InstructionX_UIKit.anim.property import shared_element

    with DemoStage() as stage:
        fr = stage.frame
        target_rect = QRect(60, 130, 150, 80)
        anim = shared_element(fr, to=target_rect, duration=300)
        stage.run("shared_element", anim, mid_ms=150, end_ms=350)
        if fr.geometry() != target_rect:
            raise AssertionError(f"shared_element 结束几何异常: {fr.geometry()}")


@check("badge_pop 角标弹入")
def _():
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QLabel

    from InstructionX_UIKit.anim.property import badge_pop
    from InstructionX_UIKit.theme import T

    with DemoStage() as stage:
        badge = QLabel("9", stage.win)
        badge.setGeometry(140, 16, 20, 20)
        badge.setAlignment(Qt.AlignCenter)
        badge.setStyleSheet(
            f"background: {T('color.danger')}; color: white; border-radius: 10px;")
        badge.show()
        pump(30)
        anim = badge_pop(badge)
        stage.run("badge_pop", anim, mid_ms=150, end_ms=350)


# ---------------------------------------------------------------------------
# 汇总
# ---------------------------------------------------------------------------

def main() -> int:
    print("-" * 60)
    if _FAILURES:
        print(f"共 {len(_FAILURES)} 项失败: {_FAILURES}")
        return 1
    print("全部检查通过，0 错误")
    return 0


if __name__ == "__main__":
    print("anim-A 属性类动画自测开始（offscreen）")
    sys.exit(main())
