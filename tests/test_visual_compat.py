# -*- coding: utf-8 -*-
"""逐页比较收窄 QSS 前后及恢复后的 RGBA，避免原生页面控件跨页堆积。"""

import argparse
import json
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
from PySide6.QtWidgets import QApplication

from InstructionX_UIKit import theme as theme_module
from InstructionX_UIKit.theme import ThemeManager, build_qss
from demo.main_window import MainWindow

app = QApplication.instance() or QApplication(sys.argv)
_RULE = 'QWidget[role="code"] QLabel { background-color: transparent; }'


def pump(ms):
    deadline = time.monotonic() + ms / 1000
    while time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.004)


def _rgba(widget):
    return widget.grab().toImage().convertToFormat(QImage.Format_RGBA8888)


def _close(window):
    window.close()
    window.deleteLater()
    app.sendPostedEvents(None, QEvent.DeferredDelete)
    app.processEvents()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--settle", type=int, default=300)
    parser.add_argument("--pages", nargs="*")
    parser.add_argument("--modes", nargs="+", choices=["light", "dark"],
                        default=["light", "dark"])
    args = parser.parse_args()
    tm = ThemeManager.instance()
    tm.set_mode("light")
    tm.apply(app)
    candidate = build_qss(tm.tokens)
    if _RULE in candidate:
        raise AssertionError("重复的代码容器 QLabel 透明背景规则仍未移除")
    legacy = candidate.replace("/* 顶部条：", _RULE + "\n/* 顶部条：", 1)
    if legacy == candidate:
        raise AssertionError("无法建立删除规则前的 QSS 对照")

    navigation = MainWindow()
    keys = [key for key, _title, _item in navigation.nav_leaves()]
    _close(navigation)
    if args.pages is not None:
        keys = [key for key in keys if key in set(args.pages)]
    if not keys:
        raise AssertionError("没有需要对照的页面")

    compared = []
    mismatches = []
    output = ROOT / "tests" / "shots" / "visual_compat"
    output.mkdir(parents=True, exist_ok=True)
    window = None
    try:
        for mode in args.modes:
            tm.set_mode(mode)
            candidate = build_qss(tm.tokens)
            legacy = candidate.replace("/* 顶部条：", _RULE + "\n/* 顶部条：", 1)
            for key in keys:
                window = MainWindow()
                window.resize(1280, 800)
                window.show()
                window.navigate(key)
                pump(args.settle)
                after = _rgba(window)
                theme_module.build_qss = lambda _tokens: legacy
                try:
                    tm.apply(app)
                finally:
                    theme_module.build_qss = build_qss
                before = _rgba(window)
                tm.apply(app)
                restored = _rgba(window)
                if after.size() != before.size() or after != before:
                    before.save(str(output / f"{mode}_{key}_before.png"))
                    after.save(str(output / f"{mode}_{key}_after.png"))
                    mismatches.append(f"{mode}/{key}")
                if after != restored:
                    restored.save(str(output / f"{mode}_{key}_restored.png"))
                    after.save(str(output / f"{mode}_{key}_before_restore.png"))
                    mismatches.append(f"恢复/{mode}/{key}")
                compared.append({"mode": mode, "page": key})
                _close(window)
                window = None
                if len(compared) % 20 == 0:
                    print(f"  已逐像素比较 {len(compared)} 个页面状态", flush=True)
    finally:
        if window is not None:
            _close(window)
        from InstructionX_UIKit.components.math_render import MathRenderHub
        from InstructionX_UIKit.mermaid import MermaidRenderHub
        MathRenderHub.instance().shutdown(10)
        hub = MermaidRenderHub.instance()
        hub.shutdown()
        if getattr(hub, "_page", None) is not None:
            hub._page.deleteLater()
            hub._page = None
        app.sendPostedEvents(None, QEvent.DeferredDelete)
        tm.set_mode("light")
        app.processEvents()
    report = {
        "comparison": "逐页独立控件树上删除一条冗余 QSS 前后及恢复后，非原始基线替代",
        "settle_ms": args.settle,
        "count": len(compared),
        "mismatches": mismatches,
        "pages": compared,
    }
    (output / "result.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    expected = args.pages is None and set(args.modes) == {"light", "dark"}
    if expected and len(compared) != 160:
        raise AssertionError(f"必须比较全部 160 个亮暗页面状态: {len(compared)}")
    if mismatches:
        raise AssertionError(f"QSS 对照存在像素差异: {mismatches}")
    print(f"  [通过] {len(compared)} 个页面状态的最终 RGBA 像素零差异")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception:
        traceback.print_exc()
        raise SystemExit(1)
