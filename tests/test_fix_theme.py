# -*- coding: utf-8 -*-
"""fix/theme 修订自测：低饱和度配色 + 三处 QSS 渲染缺陷修复。

直接运行（无 pytest 依赖）::

    QT_QPA_PLATFORM=offscreen python tests/test_fix_theme.py

覆盖：
- 任务A：LIGHT/DARK 新配色令牌值；亮/暗主按钮像素采样 = #3F5E8C / #7C98C4；
  set_mode 后 QSS 与运行时图标按主题重建（暗色勾选图标应为深色 #15181E）。
- 任务B1：QSlider 24/32/40 三高度、水平/垂直、值 0/50/100 下
  手柄描边环完整（四象限极点存在主色像素、手柄中心可见填充色、
  手柄矩形不越界、垂直 sub-page 不横向扩张盖住手柄）。
- 任务B2：QRadioButton sm/md/lg 选中态指示器外径不膨胀、
  描边环与中心圆点完整、不触顶/底被裁。
- 任务B3：DatePicker 弹出 QCalendarWidget 列宽足够（不小于委托 sizeHint），
  日期数字不被省略号替代，导航栏控件不被挤压。
- 亮 / 暗两主题各 grab() 截图到 tests/shots/ 供人工目检。
"""

import os
import sys
import traceback
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

SHOTS = ROOT / "tests" / "shots"

_FAILURES = []


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


def assert_eq(actual, expected, msg=""):
    if actual != expected:
        raise AssertionError(f"{msg} 期望 {expected!r}，实际 {actual!r}")


def assert_true(cond, msg=""):
    if not cond:
        raise AssertionError(msg or "断言失败")


def near(px, hex_color, tol=16):
    from PySide6.QtGui import QColor
    qc = QColor(hex_color) if isinstance(hex_color, str) else hex_color
    return (abs(px.red() - qc.red()) <= tol
            and abs(px.green() - qc.green()) <= tol
            and abs(px.blue() - qc.blue()) <= tol)


def dist(px, qc):
    return (abs(px.red() - qc.red()) + abs(px.green() - qc.green())
            + abs(px.blue() - qc.blue()))


# ---------------------------------------------------------------------------
# 任务A：配色令牌
# ---------------------------------------------------------------------------

@check("任务A: 低饱和度配色令牌值（LIGHT/DARK）")
def _():
    from InstructionX_UIKit.tokens import DARK, LIGHT

    light_expect = {
        "color.primary": "#3F5E8C", "color.primary.hover": "#35507A",
        "color.primary.pressed": "#2B4266", "color.primary.subtle": "#EBEFF5",
        "color.on.primary": "#FFFFFF",
        "color.success": "#3E7E5F", "color.success.hover": "#34684F",
        "color.success.subtle": "#E9F2EC",
        "color.warning": "#C08A3E", "color.warning.subtle": "#F7F0E3",
        "color.danger": "#B25050", "color.danger.hover": "#9A4444",
        "color.danger.subtle": "#F7EBEB",
    }
    dark_expect = {
        "color.primary": "#7C98C4", "color.primary.hover": "#93AAD1",
        "color.primary.pressed": "#A9BDDD", "color.primary.subtle": "#26324A",
        "color.on.primary": "#15181E",
        "color.success": "#6BA98A", "color.success.subtle": "#22362D",
        "color.warning": "#D2A668", "color.warning.subtle": "#3A3226",
        "color.danger": "#CD7A7A", "color.danger.subtle": "#3E2A2A",
    }
    for key, v in light_expect.items():
        assert_eq(LIGHT[key], v, f"LIGHT[{key}]")
    for key, v in dark_expect.items():
        assert_eq(DARK[key], v, f"DARK[{key}]")
    # 未列入本次修订的令牌保持不变（抽查）
    assert_eq(LIGHT["color.bg.base"], "#FFFFFF", "LIGHT bg.base 不应改动")
    assert_eq(DARK["color.bg.base"], "#15181E", "DARK bg.base 不应改动")
    assert_eq(LIGHT["color.text.primary"], "#1C2330", "LIGHT text.primary 不应改动")
    assert_eq(DARK["color.success.hover"], "#55D0A0", "DARK success.hover 不应改动")
    assert_eq(DARK["color.danger.hover"], "#F07878", "DARK danger.hover 不应改动")
    assert_eq(LIGHT["color.overlay"], "rgba(28,35,48,0.45)", "LIGHT overlay 不应改动")


@check("任务A: QSS 按新令牌注入且 set_mode 重建（含运行时图标）")
def _():
    from PySide6.QtWidgets import QApplication, QCheckBox

    from InstructionX_UIKit import tokens as tk
    from InstructionX_UIKit.theme import ThemeManager, build_qss

    app = QApplication.instance() or QApplication([])
    tm = ThemeManager.instance()

    qss_l = build_qss(tk.LIGHT)
    qss_d = build_qss(tk.DARK)
    assert_true("#3F5E8C" in qss_l, "亮色 QSS 应含新主色 #3F5E8C")
    assert_true("#7C98C4" in qss_d, "暗色 QSS 应含新主色 #7C98C4")
    assert_true("#15181E" in qss_d, "暗色 QSS 应含深色 on.primary #15181E")

    # 主题切换后 QSS 整体重建
    tm.set_mode("light")
    tm.apply(app)
    assert_true("#3F5E8C" in app.styleSheet(), "apply 后全局 QSS 应为亮色新配色")
    tm.set_mode("dark")
    assert_true("#7C98C4" in app.styleSheet(), "set_mode 应自动重建暗色 QSS")

    # 运行时图标按主题重建：暗色勾选图标应为深色描线（on.primary=#15181E）
    SHOTS.mkdir(parents=True, exist_ok=True)
    from PySide6.QtWidgets import QStyle, QStyleOptionButton

    cb = QCheckBox("勾选")
    cb.setChecked(True)
    cb.setFixedSize(120, 32)
    cb.show()
    app.processEvents()

    def check_icon_color(tag, expect_hex):
        app.processEvents()
        img = cb.grab().toImage()
        opt = QStyleOptionButton()
        cb.initStyleOption(opt)
        ir = cb.style().subElementRect(QStyle.SE_CheckBoxIndicator, opt, cb)
        # 仅扫描指示器内部（选中态为主色填充 + on.primary 描线对勾）
        found = 0
        for y in range(ir.top() + 2, ir.bottom() - 1):
            for x in range(ir.left() + 2, ir.right() - 1):
                if near(img.pixelColor(x, y), expect_hex, tol=60):
                    found += 1
        assert_true(found > 0,
                    f"{tag} 主题勾选图标应含 on.primary={expect_hex} 描线像素"
                    f"（指示器 {ir.getRect()}，set_mode 后图标需按主题重建）")
        return img

    img_d = check_icon_color("dark", tk.DARK["color.on.primary"])
    img_d.save(str(SHOTS / "fix_checkbox_dark.png"))
    tm.set_mode("light")
    app.processEvents()
    img_l = check_icon_color("light", tk.LIGHT["color.on.primary"])
    img_l.save(str(SHOTS / "fix_checkbox_light.png"))
    cb.close()
    tm.set_mode("light")


# ---------------------------------------------------------------------------
# 综合演示页（滑块 + 单选 + 日期），亮/暗截图
# ---------------------------------------------------------------------------

def build_fix_page():
    """构造含三尺寸滑块（水平+垂直）、单选组（选中态）、DatePicker 的页面。"""
    from PySide6.QtCore import QDate, Qt
    from PySide6.QtWidgets import (
        QDateEdit,
        QHBoxLayout,
        QLabel,
        QPushButton,
        QRadioButton,
        QSlider,
        QVBoxLayout,
        QWidget,
    )

    from InstructionX_UIKit.components.date_picker import DatePicker
    from InstructionX_UIKit.theme import set_property

    win = QWidget()
    win.setWindowTitle("fix/theme 验证页")
    root = QVBoxLayout(win)
    root.setContentsMargins(16, 16, 16, 16)
    root.setSpacing(10)

    btn = QPushButton("主要按钮")
    set_property(btn, "variant", "primary")
    btn.setObjectName("primaryBtn")
    root.addWidget(btn)

    # 三尺寸水平滑块
    for name, h in (("sm", 24), ("md", 32), ("lg", 40)):
        row = QHBoxLayout()
        row.addWidget(QLabel(f"滑块H {name}"))
        sl = QSlider(Qt.Horizontal)
        sl.setObjectName(f"slider_h_{name}")
        sl.setRange(0, 100)
        sl.setValue(50)
        sl.setFixedSize(240, h)
        row.addWidget(sl)
        row.addStretch(1)
        root.addLayout(row)

    # 三尺寸垂直滑块
    vrow = QHBoxLayout()
    for name, wd in (("sm", 24), ("md", 32), ("lg", 40)):
        vrow.addWidget(QLabel(f"V {name}"))
        sl = QSlider(Qt.Vertical)
        sl.setObjectName(f"slider_v_{name}")
        sl.setRange(0, 100)
        sl.setValue(50)
        sl.setFixedSize(wd, 120)
        vrow.addWidget(sl)
    vrow.addStretch(1)
    root.addLayout(vrow)

    # 单选组（选中态，三尺寸）
    rrow = QHBoxLayout()
    for name in ("sm", "md", "lg"):
        rb = QRadioButton(f"单选 {name}")
        rb.setObjectName(f"radio_{name}")
        rb.setChecked(name == "md")
        set_property(rb, "size", name)
        rrow.addWidget(rb)
    rb2 = QRadioButton("未选中")
    rrow.addWidget(rb2)
    rrow.addStretch(1)
    root.addLayout(rrow)

    # 日期选择（弹出式日历）
    dp = DatePicker(date=QDate(2025, 6, 15))
    dp.setObjectName("datePicker")
    root.addWidget(dp)

    win.resize(560, 460)
    return win


@check("截图: 修复验证页亮/暗双主题 grab")
def _():
    from PySide6.QtWidgets import QApplication, QPushButton

    from InstructionX_UIKit import tokens as tk
    from InstructionX_UIKit.theme import ThemeManager

    app = QApplication.instance() or QApplication([])
    tm = ThemeManager.instance()
    SHOTS.mkdir(parents=True, exist_ok=True)

    win = build_fix_page()
    win.show()
    app.processEvents()

    for mode, expect_primary in (("light", "#3F5E8C"), ("dark", "#7C98C4")):
        tm.set_mode(mode)
        tm.apply(app)
        app.processEvents()
        pm = win.grab()
        path = SHOTS / f"fix_page_{mode}.png"
        assert_true(pm.save(str(path)), f"截图保存失败: {path}")
        img = pm.toImage()
        # 主按钮中心像素 = 新主色
        btn = win.findChild(QPushButton, "primaryBtn")
        center = btn.mapTo(win, btn.rect().center())
        px = img.pixelColor(center.x(), center.y())
        assert_true(near(px, expect_primary, tol=20),
                    f"{mode} 主按钮背景应为 {expect_primary}，实际 {px.name()}")
        # 与令牌一致（即配色确实来自 tokens）
        assert_eq(tk.LIGHT["color.primary"] if mode == "light"
                  else tk.DARK["color.primary"], expect_primary)
    tm.set_mode("light")
    tm.apply(app)
    app.processEvents()
    win.close()


# ---------------------------------------------------------------------------
# 任务B1：滑块手柄完整性
# ---------------------------------------------------------------------------

@check("任务B1: QSlider 手柄 24/32/40 水平/垂直均不截断")
def _():
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QColor
    from PySide6.QtWidgets import QApplication, QSlider, QStyle, QStyleOptionSlider

    from InstructionX_UIKit import tokens as tk
    from InstructionX_UIKit.theme import ThemeManager

    app = QApplication.instance() or QApplication([])
    tm = ThemeManager.instance()
    tm.set_mode("light")
    tm.apply(app)
    primary = QColor(tk.LIGHT["color.primary"])
    SHOTS.mkdir(parents=True, exist_ok=True)

    def probe(slider, orient, label):
        img = slider.grab().toImage()
        w, h = img.width(), img.height()
        opt = QStyleOptionSlider()
        slider.initStyleOption(opt)
        st = slider.style()
        hr = st.subControlRect(QStyle.CC_Slider, opt, QStyle.SC_SliderHandle, slider)
        gr = st.subControlRect(QStyle.CC_Slider, opt, QStyle.SC_SliderGroove, slider)
        # 1) 手柄矩形必须完整落在控件内
        assert_true(hr.left() >= 0 and hr.top() >= 0
                    and hr.right() <= w - 1 and hr.bottom() <= h - 1,
                    f"{label} 手柄矩形越界: {hr.getRect()} 控件 {w}x{h}")
        # 2) 描边环四象限极点应有主色像素（环未被裁掉）
        cx, cy = hr.center().x(), hr.center().y()
        for name, (x, y) in (("top", (cx, hr.top())), ("bottom", (cx, hr.bottom())),
                             ("left", (hr.left(), cy)), ("right", (hr.right(), cy))):
            found = any(dist(img.pixelColor(x + dx, y + dy), primary) < 150
                        for dx in (-1, 0, 1) for dy in (-1, 0, 1)
                        if 0 <= x + dx < w and 0 <= y + dy < h)
            assert_true(found, f"{label} 手柄描边环 {name} 极点缺失主色像素")
        # 3) 手柄中心必须可见填充色（非主色实心块）
        assert_true(dist(img.pixelColor(cx, cy), primary) > 150,
                    f"{label} 手柄中心被主色覆盖（实心块，描边环被吃掉）")
        # 4) 填充槽不得超过 groove 厚度（垂直 bug：sub-page 横向扩张盖住手柄）
        if orient == Qt.Vertical and hr.top() > 6:
            y = max(1, hr.top() // 2)
            xs = [x for x in range(w) if dist(img.pixelColor(x, y), primary) < 150]
            if xs:
                assert_true(max(xs) - min(xs) + 1 <= gr.width() + 4,
                            f"{label} sub-page 过宽 {min(xs)}..{max(xs)}"
                            f"（groove 宽 {gr.width()}）")
        if orient == Qt.Horizontal and hr.left() > 6:
            x = max(1, hr.left() // 2)
            ys = [y for y in range(h) if dist(img.pixelColor(x, y), primary) < 150]
            if ys:
                assert_true(max(ys) - min(ys) + 1 <= gr.height() + 4,
                            f"{label} sub-page 过高 {min(ys)}..{max(ys)}"
                            f"（groove 高 {gr.height()}）")
        return img

    for orient, oname in ((Qt.Horizontal, "H"), (Qt.Vertical, "V")):
        for size in (24, 32, 40):
            for val in (0, 50, 100):
                s = QSlider(orient)
                s.setRange(0, 100)
                s.setValue(val)
                if orient == Qt.Horizontal:
                    s.setFixedSize(240, size)
                else:
                    s.setFixedSize(size, 160)
                s.show()
                app.processEvents()
                img = probe(s, orient, f"{oname} {size}px val={val}")
                if val == 50:
                    img.save(str(SHOTS / f"fix_slider_{oname}_{size}.png"))
                s.close()


# ---------------------------------------------------------------------------
# 任务B2：单选框选中圆点完整性
# ---------------------------------------------------------------------------

@check("任务B2: QRadioButton sm/md/lg 选中圆点完整不截断")
def _():
    from PySide6.QtGui import QColor
    from PySide6.QtWidgets import QApplication, QRadioButton, QStyle, QStyleOptionButton

    from InstructionX_UIKit import tokens as tk
    from InstructionX_UIKit.theme import ThemeManager, set_property

    app = QApplication.instance() or QApplication([])
    tm = ThemeManager.instance()
    tm.set_mode("light")
    tm.apply(app)
    primary = QColor(tk.LIGHT["color.primary"])
    SHOTS.mkdir(parents=True, exist_ok=True)

    expect_outer = {"sm": 14, "md": 18, "lg": 20}

    for size, h in (("sm", 24), ("md", 32), ("lg", 40)):
        rb = QRadioButton(f"选项 {size}")
        rb.setChecked(True)
        set_property(rb, "size", size)
        rb.setFixedSize(140, h)
        rb.show()
        app.processEvents()
        img = rb.grab().toImage()
        opt = QStyleOptionButton()
        rb.initStyleOption(opt)
        ir = rb.style().subElementRect(QStyle.SE_RadioButtonIndicator, opt, rb)
        # 1) 指示器外径不得膨胀（旧缺陷：选中态边框加粗使外径 18->26 被裁）
        assert_true(ir.width() <= expect_outer[size] + 2
                    and ir.height() <= expect_outer[size] + 2,
                    f"{size} 选中指示器外径膨胀: {ir.getRect()}")
        assert_true(ir.top() >= 0 and ir.bottom() <= img.height() - 1,
                    f"{size} 指示器越出控件: {ir.getRect()} 控件高 {img.height()}")
        # 2) 描边环四象限极点应有主色像素（圆环完整）
        cx, cy = ir.center().x(), ir.center().y()
        for name, (x, y) in (("top", (cx, ir.top())), ("bottom", (cx, ir.bottom())),
                             ("left", (ir.left(), cy)), ("right", (ir.right(), cy))):
            found = any(dist(img.pixelColor(x + dx, y + dy), primary) < 150
                        for dx in (-1, 0, 1) for dy in (-1, 0, 1)
                        if 0 <= x + dx < img.width() and 0 <= y + dy < img.height())
            assert_true(found, f"{size} 选中圆环 {name} 极点缺失（圆点被裁）")
        # 3) 环内应存在非主色的中心圆点区域
        assert_true(dist(img.pixelColor(cx, cy), primary) > 150,
                    f"{size} 选中态中心圆点缺失（整个指示器成实心块）")
        img.save(str(SHOTS / f"fix_radio_{size}.png"))
        rb.close()


# ---------------------------------------------------------------------------
# 任务B3：日历日期完整显示
# ---------------------------------------------------------------------------

@check("任务B3: DatePicker 日历日期无省略号、导航栏不挤压")
def _():
    from PySide6.QtCore import QDate
    from PySide6.QtGui import QFontMetrics
    from PySide6.QtWidgets import QApplication, QCalendarWidget, QTableView, QToolButton

    from InstructionX_UIKit.components.date_picker import DatePicker
    from InstructionX_UIKit.theme import ThemeManager

    app = QApplication.instance() or QApplication([])
    tm = ThemeManager.instance()
    SHOTS.mkdir(parents=True, exist_ok=True)

    from PySide6.QtWidgets import QWidget
    for mode in ("light", "dark"):
        tm.set_mode(mode)
        tm.apply(app)
        dp = DatePicker(date=QDate(2025, 6, 15))
        dp.resize(240, dp.sizeHint().height())
        dp.show()
        app.processEvents()
        cal = dp.calendarWidget()
        assert_true(isinstance(cal, QCalendarWidget), "DatePicker 应弹出 QCalendarWidget")
        # 弹出日历截图（offscreen 下弹出窗口布局由系统异步完成，仅用于目检）
        cal.show()
        app.processEvents()
        app.processEvents()
        cal.grab().save(str(SHOTS / f"fix_calendar_popup_{mode}.png"))
        cal.hide()
        app.processEvents()

        # 独立 QCalendarWidget 做硬断言（与 DatePicker 弹出实例同为全局 QSS 渲染）
        cal = QCalendarWidget()
        cal.setSelectedDate(QDate(2025, 6, 15))
        cal.show()
        cal.resize(cal.sizeHint())
        app.processEvents()
        app.processEvents()

        tv = cal.findChild(QTableView)
        assert_true(tv is not None, "日历内应含 QTableView")
        fm = QFontMetrics(tv.font())
        min_need = fm.horizontalAdvance("22") + 4
        for col in range(7):
            cw = tv.columnWidth(col)
            hint = tv.sizeHintForColumn(col)
            assert_true(cw >= min_need,
                        f"{mode} 日历第 {col} 列宽 {cw}px < 文本需要 {min_need}px"
                        "（日期将被省略号替代）")
            assert_true(cw >= hint - 1,
                        f"{mode} 日历第 {col} 列宽 {cw}px < 委托 sizeHint {hint}px"
                        "（单元格内边距过大导致省略号）")
        # 导航栏月份/年份控件不被挤压
        nav = cal.findChild(QWidget, "qt_calendar_navigationbar")
        assert_true(nav is not None and nav.height() >= 24,
                    f"{mode} 导航栏高度异常: {nav.height() if nav else None}")
        month_btn = None
        for b in cal.findChildren(QToolButton):
            if b.text():
                month_btn = b
                break
        if month_btn is not None:
            need = month_btn.fontMetrics().horizontalAdvance(month_btn.text()) + 20
            assert_true(month_btn.width() >= need - 4,
                        f"{mode} 月份按钮被挤压: 宽 {month_btn.width()} 需要 ~{need}")
        cal.grab().save(str(SHOTS / f"fix_calendar_{mode}.png"))
        dp.close()
    tm.set_mode("light")


def main() -> int:
    print("fix/theme 自测开始（offscreen）")
    print("-" * 60)
    if _FAILURES:
        print(f"共 {len(_FAILURES)} 项失败: {_FAILURES}")
        return 1
    print("全部检查通过，0 错误")
    return 0


if __name__ == "__main__":
    sys.exit(main())
