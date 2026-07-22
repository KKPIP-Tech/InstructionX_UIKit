# -*- coding: utf-8 -*-
"""fix/inputs 修复验证：图标居中 / LineEdit 图标清晰度 / TextArea 首显高度。

直接运行（无 pytest 依赖）::

    QT_QPA_PLATFORM=offscreen python tests/test_fix_inputs.py

覆盖：
- IconButton：所有 size x shape x variant 下圆形几何精确为边长平方，
  文本符号与 QIcon 墨迹中心与控件几何中心偏差 <= 1px；
- LineEdit：前缀 / 后缀 / 清除 / 眼睛图标按令牌尺寸、按 DPR 矢量重绘
  （pixmap devicePixelRatio 与尺寸断言、非 1x 位图放大）、颜色取
  text.tertiary 并随主题刷新、槽位纵向居中且不压文字；
- TextArea：auto_height 构造 + setPlainText(3 行) 后 show，未输入任何
  字符时高度 ≈ 3 行内容高（容差 ±6px），无 minimumHeight 截断；
  max_rows 截断与滚动条策略；
- 亮 / 暗双主题整页截图 tests/shots/fix_inputs_<theme>.png 及健全性检查。
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


def settle(app, ms=200):
    from PySide6.QtCore import QElapsedTimer

    timer = QElapsedTimer()
    timer.start()
    while timer.elapsed() < ms:
        app.processEvents()
        time.sleep(0.004)


def _ink_bbox(img, target, x_range, y_range=None, tol=30, min_alpha=150):
    """在指定区域内收集接近 target 颜色的像素，返回 (x0,x1,y0,y1)。"""
    if y_range is None:
        y_range = range(img.height())
    xs, ys = [], []
    for y in y_range:
        for x in x_range:
            c = img.pixelColor(x, y)
            if (abs(c.red() - target.red()) <= tol
                    and abs(c.green() - target.green()) <= tol
                    and abs(c.blue() - target.blue()) <= tol
                    and c.alpha() >= min_alpha):
                xs.append(x)
                ys.append(y)
    if not xs:
        return None
    return min(xs), max(xs), min(ys), max(ys)


# ---------------------------------------------------------------------------
# 1. IconButton：几何与居中
# ---------------------------------------------------------------------------

@check("icon_button: 全部尺寸/形状/变体下墨迹居中且圆形几何精确")
def _():
    from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
    from PySide6.QtCore import Qt

    from InstructionX_UIKit.components.icon_button import _EDGE, IconButton

    def check_center(btn, ink_color, tag):
        btn.ensurePolished()
        img = btn.grab().toImage()
        w, h = img.width(), img.height()
        bb = _ink_bbox(img, ink_color, range(2, w - 2), range(2, h - 2),
                       tol=60, min_alpha=100)
        assert_true(bb is not None, f"{tag}: 未找到墨迹")
        cx = (bb[0] + bb[1]) / 2.0
        cy = (bb[2] + bb[3]) / 2.0
        dx = cx - (w - 1) / 2.0
        dy = cy - (h - 1) / 2.0
        assert_true(abs(dx) <= 1.0 and abs(dy) <= 1.0,
                    f"{tag}: 墨迹中心偏移 ({dx:+.2f},{dy:+.2f}) 超差")

    for size in ("sm", "md", "lg"):
        for shape in (None, "circle", "round"):
            for variant in (None, "default", "primary", "danger"):
                b = IconButton(text="+", variant=variant, size=size,
                               shape=shape)
                if shape == "circle":
                    assert_eq((b.width(), b.height()),
                              (_EDGE[size], _EDGE[size]),
                              f"circle {size}/{variant} 应为正圆")
                else:
                    assert_eq(b.height(), _EDGE[size],
                              f"{size}/{variant}/{shape} 总高应等于边长")
                ink = QColor(T("color.on.primary")) if variant in (
                    "primary", "danger") else QColor(T("color.text.primary"))
                check_center(b, ink, f"text+ {size}/{shape}/{variant}")
                b.set_symbol("×")
                check_center(b, ink, f"text× {size}/{shape}/{variant}")
                # QIcon（白色实心方块，墨迹即在图标中心）
                pm = QPixmap(32, 32)
                pm.fill(Qt.transparent)
                p = QPainter(pm)
                p.setPen(Qt.NoPen)
                p.setBrush(QColor("white"))
                p.drawRect(12, 12, 8, 8)
                p.end()
                b.set_icon(QIcon(pm))
                check_center(b, QColor("white"),
                             f"qicon {size}/{shape}/{variant}")


# ---------------------------------------------------------------------------
# 2. LineEdit：图标 DPR / 令牌尺寸 / 颜色 / 位置 / 主题刷新
# ---------------------------------------------------------------------------

@check("line_edit: 图标按 DPR 矢量重绘（非 1x 位图放大）")
def _():
    from PySide6.QtCore import QSize, Qt
    from PySide6.QtGui import QColor

    from InstructionX_UIKit.components.line_edit import _draw_eye, _render_icon

    dpr = 2.0
    edge = 16
    icon = _render_icon(_draw_eye(False), T("color.text.tertiary"), edge, dpr)
    pm = icon.pixmap(QSize(edge, edge), dpr)
    assert_eq(pm.devicePixelRatio(), dpr, "pixmap devicePixelRatio")
    assert_eq((pm.width(), pm.height()), (edge * 2, edge * 2),
              "pixmap 设备像素尺寸")
    # 瞳孔中心（设备像素）应精确命中令牌色
    c = pm.toImage().pixelColor(edge * 2 // 2, edge * 2 // 2)
    token = QColor(T("color.text.tertiary"))
    assert_true(abs(c.red() - token.red()) <= 4
                and abs(c.green() - token.green()) <= 4
                and abs(c.blue() - token.blue()) <= 4,
                f"瞳孔颜色应取 text.tertiary：{c.name()} vs {token.name()}")
    # 原生 2x 矢量渲染必须不同于 1x 位图放大（模糊插值）
    pm1 = _render_icon(_draw_eye(True), "#000000", edge, 1.0).pixmap(
        QSize(edge, edge), 1.0)
    upscaled = pm1.toImage().scaled(edge * 2, edge * 2,
                                    Qt.IgnoreAspectRatio,
                                    Qt.SmoothTransformation)
    native = _render_icon(_draw_eye(True), "#000000", edge, dpr).pixmap(
        QSize(edge, edge), dpr).toImage()
    assert_true(native != upscaled, "2x 图标疑似由 1x 位图直接放大")
    # 1x 渲染仍按 1.0 DPR
    pmx = _render_icon(_draw_eye(False), "#000000", edge).pixmap(
        QSize(edge, edge))
    assert_eq(pmx.devicePixelRatio(), 1.0, "默认 DPR 应为 1.0")


@check("line_edit: 槽位图标尺寸取令牌、清除/眼睛同处理、位置精确")
def _():
    from PySide6.QtCore import QSize, Qt
    from PySide6.QtGui import QColor

    from InstructionX_UIKit.components.line_edit import LineEdit, _icon_edge

    edges = {"sm": T("space.3"), "md": T("space.4"), "lg": T("space.5")}
    heights = {"sm": 24, "md": 32, "lg": 40}
    for size in ("sm", "md", "lg"):
        assert_eq(_icon_edge(size), edges[size], f"{size} 图标边长应取令牌")
        edit = LineEdit("user", size=size, clearable=True)
        edit.set_prefix_icon("@")
        edit.set_suffix_icon(".com")
        edge = edges[size]
        # 前缀 / 后缀 action 图标按令牌边长注册
        for act, tag in ((edit._prefix_action, "前缀"),
                         (edit._suffix_action, "后缀")):
            sizes = act.icon().availableSizes()
            assert_true(any(s.width() == edge and s.height() == edge
                            for s in sizes),
                        f"{size} {tag}图标缺少 {edge}x{edge} 尺寸: {sizes}")
        # 清除按钮（Qt 内置 action）图标同样被替换为令牌尺寸
        clear_act = edit._clear_action()
        assert_true(clear_act is not None, "未找到内置清除 action")
        assert_true(not clear_act.icon().isNull(), "清除 action 图标为空")
        cpm = clear_act.icon().pixmap(QSize(edge, edge),
                                      edit.devicePixelRatioF())
        assert_eq(cpm.devicePixelRatio(), edit.devicePixelRatioF(),
                  "清除图标 DPR 应与控件一致")
        assert_eq((cpm.width(), cpm.height()),
                  (int(edge * edit.devicePixelRatioF()),
                   int(edge * edit.devicePixelRatioF())),
                  "清除图标设备尺寸")
        # 清除功能仍可用（点击内部清除按钮控件）
        from PySide6.QtTest import QTest
        from PySide6.QtWidgets import QWidget

        cleaner = LineEdit("abc", size=size, clearable=True)
        cleaner.resize(200, heights[size])
        cleaner.show()
        _APP.processEvents()
        buttons = [k for k in cleaner.findChildren(QWidget)
                   if k.parent() is cleaner]
        assert_true(len(buttons) == 1, f"{size} 清除按钮控件数量异常: {buttons}")
        QTest.mouseClick(buttons[0], Qt.LeftButton)
        assert_eq(cleaner.text(), "", "点击清除按钮后文本应清空")
        cleaner.close()
        # 眼睛图标
        pwd = LineEdit("pw", size=size)
        pwd.set_password_mode(True)
        eye_pm = pwd._pwd_action.icon().pixmap(QSize(edge, edge))
        assert_true(not eye_pm.isNull(), "眼睛图标为空")
        assert_true(any(s.width() == edge
                        for s in pwd._pwd_action.icon().availableSizes()),
                    f"{size} 眼睛图标边长应为 {edge}")

        # ---- 位置：前缀在左槽位内纵向居中，后缀/眼睛在右侧，不压文字 ----
        edit.resize(220, heights[size])
        edit.show()
        _APP.processEvents()
        img = edit.grab().toImage()
        w, h = img.width(), img.height()
        tert = QColor(T("color.text.tertiary"))
        pre = _ink_bbox(img, tert, range(2, 30))  # 避开焦点描边抗锯齿像素
        assert_true(pre is not None, f"{size} 未找到前缀墨迹")
        pcy = (pre[2] + pre[3]) / 2.0
        assert_true(abs(pcy - (h - 1) / 2.0) <= 1.5,
                    f"{size} 前缀纵向偏移 {pcy - (h - 1) / 2.0:+.2f}px")
        assert_true(pre[0] >= 2 and pre[1] <= 30,
                    f"{size} 前缀应位于左侧槽位内: x[{pre[0]},{pre[1]}]")
        suf = _ink_bbox(img, tert, range(w - 60, w))
        assert_true(suf is not None, f"{size} 未找到后缀墨迹")
        scy = (suf[2] + suf[3]) / 2.0
        assert_true(abs(scy - (h - 1) / 2.0) <= 1.5,
                    f"{size} 后缀纵向偏移 {scy - (h - 1) / 2.0:+.2f}px")
        # 文本不得与图标重叠：文本最左墨迹（text.primary）应在前缀右侧
        dark = QColor(T("color.text.primary"))
        txt = _ink_bbox(img, dark, range(0, w - 60), tol=40)
        assert_true(txt is not None and txt[0] > pre[1],
                    f"{size} 文本与前缀图标重叠: text_x0={txt and txt[0]}"
                    f" prefix_x1={pre[1]}")
        # sizeHint 应为图标让出宽度
        plain = LineEdit(size=size)
        plain.ensurePolished()
        edit.ensurePolished()
        assert_true(edit.sizeHint().width()
                    >= plain.sizeHint().width() + 2 * edge - 4,
                    f"{size} sizeHint 未为前后缀图标加宽")
        edit.close()


@check("line_edit: 图标颜色随主题刷新")
def _():
    from PySide6.QtCore import QSize
    from PySide6.QtGui import QColor

    from InstructionX_UIKit.components.line_edit import LineEdit

    tm = ThemeManager.instance()
    edit = LineEdit(clearable=True)
    edit.set_prefix_icon("@")
    edit.set_password_mode(True)
    edge = 16
    light_pm = edit._prefix_action.icon().pixmap(QSize(edge, edge)).toImage()
    clear_light = edit._clear_action().icon().pixmap(QSize(edge, edge)).toImage()
    eye_light = edit._pwd_action.icon().pixmap(QSize(edge, edge)).toImage()
    tm.set_mode("dark")
    tm.apply(_APP)
    _APP.processEvents()
    try:
        dark_pm = edit._prefix_action.icon().pixmap(QSize(edge, edge)).toImage()
        clear_dark = edit._clear_action().icon().pixmap(
            QSize(edge, edge)).toImage()
        eye_dark = edit._pwd_action.icon().pixmap(QSize(edge, edge)).toImage()
        assert_true(light_pm != dark_pm, "前缀图标未随主题重绘")
        assert_true(clear_light != clear_dark, "清除图标未随主题重绘")
        assert_true(eye_light != eye_dark, "眼睛图标未随主题重绘")
        # 暗色墨迹应命中暗色 text.tertiary
        tert = QColor(T("color.text.tertiary"))
        bb = _ink_bbox(dark_pm, tert, range(edge), range(edge), tol=30,
                       min_alpha=120)
        assert_true(bb is not None, "暗色前缀图标墨迹颜色不符合 text.tertiary")
    finally:
        tm.set_mode("light")
        tm.apply(_APP)
        _APP.processEvents()


# ---------------------------------------------------------------------------
# 3. TextArea：auto_height 首显高度
# ---------------------------------------------------------------------------

@check("text_area: 构造 3 行文本 show 后高度即正确（无首显截断）")
def _():
    from InstructionX_UIKit.components.text_area import TextArea

    ta = TextArea(auto_height=True, min_rows=1, max_rows=10)
    ta.setPlainText("一\n二\n三")
    ta.resize(320, 100)
    ta.show()
    _APP.processEvents()
    settle(_APP, 100)
    row = ta._row_height()
    expected = (3 * row + 2 * ta.document().documentMargin()
                + ta._frame_padding())
    diff = abs(ta.height() - expected)
    assert_true(diff <= 6,
                f"show 后高度 {ta.height()} 与 3 行内容高 {expected} 差 {diff}px")
    # 无 minimumHeight 截断：min==max==h 且 viewport 容纳文档
    assert_eq(ta.minimumHeight(), ta.maximumHeight(), "min/max 高度应一致")
    assert_true(ta.viewport().height() + 1 >= ta.document().size().height(),
                f"viewport {ta.viewport().height()} 截断文档 "
                f"{ta.document().size().height()}")
    # 未输入任何字符时不得塌缩为单行/最小行高以下的过期值
    stale = row + ta._frame_padding()
    assert_true(ta.height() > stale + 6,
                f"高度 {ta.height()} 疑似构造期过期值（≈{stale}）")
    ta.close()


@check("text_area: 输入增长 / max_rows 截断 / 滚动条策略 / 空文本最小行")
def _():
    from PySide6.QtCore import Qt

    from InstructionX_UIKit.components.text_area import TextArea

    ta = TextArea(auto_height=True, min_rows=2, max_rows=4)
    ta.resize(320, 120)
    ta.show()
    _APP.processEvents()
    row = ta._row_height()
    margin_h = 2 * ta.document().documentMargin()
    pad = ta._frame_padding()
    h0 = ta.height()
    assert_true(abs(h0 - (2 * row + margin_h + pad)) <= 6,
                f"空文本应占 min_rows 高度: {h0}")
    ta.setPlainText("一\n二\n三")
    _APP.processEvents()
    h3 = ta.height()
    assert_true(h3 > h0, "高度应随行数增加")
    assert_true(abs(h3 - (3 * row + margin_h + pad)) <= 6,
                f"3 行高度偏差: {h3}")
    ta.setPlainText("一\n二\n三\n四\n五\n六\n七")
    _APP.processEvents()
    h7 = ta.height()
    assert_true(abs(h7 - (4 * row + margin_h + pad)) <= 6,
                f"超出 max_rows 应截断: {h7}")
    assert_eq(ta.verticalScrollBarPolicy(), Qt.ScrollBarAsNeeded,
              "超 max_rows 应允许滚动")
    ta.setPlainText("一")
    _APP.processEvents()
    assert_eq(ta.verticalScrollBarPolicy(), Qt.ScrollBarAlwaysOff,
              "行数回落后应隐藏滚动条")
    # 宽度变化导致折行时高度随动
    ta.setPlainText("这是一段足够长的文本用于验证折行高度随宽度变化而自动重算的行为")
    ta.resize(140, 120)
    _APP.processEvents()
    h_narrow = ta.height()
    ta.resize(420, 120)
    _APP.processEvents()
    h_wide = ta.height()
    assert_true(h_narrow > h_wide,
                f"变窄折行应变高: narrow={h_narrow} wide={h_wide}")
    ta.close()


# ---------------------------------------------------------------------------
# 4. 亮 / 暗双主题截图
# ---------------------------------------------------------------------------

def build_fix_page():
    """组装三个修复组件的演示页。"""
    from PySide6.QtWidgets import QGroupBox, QHBoxLayout, QVBoxLayout, QWidget

    from InstructionX_UIKit.components.icon_button import IconButton
    from InstructionX_UIKit.components.line_edit import LineEdit
    from InstructionX_UIKit.components.text_area import TextArea

    page = QWidget()
    page.setMinimumWidth(760)
    v = QVBoxLayout(page)
    v.setContentsMargins(16, 16, 16, 16)
    v.setSpacing(12)

    box1 = QGroupBox("icon_button 图标按钮（居中）")
    h1 = QHBoxLayout(box1)
    for size in ("sm", "md", "lg"):
        for shape, variant in ((None, None), ("circle", "primary"),
                               ("round", "default"), ("circle", "danger")):
            h1.addWidget(IconButton(text="+", variant=variant, size=size,
                                    shape=shape))
    star = IconButton(text="★", variant="default", shape="circle")
    h1.addWidget(star)
    h1.addStretch(1)
    v.addWidget(box1)

    box2 = QGroupBox("line_edit 输入框（图标清晰 / 位置 / 主题刷新）")
    h2 = QHBoxLayout(box2)
    e1 = LineEdit("user", clearable=True)
    e1.set_prefix_icon("@")
    e1.set_suffix_icon(".com")
    e2 = LineEdit("secret")
    e2.set_password_mode(True)
    e3 = LineEdit(placeholder="小号", size="sm", clearable=True)
    e3.set_prefix_icon("@")
    e4 = LineEdit(placeholder="大号", size="lg")
    e4.set_suffix_icon("搜")
    for w_ in (e1, e2, e3, e4):
        w_.setMinimumWidth(160)
        h2.addWidget(w_)
    h2.addStretch(1)
    v.addWidget(box2)

    box3 = QGroupBox("text_area 文本域（auto_height 首显即正确）")
    h3 = QHBoxLayout(box3)
    t1 = TextArea(auto_height=True, min_rows=1, max_rows=10,
                  show_count=True, max_length=200)
    t1.setPlainText("第一行\n第二行\n第三行")
    t1.setMinimumWidth(340)
    t2 = TextArea(auto_height=True, min_rows=2, max_rows=4,
                  placeholder="自适应高度占位")
    t2.setMinimumWidth(300)
    h3.addWidget(t1)
    h3.addWidget(t2)
    h3.addStretch(1)
    v.addWidget(box3)
    return page


@check("亮 / 暗双主题截图与健全性检查")
def _():
    from PySide6.QtGui import QColor

    from InstructionX_UIKit import tokens as tk

    tm = ThemeManager.instance()
    SHOTS.mkdir(parents=True, exist_ok=True)
    page = build_fix_page()
    page.show()
    _APP.processEvents()
    settle(_APP, 300)

    grabbed = {}
    for mode in ("light", "dark"):
        tm.set_mode(mode)
        tm.apply(_APP)
        settle(_APP, 250)
        pm = page.grab()
        if pm.isNull() or pm.width() < 400 or pm.height() < 150:
            raise AssertionError(f"{mode} grab() 尺寸异常: "
                                 f"{pm.width()}x{pm.height()}")
        path = SHOTS / f"fix_inputs_{mode}.png"
        if not pm.save(str(path)):
            raise AssertionError(f"截图保存失败: {path}")
        grabbed[mode] = pm.toImage()
    tm.set_mode("light")
    tm.apply(_APP)
    _APP.processEvents()
    page.close()

    for mode in ("light", "dark"):
        path = SHOTS / f"fix_inputs_{mode}.png"
        assert_true(path.exists() and path.stat().st_size > 1024,
                    f"截图缺失或过小: {path}")
        img = grabbed[mode]
        colors = set()
        for ix in range(1, 6):
            for iy in range(1, 6):
                colors.add(img.pixelColor(img.width() * ix // 6,
                                          img.height() * iy // 6).rgba())
        assert_true(len(colors) > 1, f"{mode} 截图为单色，渲染异常")

    def near(px, hex_color, tol=12):
        qc = QColor(hex_color)
        return (abs(px.red() - qc.red()) <= tol
                and abs(px.green() - qc.green()) <= tol
                and abs(px.blue() - qc.blue()) <= tol)

    bg_l = grabbed["light"].pixelColor(4, 4)
    bg_d = grabbed["dark"].pixelColor(4, 4)
    assert_true(near(bg_l, tk.LIGHT["color.bg.base"]),
                f"亮色背景采样异常: {bg_l.getRgb()}")
    assert_true(near(bg_d, tk.DARK["color.bg.base"]),
                f"暗色背景采样异常: {bg_d.getRgb()}")
    print(f"  截图: {SHOTS / 'fix_inputs_light.png'}")
    print(f"  截图: {SHOTS / 'fix_inputs_dark.png'}")


def main() -> int:
    print("fix/inputs 修复验证开始（offscreen）")
    print("-" * 60)
    if _FAILURES:
        print(f"共 {len(_FAILURES)} 项失败: {_FAILURES}")
        return 1
    print("全部检查通过，0 错误")
    return 0


if __name__ == "__main__":
    sys.exit(main())
