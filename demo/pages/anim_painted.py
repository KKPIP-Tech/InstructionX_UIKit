# -*- coding: utf-8 -*-
"""动画 · 自绘演示页：24 个自绘 / 定时器动画预设的参数化卡片网格。

每卡 = 演示元件 + 参数区 + 「播放」按钮。由于自绘组件的可调参数基本都是
构造参数（InstructionX_UIKit 未提供运行时 setter），本页统一采用「参数变化即按新参数
重建演示控件」的方式应用；连续型组件重建后立即重启，触发型组件点击
「播放」重放，滚动型组件点击「播放」驱动滚动条演示。
"""

import weakref

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QGridLayout,
    QLabel,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from InstructionX_UIKit.anim import painted as P
from InstructionX_UIKit.theme import T, ThemeManager

from .common import Section, make_page
from .playground import ParamCard, add_specs

__all__ = ["create_page"]


def _lab(text, style=""):
    lab = QLabel(text)
    lab.setAlignment(Qt.AlignCenter)
    if style:
        lab.setStyleSheet(style)
    return lab


def _fill(text, bg_key="primary", fg_key="on.primary", extra=""):
    """主题感知填充标签：颜色取令牌（配合整页主题重建，切主题即刷新）。"""
    return _lab(text, f"background:{T('color.' + bg_key)};"
                      f"color:{T('color.' + fg_key)};border-radius:6px;{extra}")


def _rcard(title, hint, build, specs, play=None, demo_height=130, auto=False):
    """构建一张参数化自绘动画卡片（重建式应用参数）。

    参数:
        build: ``build(opts) -> QWidget``，按当前参数构造演示控件。
        specs: 参数规格（见 ``playground.add_specs``）。
        play: 可选 ``play(widget, opts) -> 句柄``；缺省时调用 ``widget.start()``。
        auto: True 时每次重建后立即播放（连续型 / 自动演示组件）。
    """
    card = ParamCard(title, hint=hint, demo_height=demo_height)
    opts = {}
    add_specs(card.form, opts, specs)
    card.opts = opts  # 暴露参数快照，便于审计 / 测试断言接线

    def _do_play():
        w = card.demo
        if w is None:
            return None
        if play is not None:
            return play(w, opts)
        if hasattr(w, "start"):
            w.start()
        return None

    def rebuild(*_):
        card.set_demo(build(opts))
        if auto:
            _do_play()

    card.set_play(_do_play)
    card.form.changed.connect(rebuild)
    card._rebuild = rebuild  # 供主题切换时整页重建（刷新令牌色）
    rebuild()
    return card


# ---------------------------------------------------------------------------
# 各卡片构建
# ---------------------------------------------------------------------------

def _cards() -> list:
    cards = []

    # 1 旋转圈
    cards.append(_rcard(
        "SpinnerArc 旋转圈", "自动旋转的加载圈",
        lambda o: P.SpinnerArc(size=o["size"], line_width=o["line_width"],
                               speed=o["speed"]),
        [("int", "size", "尺寸", 40, 16, 64),
         ("int", "line_width", "线宽", 3, 1, 8),
         ("float", "speed", "速度(度/帧)", 10.0, 1.0, 30.0, {"step": 1.0})],
        auto=True))
    # 2 跳动的点
    cards.append(_rcard(
        "BouncingDots 跳动的点", "加载中的跳动圆点",
        lambda o: P.BouncingDots(count=o["count"], diameter=o["diameter"],
                                 amplitude=o["amplitude"], period=o["period"]),
        [("int", "count", "圆点数", 3, 1, 6),
         ("int", "diameter", "直径", 9, 4, 16),
         ("int", "amplitude", "振幅", 6, 2, 14),
         ("int", "period", "周期", 600, 200, 2000)],
        auto=True))
    # 3 对勾描绘
    def _check_play(w, o):
        w.reset()
        w.start()
    cards.append(_rcard(
        "CheckDraw 对勾描绘", "对勾路径描绘",
        lambda o: P.CheckDraw(size=o["size"], duration=o["duration"]),
        [("int", "size", "尺寸", 56, 24, 96),
         ("int", "duration", "时长", 320, 100, 2000)],
        play=_check_play, auto=True))
    # 4 点赞爆裂
    cards.append(_rcard(
        "LikeBurstButton 点赞爆裂", "心形 + 粒子爆裂",
        lambda o: P.LikeBurstButton(size=o["size"],
                                    particle_count=o["particle_count"]),
        [("int", "size", "尺寸", 52, 32, 80),
         ("int", "particle_count", "粒子数", 10, 4, 30)],
        play=lambda w, o: w.click()))
    # 5 磁吸按钮
    cards.append(_rcard(
        "MagneticButton 磁吸按钮", "按钮随鼠标位移（移动鼠标查看）",
        lambda o: P.MagneticButton(o["text"], max_offset=o["max_offset"],
                                   magnet_range=o["magnet_range"]),
        [("text", "text", "文本", "磁吸按钮"),
         ("float", "max_offset", "最大位移", 8.0, 2.0, 24.0, {"step": 1.0}),
         ("float", "magnet_range", "磁吸范围", 96.0, 40.0, 240.0,
          {"step": 4.0, "decimals": 0})],
        play=lambda w, o: w.click()))
    # 6 骨架屏微光
    def _skeleton(o):
        w = P.SkeletonShimmer(period=o["period"], interval=o["interval"])
        w.setMinimumSize(240, 96)
        return w
    cards.append(_rcard(
        "SkeletonShimmer 骨架微光", "骨架屏微光扫过",
        _skeleton,
        [("int", "period", "周期", 1400, 400, 3000),
         ("int", "interval", "帧间隔", 33, 10, 100)],
        auto=True))
    # 7 区域微光
    def _shimmer(o):
        w = P.Shimmer(period=o["period"], band=o["band"])
        w.setMinimumSize(230, 80)
        return w
    cards.append(_rcard(
        "Shimmer 区域微光", "任意区域微光扫过",
        _shimmer,
        [("int", "period", "周期", 1440, 400, 3000),
         ("float", "band", "光带宽度", 0.4, 0.1, 0.9)],
        auto=True))
    # 8 条纹流动进度条
    def _striped(o):
        w = P.ProgressStriped(value=30, height=o["height"],
                              stripe=o["stripe"])
        w.setMinimumWidth(250)
        return w
    cards.append(_rcard(
        "ProgressStriped 条纹进度", "条纹流动 + 进度动画",
        _striped,
        [("int", "height", "高度", 14, 6, 24),
         ("int", "stripe", "条纹宽", 12, 4, 24),
         ("int", "target", "目标值", 82, 0, 100)],
        play=lambda w, o: w.animateTo(o["target"]), auto=True))
    # 9 视差滚动容器
    def _parallax(o):
        area = P.ParallaxArea()
        n = o["layers"]
        for i in range(n):
            f = 0.2 + (0.7 * i / max(n - 1, 1))
            area.addLayer(_fill(f"视差图层 {i + 1}（factor={f:.2f}）"),
                          factor=f, height=o["layer_height"])
        area.setMinimumSize(250, 180)
        return area

    def _parallax_play(w, o):
        sb = w.verticalScrollBar()
        sb.setValue(0 if sb.value() > sb.maximum() // 2 else sb.maximum())
    cards.append(_rcard(
        "ParallaxArea 视差滚动", "播放滚动查看视差",
        _parallax,
        [("int", "layers", "图层数", 3, 2, 5),
         ("int", "layer_height", "层高", 64, 40, 120)],
        play=_parallax_play, demo_height=190))
    # 10 滚动渐显
    def _reveal(o):
        box = QWidget()
        lay = QVBoxLayout(box)
        lay.setContentsMargins(4, 4, 4, 4)
        for i in range(o["blocks"]):
            blk = _fill(f"内容块 {i + 1}", "bg.muted", "text.primary")
            blk.setFixedHeight(56)
            lay.addWidget(blk)
        reveal = P.ScrollReveal(box, threshold=o["threshold"])
        reveal.setMinimumSize(250, 180)
        return reveal

    def _reveal_play(w, o):
        sb = w.verticalScrollBar()
        sb.setValue(sb.maximum() if sb.value() < sb.maximum() // 2 else 0)
    cards.append(_rcard(
        "ScrollReveal 滚动渐显", "播放滚动渐显内容块",
        _reveal,
        [("int", "blocks", "内容块数", 12, 4, 20),
         ("float", "threshold", "渐显阈值", 0.85, 0.3, 1.0)],
        play=_reveal_play, demo_height=190))
    # 11 横向滚动条带
    def _strip(o):
        w = P.HorizontalScrollStrip(
            ["设计", "令牌", "组件", "动画", "布局", "主题", "画廊", "图表"],
            step=o["step"], interval=o["interval"], autoplay=o["autoplay"])
        w.setMinimumSize(250, 64)
        return w
    cards.append(_rcard(
        "HorizontalScrollStrip 横滚条带", "自动横向滚动",
        _strip,
        [("float", "step", "步进速度", 2.0, 0.5, 6.0),
         ("int", "interval", "帧间隔", 30, 10, 100),
         ("bool", "autoplay", "自动播放", True)],
        auto=True))
    # 12 粘性固定头
    def _sticky(o):
        sticky = P.StickyHeader()
        header = _fill("  粘性章节头", extra="font-weight:bold;")
        sticky.setHeaderWidget(header)
        body = QWidget()
        blay = QVBoxLayout(body)
        for i in range(o["rows"]):
            blay.addWidget(QLabel(f"正文行 {i + 1}"))
        sticky.setBody(body, cover_height=o["cover_height"])
        sticky.setMinimumSize(250, 180)
        return sticky

    def _sticky_play(w, o):
        sb = w.verticalScrollBar()
        sb.setValue(160 if sb.value() < 80 else 0)
    cards.append(_rcard(
        "StickyHeader 粘性固定头", "播放滚动吸附 / 释放",
        _sticky,
        [("int", "rows", "正文行数", 24, 8, 40),
         ("int", "cover_height", "遮盖高度", 90, 0, 200)],
        play=_sticky_play, demo_height=190))
    # 13 滚动进度条
    def _progress(o):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        clay = QVBoxLayout(content)
        for i in range(o["rows"]):
            clay.addWidget(QLabel(f"行 {i + 1}"))
        scroll.setWidget(content)
        bar = P.ScrollProgressBar(scroll, height=o["height"])
        holder = QWidget()
        hlay = QVBoxLayout(holder)
        hlay.setContentsMargins(0, 0, 0, 0)
        hlay.setSpacing(0)
        hlay.addWidget(bar)
        hlay.addWidget(scroll, 1)
        holder.setMinimumSize(250, 180)
        holder._uik_scroll = scroll  # 供 play 取滚动条
        return holder

    def _progress_play(w, o):
        sb = w._uik_scroll.verticalScrollBar()
        sb.setValue(0 if sb.value() > sb.maximum() // 2 else sb.maximum())
    cards.append(_rcard(
        "ScrollProgressBar 滚动进度", "播放滚动驱动顶部进度条",
        _progress,
        [("int", "height", "进度条高", 8, 4, 16),
         ("int", "rows", "内容行数", 30, 10, 60)],
        play=_progress_play, demo_height=190))
    # 14 滚动叙事
    def _story(o):
        story = P.ScrollStoryArea()
        for i in range(o["steps"]):
            story.addStep(f"第 {i + 1} 步", "这是步骤的详细说明文本，" * 4)
        story.setMinimumSize(250, 180)
        return story

    def _story_play(w, o):
        sb = w.verticalScrollBar()
        sb.setValue(sb.value() + o["delta"]
                    if sb.value() < sb.maximum() - 10 else 0)
    cards.append(_rcard(
        "ScrollStoryArea 滚动叙事", "播放滚动推进叙事时间线",
        _story,
        [("int", "steps", "步数", 5, 2, 8),
         ("int", "delta", "播放步长", 120, 60, 300)],
        play=_story_play, demo_height=190))
    # 15 跑马灯
    def _marquee(o):
        w = P.MarqueeLabel(o["text"], speed=o["speed"], gap=o["gap"],
                           pause=o["pause"])
        w.setMinimumWidth(250)
        return w
    cards.append(_rcard(
        "MarqueeLabel 跑马灯", "长文本循环滚动",
        _marquee,
        [("text", "text", "文本", "跑马灯：这是一条很长很长需要循环滚动展示的中文公告文本"),
         ("float", "speed", "速度", 1.6, 0.4, 6.0),
         ("int", "gap", "间隔", 56, 16, 120),
         ("int", "pause", "停顿", 900, 0, 3000)],
        auto=True))
    # 16 流体渐变背景
    def _fluid(o):
        w = P.FluidBackground(blobs=o["blobs"], fps=o["fps"],
                              speed=o["speed"])
        w.setMinimumSize(250, 150)
        return w
    cards.append(_rcard(
        "FluidBackground 流体背景", "正弦叠加的流体渐变",
        _fluid,
        [("int", "blobs", "色团数", 3, 1, 8),
         ("float", "speed", "速度", 1.0, 0.2, 3.0),
         ("int", "fps", "帧率", 30, 10, 60)],
        auto=True, demo_height=170))
    # 17 打字机
    def _typewriter(o):
        w = P.TypewriterLabel(interval=o["interval"], cursor=o["cursor"])
        w.setMinimumWidth(250)
        return w
    cards.append(_rcard(
        "TypewriterLabel 打字机", "逐字输出 + 光标",
        _typewriter,
        [("text", "text", "文本", "打字机效果：中文逐字输出。"),
         ("int", "interval", "字间隔", 50, 10, 300),
         ("bool", "cursor", "显示光标", True)],
        play=lambda w, o: w.start(o["text"]), auto=True))
    # 18 文字解码
    def _decode(o):
        w = P.TextDecodeLabel(o["text"], step=o["step"], span=o["span"])
        w.setMinimumWidth(250)
        return w
    cards.append(_rcard(
        "TextDecodeLabel 文字解码", "乱码逐步解码为文本",
        _decode,
        [("text", "text", "文本", "解码完成的目标文本"),
         ("int", "step", "步进", 40, 10, 120),
         ("int", "span", "乱码跨度", 4, 1, 10)],
        play=lambda w, o: w.start(), auto=True))
    # 19 数字滚动（播放 = 先归零再滚到目标：rollTo 从当前值起滚，
    # 当前值已等于目标值时画面无变化，用户会以为「播放无反应」）
    def _number(o):
        w = P.NumberRollLabel(0, decimals=o["decimals"],
                              prefix=o["prefix"], duration=o["duration"])
        w.setStyleSheet("font-size:22px;font-weight:bold;")
        return w

    def _number_play(w, o):
        w.reset(0)
        return w.rollTo(o["target"])
    cards.append(_rcard(
        "NumberRollLabel 数字滚动", "count-up 数字滚动（播放先归零再滚到目标）",
        _number,
        [("int", "decimals", "小数位", 2, 0, 4),
         ("text", "prefix", "前缀", "¥"),
         ("float", "target", "目标值", 1024.5, 0.0, 99999.0, {"step": 100.0}),
         ("int", "duration", "时长", 480, 200, 3000)],
        play=_number_play, auto=True))
    # 20 逐字进场
    def _letters(o):
        w = P.LetterStaggerLabel(o["text"], stagger=o["stagger"],
                                 rise=o["rise"])
        w.setMinimumSize(240, 48)
        return w
    cards.append(_rcard(
        "LetterStaggerLabel 逐字进场", "逐字上浮进场",
        _letters,
        [("text", "text", "文本", "逐字进场效果"),
         ("int", "stagger", "字间隔", 50, 10, 200),
         ("int", "rise", "上浮高度", 12, 4, 30)],
        play=lambda w, o: w.start(), auto=True))
    # 21 卡片倾斜
    def _tilt(o):
        content = _lab("封面内容",
                       f"background:{T('color.bg.elevated')};"
                       f"color:{T('color.text.primary')};"
                       f"border:1px solid {T('color.primary')};"
                       "border-radius:8px;")
        tilt = P.CardTilt(content, max_angle=o["max_angle"],
                          persp=o["persp"])
        tilt.setMinimumSize(240, 150)
        return tilt
    cards.append(_rcard(
        "CardTilt 卡片倾斜", "鼠标移动查看 3D 倾斜",
        _tilt,
        [("float", "max_angle", "最大倾角", 10.0, 2.0, 25.0, {"step": 1.0}),
         ("float", "persp", "透视距离", 700.0, 200.0, 1500.0,
          {"step": 20.0, "decimals": 0})],
        play=lambda w, o: None, demo_height=170))
    # 22 立方体旋转
    def _cube(o):
        w = P.CubeRotator("正面 A", "侧面 B", persp=o["persp"])
        w.setMinimumSize(230, 150)
        if o["auto"]:
            w.startAuto()
        return w
    cards.append(_rcard(
        "CubeRotator 立方体旋转", "两面 3D 立方体翻转",
        _cube,
        [("float", "persp", "透视距离", 520.0, 200.0, 1200.0,
          {"step": 20.0, "decimals": 0}),
         ("bool", "auto", "自动旋转", False)],
        play=lambda w, o: w.rotate(), demo_height=170))
    # 23 翻转卡片
    def _flip(o):
        w = P.FlipCard(o["front"], o["back"], persp=o["persp"])
        w.setMinimumSize(220, 140)
        return w
    cards.append(_rcard(
        "FlipCard 翻转卡片", "点击卡片或「播放」正反面翻转",
        _flip,
        [("text", "front", "正面文本", "问题面"),
         ("text", "back", "背面文本", "答案面"),
         ("float", "persp", "透视距离", 640.0, 200.0, 1200.0,
          {"step": 20.0, "decimals": 0})],
        play=lambda w, o: w.flip(), demo_height=160))
    # 24 立体轮播
    _COVER_ITEMS = ["设计", "组件", "动画", "布局", "主题", "令牌", "图表"]

    def _cover(o):
        w = P.CoverFlow(_COVER_ITEMS[:o["items"]], persp=o["persp"])
        # 类默认最小 520x280 远超演示卡宽度，会撑破卡片网格；卡面尺寸随
        # 控件宽高自适应，故此处收敛到卡片可容纳的最小尺寸
        w.setMinimumSize(240, 190)
        return w
    cards.append(_rcard(
        "CoverFlow 立体轮播", "3-7 项透视堆叠轮播",
        _cover,
        [("int", "items", "项数", 5, 3, 7),
         ("float", "persp", "透视距离", 460.0, 200.0, 1200.0,
          {"step": 20.0, "decimals": 0})],
        play=lambda w, o: w.next(), demo_height=230))

    return cards


def create_page() -> QWidget:
    box = Section("自绘 / 定时器动画（24 个预设 · 调参数即重建，点「播放」重放）")
    grid_host = QWidget()
    grid = QGridLayout(grid_host)
    grid.setContentsMargins(0, 0, 0, 0)
    grid.setSpacing(12)
    for i, card in enumerate(_cards()):
        grid.addWidget(card, i // 3, i % 3)
    box.layout().addWidget(grid_host)
    page = make_page(
        "动画 · 自绘",
        "基于 QTimer + paintEvent 的 24 个自绘动画预设。每张卡片带 2-4 个构造"
        "参数（尺寸 / 速度 / 数量 / 周期 / 文本等），调整即按新参数重建演示"
        "控件：连续型自动重启，触发型点击「播放」重放，滚动型点击「播放」"
        "驱动滚动演示。",
        [box])

    # 主题切换：整页重建各卡演示控件，刷新 demo 内的令牌色样式
    # （自绘控件自身已监听 theme_changed；此处主要覆盖 _fill 等 QSS 标签）。
    tm = ThemeManager.instance()
    root_ref = weakref.ref(page.widget())

    def _on_theme(*_):
        root = root_ref()
        if root is None:
            tm.theme_changed.disconnect(_on_theme)
            return
        try:
            cards = root.findChildren(ParamCard)
        except RuntimeError:
            tm.theme_changed.disconnect(_on_theme)
            return
        for c in cards:
            rb = getattr(c, "_rebuild", None)
            if rb is None:
                continue
            try:
                rb()
            except RuntimeError:
                pass  # 卡片 C++ 侧已销毁（页面重建竞态），忽略

    tm.theme_changed.connect(_on_theme)
    return page
