# -*- coding: utf-8 -*-
"""反馈组件缺陷修复验证（agent R4）。

直接运行（无 pytest 依赖）::

    QT_QPA_PLATFORM=offscreen python tests/test_fix_feedback.py

覆盖三个修复点：

1. ``DropdownButton`` 双下拉箭头 —— 截图像素扫描右侧箭头区：箭头簇
   必须只有 1 个（自绘 chevron），且 chevron 顶点正上方必须是空心
   （若样式回退的实心 menu-indicator 三角仍在，该区域会被填充）。
2. ``Dialog`` 双重标题栏 / 双关闭按钮 —— 子控件树中不得存在自定义
   关闭按钮（QToolButton）与自定义标题标签（uikDlg="title"），标题
   只出现在原生窗口标题栏（windowTitle）；confirm()/info() 行为不变。
3. ``Message`` 轻提示椭圆背景 —— 四种类型 grab 截图，断言气泡宽高比
   < 6:1，角部像素采样符合四分之一圆（胶囊）而非椭圆；长文本自动
   换行、宽度不超过 480px，且仍保持胶囊形状。

亮 / 暗双主题截图保存到 ``tests/shots/fix_feedback_*.png``。
任何异常即失败，退出码 1。
"""

import math
import os
import sys
import traceback
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

SHOTS = ROOT / "tests" / "shots"
SHOTS.mkdir(parents=True, exist_ok=True)

from PySide6.QtCore import Qt, QTimer  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import (  # noqa: E402
    QApplication,
    QLabel,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from InstructionX_UIKit.theme import T, ThemeManager  # noqa: E402

APP = QApplication.instance() or QApplication([])
TM = ThemeManager.instance()
TM.set_mode("light")
TM.apply(APP)

_FAILURES = []
_SHOT_LOG = []


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


def grab_both(widget, name, min_bytes=800):
    """亮 / 暗双主题截图并保存。"""
    for mode in ("light", "dark"):
        TM.set_mode(mode)
        APP.processEvents()
        pm = widget.grab()
        if pm.isNull() or pm.width() < 10 or pm.height() < 10:
            raise AssertionError(f"{name} {mode} grab() 失败")
        path = SHOTS / f"fix_feedback_{name}_{mode}.png"
        if not pm.save(str(path)):
            raise AssertionError(f"截图保存失败: {path}")
        size = path.stat().st_size
        if size < min_bytes:
            raise AssertionError(f"截图过小（疑似空白）: {path} = {size}B")
        _SHOT_LOG.append(path.name)
    TM.set_mode("light")
    APP.processEvents()


def _diff(px, bg) -> int:
    return (abs(px.red() - bg.red()) + abs(px.green() - bg.green())
            + abs(px.blue() - bg.blue()))


# ---------------------------------------------------------------------------
# 1) DropdownButton：仅一个下拉箭头
# ---------------------------------------------------------------------------

@check("dropdown 按钮右侧仅一个箭头区域（像素扫描）")
def _():
    from InstructionX_UIKit.components.dropdown import DropdownButton

    w = QWidget()
    lay = QVBoxLayout(w)
    lay.setContentsMargins(16, 16, 16, 16)
    dd = DropdownButton("操作")
    dd.setFixedWidth(160)
    dd.add_item("edit", "编辑", shortcut="Ctrl+E")
    dd.add_item("del", "删除", danger=True)
    lay.addWidget(dd, 0, Qt.AlignLeft)
    lay.addStretch(1)
    fired = []
    dd.triggered.connect(fired.append)
    w.resize(320, 120)
    w.show()
    APP.processEvents()

    grab_both(dd, "dropdown")
    img = dd.grab().toImage()
    W, H = img.width(), img.height()
    # 按钮填充背景色（左侧中部，避开边框与文本）
    bg = img.pixelColor(6, H // 2)
    cy = H / 2.0
    cx = W - 13.0  # 自绘 chevron 中心 x（见 paintEvent）

    def marked(x, y) -> bool:
        return _diff(img.pixelColor(x, y), bg) > 90

    # —— 判据 1：右侧扫描带内箭头簇恰好 1 个 ————————————————————————
    # （若样式箭头与自绘箭头分离渲染，会出现第 2 个簇）
    arrow_cols = []
    for x in range(max(0, W - 30), W - 2):  # 排除最右 2 列边框线
        ys = [y for y in range(2, H - 2) if marked(x, y)]
        # 箭头列：命中点集中在中部纵向带且数量少（排除纵贯整列的边线）
        if 2 <= len(ys) <= 10 and all(abs(y - cy) <= 9 for y in ys):
            arrow_cols.append(x)
    clusters = []
    for x in arrow_cols:
        if clusters and x - clusters[-1][-1] <= 4:
            clusters[-1].append(x)
        else:
            clusters.append([x])
    if len(clusters) != 1:
        raise AssertionError(
            f"右侧箭头区域应为 1 个，实际 {len(clusters)} 个: "
            f"{[(c[0], c[-1]) for c in clusters]}")
    c = clusters[0]
    if not (4 <= len(c) <= 16):
        raise AssertionError(f"箭头簇宽度异常: {c[0]}..{c[-1]}")
    if abs((c[0] + c[-1]) / 2.0 - cx) > 6:
        raise AssertionError(f"箭头簇中心 {(c[0] + c[-1]) / 2} 未对齐 cx={cx}")

    # —— 判据 2：chevron 顶点上方必须空心 ————————————————————————————
    # 自绘 chevron 是 1.5px 的 "v" 形折线，顶点 (cx, cy+1.6) 正上方
    # （cy-2 / cy-1 两行、cx±1 列）应为按钮背景；样式回退的实心 ▼
    # menu-indicator 与 chevron 同位叠加时会填满该区域。
    y1, y2 = int(round(cy)) - 2, int(round(cy)) - 1
    filled = sum(1 for yy in (y1, y2)
                 for xx in range(int(cx) - 1, int(cx) + 2)
                 if marked(xx, yy))
    if filled > 2:
        raise AssertionError(
            f"chevron 顶点上方被实心填充（{filled}/6 像素），"
            f"样式回退的 menu-indicator 箭头仍存在")

    # —— 菜单交互行为不变 ————————————————————————————————————————
    dd.showMenu()
    APP.processEvents()
    grab_both(dd.menu(), "dropdown_menu")
    dd.menu().actions()[0].trigger()
    if fired != ["edit"]:
        raise AssertionError(f"菜单触发信号异常: {fired}")
    dd.menu().close()
    APP.processEvents()
    w.close()


# ---------------------------------------------------------------------------
# 2) Dialog：仅原生标题栏，无自定义关闭按钮
# ---------------------------------------------------------------------------

@check("dialog 无自定义标题栏/关闭按钮，confirm/info 行为不变")
def _():
    from InstructionX_UIKit.components.dialog import Dialog

    host = QWidget()
    host.resize(480, 300)
    lay = QVBoxLayout(host)
    lay.addWidget(QLabel("宿主窗口"))
    host.show()
    APP.processEvents()

    # —— 直接构造：子控件树检查 ————————————————————————————————
    dlg = Dialog(host, "确认删除")
    dlg.set_text("删除后不可恢复，确定继续吗？")
    dlg.show()
    APP.processEvents()
    if dlg.windowTitle() != "确认删除":
        raise AssertionError(f"windowTitle 异常: {dlg.windowTitle()!r}")
    closes = dlg.findChildren(QToolButton)
    if closes:
        raise AssertionError(f"仍存在自定义关闭按钮: {closes}")
    titles = [lb for lb in dlg.findChildren(QLabel)
              if lb.property("uikDlg") == "title"]
    if titles:
        raise AssertionError(f"仍存在自定义标题标签: {titles}")
    # set_title/title 与原生标题栏同步
    dlg.set_title("新标题")
    if dlg.windowTitle() != "新标题" or dlg.title() != "新标题":
        raise AssertionError("set_title 未同步 windowTitle/title()")
    dlg.set_title("")
    if dlg.windowTitle() != "对话框":
        raise AssertionError("空标题应回退为默认窗口标题")
    grab_both(dlg, "dialog")
    dlg.close()
    APP.processEvents()

    # —— confirm()：确定 / 取消两条路径 ————————————————————————————
    results = []
    d1 = Dialog.confirm(host, "确认删除", "删除后不可恢复，确定继续吗？",
                        on_result=results.append)
    APP.processEvents()
    if not d1.isVisible() or d1.findChildren(QToolButton):
        raise AssertionError("confirm 对话框异常（未显示或含自定义关闭按钮）")
    QTimer.singleShot(0, d1, d1.ok_button().click)
    APP.processEvents()
    if results != [True]:
        raise AssertionError(f"confirm 确定路径异常: {results}")

    d2 = Dialog.confirm(host, "再次确认", "确定放弃修改吗？",
                        on_result=results.append)
    APP.processEvents()
    QTimer.singleShot(0, d2, d2.cancel_button().click)
    APP.processEvents()
    if results != [True, False]:
        raise AssertionError(f"confirm 取消路径异常: {results}")

    # —— info()：仅确认按钮，关闭回调 ————————————————————————————
    closed = []
    d3 = Dialog.info(host, "操作完成", "数据同步已完成。",
                     on_close=lambda: closed.append(1))
    APP.processEvents()
    if d3.cancel_button().isVisible():
        raise AssertionError("info 对话框不应显示取消按钮")
    if d3.findChildren(QToolButton):
        raise AssertionError("info 对话框含自定义关闭按钮")
    grab_both(d3, "dialog_info")
    QTimer.singleShot(0, d3, d3.ok_button().click)
    APP.processEvents()
    if closed != [1]:
        raise AssertionError("info 关闭回调异常")
    host.close()


# ---------------------------------------------------------------------------
# 3) Message：圆角矩形胶囊而非椭圆
# ---------------------------------------------------------------------------

def _scan_bubble(m, tag, check_ratio=True):
    """对 grab 图像做形状断言。

    - ``check_ratio``：断言宽高比 < 6:1（四种标准高度提示）。
    - 角部采样：y=3 与 y=H-4 处首个不透明像素的内缩量必须落在
      四分之一圆（半径 r = min(radius.pill, 半宽, 半高)）的预期值
      ±3px 内；椭圆端部内缩随宽度放大（≈0.13W 以上），会被
      ``W*0.12`` 上限拦截。
    - 中高度处边缘内缩必须为 0（胶囊侧边为直线，椭圆不是）。
    """
    img = m.grab().toImage()
    W, H = img.width(), img.height()
    if check_ratio and W / H >= 6:
        raise AssertionError(f"{tag} 宽高比 {W}/{H} = {W / H:.2f} ≥ 6:1")
    rect_h = H - 1  # paintEvent 中 rect.adjusted(0, 0, -1, -1)
    r = min(float(T("radius.pill")), rect_h / 2.0, (W - 1) / 2.0)
    cyc = rect_h / 2.0

    def first_opaque_x(y):
        return next((x for x in range(W)
                     if img.pixelColor(x, y).alpha() > 128), None)

    def expected_inset(y):
        dy = abs(y - cyc)
        if dy >= r:
            return 0.0
        return r - math.sqrt(max(0.0, r * r - dy * dy))

    for y in (3, H - 4):
        got = first_opaque_x(y)
        if got is None:
            raise AssertionError(f"{tag} y={y} 行无不透明像素")
        exp = expected_inset(y)
        if abs(got - exp) > 3:
            raise AssertionError(
                f"{tag} y={y} 角部内缩 {got}px，偏离四分之一圆预期 "
                f"{exp:.1f}px（疑似椭圆/尖角）")
        if got > W * 0.12:
            raise AssertionError(
                f"{tag} y={y} 端部内缩 {got}px 随宽度放大（W={W}），疑似椭圆")
    mid = first_opaque_x(H // 2)
    if mid is None or mid > 2:
        raise AssertionError(f"{tag} 中高度处边缘内缩 {mid}px，应为 0")


@check("message 四种类型均为圆角矩形胶囊（非椭圆）")
def _():
    from InstructionX_UIKit.components.message import Message

    host = QWidget()
    host.resize(640, 400)
    lay = QVBoxLayout(host)
    lay.addWidget(QLabel("宿主窗口"))
    host.show()
    APP.processEvents()

    cases = [("info", "这是一条信息提示"),
             ("success", "保存成功"),
             ("warning", "磁盘空间不足，请及时清理"),
             ("error", "任务执行失败，请重试")]
    msgs = []
    for tp, text in cases:
        m = Message.show(host, text, tp, duration=60000)
        msgs.append((tp, m))
    QTest.qWait(400)  # 等入场动画结束
    for tp, m in msgs:
        grab_both(m, f"message_{tp}")
        _scan_bubble(m, f"message[{tp}]")
    for _tp, m in msgs:
        m.dismiss()
    QTest.qWait(500)
    host.close()


@check("message 长文本换行：宽度 ≤480 且保持胶囊形状、堆叠不重叠")
def _():
    from InstructionX_UIKit.components.message import Message

    host = QWidget()
    host.resize(640, 400)
    host.show()
    APP.processEvents()

    long_text = ("系统检测到当前账户存在异常登录行为，为保障数据安全，"
                 "已临时锁定敏感操作权限，请前往安全中心完成身份验证后再试。")
    m = Message.show(host, long_text, "warning", duration=60000)
    QTest.qWait(400)
    if m.width() > 480:
        raise AssertionError(f"长文本气泡宽度 {m.width()} 超过 480px")
    if m.height() <= 36:
        raise AssertionError(f"长文本应换行增高，实际高度 {m.height()}")
    grab_both(m, "message_long")
    _scan_bubble(m, "message[long]", check_ratio=False)
    # 多条堆叠应基于实际高度排列，不重叠
    m2 = Message.show(host, "第二条提示", "info", duration=60000)
    QTest.qWait(400)
    if m2.y() < m.y() + m.height():
        raise AssertionError(
            f"堆叠气泡重叠: m.bottom={m.y() + m.height()} m2.top={m2.y()}")
    grab_both(m2, "message_stacked")
    _scan_bubble(m2, "message[stacked]")
    m.dismiss()
    m2.dismiss()
    QTest.qWait(500)
    host.close()


def main() -> int:
    print("反馈组件缺陷修复验证（offscreen）")
    SHOTS.mkdir(parents=True, exist_ok=True)
    print("-" * 60)
    TM.set_mode("light")
    APP.processEvents()
    expected = ["dropdown", "dropdown_menu", "dialog", "dialog_info",
                "message_info", "message_success", "message_warning",
                "message_error", "message_long", "message_stacked"]
    missing = [f"fix_feedback_{n}_{t}.png" for n in expected
               for t in ("light", "dark")
               if not (SHOTS / f"fix_feedback_{n}_{t}.png").exists()]
    if missing:
        print(f"缺少截图: {missing}")
        return 1
    print(f"截图目录: {SHOTS}（共 {len(_SHOT_LOG)} 张）")
    if _FAILURES:
        print(f"共 {len(_FAILURES)} 项失败: {_FAILURES}")
        return 1
    print("全部检查通过，0 错误")
    return 0


if __name__ == "__main__":
    sys.exit(main())
