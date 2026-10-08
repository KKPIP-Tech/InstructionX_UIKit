#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""离屏截图工具（开发辅助，不属于 Kit 运行时）。

用途：在无显示器的环境下把 Demo 的若干页面渲染为 PNG，用于视觉回归对比。

用法::

    QT_QPA_PLATFORM=offscreen python tools/shoot.py --out shots/before \
        --mode light --pages tokens button inputs charts
"""

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PySide6.QtCore import Qt, QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from InstructionX_UIKit.theme import ThemeManager  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True, help="输出目录")
    ap.add_argument("--mode", default="light", choices=["light", "dark"])
    ap.add_argument("--pages", nargs="*", default=None, help="页面键；缺省为全部")
    ap.add_argument("--width", type=int, default=1280)
    ap.add_argument("--height", type=int, default=800)
    ap.add_argument("--settle", type=int, default=900, help="每页渲染等待 ms")
    args = ap.parse_args()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    app = QApplication(sys.argv)
    ThemeManager.instance().apply(app)
    ThemeManager.instance().set_mode(args.mode)

    from demo.main_window import MainWindow

    win = MainWindow()
    win.resize(args.width, args.height)
    win.show()
    app.processEvents()
    time.sleep(0.4)
    app.processEvents()

    leaves = win.nav_leaves()
    if args.pages:
        wanted = set(args.pages)
        leaves = [x for x in leaves if x[0] in wanted]

    for key, title, item in leaves:
        try:
            win.select_leaf(item)
        except Exception as exc:  # noqa: BLE001
            print(f"[skip] {key}: nav error {exc}")
            continue
        # 让事件循环转起来，等待布局 / 自绘 / 动画首帧落定
        deadline = time.time() + args.settle / 1000.0
        while time.time() < deadline:
            app.processEvents()
            time.sleep(0.02)
        path = out / f"{key}.png"
        win.grab().save(str(path))
        print(f"[ok] {key:20s} -> {path.name}  ({title})")

    return 0


if __name__ == "__main__":
    sys.exit(main())
