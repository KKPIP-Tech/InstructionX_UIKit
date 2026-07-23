# -*- coding: utf-8 -*-
"""fix/a2 修复验证：侧栏折叠图标居中 / 圆形按钮“+”墨迹居中 / 弹出窗透明。

直接运行（无 pytest 依赖）::

    QT_QPA_PLATFORM=offscreen python tests/test_fix_a2.py

覆盖：
- 侧边栏折叠为 56px 图标栏后，逐导航按钮断言图标墨迹中心与栏中心
  水平偏差 <= 1px（修复前 QToolButton 水平 Fixed 策略使按钮按 sizeHint
  宽度左对齐，图标偏离栏中心约 4~6px）；展开态恢复「图标 + 文本」，
  布局行为不变。
- Button(shape="circle") 短文本（"+"）：24/32/40 三档下墨迹 bbox 中心
  与按钮中心水平 + 垂直偏差均 <= 1px，墨迹质心偏差 <= 0.75px
  （修复前行高盒居中使 md 档垂直偏 +1.4px）；round 形状不受影响。
- Popover / Message / Notification：暗色主题弹出后按预乘 Alpha 渲染
  顶层窗口，卡体路径 + 阴影区之外的四角采样点 alpha == 0（真透明，
  无 #15181E 实心矩形）；样式引擎背景探针（PE_Widget）断言全局基座
  QSS 不再给弹出窗涂不透明底色（修复前会涂 bg.base）；三个浮层均带
  WA_TranslucentBackground、关闭 autoFillBackground、实例级 QSS 透明。
- 亮 / 暗截图 tests/shots/fixa2_*.png 供目检。

注：离屏渲染半透明区域必须使用 Format_ARGB32_Premultiplied 目标 +
pixelColor() 读取；非预乘 Format_ARGB32 上 QPainter 的合成会把透明区
变成不透明黑色（Qt 光栅引擎限制），与真实窗口合成结果不符。
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

from PySide6.QtCore import QPoint, Qt  # noqa: E402
from PySide6.QtGui import QImage, QPainter  # noqa: E402
from PySide6.QtWidgets import (  # noqa: E402
    QApplication,
    QStyle,
    QStyleOption,
    QWidget,
)

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


def settle(app, ms=120):
    from PySide6.QtCore import QElapsedTimer

    timer = QElapsedTimer()
    timer.start()
    while timer.elapsed() < ms:
        app.processEvents()
        time.sleep(0.004)


def render_alpha(widget):
    """把控件真实绘制内容渲染到透明预乘 Alpha 图像（含样式表绘制链）。

    返回的图像中，未被绘制的区域 alpha == 0；读取须用 pixelColor()
    （正确处理预乘格式）。
    """
    img = QImage(widget.size(), QImage.Format_ARGB32_Premultiplied)
    img.fill(Qt.transparent)
    widget.render(img, QPoint(0, 0), widget.rect(),
                  QWidget.RenderFlag.DrawChildren)
    return img


def alpha_map(img):
    return [[img.pixelColor(x, y).alpha() for x in range(img.width())]
            for y in range(img.height())]


def style_bg_probe(widget):
    """询问样式引擎：给该控件绘制 PE_Widget 背景时会涂什么。

    全局基座 QSS「QWidget { background: bg.base }」命中时整个矩形被
    涂上不透明底色（修复前症状的根源）；实例级透明覆盖后应完全不画。
    返回渲染结果图像（透明 = 样式不涂背景）。
    """
    widget.ensurePolished()
    img = QImage(widget.size(), QImage.Format_ARGB32_Premultiplied)
    img.fill(Qt.transparent)
    painter = QPainter(img)
    opt = QStyleOption()
    opt.initFrom(widget)
    opt.rect = img.rect()
    widget.style().drawPrimitive(QStyle.PE_Widget, opt, painter, widget)
    painter.end()
    return img


def corner_points(w, h, inset=0):
    return [(inset, inset), (w - 1 - inset, inset),
            (inset, h - 1 - inset), (w - 1 - inset, h - 1 - inset)]


# ---------------------------------------------------------------------------
# 1. 侧栏折叠图标水平居中
# ---------------------------------------------------------------------------

@check("侧栏折叠：逐导航按钮图标中心与 56px 栏中心偏差 <= 1px")
def _():
    from InstructionX_UIKit.layouts.sidebar_layout import create_sidebar_layout

    win = create_sidebar_layout(
        brand="控制台",
        nav_items=[("home", "首页"), ("settings", "设置"), ("search", "搜索")])
    win.resize(400, 400)  # xs 断点 -> 自动折叠
    win.show()
    settle(_APP)
    bar = win._sidebar
    assert_true(bar.width() == 56, f"折叠栏宽应为 56，实际 {bar.width()}")
    assert_true(win._collapsed, "400px 宽应命中 xs 断点自动折叠")
    for btn in win.nav_buttons:
        assert_true(btn.toolButtonStyle() == Qt.ToolButtonIconOnly,
                    "折叠态应为 ToolButtonIconOnly")
        assert_true(btn.text() == "", "折叠态不应有文本")
        # 按钮应撑满栏内容宽（按钮中心 == 栏中心）
        btn_cx = btn.x() + btn.width() / 2.0
        assert_true(abs(btn_cx - bar.width() / 2.0) <= 1,
                    f"按钮未在栏内居中：按钮中心 {btn_cx} vs 栏中心 "
                    f"{bar.width() / 2.0}")
        # 图标墨迹中心：选中按钮背景为半透明 subtle，图标不透明 ->
        # 取 alpha==255 像素；未选中按钮背景全透明 -> 取 alpha>0 像素
        img = render_alpha(btn)
        amap = alpha_map(img)
        threshold = 255 if btn.isChecked() else 1
        xs = [x for y, row in enumerate(amap)
              for x, a in enumerate(row) if a >= threshold]
        assert_true(xs, "未找到图标墨迹")
        ink_cx = (min(xs) + max(xs)) / 2.0
        icon_bar_cx = btn.x() + ink_cx
        dev = icon_bar_cx - bar.width() / 2.0
        assert_true(abs(dev) <= 1,
                    f"图标中心 {icon_bar_cx:.2f} 与栏中心 "
                    f"{bar.width() / 2.0} 偏差 {dev:+.2f}px > 1px")
    # 截图（亮 / 暗）
    SHOTS.mkdir(exist_ok=True)
    for mode in ("light", "dark"):
        ThemeManager.instance().set_mode(mode)
        settle(_APP)
        win.grab().save(str(SHOTS / f"fixa2_sidebar_collapsed_{mode}.png"))
    ThemeManager.instance().set_mode("light")
    settle(_APP)
    win.close()


@check("侧栏展开：图标 + 文本正常，布局行为不变")
def _():
    from InstructionX_UIKit.layouts.sidebar_layout import create_sidebar_layout

    win = create_sidebar_layout(
        brand="控制台",
        nav_items=[("home", "首页"), ("settings", "设置"), ("search", "搜索")])
    win.resize(1200, 400)  # lg 断点 -> 展开
    win.show()
    settle(_APP)
    bar = win._sidebar
    assert_true(bar.width() == 208, f"展开栏宽应为 208，实际 {bar.width()}")
    assert_true(not win._collapsed, "1200px 宽应展开")
    texts = ["首页", "设置", "搜索"]
    for btn, text in zip(win.nav_buttons, texts):
        assert_true(btn.toolButtonStyle() == Qt.ToolButtonTextBesideIcon,
                    "展开态应为 ToolButtonTextBesideIcon")
        assert_true(btn.text() == text,
                    f"展开态文本应为 {text!r}，实际 {btn.text()!r}")
        assert_true(not btn.icon().isNull(), "展开态应有图标")
        # 图标墨迹 + 文本墨迹均存在（展开态正常绘制）
        img = render_alpha(btn)
        amap = alpha_map(img)
        assert_true(any(a > 0 for row in amap for a in row),
                    "展开态按钮应有可见内容")
    for mode in ("light", "dark"):
        ThemeManager.instance().set_mode(mode)
        settle(_APP)
        win.grab().save(str(SHOTS / f"fixa2_sidebar_expanded_{mode}.png"))
    ThemeManager.instance().set_mode("light")
    settle(_APP)
    win.close()


# ---------------------------------------------------------------------------
# 2. 圆形 Button "+" 墨迹居中
# ---------------------------------------------------------------------------

def _measure_ink(btn, edge):
    """返回 (bbox中心偏差x, bbox中心偏差y, 质心偏差x, 质心偏差y, 墨迹像素数)。"""
    img = render_alpha(btn)
    bg = img.pixelColor(2, edge // 2).getRgb()[:3]  # 圆面底色（左缘内侧）
    tot = sx = sy = 0.0
    pts = []
    for y in range(edge):
        for x in range(edge):
            c = img.pixelColor(x, y)
            if c.alpha() < 100:
                continue
            d = sum(abs(a - b) for a, b in zip(c.getRgb()[:3], bg))
            if d > 96:
                w = d / 765.0
                tot += w
                sx += x * w
                sy += y * w
                pts.append((x, y))
    if not pts:
        return None
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    # 像素索引 -> 连续坐标（像素中心）后再与几何中心比较
    ccx = sx / tot + 0.5 - edge / 2.0
    ccy = sy / tot + 0.5 - edge / 2.0
    bcx = (min(xs) + max(xs)) / 2.0 - edge / 2.0
    bcy = (min(ys) + max(ys)) / 2.0 - edge / 2.0
    return bcx, bcy, ccx, ccy, len(pts)


@check("Button circle '+'：24/32/40 三档墨迹中心偏差 <= 1px（水平+垂直）")
def _():
    from InstructionX_UIKit.components.button import Button

    for mode in ("light", "dark"):
        ThemeManager.instance().set_mode(mode)
        settle(_APP)
        for size, edge in (("sm", 24), ("md", 32), ("lg", 40)):
            btn = Button("+", variant="primary", shape="circle", size=size)
            btn.setFixedSize(edge, edge)
            btn.show()
            settle(_APP, 30)
            res = _measure_ink(btn, edge)
            assert_true(res is not None, f"{mode}/{size} 未找到 '+' 墨迹")
            bcx, bcy, ccx, ccy, n = res
            assert_true(abs(bcx) <= 1 and abs(bcy) <= 1,
                        f"{mode}/{size}({edge}px) 墨迹 bbox 中心偏差 "
                        f"({bcx:+.2f},{bcy:+.2f}) > 1px")
            assert_true(abs(ccx) <= 0.75 and abs(ccy) <= 0.75,
                        f"{mode}/{size}({edge}px) 墨迹质心偏差 "
                        f"({ccx:+.2f},{ccy:+.2f}) > 0.75px")
            btn.close()
        ThemeManager.instance().set_mode("light")
    settle(_APP)


@check("Button circle 其他变体与 round 形状不受影响")
def _():
    from InstructionX_UIKit.components.button import Button

    # default 变体圆形 "+"：同样墨迹居中（文本色 vs 浅底）
    btn = Button("+", variant="default", shape="circle", size="md")
    btn.setFixedSize(32, 32)
    btn.show()
    settle(_APP, 30)
    res = _measure_ink(btn, 32)
    assert_true(res is not None, "default 变体未找到 '+' 墨迹")
    bcx, bcy, ccx, ccy, _n = res
    assert_true(abs(bcx) <= 1 and abs(bcy) <= 1,
                f"default 变体墨迹偏差 ({bcx:+.2f},{bcy:+.2f}) > 1px")
    btn.close()
    # round 形状：仍由样式绘制（长文本正常显示）
    rb = Button("胶囊", shape="round", variant="primary")
    rb.show()
    settle(_APP, 30)
    assert_true(not rb._ink_centered_text(),
                "round 形状不应走墨迹自绘路径")
    img = render_alpha(rb)
    assert_true(any(img.pixelColor(x, y).alpha() > 0
                    for y in range(img.height()) for x in range(img.width())),
                "round 按钮应有可见内容")
    rb.close()
    # 普通按钮 / 长文本圆形：不走墨迹自绘路径
    nb = Button("确定", variant="primary")
    nb.show()
    settle(_APP, 30)
    assert_true(not nb._ink_centered_text(), "普通按钮不应走墨迹自绘路径")
    nb.close()
    # 截图：三档圆形 "+" + round（独立行，避免页面滚动区只截到顶部）
    from PySide6.QtWidgets import QHBoxLayout
    row_host = QWidget()
    row_lay = QHBoxLayout(row_host)
    for size, edge in (("sm", 24), ("md", 32), ("lg", 40)):
        b = Button("+", variant="primary", shape="circle", size=size)
        b.setFixedSize(edge, edge)
        row_lay.addWidget(b)
    row_lay.addWidget(Button("胶囊", shape="round", variant="primary"))
    row_host.show()
    for mode in ("light", "dark"):
        ThemeManager.instance().set_mode(mode)
        settle(_APP)
        row_host.grab().save(str(SHOTS / f"fixa2_button_shapes_{mode}.png"))
    ThemeManager.instance().set_mode("light")
    settle(_APP)
    row_host.close()


# ---------------------------------------------------------------------------
# 3. 弹出窗真透明（无黑色方框）
# ---------------------------------------------------------------------------

def _check_popup_transparent(widget, tag, margin):
    """四角采样：alpha==0；样式背景探针：不涂底色；属性三件套。"""
    # 1) 渲染真实绘制内容：阴影边距区之外必须为真透明
    img = render_alpha(widget)
    w, h = img.width(), img.height()
    base = T("color.bg.base").lstrip("#")
    br, bg_, bb = int(base[0:2], 16), int(base[2:4], 16), int(base[4:6], 16)
    for pt in corner_points(w, h):
        c = img.pixelColor(*pt)
        assert_true(c.alpha() == 0,
                    f"{tag} 四角采样点 {pt} 不透明: {c.getRgb()}")
    # 阴影边距内缘采样（margin>0 时）：允许柔和阴影尾迹（低 alpha），
    # 但不允许不透明底色
    if margin > 0:
        for pt in corner_points(w, h, inset=margin // 2):
            c = img.pixelColor(*pt)
            assert_true(c.alpha() <= 32,
                        f"{tag} 边距采样点 {pt} 接近不透明: {c.getRgb()}")
    for pt in corner_points(w, h):
        c = img.pixelColor(*pt)
        assert_true(not (abs(c.red() - br) <= 8 and abs(c.green() - bg_) <= 8
                         and abs(c.blue() - bb) <= 8 and c.alpha() == 255),
                    f"{tag} 采样点 {pt} 命中 bg.base 实心矩形: {c.getRgb()}")
    # 2) 卡体中心必须不透明（渲染 sanity）
    center = img.pixelColor(w // 2, h // 2)
    assert_true(center.alpha() == 255,
                f"{tag} 卡体中心应不透明: {center.getRgb()}")
    # 3) 样式引擎背景探针：不得涂任何不透明底色
    probe = style_bg_probe(widget)
    for pt in corner_points(probe.width(), probe.height()):
        c = probe.pixelColor(*pt)
        assert_true(c.alpha() == 0,
                    f"{tag} 样式背景探针 {pt} 非透明: {c.getRgb()} "
                    f"（全局基座 QSS 正在给弹出窗涂底色）")
    # 4) 属性三件套：半透明背景 + 关闭自动填充 + 实例级透明 QSS
    assert_true(widget.testAttribute(Qt.WA_TranslucentBackground),
                f"{tag} 缺少 WA_TranslucentBackground")
    assert_true(not widget.autoFillBackground(),
                f"{tag} autoFillBackground 应为 False")
    assert_true("transparent" in widget.styleSheet(),
                f"{tag} 缺少实例级透明 QSS 覆盖，实际 {widget.styleSheet()!r}")


def _save_popup_shot(widget, name):
    """浮层渲染结果叠加到主题底色上保存（透明区显示底色，便于目检）。"""
    SHOTS.mkdir(exist_ok=True)
    raw = render_alpha(widget)
    canvas = QImage(raw.size(), QImage.Format_ARGB32_Premultiplied)
    canvas.fill(T("color.bg.base"))
    p = QPainter(canvas)
    p.drawImage(0, 0, raw)
    p.end()
    canvas.save(str(SHOTS / name))


@check("Popover / Message / Notification：暗色主题浮层真透明（无黑色方框）")
def _():
    from InstructionX_UIKit.components.button import Button
    from InstructionX_UIKit.components.message import Message
    from InstructionX_UIKit.components.notification import Notification
    from InstructionX_UIKit.components.popover import Popover

    ThemeManager.instance().set_mode("dark")
    settle(_APP)
    anchor = Button("anchor")
    anchor.resize(500, 400)
    anchor.show()
    settle(_APP)

    pop = Popover("筛选", "气泡内容：浮层透明验证")
    pop.show_for(anchor, placement="bottom")
    settle(_APP)
    pop._stop_enter_animation()
    settle(_APP, 30)
    _check_popup_transparent(pop, "Popover", margin=12)
    _save_popup_shot(pop, "fixa2_popover_dark.png")
    pop.close()

    msg = Message.show(anchor, "保存成功", "success", duration=600000)
    settle(_APP, 300)  # 等待入场动画结束
    _check_popup_transparent(msg, "Message", margin=0)
    _save_popup_shot(msg, "fixa2_message_dark.png")
    Message.close_all()
    settle(_APP)

    ntf = Notification.info(anchor, "通知标题", "通知内容：浮层透明验证",
                            duration=600000)
    settle(_APP, 400)
    _check_popup_transparent(ntf, "Notification", margin=0)
    _save_popup_shot(ntf, "fixa2_notification_dark.png")
    Notification.close_all()
    settle(_APP)

    ThemeManager.instance().set_mode("light")
    settle(_APP)

    # 亮色主题同样验证 + 截图
    pop2 = Popover("筛选", "气泡内容：浮层透明验证")
    pop2.show_for(anchor, placement="bottom")
    settle(_APP)
    pop2._stop_enter_animation()
    settle(_APP, 30)
    _check_popup_transparent(pop2, "Popover(light)", margin=12)
    _save_popup_shot(pop2, "fixa2_popover_light.png")
    pop2.close()

    msg2 = Message.show(anchor, "保存成功", "success", duration=600000)
    settle(_APP, 300)
    _check_popup_transparent(msg2, "Message(light)", margin=0)
    _save_popup_shot(msg2, "fixa2_message_light.png")
    Message.close_all()

    ntf2 = Notification.info(anchor, "通知标题", "通知内容：浮层透明验证",
                             duration=600000)
    settle(_APP, 400)
    _check_popup_transparent(ntf2, "Notification(light)", margin=0)
    _save_popup_shot(ntf2, "fixa2_notification_light.png")
    Notification.close_all()
    settle(_APP)
    anchor.close()


def main():
    print("== fix/a2 修复验证 ==")
    failed = bool(_FAILURES)
    print("== 结果:", "失败" if failed else "全部通过", "==")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
