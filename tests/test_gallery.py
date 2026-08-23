# -*- coding: utf-8 -*-
"""Demo 演示应用自测（SPEC §8）。

直接运行（无 pytest 依赖）::

    QT_QPA_PLATFORM=offscreen python tests/test_gallery.py

覆盖：
- offscreen 下实例化 MainWindow 并 show；
- 遍历左侧导航树**每一页**（懒加载触发页面构造），逐页 grab() 截图到
  ``tests/shots/gallery_<页名>.png``（亮色主题）；
- 切换到暗色主题，重拍至少 10 个代表页到 ``tests/shots/gallery_<页名>_dark.png``；
- 采样断言每张截图非空白 / 非全黑（去重色数 >= 2，文件 >= 200B）；
- 抽样比对亮 / 暗截图像素差异，确认主题切换对演示页生效；
- 任何页面构造异常即失败，退出码 1；全部通过退出码 0。
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
_SHOTS = {}  # key -> 亮主题 QImage，供暗色比对

# 暗色主题重拍的代表页（>= 10，覆盖全部分类）
DARK_PAGES = [
    "tokens", "card_grid", "button", "table", "statistic", "alert",
    "steps", "anim_property", "anim_painted", "basic_widgets", "charts",
]

from PySide6.QtWidgets import QApplication, QScrollArea  # noqa: E402

app = QApplication.instance() or QApplication(sys.argv)

from InstructionX_UIKit.theme import ThemeManager  # noqa: E402
from demo.main_window import MainWindow  # noqa: E402


def pump(ms):
    """推进事件循环约 ms 毫秒。"""
    deadline = time.monotonic() + ms / 1000.0
    while time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.004)


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


def _assert_shot(pm, name):
    """非空白 / 非全黑断言，返回 QImage。

    采用密集采样（约 150x150 网格），避免稀疏采样漏掉窄小内容
    （如树 / 开关等留白较多的页面）而误判为空白。
    """
    if pm.isNull() or pm.width() < 4 or pm.height() < 4:
        raise AssertionError(f"{name}: grab() 失败或尺寸异常 {pm.width()}x{pm.height()}")
    img = pm.toImage()
    w, h = img.width(), img.height()
    colors = set()
    sx, sy = max(1, w // 150), max(1, h // 150)
    for x in range(0, w, sx):
        for y in range(0, h, sy):
            colors.add(img.pixelColor(x, y).rgb())
            if len(colors) >= 2:  # 提前退出：已确认非空白
                break
        if len(colors) >= 2:
            break
    if len(colors) < 2:
        raise AssertionError(f"{name}: 密集采样仅 {len(colors)} 种颜色，疑似空白")
    if colors == {0xFF000000}:
        raise AssertionError(f"{name}: 截图全黑")
    return img


def grab_current(win):
    """截取当前页完整内容（滚动页取内部内容控件以覆盖全页）。"""
    page = win._stack.currentWidget()
    if page is None:
        raise AssertionError("当前无页面")
    content = page.widget() if isinstance(page, QScrollArea) else page
    return content.grab()


def shot_page(win, key, suffix=""):
    pm = grab_current(win)
    img = _assert_shot(pm, key)
    path = SHOTS / f"gallery_{key}{suffix}.png"
    if not pm.save(str(path)):
        raise AssertionError(f"{key}: 截图保存失败 {path}")
    if path.stat().st_size < 200:
        raise AssertionError(f"{key}: 截图过小疑似空白 {path.stat().st_size}B")
    return img


def main() -> int:
    print("Demo 自测开始（offscreen，遍历导航树全部页面）")
    print("-" * 64)
    SHOTS.mkdir(parents=True, exist_ok=True)

    tm = ThemeManager.instance()
    tm.set_mode("light")
    tm.apply(app)

    win = MainWindow()
    win.resize(1280, 800)
    win.show()
    pump(200)

    leaves = win.nav_leaves()
    print(f"导航树叶子页共 {len(leaves)} 个")

    # 1) 亮色：遍历每一页并截图
    for key, title, item in leaves:
        @case(f"[亮] {key}（{title}）")
        def _(key=key, item=item):
            win.select_leaf(item)
            pump(120)
            _SHOTS[key] = shot_page(win, key)

    # 2) 暗色：重拍代表页并比对亮暗差异
    @case("切换暗色主题")
    def _():
        tm.set_mode("dark")
        tm.apply(app)
        pump(150)
        if tm.mode != "dark":
            raise AssertionError("主题未切换到暗色")

    by_key = {key: (title, item) for key, title, item in leaves}
    for key in DARK_PAGES:
        @case(f"[暗] {key}")
        def _(key=key):
            title, item = by_key[key]
            win.select_leaf(item)
            pump(120)
            shot_page(win, key, suffix="_dark")

    @case("亮暗主题对演示页生效（抽样比对）")
    def _():
        for key in ("tokens", "table", "basic_widgets"):
            title, item = by_key[key]
            # 亮色重拍
            tm.set_mode("light"); tm.apply(app)
            win.select_leaf(item); pump(110)
            light = _assert_shot(grab_current(win), key + "·light")
            # 暗色重拍
            tm.set_mode("dark"); tm.apply(app)
            win.select_leaf(item); pump(110)
            dark = _assert_shot(grab_current(win), key + "·dark")
            if light.size() == dark.size() and light == dark:
                raise AssertionError(f"{key} 亮暗截图完全一致，主题未生效")

    # 恢复亮色，便于后续查看
    tm.set_mode("light")
    tm.apply(app)
    pump(120)

    # 退出前清理：offscreen 下 WebEngine 控件（Mermaid 查看器 / 渲染中枢
    # 隐藏页）若存活到解释器拆除阶段会段错误，须显式销毁并冲刷 deferred 事件
    from PySide6.QtCore import QEvent
    win.close()
    win.deleteLater()
    app.sendPostedEvents(None, QEvent.DeferredDelete)
    from InstructionX_UIKit.mermaid import MermaidRenderHub
    hub = MermaidRenderHub.instance()
    hub.shutdown()
    if getattr(hub, "_page", None) is not None:
        hub._page.deleteLater()
        hub._page = None
    app.sendPostedEvents(None, QEvent.DeferredDelete)
    app.processEvents()

    print("-" * 64)
    if _FAILURES:
        print(f"共 {len(_FAILURES)} 项失败: {_FAILURES}")
        return 1
    print(f"全部 {len(leaves)} 个亮色页 + {len(DARK_PAGES)} 个暗色页截图通过，"
          f"截图目录: {SHOTS}")
    print("0 错误，0 段错误")
    return 0


if __name__ == "__main__":
    sys.exit(main())
