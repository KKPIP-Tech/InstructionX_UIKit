#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""交互冒烟测试（开发辅助，不属于 Kit 运行时）。

只做一件事：**用真实鼠标事件点击**，而不是直接调内部方法。

起因：早期版本的截图验证全部通过，但因为截图脚本直接调用
``MainWindow.navigate()``，绕过了「导航项点击 -> 信号 -> 主窗口」这条链路，
导致侧栏点击实际抛 ``AttributeError`` 却在截图里完全看不出来（页面照样渲染，
只是点了没反应）。本脚本补上这条链路的覆盖。

用法::

    QT_QPA_PLATFORM=offscreen python tools/smoke_click.py
"""

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import traceback  # noqa: E402

from PySide6.QtCore import QPoint, Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from InstructionX_UIKit.theme import ThemeManager  # noqa: E402

#: 视口外的异常（AttributeError 等）会被 PySide 打到 stderr 而不是抛出，
#: 这里装一个处理器把它们收集起来，最后统一判定。
_SEEN_TRACEBACKS: list[str] = []


def _hook(exc_type, exc, tb) -> None:  # noqa: ANN001
    """收集未捕获异常（sys.excepthook 签名是 (type, value, traceback)）。"""
    if exc_type is not None:
        _SEEN_TRACEBACKS.append("".join(
            traceback.format_exception(exc_type, exc, tb)).strip())


def _pump(app, ms: int = 120) -> None:
    """转动事件循环若干毫秒（离屏下仍需手动 pump 才会派发定时器 / 信号）。"""
    end = time.time() + ms / 1000.0
    while time.time() < end:
        app.processEvents()
        time.sleep(0.01)
    app.processEvents()


def _click(app, widget) -> None:
    """在控件中心派发一次真实的左键按下 / 释放。"""
    QTest.mouseClick(widget, Qt.MouseButton.LeftButton,
                     Qt.KeyboardModifier.NoModifier,
                     QPoint(widget.width() // 2, widget.height() // 2))
    _pump(app, 200)


def main() -> int:
    sys.excepthook = _hook
    app = QApplication(sys.argv)
    ThemeManager.instance().apply(app)

    from demo.main_window import MainWindow

    win = MainWindow()
    win.resize(1440, 900)
    win.show()
    _pump(app, 500)

    failures: list[str] = []

    # ---- 1. 初始页：构造期 select_first() 应已选中第一个叶子页 ----
    if win._current is None:
        failures.append("初始化后未选中任何页面（select_first 未生效）")
    else:
        print(f"[ok] 初始页 = {win._current}")

    # ---- 2. 逐个真实点击导航项，验证页面真的切换 ----
    leaves = win.nav_leaves()
    clicked = 0
    for key, _title, item in leaves:
        if not item.isVisible():
            continue
        _click(app, item)
        if win._current != key:
            failures.append(f"点击 {key!r} 后当前页为 {win._current!r}")
        elif not item._active:
            failures.append(f"点击 {key!r} 后未高亮选中态")
        else:
            clicked += 1
        if failures:
            break   # 首个失败即停，便于定位
    if not failures:
        print(f"[ok] 真实点击导航项 {clicked} 个，全部正确切换并高亮")

    # ---- 3. 点击后取一次实际渲染，确认内容区有内容 ----
    _pump(app, 200)
    pix = win.grab()
    if pix.isNull() or pix.width() < 10:
        failures.append("点击后整窗 grab() 为空")
    else:
        print(f"[ok] 点击后窗口可正常渲染 ({pix.width()}x{pix.height()})")

    # ---- 4. 搜索过滤 + 点击过滤结果 ----
    sb = win._sidebar._search
    sb.setText("表格")
    _pump(app, 150)
    visible = [it for _c, items in win._sidebar._categories for it in items if it.isVisible()]
    if not visible:
        failures.append("搜索『表格』后没有可见导航项")
    else:
        _click(app, visible[0])
        if win._current != visible[0]._page_key:
            failures.append("搜索过滤后点击结果未切换")
        else:
            print(f"[ok] 搜索过滤后可点击（{visible[0]._page_key}）")
    sb.clear()
    _pump(app, 150)

    # ---- 5. 主题切换往返 ----
    tm = ThemeManager.instance()
    before = tm.mode
    tm.toggle()
    _pump(app, 200)
    if tm.mode == before:
        failures.append("主题切换无效")
    tm.toggle()
    _pump(app, 200)
    if tm.mode != before:
        failures.append("主题切换往返后未复位")
    else:
        print("[ok] 亮/暗主题切换往返正常")

    # ---- 汇总 ----
    stray = [t for t in _SEEN_TRACEBACKS
             if "Traceback" in t and "AttributeError" in t]
    if stray:
        failures.append(f"事件循环中出现 {len(stray)} 处未捕获异常")

    if failures:
        print("\n[FAIL]")
        for f in failures:
            print("  -", f)
        return 1
    print("\n[PASS] 交互冒烟测试全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())