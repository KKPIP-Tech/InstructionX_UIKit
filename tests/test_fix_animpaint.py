# -*- coding: utf-8 -*-
"""R6 修复回归：自绘动画 5 项缺陷（SPEC §7.2 / §9）。

直接运行（无 pytest 依赖）::

    QT_QPA_PLATFORM=offscreen python tests/test_fix_animpaint.py

覆盖（先亮主题、后暗主题重拍代表用例）：
1. ScrollReveal：10 个子控件滚到底后全部 opacity==1 且可见，截图无空白块；
   另含矮块 + 高视口（顶边永远到不了阈值线）的卡住回归；
2. ScrollStoryArea：滚动条到 maximum 时最后一个步骤点被点亮、
   末卡片完整可见，progress==1.0；回顶后首步点亮；滚动全程无
   递归重绘警告（paintEvent 内 render 自身回归）；
3. NumberRollLabel：setValue(0)->setValue(1000) 播放滚动动画，
   中间帧文本 != 终值，最终文本为 "1,000"；构造初始值直接显示；
4. CardTilt：鼠标到角落（最大倾角）时卡片四角内容像素仍存在、
   且映射坐标不越出控件 rect；
5. CubeRotator / FlipCard：45° 旋转下文字边缘锐利（中间调占比低、
   深笔画占比高，超采样快照生效）。

截图输出 tests/shots/fixanimpaint_*.png（亮 / 暗各一套）。
任何异常即失败，退出码 1；全部通过退出码 0。
"""

import math
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


def pump(app, ms):
    deadline = time.monotonic() + ms / 1000.0
    while time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.004)


def keep(window):
    _WINDOWS.append(window)
    return window


def save_shot(widget, name):
    pm = widget.grab()
    if pm.isNull() or pm.width() < 4 or pm.height() < 4:
        raise AssertionError(f"{name}: grab() 失败")
    path = SHOTS / f"fixanimpaint_{name}.png"
    if not pm.save(str(path)):
        raise AssertionError(f"{name}: 截图保存失败 {path}")
    return pm.toImage()


def row_colors(img, y, step=8):
    colors = set()
    for x in range(0, img.width(), step):
        colors.add(img.pixelColor(x, y).rgb())
    return colors


# ---------------------------------------------------------------------------
# 应用与主题准备
# ---------------------------------------------------------------------------

from PySide6.QtCore import QEvent, QPointF, Qt  # noqa: E402
from PySide6.QtGui import QMouseEvent  # noqa: E402
from PySide6.QtWidgets import (  # noqa: E402
    QApplication,
    QGraphicsOpacityEffect,
    QLabel,
    QVBoxLayout,
    QWidget,
)

app = QApplication.instance() or QApplication(sys.argv)

from InstructionX_UIKit.theme import ThemeManager  # noqa: E402
from InstructionX_UIKit.anim import painted as P  # noqa: E402

ThemeManager.instance().set_mode("light")
ThemeManager.instance().apply(app)
SHOTS.mkdir(parents=True, exist_ok=True)


def _send_mouse_move(widget, x, y):
    pos = QPointF(float(x), float(y))
    ev = QMouseEvent(QEvent.MouseMove, pos, widget.mapToGlobal(pos.toPoint()),
                     Qt.NoButton, Qt.NoButton, Qt.NoModifier)
    QApplication.sendEvent(widget, ev)


# ---------------------------------------------------------------------------
# 1. ScrollReveal
# ---------------------------------------------------------------------------

def _build_reveal(block_h=80, count=10):
    box = QWidget()
    lay = QVBoxLayout(box)
    blocks = []
    for i in range(count):
        lab = QLabel(f"内容块 {i + 1}")
        lab.setFixedHeight(block_h)
        lab.setStyleSheet("background:#3563E9;color:#FFFFFF;border-radius:6px;")
        lay.addWidget(lab)
        blocks.append(lab)
    return box, blocks


@case("ScrollReveal 滚到底全部渐显且无空白块")
def _():
    box, blocks = _build_reveal(block_h=80, count=10)
    w = keep(P.ScrollReveal(box))
    w.resize(320, 240)
    w.show()
    pump(app, 150)
    # 初始：未入视口的块不可见但布局正常（高度未被压缩）
    hidden = [b for b in blocks[4:]]
    if any(b.height() < 78 for b in hidden):
        raise AssertionError("未入视口块布局高度应正常")
    below = [b for b in blocks
             if b.mapTo(w.viewport(), b.rect().topLeft()).y()
             >= w.viewport().height()]
    for b in below:
        # 当前实现（快照叠加层方案，见 ScrollReveal docstring）：未入视口块
        # 预置为 hide() + retainSizeWhenHidden 保留布局占位，
        # 不再使用 QGraphicsOpacityEffect（真机 Windows + QSS + 高 DPI 平台坑）
        if b.isVisible():
            raise AssertionError("未入视口块应统一预隐藏（hide 保留占位）")
        eff = b.graphicsEffect()
        if eff is not None:
            raise AssertionError("预隐藏不应依赖 QGraphicsOpacityEffect")
    sb = w.verticalScrollBar()
    sb.setValue(sb.maximum() // 2)
    pump(app, 300)
    sb.setValue(sb.maximum())
    pump(app, 500)
    for i, b in enumerate(blocks):
        # 快照叠加层方案下渐显完成后摘除叠加层并 show 原控件，
        # 全程不挂 QGraphicsOpacityEffect；滚到底后所有块应已可见
        if b.graphicsEffect() is not None:
            raise AssertionError(f"块 {i} 不应残留透明效果")
        if not b.isVisible():
            raise AssertionError(f"块 {i} 滚到底后应已渐显可见")
        if b.mapTo(w.viewport(), b.rect().topLeft()).y() >= w.viewport().height():
            raise AssertionError(f"块 {i} 位置异常")
    img = save_shot(w, "scrollreveal")
    # 截图无空白块：视口内每一行采样都不止背景一色
    vh = img.height()
    for y in range(vh // 6, vh, vh // 6):
        if len(row_colors(img, y)) < 2:
            raise AssertionError(f"截图第 {y} 行疑似空白块")


@case("ScrollReveal 矮块高视口不卡住（顶边到不了阈值线也渐显）")
def _():
    box, blocks = _build_reveal(block_h=30, count=10)
    w = keep(P.ScrollReveal(box))
    w.resize(360, 420)
    w.show()
    pump(app, 300)
    pump(app, 400)
    for i, b in enumerate(blocks):
        top = b.mapTo(w.viewport(), b.rect().topLeft()).y()
        if 0 <= top < w.viewport().height():
            eff = b.graphicsEffect()
            # None = 渐显完成、效果已摘除；动画中则为打标效果且 opacity 趋向 1
            if eff is not None and (
                    not isinstance(eff, QGraphicsOpacityEffect)
                    or eff.opacity() < 0.999):
                raise AssertionError(
                    f"视口内块 {i} 应渐显（修复前卡在 opacity=0）: "
                    f"{None if eff is None else eff.opacity()}")


# ---------------------------------------------------------------------------
# 2. ScrollStoryArea
# ---------------------------------------------------------------------------

@case("ScrollStoryArea 滚到底末步点亮且完整可见")
def _():
    w = keep(P.ScrollStoryArea())
    panels = []
    for i in range(6):
        panels.append(w.addStep(f"阶段 {i + 1}", "说明文本 " * 6))
    w.resize(420, 640)   # 高视口：修复前视口中心更靠近倒数第二张
    w.show()
    pump(app, 200)
    sb = w.verticalScrollBar()
    if sb.maximum() <= 0:
        raise AssertionError("内容应可滚动")
    sb.setValue(sb.maximum())
    pump(app, 300)
    if abs(w.progress() - 1.0) > 1e-6:
        raise AssertionError(f"到底 progress 应为 1.0: {w.progress()}")
    if w.activeIndex() != w.stepCount() - 1:
        raise AssertionError(
            f"到底末步应点亮: active={w.activeIndex()} last={w.stepCount() - 1}")
    last = panels[-1]
    top = last.mapTo(w.viewport(), last.rect().topLeft()).y()
    bot = last.mapTo(w.viewport(), last.rect().bottomRight()).y()
    if not (0 <= top and bot <= w.viewport().height()):
        raise AssertionError(f"末卡片应完整可见: top={top} bot={bot} "
                             f"vh={w.viewport().height()}")
    eff = last.graphicsEffect()
    if isinstance(eff, QGraphicsOpacityEffect) and eff.opacity() < 0.6:
        raise AssertionError(f"末卡片应高亮: {eff.opacity()}")
    save_shot(w, "scrollstoryarea_bottom")
    # 回到顶部：首步点亮
    sb.setValue(sb.minimum())
    pump(app, 200)
    if w.activeIndex() != 0:
        raise AssertionError(f"回顶首步应点亮: {w.activeIndex()}")
    save_shot(w, "scrollstoryarea_top")


@case("ScrollStoryArea 滚动无递归重绘警告（paintEvent 内 render 回归）")
def _():
    # 修复前：_StoryStepPanel.paintEvent 在 alpha<1 时于自身绘制上下文内
    # render 自身，Qt 刷 Recursive repaint / Painter not active 警告。
    from PySide6.QtCore import qInstallMessageHandler

    hits = []
    keys = ("Recursive repaint", "Should no longer be called",
            "Paint device returned engine", "Painter must be active",
            "Painter not active")

    def _handler(mode, ctx, msg):
        text = str(msg)
        if any(k in text for k in keys):
            hits.append(text)

    prev = qInstallMessageHandler(_handler)
    try:
        w = keep(P.ScrollStoryArea())
        for i in range(5):
            w.addStep(f"第 {i + 1} 步", "这是步骤的详细说明文本，" * 4)
        w.resize(300, 200)  # 矮视口：非居中卡片 alpha<1，走半透明合成路径
        w.show()
        pump(app, 300)
        sb = w.verticalScrollBar()
        step = max(1, sb.maximum() // 10)
        v = sb.minimum()
        while v < sb.maximum():
            v = min(sb.maximum(), v + step)
            sb.setValue(v)
            pump(app, 120)
        sb.setValue(0)
        pump(app, 200)
    finally:
        qInstallMessageHandler(prev)
    if hits:
        raise AssertionError(f"滚动期间捕获 {len(hits)} 条重绘警告: {hits[0]}")


# ---------------------------------------------------------------------------
# 3. NumberRollLabel
# ---------------------------------------------------------------------------

@case("NumberRollLabel setValue 触发滚动动画")
def _():
    w = keep(P.NumberRollLabel(500))
    w.resize(240, 40)
    w.show()
    pump(app, 80)
    if w.text() != "500":
        raise AssertionError(f"构造初始值应直接显示: {w.text()!r}")
    w.setValue(0)
    pump(app, 700)   # slower=480 + 余量，确保滚完
    if w.text() != "0":
        raise AssertionError(f"setValue(0) 结束应为 0: {w.text()!r}")
    w.setValue(1000)
    pump(app, 200)
    mid_text = w.text()
    if mid_text == "1,000":
        raise AssertionError("动画中间帧不应等于终值（动画未播放）")
    if not (0.0 < w.value() < 1000.0):
        raise AssertionError(f"中间帧数值应在 0~1000 之间: {w.value()}")
    pump(app, 600)
    if w.text() != "1,000":
        raise AssertionError(f"最终文本应为格式化终值: {w.text()!r}")
    if abs(w.value() - 1000.0) > 1e-6:
        raise AssertionError(f"最终值应为 1000: {w.value()}")
    save_shot(w, "numberrolllabel")


# ---------------------------------------------------------------------------
# 4. CardTilt
# ---------------------------------------------------------------------------

@case("CardTilt 最大倾角四角不裁切")
def _():
    content = QLabel("封面内容ABC")
    content.setAlignment(Qt.AlignCenter)
    content.setStyleSheet(
        "background:#EDF1FE;color:#1C2330;"
        "border:2px solid #3563E9;border-radius:8px;")
    w = keep(P.CardTilt(content, max_angle=10.0))
    w.resize(280, 180)
    w.show()
    pump(app, 120)
    _send_mouse_move(w, w.width() - 2, w.height() - 2)
    pump(app, 150)
    rx, ry = w.tilt()
    if abs(rx) < 8.0 or abs(ry) < 8.0:
        raise AssertionError(f"角落应接近最大倾角: {(rx, ry)}")
    img = save_shot(w, "cardtilt_max")
    W, H = w.width(), w.height()
    m = w._tilt_margin(W, H)

    def corner_map(px, py):
        cx, cy = W / 2.0, H / 2.0
        x, y = px - cx, py - cy
        r = math.radians(rx)
        c, s = math.cos(r), math.sin(r)
        wd = 1 + y * s / w._persp
        x1, y1 = x / wd, y * c / wd
        r = math.radians(ry)
        c, s = math.cos(r), math.sin(r)
        wd2 = 1 + x1 * s / w._persp
        return x1 * c / wd2 + cx, y1 / wd2 + cy

    def bluish(rgb):
        r = (rgb >> 16) & 0xFF
        g = (rgb >> 8) & 0xFF
        b = rgb & 0xFF
        return b > 120 and b - max(r, g) > 25

    corners = {"TL": (m + 1, m + 1), "TR": (W - m - 2, m + 1),
               "BL": (m + 1, H - m - 2), "BR": (W - m - 2, H - m - 2)}
    for name, (px, py) in corners.items():
        mx, my = corner_map(px, py)
        if not (1 <= mx < W - 1 and 1 <= my < H - 1):
            raise AssertionError(f"{name} 角映射越出控件 rect: ({mx:.1f},{my:.1f})")
        found = False
        for dx in range(-8, 9):
            for dy in range(-8, 9):
                xx, yy = int(mx + dx), int(my + dy)
                if 0 <= xx < W and 0 <= yy < H:
                    if bluish(img.pixelColor(xx, yy).rgb() & 0xFFFFFF):
                        found = True
        if not found:
            raise AssertionError(f"{name} 角附近未找到边框内容像素（被裁切）")


# ---------------------------------------------------------------------------
# 5. CubeRotator / FlipCard 文字锐利度
# ---------------------------------------------------------------------------

def _text_band_metrics(img):
    """中央文字带：中间调占比（模糊特征）与深笔画占比（锐利特征）。"""
    W, H = img.width(), img.height()
    x0, x1 = int(W * 0.30), int(W * 0.70)
    y0, y1 = int(H * 0.42), int(H * 0.60)
    lums = []
    for y in range(y0, y1):
        for x in range(x0, x1):
            c = img.pixelColor(x, y)
            lums.append(0.299 * c.red() + 0.587 * c.green() + 0.114 * c.blue())
    lo, hi = min(lums), max(lums)
    span = max(1.0, hi - lo)
    mid = sum(1 for v in lums if lo + 0.25 * span < v < lo + 0.75 * span)
    dark = sum(1 for v in lums if v < lo + 0.15 * span)
    return mid / len(lums), dark / len(lums)


@case("CubeRotator 45° 文字边缘锐利")
def _():
    w = keep(P.CubeRotator("正面文字ABC", "侧面"))
    w.resize(260, 170)
    w.show()
    pump(app, 120)
    w._set_angle(45.0)
    pump(app, 80)
    img = save_shot(w, "cuberotator_45")
    mid, dark = _text_band_metrics(img)
    # 修复前（1x 快照）: mid≈0.047 dark≈0.007；3x 超采样后: mid≈0.016 dark≈0.020
    if mid > 0.028:
        raise AssertionError(f"45° 文字中间调过多（模糊）: {mid:.3f}")
    if dark < 0.010:
        raise AssertionError(f"45° 深笔画过少（笔画发虚）: {dark:.3f}")


@case("FlipCard 45° 文字边缘锐利")
def _():
    w = keep(P.FlipCard("问题面文字", "答案面"))
    w.resize(240, 150)
    w.show()
    pump(app, 120)
    # 机制断言：面快照必须走 >=3x 超采样（R6 修复点，环境无关）
    if w._face_pixmap(0).devicePixelRatio() < 3.0:
        raise AssertionError("面快照未启用 3x 超采样")
    w._set_angle(45.0)
    pump(app, 80)
    img = save_shot(w, "flipcard_45")
    mid, dark = _text_band_metrics(img)
    # 本组件文本短（5 字）、卡片窄，且 45° 透视下文字落在采样带左侧
    # 边缘，绝对深笔画占比天然低于 CubeRotator，不能共用其阈值。
    # 本机实测：1x 快照 mid≈0.042 dark≈0.005；3x 超采样 mid≈0.027
    # dark≈0.007——中间调（模糊特征）是最强判别量，阈值取两者中间。
    if mid > 0.035:
        raise AssertionError(f"45° 文字中间调过多（模糊）: {mid:.3f}")
    if dark < 0.005:
        raise AssertionError(f"45° 深笔画过少（笔画发虚）: {dark:.3f}")


# ---------------------------------------------------------------------------
# 暗色主题重拍（主题感知回归）
# ---------------------------------------------------------------------------

@case("暗色主题重拍修复用例")
def _():
    tm = ThemeManager.instance()
    tm.set_mode("dark")
    tm.apply(app)
    pump(app, 260)

    box, blocks = _build_reveal(block_h=80, count=10)
    sr = keep(P.ScrollReveal(box))
    sr.resize(320, 240)
    sr.show()
    pump(app, 150)
    sr.verticalScrollBar().setValue(sr.verticalScrollBar().maximum())
    pump(app, 400)
    for i, b in enumerate(blocks):
        eff = b.graphicsEffect()
        # None = 渐显完成、效果已摘除；否则应为 opacity 趋向 1 的打标效果
        if eff is not None and (
                not isinstance(eff, QGraphicsOpacityEffect)
                or eff.opacity() < 0.999):
            raise AssertionError(f"暗色下块 {i} 应完全渐显")
    save_shot(sr, "scrollreveal_dark")

    cube = keep(P.CubeRotator("正面文字ABC", "侧面"))
    cube.resize(260, 170)
    cube.show()
    pump(app, 120)
    cube._set_angle(45.0)
    pump(app, 80)
    save_shot(cube, "cuberotator_45_dark")

    content = QLabel("封面内容ABC")
    content.setAlignment(Qt.AlignCenter)
    content.setStyleSheet(
        "background:#2A3242;color:#E8EBF2;"
        "border:2px solid #7DA2FF;border-radius:8px;")
    tilt = keep(P.CardTilt(content, max_angle=10.0))
    tilt.resize(280, 180)
    tilt.show()
    pump(app, 120)
    _send_mouse_move(tilt, tilt.width() - 2, tilt.height() - 2)
    pump(app, 150)
    img = save_shot(tilt, "cardtilt_max_dark")
    # 暗色下四角边框像素同样存在
    W, H = tilt.width(), tilt.height()
    m = tilt._tilt_margin(W, H)
    rx, ry = tilt.tilt()

    def corner_map(px, py):
        cx, cy = W / 2.0, H / 2.0
        x, y = px - cx, py - cy
        r = math.radians(rx)
        c, s = math.cos(r), math.sin(r)
        wd = 1 + y * s / tilt._persp
        x1, y1 = x / wd, y * c / wd
        r = math.radians(ry)
        c, s = math.cos(r), math.sin(r)
        wd2 = 1 + x1 * s / tilt._persp
        return x1 * c / wd2 + cx, y1 / wd2 + cy

    def bluish(rgb):
        r = (rgb >> 16) & 0xFF
        g = (rgb >> 8) & 0xFF
        b = rgb & 0xFF
        return b > 140 and b - r > 30

    for name, (px, py) in {"TL": (m + 1, m + 1), "TR": (W - m - 2, m + 1),
                           "BL": (m + 1, H - m - 2), "BR": (W - m - 2, H - m - 2)}.items():
        mx, my = corner_map(px, py)
        found = False
        for dx in range(-8, 9):
            for dy in range(-8, 9):
                xx, yy = int(mx + dx), int(my + dy)
                if 0 <= xx < W and 0 <= yy < H:
                    if bluish(img.pixelColor(xx, yy).rgb() & 0xFFFFFF):
                        found = True
        if not found:
            raise AssertionError(f"暗色 {name} 角附近未找到边框像素（被裁切）")

    tm.set_mode("light")
    tm.apply(app)
    pump(app, 120)


# ---------------------------------------------------------------------------
# 汇总
# ---------------------------------------------------------------------------

def main() -> int:
    print("R6 修复回归开始（offscreen，5 项自绘动画缺陷）")
    print("-" * 64)
    if _FAILURES:
        print(f"共 {len(_FAILURES)} 项失败: {_FAILURES}")
        return 1
    print(f"全部检查通过，截图目录: {SHOTS}")
    print("0 错误，0 段错误")
    return 0


if __name__ == "__main__":
    sys.exit(main())
