# -*- coding: utf-8 -*-
"""fix/anim-pages 审计固化测试：动画两页 52 卡逐卡断言。

直接运行（无 pytest 依赖）::

    QT_QPA_PLATFORM=offscreen python tests/test_fix_animpages.py

覆盖（亮 / 暗主题各一轮，共 104 卡次）：

1. 初始渲染非空白（演示区 grab 后至少 2 种颜色）；
2. 点击「播放」动画进行中画面非空白，且播放回调不抛异常
   （ParamCard.replay 会吞异常，测试用包装器重新抛出记录）；
3. 连续两次「播放」旧动画句柄必须被 stop（防叠加 / 泄漏）；
4. 逐个调整每个参数：opts 快照必须写回新值（接线断言），
   自绘页演示控件必须按新参数重建（控件 identity 变化）；
5. 复位后再次「播放」画面仍非空白、无异常；
6. 专项回归：ripple 参数（时长 / 不透明度）调整后重放，
   新装的事件过滤器必须携带新参数（存量过滤器返回 bug 回归）。

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

_FAILURES = []


def fail(msg):
    _FAILURES.append(msg)
    print(f"  [失败] {msg}")


# ---------------------------------------------------------------------------
# 引导
# ---------------------------------------------------------------------------

from PySide6.QtCore import QAbstractAnimation  # noqa: E402
from PySide6.QtGui import QImage  # noqa: E402
from PySide6.QtWidgets import QApplication, QLabel  # noqa: E402

app = QApplication.instance() or QApplication([])

from InstructionX_UIKit.theme import ThemeManager  # noqa: E402

ThemeManager.instance().apply(app)

from demo.pages import anim_painted, anim_property  # noqa: E402
from demo.pages.playground import ParamCard  # noqa: E402


def pump(ms):
    """推进事件循环 ms 毫秒（动画按墙钟推进，与动画进度同步）。"""
    t0 = time.monotonic()
    while (time.monotonic() - t0) * 1000 < ms:
        app.processEvents()
        time.sleep(0.004)


def distinct_colors(widget):
    """演示区 grab 后的采样颜色数（<=1 视为空白）。"""
    pm = widget.grab()
    img = pm.toImage().convertToFormat(QImage.Format_RGB32)
    w, h = img.width(), img.height()
    if w < 2 or h < 2:
        return 0
    colors = set()
    sx = max(1, w // 80)
    sy = max(1, h // 60)
    for y in range(0, h, sy):
        for x in range(0, w, sx):
            colors.add(img.pixel(x, y) & 0xFFFFFF)
            if len(colors) > 4:
                return len(colors)
    return len(colors)


def title_of(card):
    lab = card.findChild(QLabel)
    return lab.text() if lab else "?"


def _sweep_params(card, tag, opts, is_painted):
    """逐个调整每个参数并断言接线 / 重建生效。"""
    demo_before = card.demo
    for entry in card.form._entries:
        c = entry["control"]
        kind = entry["kind"]
        if kind in ("int", "float"):
            spin = c.spin if kind == "int" else c
            cur = spin.value()
            spin.setValue(spin.minimum() if cur != spin.minimum()
                          else spin.maximum())
        elif kind == "choice":
            c.setCurrentIndex((c.currentIndex() + 1) % max(1, c.count()))
        elif kind == "bool":
            c.setChecked(not c.isChecked())
        elif kind == "text":
            c.setText("审计文本")
        pump(15)
        if opts is not None:
            key = entry["key"]
            val = card.form.values().get(key)
            if opts.get(key) != val:
                fail(f"{tag}: 参数 {key} 未写回 opts "
                     f"(opts={opts.get(key)!r} form={val!r})")
    if is_painted and card.demo is demo_before:
        fail(f"{tag}: 参数调整后演示控件未按新参数重建")


def _check_ripple(card, tag):
    """专项：ripple 调参后重放必须安装携带新参数的过滤器。"""
    from InstructionX_UIKit.components.button import Button

    btn = card.demo.findChild(Button) if card.demo is not None else None
    if btn is None:
        fail(f"{tag}: 未找到演示按钮")
        return
    dur = card.form.controls.get("duration")
    opa = card.form.controls.get("max_opacity")
    if dur is None or opa is None:
        fail(f"{tag}: 参数控件缺失")
        return
    dur.setValue(1000)
    card.replay()
    filt = getattr(btn, "_uik_ripple", None)
    if filt is None or getattr(filt, "_duration", None) != 1000:
        fail(f"{tag}: 调时长重放后过滤器参数未更新 "
             f"(filt={filt!r} duration={getattr(filt, '_duration', None)!r})")
    opa.setValue(0.8)
    card.replay()
    filt = getattr(btn, "_uik_ripple", None)
    if filt is None or abs(getattr(filt, "_max_opacity", 0) - 0.8) > 1e-6:
        fail(f"{tag}: 调不透明度重放后过滤器参数未更新 "
             f"(max_opacity={getattr(filt, '_max_opacity', None)!r})")


def audit_card(card, tag, is_painted):
    errs = []
    orig_play = card._play

    def wrapped(_o=orig_play, _errs=errs):
        try:
            return _o()
        except Exception:
            _errs.append(traceback.format_exc())
            raise

    card.set_play(wrapped)
    host = card._demo_host
    try:
        # 1 初始渲染
        pump(120)
        n0 = distinct_colors(host)
        if n0 < 2:
            fail(f"{tag}: 初始渲染空白 (distinct={n0})")
        # 2 播放（连续两次，旧句柄必须停止）
        card.replay()
        h1 = card.handle
        errs.clear()
        card.replay()
        pump(90)
        n1 = distinct_colors(host)
        if n1 < 2:
            fail(f"{tag}: 播放中画面空白 (distinct={n1})")
        if errs:
            fail(f"{tag}: 播放抛异常 {errs[-1].splitlines()[-1]}")
        if (h1 is not None and h1 is not card.handle
                and isinstance(h1, QAbstractAnimation)
                and h1.state() != QAbstractAnimation.Stopped):
            fail(f"{tag}: 重复播放旧动画句柄未停止（动画叠加泄漏）")
        # 3 参数逐个调整
        opts = getattr(card, "opts", None)
        _sweep_params(card, tag, opts, is_painted)
        # 4 复位 + 重放
        card.form.reset()
        pump(30)
        errs.clear()
        card.replay()
        pump(90)
        n2 = distinct_colors(host)
        if n2 < 2:
            fail(f"{tag}: 调参重放后画面空白 (distinct={n2})")
        if errs:
            fail(f"{tag}: 调参重放抛异常 {errs[-1].splitlines()[-1]}")
        # 5 专项回归
        if tag.split("/")[-1].startswith("ripple"):
            _check_ripple(card, tag)
    except Exception:
        fail(f"{tag}: 审计自身异常 {traceback.format_exc(limit=2)}")
    finally:
        card.set_play(orig_play)


def audit_page(name, page, is_painted):
    cards = page.findChildren(ParamCard)
    print(f"  == {name}: {len(cards)} 张卡片")
    page.resize(1120, page.sizeHint().height() + 40)
    page.show()
    pump(300)
    for card in cards:
        audit_card(card, f"{name}/{title_of(card)}", is_painted)
    page.hide()
    return len(cards)


def main():
    total = 0
    for mode in ("light", "dark"):
        ThemeManager.instance().set_mode(mode)
        print(f"#### 主题 = {mode}")
        p1 = anim_property.create_page()
        total += audit_page("property", p1, is_painted=False)
        p1.deleteLater()
        p2 = anim_painted.create_page()
        total += audit_page("painted", p2, is_painted=True)
        p2.deleteLater()
        pump(100)
    ThemeManager.instance().set_mode("light")
    print()
    if total != 2 * (28 + 24):
        fail(f"卡片总数异常: {total}（期望 104 = 52 × 2 主题）")
    if _FAILURES:
        print(f"共 {len(_FAILURES)} 项失败：")
        for f in _FAILURES:
            print(" -", f)
        return 1
    print(f"全部通过（52 卡 × 2 主题，共 {total} 卡次）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
