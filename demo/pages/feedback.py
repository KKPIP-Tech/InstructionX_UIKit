# -*- coding: utf-8 -*-
"""组件 · 反馈演示页：19 个导航与反馈组件，每组件一页，覆盖主要变体。

弹出类组件（对话框 / 抽屉 / 通知 / 轻提示 / 气泡确认 / 漫游引导）以
触发按钮演示；其余以内联变体演示。亮 / 暗主题切换自动换肤。
"""

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPen
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from InstructionX_UIKit.components.alert import Alert
from InstructionX_UIKit.components.anchor import Anchor
from InstructionX_UIKit.components.breadcrumb import Breadcrumb
from InstructionX_UIKit.components.dialog import Dialog
from InstructionX_UIKit.components.drawer import Drawer
from InstructionX_UIKit.components.dropdown import DropdownButton
from InstructionX_UIKit.components.message import Message
from InstructionX_UIKit.components.nav_menu import NavMenu
from InstructionX_UIKit.components.notification import Notification
from InstructionX_UIKit.components.page_header import PageHeader
from InstructionX_UIKit.components.pagination import Pagination
from InstructionX_UIKit.components.popconfirm import Popconfirm
from InstructionX_UIKit.components.progress_bar import CircleProgress, ProgressBar
from InstructionX_UIKit.components.result import ResultView
from InstructionX_UIKit.components.skeleton import Skeleton
from InstructionX_UIKit.components.spinner import Spinner
from InstructionX_UIKit.components.steps import Steps
from InstructionX_UIKit.components.tabs import Tabs
from InstructionX_UIKit.components.tour import Tour
from InstructionX_UIKit.theme import T, set_property

from .common import Section, col, hint_label, make_page, row
from .playground import PlaygroundPanel, swap_widget, with_playground

_KEEP = []  # 防止弹出层 / 引导层被 GC


def _primary(text):
    btn = QPushButton(text)
    set_property(btn, "variant", "primary")
    return btn


def _disabled(widget) -> QWidget:
    widget.setEnabled(False)
    return widget


def create_tabs_page() -> QWidget:
    s = Section("三种样式")
    for variant in ("line", "card", "segmented"):
        t = Tabs(variant)
        for page in ("概览", "明细", "设置"):
            lab = QLabel(f"{variant} - {page} 内容区")
            lab.setAlignment(Qt.AlignCenter)
            lab.setMinimumHeight(70)
            t.addTab(lab, page)
        t.setCurrentIndex(1)
        s.layout().addWidget(t)
    return make_page("Tabs 标签页", "line / card / segmented 三种样式。", [s])


def create_anchor_page() -> QWidget:
    s = Section("锚点联动")
    host = QWidget()
    lay = QHBoxLayout(host)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(16)
    anchor = Anchor()
    anchor.setFixedWidth(150)
    area = QScrollArea()
    area.setWidgetResizable(True)
    content = QWidget()
    vbox = QVBoxLayout(content)
    vbox.setSpacing(12)
    sections = []
    metas = [("base", "基本信息"), ("safe", "安全设置"),
             ("notify", "通知偏好"), ("about", "关于产品")]
    for key, title in metas:
        sec = QLabel(f"{title}\n" + "配置项示例文本\n" * 5)
        sec.setFrameShape(QFrame.Shape.StyledPanel)
        vbox.addWidget(sec)
        sections.append(sec)
    area.setWidget(content)
    anchor.set_items([(k, t, w) for (k, t), w in zip(metas, sections)])
    anchor.bind_scroll_area(area)
    lay.addWidget(anchor)
    lay.addWidget(area, 1)
    host.setMinimumHeight(300)
    s.layout().addWidget(host)
    return make_page("Anchor 锚点", "配合 QScrollArea 高亮当前段，点击滚动定位。", [s])


def create_breadcrumb_page() -> QWidget:
    s = Section("面包屑")
    s.layout().addWidget(Breadcrumb(["首页", "组件库", "导航", "面包屑"]))
    s.layout().addWidget(Breadcrumb(["仪表盘", "实时数据", "节点详情"], separator=">"))
    return make_page("Breadcrumb 面包屑", "分隔符可配，末级加粗，可点击。", [s])


def create_dropdown_page() -> QWidget:
    s = Section("下拉菜单按钮")
    dd = DropdownButton("更多操作")
    dd.add_item("edit", "编辑", shortcut="Ctrl+E")
    dd.add_item("share", "分享")
    dd.add_item("disabled", "禁用项", enabled=False)
    dd.add_separator()
    dd.add_item("del", "删除", danger=True)
    s.layout().addWidget(row(dd))
    s.layout().addWidget(hint_label("菜单项支持图标 / 快捷键 / 危险项。", role="tertiary"))
    return make_page("DropdownButton 下拉菜单", "QMenu 封装，菜单项带图标 / 快捷键 / 危险项。", [s])


def create_nav_menu_page() -> QWidget:
    s = Section("侧边导航菜单")
    nav = NavMenu()
    nav.setFixedSize(250, 400)
    nav.add_group("概览")
    nav.add_item("dash", "仪表盘", group="概览")
    nav.add_item("monitor", "实时监控", group="概览")
    nav.add_group("系统管理")
    nav.add_item("user", "用户管理", group="系统管理")
    nav.add_item("role", "角色权限", group="系统管理")
    nav.add_item("setting", "偏好设置")
    nav.set_current("monitor")
    s.layout().addWidget(row(nav))
    return make_page("NavMenu 侧边导航", "分组、折叠、选中条指示。", [s])


def create_page_header_page() -> QWidget:
    s = Section("页头")
    ph = PageHeader("订单详情", "编号 SO-20240601-008，创建于 2024-06-01")
    ph.set_breadcrumb(["订单中心", "订单列表", "订单详情"])
    ph.add_action(QPushButton("导出"))
    ph.add_action(_primary("编辑订单"))
    ph2 = PageHeader("系统设置", "全局参数与偏好", show_back=False)
    wrapper = col(ph, ph2, spacing=24)
    s.layout().addWidget(wrapper)
    return make_page("PageHeader 页头", "返回、标题、副标题、面包屑槽、操作区。", [s])


def create_pagination_page() -> QWidget:
    s = Section("分页")
    pg = Pagination(total=256, page_size=10, current=6)
    pg.set_show_jumper(True)
    pg.set_show_size_changer(True, options=(10, 20, 50))
    s.layout().addWidget(pg)
    s.layout().addWidget(Pagination(total=45, page_size=10))
    return make_page("Pagination 分页", "页码省略、跳转输入、每页条数。", [s])


class StepsEx(Steps):
    """步骤条游乐场扩展（demo 侧子类，不改动 InstructionX_UIKit）。

    InstructionX_UIKit ``Steps`` 的方向为构造参数，节点半径 / 连接线宽与样式为模块
    常量、无 setter；这里以子类属性 + 重写绘制方法暴露这些演示参数，
    并额外提供「点击节点切换当前步骤」开关（基类无鼠标交互）。
    """

    def __init__(self, orientation=Qt.Horizontal, parent=None):
        super().__init__(orientation, parent)
        self.node_radius = 12            # 节点半径 px
        self.link_width = 2.0            # 连接线宽 px
        self.link_style = Qt.SolidLine   # 连接线样式
        self.clickable = False           # 点击节点切换当前步骤

    # -- 参数化绘制（逻辑与基类一致，仅替换半径 / 线宽 / 线型） ------------
    def _paint_horizontal(self, p) -> None:
        n = len(self._steps)
        if n == 0:
            return
        r = self.node_radius
        title_font, desc_font = self._fonts()
        seg = self.width() / n
        cy = 26.0
        for i, st in enumerate(self._steps):
            status = self.status_of(i)
            x0 = i * seg
            cx = x0 + r + 4
            fm = QFontMetrics(title_font)
            title_w = fm.horizontalAdvance(st["title"])
            text_x = cx + r + 8
            if i < n - 1:
                x_start = text_x + title_w + 10
                x_end = (i + 1) * seg + 2
                if x_end > x_start:
                    color = T("color.primary") if status == "finish" \
                        else T("color.border")
                    pen = QPen(QColor(color))
                    pen.setWidthF(self.link_width)
                    pen.setStyle(self.link_style)
                    p.setPen(pen)
                    p.drawLine(QPointF(x_start, cy), QPointF(x_end, cy))
            self._draw_node(p, cx, cy, status, i)
            self._draw_texts(p, st, status, text_x, cy, title_font, desc_font,
                             align_top=False)

    def _paint_vertical(self, p) -> None:
        n = len(self._steps)
        if n == 0:
            return
        r = self.node_radius
        title_font, desc_font = self._fonts()
        row = max(56.0, self.height() / max(n, 1))
        cx = 20.0
        for i, st in enumerate(self._steps):
            status = self.status_of(i)
            cy = i * row + r + 6
            if i < n - 1:
                y_start = cy + r + 4
                y_end = (i + 1) * row + 6 - 4
                if y_end > y_start:
                    color = T("color.primary") if status == "finish" \
                        else T("color.border")
                    pen = QPen(QColor(color))
                    pen.setWidthF(self.link_width)
                    pen.setStyle(self.link_style)
                    p.setPen(pen)
                    p.drawLine(QPointF(cx, y_start), QPointF(cx, y_end))
            self._draw_node(p, cx, cy, status, i)
            self._draw_texts(p, st, status, cx + r + 10, cy,
                             title_font, desc_font, align_top=False)

    def _draw_node(self, p, cx, cy, status, index) -> None:
        r = self.node_radius
        fill, border, glyph, _title = self._colors(status)
        rect = QRectF(cx - r, cy - r, r * 2, r * 2)
        p.setBrush(fill)
        pen = QPen(border)
        pen.setWidthF(1.6)
        p.setPen(pen)
        p.drawEllipse(rect)
        scale = r / 12.0  # 基类字形按 r=12 设计，随半径缩放
        if status == "finish":
            pen = QPen(glyph)
            pen.setWidthF(1.8)
            pen.setCapStyle(Qt.RoundCap)
            pen.setJoinStyle(Qt.RoundJoin)
            p.setPen(pen)
            p.drawPolyline([
                QPointF(cx - 5.0 * scale, cy + 0.5 * scale),
                QPointF(cx - 1.5 * scale, cy + 4.0 * scale),
                QPointF(cx + 5.5 * scale, cy - 3.5 * scale),
            ])
        elif status == "error":
            pen = QPen(glyph)
            pen.setWidthF(1.8)
            pen.setCapStyle(Qt.RoundCap)
            p.setPen(pen)
            p.drawLine(QPointF(cx - 3.5 * scale, cy - 3.5 * scale),
                       QPointF(cx + 3.5 * scale, cy + 3.5 * scale))
            p.drawLine(QPointF(cx + 3.5 * scale, cy - 3.5 * scale),
                       QPointF(cx - 3.5 * scale, cy + 3.5 * scale))
        else:
            font = QFont(self.font())
            font.setPixelSize(T("font.sm"))
            font.setWeight(QFont.DemiBold)
            p.setFont(font)
            p.setPen(glyph)
            p.drawText(rect, Qt.AlignCenter, str(index + 1))

    # -- 点击切换当前步骤（基类无此交互，可选开启） ------------------------
    def mousePressEvent(self, event) -> None:  # noqa: N802
        if self.clickable and self._steps:
            n = len(self._steps)
            pos = event.position()
            if self._orientation == Qt.Horizontal:
                idx = int(pos.x() // (self.width() / n))
            else:
                idx = int(pos.y() // max(56.0, self.height() / max(n, 1)))
            self.set_current(idx)
        super().mousePressEvent(event)


_STEPS_POOL = [
    ("填写信息", "必填项校验"), ("确认订单", "核对金额"), ("支付", "担保交易"),
    ("发货", "48 小时内"), ("完成", ""),
]


def create_steps_page() -> QWidget:
    s = Section("步骤条（右侧参数实时生效）")
    state = {
        "orientation": "horizontal",
        "current": 1,
        "count": 4,
        "status": {1: None, 2: "error"},  # 显式状态；None = 按 current 推导
        "node_radius": 12,
        "link_width": 2.0,
        "link_style": Qt.SolidLine,
        "clickable": True,
    }
    host = QWidget()
    host.setMinimumHeight(230)
    st = None

    def build():
        """方向 / 步骤数变化时重建实例（orientation 为构造参数）。"""
        nonlocal st
        st = StepsEx(Qt.Horizontal if state["orientation"] == "horizontal"
                     else Qt.Vertical)
        st.node_radius = state["node_radius"]
        st.link_width = state["link_width"]
        st.link_style = state["link_style"]
        st.clickable = state["clickable"]
        st.set_steps(_STEPS_POOL[:state["count"]])
        st.set_current(state["current"])
        for idx, status in state["status"].items():
            if status and idx < state["count"]:
                st.set_status(idx, status)
        swap_widget(host, st, alignment=Qt.AlignmentFlag.AlignTop)
        cur_spin.setMaximum(state["count"] - 1)

    def apply_status(idx):
        def apply(v):
            state["status"][idx] = v
            if st is None or idx >= len(st._steps):
                return
            if v is None:  # 无公开「清除显式状态」API：属性赋值恢复自动推导
                st._steps[idx]["status"] = None
                st.update()
            else:
                st.set_status(idx, v)
        return apply

    panel = PlaygroundPanel("步骤条参数")
    panel.add_choice("方向", [("水平", "horizontal"), ("垂直", "vertical")],
                     "horizontal",
                     lambda v: (state.__setitem__("orientation", v), build()),
                     key="orientation")
    cur_spin = panel.add_int("当前步骤", 1, 0, 3,
                             lambda v: (state.__setitem__("current", v),
                                        st.set_current(v)), key="current")
    panel.add_int("步骤数", 4, 2, 5,
                  lambda v: (state.__setitem__("count", v), build()),
                  key="count")
    status_opts = [("自动", None), ("等待 wait", "wait"),
                   ("进行 process", "process"), ("完成 finish", "finish"),
                   ("出错 error", "error")]
    panel.add_choice("步骤2状态", status_opts, None, apply_status(1),
                     key="status1")
    panel.add_choice("步骤3状态", status_opts, "error", apply_status(2),
                     key="status2")
    panel.add_int("节点半径", 12, 8, 16,
                  lambda v: (state.__setitem__("node_radius", v),
                             setattr(st, "node_radius", v), st.update()),
                  key="node_radius")
    panel.add_choice("连接线样式", [("实线", Qt.SolidLine),
                                  ("虚线", Qt.DashLine),
                                  ("点线", Qt.DotLine)], Qt.SolidLine,
                     lambda v: (state.__setitem__("link_style", v),
                                setattr(st, "link_style", v), st.update()),
                     key="link_style")
    panel.add_int("连接线宽", 2, 1, 5,
                  lambda v: (state.__setitem__("link_width", float(v)),
                             setattr(st, "link_width", float(v)), st.update()),
                  key="link_width")
    panel.add_bool("点击切换步骤", True,
                   lambda v: (state.__setitem__("clickable", v),
                              setattr(st, "clickable", v)), key="clickable")

    build()
    s.layout().addWidget(with_playground(host, panel))
    return make_page(
        "Steps 步骤条",
        "水平 / 垂直，wait / process / finish / error 状态。右侧面板实时调节"
        "方向、当前步骤、步骤数、各步显式状态、节点半径、连接线样式 / 线宽，"
        "并可开启点击节点切换步骤。",
        [s])


def create_alert_page() -> QWidget:
    s = Section("警告提示")
    s.layout().addWidget(Alert("info", "系统升级通知", "本周六 02:00 - 04:00 进行例行维护。"))
    s.layout().addWidget(Alert("success", "保存成功", "全部配置已写入配置文件。"))
    warn = Alert("warning", "磁盘空间不足", "剩余空间低于 10%，请及时清理。", closable=True)
    warn.add_action("去清理")
    s.layout().addWidget(warn)
    err = Alert("error", "任务执行失败", "第 3 个子任务超时退出。", closable=True)
    err.add_action("查看日志")
    s.layout().addWidget(err)
    return make_page("Alert 警告提示", "info / success / warning / error，可关闭、带操作。", [s])


def create_dialog_page() -> QWidget:
    s = Section("统一对话框")
    btn1 = _primary("打开确认对话框")
    btn1.clicked.connect(lambda: Dialog.confirm(
        btn1.window(), "确认删除", "删除后不可恢复，确定继续吗？"))
    btn2 = QPushButton("打开信息对话框")
    btn2.clicked.connect(lambda: Dialog.info(
        btn2.window(), "操作完成", "数据同步已完成。"))
    s.layout().addWidget(row(btn1, btn2))
    s.layout().addWidget(hint_label("Dialog.confirm() / Dialog.info() 静态便捷方法。", role="tertiary"))
    return make_page("Dialog 对话框", "统一标题栏与按钮区，confirm() / info() 静态方法。", [s])


def create_drawer_page() -> QWidget:
    s = Section("抽屉")
    btns = []
    for pos in ("right", "left", "top", "bottom"):
        b = _primary(f"{pos} 抽屉")
        b.clicked.connect(lambda _=False, p=pos, bb=b: _open_drawer(bb, p))
        btns.append(b)
    s.layout().addWidget(row(*btns))
    s.layout().addWidget(hint_label("四边滑入，宽度可拖拽。", role="tertiary"))
    return make_page("Drawer 抽屉", "四边滑入，宽度可拖拽。", [s])


def _open_drawer(btn, position):
    dr = Drawer(btn.window(), position=position, size=300, title=f"{position} 抽屉")
    dr.set_content(QLabel(f"从 {position} 边滑入的抽屉内容。"))
    _KEEP.append(dr)
    dr.open()


def create_notification_page() -> QWidget:
    s = Section("通知提醒框")
    btns = []
    for kind, label in (("success", "成功通知"), ("error", "错误通知"),
                        ("info", "信息通知"), ("warning", "警告通知")):
        b = _primary(label) if kind in ("success", "error") else QPushButton(label)
        b.clicked.connect(lambda _=False, k=kind, bb=b: getattr(Notification, k)(
            bb.window(), f"{k} 标题", "这是通知提醒的正文内容。"))
        btns.append(b)
    s.layout().addWidget(row(*btns))
    s.layout().addWidget(hint_label("右上角堆叠弹出，自动消失，带进度条。", role="tertiary"))
    return make_page("Notification 通知提醒", "右上角堆叠弹出，自动消失，进度条。", [s])


def create_message_page() -> QWidget:
    s = Section("全局轻提示")
    btns = []
    for kind, label in (("success", "成功"), ("warning", "警告"),
                        ("info", "信息"), ("error", "错误")):
        b = _primary(label) if kind in ("success", "error") else QPushButton(label)
        b.clicked.connect(lambda _=False, k=kind, bb=b: getattr(Message, k)(
            bb.window(), f"这是一条 {k} 轻提示"))
        btns.append(b)
    s.layout().addWidget(row(*btns))
    s.layout().addWidget(hint_label("顶部居中轻提示 info / success / warning / error。", role="tertiary"))
    return make_page("Message 全局提示", "顶部居中轻提示，四种类型。", [s])


def create_popconfirm_page() -> QWidget:
    s = Section("气泡确认框")
    btn = _primary("删除文件")
    btn.clicked.connect(lambda: Popconfirm.confirm(
        btn, "确定删除该文件吗？此操作不可恢复。"))
    s.layout().addWidget(row(btn))
    s.layout().addWidget(hint_label("点击按钮弹出气泡确认框，确认 / 取消。", role="tertiary"))
    return make_page("Popconfirm 气泡确认", "Popover 式气泡确认框。", [s])


def create_result_page() -> QWidget:
    s = Section("结果页")
    rv1 = ResultView("success", "提交成功", "我们已收到你的申请，将在 2 个工作日内处理完毕。")
    rv1.add_action("返回首页", variant="primary")
    rv1.add_action("查看详情")
    rv2 = ResultView("404", "页面不存在", "请检查地址是否正确，或返回首页。")
    rv2.add_action("返回首页", variant="primary")
    rv3 = ResultView("error", "操作失败", "服务器繁忙，请稍后重试。")
    s.layout().addWidget(row(rv1, rv2, rv3, spacing=24))
    return make_page("ResultView 结果页", "success / error / info / 404 自绘图标 + 标题 + 操作。", [s])


def create_skeleton_page() -> QWidget:
    s = Section("骨架屏")
    sk = Skeleton(avatar=True, title=True, rows=3, button=True, active=True)
    sk.setMinimumWidth(420)
    s.layout().addWidget(sk)
    s.layout().addWidget(hint_label("标题 / 段落 / 头像 / 按钮形状，微光动画。", role="tertiary"))
    return make_page("Skeleton 骨架屏", "标题 / 段落 / 头像 / 按钮形状，微光动画。", [s])


def create_spinner_page() -> QWidget:
    s = Section("加载中")
    s.layout().addWidget(row(
        Spinner(size="sm", tip="加载中"), Spinner(size="md"),
        Spinner(size="lg", tip="请稍候…"), spacing=40))
    return make_page("Spinner 加载中", "旋转弧，size 与 tip 文案。", [s])


def create_progress_bar_page() -> QWidget:
    s = Section("进度")
    bars = col(
        ProgressBar(45), ProgressBar(70, status="success"),
        ProgressBar(30, status="warning"), ProgressBar(55, status="error"))
    bars.setMinimumWidth(420)
    s.layout().addWidget(bars)
    s.layout().addWidget(row(
        CircleProgress(75), CircleProgress(45, status="success"),
        CircleProgress(90, status="error"), spacing=32))
    return make_page("ProgressBar 进度条", "直线 / 环形进度，状态色。", [s])


def create_tour_page() -> QWidget:
    s = Section("漫游式引导")
    target1 = _primary("目标按钮 A")
    target2 = QPushButton("目标按钮 B")
    start = _primary("开始引导")

    def _start():
        tour = Tour(start.window())
        tour.add_step(target1, "第一步", "这是目标按钮 A 的引导说明。")
        tour.add_step(target2, "第二步", "这是目标按钮 B 的引导说明。")
        _KEEP.append(tour)
        tour.start()

    start.clicked.connect(_start)
    s.layout().addWidget(row(target1, target2, start))
    s.layout().addWidget(hint_label("高亮目标控件 + 步骤气泡，上一步 / 下一步 / 跳过。", role="tertiary"))
    return make_page("Tour 漫游引导", "高亮目标控件 + 步骤气泡。", [s])


#: 反馈组件页注册表：(导航键, 标题, 页面工厂)
FEEDBACK_PAGES = [
    ("tabs", "Tabs 标签页", create_tabs_page),
    ("anchor", "Anchor 锚点", create_anchor_page),
    ("breadcrumb", "Breadcrumb 面包屑", create_breadcrumb_page),
    ("dropdown", "DropdownButton 下拉菜单", create_dropdown_page),
    ("nav_menu", "NavMenu 侧边导航", create_nav_menu_page),
    ("page_header", "PageHeader 页头", create_page_header_page),
    ("pagination", "Pagination 分页", create_pagination_page),
    ("steps", "Steps 步骤条", create_steps_page),
    ("alert", "Alert 警告提示", create_alert_page),
    ("dialog", "Dialog 对话框", create_dialog_page),
    ("drawer", "Drawer 抽屉", create_drawer_page),
    ("notification", "Notification 通知提醒", create_notification_page),
    ("message", "Message 全局提示", create_message_page),
    ("popconfirm", "Popconfirm 气泡确认", create_popconfirm_page),
    ("result", "ResultView 结果页", create_result_page),
    ("skeleton", "Skeleton 骨架屏", create_skeleton_page),
    ("spinner", "Spinner 加载中", create_spinner_page),
    ("progress_bar", "ProgressBar 进度条", create_progress_bar_page),
    ("tour", "Tour 漫游引导", create_tour_page),
]
