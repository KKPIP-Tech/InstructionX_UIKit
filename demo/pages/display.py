# -*- coding: utf-8 -*-
"""组件 · 展示演示页：18 个数据展示组件，每组件一页，覆盖主要变体。

页面 = 标题 + 说明 + 分区演示，紧凑排布；亮 / 暗主题切换自动换肤。
"""

from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QColor, QIcon, QLinearGradient, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QStyle,
    QVBoxLayout,
    QWidget,
)

from InstructionX_UIKit.components.avatar import Avatar
from InstructionX_UIKit.components.badge import Badge
from InstructionX_UIKit.components.calendar import Calendar
from InstructionX_UIKit.components.card import Card
from InstructionX_UIKit.components.carousel import Carousel
from InstructionX_UIKit.components.collapse import Collapse
from InstructionX_UIKit.components.comment import CommentView
from InstructionX_UIKit.components.descriptions import Descriptions
from InstructionX_UIKit.components.empty import Empty
from InstructionX_UIKit.components.image_view import ImageView
from InstructionX_UIKit.components.list_view import ListWidget
from InstructionX_UIKit.components.popover import Popover
from InstructionX_UIKit.components.qrcode_view import QRCodeView
from InstructionX_UIKit.components.statistic import Statistic
from InstructionX_UIKit.components.table import Table
from InstructionX_UIKit.components.timeline import Timeline
from InstructionX_UIKit.components.tooltip import set_tooltip
from InstructionX_UIKit.components.tree import Tree
from InstructionX_UIKit.theme import T, set_property

from .common import Section, col, hint_label, make_page, row
from .playground import PlaygroundPanel, with_playground

_POPOVERS = []  # 防止弹出层被 GC


def _gradient_pixmap(w=240, h=160, c1="#3F5E8C", c2="#6BA98A"):
    """生成一张渐变测试图。"""
    pm = QPixmap(w, h)
    grad = QLinearGradient(0, 0, w, h)
    grad.setColorAt(0, QColor(c1))
    grad.setColorAt(1, QColor(c2))
    painter = QPainter(pm)
    painter.fillRect(pm.rect(), grad)
    painter.end()
    return pm


def _disabled(widget) -> QWidget:
    widget.setEnabled(False)
    return widget


def create_avatar_page() -> QWidget:
    s = Section("头像")
    img = Avatar(size="lg")
    img.set_image(_gradient_pixmap(80, 80))
    s.layout().addWidget(row(
        Avatar("张三", size="lg"), Avatar("李", shape="square", size="lg"),
        img, Avatar(size="lg"), Avatar("王芳", size=28)))
    return make_page("Avatar 头像", "圆形 / 方形，图片 / 文字 / 图标回退，多种尺寸。", [s])


def create_badge_page() -> QWidget:
    s = Section("徽标")
    s.layout().addWidget(row(
        Badge(QPushButton("消息中心"), count=5),
        Badge(QPushButton("通知"), count=120),
        Badge(QPushButton("红点"), dot=True),
        Badge(count=8),
        Badge(dot=True, color="success")))
    return make_page("Badge 徽标", "包裹任意子控件角标、独立点模式、99+ 上限。", [s])


def create_card_page() -> QWidget:
    s = Section("卡片")
    card = Card("订单概览", hoverable=True)
    extra = QPushButton("更多")
    set_property(extra, "variant", "link")
    set_property(extra, "size", "sm")
    card.set_extra(extra)
    card.body_layout().addWidget(QLabel("本月订单 1,280 笔，环比增长 12.5%。"))
    card.set_footer("更新于 10 分钟前")
    card2 = Card("无边框卡片", bordered=False)
    card2.body_layout().addWidget(QLabel("hoverable + bordered 变体演示。"))
    s.layout().addWidget(row(card, card2))
    return make_page("Card 卡片", "title / extra / footer 槽，hoverable、bordered 变体。", [s])


def create_descriptions_page() -> QWidget:
    s = Section("描述列表")
    desc = Descriptions("用户信息", bordered=True)
    desc.set_items([
        ("姓名", "张三"), ("手机号", "138****8000"), ("城市", "上海"),
        ("邮箱", "zhang@example.com"), ("角色", "管理员"), ("状态", "在职"),
    ])
    s.layout().addWidget(desc)
    return make_page("Descriptions 描述列表", "列数自适应，可选边框。", [s])


def create_list_view_page() -> QWidget:
    s = Section("列表")
    lw = ListWidget(item_height=36)
    lw.add_items(["收件箱", "星标邮件", "已发送", "草稿箱", "已删除"])
    lw.setCurrentRow(1)
    lw.setFixedSize(300, 240)
    s.layout().addWidget(row(lw))
    return make_page("ListWidget 列表", "统一项高、hover 与选中样式。", [s])


def create_table_page() -> QWidget:
    s = Section("表格")
    table = Table()
    table.set_data(
        ["姓名", "部门", "销售额"],
        [["张三", "华东", 12800], ["李四", "华北", 9600],
         ["王五", "华南", 15320], ["赵六", "西南", 8450]])
    table.setFixedHeight(200)
    s.layout().addWidget(table)
    empty = Table()
    empty.set_data(["姓名", "部门"], [])
    empty.set_empty_text("暂无符合条件的数据")
    empty.setFixedHeight(120)
    s.layout().addWidget(empty)
    return make_page("Table 表格", "斑马纹、紧凑行高、排序与空状态占位。", [s])


def create_tree_page() -> QWidget:
    s = Section("树")
    tree = Tree(checkable=True)
    tree.set_data([
        ("水果", [("苹果", [("红富士", []), ("嘎啦", [])]), ("香蕉", [])]),
        ("蔬菜", [("白菜", []), ("萝卜", [])]),
    ])
    tree.expand_all()
    tree.setFixedSize(320, 240)
    s.layout().addWidget(row(tree))
    return make_page("Tree 树", "缩进线样式与复选支持。", [s])


class TimelineEx(Timeline):
    """时间轴游乐场扩展（demo 侧子类，不改动 InstructionX_UIKit）。

    InstructionX_UIKit ``Timeline`` 仅暴露 ``add_item`` / ``set_pending`` 等数据 API，
    线条样式 / 粗细、节点半径、行距、字号、轴侧等绘制参数没有 setter；
    这里以子类属性 + 重写 ``paintEvent`` / ``_row_height`` 的方式暴露，
    数据层面仍完全复用基类 API。
    """

    def __init__(self, pending: str = None, parent=None):
        super().__init__(pending, parent)
        self.line_width = 1.0               # 连接线宽 px
        self.line_style = Qt.SolidLine      # 连接线样式
        self.dot_radius = 5                 # 节点半径 px
        self.extra_spacing = 0              # 每行附加间距 px
        self.axis_side = "left"             # 轴线位置：left / right
        self.title_font_size = T("font.md")
        self.time_font_size = T("font.xs")

    def _row_height(self, item) -> int:
        base = 46 if item["time"] else 30
        return base + int(self.extra_spacing)

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        line_color = QColor(T("color.border"))
        text_primary = QColor(T("color.text.primary"))
        text_tertiary = QColor(T("color.text.tertiary"))

        font_text = painter.font()
        font_text.setPixelSize(int(self.title_font_size))
        font_time = painter.font()
        font_time.setPixelSize(int(self.time_font_size))

        right = self.axis_side == "right"
        w = self.width()
        dot_x = w - 16 if right else 16
        r = int(self.dot_radius)
        align = (Qt.AlignVCenter | Qt.AlignRight) if right \
            else (Qt.AlignVCenter | Qt.AlignLeft)

        def text_rect(y, h):
            if right:
                return QRect(8, y, dot_x - 20, h)
            return QRect(36, y, w - 44, h)

        y = 10
        prev_dot_y = None
        for item in self._items:
            row_h = self._row_height(item)
            dot_y = y + 11
            if prev_dot_y is not None:
                painter.setPen(QPen(line_color, self.line_width, self.line_style))
                painter.drawLine(dot_x, prev_dot_y, dot_x, dot_y)
            icon = item["icon"]
            if isinstance(icon, QIcon) and not icon.isNull():
                painter.fillRect(QRect(dot_x - 7, dot_y - 7, 14, 14),
                                 QColor(T("color.bg.base")))
                icon.paint(painter, QRect(dot_x - 7, dot_y - 7, 14, 14))
            else:
                painter.setPen(Qt.NoPen)
                painter.setBrush(self._color_of(item))
                painter.drawEllipse(dot_x - r, dot_y - r, r * 2, r * 2)
            painter.setFont(font_text)
            painter.setPen(text_primary)
            painter.drawText(text_rect(y, 22), align, item["text"])
            if item["time"]:
                painter.setFont(font_time)
                painter.setPen(text_tertiary)
                painter.drawText(text_rect(y + 22, 16), align, item["time"])
            prev_dot_y = dot_y
            y += row_h

        # 尾部 pending：虚线 + 空心节点
        if self._pending:
            dot_y = y + 30
            painter.setPen(QPen(line_color, self.line_width, Qt.DashLine))
            start_y = prev_dot_y if prev_dot_y is not None else y
            painter.drawLine(dot_x, start_y, dot_x, dot_y)
            painter.setPen(QPen(QColor(T("color.primary")), 1.5))
            painter.setBrush(QColor(T("color.bg.base")))
            painter.drawEllipse(dot_x - r, dot_y - r, r * 2, r * 2)
            painter.setFont(font_text)
            painter.setPen(text_tertiary)
            painter.drawText(text_rect(dot_y - 11, 22), align,
                             str(self._pending))
        painter.end()


_TL_ITEMS = [
    ("创建订单", "2026-07-21 09:30"),
    ("支付成功", "2026-07-21 09:32"),
    ("商家已接单", "2026-07-21 09:35"),
]
_TL_ICONS = [
    QStyle.StandardPixmap.SP_FileDialogNewFolder,
    QStyle.StandardPixmap.SP_DialogApplyButton,
    QStyle.StandardPixmap.SP_ArrowForward,
]


def create_timeline_page() -> QWidget:
    s = Section("时间轴（右侧参数实时生效）")
    state = {
        "colors": [None, "success", None],  # None = 主题 primary
        "icon_mode": False,
        "pending_on": True,
        "pending_text": "等待骑手接单",
    }
    tl = TimelineEx(pending=state["pending_text"])
    tl.setMinimumHeight(260)

    def rebuild_items():
        tl.clear()
        for i, (text, time) in enumerate(_TL_ITEMS):
            icon = tl.style().standardIcon(_TL_ICONS[i]) \
                if state["icon_mode"] else None
            tl.add_item(text, time=time, color=state["colors"][i], icon=icon)

    def apply_pending(*_):
        tl.set_pending(state["pending_text"] if state["pending_on"] else None)

    rebuild_items()

    panel = PlaygroundPanel("时间轴参数")
    color_opts = [("主题 primary", None), ("成功 success", "success"),
                  ("警告 warning", "warning"), ("危险 danger", "danger")]
    for i in range(3):
        panel.add_choice(
            f"节点{i + 1}颜色", color_opts, state["colors"][i],
            lambda v, i=i: (state["colors"].__setitem__(i, v), rebuild_items()),
            key=f"color{i}")
    panel.add_bool("显示 pending", True,
                   lambda v: (state.__setitem__("pending_on", v),
                              apply_pending()), key="pending_on")
    panel.add_text("pending 文本", state["pending_text"],
                   lambda v: (state.__setitem__("pending_text", v),
                              apply_pending()), key="pending_text")
    panel.add_choice("节点图标", [("圆点", False), ("图标", True)], False,
                     lambda v: (state.__setitem__("icon_mode", v),
                                rebuild_items()), key="icon_mode")
    panel.add_choice("线条样式", [("实线", Qt.SolidLine), ("虚线", Qt.DashLine),
                                ("点线", Qt.DotLine)], Qt.SolidLine,
                     lambda v: (setattr(tl, "line_style", v), tl.update()),
                     key="line_style")
    panel.add_int("线条粗细", 1, 1, 4,
                  lambda v: (setattr(tl, "line_width", float(v)), tl.update()),
                  key="line_width")
    panel.add_int("节点半径", 5, 3, 9,
                  lambda v: (setattr(tl, "dot_radius", v), tl.update()),
                  key="dot_radius")
    panel.add_int("行距附加", 0, 0, 24,
                  lambda v: (setattr(tl, "extra_spacing", v),
                             tl.updateGeometry(), tl.update()),
                  key="spacing")
    panel.add_choice("轴线位置", [("左侧", "left"), ("右侧", "right")], "left",
                     lambda v: (setattr(tl, "axis_side", v), tl.update()),
                     key="axis_side")
    panel.add_int("正文字号", 13, 10, 18,
                  lambda v: (setattr(tl, "title_font_size", v), tl.update()),
                  key="font_size")
    panel.add_int("时间字号", 11, 8, 14,
                  lambda v: (setattr(tl, "time_font_size", v), tl.update()),
                  key="time_font_size")

    s.layout().addWidget(with_playground(tl, panel))
    return make_page(
        "Timeline 时间轴",
        "自绘节点颜色 / 图标，pending 尾部。右侧面板实时调节节点颜色、图标、"
        "pending、线条样式 / 粗细、节点半径、行距、轴侧与字号。",
        [s])


def create_statistic_page() -> QWidget:
    s = Section("统计数值")
    s1 = Statistic("活跃用户", 12800)
    s1.set_suffix("人")
    s1.set_trend(12.5)
    s2 = Statistic("成交金额", 93456.78, precision=2)
    s2.set_prefix("¥")
    s2.set_trend(-3.2)
    s3 = Statistic("待处理工单", 42)
    s.layout().addWidget(row(s1, s2, s3, spacing=48))
    return make_page("Statistic 统计数值", "标题 + 大数值 + 前后缀 + 趋势箭头。", [s])


def create_calendar_page() -> QWidget:
    s = Section("日历")
    cal = Calendar()
    cal.setFixedSize(420, 340)
    s.layout().addWidget(row(cal))
    return make_page("Calendar 日历", "中文表头、今日高亮。", [s])


def create_carousel_page() -> QWidget:
    s = Section("走马灯")
    carousel = Carousel()
    for i, color in enumerate(["#7C5CFC", "#3E7E5F", "#C08A3E"]):
        page = QLabel(f"第 {i + 1} 屏")
        page.setAlignment(Qt.AlignCenter)
        page.setStyleSheet(
            f"background-color: {color}; color: white; font-size: 20px; "
            f"border-radius: 8px; margin: 4px;")
        carousel.add_page(page)
    carousel.setFixedSize(520, 260)
    s.layout().addWidget(row(carousel))
    return make_page("Carousel 走马灯", "QStackedLayout + 指示点 + 左右箭头，autoplay。", [s])


def create_image_view_page() -> QWidget:
    s = Section("图片")
    ok = ImageView(_gradient_pixmap(400, 300))
    ok.setFixedSize(220, 165)
    bad = ImageView("/nonexistent/path/to/image.png")
    bad.setFixedSize(220, 165)
    s.layout().addWidget(row(ok, bad))
    s.layout().addWidget(hint_label("左：圆角图片 + hover 预览蒙层；右：加载失败占位。", role="tertiary"))
    return make_page("ImageView 图片", "圆角图片、加载失败占位、hover 预览蒙层。", [s])


def create_qrcode_page() -> QWidget:
    s = Section("二维码")
    s.layout().addWidget(row(
        QRCodeView("https://example.com/uik", size=130),
        QRCodeView("InstructionX_UIKit 二维码", size=130, error_correction="H"),
        spacing=24))
    return make_page("QRCodeView 二维码", "qrcode 库生成，容错级别参数。", [s])


def create_comment_page() -> QWidget:
    s = Section("评论")
    c = CommentView("张三", "这个组件库的暗色主题做得很细致，表格斑马纹很清楚。",
                    "2 小时前", actions=["回复", "赞"])
    c.add_reply(CommentView("李四", "同感，期待图表页面。", "1 小时前", actions=["回复"]))
    c.add_reply(CommentView("王五", "折叠面板的动画也很顺滑。", "30 分钟前"))
    s.layout().addWidget(c)
    return make_page("CommentView 评论", "头像 + 作者 + 时间 + 内容 + 操作行，可嵌套回复。", [s])


def create_collapse_page() -> QWidget:
    s = Section("折叠面板")
    cl = Collapse()
    cl.add_panel("什么是 InstructionX_UIKit？",
                 "一套基于设计令牌与主题系统的 PySide6 组件库。", expanded=True)
    cl.add_panel("如何切换暗色主题？",
                 "调用 ThemeManager.instance().toggle() 即可全局切换。")
    cl.add_panel("是否支持自定义组件？",
                 QLabel("可以，所有组件均基于 Qt 原生控件子类化。"))
    cl.setMinimumWidth(480)
    cl.setMinimumHeight(260)
    s.layout().addWidget(cl)
    return make_page("Collapse 折叠面板", "手风琴可选，动画展开。", [s])


def create_empty_page() -> QWidget:
    s = Section("空状态")
    empty = Empty("暂无搜索结果，换个关键词试试")
    empty.set_action("清空筛选")
    empty.setMinimumHeight(280)
    s.layout().addWidget(empty)
    return make_page("Empty 空状态", "自绘插画 + 描述 + 操作按钮槽。", [s])


def create_tooltip_page() -> QWidget:
    s = Section("工具提示")
    btn = QPushButton("悬停查看提示")
    set_property(btn, "variant", "primary")
    set_tooltip(btn, "这是由全局 QSS 统一样式的工具提示。", title="操作提示")
    btn2 = QPushButton("纯文本提示")
    set_tooltip(btn2, "只有正文的提示")
    s.layout().addWidget(row(btn, btn2))
    s.layout().addWidget(hint_label("运行 Demo 后将鼠标悬停在按钮上即可看到富样式提示。", role="tertiary"))
    return make_page("Tooltip 工具提示", "set_tooltip(widget, text) 富样式 QToolTip。", [s])


def create_popover_page() -> QWidget:
    s = Section("气泡卡片")
    anchor = QPushButton("点击弹出气泡卡片")
    set_property(anchor, "variant", "primary")
    pop = Popover("快捷筛选", "按状态、时间或负责人筛选列表数据。\n点击外部区域关闭。")
    _POPOVERS.append(pop)
    anchor.clicked.connect(lambda: pop.show_for(anchor, placement="bottom"))
    s.layout().addWidget(row(anchor))
    s.layout().addWidget(hint_label("点击按钮相对锚点弹出带箭头气泡卡片。", role="tertiary"))
    return make_page("Popover 气泡卡片", "相对锚点弹出（QFrame, Popup），带箭头。", [s])


#: 展示组件页注册表：(导航键, 标题, 页面工厂)
DISPLAY_PAGES = [
    ("avatar", "Avatar 头像", create_avatar_page),
    ("badge", "Badge 徽标", create_badge_page),
    ("card", "Card 卡片", create_card_page),
    ("descriptions", "Descriptions 描述列表", create_descriptions_page),
    ("list_view", "ListWidget 列表", create_list_view_page),
    ("table", "Table 表格", create_table_page),
    ("tree", "Tree 树", create_tree_page),
    ("timeline", "Timeline 时间轴", create_timeline_page),
    ("statistic", "Statistic 统计数值", create_statistic_page),
    ("calendar", "Calendar 日历", create_calendar_page),
    ("carousel", "Carousel 走马灯", create_carousel_page),
    ("image_view", "ImageView 图片", create_image_view_page),
    ("qrcode_view", "QRCodeView 二维码", create_qrcode_page),
    ("comment", "CommentView 评论", create_comment_page),
    ("collapse", "Collapse 折叠面板", create_collapse_page),
    ("empty", "Empty 空状态", create_empty_page),
    ("tooltip", "Tooltip 工具提示", create_tooltip_page),
    ("popover", "Popover 气泡卡片", create_popover_page),
]
