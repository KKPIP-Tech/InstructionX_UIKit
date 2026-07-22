# -*- coding: utf-8 -*-
"""F3 修复验证：动画真机可用性（快照叠加层路径 + 三个自绘组件修复）。

直接运行（无 pytest 依赖）::

    QT_QPA_PLATFORM=offscreen python tests/test_fix_f3.py

背景：真机（Windows + Qt6 + QSS + 高 DPI）上 QGraphicsEffect 可能整片
不绘制、pos 动画被布局重置，导致 15 个动画「完全不渲染」。fix/f3 将
这些动画统一改为快照叠加层基元（property.py 内部），本测试验证：

1. 15 个动画（fade_in, slide_in, zoom_in, spring_pop, badge_pop,
   blur_in, mask_reveal, hover_lift, pulse, bounce, swing, shake,
   float_loop, pulse_glow, cross_fade）逐一在
   「布局管理的控件」与「绝对定位控件」两种宿主下触发，断言：
   - 动画期间：快照会话 / 叠加层存在、目标隐藏、叠加层中间帧非空白、
     快照 DPR 与目标 devicePixelRatioF 一致；
   - 结束（或 stop）后：目标还原可见、几何不变、占位 / 叠加层清理。
2. NumberRollLabel：演示播放逻辑（先 reset(0) 再 rollTo）产生中间值，
   重复播放仍能重滚（「播放无反应」回归）。
3. FlipCard：点击正面即翻转；句柄被外部 stop 后 flip() 不死锁。
4. ScrollReveal：Demo 演示卡场景（小视口、先构建后显示）滚动后
   全部子控件完全渐显（无卡住的 0 透明度效果）。

截图输出 tests/shots/fixf3_*.png（关键动画中间帧）。
任何断言失败即记录，末尾汇总，失败时退出码 1。
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
_WINDOWS = []


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


def pump(ms):
    deadline = time.monotonic() + ms / 1000.0
    while time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.004)


def keep(window):
    _WINDOWS.append(window)
    return window


def shot(widget, name):
    pm = widget.grab()
    if pm.isNull() or pm.width() < 4:
        raise AssertionError(f"{name}: grab() 失败")
    path = SHOTS / f"fixf3_{name}.png"
    if not pm.save(str(path)):
        raise AssertionError(f"{name}: 截图保存失败 {path}")


# ---------------------------------------------------------------------------
# 应用与主题准备
# ---------------------------------------------------------------------------

from PySide6.QtCore import QAbstractAnimation, QEvent, QPoint, Qt  # noqa: E402
from PySide6.QtGui import QImage  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import (  # noqa: E402
    QApplication,
    QLabel,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

app = QApplication.instance() or QApplication(sys.argv)

from InstructionX_UIKit.theme import ThemeManager, T  # noqa: E402
from InstructionX_UIKit.anim import property as A  # noqa: E402
from InstructionX_UIKit.anim import painted as P  # noqa: E402

ThemeManager.instance().set_mode("light")
ThemeManager.instance().apply(app)
SHOTS.mkdir(parents=True, exist_ok=True)

print("F3 修复验证开始（offscreen，快照叠加层 + 3 组件）")


# ---------------------------------------------------------------------------
# 宿主与断言辅助
# ---------------------------------------------------------------------------

def _make_target(color_key="primary"):
    lab = QLabel("演示")
    lab.setFixedSize(120, 60)
    lab.setAlignment(Qt.AlignCenter)
    lab.setStyleSheet(
        f"background:{T('color.' + color_key)};color:#FFFFFF;"
        "border-radius:8px;font-weight:bold;")
    return lab


def make_host(layout, color_key="primary"):
    """创建一种宿主：layout=True 为 QVBoxLayout 管理的窗口，否则绝对定位。"""
    win = keep(QWidget())
    win.resize(280, 200)
    target = _make_target(color_key)
    if layout:
        lay = QVBoxLayout(win)
        lay.addStretch(1)
        lay.addWidget(target, 0, Qt.AlignCenter)
        lay.addStretch(1)
    else:
        target.setParent(win)
        target.move(80, 70)
    win.show()
    target.show()
    pump(60)
    return win, target


def overlay_coverage(overlay):
    """叠加层快照的非透明像素占比（中间帧非空白判据）。"""
    pm = overlay.grab()
    img = pm.toImage().convertToFormat(QImage.Format_ARGB32)
    w, h = img.width(), img.height()
    if w < 2 or h < 2:
        return 0.0
    opaque = 0
    total = 0
    sx = max(1, w // 120)
    sy = max(1, h // 90)
    for y in range(0, h, sy):
        for x in range(0, w, sx):
            total += 1
            if img.pixelColor(x, y).alpha() > 10:
                opaque += 1
    return opaque / max(1, total)


def check_snap_mid(anim, target, name, dpr):
    """动画中间态公共断言：会话 / 叠加层存在、目标隐藏、画面非空白。"""
    if not isinstance(anim, QAbstractAnimation):
        raise AssertionError(f"{name}: 句柄不是动画对象")
    sessions = anim.sessions
    if not sessions or sessions[0].overlay is None:
        raise AssertionError(f"{name}: 动画期间应存在快照会话与叠加层")
    if not target.isHidden():
        raise AssertionError(f"{name}: 动画期间目标应隐藏（叠加层接管绘制）")
    overlay = sessions[0].overlay
    if abs(overlay._pm.devicePixelRatio() - dpr) > 1e-3:
        raise AssertionError(
            f"{name}: 快照 DPR 应与目标一致: "
            f"{overlay._pm.devicePixelRatio()} != {dpr}")
    cov = overlay_coverage(overlay)
    if cov < 0.02:
        raise AssertionError(f"{name}: 叠加层中间帧空白 (coverage={cov:.3f})")
    return overlay


def check_restored(target, geo0, name):
    """结束态公共断言：目标可见、几何不变、占位已清理。"""
    if not target.isVisible():
        raise AssertionError(f"{name}: 结束后目标应还原可见")
    if target.geometry() != geo0:
        raise AssertionError(
            f"{name}: 结束后几何应还原: {target.geometry()} != {geo0}")
    if getattr(target, "_uik_snap_hold", None) is not None:
        raise AssertionError(f"{name}: 结束后占位 hold 应已清理")


# ---------------------------------------------------------------------------
# 1. 15 个动画 × 两种宿主
# ---------------------------------------------------------------------------

#: (名称, 触发函数, 时长ms, 循环型?) —— 循环型验证 stop() 还原
_SNAP_CASES = [
    ("fade_in", lambda t: A.fade_in(t, duration=180), 180, False),
    ("slide_in", lambda t: A.slide_in(t, direction="left", distance=40,
                                      duration=180), 180, False),
    ("zoom_in", lambda t: A.zoom_in(t, from_scale=0.5, duration=180), 180, False),
    ("spring_pop", lambda t: A.spring_pop(t, duration=220), 220, False),
    ("badge_pop", lambda t: A.badge_pop(t, duration=220), 220, False),
    ("blur_in", lambda t: A.blur_in(t, radius=10, duration=180), 180, False),
    ("mask_reveal", lambda t: A.mask_reveal(t, direction="circle",
                                            duration=180), 180, False),
    ("pulse", lambda t: A.pulse(t, peak=1.12, duration=180), 180, False),
    ("bounce", lambda t: A.bounce(t, height=10, duration=240), 240, False),
    ("swing", lambda t: A.swing(t, angle=10, duration=240), 240, False),
    ("shake", lambda t: A.shake(t, distance=6, duration=180), 180, False),
    ("float_loop", lambda t: A.float_loop(t, dy=5, duration=320), 320, True),
    ("pulse_glow", lambda t: A.pulse_glow(t, min_blur=6, max_blur=20,
                                          duration=320), 320, True),
]

_SHOT_ANIMS = {"fade_in", "slide_in", "zoom_in", "blur_in", "mask_reveal",
               "swing", "pulse_glow", "bounce"}


@case("13 个快照动画 × 布局 / 绝对定位双宿主")
def _():
    for layout in (True, False):
        host_kind = "layout" if layout else "absolute"
        for name, trigger, dur, is_loop in _SNAP_CASES:
            tag = f"{name}[{host_kind}]"
            win, target = make_host(layout)
            geo0 = target.geometry()
            dpr = target.devicePixelRatioF()
            anim = trigger(target)
            try:
                pump(int(dur * 0.45))
                check_snap_mid(anim, target, tag, dpr)
                if name in _SHOT_ANIMS and not layout:
                    shot(win, name)
                if is_loop:
                    if anim.state() != QAbstractAnimation.Running:
                        raise AssertionError(f"{tag}: 循环动画应保持 Running")
                    anim.stop()  # 循环型：验证 stop() 还原
                    pump(40)
                else:
                    pump(dur + 200)
                    if anim.state() != QAbstractAnimation.Stopped:
                        raise AssertionError(f"{tag}: 动画应已自然结束")
                check_restored(target, geo0, tag)
            finally:
                try:
                    anim.stop()
                except Exception:  # noqa: BLE001
                    pass
                win.close()
                win.deleteLater()
                pump(15)


@case("hover_lift 悬停上浮 × 双宿主（事件驱动）")
def _():
    for layout in (True, False):
        host_kind = "layout" if layout else "absolute"
        tag = f"hover_lift[{host_kind}]"
        win, target = make_host(layout, color_key="success")
        geo0 = target.geometry()
        filt = A.hover_lift(target, dy=6, duration=120)
        try:
            QApplication.sendEvent(target, QEvent(QEvent.Enter))
            pump(180)
            overlay = filt.overlay
            if overlay is None:
                raise AssertionError(f"{tag}: Enter 后应创建抬升叠加层")
            if not target.isHidden():
                raise AssertionError(f"{tag}: 抬升期间目标应隐藏")
            if overlay.dy > -4.0:
                raise AssertionError(f"{tag}: 叠加层应上移约 6px: {overlay.dy}")
            if overlay_coverage(overlay) < 0.02:
                raise AssertionError(f"{tag}: 抬升叠加层画面空白")
            if not layout:
                shot(win, "hover_lift")
            QApplication.sendEvent(overlay, QEvent(QEvent.Leave))
            pump(240)
            if target.isHidden():
                raise AssertionError(f"{tag}: Leave 后目标应还原可见")
            if target.geometry() != geo0:
                raise AssertionError(f"{tag}: Leave 后几何应不变")
        finally:
            filt.uninstall()
            win.close()
            win.deleteLater()
            pump(15)


@case("cross_fade 两控件分支 × 双宿主")
def _():
    for layout in (True, False):
        host_kind = "layout" if layout else "absolute"
        tag = f"cross_fade(2widgets)[{host_kind}]"
        win = keep(QWidget())
        win.resize(280, 200)
        a = _make_target("primary")
        b = _make_target("danger")
        if layout:
            lay = QVBoxLayout(win)
            lay.addStretch(1)
            lay.addWidget(a, 0, Qt.AlignCenter)
            lay.addWidget(b, 0, Qt.AlignCenter)
            lay.addStretch(1)
            b.hide()
        else:
            a.setParent(win)
            a.move(80, 70)
            b.setParent(win)
            b.move(80, 70)
            b.hide()
        win.show()
        a.show()
        pump(60)
        anim = A.cross_fade(a, to=b, duration=180)
        try:
            pump(80)
            sessions = anim.sessions
            if len(sessions) != 2:
                raise AssertionError(f"{tag}: 应有 A/B 两个快照会话")
            if not a.isHidden() or not b.isHidden():
                raise AssertionError(f"{tag}: 过渡期间 A/B 均应隐藏")
            if not layout:
                shot(win, "cross_fade")
            pump(240)
            if a.isVisible():
                raise AssertionError(f"{tag}: 结束后 A 应保持隐藏（hide_source）")
            if not b.isVisible():
                raise AssertionError(f"{tag}: 结束后 B 应显示")
            if anim.sessions:
                raise AssertionError(f"{tag}: 结束后会话应清理")
        finally:
            anim.stop()
            win.close()
            win.deleteLater()
            pump(15)


@case("cross_fade / page_transition QStackedWidget 分支")
def _():
    win = keep(QWidget())
    win.resize(280, 200)
    st = QStackedWidget(win)
    st.setGeometry(40, 40, 200, 120)
    p1 = _make_target("primary")
    p2 = _make_target("success")
    st.addWidget(p1)
    st.addWidget(p2)
    win.show()
    st.show()
    pump(60)
    # cross_fade：立即切页 + 旧页快照叠加层淡出
    anim = A.cross_fade(st, index=1, duration=180)
    pump(80)
    if st.currentIndex() != 1:
        raise AssertionError("cross_fade(stacked): 应立即切到目标页")
    if not anim._overlays:
        raise AssertionError("cross_fade(stacked): 过渡期间应有旧页叠加层")
    pump(240)
    if anim._overlays:
        raise AssertionError("cross_fade(stacked): 结束后叠加层应清理")
    # page_transition slide：新页快照滑入，自然结束才切页
    anim2 = A.page_transition(st, 0, kind="slide", direction="left",
                              duration=200)
    pump(90)
    if st.currentIndex() != 1:
        raise AssertionError("page_transition(slide): 动画期间不应提前切页")
    if not anim2._overlays:
        raise AssertionError("page_transition(slide): 动画期间应有新页叠加层")
    shot(win, "page_transition_slide")
    pump(260)
    if st.currentIndex() != 0:
        raise AssertionError("page_transition(slide): 结束后应切到目标页")
    win.close()
    win.deleteLater()
    pump(15)


@case("并发与重放安全（同目标连续触发 / 中途 stop）")
def _():
    win, target = make_host(False)
    geo0 = target.geometry()
    # 同一目标连续两次 fade_in（旧会话应被 stop 还原，不泄漏）
    a1 = A.fade_in(target, duration=400)
    pump(60)
    a1.stop()
    pump(30)
    if not target.isVisible():
        raise AssertionError("stop 后目标应立即还原可见")
    a2 = A.zoom_in(target, from_scale=0.4, duration=180)
    pump(80)
    if not target.isHidden():
        raise AssertionError("重放期间目标应隐藏")
    pump(200)
    check_restored(target, geo0, "重放")
    # 双会话并发：fade_in + swing 同时进行，先结束者不得误显示目标
    b1 = A.fade_in(target, duration=160)
    b2 = A.swing(target, angle=8, duration=400)
    pump(220)  # fade_in 已结束，swing 仍在进行
    if not target.isHidden():
        raise AssertionError("并发会话：一个未结束时目标不应被还原显示")
    b2.stop()
    pump(30)
    check_restored(target, geo0, "并发结束")
    win.close()
    win.deleteLater()
    pump(15)


# ---------------------------------------------------------------------------
# 2. NumberRollLabel 播放逻辑
# ---------------------------------------------------------------------------

@case("NumberRollLabel 播放（先归零再滚）产生中间值且可重复")
def _():
    w = keep(P.NumberRollLabel(0, decimals=1, prefix="¥", duration=300))
    w.resize(240, 40)
    w.show()
    pump(60)
    for round_ in (1, 2):
        # Demo 演示卡的播放路径：reset(0) → rollTo(target)
        w.reset(0)
        if w.value() != 0.0:
            raise AssertionError("reset(0) 应立即归零")
        w.rollTo(500.0)
        pump(120)
        mid = w.value()
        if not (0.0 < mid < 500.0):
            raise AssertionError(
                f"第 {round_} 轮播放中间值应在 (0,500) 内: {mid}")
        pump(400)
        if abs(w.value() - 500.0) > 1e-6:
            raise AssertionError(f"第 {round_} 轮结束应为 500: {w.value()}")
        if w.text() != "¥500.0":
            raise AssertionError(f"终值文本格式异常: {w.text()!r}")
    # 库 API 语义：setValue == rollTo（从当前值起滚）
    w.setValue(100.0)
    pump(120)
    if not (100.0 < w.value() < 500.0):
        raise AssertionError(f"setValue 应从当前值起滚: {w.value()}")
    pump(300)


# ---------------------------------------------------------------------------
# 3. FlipCard 点击翻转 + stop 解锁
# ---------------------------------------------------------------------------

@case("FlipCard 点击翻转 / 句柄外部 stop 后仍可翻转")
def _():
    w = keep(P.FlipCard("问题面", "答案面"))
    w.resize(220, 140)
    w.show()
    pump(80)
    if w.isFlipped():
        raise AssertionError("初始应为正面")
    QTest.mouseClick(w, Qt.LeftButton, pos=w.rect().center())
    pump(620)
    if not w.isFlipped():
        raise AssertionError("点击后应翻转为背面")
    shot(w, "flipcard_back")
    QTest.mouseClick(w, Qt.LeftButton, pos=w.rect().center())
    pump(620)
    if w.isFlipped():
        raise AssertionError("再次点击应翻回正面")
    # 句柄被外部 stop（演示卡重放路径）后 flip() 不得死锁
    h1 = w.flip()
    pump(100)  # 动画进行到一半
    h1.stop()
    pump(60)
    h2 = w.flip()
    if h2 is None:
        raise AssertionError("外部 stop 后 flip() 应自动解锁并返回新句柄")
    pump(620)
    if not w.isFlipped():
        raise AssertionError("解锁后翻转应完成（背面朝上）")


# ---------------------------------------------------------------------------
# 4. ScrollReveal 演示卡场景
# ---------------------------------------------------------------------------

def _reveal_fully_shown(child):
    """完全渐显判据：无残留效果（已摘除）或打标效果 opacity==1。"""
    eff = child.graphicsEffect()
    if eff is None:
        return True
    return bool(eff.property("_uik_reveal")) and eff.opacity() >= 0.999


@case("ScrollReveal 演示卡场景（小视口 / 先构建后显示）滚动渐显")
def _():
    # 复刻 Demo 卡片构建时序：页面未 show 时先构建 ScrollReveal
    box = QWidget()
    lay = QVBoxLayout(box)
    lay.setContentsMargins(4, 4, 4, 4)
    blocks = []
    for i in range(12):
        blk = QLabel(f"内容块 {i + 1}")
        blk.setFixedHeight(56)
        blk.setStyleSheet(
            f"background:{T('color.bg.muted')};"
            f"color:{T('color.text.primary')};border-radius:6px;")
        lay.addWidget(blk)
        blocks.append(blk)
    reveal = keep(P.ScrollReveal(box, threshold=0.85))
    reveal.setMinimumSize(250, 180)
    win = keep(QWidget())
    win.resize(280, 220)
    wlay = QVBoxLayout(win)
    wlay.setContentsMargins(0, 0, 0, 0)
    wlay.addWidget(reveal)
    # 构建后延迟显示（演示页构造时序）：扫描应自动重试而非错误预隐藏
    pump(120)
    win.show()
    pump(200)
    vp_h = reveal.viewport().height()
    if vp_h < 100:
        raise AssertionError(f"视口高度异常: {vp_h}")
    # 视口外下方块此时应被预隐藏（opacity=0 的打标效果）
    below = [b for b in blocks
             if b.mapTo(reveal.viewport(), QPoint(0, 0)).y() >= vp_h]
    if not below:
        raise AssertionError("演示场景应存在视口外块")
    for b in below:
        eff = b.graphicsEffect()
        if eff is None or eff.opacity() != 0.0:
            raise AssertionError("视口外块应预隐藏为 opacity=0")
    # 播放路径：滚到底
    sb = reveal.verticalScrollBar()
    sb.setValue(sb.maximum())
    pump(600)
    for i, b in enumerate(blocks):
        if not _reveal_fully_shown(b):
            eff = b.graphicsEffect()
            raise AssertionError(
                f"滚到底后块 {i} 应完全渐显: "
                f"{None if eff is None else eff.opacity()}")
        if not b.isVisible():
            raise AssertionError(f"块 {i} 应保持逻辑可见（布局不被破坏）")
    shot(reveal, "scrollreveal_bottom")
    # 回顶：全部保持渐显完成态
    sb.setValue(0)
    pump(300)
    for i, b in enumerate(blocks):
        if not _reveal_fully_shown(b):
            raise AssertionError(f"回顶后块 {i} 应保持完全渐显")
    shot(reveal, "scrollreveal_top")


# ---------------------------------------------------------------------------
# 5. Demo 演示页集成（真实卡片路径）
# ---------------------------------------------------------------------------

@case("Demo 演示卡集成：NumberRoll / FlipCard / ScrollReveal")
def _():
    from demo.pages import anim_painted
    from demo.pages.playground import ParamCard

    page = keep(anim_painted.create_page())
    page.resize(1120, page.sizeHint().height() + 40)
    page.show()
    pump(400)
    cards = page.findChildren(ParamCard)
    number_card = flip_card = reveal_card = None
    for c in cards:
        if isinstance(c.demo, P.NumberRollLabel):
            number_card = c
        elif isinstance(c.demo, P.FlipCard):
            flip_card = c
        elif isinstance(c.demo, P.ScrollReveal):
            reveal_card = c
    if number_card is None or flip_card is None or reveal_card is None:
        raise AssertionError("演示卡缺失")
    # NumberRoll：自动播放已滚到目标；点「播放」必须重新从 0 滚出中间值
    w = number_card.demo
    pump(700)  # 等自动播放到终值
    number_card.replay()
    pump(150)
    target_val = number_card.opts["target"]
    if not (0.0 < w.value() < target_val):
        raise AssertionError(
            f"演示卡播放应产生中间值（修复前恒等于目标值）: {w.value()}")
    pump(700)
    # FlipCard：点击演示卡正面即翻转
    fc = flip_card.demo
    QTest.mouseClick(fc, Qt.LeftButton, pos=fc.rect().center())
    pump(620)
    if not fc.isFlipped():
        raise AssertionError("演示卡 FlipCard 点击应翻转")
    # ScrollReveal：播放滚动后全部完全渐显
    reveal_card.replay()
    pump(700)
    rv = reveal_card.demo
    content = rv.widget()
    kids = content.findChildren(QWidget, options=Qt.FindDirectChildrenOnly)
    for i, b in enumerate(kids):
        if not _reveal_fully_shown(b):
            raise AssertionError(f"演示卡 ScrollReveal 块 {i} 未完全渐显")
    page.hide()


# ---------------------------------------------------------------------------
# 汇总
# ---------------------------------------------------------------------------

def main() -> int:
    print("-" * 64)
    for w in _WINDOWS:
        try:
            w.close()
            w.deleteLater()
        except RuntimeError:
            pass
    pump(50)
    if _FAILURES:
        print(f"共 {len(_FAILURES)} 项失败: {_FAILURES}")
        return 1
    print(f"全部检查通过，截图目录: {SHOTS}")
    print("0 错误，0 段错误")
    return 0


if __name__ == "__main__":
    sys.exit(main())
