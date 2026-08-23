# -*- coding: utf-8 -*-
"""导航与反馈组件自测（SPEC §5.3 / §9，agent C）。

直接运行（无 pytest 依赖）::

    QT_QPA_PLATFORM=offscreen python tests/test_components_feedback.py

覆盖 SPEC §5.3 全部 19 个组件文件：离屏实例化、交互路径触发、
亮 / 暗双主题 ``grab()`` 截图到 ``tests/shots/feedback_<name>_<theme>.png``。
对话框 / 抽屉 / 通知 / 轻提示 / 气泡确认 / 引导均采用非阻塞方式
（show + QTimer / QTest.qWait），不调用 exec_()。
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

from PySide6.QtCore import Qt, QTimer  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import (  # noqa: E402
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from InstructionX_UIKit.theme import ThemeManager  # noqa: E402

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
    """亮 / 暗双主题截图并保存，返回 {theme: 文件字节数}。"""
    sizes = {}
    for mode in ("light", "dark"):
        TM.set_mode(mode)
        APP.processEvents()
        pm = widget.grab()
        if pm.isNull() or pm.width() < 10 or pm.height() < 10:
            raise AssertionError(f"{name} {mode} grab() 失败")
        path = SHOTS / f"feedback_{name}_{mode}.png"
        if not pm.save(str(path)):
            raise AssertionError(f"截图保存失败: {path}")
        size = path.stat().st_size
        if size < min_bytes:
            raise AssertionError(f"截图过小（疑似空白）: {path} = {size}B")
        sizes[mode] = size
        _SHOT_LOG.append(path.name)
    TM.set_mode("light")
    APP.processEvents()
    return sizes


def close_later(widget, slot=None):
    """非阻塞关闭：QTimer 触发槽函数（默认 close），并处理事件。"""
    QTimer.singleShot(0, widget, slot or widget.close)
    APP.processEvents()


# ---------------------------------------------------------------------------
# 导航类组件
# ---------------------------------------------------------------------------

@check("tabs 三种样式")
def _():
    from InstructionX_UIKit.components.tabs import Tabs

    w = QWidget()
    lay = QVBoxLayout(w)
    lay.setContentsMargins(16, 16, 16, 16)
    lay.setSpacing(16)
    for variant in ("line", "card", "segmented"):
        t = Tabs(variant)
        for page in ("概览", "明细", "设置"):
            lab = QLabel(f"{variant} - {page} 内容区")
            lab.setAlignment(Qt.AlignCenter)
            t.addTab(lab, page)
        t.setCurrentIndex(1)
        t.setMinimumHeight(140)
        lay.addWidget(t)
    assert Tabs().variant() == "line"
    try:
        Tabs("weird")
    except ValueError:
        pass
    else:
        raise AssertionError("非法变体必须抛 ValueError")
    w.resize(560, 520)
    w.show()
    APP.processEvents()
    grab_both(w, "tabs")
    w.close()


@check("anchor 锚点联动滚动区")
def _():
    from InstructionX_UIKit.components.anchor import Anchor

    w = QWidget()
    lay = QHBoxLayout(w)
    lay.setContentsMargins(16, 16, 16, 16)
    lay.setSpacing(16)

    anchor = Anchor()
    anchor.setFixedWidth(140)
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
        sec.setFrameShape(QFrame.StyledPanel)
        # 段落需足够高：滚动条最大行程须容纳 notify 段落顶到视口顶部，
        # 否则 setValue 被钳制，联动高亮永远停在上一段
        sec.setMinimumHeight(200)
        vbox.addWidget(sec)
        sections.append(sec)
    area.setWidget(content)

    anchor.set_items([(k, t, s) for (k, t), s in zip(metas, sections)])
    anchor.bind_scroll_area(area)
    lay.addWidget(anchor)
    lay.addWidget(area, 1)
    w.resize(560, 320)
    w.show()
    APP.processEvents()

    seen = []
    anchor.currentChanged.connect(seen.append)
    anchor.scroll_to("notify")
    APP.processEvents()
    if anchor.current() != "notify":
        raise AssertionError(f"滚动后期望当前锚点 notify，实际 {anchor.current()}")
    anchor.scroll_to("base")
    APP.processEvents()
    grab_both(w, "anchor")
    w.close()


@check("breadcrumb 分隔符与点击")
def _():
    from InstructionX_UIKit.components.breadcrumb import Breadcrumb

    w = QWidget()
    lay = QVBoxLayout(w)
    lay.setContentsMargins(16, 16, 16, 16)
    lay.setSpacing(12)
    bc1 = Breadcrumb(["首页", "组件库", "导航", "面包屑"])
    bc2 = Breadcrumb(["仪表盘", "实时数据", "节点详情"], separator=">")
    lay.addWidget(bc1)
    lay.addWidget(bc2)
    lay.addStretch(1)
    hits = []
    bc1.itemClicked.connect(lambda i, t: hits.append((i, t)))
    bc1.layout().itemAt(0).widget().click()
    if hits != [(0, "首页")]:
        raise AssertionError(f"面包屑点击信号异常: {hits}")
    assert bc2.separator() == ">"
    w.resize(520, 140)
    w.show()
    APP.processEvents()
    grab_both(w, "breadcrumb")
    w.close()


@check("dropdown 菜单项（图标/快捷键/危险项）")
def _():
    from InstructionX_UIKit.components.dropdown import DropdownButton

    w = QWidget()
    lay = QVBoxLayout(w)
    lay.setContentsMargins(16, 16, 16, 16)
    dd = DropdownButton("更多操作")
    dd.add_item("edit", "编辑", shortcut="Ctrl+E")
    dd.add_item("share", "分享")
    dd.add_item("disabled", "禁用项", enabled=False)
    dd.add_separator()
    dd.add_item("del", "删除", danger=True)
    lay.addWidget(dd, 0, Qt.AlignLeft)
    lay.addStretch(1)
    fired = []
    dd.triggered.connect(fired.append)
    w.resize(360, 160)
    w.show()
    APP.processEvents()
    grab_both(w, "dropdown")

    # 弹出菜单并截图（非阻塞）
    dd.showMenu()
    APP.processEvents()
    grab_both(dd.menu(), "dropdown_menu")
    acts = dd.menu().actions()
    acts[0].trigger()  # 编辑
    if fired != ["edit"]:
        raise AssertionError(f"菜单触发信号异常: {fired}")
    dd.menu().close()
    APP.processEvents()
    w.close()


@check("nav_menu 分组/折叠/选中条")
def _():
    from InstructionX_UIKit.components.nav_menu import NavMenu

    nav = NavMenu()
    nav.setFixedSize(240, 380)
    nav.add_group("概览")
    nav.add_item("dash", "仪表盘", group="概览")
    nav.add_item("monitor", "实时监控", group="概览")
    nav.add_group("系统管理")
    nav.add_item("user", "用户管理", group="系统管理")
    nav.add_item("role", "角色权限", group="系统管理")
    nav.add_item("setting", "偏好设置")
    seen = []
    nav.currentChanged.connect(seen.append)
    nav.set_current("monitor")
    if nav.current() != "monitor" or seen != ["monitor"]:
        raise AssertionError(f"导航选中异常: {seen}")
    nav.set_collapsed("系统管理", True)
    assert nav.is_collapsed("系统管理") is True
    nav.set_collapsed("系统管理", False)
    assert nav.is_collapsed("系统管理") is False
    nav.show()
    APP.processEvents()
    grab_both(nav, "nav_menu")
    nav.close()


@check("page_header 页头")
def _():
    from InstructionX_UIKit.components.page_header import PageHeader

    w = QWidget()
    lay = QVBoxLayout(w)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(24)
    ph = PageHeader("订单详情", "编号 SO-20240601-008，创建于 2024-06-01")
    ph.set_breadcrumb(["订单中心", "订单列表", "订单详情"])
    ph.add_action(QPushButton("导出"))
    primary = QPushButton("编辑订单")
    from InstructionX_UIKit.theme import set_property
    set_property(primary, "variant", "primary")
    ph.add_action(primary)
    backed = []
    ph.backClicked.connect(lambda: backed.append(1))
    lay.addWidget(ph)
    ph2 = PageHeader("系统设置", "全局参数与偏好", show_back=False)
    lay.addWidget(ph2)
    lay.addStretch(1)
    # 触发返回信号
    ph._back.click()
    if backed != [1]:
        raise AssertionError("返回信号未发射")
    w.resize(680, 220)
    w.show()
    APP.processEvents()
    grab_both(w, "page_header")
    w.close()


@check("pagination 页码省略/跳转/每页条数")
def _():
    from InstructionX_UIKit.components.pagination import Pagination

    w = QWidget()
    lay = QVBoxLayout(w)
    lay.setContentsMargins(16, 16, 16, 16)
    lay.setSpacing(16)
    pg = Pagination(total=256, page_size=10, current=6)
    pg.set_show_jumper(True)
    pg.set_show_size_changer(True, options=(10, 20, 50))
    pg2 = Pagination(total=45, page_size=10)
    lay.addWidget(pg)
    lay.addWidget(pg2)
    lay.addStretch(1)
    seen = []
    pg.currentChanged.connect(seen.append)
    pg.set_current(12)
    if pg.current() != 12 or seen[-1] != 12:
        raise AssertionError("分页跳转异常")
    # 模拟跳转输入
    edit = pg.findChild(QLineEdit)
    edit.setText("3")
    edit.returnPressed.emit()
    if pg.current() != 3:
        raise AssertionError(f"跳至输入异常: {pg.current()}")
    # 每页条数变化
    sizes = []
    pg.pageSizeChanged.connect(sizes.append)
    pg.set_page_size(50)
    if pg.page_size() != 50 or sizes != [50]:
        raise AssertionError("每页条数变化异常")
    assert pg.page_count() == 6
    pg.set_page_size(10)
    pg.set_current(6)
    w.resize(680, 160)
    w.show()
    APP.processEvents()
    grab_both(w, "pagination")
    w.close()


@check("steps 步骤条（水平/垂直 + 四状态）")
def _():
    from InstructionX_UIKit.components.steps import Steps

    w = QWidget()
    lay = QVBoxLayout(w)
    lay.setContentsMargins(16, 16, 16, 16)
    lay.setSpacing(16)
    st = Steps()
    st.set_steps([("填写信息", "必填项校验"), ("确认订单", "核对金额"),
                  ("支付", ""), ("完成", "")])
    st.set_current(1)
    st.set_status(2, "error")
    if st.status_of(0) != "finish" or st.status_of(1) != "process" \
            or st.status_of(2) != "error" or st.status_of(3) != "wait":
        raise AssertionError("步骤状态推导异常")
    lay.addWidget(st)
    vst = Steps(Qt.Vertical)
    vst.set_steps([("创建任务", "2024-06-01"), ("执行中", "耗时约 2 分钟"),
                   ("完成", "")])
    vst.set_current(1)
    vst.setFixedHeight(200)
    lay.addWidget(vst)
    w.resize(720, 340)
    w.show()
    APP.processEvents()
    grab_both(w, "steps")
    w.close()


# ---------------------------------------------------------------------------
# 反馈类组件
# ---------------------------------------------------------------------------

@check("alert 四种类型/可关闭/带操作")
def _():
    from InstructionX_UIKit.components.alert import Alert

    w = QWidget()
    lay = QVBoxLayout(w)
    lay.setContentsMargins(16, 16, 16, 16)
    lay.setSpacing(10)
    a1 = Alert("info", "系统升级通知", "本周六 02:00 - 04:00 进行例行维护。")
    a2 = Alert("success", "保存成功", "全部配置已写入配置文件。")
    a3 = Alert("warning", "磁盘空间不足", "剩余空间低于 10%，请及时清理。",
               closable=True)
    a4 = Alert("error", "任务执行失败", "第 3 个子任务超时退出。", closable=True)
    acted = []
    a3.add_action("去清理", lambda: acted.append("clean"))
    a4.add_action("查看日志", lambda: acted.append("log"))
    closed = []
    a3.closed.connect(lambda: closed.append(1))
    for a in (a1, a2, a3, a4):
        lay.addWidget(a)
    lay.addStretch(1)
    a3._actions.itemAt(0).widget().click()
    if acted != ["clean"]:
        raise AssertionError(f"操作按钮回调异常: {acted}")
    w.resize(560, 340)
    w.show()
    APP.processEvents()
    grab_both(w, "alert")
    a3._close.click()
    if closed != [1] or a3.isVisible():
        raise AssertionError("关闭按钮行为异常")
    w.close()


@check("dialog 统一对话框（confirm/info 非阻塞）")
def _():
    from InstructionX_UIKit.components.dialog import Dialog

    host = QWidget()
    host.resize(480, 300)
    lay = QVBoxLayout(host)
    lay.addWidget(QLabel("宿主窗口"))
    host.show()
    APP.processEvents()

    results = []
    dlg = Dialog.confirm(host, "确认删除", "删除后不可恢复，确定继续吗？",
                         on_result=results.append)
    APP.processEvents()
    if not dlg.isVisible():
        raise AssertionError("confirm 对话框未显示")
    grab_both(dlg, "dialog")
    QTimer.singleShot(0, dlg, dlg.ok_button().click)
    APP.processEvents()
    if results != [True]:
        raise AssertionError(f"confirm 结果异常: {results}")

    info_hits = []
    d2 = Dialog.info(host, "操作完成", "数据同步已完成。",
                     on_close=lambda: info_hits.append(1))
    APP.processEvents()
    grab_both(d2, "dialog_info")
    QTimer.singleShot(0, d2, d2.ok_button().click)
    APP.processEvents()
    if info_hits != [1]:
        raise AssertionError("info 关闭回调异常")
    host.close()


@check("drawer 抽屉滑入/滑出")
def _():
    from InstructionX_UIKit.components.drawer import Drawer

    host = QWidget()
    lay = QVBoxLayout(host)
    lay.addWidget(QLabel("宿主窗口内容"))
    host.resize(640, 400)
    host.show()
    APP.processEvents()

    dr = Drawer(host, position="right", size=320, title="筛选条件")
    dr.set_content(QLabel("这里放置筛选表单"))
    dr.open()
    QTest.qWait(420)  # 等待滑入动画完成
    if not dr.isVisible() or not dr.panel().isVisible():
        raise AssertionError("抽屉未打开")
    grab_both(dr, "drawer")

    # 左侧抽屉也走一遍开合路径
    dr2 = Drawer(host, position="left", size=280, title="导航")
    dr2.set_content(QLabel("左侧抽屉"))
    dr2.open()
    QTest.qWait(420)
    grab_both(dr2, "drawer_left")
    dr2.close()
    QTest.qWait(420)
    if dr2.isVisible():
        raise AssertionError("抽屉滑出后应隐藏")

    dr.close()
    QTest.qWait(420)
    if dr.isVisible():
        raise AssertionError("抽屉关闭失败")
    host.close()


@check("notification 堆叠/进度/自动消失")
def _():
    from InstructionX_UIKit.components.notification import Notification

    host = QWidget()
    host.resize(640, 400)
    lay = QVBoxLayout(host)
    lay.addWidget(QLabel("宿主窗口"))
    host.show()
    APP.processEvents()

    n1 = Notification.success(host, "构建完成", "产物已输出到 dist/ 目录。")
    n2 = Notification.error(host, "部署失败",
                            "服务器连接超时，请检查网络后重试。")
    QTest.qWait(400)  # 等待入场动画
    if len(Notification._active) < 2:
        raise AssertionError("通知未进入堆叠列表")
    grab_both(n1, "notification")
    grab_both(n2, "notification_2")

    # 自动消失路径
    Notification.info(host, "同步", "数据同步中…", duration=120)
    QTest.qWait(700)
    if any(n._duration == 120 for n in Notification._active):
        raise AssertionError("短时通知应已自动关闭")

    n1.dismiss()
    n2.dismiss()
    QTest.qWait(300)
    APP.processEvents()
    host.close()


@check("message 顶部居中轻提示/自动消失")
def _():
    from InstructionX_UIKit.components.message import Message

    host = QWidget()
    host.resize(640, 400)
    lay = QVBoxLayout(host)
    lay.addWidget(QLabel("宿主窗口"))
    host.show()
    APP.processEvents()

    m1 = Message.success(host, "保存成功")
    m2 = Message.warning(host, "磁盘空间不足，请及时清理")
    QTest.qWait(300)
    grab_both(m1, "message")
    grab_both(m2, "message_2")

    Message.info(host, "这是一条会自动消失的提示", duration=80)
    QTest.qWait(600)
    if len(Message._active) > 2:
        raise AssertionError("短时提示应已自动关闭")

    m1.dismiss()
    m2.dismiss()
    QTest.qWait(500)
    APP.processEvents()
    host.close()


@check("popconfirm 气泡确认框")
def _():
    from InstructionX_UIKit.components.popconfirm import Popconfirm

    host = QWidget()
    lay = QVBoxLayout(host)
    btn = QPushButton("删除文件")
    lay.addWidget(btn, 0, Qt.AlignCenter)
    host.resize(420, 300)
    host.show()
    APP.processEvents()

    results = []
    pc = Popconfirm.confirm(btn, "确定删除该文件吗？此操作不可恢复。",
                            on_result=results.append)
    APP.processEvents()
    if not pc.isVisible():
        raise AssertionError("气泡确认框未弹出")
    grab_both(pc, "popconfirm")
    QTimer.singleShot(0, pc, pc.ok_button().click)
    APP.processEvents()
    if results != [True]:
        raise AssertionError(f"确认回调异常: {results}")

    pc2 = Popconfirm.confirm(btn, "再次确认", on_result=results.append)
    APP.processEvents()
    QTimer.singleShot(0, pc2, pc2.cancel_button().click)
    APP.processEvents()
    if results != [True, False]:
        raise AssertionError(f"取消回调异常: {results}")
    host.close()


@check("result 结果页")
def _():
    from InstructionX_UIKit.components.result import ResultView

    w = QWidget()
    lay = QHBoxLayout(w)
    lay.setContentsMargins(16, 16, 16, 16)
    lay.setSpacing(24)
    rv1 = ResultView("success", "提交成功",
                     "我们已收到你的申请，将在 2 个工作日内处理完毕。")
    hits = []
    rv1.add_action("返回首页", lambda: hits.append("home"), variant="primary")
    rv1.add_action("查看详情", lambda: hits.append("detail"))
    rv2 = ResultView("404", "页面不存在", "请检查地址是否正确，或返回首页。")
    rv2.add_action("返回首页", variant="primary")
    lay.addWidget(rv1)
    lay.addWidget(rv2)
    rv1._actions.itemAt(0).widget().click()
    if hits != ["home"]:
        raise AssertionError(f"结果页操作回调异常: {hits}")
    w.resize(780, 380)
    w.show()
    APP.processEvents()
    grab_both(w, "result")
    w.close()


@check("skeleton 骨架屏微光动画")
def _():
    from InstructionX_UIKit.components.skeleton import Skeleton

    w = QWidget()
    lay = QVBoxLayout(w)
    lay.setContentsMargins(16, 16, 16, 16)
    sk = Skeleton(avatar=True, title=True, rows=3, button=True, active=True)
    lay.addWidget(sk)
    lay.addStretch(1)
    if not sk.is_active():
        raise AssertionError("骨架屏动画应处于激活状态")
    w.resize(480, 300)
    w.show()
    APP.processEvents()
    QTest.qWait(150)  # 让微光扫到中程
    grab_both(w, "skeleton")
    sk.stop()
    if sk.is_active():
        raise AssertionError("骨架屏动画停止失败")
    w.close()


@check("spinner 旋转弧/尺寸/文案")
def _():
    from InstructionX_UIKit.components.spinner import Spinner

    w = QWidget()
    lay = QHBoxLayout(w)
    lay.setContentsMargins(24, 24, 24, 24)
    lay.setSpacing(40)
    sp1 = Spinner(size="sm", tip="加载中")
    sp2 = Spinner(size="md")
    sp3 = Spinner(size="lg", tip="请稍候…")
    for sp in (sp1, sp2, sp3):
        lay.addWidget(sp, 0, Qt.AlignCenter)
    if not sp1.is_spinning():
        raise AssertionError("Spinner 默认应自动旋转")
    w.resize(480, 180)
    w.show()
    APP.processEvents()
    QTest.qWait(80)
    grab_both(w, "spinner")
    sp2.stop()
    if sp2.is_spinning():
        raise AssertionError("Spinner 停止失败")
    w.close()


@check("progress_bar 直线/环形 + 状态色")
def _():
    from InstructionX_UIKit.components.progress_bar import CircleProgress, ProgressBar

    w = QWidget()
    lay = QVBoxLayout(w)
    lay.setContentsMargins(16, 16, 16, 16)
    lay.setSpacing(12)
    bars = [ProgressBar(45), ProgressBar(100, "success"),
            ProgressBar(70, "warning"), ProgressBar(30, "error"),
            ProgressBar(60, show_info=False)]
    for b in bars:
        lay.addWidget(b)
    row = QHBoxLayout()
    row.setSpacing(24)
    cp1 = CircleProgress(75)
    cp2 = CircleProgress(100, status="success")
    cp3 = CircleProgress(40, status="error")
    for cp in (cp1, cp2, cp3):
        row.addWidget(cp)
    row.addStretch(1)
    lay.addLayout(row)
    lay.addStretch(1)
    seen = []
    cp1.valueChanged.connect(seen.append)
    cp1.set_value(80)
    if seen != [80] or cp1.value() != 80:
        raise AssertionError(f"环形进度信号异常: {seen}")
    cp1.set_value(75)
    bars[0].set_status("normal")
    w.resize(560, 400)
    w.show()
    APP.processEvents()
    grab_both(w, "progress_bar")
    w.close()


@check("tour 镂空高亮 + 步骤气泡")
def _():
    from InstructionX_UIKit.components.tour import Tour

    host = QWidget()
    lay = QVBoxLayout(host)
    lay.setContentsMargins(40, 40, 40, 40)
    lay.setSpacing(16)
    btn_save = QPushButton("保存更改")
    btn_pub = QPushButton("发布上线")
    lay.addWidget(QLabel("引导目标演示窗口"))
    lay.addWidget(btn_save)
    lay.addWidget(btn_pub)
    lay.addStretch(1)
    host.resize(640, 400)
    host.show()
    APP.processEvents()

    tour = Tour(host)
    tour.add_step(btn_save, "保存更改", "点击此按钮将当前配置写入文件。")
    tour.add_step(btn_pub, "发布上线", "确认无误后点击发布，全量生效。")
    seen = []
    tour.currentChanged.connect(seen.append)
    tour.start()
    APP.processEvents()
    if not tour.is_running() or seen != [0]:
        raise AssertionError("引导启动异常")
    grab_both(host, "tour")

    tour.next()
    APP.processEvents()
    if tour.current() != 1:
        raise AssertionError("下一步异常")
    grab_both(host, "tour_step2")
    tour.prev()
    if tour.current() != 0:
        raise AssertionError("上一步异常")

    skipped = []
    tour.skipped.connect(lambda: skipped.append(1))
    tour.skip()
    if skipped != [1] or tour.isVisible():
        raise AssertionError("跳过引导异常")

    finished = []
    tour.finished.connect(lambda: finished.append(1))
    tour.start(1)  # 直接到最后一步
    APP.processEvents()
    tour.next()  # 完成
    if finished != [1]:
        raise AssertionError("完成信号异常")
    host.close()


def main() -> int:
    print("导航与反馈组件自测开始（offscreen）")
    SHOTS.mkdir(parents=True, exist_ok=True)
    print("-" * 60)
    # 恢复亮色，避免影响后续测试进程内状态
    TM.set_mode("light")
    APP.processEvents()
    expected = [
        "tabs", "anchor", "breadcrumb", "dropdown", "nav_menu",
        "page_header", "pagination", "steps", "alert", "dialog", "drawer",
        "notification", "message", "popconfirm", "result", "skeleton",
        "spinner", "progress_bar", "tour",
    ]
    missing = [f"feedback_{n}_{t}.png" for n in expected
               for t in ("light", "dark")
               if not (SHOTS / f"feedback_{n}_{t}.png").exists()]
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
