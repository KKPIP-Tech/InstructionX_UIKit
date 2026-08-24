# -*- coding: utf-8 -*-
"""布局预设演示页：13 个布局预设，每页以实尺寸嵌入对应布局。

布局本身（InstructionX_UIKit.layouts）为 API 驱动、不含假数据；
本页负责生成示例内容（见 ``layout_samples.py``）并传入布局。
每个演示页顶部有「用法」分区，展示该布局的单行调用示例，
开发者照此即可用 Kit 复现相同效果。
"""

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QFrame, QWidget

from InstructionX_UIKit.layouts.card_grid import create_card_grid
from InstructionX_UIKit.layouts.centered_container import create_centered_container
from InstructionX_UIKit.layouts.chat_conversation import create_chat_conversation
from InstructionX_UIKit.layouts.dashboard_grid import create_dashboard_grid
from InstructionX_UIKit.layouts.hero_section import create_hero_section
from InstructionX_UIKit.layouts.holy_grail import create_holy_grail
from InstructionX_UIKit.layouts.master_detail import create_master_detail
from InstructionX_UIKit.layouts.media_left_right import create_media_left_right
from InstructionX_UIKit.layouts.sidebar_layout import create_sidebar_layout
from InstructionX_UIKit.layouts.single_column import create_single_column
from InstructionX_UIKit.layouts.split_panel import create_split_panel
from InstructionX_UIKit.layouts.top_nav_bar import create_top_nav_bar
from InstructionX_UIKit.layouts.waterfall import create_waterfall

from . import layout_samples as samples
from .common import Section, make_page, usage_section


def _build_top_nav_bar() -> QWidget:
    return create_top_nav_bar(**samples.TOP_NAV_BAR)


def _build_holy_grail() -> QWidget:
    return create_holy_grail(
        **samples.HOLY_GRAIL,
        center=samples.build_holy_grail_center(),
        side=samples.build_holy_grail_side(),
    )


def _build_card_grid() -> QWidget:
    return create_card_grid(items=samples.CARD_GRID_ITEMS)


def _build_single_column() -> QWidget:
    return create_single_column(**samples.SINGLE_COLUMN)


def _build_sidebar_layout() -> QWidget:
    return create_sidebar_layout(
        brand="控制台",
        nav_items=samples.SIDEBAR_NAV_ITEMS,
        content=samples.build_sidebar_content(),
    )


def _build_master_detail() -> QWidget:
    return create_master_detail(**samples.MASTER_DETAIL)


def _build_split_panel() -> QWidget:
    return create_split_panel(
        **samples.SPLIT_PANEL,
        content=samples.build_split_panel_content(),
    )


def _build_dashboard_grid() -> QWidget:
    return create_dashboard_grid(cards=samples.build_dashboard_cards())


def _build_hero_section() -> QWidget:
    return create_hero_section(**samples.HERO_SECTION)


def _build_centered_container() -> QWidget:
    return create_centered_container(**samples.CENTERED_CONTAINER)


def _build_waterfall() -> QWidget:
    return create_waterfall(items=samples.WATERFALL_ITEMS)


def _build_media_left_right() -> QWidget:
    return create_media_left_right(**samples.MEDIA_LEFT_RIGHT)


def _build_chat_conversation() -> QWidget:
    """流式对话演示：提交后模拟 AI 逐 token 流式回复；气泡操作条常显，
    演示复制 / 删除 / 编辑与重新生成 / 继续生成信号接线。"""
    conv = create_chat_conversation(messages=samples.CHAT_MESSAGES)
    conv.set_actions_always_visible(True)

    def _stream_reply(idx, text):
        """逐段流式输出 text 到消息 idx，结束后冻结计时。"""
        chunks = [text[i:i + 6] for i in range(0, len(text), 6)]
        timer = QTimer(conv)

        def _tick():
            if not chunks:
                timer.stop()
                timer.deleteLater()
                conv.finish_message(idx)
                return
            conv.append_to_message(idx, chunks.pop(0))

        timer.timeout.connect(_tick)
        timer.start(50)

    def _on_submit(text):
        user_idx = conv.add_message("user", text)
        conv.finish_message(user_idx)
        idx = conv.add_message("assistant", "")
        _stream_reply(idx, samples.CHAT_STREAM_REPLY)

    def _on_regenerate(index):
        # 演示：清空原内容后重新流式输出同一回复（真实场景由调用方重新请求模型）
        conv.update_message(index, "")
        _stream_reply(index, samples.CHAT_STREAM_REPLY)

    def _on_continue(index):
        conv.append_to_message(index, samples.CHAT_STREAM_CONTINUE)
        conv.finish_message(index)

    conv.messageSubmitted.connect(_on_submit)
    conv.regenerateRequested.connect(_on_regenerate)
    conv.continueRequested.connect(_on_continue)
    return conv


# (导航键, 标题, 说明, 布局工厂, 预览高度)
_LAYOUTS = [
    ("top_nav_bar", "顶部导航栏", "Logo + 菜单 + 搜索 + 头像的窗口级顶部导航。",
     _build_top_nav_bar, 520),
    ("holy_grail", "圣杯布局", "header / footer / 双侧栏 / 主区，QSplitter 可拖拽调整。",
     _build_holy_grail, 560),
    ("card_grid", "卡片网格", "按断点 1 / 2 / 3 / 4 列自适应的卡片网格。",
     _build_card_grid, 560),
    ("single_column", "单列堆叠", "最大宽 760 居中的单列垂直节奏布局。",
     _build_single_column, 560),
    ("sidebar_layout", "侧边栏布局", "左侧导航 + 右侧内容，可折叠为图标栏。",
     _build_sidebar_layout, 560),
    ("master_detail", "列表-详情", "左列表右详情，窄断点自动堆叠。",
     _build_master_detail, 560),
    ("split_panel", "分栏面板", "QSplitter 2-3 栏，记忆拖拽比例。",
     _build_split_panel, 560),
    ("dashboard_grid", "仪表盘网格", "12 列网格，卡片跨 3 / 4 / 6 / 12 列。",
     _build_dashboard_grid, 640),
    ("hero_section", "英雄区", "大标题 + 副文案 + 双按钮 + 右侧插图占位。",
     _build_hero_section, 480),
    ("centered_container", "居中容器", "内容限宽 960 居中展示。",
     _build_centered_container, 560),
    ("waterfall", "瀑布流", "2-4 列不等高卡片瀑布流。",
     _build_waterfall, 640),
    ("media_left_right", "图文左右", "图左文右 / 图右文左交替段落。",
     _build_media_left_right, 640),
    ("chat_conversation", "流式对话", "AI 对话页面：Markdown 消息气泡 + 流式追加 + 底部输入区。",
     _build_chat_conversation, 560),
]


def _embed(key: str, factory, height: int) -> QFrame:
    """把布局以实尺寸嵌入一个分区容器（顶部附「用法」代码标签）。"""
    box = Section("实时预览")
    widget = factory()
    widget.setMinimumHeight(height)
    box.layout().addWidget(widget)
    return box


def _make(key: str) -> QWidget:
    for k, title, desc, factory, height in _LAYOUTS:
        if k == key:
            return make_page(title, desc, [
                usage_section(samples.USAGE[key]),
                _embed(key, factory, height),
            ])
    raise KeyError(f"未知布局: {key}")


# 逐个页面工厂（create_page() -> QWidget 契约：每布局一个演示页）--------------

def create_top_nav_bar_page() -> QWidget:
    return _make("top_nav_bar")


def create_holy_grail_page() -> QWidget:
    return _make("holy_grail")


def create_card_grid_page() -> QWidget:
    return _make("card_grid")


def create_single_column_page() -> QWidget:
    return _make("single_column")


def create_sidebar_layout_page() -> QWidget:
    return _make("sidebar_layout")


def create_master_detail_page() -> QWidget:
    return _make("master_detail")


def create_split_panel_page() -> QWidget:
    return _make("split_panel")


def create_dashboard_grid_page() -> QWidget:
    return _make("dashboard_grid")


def create_hero_section_page() -> QWidget:
    return _make("hero_section")


def create_centered_container_page() -> QWidget:
    return _make("centered_container")


def create_waterfall_page() -> QWidget:
    return _make("waterfall")


def create_media_left_right_page() -> QWidget:
    return _make("media_left_right")


def create_chat_conversation_page() -> QWidget:
    return _make("chat_conversation")


#: 布局页注册表：(导航键, 标题, 页面工厂)
LAYOUT_PAGES = [
    ("top_nav_bar", "顶部导航栏", create_top_nav_bar_page),
    ("holy_grail", "圣杯布局", create_holy_grail_page),
    ("card_grid", "卡片网格", create_card_grid_page),
    ("single_column", "单列堆叠", create_single_column_page),
    ("sidebar_layout", "侧边栏布局", create_sidebar_layout_page),
    ("master_detail", "列表-详情", create_master_detail_page),
    ("split_panel", "分栏面板", create_split_panel_page),
    ("dashboard_grid", "仪表盘网格", create_dashboard_grid_page),
    ("hero_section", "英雄区", create_hero_section_page),
    ("centered_container", "居中容器", create_centered_container_page),
    ("waterfall", "瀑布流", create_waterfall_page),
    ("media_left_right", "图文左右", create_media_left_right_page),
    ("chat_conversation", "流式对话", create_chat_conversation_page),
]
