# -*- coding: utf-8 -*-
"""Demo 演示页包：统一导航注册表。

``NAV`` 为有序结构：``[(分类键, 分类标题, [(页面键, 页面标题, 页面工厂), ...]), ...]``。
每个页面工厂遵循 ``create_page() -> QWidget`` 约定（返回一个完整演示页）。
MainWindow 依据 ``NAV`` 构建左侧导航树并懒加载右侧页面。

除布局页（页面内已含「用法」分区）外，本模块在页面工厂外包一层
``_with_usage``：按页面键在页面顶部注入「用法」代码标签
（单行灰字等宽样式），展示该组件 / 动画的最小 Kit 调用示例，
开发者看 Demo 即可学会用法。
"""

from . import (
    anim_painted,
    anim_property,
    basic_widgets,
    blueprint,
    charts,
    display,
    feedback,
    inputs,
    layouts,
    tokens,
)
from .common import usage_section

#: 页面键 -> 最小调用示例（注入到页面顶部「用法」分区；布局页自带用法，不在此列）
USAGE = {
    # -- 设计令牌 / 基础 --------------------------------------------------
    "tokens": 'from InstructionX_UIKit.theme import T, ThemeManager  # T("color.primary") 取令牌',
    "basic_widgets": 'from InstructionX_UIKit.components import Button, LineEdit, CheckBox  # 标准控件换肤',
    "charts": 'from InstructionX_UIKit.charts import ChartWidget  # set_option({...}) 数据驱动渲染',
    # -- 组件 · 输入 ------------------------------------------------------
    "button": 'Button("确定", variant="primary", size="md")',
    "icon_button": 'IconButton(text="+", variant="default", shape="circle")',
    "checkbox": 'CheckBox("记住我", checked=True)',
    "radio": 'RadioButton("选项 A")  # 配合 RadioGroup 互斥',
    "switch": 'Switch(checked=True, size="md")',
    "line_edit": 'LineEdit(placeholder="请输入", size="md")',
    "text_area": 'TextArea(placeholder="请输入", auto_height=True, max_length=200)',
    "spin_box": 'SpinBox(minimum=0, maximum=99, value=1)  # DoubleSpinBox 同理',
    "combo_box": 'ComboBox(items=["选项一", "选项二"], searchable=True)',
    "slider": 'Slider(minimum=0, maximum=100, value=30)',
    "date_picker": 'DatePicker()  # 弹出自定义中文日历',
    "time_picker": 'TimePicker()  # 时 / 分 / 秒调节',
    "rating": 'Rating(count=5, value=3.5)',
    "color_picker": 'ColorPicker(color="#3F5E8C")  # colorChanged 信号',
    "auto_complete": 'AutoComplete(items=["apple", "banana"], placeholder="输入过滤")',
    "cascader": 'Cascader(options=[{"value": "zj", "label": "浙江", "children": [...]}])',
    "transfer": 'Transfer(items=[("条目 1", False), ("条目 2", True)])',
    "upload": 'UploadWidget(hint="拖拽文件到此处，或点击选择文件")',
    "segmented": 'SegmentedControl(items=["日", "周", "月"], current=0)',
    "form": 'FormLayout()  # add_row("用户名", LineEdit(), required=True)',
    # -- 组件 · 展示 ------------------------------------------------------
    "avatar": 'Avatar("张三", size="lg")',
    "badge": 'Badge(widget=btn, count=5)  # 或独立点 badge=Badge(...)',
    "card": 'Card(title="卡片标题")  # layout() 内加内容',
    "descriptions": 'Descriptions(title="用户信息", column=3)  # set_items([...]) / add_item(label, value)',
    "list_view": 'ListWidget()  # add_items([...]) 由调用方传数据',
    "table": 'Table(rows=0, columns=3)  # set_data(headers, rows) 由调用方传数据',
    "tree": 'Tree()  # set_data([...]) / add_item(text, parent) 由调用方传数据',
    "timeline": 'Timeline(pending="等待中")  # add_item(text, time=..., color=..., icon=...)',
    "statistic": 'Statistic(title="活跃用户", value=24317)  # set_suffix("人") / set_trend(8.2)',
    "calendar": 'Calendar()  # 中文月历卡片',
    "carousel": 'Carousel(autoplay=3000)  # add_page(widget)',
    "image_view": 'ImageView(source=QPixmap("a.png"), radius=8)',
    "qrcode_view": 'QRCodeView(text="https://example.com", size=128)',
    "comment": 'CommentView(author="张三", content="写得很好", time="2 小时前")',
    "collapse": 'Collapse(accordion=False)  # add_panel(title, content)',
    "empty": 'Empty(description="暂无数据")',
    "tooltip": 'set_tooltip(btn, "提示文本")',
    "popover": 'Popover(title="标题", content=widget)  # show_for(anchor, placement="bottom")',
    "markdown_view": 'MarkdownView("# 标题\\n正文")  # append_markdown(chunk) 流式追加',
    # -- 组件 · 反馈 ------------------------------------------------------
    "tabs": 'Tabs(variant="line")  # addTab("标签一", widget)',
    "anchor": 'Anchor()  # set_items([(key, title, target_widget), ...])',
    "breadcrumb": 'Breadcrumb(items=["首页", "列表", "详情"])',
    "dropdown": 'DropdownButton("更多操作")  # set_items([...]) 或 add_item(...)',
    "nav_menu": 'NavMenu()  # add_group("组") / add_item(key, text, icon)',
    "page_header": 'PageHeader(title="标题", subtitle="副标题")',
    "pagination": 'Pagination(total=128, page_size=10)',
    "steps": 'Steps(Qt.Horizontal)  # 方向为构造参数，add_item(...) 加节点',
    "alert": 'Alert(type="info", title="提示", description="说明文本")',
    "dialog": 'Dialog.confirm(parent, "标题", "内容", on_result=fn)  # 或 Dialog.info(...)',
    "drawer": 'Drawer(parent, position="right", size=300, title="标题")',
    "notification": 'Notification.success(parent, "标题", "内容", duration=4000)',
    "message": 'Message.success(parent, "已保存", duration=2000)',
    "popconfirm": 'Popconfirm.confirm(anchor, "确认删除？", on_result=fn)',
    "result": 'ResultView(status="success", title="操作成功", subtitle="...")',
    "skeleton": 'Skeleton(avatar=True, title=True, rows=3)',
    "spinner": 'Spinner(size="md", tip="加载中...")',
    "progress_bar": 'ProgressBar(value=40)  # CircleProgress(value=75)',
    "tour": 'Tour(window)  # add_step(target, title, content) 后 start()',
    # -- 动画 --------------------------------------------------------------
    "anim_property": 'from InstructionX_UIKit.anim import fade_in  # fade_in(widget, duration=...)',
    "anim_painted": 'from InstructionX_UIKit.anim import SpinnerArc  # 自绘动画控件，直接实例化',
}


def _with_usage(key, factory):
    """在页面顶部注入「用法」代码标签（页面需由 make_page 构建）。"""
    def make():
        page = factory()
        code = USAGE.get(key)
        if code:
            try:
                content = page.widget()
                content.layout().insertWidget(2, usage_section(code))
            except (AttributeError, TypeError):
                pass  # 非 make_page 结构的页面不注入
        return page
    return make


def _register(pages):
    """为 (键, 标题, 工厂) 列表中的每个工厂包上用法注入。"""
    return [(key, title, _with_usage(key, factory)) for key, title, factory in pages]


#: 导航注册表（顺序即导航树顺序）
NAV = [
    ("tokens", "设计令牌", _register([
        ("tokens", "设计令牌总览", tokens.create_page),
    ])),
    ("layouts", "布局预设", list(layouts.LAYOUT_PAGES)),  # 布局页自带「用法」分区
    ("inputs", "组件 · 输入", _register(inputs.INPUT_PAGES)),
    ("display", "组件 · 展示", _register(display.DISPLAY_PAGES)),
    ("feedback", "组件 · 反馈", _register(feedback.FEEDBACK_PAGES)),
    ("anim_property", "动画 · 属性", _register([
        ("anim_property", "属性动画（28）", anim_property.create_page),
    ])),
    ("anim_painted", "动画 · 自绘", _register([
        ("anim_painted", "自绘动画（24）", anim_painted.create_page),
    ])),
    ("basic_widgets", "基础控件", _register([
        ("basic_widgets", "基础控件全家福", basic_widgets.create_page),
    ])),
    ("charts", "图表", _register([
        ("charts", "图表（原生引擎）", charts.create_page),
    ])),
    ("blueprint", "蓝图", _register([
        ("blueprint", "蓝图（节点图）", blueprint.create_page),
    ])),
]

__all__ = ["NAV"]
