# -*- coding: utf-8 -*-
"""数据展示组件自测（agent B，SPEC §5.2 / §9）。

直接运行（无 pytest 依赖）::

    QT_QPA_PLATFORM=offscreen python tests/test_components_display.py

覆盖：18 个数据展示组件逐个实例化，亮 / 暗主题各 grab() 截图到
``tests/shots/display_<name>_<theme>.png``；附带关键行为断言
（徽标 99+、折叠动画、轮播切换、二维码生成、树复选等）。
任何异常即失败，退出码 1。
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
SHOTS.mkdir(parents=True, exist_ok=True)

_FAILURES = []


def _ensure_app():
    """模块级创建 QApplication 并应用主题（@check 在导入期执行）。"""
    from PySide6.QtWidgets import QApplication

    from InstructionX_UIKit.theme import ThemeManager

    app = QApplication.instance() or QApplication(sys.argv)
    ThemeManager.instance().apply(app)
    return app


_APP = _ensure_app()

print("display 组件自测开始（offscreen）")
print("-" * 60)
print("[行为断言]")


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


def _gradient_pixmap(w=240, h=160, c1="#3563E9", c2="#3CBF8C"):
    """生成一张渐变测试图。"""
    from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPixmap

    pm = QPixmap(w, h)
    grad = QLinearGradient(0, 0, w, h)
    grad.setColorAt(0, QColor(c1))
    grad.setColorAt(1, QColor(c2))
    painter = QPainter(pm)
    painter.fillRect(pm.rect(), grad)
    painter.end()
    return pm


# ---------------------------------------------------------------------------
# 各组件演示构建函数：返回 (顶层宿主控件, 建议尺寸)
# ---------------------------------------------------------------------------

def build_avatar():
    from PySide6.QtWidgets import QHBoxLayout, QWidget
    from InstructionX_UIKit.components.avatar import Avatar

    host = QWidget()
    row = QHBoxLayout(host)
    row.setContentsMargins(12, 12, 12, 12)
    row.setSpacing(12)
    a1 = Avatar("张三", size="lg")
    a2 = Avatar("李", shape="square", size="lg")
    a3 = Avatar(size="lg")
    a3.set_image(_gradient_pixmap(80, 80))
    a4 = Avatar(size="lg")  # 空 -> 默认剪影
    a5 = Avatar("王芳", size=28)
    for a in (a1, a2, a3, a4, a5):
        row.addWidget(a)
    row.addStretch(1)
    return host, (360, 90)


def build_badge():
    from PySide6.QtWidgets import QHBoxLayout, QPushButton, QWidget
    from InstructionX_UIKit.components.badge import Badge

    host = QWidget()
    row = QHBoxLayout(host)
    row.setContentsMargins(16, 16, 16, 16)
    row.setSpacing(24)
    b1 = Badge(QPushButton("消息中心"), count=5)
    b2 = Badge(QPushButton("通知"), count=120)  # 99+
    b3 = Badge(QPushButton("红点"), dot=True)
    b4 = Badge(count=8)  # 独立角标
    b5 = Badge(dot=True, color="success")
    for b in (b1, b2, b3, b4, b5):
        row.addWidget(b)
    row.addStretch(1)
    return host, (460, 100)


def build_card():
    from PySide6.QtWidgets import QLabel, QPushButton, QVBoxLayout, QWidget
    from InstructionX_UIKit.components.card import Card
    from InstructionX_UIKit.theme import set_property

    host = QWidget()
    col = QVBoxLayout(host)
    col.setContentsMargins(12, 12, 12, 12)
    col.setSpacing(12)
    card = Card("订单概览", hoverable=True)
    extra = QPushButton("更多")
    set_property(extra, "variant", "link")
    set_property(extra, "size", "sm")
    card.set_extra(extra)
    card.body_layout().addWidget(QLabel("本月订单 1,280 笔，环比增长 12.5%。"))
    card.set_footer("更新于 10 分钟前")
    card2 = Card("无边框卡片", bordered=False)
    card2.body_layout().addWidget(QLabel("hoverable + bordered 变体演示。"))
    col.addWidget(card)
    col.addWidget(card2)
    return host, (420, 250)


def build_descriptions():
    from PySide6.QtWidgets import QVBoxLayout, QWidget
    from InstructionX_UIKit.components.descriptions import Descriptions

    host = QWidget()
    col = QVBoxLayout(host)
    col.setContentsMargins(12, 12, 12, 12)
    desc = Descriptions("用户信息", bordered=True)
    desc.set_items([
        ("姓名", "张三"), ("手机号", "138****8000"),
        ("城市", "上海"), ("邮箱", "zhang@example.com"),
        ("角色", "管理员"), ("状态", "在职"),
    ])
    col.addWidget(desc)
    desc2 = Descriptions()
    desc2.set_items([("创建时间", "2026-07-21 10:30"), ("备注", "自适应列数")])
    col.addWidget(desc2)
    col.addStretch(1)
    return host, (560, 230)


def build_list_view():
    from InstructionX_UIKit.components.list_view import ListWidget

    lw = ListWidget(item_height=36)
    lw.add_items(["收件箱", "星标邮件", "已发送", "草稿箱", "已删除"])
    lw.setCurrentRow(1)
    lw.resize(280, 220)
    return lw, (280, 220)


def build_table():
    from PySide6.QtWidgets import QVBoxLayout, QWidget
    from InstructionX_UIKit.components.table import Table

    host = QWidget()
    col = QVBoxLayout(host)
    col.setContentsMargins(12, 12, 12, 12)
    col.setSpacing(12)
    table = Table()
    table.set_data(
        ["姓名", "部门", "销售额"],
        [["张三", "华东", 12800], ["李四", "华北", 9600], ["王五", "华南", 15320]],
    )
    col.addWidget(table)
    empty = Table()
    empty.set_data(["姓名", "部门"], [])
    empty.set_empty_text("暂无符合条件的数据")
    empty.setMaximumHeight(120)
    col.addWidget(empty)
    return host, (460, 320)


def build_tree():
    from InstructionX_UIKit.components.tree import Tree

    tree = Tree(checkable=True)
    tree.set_data([
        ("水果", [("苹果", [("红富士", []), ("嘎啦", [])]), ("香蕉", [])]),
        ("蔬菜", [("白菜", []), ("萝卜", [])]),
    ])
    tree.expand_all()
    tree.resize(320, 240)
    return tree, (320, 240)


def build_timeline():
    from PySide6.QtWidgets import QVBoxLayout, QWidget
    from InstructionX_UIKit.components.timeline import Timeline

    host = QWidget()
    col = QVBoxLayout(host)
    col.setContentsMargins(12, 12, 12, 12)
    tl = Timeline(pending="等待骑手接单")
    tl.add_item("创建订单", time="2026-07-21 09:30")
    tl.add_item("支付成功", time="2026-07-21 09:32", color="success")
    tl.add_item("商家已接单", time="2026-07-21 09:35")
    col.addWidget(tl)
    col.addStretch(1)
    return host, (340, 260)


def build_statistic():
    from PySide6.QtWidgets import QHBoxLayout, QWidget
    from InstructionX_UIKit.components.statistic import Statistic

    host = QWidget()
    row = QHBoxLayout(host)
    row.setContentsMargins(12, 12, 12, 12)
    row.setSpacing(48)
    s1 = Statistic("活跃用户", 12800)
    s1.set_suffix("人")
    s1.set_trend(12.5)
    s2 = Statistic("成交金额", 93456.78, precision=2)
    s2.set_prefix("¥")
    s2.set_trend(-3.2)
    s3 = Statistic("待处理工单", 42)
    for s in (s1, s2, s3):
        row.addWidget(s)
    row.addStretch(1)
    return host, (520, 110)


def build_calendar():
    from InstructionX_UIKit.components.calendar import Calendar

    cal = Calendar()
    return cal, (400, 320)


def build_carousel():
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QLabel
    from InstructionX_UIKit.components.carousel import Carousel

    carousel = Carousel()
    colors = ["#7C5CFC", "#1E9E6A", "#E0962A"]
    for i, color in enumerate(colors):
        page = QLabel(f"第 {i + 1} 屏")
        page.setAlignment(Qt.AlignCenter)
        page.setStyleSheet(
            f"background-color: {color}; color: white; font-size: 20px; "
            f"border-radius: 8px; margin: 4px;"
        )
        carousel.add_page(page)
    carousel.resize(480, 240)
    return carousel, (480, 240)


def build_image_view():
    from PySide6.QtWidgets import QHBoxLayout, QWidget
    from InstructionX_UIKit.components.image_view import ImageView

    host = QWidget()
    row = QHBoxLayout(host)
    row.setContentsMargins(12, 12, 12, 12)
    row.setSpacing(12)
    ok = ImageView(_gradient_pixmap(400, 300))
    ok.setFixedSize(200, 150)
    bad = ImageView("/nonexistent/path/to/image.png")
    bad.setFixedSize(200, 150)
    row.addWidget(ok)
    row.addWidget(bad)
    return host, (440, 180)


def build_qrcode_view():
    from PySide6.QtWidgets import QHBoxLayout, QWidget
    from InstructionX_UIKit.components.qrcode_view import QRCodeView

    host = QWidget()
    row = QHBoxLayout(host)
    row.setContentsMargins(12, 12, 12, 12)
    row.setSpacing(16)
    qr1 = QRCodeView("https://example.com/uik", size=120)
    qr2 = QRCodeView("PySide6 UI Kit 二维码", size=120, error_correction="H")
    row.addWidget(qr1)
    row.addWidget(qr2)
    return host, (340, 170)


def build_comment():
    from PySide6.QtWidgets import QVBoxLayout, QWidget
    from InstructionX_UIKit.components.comment import CommentView

    host = QWidget()
    col = QVBoxLayout(host)
    col.setContentsMargins(12, 12, 12, 12)
    c = CommentView("张三", "这个组件库的暗色主题做得很细致，表格斑马纹很清楚。",
                    "2 小时前", actions=["回复", "赞"])
    reply = CommentView("李四", "同感，期待图表页面。", "1 小时前",
                        actions=["回复"])
    reply2 = CommentView("王五", "折叠面板的动画也很顺滑。", "30 分钟前")
    c.add_reply(reply)
    c.add_reply(reply2)
    col.addWidget(c)
    col.addStretch(1)
    return host, (460, 260)


def build_collapse():
    from PySide6.QtWidgets import QLabel
    from InstructionX_UIKit.components.collapse import Collapse

    col = Collapse()
    col.add_panel("什么是 PySide6 UI Kit？",
                  "一套基于设计令牌与主题系统的 PySide6 组件库。",
                  expanded=True)
    col.add_panel("如何切换暗色主题？",
                  "调用 ThemeManager.instance().toggle() 即可全局切换。")
    col.add_panel("是否支持自定义组件？",
                  QLabel("可以，所有组件均基于 Qt 原生控件子类化。"))
    col.resize(420, 240)
    return col, (420, 240)


def build_empty():
    from InstructionX_UIKit.components.empty import Empty

    empty = Empty("暂无搜索结果，换个关键词试试")
    empty.set_action("清空筛选")
    empty.resize(320, 260)
    return empty, (320, 260)


def build_tooltip():
    from PySide6.QtWidgets import QHBoxLayout, QPushButton, QWidget
    from InstructionX_UIKit.components.tooltip import set_tooltip
    from InstructionX_UIKit.theme import set_property

    host = QWidget()
    row = QHBoxLayout(host)
    row.setContentsMargins(12, 12, 12, 12)
    btn = QPushButton("悬停查看提示")
    set_property(btn, "variant", "primary")
    set_tooltip(btn, "这是由全局 QSS 统一样式的工具提示。", title="操作提示")
    btn2 = QPushButton("纯文本提示")
    set_tooltip(btn2, "只有正文的提示")
    row.addWidget(btn)
    row.addWidget(btn2)
    return host, (320, 90)


_POPOVERS = []  # 防止弹出层被 GC


def build_popover():
    from PySide6.QtWidgets import QPushButton, QVBoxLayout, QWidget
    from InstructionX_UIKit.components.popover import Popover

    host = QWidget()
    col = QVBoxLayout(host)
    col.setContentsMargins(12, 12, 12, 12)
    anchor = QPushButton("锚点按钮")
    col.addWidget(anchor, 0)
    col.addStretch(1)
    host.resize(320, 200)
    pop = Popover("快捷筛选", "按状态、时间或负责人筛选列表数据。\n点击外部区域关闭。")
    _POPOVERS.append(pop)
    host._popover = pop  # noqa: SLF001
    host._anchor = anchor  # noqa: SLF001
    return host, (320, 200)


BUILDERS = {
    "avatar": build_avatar,
    "badge": build_badge,
    "card": build_card,
    "descriptions": build_descriptions,
    "list_view": build_list_view,
    "table": build_table,
    "tree": build_tree,
    "timeline": build_timeline,
    "statistic": build_statistic,
    "calendar": build_calendar,
    "carousel": build_carousel,
    "image_view": build_image_view,
    "qrcode_view": build_qrcode_view,
    "comment": build_comment,
    "collapse": build_collapse,
    "empty": build_empty,
    "tooltip": build_tooltip,
    "popover": build_popover,
}


# ---------------------------------------------------------------------------
# 截图
# ---------------------------------------------------------------------------

def grab_all(app, theme: str) -> None:
    from PySide6.QtTest import QTest

    from InstructionX_UIKit.theme import ThemeManager

    ThemeManager.instance().set_mode(theme)
    app.processEvents()
    for name, builder in BUILDERS.items():
        host = None
        try:
            host, size = builder()
            host.resize(*size)
            host.show()
            app.processEvents()
            QTest.qWait(30)
            if name == "popover":
                pop = host._popover  # noqa: SLF001
                pop.show_for(host._anchor, placement="bottom")  # noqa: SLF001
                app.processEvents()
                QTest.qWait(30)
                shot = pop.grab()
            else:
                shot = host.grab()
            path = SHOTS / f"display_{name}_{theme}.png"
            if not shot.save(str(path)):
                raise RuntimeError(f"截图保存失败: {path}")
            if shot.width() == 0 or shot.height() == 0:
                raise RuntimeError(f"截图为空: {name}")
            print(f"  截图: {path.name} ({shot.width()}x{shot.height()})")
        except Exception:
            _FAILURES.append(f"grab:{name}:{theme}")
            print(f"  [失败] grab {name} ({theme})")
            traceback.print_exc()
        finally:
            if name == "popover" and host is not None:
                host._popover.hide()  # noqa: SLF001
            if host is not None:
                host.hide()
                host.deleteLater()
        app.processEvents()


# ---------------------------------------------------------------------------
# 行为断言
# ---------------------------------------------------------------------------

@check("徽标 99+ / 红点 / 独立模式")
def _():
    from InstructionX_UIKit.components.badge import Badge

    b = Badge(count=120)
    assert b._text() == "99+", b._text()
    b.set_max_count(999)
    assert b._text() == "120"
    b.set_dot(True)
    assert b.is_dot()
    b.set_color("success")


@check("折叠面板动画展开 / 手风琴互斥")
def _():
    from PySide6.QtTest import QTest
    from InstructionX_UIKit.components.collapse import Collapse

    # 普通模式：可同时展开
    col = Collapse()
    col.add_panel("一", "内容一")
    col.add_panel("二", "内容二")
    col.resize(400, 300)
    col.show()
    col.set_expanded(0, True)
    col.set_expanded(1, True)
    QTest.qWait(350)  # 等待高度动画结束
    assert col.is_expanded(0) and col.is_expanded(1)
    col.hide()
    col.deleteLater()

    # 手风琴模式：展开 1 应收起 0
    acc = Collapse(accordion=True)
    acc.add_panel("一", "内容一")
    acc.add_panel("二", "内容二")
    acc.resize(400, 300)
    acc.show()
    acc.set_expanded(0, True)
    acc.set_expanded(1, True)
    QTest.qWait(350)
    assert not acc.is_expanded(0) and acc.is_expanded(1)
    acc.hide()
    acc.deleteLater()


@check("轮播滑动切换与指示点")
def _():
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QLabel
    from InstructionX_UIKit.components.carousel import Carousel

    c = Carousel()
    fired = []
    c.currentChanged.connect(fired.append)
    for i in range(3):
        c.add_page(QLabel(f"p{i}"))
    c.resize(400, 200)
    c.show()
    c.go_to(1)
    QTest.qWait(450)  # 滑动画结束
    assert c.current_index() == 1 and fired == [1], (c.current_index(), fired)
    c.prev()
    QTest.qWait(450)
    assert c.current_index() == 0
    c.hide()


@check("二维码矩阵生成与导出")
def _():
    from InstructionX_UIKit.components.qrcode_view import QRCodeView

    qr = QRCodeView("https://example.com", size=100, error_correction="Q")
    assert qr._matrix and len(qr._matrix) > 20
    pm = qr.to_pixmap()
    assert not pm.isNull() and pm.width() == qr.width()
    try:
        qr.set_error_correction("X")
        raise AssertionError("应拒绝非法容错级别")
    except ValueError:
        pass


@check("树复选 / 表格数据与空态")
def _():
    from PySide6.QtCore import Qt
    from InstructionX_UIKit.components.table import Table
    from InstructionX_UIKit.components.tree import Tree

    tree = Tree(checkable=True)
    tree.set_data([("A", [("A1", [])])])
    item = tree.topLevelItem(0)
    assert item.flags() & Qt.ItemIsUserCheckable
    tree.set_checkable(False)

    table = Table()
    table.set_data(["c1", "c2"], [[1, 2], [3, 4]])
    assert table.rowCount() == 2 and table.columnCount() == 2
    table.set_data(["c1"], [])
    assert table.rowCount() == 0  # 空态占位由 paintEvent 绘制


@check("时间轴 / 统计 / 描述列表行为")
def _():
    from InstructionX_UIKit.components.descriptions import Descriptions
    from InstructionX_UIKit.components.statistic import Statistic
    from InstructionX_UIKit.components.timeline import Timeline

    tl = Timeline(pending="进行中")
    tl.add_item("节点一", time="10:00")
    assert tl.sizeHint().height() > 50
    tl.set_pending(None)

    st = Statistic("标题", 100)
    st.set_trend(-2.5)
    st.clear_trend()
    st.set_value(1234.5, precision=1)
    assert st._value_label.text() == "1,234.5"

    desc = Descriptions(column=2, bordered=True)
    desc.set_items([("a", "1"), ("b", "2"), ("c", "3")])
    desc.resize(500, 200)
    desc.show()
    assert desc._grid.count() == 3
    desc.hide()


@check("头像回退 / 图片失败占位 / 提示函数 / 气泡方位校验")
def _():
    from PySide6.QtWidgets import QPushButton
    from InstructionX_UIKit.components.avatar import Avatar
    from InstructionX_UIKit.components.image_view import ImageView
    from InstructionX_UIKit.components.popover import Popover
    from InstructionX_UIKit.components.tooltip import set_tooltip

    a = Avatar("测试")
    a.set_image("/no/such/file.png")  # 加载失败 -> 回退文字
    assert a.text() == "测试"
    a.set_shape("square")
    a.set_size("sm")

    iv = ImageView("/no/such/file.png")
    assert iv.is_failed()

    btn = QPushButton("x")
    set_tooltip(btn, "正文", title="标题")
    assert "标题" in btn.toolTip()

    pop = Popover("t", "content")
    try:
        pop.show_for(btn, placement="nowhere")
        raise AssertionError("应拒绝非法方位")
    except ValueError:
        pass


def main() -> int:
    from PySide6.QtWidgets import QApplication

    from InstructionX_UIKit.theme import ThemeManager

    app = QApplication.instance() or QApplication(sys.argv)
    ThemeManager.instance().apply(app)

    print("-" * 60)
    print("[截图] 亮色主题")
    grab_all(app, "light")
    print("[截图] 暗色主题")
    grab_all(app, "dark")

    print("-" * 60)
    if _FAILURES:
        print(f"共 {len(_FAILURES)} 项失败: {_FAILURES}")
        return 1
    print("全部检查通过，0 错误")
    return 0


if __name__ == "__main__":
    sys.exit(main())
