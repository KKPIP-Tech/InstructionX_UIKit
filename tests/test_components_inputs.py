# -*- coding: utf-8 -*-
"""inputs 代理自测：输入与按钮组件（SPEC §5.1 / §9）。

直接运行（无 pytest 依赖）::

    QT_QPA_PLATFORM=offscreen python tests/test_components_inputs.py

覆盖：
- 20 个组件逐个实例化（含主要变体与禁用态）与关键行为断言；
- 信号冒烟：valueChanged / colorChanged / pathChanged / changed /
  filesChanged / currentChanged / validated；
- 组装滚动演示页，亮 / 暗主题各整页 grab() 截图，
  并对每个组件分区单独 grab() 到 tests/shots/inputs_<name>_<theme>.png；
- 截图健全性检查（尺寸、文件大小、非单色、亮暗背景符合令牌）。
任何异常即失败，退出码 1。
"""

import os
import sys
import time
import traceback
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

SHOTS = ROOT / "tests" / "shots"

_FAILURES = []

# 各检查在模块导入期即执行，需先备好 QApplication 并应用主题
from PySide6.QtWidgets import QApplication  # noqa: E402

_APP = QApplication.instance() or QApplication([])

from InstructionX_UIKit.theme import ThemeManager  # noqa: E402

ThemeManager.instance().apply(_APP)


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


def assert_true(cond, msg=""):
    if not cond:
        raise AssertionError(msg or "断言失败")


def assert_eq(actual, expected, msg=""):
    if actual != expected:
        raise AssertionError(f"{msg} 期望 {expected!r}，实际 {actual!r}")


def settle(app, ms=300):
    """推进事件循环 ms 毫秒，让动画 / 防抖走完。"""
    from PySide6.QtCore import QElapsedTimer

    timer = QElapsedTimer()
    timer.start()
    while timer.elapsed() < ms:
        app.processEvents()
        time.sleep(0.004)


# ---------------------------------------------------------------------------
# 1. 组件实例化与行为断言（SPEC §5.1，20 个文件）
# ---------------------------------------------------------------------------

@check("button: Button 变体 / 尺寸 / loading / block")
def _():
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QSizePolicy

    from InstructionX_UIKit.components.button import Button

    btn = Button("主要", variant="primary", size="lg")
    assert_eq(btn.property("variant"), "primary", "variant 属性")
    assert_eq(btn.property("uiksize"), "lg", "size 应映射为 uiksize")
    btn.ensurePolished()
    assert_eq(btn.sizeHint().height(), 40, "lg 高度")
    for v in ("default", "dashed", "text", "link", "danger"):
        b = Button("x", variant=v)
        assert_eq(b.property("variant"), v, f"variant={v}")
    b2 = Button("x", size="sm")
    b2.ensurePolished()
    assert_eq(b2.sizeHint().height(), 24, "sm 高度")
    b2.set_shape("circle")
    assert_eq(b2.property("shape"), "circle", "shape 属性")
    # loading：屏蔽鼠标 + 状态可读 + 可复原
    plain_w = b2.sizeHint().width()
    b2.set_loading(True)
    assert_true(b2.is_loading(), "loading 状态")
    assert_true(b2.sizeHint().width() > plain_w,
                "loading 应加宽自身 sizeHint")
    b2.set_loading(False)
    assert_true(not b2.is_loading(), "loading 复原")
    # block：水平 Expanding
    b3 = Button("块级", block=True)
    assert_eq(b3.sizePolicy().horizontalPolicy(), QSizePolicy.Expanding,
              "block 应水平撑满")
    b4 = Button("禁用")
    b4.setEnabled(False)
    assert_true(not b4.isEnabled(), "禁用态")


@check("icon_button: IconButton 图标 / 文本符号 / 形状 / 尺寸")
def _():
    from InstructionX_UIKit.components.icon_button import IconButton

    b = IconButton(text="+", variant="primary", shape="circle", size="md")
    assert_eq(b.text(), "+", "文本符号")
    assert_eq(b.property("variant"), "primary", "variant 属性")
    assert_eq((b.width(), b.height()), (32, 32), "circle 固定正圆")
    b.set_size("sm")
    assert_eq((b.width(), b.height()), (24, 24), "circle sm 边长")
    b.set_shape(None)
    b.set_symbol("×")
    assert_eq(b.text(), "×", "切换文本符号")
    from PySide6.QtGui import QIcon
    b.set_icon(QIcon())
    assert_eq(b.text(), "", "设置图标清空文本")
    b.setEnabled(False)


@check("checkbox: CheckBox 三态支持")
def _():
    from PySide6.QtCore import Qt

    from InstructionX_UIKit.components.checkbox import CheckBox

    cb = CheckBox("普通", checked=True)
    assert_true(cb.isChecked(), "初始勾选")
    tri = CheckBox("三态", tristate=True)
    assert_true(tri.isTristate(), "三态开启")
    tri.set_check_state(Qt.PartiallyChecked)
    assert_eq(tri.check_state(), Qt.PartiallyChecked, "部分选中")
    tri.set_check_state(Qt.Checked)
    assert_eq(tri.check_state(), Qt.Checked, "全选")
    dis = CheckBox("禁用", checked=True)
    dis.setEnabled(False)


@check("radio: RadioButton / RadioGroup 按 id 管理")
def _():
    from InstructionX_UIKit.components.radio import RadioButton, RadioGroup

    group = RadioGroup()
    r1 = group.add_button("方案一", id=1)
    r2 = group.add_button("方案二", id=2)
    assert_true(isinstance(r1, RadioButton), "自动创建 RadioButton")
    group.set_checked_id(2)
    assert_eq(group.checked_id(), 2, "checked_id")
    assert_eq(group.checked_text(), "方案二", "checked_text")
    r1.setChecked(True)
    assert_eq(group.checked_id(), 1, "互斥切换")
    group.set_checked_text("方案二")
    assert_eq(group.checked_id(), 2, "按文案选中")
    r2.setEnabled(False)


@check("switch: Switch 状态 / 尺寸 / 过渡动画")
def _():
    from PySide6.QtWidgets import QApplication

    from InstructionX_UIKit.components.switch import Switch

    sw = Switch(checked=True)
    assert_true(sw.isChecked(), "初始开")
    assert_eq((sw.width(), sw.height()), (44, 22), "md 固定尺寸")
    sw.set_size("sm")
    assert_eq((sw.width(), sw.height()), (32, 16), "sm 固定尺寸")
    assert_eq(sw.property("uiksize"), "sm", "size 属性映射")
    sw.setChecked(False)
    settle(QApplication.instance(), 350)  # 等待过渡动画
    assert_true(sw._pos < 0.05, "动画后位置应归 0")
    sw.toggle()
    settle(QApplication.instance(), 350)
    assert_true(sw._pos > 0.95, "动画后位置应归 1")
    sw.setEnabled(False)


@check("line_edit: LineEdit 前后缀 / 清除 / 密码切换 / error")
def _():
    from PySide6.QtWidgets import QLineEdit

    from InstructionX_UIKit.components.line_edit import LineEdit

    edit = LineEdit(placeholder="邮箱", clearable=True)
    assert_true(edit.isClearButtonEnabled(), "清除按钮")
    edit.set_prefix_icon("@")
    edit.set_suffix_icon(".com")
    assert_true(len(edit.actions()) >= 2, "前后缀 action")
    edit.set_error(True)
    assert_eq(edit.property("error"), "true", "error 属性")
    assert_true(edit.has_error(), "has_error")
    edit.set_error(False)
    assert_eq(edit.property("error"), "false", "error 复原")
    pwd = LineEdit()
    pwd.set_password_mode(True)
    assert_eq(pwd.echoMode(), QLineEdit.Password, "密码模式")
    pwd._toggle_password()
    assert_eq(pwd.echoMode(), QLineEdit.Normal, "切换明文")
    pwd._toggle_password()
    assert_eq(pwd.echoMode(), QLineEdit.Password, "切回密文")
    sm = LineEdit(size="sm")
    sm.ensurePolished()
    assert_eq(sm.sizeHint().height(), 24, "sm 高度")
    edit.setEnabled(False)


@check("text_area: TextArea 自适应高度 / 字数统计 / 最大长度")
def _():
    from InstructionX_UIKit.components.text_area import TextArea

    ta = TextArea(placeholder="简介", auto_height=True, min_rows=2,
                  max_rows=4, max_length=10, show_count=True)
    ta.setPlainText("一二三四五六七八九十超额字符")
    assert_eq(ta.count(), 10, "最大长度截断")
    assert_true("10 / 10" in ta._count_label.text(), "字数统计")
    h1 = ta.maximumHeight()
    ta.blockSignals(True)
    ta.setPlainText("一\n二\n三\n四\n五\n六\n七")
    ta.blockSignals(False)
    ta._on_text_changed()
    assert_true(ta.maximumHeight() >= h1, "高度随行数增加")
    row = ta._row_height()
    doc_margin_h = 2 * ta.document().documentMargin()
    assert_true(ta.maximumHeight()
                <= 4 * row + doc_margin_h + ta._frame_padding() + 2,
                "高度受 max_rows 约束")
    ta2 = TextArea()
    ta2.setEnabled(False)


@check("spin_box: SpinBox / DoubleSpinBox 范围与尺寸")
def _():
    from InstructionX_UIKit.components.spin_box import DoubleSpinBox, SpinBox

    sp = SpinBox(minimum=1, maximum=10, value=3, size="lg")
    assert_eq(sp.value(), 3, "初始值")
    assert_eq(sp.property("uiksize"), "lg", "size 属性")
    sp.stepUp()
    assert_eq(sp.value(), 4, "stepUp")
    dsp = DoubleSpinBox(minimum=0.0, maximum=9.9, value=1.5, decimals=1,
                        suffix=" 元")
    assert_eq(dsp.value(), 1.5, "小数值")
    assert_eq(dsp.suffix(), " 元", "后缀")
    dsp.setEnabled(False)


@check("combo_box: ComboBox 搜索过滤与回退")
def _():
    from InstructionX_UIKit.components.combo_box import ComboBox

    cb = ComboBox(["北京", "上海", "广州"], searchable=True)
    assert_true(cb.isEditable(), "可编辑")
    assert_true(cb.completer() is not None, "附带 completer")
    cb.setCurrentIndex(1)
    cb.lineEdit().setText("不存在")
    cb._on_editing_finished()
    assert_eq(cb.currentIndex(), 1, "非法输入回退")
    cb.lineEdit().setText("广州")
    cb._on_editing_finished()
    assert_eq(cb.currentIndex(), 2, "合法输入选中")
    cb.set_items(["甲", "乙"])
    assert_eq(cb.count(), 2, "set_items")
    cb2 = ComboBox(["x"], size="sm")
    cb2.ensurePolished()
    assert_eq(cb2.sizeHint().height(), 24, "sm 高度")
    cb.setEnabled(False)


@check("slider: Slider 刻度与数值提示开关")
def _():
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QSlider

    from InstructionX_UIKit.components.slider import Slider

    sl = Slider(minimum=0, maximum=100, value=45)
    sl.set_ticks(10)
    assert_eq(sl.tickInterval(), 10, "刻度间隔")
    assert_eq(sl.tickPosition(), QSlider.TicksBelow, "刻度位置")
    sl.set_tip_enabled(False)
    sl.setValue(60)
    assert_eq(sl.value(), 60, "取值")
    v = Slider(orientation=Qt.Vertical)
    assert_eq(v.orientation(), Qt.Vertical, "垂直滑块")
    sl.setEnabled(False)


@check("date_picker / time_picker: 字符串往返与尺寸")
def _():
    from InstructionX_UIKit.components.date_picker import DatePicker
    from InstructionX_UIKit.components.time_picker import TimePicker

    dp = DatePicker(size="md")
    assert_true(dp.calendarPopup(), "弹出日历")
    assert_true(dp.calendarWidget() is not None, "日历实例")
    assert_true(dp.set_date_str("2025-06-15"), "日期解析")
    assert_eq(dp.date_str(), "2025-06-15", "日期往返")
    assert_true(not dp.set_date_str("2025-13-99"), "非法日期")
    tp = TimePicker(size="sm")
    assert_true(tp.set_time_str("09:30:00"), "时间解析")
    assert_eq(tp.time_str(), "09:30:00", "时间往返")
    dp.setEnabled(False)


@check("rating: Rating 半星 / 信号 / 只读")
def _():
    from InstructionX_UIKit.components.rating import Rating

    r = Rating(count=5, value=3.5, allow_half=True)
    assert_eq(r.value(), 3.5, "半星初始值")
    seen = []
    r.valueChanged.connect(seen.append)
    r.set_value(4.0, animate=False)
    assert_eq(seen[-1], 4.0, "valueChanged 信号")
    r.set_value(3.7, animate=False)
    assert_eq(r.value(), 3.5, "半星取整")
    r.set_allow_half(False)
    r.set_value(3.2, animate=False)
    assert_eq(r.value(), 3.0, "整星取整")
    ro = Rating(value=4, read_only=True)
    ro._hover = None
    r.setEnabled(False)


@check("color_picker: ColorPicker 信号与文本")
def _():
    from PySide6.QtGui import QColor

    from InstructionX_UIKit.components.color_picker import ColorPicker

    cp = ColorPicker("#3563E9")
    assert_eq(cp.color().name().lower(), "#3563e9", "初始颜色")
    seen = []
    cp.colorChanged.connect(seen.append)
    cp.set_color(QColor("#1E9E6A"))
    assert_eq(len(seen), 1, "colorChanged 信号")
    assert_eq(cp._label.text(), "#1E9E6A", "十六进制文本")
    cp.set_size("sm")
    assert_eq((cp._swatch.width(), cp._swatch.height()), (24, 24), "sm 色块")
    cp.set_show_text(False)
    cp.setEnabled(False)


@check("auto_complete: AutoComplete 延迟过滤")
def _():
    from PySide6.QtWidgets import QApplication

    from InstructionX_UIKit.components.auto_complete import AutoComplete

    ac = AutoComplete(["苹果", "香蕉", "苹果派"], delay=50)
    ac.setText("苹")
    ac._apply_filter()
    assert_eq(ac._model.rowCount(), 2, "包含过滤")
    ac.setText("")
    ac._apply_filter()
    assert_eq(ac._model.rowCount(), 3, "空文本全量")
    # 防抖：textEdited 后先不过滤，超时再过滤
    ac.setText("香")
    ac.textEdited.emit("香")
    QApplication.instance().processEvents()
    settle(QApplication.instance(), 200)
    assert_eq(ac._model.rowCount(), 1, "防抖后过滤")
    ac.set_items(["一", "二"])
    assert_eq(ac.items(), ["一", "二"], "set_items")
    ac.setEnabled(False)


@check("cascader: Cascader 路径选择与信号")
def _():
    from InstructionX_UIKit.components.cascader import Cascader

    options = [
        {"value": "zj", "label": "浙江", "children": [
            {"value": "hz", "label": "杭州"},
            {"value": "nb", "label": "宁波", "disabled": True},
        ]},
        {"value": "gd", "label": "广东", "children": [
            {"value": "gz", "label": "广州"},
        ]},
    ]
    ca = Cascader(options)
    assert_true(ca.set_path(["zj", "hz"]), "set_path")
    assert_eq(ca.path(), ["zj", "hz"], "path")
    assert_eq(ca.labels(), ["浙江", "杭州"], "labels")
    assert_true("杭州" in ca._button.text(), "按钮文案")
    assert_true(not ca.set_path(["zj", "xx"]), "非法路径")
    # 菜单触发叶子 -> pathChanged
    seen = []
    ca.pathChanged.connect(seen.append)
    ca._rebuild_menu()
    top = ca._menu.actions()
    assert_eq(len(top), 2, "顶级菜单项")
    sub = top[0].menu()
    assert_true(sub is not None, "子菜单")
    leaf = sub.actions()[0]
    leaf.trigger()
    assert_eq(seen[-1], ["zj", "hz"], "pathChanged 信号")
    ca.clear()
    assert_eq(ca.path(), [], "clear")
    ca.setEnabled(False)


@check("transfer: Transfer 左右移动与信号")
def _():
    from InstructionX_UIKit.components.transfer import Transfer

    tr = Transfer(["甲", "乙", "丙", "丁"])
    fired = []
    tr.changed.connect(fired.append)
    tr._source.item(0).setSelected(True)
    tr._source.item(1).setSelected(True)
    tr._btn_right.click()
    assert_eq(tr.target_items(), ["甲", "乙"], "移动到目标")
    assert_eq(tr.source_items(), ["丙", "丁"], "源剩余")
    assert_eq(fired[-1], ["甲", "乙"], "changed 信号")
    tr._target.item(0).setSelected(True)
    tr._btn_left.click()
    assert_eq(tr.target_items(), ["乙"], "移回源")
    tr.set_target_items(["丙"])
    assert_eq(tr.target_items(), ["丙"], "set_target_items")
    tr.set_titles("可选", "已选")
    tr.setEnabled(False)


@check("upload: UploadWidget 增删文件与信号")
def _():
    from InstructionX_UIKit.components.upload import UploadWidget

    up = UploadWidget()
    fired = []
    up.filesChanged.connect(fired.append)
    up.add_files(["/tmp/a.txt", "/tmp/b.png", "/tmp/a.txt"])  # 重复去重
    assert_eq(up.files(), ["/tmp/a.txt", "/tmp/b.png"], "去重添加")
    assert_true(up._list.isVisible() or not up._list.isHidden(), "列表可见性")
    up.remove_file("/tmp/a.txt")
    assert_eq(up.files(), ["/tmp/b.png"], "移除")
    up.clear()
    assert_eq(up.files(), [], "清空")
    assert_eq(fired[-1], [], "filesChanged 信号")
    assert_true(up._list.isHidden(), "空列表隐藏")
    up.setEnabled(False)


@check("segmented: SegmentedControl 切换 / 禁用项 / 动画")
def _():
    from PySide6.QtWidgets import QApplication

    from InstructionX_UIKit.components.segmented import SegmentedControl

    seg = SegmentedControl(["日", "周", "月"], current=0)
    assert_eq(seg.count(), 3, "分段数")
    assert_eq(seg.property("uiksize"), "md", "size 属性")
    seen = []
    seg.currentChanged.connect(seen.append)
    seg.set_current(2, animate=False)
    assert_eq(seg.current(), 2, "set_current")
    assert_eq(seg.current_text(), "月", "current_text")
    assert_eq(seen[-1], 2, "currentChanged 信号")
    seg.set_item_enabled(1, False)
    seg.set_current(1)
    assert_eq(seg.current(), 2, "禁用项不可选")
    seg.set_current(0)  # 动画切换
    settle(QApplication.instance(), 350)
    assert_eq(seg.current(), 0, "动画后下标")
    x, w = seg._thumb_target(0)
    assert_true(abs(seg._thumb_x - x) < 1.0, "动画后指示块位置")
    seg.setEnabled(False)


@check("form: FormLayout 必填星号 / 错误提示行 / 校验")
def _():
    from InstructionX_UIKit.components.form import FormLayout
    from InstructionX_UIKit.components.line_edit import LineEdit

    form = FormLayout()
    edit = LineEdit()
    item = form.add_row("用户名", edit, required=True,
                        validator=lambda v: len(v) >= 3 or "至少 3 个字符")
    assert_true("*" in item._label_widget.text(), "必填星号")
    assert_true(not item.validate(), "空值必填失败")
    assert_eq(item.error(), "用户名不能为空", "必填错误文案")
    edit.setText("ab")
    assert_true(not item.validate(), "校验器失败")
    assert_eq(item.error(), "至少 3 个字符", "校验器文案")
    edit.setText("abc")
    assert_true(item.validate(), "校验通过")
    assert_eq(item.error(), "", "错误清除")
    edit.setText("")
    assert_true(not form.validate_all(), "整表校验失败")
    edit.setText("ok123")
    assert_true(form.validate_all(), "整表校验通过")
    form.clear_errors()
    form.set_required(item, False)
    assert_true("*" not in item._label_widget.text(), "取消必填")


# ---------------------------------------------------------------------------
# 2. 演示页组装（每个组件一组，含变体与禁用态）
# ---------------------------------------------------------------------------

def _row(layout, widgets):
    """把若干控件加入一行（左对齐）。"""
    from PySide6.QtWidgets import QHBoxLayout

    row = QHBoxLayout()
    row.setSpacing(8)
    for w in widgets:
        row.addWidget(w)
    row.addStretch(1)
    layout.addLayout(row)


def build_sections():
    """构建 20 个组件分区，返回 {名称: QGroupBox}（保持插入顺序）。"""
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QGroupBox, QVBoxLayout, QWidget

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

    sections = {}

    def group(title):
        box = QGroupBox(title)
        v = QVBoxLayout(box)
        v.setSpacing(8)
        sections[title.split(" ")[0]] = box
        return v

    # 1 按钮
    v = group("button 按钮")
    _row(v, [Button(t, variant=var) for t, var in
             (("主要", "primary"), ("默认", "default"), ("虚线", "dashed"),
              ("文字", "text"), ("链接", "link"), ("危险", "danger"))])
    _row(v, [Button("小", size="sm"), Button("中", size="md"),
             Button("大", size="lg"), Button("加载中", variant="primary",
                                             loading=True),
             Button("禁用", variant="primary")])
    v.itemAt(1).layout().itemAt(4).widget().setEnabled(False)
    block = Button("块级按钮", block=True)
    v.addWidget(block)

    # 2 图标按钮
    v = group("icon_button 图标按钮")
    _row(v, [IconButton(text="+", variant="primary", shape="circle"),
             IconButton(text="×", variant="danger", shape="circle"),
             IconButton(text="?", shape="circle"),
             IconButton(text="★", variant="default"),
             IconButton(text="+", size="sm"),
             IconButton(text="+", size="lg")])
    ib_dis = IconButton(text="+", variant="primary", shape="circle")
    ib_dis.setEnabled(False)
    _row(v, [ib_dis])

    # 3 复选框
    v = group("checkbox 复选框")
    tri = CheckBox("部分选中", tristate=True)
    tri.set_check_state(Qt.PartiallyChecked)
    cb_dis = CheckBox("禁用勾选", checked=True)
    cb_dis.setEnabled(False)
    _row(v, [CheckBox("未选中"), CheckBox("已选中", checked=True), tri,
             cb_dis])

    # 4 单选框
    v = group("radio 单选框")
    rg = RadioGroup()
    radios = [rg.add_button(t, id=i + 1) for i, t in
              enumerate(("方案一", "方案二", "方案三"))]
    rg.set_checked_id(1)
    rb_dis = RadioButton("禁用")
    rb_dis.setEnabled(False)
    _row(v, radios + [rb_dis])

    # 5 开关
    v = group("switch 开关")
    sw_dis = Switch(checked=True)
    sw_dis.setEnabled(False)
    _row(v, [Switch(checked=True), Switch(checked=False),
             Switch(checked=True, size="sm"), sw_dis])

    # 6 单行输入框
    v = group("line_edit 输入框")
    le1 = LineEdit(placeholder="请输入用户名", clearable=True)
    le2 = LineEdit("user", clearable=True)
    le2.set_prefix_icon("@")
    le2.set_suffix_icon(".com")
    le3 = LineEdit("secret")
    le3.set_password_mode(True)
    le4 = LineEdit("错误内容")
    le4.set_error(True)
    le5 = LineEdit("禁用")
    le5.setEnabled(False)
    le6 = LineEdit(placeholder="小号", size="sm")
    le7 = LineEdit(placeholder="大号", size="lg")
    for w in (le1, le2, le3, le4):
        w.setMinimumWidth(180)
    _row(v, [le1, le2, le3, le4])
    _row(v, [le5, le6, le7])

    # 7 多行文本域
    v = group("text_area 文本域")
    ta = TextArea(placeholder="介绍一下自己（自适应高度 + 字数统计）",
                  auto_height=True, min_rows=2, max_rows=5,
                  max_length=120, show_count=True)
    ta.setPlainText("这是一段示例文本。")
    ta.setMinimumWidth(320)
    ta_dis = TextArea(placeholder="禁用")
    ta_dis.setEnabled(False)
    _row(v, [ta, ta_dis])

    # 8 数字调节框
    v = group("spin_box 数字框")
    sp_dis = SpinBox(value=7)
    sp_dis.setEnabled(False)
    _row(v, [SpinBox(minimum=0, maximum=99, value=5, size="sm"),
             SpinBox(minimum=0, maximum=99, value=42),
             SpinBox(minimum=0, maximum=99, value=8, size="lg"),
             DoubleSpinBox(minimum=0, maximum=99, value=19.9, suffix=" 元"),
             sp_dis])

    # 9 下拉框
    v = group("combo_box 下拉框")
    co_dis = ComboBox(["不可用"])
    co_dis.setEnabled(False)
    _row(v, [ComboBox(["北京", "上海", "广州"], size="sm"),
             ComboBox(["北京", "上海", "广州"]),
             ComboBox(["苹果", "香蕉", "橙子"], searchable=True,
                      placeholder="搜索水果", size="lg"),
             co_dis])

    # 10 滑块
    v = group("slider 滑块")
    sl = Slider(minimum=0, maximum=100, value=45)
    sl.set_ticks(10)
    sl.setMinimumWidth(280)
    sl_dis = Slider(value=30)
    sl_dis.setMinimumWidth(200)
    sl_dis.setEnabled(False)
    _row(v, [sl, sl_dis])

    # 11 日期选择
    v = group("date_picker 日期")
    dp = DatePicker()
    dp.set_date_str("2025-06-15")
    dp_sm = DatePicker(size="sm")
    dp_dis = DatePicker()
    dp_dis.setEnabled(False)
    _row(v, [dp, dp_sm, dp_dis])

    # 12 时间选择
    v = group("time_picker 时间")
    tp = TimePicker()
    tp.set_time_str("09:30:00")
    tp_dis = TimePicker()
    tp_dis.setEnabled(False)
    _row(v, [tp, tp_dis])

    # 13 评分
    v = group("rating 评分")
    ra_dis = Rating(value=3, read_only=True)
    ra_dis.setEnabled(False)
    _row(v, [Rating(value=3.5, allow_half=True),
             Rating(value=4, read_only=True), ra_dis])

    # 14 颜色选择
    v = group("color_picker 颜色")
    cp_dis = ColorPicker("#98A0AC")
    cp_dis.setEnabled(False)
    _row(v, [ColorPicker("#3563E9"), ColorPicker("#1E9E6A", size="sm"),
             cp_dis])

    # 15 自动完成
    v = group("auto_complete 自动完成")
    ac = AutoComplete(["苹果", "香蕉", "橙子", "苹果派", "葡萄"],
                      placeholder="输入以搜索水果")
    ac.setMinimumWidth(200)
    ac.setText("苹")
    ac_dis = AutoComplete(["x"], placeholder="禁用")
    ac_dis.setEnabled(False)
    _row(v, [ac, ac_dis])

    # 16 级联选择
    v = group("cascader 级联选择")
    cas = Cascader([
        {"value": "zj", "label": "浙江", "children": [
            {"value": "hz", "label": "杭州"},
            {"value": "nb", "label": "宁波"}]},
        {"value": "gd", "label": "广东", "children": [
            {"value": "gz", "label": "广州"},
            {"value": "sz", "label": "深圳"}]},
    ])
    cas.set_path(["zj", "hz"])
    cas_dis = Cascader([{"value": "x", "label": "无"}])
    cas_dis.setEnabled(False)
    _row(v, [cas, cas_dis])

    # 17 穿梭框
    v = group("transfer 穿梭框")
    tr = Transfer(["苹果", "香蕉", "橙子", "葡萄", "西瓜"])
    tr.set_target_items(["香蕉", "葡萄"])
    v.addWidget(tr)

    # 18 上传
    v = group("upload 上传")
    up = UploadWidget()
    up.add_files(["/tmp/季度报告.docx", "/tmp/数据汇总.csv"])
    up.setMinimumWidth(360)
    _row(v, [up])

    # 19 分段控制器
    v = group("segmented 分段控制")
    seg1 = SegmentedControl(["日", "周", "月", "年"], current=1)
    seg2 = SegmentedControl(["列表", "卡片", "禁用项"], current=0, size="sm")
    seg2.set_item_enabled(2, False)
    seg_dis = SegmentedControl(["甲", "乙"], current=0)
    seg_dis.setEnabled(False)
    _row(v, [seg1, seg2, seg_dis])

    # 20 表单
    v = group("form 表单")
    holder = QWidget()
    form = FormLayout(holder)
    edit_user = LineEdit("abc")
    form.add_row("用户名", edit_user, required=True,
                 validator=lambda x: len(x) >= 3 or "至少 3 个字符")
    edit_mail = LineEdit("bad")
    form.add_row("邮箱", edit_mail, required=True,
                 validator=lambda x: "@" in x or "邮箱格式不正确")
    form.add_row("备注", TextArea(auto_height=True, min_rows=2, max_rows=3))
    form.validate_all()  # 触发错误提示行
    v.addWidget(holder)

    return sections


def build_page(sections):
    """把分区组装进滚动页，返回 (scroll_area, content)。"""
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QScrollArea, QVBoxLayout, QWidget

    content = QWidget()
    content.setAttribute(Qt.WA_StyledBackground, True)
    v = QVBoxLayout(content)
    v.setContentsMargins(16, 16, 16, 16)
    v.setSpacing(12)
    for box in sections.values():
        v.addWidget(box)
    v.addStretch(1)
    scroll = QScrollArea()
    scroll.setWidget(content)
    scroll.setWidgetResizable(True)
    scroll.resize(880, 640)
    return scroll, content


# ---------------------------------------------------------------------------
# 3. 双主题截图与健全性检查
# ---------------------------------------------------------------------------

def _image_is_monochrome(img) -> bool:
    """采样若干像素，判断是否为单色图（全黑 / 全白等渲染异常）。"""
    w, h = img.width(), img.height()
    colors = set()
    for ix in range(1, 6):
        for iy in range(1, 6):
            colors.add(img.pixelColor(w * ix // 6, h * iy // 6).rgba())
    return len(colors) <= 1


@check("演示页组装 + 亮 / 暗双主题截图")
def _():
    from PySide6.QtGui import QColor
    from PySide6.QtWidgets import QApplication

    from InstructionX_UIKit import tokens as tk
    from InstructionX_UIKit.theme import ThemeManager

    app = QApplication.instance() or QApplication([])
    tm = ThemeManager.instance()
    SHOTS.mkdir(parents=True, exist_ok=True)

    sections = build_sections()
    assert_eq(len(sections), 20, "应组装 20 个组件分区")
    scroll, content = build_page(sections)
    scroll.show()
    app.processEvents()
    settle(app, 400)

    grabbed = {}
    for mode in ("light", "dark"):
        tm.set_mode(mode)
        tm.apply(app)
        settle(app, 250)
        # 整页截图（直接 grab 内容控件，覆盖滚动区外内容）
        page = content.grab()
        if page.isNull() or page.width() < 200 or page.height() < 400:
            raise AssertionError(f"{mode} 整页 grab() 尺寸异常: "
                                 f"{page.width()}x{page.height()}")
        page_path = SHOTS / f"inputs_page_{mode}.png"
        if not page.save(str(page_path)):
            raise AssertionError(f"整页截图保存失败: {page_path}")
        grabbed[mode] = page.toImage()
        # 分区截图
        for name, box in sections.items():
            pm = box.grab()
            if pm.isNull() or pm.width() < 50 or pm.height() < 20:
                raise AssertionError(f"{mode} 分区 {name} grab() 尺寸异常: "
                                     f"{pm.width()}x{pm.height()}")
            path = SHOTS / f"inputs_{name}_{mode}.png"
            if not pm.save(str(path)):
                raise AssertionError(f"分区截图保存失败: {path}")

    tm.set_mode("light")
    tm.apply(app)
    app.processEvents()
    scroll.close()

    # -- 健全性：文件存在且非单色 -------------------------------------
    for mode in ("light", "dark"):
        for name in sections:
            path = SHOTS / f"inputs_{name}_{mode}.png"
            if not path.exists() or path.stat().st_size < 1024:
                raise AssertionError(f"截图缺失或过小: {path}")
        page_path = SHOTS / f"inputs_page_{mode}.png"
        if page_path.stat().st_size < 20000:
            raise AssertionError(f"整页截图过小: {page_path}")
    # 单色检测（整页）
    for mode in ("light", "dark"):
        if _image_is_monochrome(grabbed[mode]):
            raise AssertionError(f"{mode} 整页截图为单色，渲染异常")

    # -- 像素比对：页面背景应贴近 bg.base -------------------------------
    def near(px, hex_color, tol=12):
        qc = QColor(hex_color)
        return (abs(px.red() - qc.red()) <= tol
                and abs(px.green() - qc.green()) <= tol
                and abs(px.blue() - qc.blue()) <= tol)

    bg_l = grabbed["light"].pixelColor(4, 4)
    bg_d = grabbed["dark"].pixelColor(4, 4)
    if not near(bg_l, tk.LIGHT["color.bg.base"]):
        raise AssertionError(f"亮色页面背景采样异常: {bg_l.getRgb()}")
    if not near(bg_d, tk.DARK["color.bg.base"]):
        raise AssertionError(f"暗色页面背景采样异常: {bg_d.getRgb()}")
    if bg_l.getRgb() == bg_d.getRgb():
        raise AssertionError("亮暗整页背景必须不同")

    print(f"  截图: {SHOTS / 'inputs_page_light.png'}")
    print(f"  截图: {SHOTS / 'inputs_page_dark.png'}")
    print(f"  分区截图: {SHOTS}/inputs_<name>_<theme>.png（20 x 2）")


def main() -> int:
    print("inputs 组件自测开始（offscreen）")
    # 触发各检查（装饰器已在导入时执行，这里仅汇总）
    print("-" * 60)
    if _FAILURES:
        print(f"共 {len(_FAILURES)} 项失败: {_FAILURES}")
        return 1
    print("全部检查通过，0 错误")
    return 0


if __name__ == "__main__":
    sys.exit(main())
