# -*- coding: utf-8 -*-
"""fix/f2 修复验证：LineEdit 垂直居中 / 槽位遮挡，Popover 气泡自然度。

直接运行（无 pytest 依赖）::

    QT_QPA_PLATFORM=offscreen python tests/test_fix_f2.py

覆盖：
- LineEdit：sm/md/lg（24/32/40）三档下文本墨迹中心与控件中心偏差 <= 1px；
  右侧槽位视觉顺序 [后缀][清除 ×][眼睛]，各槽位墨迹 bbox 互不相交；
  多字符后缀文本（".com"）按真实字宽绘制（不再压入正方形图标），
  超长后缀时 textMargins 为正文预留空间，正文墨迹与后缀墨迹不相交；
  亮 / 暗截图 tests/shots/fixf2_lineedit_<theme>_after.png。
- Popover：四方位 x 亮 / 暗截图 tests/shots/fixf2_popover_<p>_<t>_after.png；
  箭头为 ~8px 等腰三角形且对准锚点中心；箭头与主体填充色一致；
  箭头与主体相接带无杂色（无缝无黑边）；120ms 淡入 + 上移入场动画；
  暗色描边取 border.strong。
- before/after 对比：tests/shots/fixf2_*_before.png 为修复前（HEAD）工件，
  后缀区墨迹宽度对比证明修复生效。
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


def settle(app, ms=200):
    from PySide6.QtCore import QElapsedTimer

    timer = QElapsedTimer()
    timer.start()
    while timer.elapsed() < ms:
        app.processEvents()
        time.sleep(0.004)


def _near(c, target, tol):
    return (abs(c.red() - target.red()) <= tol
            and abs(c.green() - target.green()) <= tol
            and abs(c.blue() - target.blue()) <= tol)


def _ink_bbox(img, target, x_range, y_range=None, tol=40, min_alpha=120):
    """在指定区域内收集接近 target 颜色的像素，返回 (x0,x1,y0,y1)。"""
    if y_range is None:
        y_range = range(img.height())
    xs, ys = [], []
    for y in y_range:
        for x in x_range:
            c = img.pixelColor(x, y)
            if _near(c, target, tol) and c.alpha() >= min_alpha:
                xs.append(x)
                ys.append(y)
    if not xs:
        return None
    return min(xs), max(xs), min(ys), max(ys)


def _slot_ink_bbox(img, tert, x_range, y_range, tol=24, min_alpha=120):
    """text.tertiary 墨迹盒；附加蓝灰判据，排除正文抗锯齿的近似灰像素。"""
    xs, ys = [], []
    for y in y_range:
        for x in x_range:
            c = img.pixelColor(x, y)
            if (_near(c, tert, tol) and c.alpha() >= min_alpha
                    and c.blue() - c.red() >= 10):
                xs.append(x)
                ys.append(y)
    if not xs:
        return None
    return min(xs), max(xs), min(ys), max(ys)


# ---------------------------------------------------------------------------
# 1. LineEdit：三档文本垂直居中
# ---------------------------------------------------------------------------

_HEIGHTS = {"sm": 24, "md": 32, "lg": 40}


@check("line_edit: sm/md/lg 三档文本墨迹精确垂直居中（±1px）")
def _():
    from PySide6.QtGui import QColor

    from InstructionX_UIKit.components.line_edit import LineEdit

    dark = QColor(T("color.text.primary"))
    for size in ("sm", "md", "lg"):
        h = _HEIGHTS[size]
        for text in ("Hello", "用户邮箱", "Aa"):
            e = LineEdit(text, size=size, clearable=True)
            e.set_suffix_icon(".com")
            e.resize(260, h)
            e.show()
            _APP.processEvents()
            e.clearFocus()  # 去掉光标竖线，避免污染墨迹盒
            _APP.processEvents()
            img = e.grab().toImage()
            bb = _ink_bbox(img, dark, range(2, img.width() - 2),
                           range(2, img.height() - 2), tol=60, min_alpha=100)
            assert_true(bb is not None, f"{size} {text!r} 未找到文本墨迹")
            cy = (bb[2] + bb[3]) / 2.0
            dy = cy - (h - 1) / 2.0
            assert_true(abs(dy) <= 1.0,
                        f"{size} {text!r} 墨迹中心偏移 {dy:+.2f}px 超差 "
                        f"(bbox={bb}, h={h})")
            e.close()


# ---------------------------------------------------------------------------
# 2. LineEdit：槽位顺序 [后缀][清除 ×][眼睛] 且不重叠
# ---------------------------------------------------------------------------

@check("line_edit: 槽位顺序 [后缀][清除×][眼睛]，墨迹 bbox 不相交")
def _():
    from PySide6.QtGui import QColor

    from InstructionX_UIKit.components.line_edit import LineEdit

    tert = QColor(T("color.text.tertiary"))
    for size in ("sm", "md", "lg"):
        h = _HEIGHTS[size]
        e = LineEdit("secret", size=size, clearable=True)
        e.set_suffix_icon(".com")
        e.set_password_mode(True)
        e.resize(280, h)
        e.show()
        _APP.processEvents()
        settle(_APP, 250)  # 等待清除按钮淡入
        img = e.grab().toImage()
        w = img.width()

        suffix_btn = e._slot_button(e._suffix_action)
        clear_btn = e._slot_button(e._clear_action())
        eye_btn = e._slot_button(e._pwd_action)
        assert_true(suffix_btn is not None and clear_btn is not None
                    and eye_btn is not None, f"{size} 槽位按钮缺失")
        # 几何顺序：后缀 < 清除 < 眼睛
        assert_true(suffix_btn.x() < clear_btn.x() < eye_btn.x(),
                    f"{size} 槽位几何顺序错误: suffix@{suffix_btn.x()} "
                    f"clear@{clear_btn.x()} eye@{eye_btn.x()}")
        assert_true(eye_btn.geometry().right() >= w - 30,
                    f"{size} 眼睛应位于最右槽位: {eye_btn.geometry()}")

        # 各槽位墨迹（同取 text.tertiary，按几何区域分离，蓝灰判据）
        y_all = range(1, h - 1)
        suf = _slot_ink_bbox(img, tert, range(0, clear_btn.x()), y_all)
        clr = _slot_ink_bbox(img, tert, range(clear_btn.x(), eye_btn.x()),
                             y_all)
        eye = _slot_ink_bbox(img, tert, range(eye_btn.x(), w), y_all)
        assert_true(suf is not None, f"{size} 未找到后缀墨迹")
        assert_true(clr is not None, f"{size} 未找到清除×墨迹")
        assert_true(eye is not None, f"{size} 未找到眼睛墨迹")
        assert_true(suf[1] < clr[0],
                    f"{size} 后缀与清除×墨迹相交: {suf} vs {clr}")
        assert_true(clr[1] < eye[0],
                    f"{size} 清除×与眼睛墨迹相交: {clr} vs {eye}")
        # 多字符后缀按真实字宽绘制（不再压入正方形图标）
        edge = {"sm": 12, "md": 16, "lg": 20}[size]
        assert_true(suf[1] - suf[0] + 1 > edge,
                    f"{size} 后缀墨迹宽 {suf[1] - suf[0] + 1}px，"
                    f"疑似仍被压入 {edge}px 方形图标")
        # 后缀墨迹垂直居中（±1.5px）
        scy = (suf[2] + suf[3]) / 2.0
        assert_true(abs(scy - (h - 1) / 2.0) <= 1.5,
                    f"{size} 后缀墨迹纵向偏移 {scy - (h - 1) / 2.0:+.2f}px")
        e.close()


@check("line_edit: 超长后缀为正文预留空间，正文与后缀墨迹不相交")
def _():
    from PySide6.QtGui import QColor

    from InstructionX_UIKit.components.line_edit import LineEdit

    dark = QColor(T("color.text.primary"))
    tert = QColor(T("color.text.tertiary"))
    e = LineEdit("a-very-long-user-name@some-mail-provider", clearable=True)
    e.set_suffix_icon("@gmail.com")
    e.resize(240, 32)
    e.show()
    _APP.processEvents()
    e.clearFocus()
    _APP.processEvents()
    assert_true(e.textMargins().right() > 0,
                "超长后缀应通过 textMargins 为正文预留空间")
    img = e.grab().toImage()
    suffix_btn = e._slot_button(e._suffix_action)
    clear_btn = e._slot_button(e._clear_action())
    assert_true(suffix_btn is not None and clear_btn is not None, "槽位按钮缺失")
    # 后缀墨迹带（蓝灰判据，避免正文抗锯齿边缘被误判为 tert 色）
    suf = _slot_ink_bbox(img, tert, range(0, clear_btn.x()), range(1, 31))
    assert_true(suf is not None, "未找到后缀墨迹")
    # 正文墨迹右缘不得进入后缀墨迹带
    txt = _ink_bbox(img, dark, range(0, suf[1] + 1), range(1, 31), tol=60)
    if txt is not None:
        assert_true(txt[1] < suf[0],
                    f"正文与后缀墨迹相交: text_x1={txt[1]} suffix_x0={suf[0]}")
    e.close()


# ---------------------------------------------------------------------------
# 3. LineEdit：亮 / 暗截图 + before/after 后缀墨迹宽度对比
# ---------------------------------------------------------------------------

def build_lineedit_page():
    from PySide6.QtWidgets import QVBoxLayout, QWidget

    from InstructionX_UIKit.components.line_edit import LineEdit

    page = QWidget()
    v = QVBoxLayout(page)
    v.setContentsMargins(16, 16, 16, 16)
    v.setSpacing(10)
    for size in ("sm", "md", "lg"):
        e = LineEdit("user@example", size=size, clearable=True)
        e.set_prefix_icon("@")
        e.set_suffix_icon(".com")
        e.setMinimumWidth(280)
        v.addWidget(e)
    e2 = LineEdit("secret", clearable=True)
    e2.set_password_mode(True)
    e2.set_suffix_icon(".com")
    e2.setMinimumWidth(280)
    v.addWidget(e2)
    return page


@check("line_edit: 亮 / 暗截图与 before/after 后缀墨迹宽度对比")
def _():
    from PySide6.QtGui import QColor

    tm = ThemeManager.instance()
    SHOTS.mkdir(parents=True, exist_ok=True)
    page = build_lineedit_page()
    page.show()
    _APP.processEvents()
    settle(_APP, 300)

    after = {}
    for mode in ("light", "dark"):
        tm.set_mode(mode)
        tm.apply(_APP)
        settle(_APP, 250)
        pm = page.grab()
        path = SHOTS / f"fixf2_lineedit_{mode}_after.png"
        assert_true(pm.save(str(path)), f"截图保存失败: {path}")
        after[mode] = pm.toImage()
    tm.set_mode("light")
    tm.apply(_APP)
    _APP.processEvents()
    page.close()

    # 修复后：md 行（第 2 行）后缀 ".com" 墨迹宽度应接近真实字宽（>20px）
    tert = QColor(T("color.text.tertiary"))
    img = after["light"]
    md_row_y = range(50, 82)  # 布局：margins16 + 24 + spacing10 → md 行 y≈50..82
    suf = _ink_bbox(img, tert, range(240, 296), md_row_y)
    assert_true(suf is not None, "md 行后缀墨迹缺失")
    after_w = suf[1] - suf[0] + 1
    assert_true(after_w > 20, f"修复后后缀墨迹宽 {after_w}px，疑似仍被压缩")

    # 修复前工件：同位置后缀被压入 16px 方形图标（墨迹宽度明显更小）
    before_path = SHOTS / "fixf2_lineedit_light_before.png"
    assert_true(before_path.exists(), f"缺少 before 截图: {before_path}")
    from PySide6.QtGui import QImage
    before = QImage(str(before_path))
    suf_b = _ink_bbox(before, tert, range(240, 296), md_row_y)
    if suf_b is not None:
        before_w = suf_b[1] - suf_b[0] + 1
        assert_true(after_w > before_w,
                    f"before/after 无差异: before={before_w} after={after_w}")
        print(f"  后缀墨迹宽度: before={before_w}px -> after={after_w}px")
    for mode in ("light", "dark"):
        for kind in ("before", "after"):
            p = SHOTS / f"fixf2_lineedit_{mode}_{kind}.png"
            assert_true(p.exists() and p.stat().st_size > 1024,
                        f"截图缺失或过小: {p}")
    print(f"  截图: {SHOTS / 'fixf2_lineedit_light_after.png'}")
    print(f"  截图: {SHOTS / 'fixf2_lineedit_dark_after.png'}")


# ---------------------------------------------------------------------------
# 4. Popover：四方位 x 亮 / 暗截图 + 箭头 / 阴影 / 描边断言
# ---------------------------------------------------------------------------

@check("popover: 四方位亮/暗截图、箭头形态 / 对齐 / 填色 / 接缝断言")
def _():
    from PySide6.QtGui import QColor
    from PySide6.QtWidgets import QPushButton, QWidget

    from InstructionX_UIKit.components.popover import Popover

    tm = ThemeManager.instance()
    SHOTS.mkdir(parents=True, exist_ok=True)
    pops = []
    try:
        for mode in ("light", "dark"):
            tm.set_mode(mode)
            tm.apply(_APP)
            settle(_APP, 150)
            bg = QColor(T("color.bg.elevated"))
            border = QColor(T("color.border.strong" if mode == "dark"
                              else "color.border"))
            for placement in ("top", "bottom", "left", "right"):
                host = QWidget()
                host.resize(480, 360)
                anchor = QPushButton("anchor", host)
                anchor.move(200, 160)
                anchor.resize(90, 32)
                host.show()
                settle(_APP, 100)
                from PySide6.QtCore import QSize
                from PySide6.QtWidgets import QLabel
                body = QLabel("")
                body.setFixedSize(QSize(64, 36))
                # 无标题 + 透明空标签：卡体填充 / 接缝断言不受内容像素干扰
                pop = Popover("", body)
                pops.append(pop)
                pop.show_for(anchor, placement=placement)
                # 入场动画：120ms 淡入 + 上移
                assert_true(pop.windowOpacity() < 1.0,
                            f"{placement}/{mode} 缺少淡入入场动画")
                settle(_APP, 350)
                assert_true(abs(pop.windowOpacity() - 1.0) < 1e-6,
                            f"{placement}/{mode} 动画结束后透明度应恢复 1")
                pm = pop.grab()
                path = SHOTS / f"fixf2_popover_{placement}_{mode}_after.png"
                assert_true(pm.save(str(path)), f"截图保存失败: {path}")
                img = pm.toImage()
                assert_true(pop.placement() == placement,
                            f"{placement}/{mode} 发生翻转: {pop.placement()}")

                card = pop._card_rect()
                # 箭头中心应对准锚点中心（控件坐标）
                anchor_g = anchor.mapToGlobal(anchor.rect().center())
                local = pop.mapFromGlobal(anchor_g)
                vertical = placement in ("top", "bottom")

                # -- 沿中轴采样：卡体内 -> 卡体边缘 -> 箭头尖端 --
                if vertical:
                    axis = local.x()
                    edge = card.bottom() if placement == "top" else card.top()
                    step = 1 if placement == "top" else -1
                else:
                    axis = local.y()
                    edge = card.right() if placement == "left" else card.left()
                    step = 1 if placement == "left" else -1
                axis = int(round(axis))

                def px(d, off=0):
                    if vertical:
                        return img.pixelColor(axis + off, int(round(edge)) + d * step)
                    return img.pixelColor(int(round(edge)) + d * step, axis + off)

                # 卡体内部填充色（取右上角内测点，避开标题 / 正文文本）
                inner = img.pixelColor(int(card.right()) - 8,
                                       int(card.top()) + 8)
                assert_true(_near(inner, bg, 12) and inner.alpha() >= 250,
                            f"{placement}/{mode} 卡体填充色异常: {inner.name()}")
                # 箭头尖端内（卡体边缘外 5px）填充色与主体一致
                tip = px(5)
                assert_true(_near(tip, bg, 12) and tip.alpha() >= 250,
                            f"{placement}/{mode} 箭头填充色与主体不一致: "
                            f"{tip.name()} vs {bg.name()}")
                # 箭头可见高度：从中轴向外的连续 bg 墨迹长度 ≈ 8-1（底边沉入）
                run = 0
                for d in range(1, 12):
                    c = px(d)
                    if _near(c, bg, 30) and c.alpha() >= 200:
                        run = d
                    else:
                        break
                assert_true(5 <= run <= 9,
                            f"{placement}/{mode} 箭头可见高度 {run}px，"
                            f"应为 8px 等腰三角形（底边沉入 1px）")
                # 等腰对称：尖端内 3px 处左右半宽差 <= 1.5px
                left = right = 0
                for off in range(1, 12):
                    if _near(px(3, -off), bg, 40) and px(3, -off).alpha() >= 150:
                        left = off
                    else:
                        break
                for off in range(1, 12):
                    if _near(px(3, off), bg, 40) and px(3, off).alpha() >= 150:
                        right = off
                    else:
                        break
                assert_true(abs(left - right) <= 1.5,
                            f"{placement}/{mode} 箭头不对称: 左{left} 右{right}")
                # 接缝带（卡体边缘 ±2px，箭头底边宽范围内）无杂色：
                # 每个像素必须是 主体/描边色，或低透明阴影，不允许黑洞/黑缝
                stray = []
                half = 9
                for d in range(-2, 3):
                    for off in range(-half, half + 1):
                        c = px(d, off)
                        if c.alpha() >= 250 and not _near(c, bg, 60) \
                                and not _near(c, border, 60):
                            stray.append((d, off, c.name()))
                assert_true(not stray,
                            f"{placement}/{mode} 箭头接缝存在杂色: {stray[:4]}")
                pop.hide()
                host.close()
    finally:
        tm.set_mode("light")
        tm.apply(_APP)
        _APP.processEvents()

    for mode in ("light", "dark"):
        for placement in ("top", "bottom", "left", "right"):
            for kind in ("before", "after"):
                p = SHOTS / f"fixf2_popover_{placement}_{mode}_{kind}.png"
                assert_true(p.exists() and p.stat().st_size > 512,
                            f"截图缺失或过小: {p}")
    print(f"  截图: {SHOTS}/fixf2_popover_<方位>_<主题>_[before|after].png")


def main() -> int:
    print("fix/f2 修复验证开始（offscreen）")
    print("-" * 60)
    if _FAILURES:
        print(f"共 {len(_FAILURES)} 项失败: {_FAILURES}")
        return 1
    print("全部检查通过，0 错误")
    return 0


if __name__ == "__main__":
    sys.exit(main())
