# -*- coding: utf-8 -*-
"""组件 · 输入演示页：20 个输入与按钮组件，每组件一页，覆盖主要变体。

页面 = 标题 + 说明 + 分区演示（变体 / 尺寸 / 状态），紧凑排布。
所有组件基于全局 QSS 与令牌，亮 / 暗主题切换自动换肤。
"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget

from InstructionX_UIKit.components.auto_complete import AutoComplete
from InstructionX_UIKit.components.button import Button
from InstructionX_UIKit.components.cascader import Cascader
from InstructionX_UIKit.components.checkbox import CheckBox
from InstructionX_UIKit.components.color_picker import ColorPicker
from InstructionX_UIKit.components.combo_box import ComboBox
from InstructionX_UIKit.components.date_picker import DatePicker
from InstructionX_UIKit.components.form import FormLayout
from InstructionX_UIKit.components.icon_button import IconButton
from InstructionX_UIKit.components.line_edit import LineEdit
from InstructionX_UIKit.components.radio import RadioButton, RadioGroup
from InstructionX_UIKit.components.rating import Rating
from InstructionX_UIKit.components.segmented import SegmentedControl
from InstructionX_UIKit.components.slider import Slider
from InstructionX_UIKit.components.spin_box import DoubleSpinBox, SpinBox
from InstructionX_UIKit.components.switch import Switch
from InstructionX_UIKit.components.text_area import TextArea
from InstructionX_UIKit.components.time_picker import TimePicker
from InstructionX_UIKit.components.transfer import Transfer
from InstructionX_UIKit.components.upload import UploadWidget

from .common import Section, hint_label, make_page, row


def _disabled(widget) -> QWidget:
    widget.setEnabled(False)
    return widget


# ---------------------------------------------------------------------------
# 各组件页面
# ---------------------------------------------------------------------------

def create_button_page() -> QWidget:
    variants = Section("变体 variant")
    variants.layout().addWidget(row(*[
        Button(t, variant=v) for t, v in
        (("主要", "primary"), ("默认", "default"), ("虚线", "dashed"),
         ("文字", "text"), ("链接", "link"), ("危险", "danger"))]))
    sizes = Section("尺寸 / 状态")
    sizes.layout().addWidget(row(
        Button("小号", size="sm"), Button("中号", size="md"),
        Button("大号", size="lg"), Button("加载中", variant="primary", loading=True),
        _disabled(Button("禁用", variant="primary"))))
    sizes.layout().addWidget(Button("块级按钮 block", variant="primary", block=True))
    shapes = Section("形状 shape")
    # 圆形按钮：QSS 约定「配合组件固定宽=高」，此处按 sm/md/lg 边长
    # 24/32/40 固定为正方形，否则 "+" 单字按钮宽度由字宽决定，会渲染成
    # 细长条。短文本（≤2 字符）圆形按钮由组件按墨迹盒自绘，"+" 在三档
    # 尺寸下均水平 + 垂直精确居中。
    circle_sm = Button("+", shape="circle", variant="primary", size="sm")
    circle_sm.setFixedSize(24, 24)
    circle_md = Button("+", shape="circle", variant="primary")
    circle_md.setFixedSize(32, 32)
    circle_lg = Button("+", shape="circle", variant="primary", size="lg")
    circle_lg.setFixedSize(40, 40)
    shapes.layout().addWidget(row(
        Button("圆角", shape="round"), circle_sm, circle_md, circle_lg,
        Button("胶囊", shape="round", variant="primary")))
    return make_page("Button 按钮", "六种变体、三种尺寸，支持加载态、块级与圆角 / 圆形。",
                     [variants, sizes, shapes])


def create_icon_button_page() -> QWidget:
    s1 = Section("图标与形状")
    s1.layout().addWidget(row(
        IconButton(text="+", variant="primary", shape="circle"),
        IconButton(text="×", variant="danger", shape="circle"),
        IconButton(text="?", shape="circle"),
        IconButton(text="★", variant="default"),
        IconButton(text="⚙", shape="round", variant="primary")))
    s2 = Section("尺寸 / 禁用")
    s2.layout().addWidget(row(
        IconButton(text="+", size="sm"), IconButton(text="+", size="md"),
        IconButton(text="+", size="lg"),
        _disabled(IconButton(text="+", variant="primary", shape="circle"))))
    return make_page("IconButton 图标按钮", "QToolButton 封装，支持文本符号 / QIcon，变体、尺寸与形状。",
                     [s1, s2])


def create_checkbox_page() -> QWidget:
    s = Section("状态")
    tri = CheckBox("部分选中（三态）", tristate=True)
    tri.set_check_state(Qt.PartiallyChecked)
    s.layout().addWidget(row(
        CheckBox("未选中"), CheckBox("已选中", checked=True), tri,
        _disabled(CheckBox("禁用", checked=True))))
    return make_page("CheckBox 复选框", "QSS 自绘指示框，支持三态与禁用态。", [s])


def create_radio_page() -> QWidget:
    s = Section("单选组")
    group = RadioGroup()
    radios = [group.add_button(t, id=i + 1) for i, t in
              enumerate(("方案一", "方案二", "方案三"))]
    group.set_checked_id(2)
    s.layout().addWidget(row(*(radios + [_disabled(RadioButton("禁用"))])))
    return make_page("RadioButton 单选框", "RadioGroup 按 id 管理互斥选择，支持按文案选中。", [s])


def create_switch_page() -> QWidget:
    s = Section("开关")
    s.layout().addWidget(row(
        Switch(checked=True), Switch(checked=False),
        Switch(checked=True, size="sm"),
        _disabled(Switch(checked=True))))
    return make_page("Switch 开关", "自绘滑块开关，带过渡动画，sm / md 两种尺寸。", [s])


def create_line_edit_page() -> QWidget:
    s1 = Section("基础与前后缀")
    le1 = LineEdit(placeholder="请输入用户名", clearable=True)
    le2 = LineEdit("user", clearable=True)
    le2.set_prefix_icon("@")
    le2.set_suffix_icon(".com")
    for w in (le1, le2):
        w.setMinimumWidth(200)
    s1.layout().addWidget(row(le1, le2))
    s2 = Section("密码 / 错误 / 禁用 / 尺寸")
    pwd = LineEdit("secret")
    pwd.set_password_mode(True)
    err = LineEdit("错误内容")
    err.set_error(True)
    pwd.setMinimumWidth(180)
    err.setMinimumWidth(180)
    s2.layout().addWidget(row(pwd, err, _disabled(LineEdit("禁用"))))
    s2.layout().addWidget(row(LineEdit(placeholder="小号", size="sm"),
                              LineEdit(placeholder="大号", size="lg")))
    return make_page("LineEdit 输入框", "前后缀图标、清除按钮、密码切换、error 红色边框。",
                     [s1, s2])


def create_text_area_page() -> QWidget:
    s = Section("自适应高度 + 字数统计")
    ta = TextArea(placeholder="介绍一下自己（自适应高度 + 字数统计）",
                  auto_height=True, min_rows=2, max_rows=5,
                  max_length=120, show_count=True)
    ta.setPlainText("这是一段示例文本，演示自适应高度与右下角的字数统计。")
    ta.setMinimumWidth(360)
    s.layout().addWidget(row(ta, _disabled(TextArea(placeholder="禁用"))))
    return make_page("TextArea 文本域", "自适应高度、最大长度与字数统计。", [s])


def create_spin_box_page() -> QWidget:
    s = Section("数字调节框")
    s.layout().addWidget(row(
        SpinBox(minimum=0, maximum=99, value=5, size="sm"),
        SpinBox(minimum=0, maximum=99, value=42),
        SpinBox(minimum=0, maximum=99, value=8, size="lg"),
        DoubleSpinBox(minimum=0, maximum=99, value=19.9, suffix=" 元"),
        _disabled(SpinBox(value=7))))
    return make_page("SpinBox 数字框", "整数与小数调节框，统一高度与按钮样式。", [s])


def create_combo_box_page() -> QWidget:
    s = Section("下拉框")
    s.layout().addWidget(row(
        ComboBox(["北京", "上海", "广州"], size="sm"),
        ComboBox(["北京", "上海", "广州"]),
        ComboBox(["苹果", "香蕉", "橙子"], searchable=True,
                 placeholder="搜索水果", size="lg"),
        _disabled(ComboBox(["不可用"]))))
    return make_page("ComboBox 下拉框", "下拉样式、搜索过滤选项与非法输入回退。", [s])


def create_slider_page() -> QWidget:
    s = Section("滑块")
    sl = Slider(minimum=0, maximum=100, value=45)
    sl.set_ticks(10)
    sl.setMinimumWidth(320)
    dis = Slider(value=30)
    dis.setMinimumWidth(220)
    dis.setEnabled(False)
    s.layout().addWidget(row(sl, dis))
    return make_page("Slider 滑块", "刻度与数值提示，QSS 精致滑轨。", [s])


def create_date_picker_page() -> QWidget:
    s = Section("日期选择")
    dp = DatePicker()
    dp.set_date_str("2025-06-15")
    s.layout().addWidget(row(dp, DatePicker(size="sm"), _disabled(DatePicker())))
    return make_page("DatePicker 日期选择", "弹出自定义样式的中文日历。", [s])


def create_time_picker_page() -> QWidget:
    s = Section("时间选择")
    tp = TimePicker()
    tp.set_time_str("09:30:00")
    s.layout().addWidget(row(tp, TimePicker(size="sm"), _disabled(TimePicker())))
    return make_page("TimePicker 时间选择", "时 / 分 / 秒时间调节框。", [s])


def create_rating_page() -> QWidget:
    s = Section("评分")
    s.layout().addWidget(row(
        Rating(value=3.5, allow_half=True),
        Rating(value=4, read_only=True),
        _disabled(Rating(value=3, read_only=True))))
    return make_page("Rating 评分", "自绘星级，允许半星，value 信号。", [s])


def create_color_picker_page() -> QWidget:
    s = Section("颜色选择")
    s.layout().addWidget(row(
        ColorPicker("#3F5E8C"), ColorPicker("#3E7E5F", size="sm"),
        _disabled(ColorPicker("#98A0AC"))))
    return make_page("ColorPicker 颜色选择", "色块按钮 + QColorDialog，colorChanged 信号。", [s])


def create_auto_complete_page() -> QWidget:
    s = Section("自动完成")
    ac = AutoComplete(["苹果", "香蕉", "橙子", "苹果派", "葡萄"],
                      placeholder="输入以搜索水果")
    ac.setMinimumWidth(240)
    s.layout().addWidget(row(ac, _disabled(AutoComplete(["x"], placeholder="禁用"))))
    s.layout().addWidget(hint_label("输入关键字后延迟过滤候选，回车选中。", role="tertiary"))
    return make_page("AutoComplete 自动完成", "QCompleter 封装，延迟过滤。", [s])


def create_cascader_page() -> QWidget:
    s = Section("级联选择")
    cas = Cascader([
        {"value": "zj", "label": "浙江", "children": [
            {"value": "hz", "label": "杭州"},
            {"value": "nb", "label": "宁波"}]},
        {"value": "gd", "label": "广东", "children": [
            {"value": "gz", "label": "广州"},
            {"value": "sz", "label": "深圳"}]},
    ])
    cas.set_path(["zj", "hz"])
    s.layout().addWidget(row(cas, _disabled(Cascader([{"value": "x", "label": "无"}]))))
    return make_page("Cascader 级联选择", "按钮 + 多级菜单，pathChanged 信号。", [s])


def create_transfer_page() -> QWidget:
    s = Section("穿梭框")
    tr = Transfer(["苹果", "香蕉", "橙子", "葡萄", "西瓜"])
    tr.set_target_items(["香蕉", "葡萄"])
    s.layout().addWidget(tr)
    return make_page("Transfer 穿梭框", "双列表左右移动，changed 信号。", [s])


def create_upload_page() -> QWidget:
    s = Section("上传")
    up = UploadWidget()
    up.add_files(["季度报告.docx", "数据汇总.csv", "设计稿.png"])
    up.setMinimumWidth(400)
    s.layout().addWidget(row(up))
    s.layout().addWidget(hint_label("拖拽文件到此处，或点击选择文件；列表可移除。", role="tertiary"))
    return make_page("UploadWidget 上传", "拖拽区 + 文件选择，filesChanged 信号。", [s])


def create_segmented_page() -> QWidget:
    s = Section("分段控制器")
    seg2 = SegmentedControl(["列表", "卡片", "禁用项"], current=0, size="sm")
    seg2.set_item_enabled(2, False)
    s.layout().addWidget(row(
        SegmentedControl(["日", "周", "月", "年"], current=1),
        seg2,
        _disabled(SegmentedControl(["甲", "乙"], current=0))))
    return make_page("SegmentedControl 分段控制", "自绘滑动指示块，currentChanged 信号。", [s])


def create_form_page() -> QWidget:
    s = Section("表单校验")
    holder = QWidget()
    form = FormLayout(holder)
    user = LineEdit("abc")
    form.add_row("用户名", user, required=True,
                 validator=lambda v: len(v) >= 3 or "至少 3 个字符")
    mail = LineEdit("bad")
    form.add_row("邮箱", mail, required=True,
                 validator=lambda v: "@" in v or "邮箱格式不正确")
    form.add_row("备注", TextArea(auto_height=True, min_rows=2, max_rows=3))
    form.validate_all()  # 触发错误提示行
    holder.setMinimumWidth(420)
    s.layout().addWidget(holder)
    s.layout().addWidget(hint_label("必填星号 + 校验错误提示行；上方邮箱故意填写非法值以展示错误态。",
                                    role="tertiary"))
    return make_page("FormLayout 表单", "必填星号、错误提示行与整表校验。", [s])


#: 输入组件页注册表：(导航键, 标题, 页面工厂)
INPUT_PAGES = [
    ("button", "Button 按钮", create_button_page),
    ("icon_button", "IconButton 图标按钮", create_icon_button_page),
    ("checkbox", "CheckBox 复选框", create_checkbox_page),
    ("radio", "RadioButton 单选框", create_radio_page),
    ("switch", "Switch 开关", create_switch_page),
    ("line_edit", "LineEdit 输入框", create_line_edit_page),
    ("text_area", "TextArea 文本域", create_text_area_page),
    ("spin_box", "SpinBox 数字框", create_spin_box_page),
    ("combo_box", "ComboBox 下拉框", create_combo_box_page),
    ("slider", "Slider 滑块", create_slider_page),
    ("date_picker", "DatePicker 日期", create_date_picker_page),
    ("time_picker", "TimePicker 时间", create_time_picker_page),
    ("rating", "Rating 评分", create_rating_page),
    ("color_picker", "ColorPicker 颜色", create_color_picker_page),
    ("auto_complete", "AutoComplete 自动完成", create_auto_complete_page),
    ("cascader", "Cascader 级联选择", create_cascader_page),
    ("transfer", "Transfer 穿梭框", create_transfer_page),
    ("upload", "UploadWidget 上传", create_upload_page),
    ("segmented", "SegmentedControl 分段", create_segmented_page),
    ("form", "FormLayout 表单", create_form_page),
]
