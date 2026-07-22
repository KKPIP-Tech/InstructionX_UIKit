# -*- coding: utf-8 -*-
"""fix/f1 修复验证：矢量图标集 / 侧边栏图标化 / 令牌字阶渲染 / 按钮形状。

直接运行（无 pytest 依赖）::

    QT_QPA_PLATFORM=offscreen python tests/test_fix_f1.py

覆盖：
- InstructionX_UIKit.icons：ICON_NAMES 全部名称生成 QIcon 非空、pixmap 非空白且
  墨迹命中指定颜色；缺省色取 text.secondary；未知名称抛 ValueError；
- SidebarLayout：展开态导航项 icon+text，折叠为 56px 图标栏时仅 icon
  （按钮文本置空，遍历子控件无单字 QLabel），选中项图标色为主色、
  未选中为 text.secondary；
- tokens 页：字阶区各级示例 QLabel 的 font pixelSize 与令牌一致且互不
  相同，渲染墨迹高度随字阶递增（肉眼可分辨）；字重区 font weight 与
  令牌一致；
- Button 演示 Shape 区：无宽度 > 高度 2 倍的异常按钮，圆形按钮宽 = 高；
- 亮 / 暗截图 tests/shots/fixf1_*.png（侧栏展开 / 折叠、令牌页、按钮页）。
任何异常即失败，退出码 1。
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

from PySide6.QtWidgets import QApplication  # noqa: E402

_APP = QApplication.instance() or QApplication([])

from InstructionX_UIKit.theme import T, ThemeManager  # noqa: E402

ThemeManager.instance().set_mode("light")
ThemeManager.instance().apply(_APP)


def check(name):
    """装饰器：登记一项检查，异常即记为失败。"""

    def deco(fn):
        try:
            fn()
            print(f"  [通过] {name}")
        except Exception:
            _FAILURES.append(name)
            print(f"  [失败] {name}")
            traceback.print_exc()

    return deco


def assert_true(cond, msg=""):
    if not cond:
        raise AssertionError(msg or "断言失败")


def assert_eq(actual, expected, msg=""):
    if actual != expected:
        raise AssertionError(f"{msg} 期望 {expected!r}，实际 {actual!r}")


def settle(app, ms=150):
    from PySide6.QtCore import QElapsedTimer

    timer = QElapsedTimer()
    timer.start()
    while timer.elapsed() < ms:
        app.processEvents()
        time.sleep(0.004)


def _has_color(img, target, tol=40, min_alpha=150):
    """图像中是否存在接近 target 的不透明像素。"""
    for y in range(img.height()):
        for x in range(img.width()):
            c = img.pixelColor(x, y)
            if (abs(c.red() - target.red()) <= tol
                    and abs(c.green() - target.green()) <= tol
                    and abs(c.blue() - target.blue()) <= tol
                    and c.alpha() >= min_alpha):
                return True
    return False


def _ink_pixels(img, min_alpha=30):
    n = 0
    for y in range(img.height()):
        for x in range(img.width()):
            if img.pixelColor(x, y).alpha() >= min_alpha:
                n += 1
    return n


def _ink_height(widget):
    """控件 grab 后非背景墨迹的纵向跨度（px）。"""
    img = widget.grab().toImage()
    bg = img.pixelColor(0, 0)
    ys = []
    for y in range(img.height()):
        for x in range(img.width()):
            c = img.pixelColor(x, y)
            if (abs(c.red() - bg.red()) > 24 or abs(c.green() - bg.green()) > 24
                    or abs(c.blue() - bg.blue()) > 24):
                ys.append(y)
                break
    return (max(ys) - min(ys) + 1) if ys else 0


# ---------------------------------------------------------------------------
# 1. 矢量图标集
# ---------------------------------------------------------------------------

@check("icons: ICON_NAMES 全部名称生成非空、非空白 QIcon")
def _():
    from PySide6.QtCore import QSize
    from PySide6.QtGui import QColor

    from InstructionX_UIKit.icons import ICON_NAMES, get_icon

    expected = {"home", "chart", "layout", "component", "animation",
                "settings", "user", "search", "menu", "arrow_left",
                "arrow_right", "plus", "close", "info", "warning", "check"}
    assert_true(expected.issubset(set(ICON_NAMES)),
                f"ICON_NAMES 缺少必需图标: {expected - set(ICON_NAMES)}")
    red = QColor("#d4380d")
    for name in ICON_NAMES:
        for size in (16, 24, 32):
            icon = get_icon(name, size=size, color=red)
            assert_true(not icon.isNull(), f"{name}@{size} 图标为空")
            pm = icon.pixmap(QSize(size, size))
            assert_true(not pm.isNull(), f"{name}@{size} pixmap 为空")
            img = pm.toImage()
            n = _ink_pixels(img)
            assert_true(n >= size,  # 至少一条贯穿笔画量级的墨迹
                        f"{name}@{size} pixmap 近乎空白（墨迹像素 {n}）")
            assert_true(_has_color(img, red, tol=60, min_alpha=120),
                        f"{name}@{size} 墨迹未命中指定颜色")


@check("icons: 缺省颜色取 text.secondary，未知名称抛 ValueError")
def _():
    from PySide6.QtCore import QSize
    from PySide6.QtGui import QColor

    from InstructionX_UIKit.icons import get_icon

    img = get_icon("home", 24).pixmap(QSize(24, 24)).toImage()
    sec = QColor(T("color.text.secondary"))
    assert_true(_has_color(img, sec, tol=40, min_alpha=120),
                "缺省颜色应取 color.text.secondary")
    try:
        get_icon("no_such_icon")
    except ValueError:
        pass
    else:
        raise AssertionError("未知图标名应抛 ValueError")


# ---------------------------------------------------------------------------
# 2. 侧边栏布局：导航图标化 + 折叠图标栏
# ---------------------------------------------------------------------------

def _nav_buttons(widget):
    from PySide6.QtWidgets import QToolButton

    return [b for b in widget._sidebar.findChildren(QToolButton)]


@check("sidebar: 展开态导航项 icon+text，折叠态仅 icon 且无单字 QLabel")
def _():
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QLabel

    from demo.pages.layout_samples import SIDEBAR_NAV_ITEMS as _NAV_ITEMS
    from InstructionX_UIKit.layouts.sidebar_layout import create_sidebar_layout

    w = create_sidebar_layout(brand="控制台", nav_items=_NAV_ITEMS)
    try:
        w.resize(1280, 800)
        w.show()
        _APP.processEvents()
        settle(_APP, 100)
        buttons = _nav_buttons(w)
        assert_eq(len(buttons), len(_NAV_ITEMS), "导航按钮数量")
        # 展开态：icon + text
        for btn, (_icon, text) in zip(buttons, _NAV_ITEMS):
            assert_eq(btn.text(), text, "展开态导航项应显示文本")
            assert_true(not btn.icon().isNull(), f"{text} 展开态应有图标")
            assert_eq(btn.toolButtonStyle(), Qt.ToolButtonTextBesideIcon,
                      "展开态应为图标+文本并排")
        # 折叠态：仅图标
        w.resize(480, 700)
        _APP.processEvents()
        settle(_APP, 100)
        assert_eq(w._sidebar.width(), 56, "折叠后侧栏应为 56px 图标栏")
        for btn in buttons:
            assert_eq(btn.text(), "", "折叠态导航项文本应置空（仅图标）")
            assert_true(not btn.icon().isNull(), "折叠态导航项应保留图标")
            assert_eq(btn.toolButtonStyle(), Qt.ToolButtonIconOnly,
                      "折叠态应为仅图标")
        # 遍历侧栏全部子控件：不得有可见的单字 QLabel（旧「首/析/目」图标字）
        singles = [lab.text() for lab in w._sidebar.findChildren(QLabel)
                   if lab.isVisible() and len(lab.text()) == 1]
        assert_true(not singles, f"折叠态侧栏仍存在单字 QLabel: {singles}")
        # 恢复展开，文本回归
        w.resize(1280, 800)
        _APP.processEvents()
        for btn, (_icon, text) in zip(buttons, _NAV_ITEMS):
            assert_eq(btn.text(), text, "恢复展开后文本应回归")
    finally:
        w.close()
        w.deleteLater()


@check("sidebar: 图标颜色随选中态区分（选中主色 / 未选中次要色）")
def _():
    from PySide6.QtCore import QSize
    from PySide6.QtGui import QColor

    from demo.pages.layout_samples import SIDEBAR_NAV_ITEMS
    from InstructionX_UIKit.layouts.sidebar_layout import create_sidebar_layout

    w = create_sidebar_layout(brand="控制台", nav_items=SIDEBAR_NAV_ITEMS)
    try:
        w.resize(1280, 800)
        w.show()
        _APP.processEvents()
        buttons = _nav_buttons(w)
        checked = next(b for b in buttons if b.isChecked())
        unchecked = next(b for b in buttons if not b.isChecked())
        size = QSize(18, 18)
        img_on = checked.icon().pixmap(size).toImage()
        img_off = unchecked.icon().pixmap(size).toImage()
        primary = QColor(T("color.primary"))
        secondary = QColor(T("color.text.secondary"))
        assert_true(_has_color(img_on, primary, tol=50, min_alpha=120),
                    "选中项图标应使用 color.primary")
        assert_true(_has_color(img_off, secondary, tol=40, min_alpha=120),
                    "未选中项图标应使用 color.text.secondary")
        # 切换选中项后图标颜色应重绘
        unchecked.click()
        _APP.processEvents()
        img_new = unchecked.icon().pixmap(size).toImage()
        assert_true(_has_color(img_new, primary, tol=50, min_alpha=120),
                    "新选中项图标未切换为主色")
    finally:
        w.close()
        w.deleteLater()


# ---------------------------------------------------------------------------
# 3. tokens 页：字阶 / 字重真实渲染
# ---------------------------------------------------------------------------

@check("tokens: 字阶各级 QLabel pixelSize 与令牌一致且互不相同")
def _():
    from PySide6.QtWidgets import QLabel

    from demo.pages.tokens import _FONT_SCALES, create_page

    page = create_page()
    try:
        page.resize(960, 1200)
        page.show()
        _APP.processEvents()
        settle(_APP, 100)
        samples = {}
        for lab in page.findChildren(QLabel):
            key = lab.property("type_scale")
            if key:
                samples[key] = lab
        assert_eq(len(samples), len(_FONT_SCALES), "字阶示例标签数量")
        sizes = []
        for key, _label in _FONT_SCALES:
            lab = samples[key]
            px = lab.font().pixelSize()
            assert_eq(px, T(key), f"{key} 示例 QLabel 的 font pixelSize")
            sizes.append(px)
            # 数值标签（text.tertiary）应同行附带
        assert_eq(len(set(sizes)), len(sizes), "各级字阶 pixelSize 应互不相同")
        # 渲染墨迹高度随字阶递增（肉眼可分辨的递增梯度）
        heights = [(_ink_height(samples[key]), key) for key, _ in _FONT_SCALES]
        for (h0, k0), (h1, k1) in zip(heights, heights[1:]):
            assert_true(h1 >= h0, f"墨迹高度未递增: {k0}={h0}px > {k1}={h1}px")
        assert_true(heights[-1][0] - heights[0][0] >= 10,
                    f"字阶视觉跨度过小: {heights[0]} ~ {heights[-1]}")
    finally:
        page.close()
        page.deleteLater()


@check("tokens: 字重各级 QLabel weight 与令牌一致（400/500/600/700）")
def _():
    from PySide6.QtWidgets import QLabel

    from demo.pages.tokens import _FONT_WEIGHTS, create_page

    page = create_page()
    try:
        page.show()
        _APP.processEvents()
        samples = {}
        for lab in page.findChildren(QLabel):
            key = lab.property("type_weight")
            if key:
                samples[key] = lab
        assert_eq(len(samples), len(_FONT_WEIGHTS), "字重示例标签数量")
        for key, _label in _FONT_WEIGHTS:
            assert_eq(int(samples[key].font().weight()), T(key),
                      f"{key} 示例 QLabel 的 font weight")
    finally:
        page.close()
        page.deleteLater()


# ---------------------------------------------------------------------------
# 4. Button 演示 Shape 区：无细长条按钮
# ---------------------------------------------------------------------------

@check("inputs: Button Shape 区无宽度 > 高度 2 倍的异常按钮")
def _():
    from PySide6.QtWidgets import QAbstractButton, QGroupBox

    from demo.pages.inputs import create_button_page

    page = create_button_page()
    try:
        page.resize(900, 700)
        page.show()
        _APP.processEvents()
        settle(_APP, 100)
        sections = [g for g in page.findChildren(QGroupBox)
                    if g.title() == "形状 shape"]
        assert_eq(len(sections), 1, "应存在「形状 shape」分区")
        buttons = sections[0].findChildren(QAbstractButton)
        assert_true(len(buttons) >= 3, "Shape 区按钮数量异常")
        for b in buttons:
            h = b.height()
            assert_true(h > 0, "按钮高度为 0")
            assert_true(b.width() <= h * 2,
                        f"按钮 {b.text()!r} 宽 {b.width()} 超过高 {h} 的 2 倍"
                        "（细长条回归）")
        # 圆形按钮应为正方形
        circle = next(b for b in buttons if b.property("shape") == "circle")
        assert_eq(circle.width(), circle.height(), "圆形按钮宽应等于高")
    finally:
        page.close()
        page.deleteLater()


# ---------------------------------------------------------------------------
# 5. 亮 / 暗截图目检
# ---------------------------------------------------------------------------

def _grab_shot(widget, name, min_size=2048):
    pm = widget.grab()
    if pm.isNull() or pm.width() < 50:
        raise AssertionError(f"{name} grab() 返回空图像")
    path = SHOTS / name
    if not pm.save(str(path)):
        raise AssertionError(f"截图保存失败: {path}")
    if path.stat().st_size < min_size:
        raise AssertionError(f"截图文件过小: {path}")
    print(f"  截图: {path}")


@check("亮 / 暗截图：侧栏展开 / 折叠、令牌页、按钮 Shape 区")
def _():
    from demo.pages.inputs import create_button_page
    from demo.pages.tokens import create_page
    from demo.pages.layout_samples import SIDEBAR_NAV_ITEMS
    from InstructionX_UIKit.layouts.sidebar_layout import create_sidebar_layout

    tm = ThemeManager.instance()
    SHOTS.mkdir(parents=True, exist_ok=True)

    sidebar = create_sidebar_layout(brand="控制台", nav_items=SIDEBAR_NAV_ITEMS)
    tokens_page = create_page()
    button_page = create_button_page()
    try:
        sidebar.resize(1280, 800)
        sidebar.show()
        tokens_page.resize(960, 1400)
        tokens_page.show()
        button_page.resize(900, 700)
        button_page.show()
        _APP.processEvents()
        settle(_APP, 200)
        for mode in ("light", "dark"):
            tm.set_mode(mode)
            tm.apply(_APP)
            settle(_APP, 200)
            # 展开态侧栏
            sidebar.resize(1280, 800)
            _APP.processEvents()
            _grab_shot(sidebar, f"fixf1_sidebar_expanded_{mode}.png")
            # 折叠态图标栏
            sidebar.resize(480, 700)
            _APP.processEvents()
            settle(_APP, 100)
            _grab_shot(sidebar, f"fixf1_sidebar_collapsed_{mode}.png")
            sidebar.resize(1280, 800)
            _APP.processEvents()
            # 令牌页（整页内容，字阶区肉眼可分辨递增）
            _grab_shot(tokens_page.widget(), f"fixf1_tokens_{mode}.png")
            # 按钮页（Shape 区）
            _grab_shot(button_page, f"fixf1_buttons_{mode}.png")
        tm.set_mode("light")
        tm.apply(_APP)
        _APP.processEvents()
    finally:
        for w in (sidebar, tokens_page, button_page):
            w.close()
            w.deleteLater()


def main() -> int:
    print("fix/f1 修复验证开始（offscreen）")
    print("-" * 60)
    if _FAILURES:
        print(f"共 {len(_FAILURES)} 项失败: {_FAILURES}")
        return 1
    print("全部检查通过，0 错误")
    return 0


if __name__ == "__main__":
    sys.exit(main())
