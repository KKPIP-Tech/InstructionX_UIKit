# -*- coding: utf-8 -*-
"""core 代理自测：设计令牌 + 主题系统（SPEC §2/§3/§4）。

直接运行（无 pytest 依赖）::

    QT_QPA_PLATFORM=offscreen python tests/test_core.py

覆盖：
- 令牌键完整性与 SPEC 数值抽查；
- ThemeManager 单例 / 信号 / set_mode / toggle / apply / tokens / T()；
- build_qss 选择器覆盖与亮暗参数化；
- set_property（含 size -> uiksize 别名）与输入控件高度 24/32/40；
- apply_shadow 三级阴影；
- 构造综合窗口，亮 / 暗两主题各 grab() 截图到 tests/shots/；
- 通过截图像素比对验证主题切换真实生效。
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


# ---------------------------------------------------------------------------
# 1. 设计令牌（SPEC §2）
# ---------------------------------------------------------------------------

@check("令牌键完整性与数值抽查")
def _():
    from InstructionX_UIKit.tokens import (
        DARK,
        DURATION,
        EASING,
        FONT_FAMILY,
        LIGHT,
        MONO_FAMILY,
        Breakpoint,
    )
    from PySide6.QtCore import QEasingCurve

    expected_keys = {
        # 色彩（SPEC §2.1，24 项）
        "color.bg.base", "color.bg.subtle", "color.bg.muted", "color.bg.elevated",
        "color.border", "color.border.strong",
        "color.text.primary", "color.text.secondary", "color.text.tertiary",
        "color.text.disabled",
        "color.primary", "color.primary.hover", "color.primary.pressed",
        "color.primary.subtle", "color.on.primary",
        "color.success", "color.success.hover", "color.success.subtle",
        "color.warning", "color.warning.subtle",
        "color.danger", "color.danger.hover", "color.danger.subtle",
        "color.overlay",
        # 字体（SPEC §2.2）
        "font.xs", "font.sm", "font.md", "font.lg",
        "font.title.sm", "font.title.md", "font.title.lg",
        "font.display", "font.hero",
        "font.weight.regular", "font.weight.medium", "font.weight.semibold",
        "font.weight.bold",
        "font.line_height.body", "font.line_height.title",
        # 间距（SPEC §2.3）
        "space.0", "space.05", "space.1", "space.2", "space.3", "space.4",
        "space.5", "space.6", "space.8", "space.10", "space.12", "space.16",
        # 圆角（SPEC §2.4）
        "radius.sm", "radius.md", "radius.lg", "radius.xl", "radius.pill",
        # 阴影（SPEC §2.5）
        "shadow.sm", "shadow.md", "shadow.lg",
        # 断点（SPEC §2.6）
        "breakpoint.xs", "breakpoint.sm", "breakpoint.md", "breakpoint.lg",
        "breakpoint.xl",
        # 动效（SPEC §2.7）
        "duration.instant", "duration.fast", "duration.normal",
        "duration.slow", "duration.slower",
        "easing.standard", "easing.entrance", "easing.spring",
        "easing.emphasis", "easing.linear",
    }
    for name, tokens in (("LIGHT", LIGHT), ("DARK", DARK)):
        missing = expected_keys - set(tokens)
        assert_eq(missing, set(), f"{name} 缺少令牌键")
    assert_eq(set(LIGHT), set(DARK), "亮暗令牌键集合必须一致")

    # 数值抽查（SPEC §2.1/§2.3/§2.4/§2.5/§2.7）
    spot = {
        "color.bg.base": ("#FFFFFF", "#15181E"),
        "color.bg.elevated": ("#FFFFFF", "#1F242E"),
        "color.border": ("#E3E6EB", "#2C333F"),
        "color.text.primary": ("#1C2330", "#E7EAF0"),
        "color.text.disabled": ("#C2C8D0", "#4A515C"),
        "color.primary": ("#3F5E8C", "#7C98C4"),
        "color.primary.hover": ("#35507A", "#93AAD1"),
        "color.primary.pressed": ("#2B4266", "#A9BDDD"),
        "color.primary.subtle": ("#EBEFF5", "#26324A"),
        "color.on.primary": ("#FFFFFF", "#15181E"),
        "color.success": ("#3E7E5F", "#6BA98A"),
        "color.warning": ("#C08A3E", "#D2A668"),
        "color.danger": ("#B25050", "#CD7A7A"),
        "color.danger.hover": ("#9A4444", "#F07878"),
        "color.overlay": ("rgba(28,35,48,0.45)", "rgba(0,0,0,0.55)"),
        "space.0": (0, 0), "space.05": (2, 2), "space.4": (16, 16),
        "space.16": (64, 64),
        "radius.sm": (4, 4), "radius.md": (6, 6), "radius.pill": (999, 999),
        "font.md": (13, 13), "font.hero": (32, 32),
        "font.weight.semibold": (600, 600),
        "font.line_height.body": (1.5, 1.5),
    }
    for key, (lv, dv) in spot.items():
        assert_eq(LIGHT[key], lv, f"LIGHT[{key}]")
        assert_eq(DARK[key], dv, f"DARK[{key}]")

    # 阴影参数（SPEC §2.5：亮色 RGB(16,24,40) 15/25/36%，暗色 RGB(0,0,0) 40/55/70%）
    assert_eq(LIGHT["shadow.sm"], {"blur": 6, "offset": (0, 1), "color": (16, 24, 40, 38)})
    assert_eq(LIGHT["shadow.md"]["blur"], 16)
    assert_eq(LIGHT["shadow.lg"]["offset"], (0, 8))
    assert_eq(DARK["shadow.sm"]["color"][:3], (0, 0, 0))
    assert DARK["shadow.sm"]["color"][3] > LIGHT["shadow.sm"]["color"][3]

    # 字族字符串（SPEC §2.2 原文）
    assert_eq(
        FONT_FAMILY,
        '"Segoe UI", "PingFang SC", "Microsoft YaHei", '
        '"Noto Sans CJK SC", "WenQuanYi Micro Hei", sans-serif',
    )
    assert_eq(MONO_FAMILY, '"Cascadia Code", "JetBrains Mono", "Consolas", monospace')

    # 断点（SPEC §2.6）
    cases = [(0, "xs"), (639, "xs"), (640, "sm"), (767, "sm"), (768, "md"),
             (1023, "md"), (1024, "lg"), (1439, "lg"), (1440, "xl"), (3840, "xl")]
    for w, expect in cases:
        assert_eq(Breakpoint.from_width(w), expect, f"Breakpoint.from_width({w})")

    # 动效（SPEC §2.7）
    assert_eq(DURATION, {"instant": 80, "fast": 120, "normal": 200,
                         "slow": 320, "slower": 480})
    assert_eq(EASING["standard"], QEasingCurve.OutCubic)
    assert_eq(EASING["entrance"], QEasingCurve.OutQuint)
    assert_eq(EASING["spring"], QEasingCurve.OutBack)
    assert_eq(EASING["emphasis"], QEasingCurve.OutQuart)
    assert_eq(EASING["linear"], QEasingCurve.Linear)


# ---------------------------------------------------------------------------
# 2. 主题系统 API（SPEC §3）
# ---------------------------------------------------------------------------

@check("ThemeManager 单例 / 信号 / set_mode / toggle / apply / tokens / T")
def _():
    from PySide6.QtWidgets import QApplication

    from InstructionX_UIKit import tokens as tk
    from InstructionX_UIKit.theme import T, ThemeManager, build_qss

    app = QApplication.instance() or QApplication([])
    tm = ThemeManager.instance()
    if ThemeManager.instance() is not tm:
        raise AssertionError("instance() 必须返回同一单例")
    assert_eq(tm.mode, "light", "默认模式")
    assert tm.tokens is tk.LIGHT

    events = []
    tm.theme_changed.connect(events.append)

    tm.apply(app)
    assert_eq(app.styleSheet(), build_qss(tk.LIGHT), "apply 后全局 QSS")

    tm.set_mode("dark")
    assert_eq(tm.mode, "dark")
    assert tm.tokens is tk.DARK
    assert_eq(T("color.primary"), "#7C98C4", "T() 应随主题切换")
    # 已 apply 过，set_mode 必须自动重设全局 QSS
    assert_eq(app.styleSheet(), build_qss(tk.DARK), "set_mode 自动重应用")
    assert_eq(events, ["dark"], "theme_changed 发射")

    tm.toggle()
    assert_eq(tm.mode, "light")
    assert_eq(events, ["dark", "light"])
    assert_eq(app.styleSheet(), build_qss(tk.LIGHT))
    assert_eq(T("space.4"), 16)

    # 非法模式
    try:
        tm.set_mode("blue")
    except ValueError:
        pass
    else:
        raise AssertionError("非法模式必须抛 ValueError")
    assert_eq(tm.mode, "light")


@check("build_qss 覆盖 SPEC §4 选择器且亮暗参数化")
def _():
    from InstructionX_UIKit import tokens as tk
    from InstructionX_UIKit.theme import build_qss

    qss_l = build_qss(tk.LIGHT)
    qss_d = build_qss(tk.DARK)
    if qss_l == qss_d:
        raise AssertionError("亮暗 QSS 必须不同（参数化生成）")
    if "#3F5E8C" not in qss_l or "#7C98C4" not in qss_d:
        raise AssertionError("QSS 未按令牌注入主题色")

    required = [
        # 基座
        "QWidget", "QToolTip", "QMenu", "QMenu::item", "QMenu::separator",
        "QScrollBar:vertical", "QScrollBar::handle:vertical",
        "QScrollBar::handle:vertical:hover", "QScrollBar:horizontal",
        "QSplitter::handle",
        # 按钮变体 / 尺寸 / 形状 / 状态
        'QPushButton[variant="primary"]', 'QPushButton[variant="default"]',
        'QPushButton[variant="dashed"]', 'QPushButton[variant="text"]',
        'QPushButton[variant="link"]', 'QPushButton[variant="danger"]',
        'QPushButton[size="sm"]', 'QPushButton[size="md"]', 'QPushButton[size="lg"]',
        'QPushButton[shape="circle"]', 'QPushButton[shape="round"]',
        "QPushButton:hover", "QPushButton:pressed", "QPushButton:disabled",
        # 输入与基础控件（SPEC §4 清单）
        "QLineEdit", "QTextEdit", "QPlainTextEdit", "QSpinBox", "QDoubleSpinBox",
        "QComboBox", "QDateEdit", "QTimeEdit", "QDateTimeEdit",
        "QSlider", "QProgressBar", "QCheckBox", "QRadioButton",
        "QTabWidget", "QTabBar", "QTableView", "QTreeView", "QListView",
        "QHeaderView", "QGroupBox", "QFrame", "QCalendarWidget",
        "QMenuBar", "QToolBar", "QStatusBar", "QDockWidget", "QMessageBox",
        # 高度选择器
        'QLineEdit[size="sm"]', 'QComboBox[size="lg"]',
    ]
    for needle in required:
        if needle not in qss_l:
            raise AssertionError(f"QSS 缺少选择器: {needle}")
    # 8px 细滚动条
    if "width: 8px" not in qss_l or "height: 8px" not in qss_l:
        raise AssertionError("滚动条必须为 8px 细样式")


@check("set_property 与输入控件高度 sm=24 / md=32 / lg=40")
def _():
    from PySide6.QtWidgets import QApplication, QComboBox, QLineEdit, QPushButton, QSpinBox

    from InstructionX_UIKit.theme import ThemeManager, set_property

    app = QApplication.instance() or QApplication([])
    tm = ThemeManager.instance()
    tm.set_mode("light")
    tm.apply(app)

    # size 与 QWidget 内置属性冲突，set_property 自动映射 uiksize
    btn = QPushButton("x")
    set_property(btn, "size", "sm")
    assert_eq(btn.property("uiksize"), "sm", "size 应映射为 uiksize")

    def height(widget, size=None):
        if size is not None:
            set_property(widget, "size", size)
        widget.ensurePolished()
        return widget.sizeHint().height()

    targets = {"sm": 24, "md": 32, "lg": 40}
    for cls in (QLineEdit, QComboBox, QSpinBox, QPushButton):
        for size, expect in targets.items():
            w = cls() if cls is not QPushButton else cls("按钮")
            if cls is QComboBox:
                w.addItem("选项")
            got = height(w, size)
            assert_eq(got, expect, f"{cls.__name__}[size={size}] 高度")
        # 默认（无属性）应为 md=32
        got = height(cls() if cls is not QPushButton else cls("按钮"))
        assert_eq(got, 32, f"{cls.__name__} 默认高度")


@check("apply_shadow 三级阴影按令牌生效")
def _():
    from PySide6.QtWidgets import QGraphicsDropShadowEffect, QWidget

    from InstructionX_UIKit import tokens as tk
    from InstructionX_UIKit.theme import ThemeManager, apply_shadow

    tm = ThemeManager.instance()
    tm.set_mode("light")
    for level in ("sm", "md", "lg"):
        w = QWidget()
        apply_shadow(w, level)
        eff = w.graphicsEffect()
        if not isinstance(eff, QGraphicsDropShadowEffect):
            raise AssertionError("必须安装 QGraphicsDropShadowEffect")
        spec = tk.LIGHT[f"shadow.{level}"]
        assert_eq(eff.blurRadius(), spec["blur"], f"{level} blur")
        assert_eq((eff.xOffset(), eff.yOffset()), tuple(map(float, spec["offset"])),
                  f"{level} offset")
        col = spec["color"]
        assert_eq(eff.color().getRgb(), col, f"{level} color")
    try:
        apply_shadow(QWidget(), "xl")
    except ValueError:
        pass
    else:
        raise AssertionError("非法级别必须抛 ValueError")


# ---------------------------------------------------------------------------
# 3. 综合窗口构建与双主题截图（SPEC §9）
# ---------------------------------------------------------------------------

def build_showcase():
    """构造包含 SPEC 要求控件的综合演示窗口。"""
    from PySide6.QtCore import QDate, Qt
    from PySide6.QtWidgets import (
        QCheckBox,
        QComboBox,
        QHBoxLayout,
        QLabel,
        QLineEdit,
        QProgressBar,
        QPushButton,
        QRadioButton,
        QSlider,
        QSpinBox,
        QTableWidget,
        QTableWidgetItem,
        QTabWidget,
        QVBoxLayout,
        QWidget,
        QCalendarWidget,
    )

    from InstructionX_UIKit.theme import set_property

    win = QWidget()
    win.setWindowTitle("core 主题演示")
    root = QVBoxLayout(win)
    root.setContentsMargins(20, 20, 20, 20)
    root.setSpacing(12)

    title = QLabel("PySide6 UI Kit — core 主题演示")
    title.setStyleSheet("font-size: 17px; font-weight: bold;")
    root.addWidget(title)

    # 第一行：按钮各变体
    row1 = QHBoxLayout()
    row1.setSpacing(8)
    for text, variant in (("主要按钮", "primary"), ("默认按钮", "default"),
                          ("虚线按钮", "dashed"), ("文字按钮", "text"),
                          ("链接按钮", "link"), ("危险按钮", "danger")):
        b = QPushButton(text)
        set_property(b, "variant", variant)
        row1.addWidget(b)
    row1.addStretch(1)
    root.addLayout(row1)

    # 第二行：输入控件
    row2 = QHBoxLayout()
    row2.setSpacing(8)
    edit = QLineEdit()
    edit.setPlaceholderText("请输入内容")
    combo = QComboBox()
    combo.addItems(["选项一", "选项二", "选项三"])
    spin = QSpinBox()
    spin.setValue(42)
    cb = QCheckBox("复选框")
    cb.setChecked(True)
    rb = QRadioButton("单选框")
    rb.setChecked(True)
    for w in (edit, combo, spin, cb, rb):
        row2.addWidget(w)
    row2.addStretch(1)
    root.addLayout(row2)

    # 第三行：滑块与进度条
    row3 = QHBoxLayout()
    row3.setSpacing(16)
    slider = QSlider(Qt.Horizontal)
    slider.setRange(0, 100)
    slider.setValue(45)
    bar = QProgressBar()
    bar.setRange(0, 100)
    bar.setValue(65)
    row3.addWidget(slider, 1)
    row3.addWidget(bar, 1)
    root.addLayout(row3)

    # 标签页：表格 + 日历
    tabs = QTabWidget()
    table = QTableWidget(4, 3)
    table.setHorizontalHeaderLabels(["名称", "状态", "数量"])
    table.setAlternatingRowColors(True)
    data = [("设计令牌", "完成", 74), ("主题系统", "完成", 5),
            ("组件库", "进行中", 60), ("动画库", "待办", 50)]
    for r, row in enumerate(data):
        for c, val in enumerate(row):
            table.setItem(r, c, QTableWidgetItem(str(val)))
    table.resizeColumnsToContents()
    tabs.addTab(table, "表格")

    cal = QCalendarWidget()
    cal.setSelectedDate(QDate(2025, 6, 15))
    tabs.addTab(cal, "日历")
    root.addWidget(tabs, 1)

    win.resize(780, 560)
    return win


@check("综合窗口构建 + 亮 / 暗主题截图与像素比对")
def _():
    from PySide6.QtWidgets import QApplication

    from InstructionX_UIKit import tokens as tk
    from InstructionX_UIKit.theme import ThemeManager

    app = QApplication.instance() or QApplication([])
    tm = ThemeManager.instance()
    SHOTS.mkdir(parents=True, exist_ok=True)

    from PySide6.QtWidgets import QTabWidget

    win = build_showcase()
    win.show()
    tabs = win.findChild(QTabWidget)

    grabbed = {}
    for mode, path in (("light", SHOTS / "core_light.png"),
                       ("dark", SHOTS / "core_dark.png")):
        tm.set_mode(mode)
        tm.apply(app)
        app.processEvents()
        pm = win.grab()
        if pm.isNull() or pm.width() < 100:
            raise AssertionError(f"{mode} 主题 grab() 失败")
        if not pm.save(str(path)):
            raise AssertionError(f"截图保存失败: {path}")
        grabbed[mode] = pm.toImage()
        # 翻到日历页补拍一张，验证 QCalendarWidget 主题化
        if tabs is not None:
            tabs.setCurrentIndex(1)
            app.processEvents()
            cal_pm = win.grab()
            cal_pm.save(str(SHOTS / f"core_calendar_{mode}.png"))
            tabs.setCurrentIndex(0)
            app.processEvents()

    tm.set_mode("light")
    tm.apply(app)
    app.processEvents()
    win.close()

    for path in (SHOTS / "core_light.png", SHOTS / "core_dark.png",
                 SHOTS / "core_calendar_light.png", SHOTS / "core_calendar_dark.png"):
        if not path.exists() or path.stat().st_size < 4096:
            raise AssertionError(f"截图缺失或过小: {path}")

    # 像素比对 1：窗口背景应贴近 bg.base（亮 #FFFFFF / 暗 #15181E）
    def near(px, hex_color, tol=12):
        from PySide6.QtGui import QColor
        qc = QColor(hex_color)
        return (abs(px.red() - qc.red()) <= tol
                and abs(px.green() - qc.green()) <= tol
                and abs(px.blue() - qc.blue()) <= tol)

    bg_l = grabbed["light"].pixelColor(6, 6)
    bg_d = grabbed["dark"].pixelColor(6, 6)
    if not near(bg_l, tk.LIGHT["color.bg.base"]):
        raise AssertionError(f"亮色背景采样异常: {bg_l.getRgb()}")
    if not near(bg_d, tk.DARK["color.bg.base"]):
        raise AssertionError(f"暗色背景采样异常: {bg_d.getRgb()}")
    if bg_l.getRgb() == bg_d.getRgb():
        raise AssertionError("亮暗截图背景必须不同")

    # 像素比对 2：主按钮中心应贴近 color.primary
    from PySide6.QtWidgets import QPushButton

    primary = [w for w in win.findChildren(QPushButton)
               if w.property("variant") == "primary"]
    if primary:
        btn = primary[0]
        center = btn.mapTo(win, btn.rect().center())
        pl = grabbed["light"].pixelColor(center.x(), center.y())
        pd = grabbed["dark"].pixelColor(center.x(), center.y())
        if not near(pl, tk.LIGHT["color.primary"], tol=16):
            raise AssertionError(f"亮色主按钮采样异常: {pl.getRgb()}")
        if not near(pd, tk.DARK["color.primary"], tol=16):
            raise AssertionError(f"暗色主按钮采样异常: {pd.getRgb()}")

    print(f"  截图: {SHOTS / 'core_light.png'}")
    print(f"  截图: {SHOTS / 'core_dark.png'}")


def main() -> int:
    print("core 自测开始（offscreen）")
    # 触发各检查（装饰器已在导入时执行，这里仅汇总）
    print("-" * 60)
    if _FAILURES:
        print(f"共 {len(_FAILURES)} 项失败: {_FAILURES}")
        return 1
    print("全部检查通过，0 错误")
    return 0


if __name__ == "__main__":
    sys.exit(main())
