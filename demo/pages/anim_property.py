# -*- coding: utf-8 -*-
"""动画 · 属性演示页：28 个属性动画预设的参数化卡片网格。

每卡 = 演示元件 + 参数区（2-4 个有意义参数）+「播放」按钮：调整参数后
点击「播放」即按新参数重放；循环型动画（漂浮 / 辉光 / 呼吸 / 渐变流动等）
参数变化即时重启。参数全部对应 ``InstructionX_UIKit.anim.property`` 各预设的真实
``**opts``，不存在的参数不虚构。
"""

from PySide6.QtCore import QPoint, QRect, QTimer, Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QFrame, QGridLayout, QLabel, QStackedWidget, QWidget

from InstructionX_UIKit.anim import property as A
from InstructionX_UIKit.components.button import Button
from InstructionX_UIKit.components.switch import Switch
from InstructionX_UIKit.theme import T, ThemeManager

from .common import ColorBlock, Section, make_page
from .playground import ParamCard, add_specs

__all__ = ["create_page"]

_DIRECTIONS = ["left", "right", "up", "down"]


class _Stage(QWidget):
    """绝对定位演示舞台：避免布局刷新覆盖 pos / geometry 动画。"""

    def __init__(self, w=250, h=112, parent=None):
        super().__init__(parent)
        self.setFixedSize(w, h)
        self._w, self._h = w, h

    def place(self, child, cw, ch, x=None, y=None):
        """把控件以固定尺寸放入舞台（默认居中）。"""
        child.setParent(self)
        child.setFixedSize(cw, ch)
        if x is None:
            x = (self._w - cw) // 2
        if y is None:
            y = (self._h - ch) // 2
        child.move(x, y)
        child.show()
        return child


def _pcard(title, hint, stage, play, specs, demo_height=130,
           continuous=False, on_stop=None):
    """构建一张参数化属性动画卡片。

    play(opts) -> 可选句柄；重放 / 参数变化（continuous）前自动停止旧句柄。
    """
    card = ParamCard(title, stage, hint=hint, demo_height=demo_height,
                     continuous=continuous, on_stop=on_stop)
    opts = {}
    add_specs(card.form, opts, specs)
    card.opts = opts  # 暴露参数快照，便于审计 / 测试断言接线
    card.set_play(lambda: play(opts))
    return card


def _block(text="", key="primary", size=(120, 66)):
    return ColorBlock(text, color_key=key, size=size)


def _restore_handle(h):
    """「应用 ↔ 还原」类句柄的清理：优先 restore()。"""
    if h is not None and hasattr(h, "restore"):
        h.restore()


# ---------------------------------------------------------------------------
# 卡片构建
# ---------------------------------------------------------------------------

def _cards() -> list:
    cards = []

    # 1 淡入
    st = _Stage(); t = st.place(_block("淡入"), 120, 66)
    cards.append(_pcard(
        "fade_in 淡入", "透明度 0 → 1", st,
        lambda o, t=t: A.fade_in(t, **o),
        [("int", "duration", "时长", 200, 50, 2000),
         ("easing", "easing", "缓动", "standard"),
         ("float", "from_opacity", "起始透明度", 0.0, 0.0, 1.0)]))
    # 2 淡出（快照叠加层路径：结束保持隐藏；延时自动复原，避免卡片停留在隐藏态）
    st = _Stage(); t = st.place(_block("淡出"), 120, 66)

    def _fade_out(o, t=t):
        t.setVisible(True)  # 重放前先复原（上次结束保持隐藏）
        anim = A.fade_out(t, **o)

        def _auto_restore(t=t):
            try:  # 延时触发时目标可能已随演示卡重建销毁
                t.setVisible(True)
            except RuntimeError:
                pass
        # 仅当动画自然结束（隐藏）时延时复原；中途被 replay stop 已还原可见
        anim.finished.connect(
            lambda: QTimer.singleShot(700, _auto_restore))
        return anim
    cards.append(_pcard(
        "fade_out 淡出", "渐隐直至隐藏（稍后自动复原）", st, _fade_out,
        [("int", "duration", "时长", 200, 50, 2000),
         ("easing", "easing", "缓动", "standard")]))
    # 3 滑入
    st = _Stage(); t = st.place(_block("滑入"), 120, 66)
    cards.append(_pcard(
        "slide_in 滑入", "从指定方向偏移滑入", st,
        lambda o, t=t: A.slide_in(t, **o),
        [("choice", "direction", "方向", "left", list(_DIRECTIONS)),
         ("int", "distance", "距离", 70, 16, 200),
         ("bool", "fade", "同步淡入", True),
         ("int", "duration", "时长", 200, 50, 2000)]))
    # 4 缩放进入
    st = _Stage(); t = st.place(_block("缩放"), 120, 66)
    cards.append(_pcard(
        "zoom_in 缩放进入", "由小放大进入", st,
        lambda o, t=t: A.zoom_in(t, **o),
        [("float", "from_scale", "起始缩放", 0.6, 0.05, 1.0),
         ("bool", "fade", "同步淡入", True),
         ("int", "duration", "时长", 200, 50, 2000)]))
    # 5 弹性弹出
    st = _Stage(); t = st.place(_block("弹性"), 120, 66)
    cards.append(_pcard(
        "spring_pop 弹性弹出", "回弹式弹出", st,
        lambda o, t=t: A.spring_pop(t, **o),
        [("float", "from_scale", "起始缩放", 0.55, 0.05, 1.0),
         ("int", "duration", "时长", 320, 100, 1000)]))
    # 6 角标弹入
    st = _Stage(); t = st.place(_block("99+", key="danger", size=(48, 40)), 48, 40)
    cards.append(_pcard(
        "badge_pop 角标弹入", "角标弹性入场", st,
        lambda o, t=t: A.badge_pop(t, **o),
        [("int", "duration", "时长", 320, 100, 1000),
         ("easing", "easing", "缓动", "spring")]))
    # 7 交错入场（4 个绝对定位小块）
    st = _Stage()
    cont = QWidget(st); cont.setGeometry(15, 30, 220, 50); cont.show()
    kids = []
    for i in range(4):
        k = ColorBlock("", color_key="primary", size=(44, 44), parent=cont)
        k.setFixedSize(44, 44); k.move(8 + i * 54, 3); k.show(); kids.append(k)
    cards.append(_pcard(
        "stagger_in 交错入场", "子控件依次淡入上移", st,
        lambda o: A.stagger_in(cont, children=kids, **o),
        [("int", "interval", "间隔", 90, 0, 300),
         ("int", "distance", "起始偏移", 24, 0, 80),
         ("int", "duration", "时长", 200, 50, 2000)]))
    # 8 模糊进入
    st = _Stage(); t = st.place(_block("模糊"), 120, 66)
    cards.append(_pcard(
        "blur_in 模糊进入", "模糊半径 → 0", st,
        lambda o, t=t: A.blur_in(t, **o),
        [("int", "radius", "模糊半径", 16, 0, 40),
         ("int", "duration", "时长", 320, 100, 2000)]))
    # 9 遮罩揭示
    st = _Stage(); t = st.place(_block("揭示"), 120, 66)
    cards.append(_pcard(
        "mask_reveal 遮罩揭示", "逐帧裁剪揭示", st,
        lambda o, t=t: A.mask_reveal(t, **o),
        [("choice", "direction", "方向", "circle",
          ["right", "left", "down", "up", "circle"]),
         ("int", "duration", "时长", 320, 100, 2000)]))
    # 10 悬停上浮（事件过滤器；重放 = 按新参数重装过滤器）
    st = _Stage(); t = st.place(_block("悬停我", key="success"), 120, 66)
    cards.append(_pcard(
        "hover_lift 悬停上浮", "鼠标悬停上浮（安装后悬停查看）", st,
        lambda o, t=t: A.hover_lift(t, **o),
        [("int", "dy", "上移距离", 6, 0, 20),
         ("bool", "use_shadow", "阴影切换", True),
         ("int", "duration", "时长", 120, 50, 600)],
        on_stop=lambda h: h.uninstall() if h is not None else None))
    # 11 按钮变形加载（应用 ↔ 还原）
    st = _Stage(); btn = st.place(Button("提交", variant="primary"), 120, 36)
    morph_state = {"on": False}

    def _morph(o, btn=btn, state=morph_state):
        if state["on"]:
            state["on"] = False
            return None  # 还原由 on_stop 的 restore() 完成
        state["on"] = True
        return A.button_morph_loading(btn, **o)
    cards.append(_pcard(
        "button_morph_loading 按钮变形", "点击在加载 ↔ 还原间切换", st, _morph,
        [("int", "duration", "变形时长", 200, 50, 2000),
         ("int", "pulse_duration", "呼吸周期", 900, 200, 2000)],
        on_stop=_restore_handle))
    # 12 涟漪（重放 = 按新参数重装过滤器并触发一次）
    st = _Stage(); rbtn = st.place(Button("点我涟漪", variant="primary"), 120, 36)
    ripple_state = {"filt": None}

    def _ripple(o, rbtn=rbtn, state=ripple_state):
        old = state["filt"]
        if old is not None:
            rbtn.removeEventFilter(old)
            old.overlay.deleteLater()  # 清掉旧叠加层，避免残留
            old.deleteLater()
        # 必须清掉库函数的安装标记，否则 ripple() 会返回带旧参数的存量过滤器
        rbtn._uik_ripple = None
        state["filt"] = A.ripple(rbtn, **o)
        state["filt"].start(rbtn.rect().center())
        return None
    cards.append(_pcard(
        "ripple 涟漪", "Material 点击波纹", st, _ripple,
        [("float", "max_opacity", "起始不透明度", 0.35, 0.05, 0.8),
         ("int", "duration", "时长", 320, 100, 1000)]))
    # 13 开关切换
    st = _Stage(); sw = st.place(Switch(checked=False), 44, 22)
    cards.append(_pcard(
        "switch_toggle 开关切换", "按压回弹 + 换态", st,
        lambda o: A.switch_toggle(sw, **o),
        [("int", "duration", "时长", 120, 50, 600),
         ("easing", "easing", "缓动", "standard")]))
    # 14 脉冲
    st = _Stage(); t = st.place(_block("脉冲"), 120, 66)
    cards.append(_pcard(
        "pulse 脉冲", "缩放心跳强调", st,
        lambda o, t=t: A.pulse(t, **o),
        [("float", "peak", "峰值缩放", 1.06, 1.0, 1.5),
         ("int", "loops", "循环次数", 1, 1, 5),
         ("int", "duration", "时长", 320, 100, 2000)]))
    # 15 弹跳
    st = _Stage(); t = st.place(_block("弹跳", key="success"), 120, 66)
    cards.append(_pcard(
        "bounce 弹跳", "上移后落地回弹", st,
        lambda o, t=t: A.bounce(t, **o),
        [("int", "height", "弹跳高度", 12, 4, 40),
         ("int", "loops", "循环次数", 1, 1, 5),
         ("int", "duration", "时长", 480, 200, 2000)]))
    # 16 摇摆
    st = _Stage(); t = st.place(_block("摇摆", key="warning"), 120, 66)
    cards.append(_pcard(
        "swing 摇摆", "左右摇摆", st,
        lambda o, t=t: A.swing(t, **o),
        [("int", "angle", "摆角(度)", 8, 2, 30),
         ("int", "loops", "循环次数", 1, 1, 5),
         ("int", "duration", "时长", 480, 200, 2000)]))
    # 17 抖动
    st = _Stage(); t = st.place(_block("抖动", key="danger"), 120, 66)
    cards.append(_pcard(
        "shake 抖动", "水平抖动", st,
        lambda o, t=t: A.shake(t, **o),
        [("int", "distance", "振幅", 6, 2, 20),
         ("int", "loops", "循环次数", 1, 1, 5),
         ("int", "duration", "时长", 320, 100, 1000)]))
    # 18 高亮闪烁
    st = _Stage(); t = st.place(_block("闪烁"), 120, 66)

    def _flash(o, t=t):
        opts = dict(o)
        opts["color"] = QColor(T(f"color.{opts['color']}"))
        return A.flash_highlight(t, **opts)
    cards.append(_pcard(
        "flash_highlight 高亮闪烁", "主题色叠加淡出", st, _flash,
        [("int", "times", "闪烁次数", 2, 1, 6),
         ("float", "max_opacity", "不透明度", 0.45, 0.1, 0.9),
         ("choice", "color", "高亮色", "warning",
          ["primary", "success", "warning", "danger"]),
         ("int", "duration", "时长", 480, 200, 2000)]))
    # 19 漂浮循环（重放前还原初始位置，避免以中途位置为新基准逐次漂移）
    st = _Stage(); t = st.place(_block("漂浮", key="success"), 120, 66)
    float_home = t.pos()

    def _float_stop(h, t=t, home=float_home):
        if h is not None:
            h.stop()
        t.move(home)
    cards.append(_pcard(
        "float_loop 漂浮循环", "原位上下往复（循环）", st,
        lambda o, t=t: A.float_loop(t, **o),
        [("int", "dy", "幅度", 6, 2, 24),
         ("int", "duration", "周期", 1600, 400, 4000),
         ("int", "loops", "循环次数", -1, -1, 5, {"special": "无限"})],
        continuous=True, on_stop=_float_stop))
    # 20 辉光呼吸
    st = _Stage(); t = st.place(_block("辉光"), 120, 66)
    cards.append(_pcard(
        "pulse_glow 辉光呼吸", "投影半径呼吸（循环）", st,
        lambda o, t=t: A.pulse_glow(t, **o),
        [("int", "min_blur", "最小半径", 8, 0, 20),
         ("int", "max_blur", "最大半径", 28, 10, 60),
         ("int", "duration", "周期", 1600, 400, 4000)],
        continuous=True))
    # 21 呼吸
    st = _Stage(); t = st.place(_block("呼吸"), 120, 66)
    cards.append(_pcard(
        "breathing 呼吸", "透明度呼吸（循环）", st,
        lambda o, t=t: A.breathing(t, **o),
        [("float", "min_opacity", "最低透明度", 0.5, 0.05, 0.9),
         ("int", "duration", "周期", 1600, 400, 4000)],
        continuous=True))
    # 22 背景渐变流动（初始静态渐变，主题切换时刷新）
    st = _Stage(); gf = QFrame(st); st.place(gf, 150, 66)

    def _gflow_colors(palette):
        if palette == "theme":
            return [T("color.primary"), T("color.success")]
        if palette == "warm":
            return ["#C08A3E", "#D6473C"]
        return ["#7C5CFC", "#E05C8A"]

    def _gflow_static(gf=gf):
        """未播放时的静态渐变底（否则演示区是一块空白 QFrame）。"""
        ca, cb = _gflow_colors("theme")
        gf.setStyleSheet(
            f"background: qlineargradient(x1:0, y1:0, x2:1, y2:0, "
            f"stop:0 {ca}, stop:1 {cb}); border-radius: {T('radius.md')}px;")

    gf.setAttribute(Qt.WA_StyledBackground, True)
    _gflow_static()
    ThemeManager.instance().theme_changed.connect(lambda *_: _gflow_static())

    def _gflow(o, gf=gf):
        opts = dict(o)
        palette = opts.pop("palette")
        opts["colors"] = _gflow_colors(palette)
        return A.gradient_flow(gf, **opts)
    cards.append(_pcard(
        "gradient_flow 背景渐变", "渐变色带流动（循环）", st, _gflow,
        [("choice", "palette", "色带", "theme",
          [("主题 蓝→绿", "theme"), ("暖 橙→红", "warm"), ("紫→粉", "violet")]),
         ("choice", "direction", "方向", "horizontal",
          ["horizontal", "vertical"]),
         ("int", "duration", "周期", 2400, 500, 6000)],
        continuous=True))
    # 23 文字渐变流动
    st = _Stage(); lab = QLabel("渐变流动文字", st); st.place(lab, 170, 40)
    cards.append(_pcard(
        "gradient_text_flow 文字渐变", "逐字色相流动（循环）", st,
        lambda o: A.gradient_text_flow(lab, **o),
        [("text", "text", "文本", "渐变流动文字"),
         ("int", "duration", "周期", 2000, 500, 6000)],
        continuous=True))
    # 24 交叉淡化（两页 stacked）
    st = _Stage(); stack = QStackedWidget(st); st.place(stack, 150, 70)
    stack.addWidget(_block("页面 A", key="primary", size=(150, 70)))
    stack.addWidget(_block("页面 B", key="success", size=(150, 70)))
    cf = {"i": 0}

    def _cross(o, stack=stack, cf=cf):
        cf["i"] = 1 - cf["i"]
        return A.cross_fade(stack, index=cf["i"], **o)
    cards.append(_pcard(
        "cross_fade 交叉淡化", "两页 A/B 交叉淡化", st, _cross,
        [("int", "duration", "时长", 200, 50, 2000),
         ("easing", "easing", "缓动", "standard")]))
    # 25 页面切换（stacked，fade/slide）
    st = _Stage(); stack2 = QStackedWidget(st); st.place(stack2, 150, 70)
    stack2.addWidget(_block("第一页", key="primary", size=(150, 70)))
    stack2.addWidget(_block("第二页", key="warning", size=(150, 70)))
    pt = {"i": 0}

    def _page_trans(o, stack=stack2, pt=pt):
        pt["i"] = 1 - pt["i"]
        return A.page_transition(stack, pt["i"], **o)
    cards.append(_pcard(
        "page_transition 页面切换", "QStackedWidget 切页", st, _page_trans,
        [("choice", "kind", "模式", "slide", ["fade", "slide"]),
         ("choice", "direction", "方向", "left", list(_DIRECTIONS)),
         ("int", "duration", "时长", 320, 100, 2000)]))
    # 26 滑动过渡（stacked 分支）
    st = _Stage(); stack3 = QStackedWidget(st); st.place(stack3, 150, 70)
    stack3.addWidget(_block("甲", key="success", size=(150, 70)))
    stack3.addWidget(_block("乙", key="danger", size=(150, 70)))
    strans = {"i": 0}

    def _slide_trans(o, stack=stack3, strans=strans):
        strans["i"] = 1 - strans["i"]
        return A.slide_transition(stack, index=strans["i"], **o)
    cards.append(_pcard(
        "slide_transition 滑动过渡", "源滑出 / 目标滑入", st, _slide_trans,
        [("choice", "direction", "方向", "left", list(_DIRECTIONS)),
         ("int", "duration", "时长", 320, 100, 2000),
         ("bool", "hide_source", "结束后隐藏源", True)]))
    # 27 容器变形（应用 ↔ 还原；底色取主题令牌，空闲时随主题刷新）
    st = _Stage(); morph_box = QFrame(st)
    mbox_state = {"on": False}

    def _mbox_style(box=morph_box, radius=0):
        box.setStyleSheet(
            f"background:{T('color.primary')};border-radius:{radius}px;")

    _mbox_style()
    st.place(morph_box, 120, 66)

    def _mbox_theme(*_):
        if not mbox_state["on"]:  # 变形进行中由动画逐帧重写样式，不干预
            _mbox_style()

    ThemeManager.instance().theme_changed.connect(_mbox_theme)

    def _morph_box(o, box=morph_box, state=mbox_state):
        if state["on"]:
            state["on"] = False
            return None  # 还原由 on_stop 的 restore() 完成
        state["on"] = True
        opts = dict(o)
        radius = opts.pop("radius")
        return A.container_morph(box, size=(170, 90), radius=radius,
                                 from_radius=0, **opts)
    cards.append(_pcard(
        "container_morph 容器变形", "大小 / 圆角变形 ↔ 还原", st, _morph_box,
        [("int", "radius", "目标圆角", 28, 0, 40),
         ("int", "duration", "时长", 320, 100, 2000)],
        on_stop=_restore_handle))
    # 28 共享元素（绝对定位，两位置往返）
    st = _Stage(250, 112)
    mover = ColorBlock("", color_key="primary", size=(56, 44))
    st.place(mover, 56, 44, x=14, y=(112 - 44) // 2)
    se = {"left": True}

    def _shared(o, mover=mover, se=se):
        se["left"] = not se["left"]
        target = QRect(14, (112 - 44) // 2, 56, 44) if se["left"] \
            else QRect(250 - 14 - 56, (112 - 44) // 2, 56, 44)
        return A.shared_element(mover, to=target, **o)
    cards.append(_pcard(
        "shared_element 共享元素", "控件几何 A→B 往返", st, _shared,
        [("int", "duration", "时长", 320, 100, 2000),
         ("easing", "easing", "缓动", "emphasis"),
         ("bool", "fade", "同步淡入", False)]))

    return cards


def create_page() -> QWidget:
    box = Section("属性动画（28 个预设 · 调参数后点「播放」重放）")
    grid_host = QWidget()
    grid = QGridLayout(grid_host)
    grid.setContentsMargins(0, 0, 0, 0)
    grid.setSpacing(12)
    for i, card in enumerate(_cards()):
        grid.addWidget(card, i // 3, i % 3)
    box.layout().addWidget(grid_host)
    return make_page(
        "动画 · 属性",
        "基于 QPropertyAnimation / QVariantAnimation / 动画组的 28 个属性动画预设。"
        "每张卡片带 2-4 个参数（时长 / 缓动 / 方向 / 幅度 / 循环次数等），调整"
        "后点击「播放」按新参数重放；循环类动画参数变化即时重启。",
        [box])
