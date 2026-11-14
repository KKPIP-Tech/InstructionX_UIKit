# -*- coding: utf-8 -*-
"""动画快照、阴影资源上界与固定帧像素回归。"""

import argparse
import os
import sys
import time
import traceback
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QEvent
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication, QFrame, QLabel

from InstructionX_UIKit.anim import CardTilt, FlipCard, ScrollStoryArea
from InstructionX_UIKit.anim.property import _SnapshotOverlay, _grab_pixmap
from InstructionX_UIKit.theme import ThemeManager, apply_shadow

app = QApplication.instance() or QApplication(sys.argv)
tm = ThemeManager.instance()
tm.set_mode("light")
tm.apply(app)
_FAILURES = []
_IMAGES = {}


def pump(ms):
    deadline = time.monotonic() + ms / 1000
    while time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.003)


def keep_image(widget, name):
    _IMAGES[name] = widget.grab().toImage().convertToFormat(QImage.Format_RGBA8888)


def case(name):
    def decorate(function):
        try:
            function()
            print(f"  [通过] {name}")
        except Exception:
            _FAILURES.append(name)
            print(f"  [失败] {name}")
            traceback.print_exc()
        return function
    return decorate


@case("隐藏叙事卡片不重抓快照，恢复后像素一致")
def _():
    area = ScrollStoryArea()
    area.addStep("第一步", "隐藏时不得产生快照工作。")
    area.addStep("第二步", "恢复后重新抓取当前主题。")
    area.resize(380, 260)
    area.show()
    pump(180)
    keep_image(area, "story_visible")
    area.hide()
    calls = []
    for panel in area._steps:
        original = panel.render
        panel.render = lambda *args, original=original: calls.append(1) or original(*args)
    tm.set_mode("dark")
    tm.set_mode("light")
    pump(150)
    assert not calls, f"隐藏期间仍执行 {len(calls)} 次快照 render"
    assert all(not panel._capture_timer.isActive() for panel in area._steps)
    area.show()
    pump(180)
    keep_image(area, "story_restored")
    area.close()
    area.deleteLater()


@case("倾斜卡片尺寸缓存有界且固定角度像素稳定")
def _():
    card = CardTilt(QLabel("倾斜内容"))
    for index in range(16):
        card.resize(280 + index * 3, 190 + index * 2)
        card.show()
        pump(10)
        card._tilt_margin(card.width(), card.height())
    assert len(card._margin_cache) <= 1, f"尺寸缓存无界: {len(card._margin_cache)}"
    card.resize(280, 190)
    card._set_tilt(4.0, -3.0)
    pump(30)
    keep_image(card, "tilt_fixed")
    card.close()
    card.deleteLater()


@case("相同阴影参数复用效果对象")
def _():
    frame = QFrame()
    frame.setProperty("role", "card")
    frame.resize(180, 90)
    frame.show()
    apply_shadow(frame, "sm")
    first = frame.graphicsEffect()
    for _index in range(24):
        apply_shadow(frame, "sm")
    assert frame.graphicsEffect() is first, "同参数阴影不应重新创建效果对象"
    assert len(frame.findChildren(type(first))) == 1
    pump(40)
    keep_image(frame, "shadow")
    frame.close()
    frame.deleteLater()


@case("叠加层模糊缓存有界且固定帧像素稳定")
def _():
    target = QLabel("快照固定帧")
    target.resize(160, 80)
    target.show()
    pump(20)
    overlay = _SnapshotOverlay(target, _grab_pixmap(target), margin=12)
    for radius in range(1, 130):
        overlay.blur = float(radius)
        overlay.grab()
    assert len(overlay._blur_cache) <= 8, f"模糊缓存超界: {len(overlay._blur_cache)}"
    overlay.blur = 3.5
    overlay.opacity = 0.65
    overlay.scale = 1.04
    keep_image(overlay, "snapshot_fixed")
    overlay.deleteLater()
    target.close()
    target.deleteLater()


@case("翻转固定进度像素稳定")
def _():
    card = FlipCard("问题面", "答案面")
    card.resize(240, 150)
    card.show()
    pump(20)
    animation = card.flip()
    animation.setCurrentTime(animation.duration() // 2)
    animation.stop()
    pump(20)
    keep_image(card, "flip_fixed")
    card.close()
    card.deleteLater()


def verify_images(capture, baseline):
    if capture:
        baseline.mkdir(parents=True, exist_ok=True)
        for name, image in _IMAGES.items():
            if not image.save(str(baseline / f"{name}.png")):
                raise AssertionError(f"无法保存基线: {name}")
        return
    if not baseline.is_dir():
        raise AssertionError(f"缺少不可变图像基线: {baseline}")
    assert set(_IMAGES) == {path.stem for path in baseline.glob("*.png")}
    for name, image in _IMAGES.items():
        reference = QImage(str(baseline / f"{name}.png")).convertToFormat(
            QImage.Format_RGBA8888)
        assert reference.size() == image.size() and reference == image, f"固定帧像素差异: {name}"


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline", type=Path,
                        default=ROOT / "temp" / "animation_resources_baseline")
    parser.add_argument("--capture-baseline", action="store_true")
    args = parser.parse_args()
    app.sendPostedEvents(None, QEvent.DeferredDelete)
    try:
        verify_images(args.capture_baseline, args.baseline)
    except Exception:
        _FAILURES.append("固定帧图像核对")
        traceback.print_exc()
    raise SystemExit(1 if _FAILURES else 0)
