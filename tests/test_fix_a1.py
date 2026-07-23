# -*- coding: utf-8 -*-
"""A1 修复验证：动画「播放」叠加层错位 / 污染相邻卡片。

直接运行（无 pytest 依赖）::

    QT_QPA_PLATFORM=offscreen python tests/test_fix_a1.py

背景（真机 Windows 复现）：动画 · 属性页点击某张动画卡的「播放」，
动画快照叠加层却映射 / 叠加到其他动画卡的显示区域上。根因有二：

1. demo/pages/anim_property.py ``_cards()`` 中 14 张卡片的播放回调写成
   裸捕获 ``lambda o: A.<preset>(t, **o)``——``t`` 是 ``_cards`` 内被反复
   重新赋值的局部变量（Python 闭包晚绑定），函数执行完 ``t`` 指向最后
   一次赋值（breathing 卡的色块），导致上述卡片的动画会话全部落在
   breathing 卡的演示区上。修复为默认参数绑定 ``lambda o, t=t: ...``。
2. anim/property.py 快照叠加层 ``_SnapshotOverlay`` / 占位 ``_TargetHold``
   spacer 未做透明加固：主题全局 QSS 基座规则
   ``QWidget { background-color: <bg.base> }`` 可把普通 QWidget 刷成
   不透明底色块，叠加层外扩 margin 区域变成盖住相邻卡片的实心矩形。
   修复为 ``WA_TranslucentBackground`` + ``setAutoFillBackground(False)``
   + 实例级 ``background: transparent``（见 ``_force_transparent``）。

本测试构造真实 demo 动画页（demo.pages.anim_property.create_page），断言：

A. 点击第 1 张卡「播放」，动画会话 target 属于第 1 张卡自己的 stage
   （而非其他卡）；并逐一回归全部曾被晚绑定波及的卡片。
B. 叠加层 parent == target.parentWidget()，geometry == 目标在父坐标系
   的 rect 外扩 margin（逐像素相等）。
C. 叠加层透明底座：WA_TranslucentBackground / 非 autoFillBackground /
   实例级 transparent 样式表；播放期间叠加层矩形内、快照内容外的
   margin 带像素保持页面原貌。
D. 整页逐像素 diff：fade_in 播放期间变化掩码只允许落在第 1 张卡
   区域内（相邻卡演示区逐像素不变）。
E. 全部走叠加层的动画（fade_in / slide_in / zoom_in / spring_pop /
   badge_pop / blur_in / mask_reveal / pulse / bounce / swing / shake /
   float_loop / pulse_glow / cross_fade / hover_lift）逐一做
   「污染范围」断言：变化掩码 ⊆ 叠加层矩形（映射到页面坐标）。

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


# ---------------------------------------------------------------------------
# 引导：QApplication + 主题（全局 QSS 基座规则是根因之一，必须应用）
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

from PySide6.QtCore import QElapsedTimer, QEvent, QPoint, QRect, Qt  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

import numpy as np  # noqa: E402

from InstructionX_UIKit.anim.property import _SnapshotOverlay  # noqa: E402
from demo.pages.anim_property import create_page  # noqa: E402
from demo.pages.playground import ParamCard  # noqa: E402


def pump(ms: int) -> None:
    """驱动事件循环 ms 毫秒。"""
    app = QApplication.instance()
    timer = QElapsedTimer()
    timer.start()
    while timer.elapsed() < ms:
        app.processEvents()
        time.sleep(0.004)


def snap(widget) -> "np.ndarray":
    """grab 控件为 (H, W, 4) uint8 数组（RGBA8888，逐像素可比较）。"""
    from PySide6.QtGui import QImage

    img = widget.grab().toImage().convertToFormat(QImage.Format_RGBA8888)
    w, h = img.width(), img.height()
    arr = np.frombuffer(img.bits(), np.uint8, count=h * w * 4)
    return arr.reshape(h, w, 4).copy()


def changed_mask(before: "np.ndarray", during: "np.ndarray"):
    """逐像素变化掩码 + 变化像素数。"""
    if before.shape != during.shape:
        raise AssertionError(f"前后快照尺寸不一致: {before.shape} vs {during.shape}")
    mask = np.any(before != during, axis=2)
    return mask, int(mask.sum())


def rect_of(widget, ancestor) -> QRect:
    """widget 矩形映射到 ancestor 坐标系。"""
    return QRect(widget.mapTo(ancestor, QPoint(0, 0)), widget.size())


def mask_outside(mask, rect: QRect, tol: int = 0) -> int:
    """掩码中落在 rect（外扩 tol）之外的像素数。"""
    h, w = mask.shape
    ys, xs = np.nonzero(mask)
    if len(ys) == 0:
        return 0
    x0 = max(0, rect.x() - tol)
    y0 = max(0, rect.y() - tol)
    x1 = min(w, rect.x() + rect.width() + tol)
    y1 = min(h, rect.y() + rect.height() + tol)
    outside = (xs < x0) | (xs >= x1) | (ys < y0) | (ys >= y1)
    return int(outside.sum())


def card_of(widget, cards):
    """沿父链找 widget 所属的 ParamCard。"""
    w = widget
    while w is not None:
        if isinstance(w, ParamCard):
            return w
        w = w.parentWidget()
    return None


def stop_handle(h) -> None:
    """停止动画 / 过滤器句柄（hover_lift 过滤器 stop 别名 uninstall）。"""
    if h is None:
        return
    try:
        h.stop()
    except Exception:  # noqa: BLE001
        pass


# ---------------------------------------------------------------------------
# 构建真实 demo 页
# ---------------------------------------------------------------------------

_PAGE = create_page()
_PAGE.resize(1120, 2600)
_PAGE.show()
pump(300)
_CONTENT = _PAGE.widget()  # QScrollArea 的内容根（整页 grab）
_CARDS = _PAGE.findChildren(ParamCard)
assert len(_CARDS) == 28, f"demo 页应有 28 张卡，实际 {len(_CARDS)}"

#: 曾被闭包晚绑定波及的卡片索引（播放回调裸捕获 t）
_LATE_BOUND_CARDS = [0, 2, 3, 4, 5, 7, 8, 9, 13, 14, 15, 16, 18, 19, 20]

#: 走快照叠加层的动画：索引 -> (名称, 是否 hover 过滤器)
_OVERLAY_CARDS = [
    (0, "fade_in", False),
    (2, "slide_in", False),
    (3, "zoom_in", False),
    (4, "spring_pop", False),
    (5, "badge_pop", False),
    (7, "blur_in", False),
    (8, "mask_reveal", False),
    (13, "pulse", False),
    (14, "bounce", False),
    (15, "swing", False),
    (16, "shake", False),
    (18, "float_loop", False),
    (19, "pulse_glow", False),
    (23, "cross_fade", False),
    (9, "hover_lift", True),
]


def _target_of(card, handle):
    """从句柄取动画目标：快照会话 target 或 hover 过滤器 _target。"""
    sessions = getattr(handle, "sessions", None)
    if sessions:
        return sessions[0].target
    tgt = getattr(handle, "_target", None)  # _HoverLiftFilter
    if tgt is not None:
        return tgt
    return None


def _overlays_of(card, handle):
    """从句柄取 [(overlay, 参照目标)]：会话叠加层 + 游离叠加层 + hover 叠加层。"""
    out = []
    for s in getattr(handle, "sessions", None) or []:
        if s.overlay is not None:
            out.append((s.overlay, s.target))
    for ov in getattr(handle, "_overlays", None) or []:  # cross_fade 游离叠加层
        out.append((ov, None))
    ov = getattr(handle, "overlay", None)  # _HoverLiftFilter.overlay 属性
    if isinstance(ov, _SnapshotOverlay):
        out.append((ov, getattr(handle, "_target", None)))
    return out


# ---------------------------------------------------------------------------
# A. 点击播放，动画落在本卡（闭包晚绑定回归）
# ---------------------------------------------------------------------------

@case("A1 点击第 1 张卡「播放」：会话 target 属于第 1 张卡的 stage")
def _():
    card = _CARDS[0]
    card.opts["duration"] = 3000
    card.play_button.click()  # 真实点击路径（clicked -> replay）
    pump(60)
    h = card.handle
    if h is None or not getattr(h, "sessions", None):
        raise AssertionError("第 1 张卡播放后无快照会话")
    tgt = h.sessions[0].target
    if tgt.parentWidget() is not card.demo:
        raise AssertionError(
            f"会话 target 的 stage 不是本卡 demo: target={tgt}, "
            f"其父={tgt.parentWidget()}, 本卡 stage={card.demo}")
    if card_of(tgt, _CARDS) is not card:
        raise AssertionError("会话 target 不属于第 1 张卡")
    if not tgt.isHidden():
        raise AssertionError("播放期间目标应被快照会话隐藏")
    stop_handle(h)
    pump(60)
    if tgt.isHidden():
        raise AssertionError("stop 后目标未还原可见")


@case("A2 全部曾被晚绑定波及的卡片：播放均落在本卡")
def _():
    bad = []
    for idx in _LATE_BOUND_CARDS:
        card = _CARDS[idx]
        card.opts["duration"] = 1200
        h = card.replay()
        pump(30)
        tgt = _target_of(card, h)
        if tgt is None:
            bad.append((idx, "无动画目标"))
        elif card_of(tgt, _CARDS) is not card:
            bad.append((idx, f"动画落到其他卡: {card_of(tgt, _CARDS)}"))
        stop_handle(h)
        pump(30)
    if bad:
        raise AssertionError(f"仍有卡片动画错位: {bad}")


# ---------------------------------------------------------------------------
# B / C. 叠加层几何精确 + 透明底座（污染范围 sweep，覆盖全部叠加层动画）
# ---------------------------------------------------------------------------

@case("B/C/E 全部叠加层动画：几何 == 目标±margin、透明底座、污染 ⊆ 叠加层矩形")
def _():
    problems = []
    for idx, name, is_hover in _OVERLAY_CARDS:
        card = _CARDS[idx]
        card.opts["duration"] = 2000
        before = snap(_CONTENT)
        h = card.replay()
        if is_hover:  # hover_lift 需要 Enter 事件触发抬升
            tgt0 = _target_of(card, h)
            QApplication.sendEvent(tgt0, QEvent(QEvent.Enter))
        pump(400)  # 推进到 ~20% 进度（动画确在播放中）
        pairs = _overlays_of(card, h)
        if not pairs:
            problems.append(f"{name}: 播放期间无叠加层")
            stop_handle(h)
            pump(40)
            continue
        during = snap(_CONTENT)
        mask, nchanged = changed_mask(before, during)
        if nchanged == 0:
            problems.append(f"{name}: 播放期间整页无任何像素变化（动画未渲染）")
        for ov, tgt in pairs:
            # B. 父对象与几何（父坐标系，含 margin 外扩）
            if tgt is not None:
                if ov.parentWidget() is not tgt.parentWidget():
                    problems.append(f"{name}: 叠加层 parent != target.parentWidget()")
                m = ov._margin
                expect = tgt.geometry().adjusted(-m, -m, m, m)
                if ov.geometry() != expect:
                    problems.append(
                        f"{name}: 叠加层几何 {ov.geometry()} != 目标±margin {expect}")
            # C. 透明底座
            if not ov.testAttribute(Qt.WA_TranslucentBackground):
                problems.append(f"{name}: 叠加层未设 WA_TranslucentBackground")
            if ov.autoFillBackground():
                problems.append(f"{name}: 叠加层 autoFillBackground 未关闭")
            if "transparent" not in ov.styleSheet():
                problems.append(f"{name}: 叠加层缺少实例级 transparent 样式表")
            # E. 污染范围：变化掩码 ⊆ 叠加层矩形（页面坐标，2px 容差）
            orect = rect_of(ov, _CONTENT)
            n_out = mask_outside(mask, orect, tol=2)
            if n_out > 0:
                problems.append(
                    f"{name}: {n_out} 个变化像素落在叠加层矩形 {orect} 之外")
        stop_handle(h)
        pump(60)
    if problems:
        raise AssertionError("; ".join(problems))


# ---------------------------------------------------------------------------
# D. fade_in 播放期间：相邻卡演示区逐像素不变 + margin 带保持页面原貌
# ---------------------------------------------------------------------------

@case("D 点击第 1 张卡 fade_in：变化仅落在本卡，相邻卡与 margin 带像素不变")
def _():
    card = _CARDS[0]
    card.opts["duration"] = 3000
    before = snap(_CONTENT)
    card.play_button.click()
    pump(400)
    h = card.handle
    if h is None or not getattr(h, "sessions", None):
        raise AssertionError("播放后无快照会话")
    sess = h.sessions[0]
    tgt, ov = sess.target, sess.overlay
    during = snap(_CONTENT)
    mask, nchanged = changed_mask(before, during)
    if nchanged < 100:
        raise AssertionError(f"fade_in 播放期间变化像素过少（{nchanged}），动画疑似未渲染")

    # 变化掩码只允许落在本卡区域内
    crect = rect_of(card, _CONTENT)
    n_out = mask_outside(mask, crect)
    if n_out > 0:
        raise AssertionError(f"{n_out} 个变化像素落在本卡区域 {crect} 之外")

    # 相邻卡（同排第 2、3 张 + 下一排第 4 张）演示区逐像素不变
    for nb in (1, 2, 3):
        nrect = rect_of(_CARDS[nb], _CONTENT)
        sub = mask[nrect.y():nrect.y() + nrect.height(),
                   nrect.x():nrect.x() + nrect.width()]
        if int(sub.sum()) > 0:
            raise AssertionError(f"相邻卡 {nb} 区域有 {int(sub.sum())} 个像素被污染")

    # margin 带（叠加层矩形内、快照内容外）保持页面原貌
    orect = rect_of(ov, _CONTENT)
    trect = rect_of(tgt, _CONTENT)
    m = ov._margin
    if m < 1:
        raise AssertionError("fade_in 叠加层 margin 应 >= 1")
    band = mask[orect.y():orect.y() + orect.height(),
                orect.x():orect.x() + orect.width()].copy()
    inner = QRect(trect.x() - orect.x(), trect.y() - orect.y(),
                  trect.width(), trect.height())
    band[inner.y():inner.y() + inner.height(),
         inner.x():inner.x() + inner.width()] = False
    if int(band.sum()) > 0:
        raise AssertionError(f"margin 带内有 {int(band.sum())} 个像素被改变（应为透明）")

    stop_handle(h)
    pump(80)
    after = snap(_CONTENT)
    mask2, n2 = changed_mask(before, after)
    if n2 > 0:
        raise AssertionError(f"stop 还原后整页仍有 {n2} 个像素与播放前不一致")


# ---------------------------------------------------------------------------
# 汇总
# ---------------------------------------------------------------------------

def main() -> int:
    print("-" * 64)
    try:
        _PAGE.close()
        _PAGE.deleteLater()
    except RuntimeError:
        pass
    pump(50)
    if _FAILURES:
        print(f"共 {len(_FAILURES)} 项失败: {_FAILURES}")
        return 1
    print("全部检查通过")
    print("0 错误，0 段错误")
    return 0


if __name__ == "__main__":
    sys.exit(main())
