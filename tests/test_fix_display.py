# -*- coding: utf-8 -*-
"""展示修复回归测试（R3）：瀑布流不等高、徽标 z-order/99+、气泡阴影。

直接运行（无 pytest 依赖）::

    QT_QPA_PLATFORM=offscreen python tests/test_fix_display.py

断言：
- 瀑布流：同列卡片高度不全相等（真正的不等高瀑布流）、渲染高度等于
  固定高度（列内不被拉伸）、断点列数 2/2/3/4、最短列优先分配均衡；
- 徽标：``99+`` 文本 boundingRect 完全落在角标 rect 内、角标是被包裹
  控件之上的顶层子控件（children 末尾 + 像素级遮挡验证）、resize /
  show 后保持顶层、独立点模式不受影响；
- 气泡：``Qt.Popup | Qt.FramelessWindowHint`` + ``WA_TranslucentBackground``，
  四个方位实例化弹出并截图，阴影区域柔和可见、箭头与底色一致。

截图输出 ``tests/shots/fix_display_*.png``（亮 / 暗）。任何异常记为
失败，退出码 1。
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
_shots = 0


def _check(name, fn):
    """登记一项检查，异常即记为失败。"""
    try:
        fn()
        print(f"  [通过] {name}")
    except Exception:
        _FAILURES.append(name)
        print(f"  [失败] {name}")
        traceback.print_exc()


def _save(pm, name):
    """保存截图并校验非空。"""
    global _shots
    if pm.isNull() or pm.width() < 10 or pm.height() < 10:
        raise AssertionError(f"grab() 返回空图像: {name}")
    path = SHOTS / name
    if not pm.save(str(path)):
        raise AssertionError(f"截图保存失败: {path}")
    if path.stat().st_size < 1024:
        raise AssertionError(f"截图文件过小: {path}")
    _shots += 1
    print(f"    截图: {path.name} ({pm.width()}x{pm.height()})")


def _red_dominant(c) -> bool:
    """像素是否红色主导（danger 角标色，亮 #D94848 / 暗 #E86060）。"""
    return c.alpha() > 200 and c.red() > 150 and c.red() > c.green() + 40 \
        and c.red() > c.blue() + 40


def main() -> int:
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QFontMetrics
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import (
        QApplication,
        QHBoxLayout,
        QPushButton,
        QWidget,
    )

    from InstructionX_UIKit.theme import T, ThemeManager

    app = QApplication.instance() or QApplication(sys.argv)
    tm = ThemeManager.instance()
    tm.set_mode("light")
    tm.apply(app)
    SHOTS.mkdir(parents=True, exist_ok=True)

    print("展示修复回归测试开始（offscreen）")
    print("-" * 60)

    # ------------------------------------------------------------------
    # 1. 瀑布流：不等高 + 固定高度 + 最短列优先
    # ------------------------------------------------------------------
    print("[瀑布流]")

    def waterfall_heights():
        from demo.pages.layout_samples import WATERFALL_ITEMS
        from InstructionX_UIKit.layouts.waterfall import Waterfall

        wf = Waterfall(items=WATERFALL_ITEMS)
        try:
            wf.resize(1280, 800)
            wf.show()
            app.processEvents()
            assert wf._cols == 4, wf._cols
            groups = wf.column_cards()
            assert len(groups) == 4, len(groups)
            totals = []
            for g in groups:
                hs = [c.height() for c in g]
                # 同列卡片高度不全相等（瀑布流区别于等高网格的核心）
                assert len(set(hs)) > 1, f"同列卡片等高: {hs}"
                for c in g:
                    # 列内卡片高度不被拉伸：渲染高度 == 固定高度
                    assert c.height() == c.property("card_height"), (
                        c.height(), c.property("card_height"))
                    assert 120 <= c.height() <= 260, c.height()
                # 各列累计高度（含间距）
                totals.append(sum(hs) + T("space.4") * max(0, len(hs) - 1))
            # 最短列优先分配：各列高度均衡（极差不超过最高卡片）
            assert max(totals) - min(totals) <= 260, totals
        finally:
            wf.close()
            wf.deleteLater()

    _check("同列卡片高度不全相等且不被拉伸（120-260）", waterfall_heights)

    def waterfall_breakpoints():
        from demo.pages.layout_samples import WATERFALL_ITEMS
        from InstructionX_UIKit.layouts.waterfall import Waterfall

        wf = Waterfall(items=WATERFALL_ITEMS)
        try:
            wf.show()
            for width, want in ((500, 2), (700, 2), (900, 3), (1280, 4), (1500, 4)):
                wf.resize(width, 800)
                app.processEvents()
                assert wf._cols == want, (width, wf._cols, want)
                assert len(wf.column_cards()) == want
        finally:
            wf.close()
            wf.deleteLater()

    _check("断点列数 2/2/3/4 响应式重排", waterfall_breakpoints)

    def waterfall_shots():
        from demo.pages.layout_samples import WATERFALL_ITEMS
        from InstructionX_UIKit.layouts.waterfall import create_waterfall

        wf = create_waterfall(items=WATERFALL_ITEMS)
        try:
            wf.resize(1280, 800)
            wf.show()
            for mode in ("light", "dark"):
                tm.set_mode(mode)
                tm.apply(app)
                app.processEvents()
                QTest.qWait(30)
                _save(wf.grab(), f"fix_display_waterfall_1280_{mode}.png")
        finally:
            wf.close()
            wf.deleteLater()
            tm.set_mode("light")
            tm.apply(app)
            app.processEvents()

    _check("瀑布流 1280 亮/暗截图", waterfall_shots)

    # ------------------------------------------------------------------
    # 2. 徽标：99+ 完整 + z-order 顶层 + 点模式不受影响
    # ------------------------------------------------------------------
    print("[徽标]")

    def badge_overflow_and_zorder():
        from InstructionX_UIKit.components.badge import Badge, _PILL_H

        b = Badge(QPushButton("通知"), count=120)
        try:
            b.resize(b.sizeHint())
            b.show()
            app.processEvents()
            assert b._text() == "99+", b._text()
            # z-order：角标是 children 中最后（顶层）的子控件
            assert b.children()[-1] is b._pill, (
                [type(c).__name__ for c in b.children()])
            assert b._pill.isVisible()
            # 角标完整落在徽标控件边界内（不被父边界裁剪）
            assert b.rect().contains(b._pill.geometry()), (
                b._pill.geometry(), b.rect())
            # 99+ 文本 boundingRect 完全落在角标 rect 内
            fm = QFontMetrics(b._text_font())
            tr = fm.boundingRect(b._pill.rect(), int(Qt.AlignCenter), b._text())
            assert b._pill.rect().contains(tr), (tr, b._pill.rect())
            # 像素级 z-order：角标与被包裹控件重叠区仍显示角标红
            img = b.grab().toImage()
            g = b._pill.geometry()
            c = img.pixelColor(g.x() + 3, g.center().y())  # 左端深入子控件区
            assert _red_dominant(c), (c.red(), c.green(), c.blue(), c.alpha())
            c2 = img.pixelColor(g.center().x(), g.y() + _PILL_H - 3)  # 下部重叠区
            assert _red_dominant(c2), (c2.red(), c2.green(), c2.blue(), c2.alpha())
            # 换绑子控件后角标仍是 children 末尾
            b.set_widget(QPushButton("新按钮"))
            b.resize(b.sizeHint())
            app.processEvents()
            assert b.children()[-1] is b._pill
            img2 = b.grab().toImage()
            g2 = b._pill.geometry()
            c3 = img2.pixelColor(g2.x() + 3, g2.center().y())
            assert _red_dominant(c3), (c3.red(), c3.green(), c3.blue(), c3.alpha())
        finally:
            b.close()
            b.deleteLater()

    _check("99+ 文本完整 + 角标顶层（z-order）", badge_overflow_and_zorder)

    def badge_resize_stays_top():
        from InstructionX_UIKit.components.badge import Badge

        b = Badge(QPushButton("消息"), count=5)
        try:
            b.resize(b.sizeHint())
            b.show()
            app.processEvents()
            # 父控件 resize 后角标保持顶层且完整可见
            b.resize(b.width() + 80, b.height() + 40)
            app.processEvents()
            QTest.qWait(20)
            assert b.children()[-1] is b._pill
            assert b.rect().contains(b._pill.geometry())
            img = b.grab().toImage()
            g = b._pill.geometry()
            c = img.pixelColor(g.center().x(), g.center().y())
            assert _red_dominant(c), (c.red(), c.green(), c.blue(), c.alpha())
        finally:
            b.close()
            b.deleteLater()

    _check("父控件 resize 后角标保持顶层", badge_resize_stays_top)

    def badge_dot_mode():
        from InstructionX_UIKit.components.badge import Badge, _DOT_D

        # 独立红点：尺寸与渲染不受本次修复影响
        d = Badge(dot=True)
        try:
            assert d._pill_width() == _DOT_D, d._pill_width()
            d.resize(d.sizeHint())
            d.show()
            app.processEvents()
            assert d._pill.width() == _DOT_D and d._pill.height() == _DOT_D
            img = d.grab().toImage()
            c = img.pixelColor(d.width() // 2, d.height() // 2)
            assert _red_dominant(c), (c.red(), c.green(), c.blue(), c.alpha())
        finally:
            d.close()
            d.deleteLater()
        # 包裹红点 + 独立数字角标
        w = Badge(QPushButton("红点"), dot=True)
        s = Badge(count=8)
        try:
            w.resize(w.sizeHint())
            s.resize(s.sizeHint())
            w.show()
            s.show()
            app.processEvents()
            assert w._pill.width() == _DOT_D
            assert s.children()[-1] is s._pill and s._pill.isVisible()
        finally:
            w.close()
            w.deleteLater()
            s.close()
            s.deleteLater()

    _check("独立点模式与独立角标不受影响", badge_dot_mode)

    def badge_shots():
        from InstructionX_UIKit.components.badge import Badge

        host = QWidget()
        row = QHBoxLayout(host)
        row.setContentsMargins(16, 16, 16, 16)
        row.setSpacing(24)
        for b in (Badge(QPushButton("消息中心"), count=5),
                  Badge(QPushButton("通知"), count=120),
                  Badge(QPushButton("红点"), dot=True),
                  Badge(count=8),
                  Badge(dot=True, color="success")):
            row.addWidget(b)
        row.addStretch(1)
        try:
            host.resize(520, 100)
            host.show()
            for mode in ("light", "dark"):
                tm.set_mode(mode)
                tm.apply(app)
                app.processEvents()
                QTest.qWait(30)
                _save(host.grab(), f"fix_display_badge_{mode}.png")
        finally:
            host.close()
            host.deleteLater()
            tm.set_mode("light")
            tm.apply(app)
            app.processEvents()

    _check("徽标 亮/暗截图", badge_shots)

    # ------------------------------------------------------------------
    # 3. 气泡：四方向实例化 + 窗口标志 + 阴影 / 箭头像素 + 截图
    # ------------------------------------------------------------------
    print("[气泡]")
    _pops = []  # 防止弹出层被 GC

    def popover_four_ways():
        from InstructionX_UIKit.components.popover import Popover

        host = QWidget()
        host.resize(720, 720)
        anchor = QPushButton("锚点按钮", host)
        anchor.resize(120, 40)
        anchor.move(300, 340)
        host.show()
        app.processEvents()

        try:
            for mode in ("light", "dark"):
                tm.set_mode(mode)
                tm.apply(app)
                app.processEvents()
                for placement in ("top", "bottom", "left", "right"):
                    pop = Popover("快捷筛选",
                                  "按状态、时间或负责人筛选列表数据，支持多条件组合。")
                    _pops.append(pop)
                    # 窗口标志：Popup + Frameless + 半透明背景
                    assert pop.windowFlags() & Qt.Popup
                    assert pop.windowFlags() & Qt.FramelessWindowHint
                    assert pop.testAttribute(Qt.WA_TranslucentBackground)
                    pop.show_for(anchor, placement)
                    app.processEvents()
                    QTest.qWait(30)
                    assert pop.isVisible()
                    assert pop.placement() == placement, (
                        placement, pop.placement())
                    pm = pop.grab()
                    _save(pm, f"fix_display_popover_{placement}_{mode}.png")

                    img = pm.toImage()
                    card = pop._card_rect()
                    cx = int(card.center().x())
                    if placement == "bottom":
                        # 阴影：卡片底边外侧柔和可见（暗色、半透明）
                        sc = img.pixelColor(cx - 30, int(card.bottom()) + 4)
                        assert sc.alpha() > 20, (
                            "阴影不可见", sc.red(), sc.green(), sc.blue(), sc.alpha())
                        assert max(sc.red(), sc.green(), sc.blue()) < 120, (
                            "阴影颜色异常", sc.red(), sc.green(), sc.blue())
                        # 箭头：与卡片底色一致（指向锚点一侧）
                        bg = T("color.bg.elevated")
                        ac = img.pixelColor(cx, int(card.top()) - 4)
                        from PySide6.QtGui import QColor
                        want = QColor(bg)
                        for got, exp in ((ac.red(), want.red()),
                                         (ac.green(), want.green()),
                                         (ac.blue(), want.blue())):
                            assert abs(got - exp) <= 8, (
                                "箭头与底色不一致", ac.name(), bg)
                    pop.hide()
                    app.processEvents()
                    _pops.remove(pop)
                    pop.deleteLater()
        finally:
            host.close()
            host.deleteLater()
            tm.set_mode("light")
            tm.apply(app)
            app.processEvents()

    _check("四方向实例化 + 窗口标志 + 阴影/箭头像素 + 亮暗截图", popover_four_ways)

    print("-" * 60)
    print(f"截图输出目录: {SHOTS}（共 {_shots} 张）")
    if _FAILURES:
        print(f"共 {len(_FAILURES)} 项失败: {_FAILURES}")
        return 1
    print("全部检查通过，0 错误")
    return 0


if __name__ == "__main__":
    sys.exit(main())
