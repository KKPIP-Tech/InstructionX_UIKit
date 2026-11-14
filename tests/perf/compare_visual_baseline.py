# -*- coding: utf-8 -*-
"""原始源码与候选源码的确定性视觉 A/B；不使用 worktree，不改变业务数据。"""

import argparse
import hashlib
import inspect
import json
import os
from pathlib import Path
import random
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
ORIGINAL_SHA = "949b7288a50b6ed5beed744db3c8bf46a13c00ef"
SEED = 20261114


def capture(args):
    source = args.source.resolve()
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    os.environ["QT_QPA_FONTDIR"] = r"C:\Windows\Fonts"
    os.environ["PYTHONIOENCODING"] = "utf-8"
    sys.path.insert(0, str(source))

    from PySide6.QtCore import QAbstractAnimation, QEvent, QTimer
    from PySide6.QtGui import QImage
    from PySide6.QtWidgets import QApplication, QWidget
    from shiboken6 import isValid

    app = QApplication.instance() or QApplication(sys.argv)
    original_start = QTimer.start

    def frozen_start(timer, *timer_args):
        frame = inspect.currentframe().f_back
        for _ in range(16):
            if frame is None:
                break
            module = frame.f_globals.get("__name__", "")
            if module == "InstructionX_UIKit.anim.painted" \
                    or module.startswith("demo.pages.anim_"):
                return None
            frame = frame.f_back
        return original_start(timer, *timer_args)

    QTimer.start = frozen_start
    window = None
    try:
        from InstructionX_UIKit.components.math_render import MathRenderHub
        from InstructionX_UIKit.mermaid import MermaidRenderHub
        from InstructionX_UIKit.theme import ThemeManager
        from demo.main_window import MainWindow

        theme = ThemeManager.instance()
        theme.set_mode(args.mode)
        theme.apply(app)

        def pump(milliseconds):
            deadline = time.monotonic() + milliseconds / 1000
            while time.monotonic() < deadline:
                app.processEvents()
                time.sleep(0.004)

        def finish_streams():
            for timer in window.findChildren(QTimer):
                parent = timer.parent()
                if not isValid(timer) or not timer.isActive() \
                        or timer.interval() != 40 \
                        or type(parent).__name__ != "MarkdownView":
                    continue
                for _ in range(10000):
                    if not isValid(timer) or not timer.isActive():
                        break
                    timer.timeout.emit()
                if isValid(timer) and timer.isActive():
                    raise AssertionError("流式 Markdown 未能在有限步骤内完成")

        def async_pending():
            math = MathRenderHub.instance()
            mermaid = MermaidRenderHub.instance()
            if math._pending or mermaid._pending:
                return True
            for viewer in window.findChildren(QWidget):
                if type(viewer).__name__ != "MermaidView":
                    continue
                if viewer._web is not None and not viewer._web_ready:
                    return True
                poll = viewer._poll_timer
                if poll is not None and isValid(poll) and poll.isActive():
                    return True
            return False

        def wait_async():
            deadline = time.monotonic() + 20
            while async_pending():
                if time.monotonic() >= deadline:
                    raise AssertionError("公式或 Mermaid 异步内容未在 20 秒内稳定")
                pump(20)
            pump(40)

        def complete_animations():
            for animation in window.findChildren(QAbstractAnimation):
                if not isValid(animation):
                    continue
                animation.setLoopCount(1)
                if animation.duration() > 0:
                    animation.setCurrentTime(animation.duration())
                if animation.state() != QAbstractAnimation.Stopped:
                    animation.stop()
            pump(40)

        window = MainWindow()
        window.resize(args.width, args.height)
        window.show()
        pump(400)
        leaves = window.nav_leaves()
        if args.pages is not None:
            wanted = set(args.pages)
            leaves = [item for item in leaves if item[0] in wanted]
        if not leaves:
            raise AssertionError("没有可截图的页面")
        output = args.out.resolve() / args.mode
        output.mkdir(parents=True, exist_ok=True)
        records = []
        for key, _title, item in leaves:
            random.seed(SEED)
            window.select_leaf(item)
            pump(args.settle)
            finish_streams()
            pump(60)
            wait_async()
            complete_animations()
            image = window.grab().toImage().convertToFormat(QImage.Format_RGBA8888)
            path = output / f"{key}.png"
            if not image.save(str(path)):
                raise AssertionError(f"截图保存失败: {path}")
            payload = bytes(image.constBits())
            records.append({"page": key, "width": image.width(), "height": image.height(),
                            "rgba_sha256": hashlib.sha256(payload).hexdigest()})
            print(f"[截图] {args.mode}/{key}", flush=True)
        manifest = {
            "source": str(source), "source_sha": args.source_sha,
            "mode": args.mode, "seed": SEED, "settle_ms": args.settle,
            "size": [args.width, args.height], "count": len(records),
            "freeze": "完成流式 Markdown；等待异步内容；暂停自绘定时器；属性动画完成一轮",
            "images": records,
        }
        (args.out.resolve() / f"manifest-{args.mode}.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"已保存 {len(records)} 张确定性截图: {output}", flush=True)
    finally:
        QTimer.start = original_start
        if window is not None:
            window.close()
            window.deleteLater()
            app.sendPostedEvents(None, QEvent.DeferredDelete)
        from InstructionX_UIKit.components.math_render import MathRenderHub
        from InstructionX_UIKit.mermaid import MermaidRenderHub
        math = MathRenderHub.instance()
        math.shutdown(10)
        hub = MermaidRenderHub.instance()
        hub.shutdown()
        if getattr(hub, "_page", None) is not None:
            hub._page.deleteLater()
            hub._page = None
        app.sendPostedEvents(None, QEvent.DeferredDelete)
        app.processEvents()


def compare(args):
    import numpy as np
    from PySide6.QtGui import QImage

    before_root = args.before.resolve()
    after_root = args.after.resolve()
    records = []
    for mode in ("light", "dark"):
        before_paths = sorted((before_root / mode).glob("*.png"))
        after_paths = sorted((after_root / mode).glob("*.png"))
        before_names = {path.name for path in before_paths}
        after_names = {path.name for path in after_paths}
        if before_names != after_names:
            raise AssertionError(f"{mode} 页面集合不一致: {sorted(before_names ^ after_names)}")
        for before_path in before_paths:
            after_path = after_root / mode / before_path.name
            before = QImage(str(before_path)).convertToFormat(QImage.Format_RGBA8888)
            after = QImage(str(after_path)).convertToFormat(QImage.Format_RGBA8888)
            row = {"mode": mode, "page": before_path.stem}
            if before.size() != after.size():
                row.update(equal=False, reason="尺寸不同",
                           before_size=[before.width(), before.height()],
                           after_size=[after.width(), after.height()])
            else:
                aa = np.frombuffer(after.constBits(), dtype=np.uint8).reshape(
                    after.height(), after.width(), 4)
                bb = np.frombuffer(before.constBits(), dtype=np.uint8).reshape(
                    before.height(), before.width(), 4)
                delta = aa.astype(np.int16) - bb.astype(np.int16)
                changed = np.any(delta, axis=2)
                ys, xs = np.where(changed)
                row.update(equal=not changed.any(), changed=int(changed.sum()),
                           max_delta=int(np.abs(delta).max()),
                           bbox=None if not len(xs) else [int(xs.min()), int(ys.min()),
                                                          int(xs.max()), int(ys.max())])
            records.append(row)
    mismatches = [row for row in records if not row["equal"]]
    count_error = args.require_all and len(records) != 160
    report = {"before": str(before_root), "after": str(after_root),
              "count": len(records), "required_count": 160 if args.require_all else None,
              "mismatches": mismatches, "pass": not mismatches and not count_error}
    args.out.resolve().mkdir(parents=True, exist_ok=True)
    (args.out.resolve() / "comparison.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"count": len(records), "mismatch_count": len(mismatches),
                      "require_all": args.require_all, "pass": report["pass"]},
                     ensure_ascii=False), flush=True)
    return 0 if report["pass"] else 1


def main():
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)
    shoot = commands.add_parser("capture")
    shoot.add_argument("--source", type=Path, required=True)
    shoot.add_argument("--source-sha", required=True)
    shoot.add_argument("--out", type=Path, required=True)
    shoot.add_argument("--mode", choices=["light", "dark"], required=True)
    shoot.add_argument("--pages", nargs="*")
    shoot.add_argument("--width", type=int, default=1280)
    shoot.add_argument("--height", type=int, default=800)
    shoot.add_argument("--settle", type=int, default=300)
    shoot.set_defaults(function=capture)
    diff = commands.add_parser("compare")
    diff.add_argument("--before", type=Path, required=True)
    diff.add_argument("--after", type=Path, required=True)
    diff.add_argument("--out", type=Path, required=True)
    diff.add_argument("--require-all", action="store_true")
    diff.set_defaults(function=compare)
    args = parser.parse_args()
    result = args.function(args)
    return 0 if result is None else result


if __name__ == "__main__":
    raise SystemExit(main())
