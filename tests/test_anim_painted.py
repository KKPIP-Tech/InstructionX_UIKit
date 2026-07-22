# -*- coding: utf-8 -*-
"""anim-B 代理自测：自绘 / 定时器类动画预设（SPEC §7.2 / §9）。

直接运行（无 pytest 依赖）::

    QT_QPA_PLATFORM=offscreen python tests/test_anim_painted.py

覆盖：
- offscreen 下实例化 SPEC §7.2 全部 24 个类各 1 次；
- 触发各自的动画入口（click / start / flip / rotate / next / 滚动等），
  推进事件循环约 800ms；
- 每个类 grab() 截图到 tests/shots/animpaint_<name>.png；
- 采样断言截图非空白、非全黑（去重色数 >= 2）；
- 交互断言：MagneticButton 磁吸位移与弹回、HorizontalScrollStrip 自动滚动、
  TypewriterLabel 逐字推进、NumberRollLabel 滚动到目标值、
  FlipCard / CubeRotator 翻面、CoverFlow 切换 currentChanged；
- 暗色主题重拍 4 个代表控件并与亮色截图比对像素差异；
- 任何异常即失败，退出码 1；全部通过退出码 0。
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
_WINDOWS = []   # 保活所有顶层窗口
_SHOTS = {}     # name -> QImage（亮主题），供暗色比对


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
    """推进事件循环约 ms 毫秒（不阻塞退出，模拟真实运行）。"""
    deadline = time.monotonic() + ms / 1000.0
    while time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.004)


def keep(window):
    _WINDOWS.append(window)
    return window


def shot(widget, name):
    """grab() 截图保存到 tests/shots/animpaint_<name>.png 并做非空白断言。"""
    pm = widget.grab()
    if pm.isNull() or pm.width() < 4 or pm.height() < 4:
        raise AssertionError(f"{name}: grab() 失败或尺寸异常 {pm.width()}x{pm.height()}")
    path = SHOTS / f"animpaint_{name}.png"
    if not pm.save(str(path)):
        raise AssertionError(f"{name}: 截图保存失败 {path}")
    if path.stat().st_size < 200:
        raise AssertionError(f"{name}: 截图过小疑似空白 {path.stat().st_size}B")
    img = pm.toImage()
    w, h = img.width(), img.height()
    colors = set()
    step_x, step_y = max(1, w // 12), max(1, h // 12)
    for x in range(0, w, step_x):
        for y in range(0, h, step_y):
            colors.add(img.pixelColor(x, y).rgb())
    if len(colors) < 2:
        raise AssertionError(f"{name}: 采样只有 {len(colors)} 种颜色，疑似空白")
    if colors == {0xFF000000}:
        raise AssertionError(f"{name}: 截图全黑")
    _SHOTS[name] = img
    return img


# ---------------------------------------------------------------------------
# 应用与主题准备
# ---------------------------------------------------------------------------

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication.instance() or QApplication(sys.argv)

from InstructionX_UIKit.theme import ThemeManager  # noqa: E402
from InstructionX_UIKit.anim import painted as P  # noqa: E402

ThemeManager.instance().set_mode("light")
ThemeManager.instance().apply(app)
SHOTS.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# 24 个类逐一实例化 + 截图
# ---------------------------------------------------------------------------

@case("SpinnerArc 旋转圈")
def _():
    w = keep(P.SpinnerArc(size=36))
    w.show()
    pump(app, 300)
    if not w.isRunning():
        raise AssertionError("SpinnerArc 应在旋转中")
    shot(w, "spinnerarc")


@case("LikeBurstButton 点赞爆裂")
def _():
    w = keep(P.LikeBurstButton(size=48))
    w.show()
    pump(app, 60)
    w.click()
    if not w.isChecked():
        raise AssertionError("点击后应为已点赞状态")
    pump(app, 260)   # 粒子飞行中
    shot(w, "likeburstbutton")
    pump(app, 600)   # 粒子寿命结束，定时器应收起
    if w._particles:
        raise AssertionError("粒子应已清空")


@case("MagneticButton 磁吸按钮")
def _():
    from PySide6.QtCore import QPoint
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QVBoxLayout, QWidget

    win = keep(QWidget())
    win.resize(320, 180)
    lay = QVBoxLayout(win)
    btn = P.MagneticButton("磁吸按钮")
    lay.addStretch(1)
    lay.addWidget(btn, 0)
    lay.addStretch(1)
    win.show()
    pump(app, 120)
    center = btn.mapTo(win, btn.rect().center())
    near = QPoint(center.x() + 26, center.y() + 10)
    QTest.mouseMove(win, near)
    pump(app, 240)
    off = btn.offset
    dist = (off.x() ** 2 + off.y() ** 2) ** 0.5
    if dist < 0.8:
        raise AssertionError(f"磁吸位移未生效: {off}")
    if dist > 9.5:
        raise AssertionError(f"磁吸位移超过上限: {dist}")
    shot(win, "magneticbutton")
    # 鼠标移远 -> 应弹回
    QTest.mouseMove(win, QPoint(6, 6))
    pump(app, 600)
    off = btn.offset
    if (off.x() ** 2 + off.y() ** 2) ** 0.5 > 1.5:
        raise AssertionError(f"离开后应弹回原位: {off}")


@case("CheckDraw 对勾描绘")
def _():
    w = keep(P.CheckDraw(size=48))
    w.show()
    w.start()
    pump(app, 500)   # DURATION.slow=320 + 余量
    if w.progress() < 0.99:
        raise AssertionError(f"描绘应已完成: {w.progress()}")
    shot(w, "checkdraw")
    w.reset()
    if w.progress() != 0.0:
        raise AssertionError("reset 后进度应为 0")


@case("BouncingDots 跳动的点")
def _():
    w = keep(P.BouncingDots(count=3, diameter=8))
    w.show()
    pump(app, 320)
    shot(w, "bouncingdots")


@case("SkeletonShimmer 骨架屏微光")
def _():
    w = keep(P.SkeletonShimmer())
    w.resize(300, 100)
    w.show()
    pump(app, 420)
    shot(w, "skeletonshimmer")


@case("Shimmer 区域微光")
def _():
    w = keep(P.Shimmer())
    w.resize(220, 72)
    w.show()
    pump(app, 400)
    shot(w, "shimmer")


@case("ProgressStriped 条纹流动进度条")
def _():
    w = keep(P.ProgressStriped(value=30, height=12))
    w.resize(260, 12)
    w.show()
    w.animateTo(78)
    pump(app, 460)
    if not (60.0 < w.value() <= 78.5):
        raise AssertionError(f"animateTo 未到达目标: {w.value()}")
    shot(w, "progressstriped")


@case("ParallaxArea 视差滚动容器")
def _():
    from PySide6.QtWidgets import QLabel

    w = keep(P.ParallaxArea())
    w.resize(320, 220)
    factors = (0.2, 0.55, 0.9)
    for i, f in enumerate(factors):
        lab = QLabel(f"视差图层 {i + 1}（factor={f}）")
        lab.setAlignment(Qt.AlignCenter)
        lab.setStyleSheet("background:#3563E9;color:#FFFFFF;border-radius:6px;")
        w.addLayer(lab, factor=f, height=72)
    w.show()
    pump(app, 120)
    sb = w.verticalScrollBar()
    if sb.maximum() <= 0:
        raise AssertionError("内容高度不足，无法滚动")
    sb.setValue(sb.maximum() // 2)
    pump(app, 200)
    # 视差断言：慢层偏移量应大于快层
    v = sb.value()
    ys = [layer.y() for layer, _base, _f in w._layers]
    bases = [base for _w2, base, _f2 in w._layers]
    offsets = [y - b for y, b in zip(ys, bases)]
    if not (offsets[0] > offsets[1] > offsets[2] >= 0):
        raise AssertionError(f"视差位移不符合 factor 排序: {offsets} (v={v})")
    shot(w, "parallaxarea")


@case("ScrollReveal 进入视口渐显")
def _():
    from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget
    from PySide6.QtWidgets import QGraphicsOpacityEffect

    box = QWidget()
    lay = QVBoxLayout(box)
    blocks = []
    for i in range(12):
        lab = QLabel(f"内容块 {i + 1}")
        lab.setFixedHeight(64)
        lab.setStyleSheet("background:#EDF1FE;border-radius:6px;")
        lay.addWidget(lab)
        blocks.append(lab)
    w = keep(P.ScrollReveal(box))
    w.resize(320, 240)
    w.show()
    pump(app, 150)
    sb = w.verticalScrollBar()
    sb.setValue(sb.maximum() // 2)
    pump(app, 400)
    sb.setValue(sb.maximum())
    pump(app, 400)
    # 底部块已滚入视口，应已渐显；渐显完成后效果被摘除（恢复原生渲染），
    # 因此 None 代表已完成渐显，动画中则为 opacity 趋向 1 的打标效果
    last_eff = blocks[-1].graphicsEffect()
    if last_eff is not None:
        if not isinstance(last_eff, QGraphicsOpacityEffect):
            raise AssertionError("底部块应安装了透明效果")
        if last_eff.opacity() < 0.5:
            raise AssertionError(f"底部块应已渐显: {last_eff.opacity()}")
    shot(w, "scrollreveal")


@case("HorizontalScrollStrip 横向滚动条带")
def _():
    items = ["设计", "令牌", "组件", "动画", "布局", "主题", "画廊", "图表"]
    w = keep(P.HorizontalScrollStrip(items, step=2))
    w.resize(420, 46)
    # offscreen 虚拟光标固定在 (0,0)，把窗口挪开避免误判悬停暂停
    w.move(900, 700)
    w.show()
    pump(app, 200)
    sb = w.horizontalScrollBar()
    if sb.maximum() <= 0:
        raise AssertionError("条带内容应超出视口")
    v0 = sb.value()
    pump(app, 400)
    v1 = sb.value()
    if v1 == v0:
        raise AssertionError("自动滚动未生效")
    shot(w, "horizontalscrollstrip")


@case("StickyHeader 粘性固定头")
def _():
    from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

    w = keep(P.StickyHeader())
    header = QLabel("  粘性章节头")
    header.setStyleSheet("background:#3563E9;color:#FFFFFF;font-weight:bold;")
    w.setHeaderWidget(header)
    body = QWidget()
    lay = QVBoxLayout(body)
    for i in range(24):
        lay.addWidget(QLabel(f"正文行 {i + 1}"))
    w.setBody(body, cover_height=90)
    w.resize(340, 240)
    w.show()
    pump(app, 120)
    sb = w.verticalScrollBar()
    sb.setValue(0)
    pump(app, 100)
    y_before = header.y()
    sb.setValue(160)   # 超过封面高度，头部应吸附到 y=0
    pump(app, 150)
    if header.y() != 0:
        raise AssertionError(f"吸附后头部 y 应为 0: {header.y()}")
    if y_before < 0:
        raise AssertionError("初始头部不应为负坐标")
    shot(w, "stickyheader")


@case("ScrollProgressBar 滚动进度条")
def _():
    from PySide6.QtWidgets import QLabel, QScrollArea, QVBoxLayout, QWidget

    area = QWidget()
    # 先建一个可滚动区域
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    content = QWidget()
    lay = QVBoxLayout(content)
    for i in range(30):
        lay.addWidget(QLabel(f"行 {i + 1}"))
    scroll.setWidget(content)
    scroll.resize(320, 200)
    keep(scroll).show()
    w = keep(P.ScrollProgressBar(scroll, height=6))
    w.resize(320, 6)
    w.show()
    pump(app, 120)
    sb = scroll.verticalScrollBar()
    sb.setValue(sb.maximum() // 2)
    pump(app, 150)
    if not (0.4 < w.value() < 0.6):
        raise AssertionError(f"进度应约为 0.5: {w.value()}")
    sb.setValue(sb.maximum())
    pump(app, 120)
    if w.value() < 0.99:
        raise AssertionError(f"到底应为 1.0: {w.value()}")
    shot(w, "scrollprogressbar")


@case("ScrollStoryArea 滚动叙事")
def _():
    w = keep(P.ScrollStoryArea())
    for i in range(5):
        w.addStep(f"第 {i + 1} 步", f"这是步骤 {i + 1} 的详细说明文本，" * 4)
    w.resize(380, 260)
    w.show()
    pump(app, 150)
    sb = w.verticalScrollBar()
    if sb.maximum() <= 0:
        raise AssertionError("内容应可滚动")
    sb.setValue(sb.maximum() // 2)
    pump(app, 200)
    if not (0.2 < w.progress() < 0.8):
        raise AssertionError(f"进度异常: {w.progress()}")
    if w.activeIndex() < 0:
        raise AssertionError("应有激活步骤")
    shot(w, "scrollstoryarea")
    if w.stepCount() != 5:
        raise AssertionError("步骤数应为 5")


@case("MarqueeLabel 跑马灯")
def _():
    w = keep(P.MarqueeLabel("跑马灯：这是一条很长很长需要循环滚动展示的中文公告文本"))
    w.resize(240, 26)
    w.show()
    pump(app, 1300)   # 含起始停顿 900ms + 滚动一段
    if w._offset <= 0:
        raise AssertionError("跑马灯应已开始滚动")
    shot(w, "marqueelabel")


@case("FluidBackground 流体渐变背景")
def _():
    w = keep(P.FluidBackground())
    w.resize(480, 270)
    w.show()
    pump(app, 350)
    shot(w, "fluidbackground")


@case("TypewriterLabel 打字机")
def _():
    w = keep(P.TypewriterLabel(interval=40))
    w.resize(360, 30)
    w.show()
    w.start("打字机效果：中文逐字输出测试")
    pump(app, 260)
    mid = w.text()
    if not (0 < len(mid.strip()) < len("打字机效果：中文逐字输出测试") + 1):
        raise AssertionError(f"中途文本异常: {mid!r}")
    pump(app, 900)
    if w.text() != "打字机效果：中文逐字输出测试":
        raise AssertionError(f"打完应为全文: {w.text()!r}")
    shot(w, "typewriterlabel")


@case("TextDecodeLabel 文字解码")
def _():
    w = keep(P.TextDecodeLabel("解码完成的目标文本", step=40))
    w.resize(320, 30)
    w.show()
    w.start()
    pump(app, 220)
    mid = w.text()
    if mid == "解码完成的目标文本":
        raise AssertionError("解码中途不应已是全文")
    if not mid:
        raise AssertionError("解码中途不应为空")
    pump(app, 1200)
    if w.text() != "解码完成的目标文本":
        raise AssertionError(f"解码结束应为全文: {w.text()!r}")
    shot(w, "textdecodelabel")


@case("NumberRollLabel 数字滚动")
def _():
    w = keep(P.NumberRollLabel(0, decimals=2, prefix="¥"))
    w.resize(240, 40)
    w.show()
    w.rollTo(1024.50)
    pump(app, 200)
    if not (0.0 < w.value() < 1024.50):
        raise AssertionError(f"滚动中途值异常: {w.value()}")
    pump(app, 600)
    if abs(w.value() - 1024.50) > 1e-6:
        raise AssertionError(f"结束应为 1024.50: {w.value()}")
    if w.text() != "¥1,024.50":
        raise AssertionError(f"文本格式异常: {w.text()!r}")
    shot(w, "numberrolllabel")


@case("LetterStaggerLabel 逐字进场")
def _():
    w = keep(P.LetterStaggerLabel("逐字进场效果", stagger=50))
    w.resize(280, 44)
    w.show()
    pump(app, 800)   # 8 字 * 50 + 320 ≈ 720ms
    shot(w, "letterstaggerlabel")
    if not w._done:
        raise AssertionError("逐字进场应已完成")


@case("CardTilt 卡片倾斜")
def _():
    from PySide6.QtCore import QEvent, QPointF
    from PySide6.QtGui import QMouseEvent
    from PySide6.QtWidgets import QLabel

    content = QLabel("封面内容")
    content.setAlignment(Qt.AlignCenter)
    content.setStyleSheet("background:#EDF1FE;color:#1C2330;border:1px solid #3563E9;border-radius:8px;")
    w = keep(P.CardTilt(content))
    w.resize(280, 180)
    w.show()
    pump(app, 120)
    # offscreen 多窗口堆叠时窗口系统命中不稳定，直接投递事件给控件
    pos = QPointF(w.width() * 0.85, w.height() * 0.2)
    ev = QMouseEvent(QEvent.MouseMove, pos, w.mapToGlobal(pos.toPoint()),
                     Qt.NoButton, Qt.NoButton, Qt.NoModifier)
    QApplication.sendEvent(w, ev)
    pump(app, 150)
    rx, ry = w.tilt()
    if abs(rx) < 0.5 and abs(ry) < 0.5:
        raise AssertionError(f"倾斜未生效: {(rx, ry)}")
    shot(w, "cardtilt")


@case("CubeRotator 立方体旋转")
def _():
    w = keep(P.CubeRotator("正面 A", "侧面 B"))
    w.resize(260, 170)
    w.show()
    pump(app, 100)
    if w.rotate() is None:
        raise AssertionError("rotate() 应返回动画句柄")
    pump(app, 700)   # slower=480 + 余量
    if w.face() != 1:
        raise AssertionError(f"旋转后应为侧面: {w.face()}")
    shot(w, "cuberotator")


@case("FlipCard 翻转卡片")
def _():
    w = keep(P.FlipCard("问题面", "答案面"))
    w.resize(240, 150)
    w.show()
    pump(app, 100)
    events = []
    w.flipped.connect(events.append)
    if w.flip() is None:
        raise AssertionError("flip() 应返回动画句柄")
    pump(app, 700)
    if not w.isFlipped():
        raise AssertionError("翻转后应为背面朝上")
    if events != [True]:
        raise AssertionError(f"flipped 信号异常: {events}")
    shot(w, "flipcard")


@case("CoverFlow 立体轮播")
def _():
    w = keep(P.CoverFlow(["设计", "组件", "动画", "布局", "主题"]))
    w.resize(560, 300)
    w.show()
    pump(app, 100)
    events = []
    w.currentChanged.connect(events.append)
    w.next()
    pump(app, 500)
    if w.currentIndex() != 1 or events != [1]:
        raise AssertionError(f"next 后应为第 2 项: {w.currentIndex()} {events}")
    w.slideTo(3)
    pump(app, 500)
    if w.currentIndex() != 3:
        raise AssertionError(f"slideTo(3) 异常: {w.currentIndex()}")
    shot(w, "coverflow")


# ---------------------------------------------------------------------------
# 暗色主题抽查：4 个代表控件重拍并与亮色比对
# ---------------------------------------------------------------------------

@case("暗色主题重拍与像素差异比对")
def _():
    tm = ThemeManager.instance()
    tm.set_mode("dark")
    tm.apply(app)
    pump(app, 260)

    probes = {
        "spinnerarc": P.SpinnerArc(size=36),
        "fluidbackground": P.FluidBackground(),
        "coverflow": P.CoverFlow(["设计", "组件", "动画", "布局", "主题"]),
        "letterstaggerlabel": P.LetterStaggerLabel("逐字进场效果", stagger=40),
    }
    probes["fluidbackground"].resize(480, 270)
    probes["coverflow"].resize(560, 300)
    probes["letterstaggerlabel"].resize(280, 44)
    for w in probes.values():
        keep(w).show()
    pump(app, 700)

    for name, w in probes.items():
        pm = w.grab()
        path = SHOTS / f"animpaint_{name}_dark.png"
        if not pm.save(str(path)):
            raise AssertionError(f"{name} 暗色截图保存失败")
        dark_img = pm.toImage()
        light_img = _SHOTS.get(name)
        if light_img is None or light_img.size() != dark_img.size():
            continue
        # 亮暗截图必须存在像素差异（主题真实生效）
        w_, h_ = dark_img.width(), dark_img.height()
        diffs = 0
        for x in range(0, w_, max(1, w_ // 16)):
            for y in range(0, h_, max(1, h_ // 16)):
                if dark_img.pixelColor(x, y).rgb() != light_img.pixelColor(x, y).rgb():
                    diffs += 1
        if diffs == 0:
            raise AssertionError(f"{name} 亮暗截图完全一致，主题未生效")

    tm.set_mode("light")
    tm.apply(app)
    pump(app, 120)


# ---------------------------------------------------------------------------
# 汇总
# ---------------------------------------------------------------------------

def main() -> int:
    print("anim-B 自测开始（offscreen，24 个自绘/定时器类动画预设）")
    print("-" * 64)
    # 用例在装饰器执行时已运行完毕，这里仅汇总
    if _FAILURES:
        print(f"共 {len(_FAILURES)} 项失败: {_FAILURES}")
        return 1
    print(f"全部 {24 + 1} 项检查通过，截图目录: {SHOTS}")
    print("0 错误，0 段错误")
    return 0


if __name__ == "__main__":
    sys.exit(main())
