# USAGE — InstructionX_UIKit 使用方法

> 本文档覆盖安装、快速开始、主题系统、全部 57 个组件、12 个布局、52 个动画预设、图表引擎与蓝图（节点图）组件的最小可运行示例。
> 所有示例均与仓库真实 API 一致；离屏验证一律使用 `QT_QPA_PLATFORM=offscreen`。

## 目录

- [1. 安装](#1-安装)
- [2. 快速开始](#2-快速开始)
- [3. 主题系统](#3-主题系统)
- [4. 组件用法](#4-组件用法)
  - [4.1 输入与按钮](#41-输入与按钮)
  - [4.2 数据展示](#42-数据展示)
  - [4.3 导航与反馈](#43-导航与反馈)
- [5. 布局用法](#5-布局用法)
- [6. 动画用法](#6-动画用法)
- [7. 图表用法（InstructionX_UIKit.charts 原生引擎）](#7-图表用法instructionx_uikitcharts-原生引擎)
- [8. 蓝图模式（InstructionX_UIKit.blueprint 节点图）](#8-蓝图模式instructionx_uikitblueprint-节点图)
- [9. 常见问题](#9-常见问题)

## 1. 安装

```bash
pip install -r requirements.txt
```

`requirements.txt` 内容：

```
PySide6>=6.6
PySide6-Addons>=6.6
qrcode[pil]>=7.4
```

仅 PySide6（>=6.6，含 Addons）与 qrcode（二维码组件用）依赖，无其他第三方库。

## 2. 快速开始

### 2.1 运行 Demo 演示

```bash
python main.py
```

Demo 入口逻辑（main.py）：创建 `QApplication` → `ThemeManager.instance().apply(app)` → 显示 1280x800 的 `MainWindow`，左侧导航含设计令牌 / 布局 / 组件 / 动画全部分页。

### 2.2 最小应用骨架

```python
import sys
from PySide6.QtWidgets import QApplication
from InstructionX_UIKit.theme import ThemeManager
from InstructionX_UIKit.components.button import Button

app = QApplication(sys.argv)
ThemeManager.instance().apply(app)          # 应用亮色主题（QSS + 字体 + 调色板）

btn = Button("确定", variant="primary", size="md")
btn.clicked.connect(lambda: print("clicked"))
btn.show()
sys.exit(app.exec())
```

要点：先建 `QApplication`，再 `apply()`，然后正常使用任何 Qt / 组件库控件即可，全局 QSS 自动生效。

## 3. 主题系统

### 3.1 模式切换

```python
from InstructionX_UIKit.theme import ThemeManager

tm = ThemeManager.instance()     # 单例
tm.set_mode("dark")              # 显式设置（"light" / "dark"）
tm.toggle()                      # 亮暗互切
print(tm.mode)                   # 当前模式
```

- `apply(app)` 之后调用 `set_mode` / `toggle` 会自动重新生成 QSS 并设置到 QApplication，所有 QSS 控件即时换肤。
- `theme_changed(str)` 信号发射 `"light"` / `"dark"`，组件库自绘控件已在内部连接；业务自绘代码也应连接它触发 `update()`：

```python
ThemeManager.instance().theme_changed.connect(lambda mode: self.update())
```

### 3.2 T() 取令牌

```python
from InstructionX_UIKit.theme import T

color = T("color.primary")       # "#3563E9"（亮）/ "#5B87F2"（暗）
gap = T("space.4")               # 16
radius = T("radius.md")          # 6
shadow = T("shadow.md")          # {"blur": 16, "offset": (0, 4), "color": (16, 24, 40, 64)}
```

### 3.3 apply_shadow 与 set_property

```python
from InstructionX_UIKit.theme import apply_shadow, set_property

apply_shadow(card, "md")         # level: "sm" / "md" / "lg"，挂 QGraphicsDropShadowEffect

set_property(button, "variant", "primary")   # 改 QSS 变体并自动 unpolish/polish
set_property(button, "size", "sm")           # 内部映射为 uiksize，规避内置 size 属性冲突
set_property(edit, "error", "true")          # 错误态红边框
```

注意：`size` 是 QWidget 内置属性，直接 `widget.setProperty("size", "sm")` 无效；务必使用 `set_property()`（详见 Design.md §11.3）。

### 3.4 设计令牌状态机（TokenState）

`T()` 只是读取；当需要**订阅**令牌变化、按类型取令牌、或做会话级调参时，
请使用 `InstructionX_UIKit.tokens.TokenState`（单例，以 ThemeManager 当前模式为源，
`set_mode` / `toggle` 时自动刷新并发射 `mode_changed`）：

```python
from InstructionX_UIKit.tokens import TokenState

ts = TokenState.instance()

# 按类型读取（所有预设令牌均可经状态机获得）
ts.value("color.primary")        # 等价 T()，但支持 default：ts.value("k", 默认值)
ts.color("color.primary")        # QColor
ts.size("space.4")               # 16（int；space./radius./font. 等数值令牌）
ts.font("title.lg", "bold")      # 按字阶 + 字重直接得到 QFont
ts.shadow("md")                  # {"blur": 16, "offset": (0, 4), "color": (...)}

# 分组导出（当前模式 dict 副本）
ts.colors() / ts.typography() / ts.spacing() / ts.radii()
ts.shadows() / ts.durations() / ts.easings() / ts.breakpoints()

# 断点状态（供响应式组件订阅）
ts.set_width(self.width())       # 窗口 resize 时调用；跨档发射 breakpoint_changed
ts.current_breakpoint            # "xs" / "sm" / "md" / "lg" / "xl"

# 信号订阅示例
ts.token_changed.connect(lambda key: print("令牌变更:", key))
ts.mode_changed.connect(lambda mode: print("模式:", mode))
ts.breakpoint_changed.connect(lambda bp: print("断点:", bp))
```

**运行时覆盖（仅当前会话）**：

```python
ts.set_token("color.primary", "#FF6600")   # 发射 token_changed；不改 LIGHT/DARK 常量
ts.reset_token("color.primary")            # 还原单个
ts.reset_all()                             # 还原全部
```

**与 QSS 的关系**：`set_token` 只改变状态机视图（`value()` / `T()` / 分组导出），
**已生成的全局 QSS 不会自动随之变化**。因此：

- 自绘组件（`paintEvent` 中用 `T()` 取色的 Switch / Rating / SegmentedControl 等）
  应监听 `token_changed` 并 `update()` 重绘——上述三个组件已内置该监听；
- 依赖 QSS 的控件若需响应覆盖，请重新 `build_qss(ts.tokens)` 并
  `app.setStyleSheet(...)`，或改用自绘 + 信号订阅的方式。

`T()` 内部即委托 `TokenState`，旧代码无需修改即可感知会话覆盖。

## 4. 组件用法

导入约定：`from InstructionX_UIKit.components.<模块> import <类>`。示例中省略 `QApplication` 骨架，实际运行请参考 §2.2。

### 4.1 输入与按钮

**Button**（`button.py`）—— 六变体按钮，支持加载态与撑满。

```python
from InstructionX_UIKit.components.button import Button
btn = Button("提交", variant="primary", size="md")  # variant: primary/default/dashed/text/link/danger；size: sm/md/lg；shape: round/circle
btn.clicked.connect(lambda: print("提交"))
btn.set_loading(True)        # 进入加载态（自绘旋转弧 + 禁用）；set_loading(False) 恢复
btn.set_block(True)          # 撑满父布局宽度
```

**IconButton**（`icon_button.py`）—— 图标按钮（QToolButton）。

```python
from InstructionX_UIKit.components.icon_button import IconButton
ib = IconButton(text="搜索", variant="default", size="md", shape="circle")
ib.set_symbol("?")           # 无 QIcon 时用文本符号；也可 set_icon(QIcon)
ib.clicked.connect(lambda: print("icon clicked"))
```

**CheckBox**（`checkbox.py`）—— 复选框，支持三态。

```python
from PySide6.QtCore import Qt
from InstructionX_UIKit.components.checkbox import CheckBox
cb = CheckBox("记住我", checked=True)
cb.stateChanged.connect(lambda s: print(Qt.CheckState(s)))
tri = CheckBox("全选", tristate=True)          # 三态；set_check_state(Qt.PartiallyChecked)
```

**RadioButton / RadioGroup**（`radio.py`）—— 单选与分组封装。

```python
from InstructionX_UIKit.components.radio import RadioButton, RadioGroup
r1, r2 = RadioButton("选项A", checked=True), RadioButton("选项B")
group = RadioGroup()
group.add_button(r1, id=1); group.add_button(r2, id=2)
group.idToggled.connect(lambda i, on: on and print("选中", i, group.checked_text()))
```

**Switch**（`switch.py`）—— 自绘滑块开关。

```python
from InstructionX_UIKit.components.switch import Switch
sw = Switch(checked=True, size="md")           # size: sm/md
sw.toggled.connect(lambda on: print("开关", on))
```

**LineEdit**（`line_edit.py`）—— 单行输入，前缀/后缀、清除、密码、错误态。

```python
from InstructionX_UIKit.components.line_edit import LineEdit
edit = LineEdit(placeholder="请输入用户名", clearable=True, size="md")
edit.textChanged.connect(print)
edit.set_error(True)                            # 校验失败：红边框；set_error(False) 恢复
pwd = LineEdit(placeholder="密码"); pwd.set_password_mode(True)   # 自带明文切换按钮
```

**TextArea**（`text_area.py`）—— 多行输入，自适应高度与字数统计。

```python
from InstructionX_UIKit.components.text_area import TextArea
ta = TextArea(placeholder="请输入简介", auto_height=True, min_rows=3, max_rows=8,
              max_length=200, show_count=True)
ta.textChanged.connect(lambda: print(ta.count()))
```

**SpinBox / DoubleSpinBox**（`spin_box.py`）—— 数字调节框。

```python
from InstructionX_UIKit.components.spin_box import SpinBox, DoubleSpinBox
sp = SpinBox(minimum=0, maximum=100, value=20, step=5, size="md")
sp.valueChanged.connect(print)
dsp = DoubleSpinBox(minimum=0.0, maximum=10.0, value=1.5, step=0.1, decimals=2, suffix=" kg")
```

**ComboBox**（`combo_box.py`）—— 下拉选择，支持搜索过滤。

```python
from InstructionX_UIKit.components.combo_box import ComboBox
combo = ComboBox(["北京", "上海", "广州"], searchable=True, placeholder="请选择城市")
combo.currentTextChanged.connect(print)
combo.set_items(["杭州", "南京"])               # 运行时替换选项
```

**Slider**（`slider.py`）—— 滑块，刻度与悬停提示值。

```python
from PySide6.QtCore import Qt
from InstructionX_UIKit.components.slider import Slider
sl = Slider(Qt.Horizontal, minimum=0, maximum=100, value=30)
sl.set_ticks(10)                                # 刻度间隔
sl.set_tip_enabled(True)                        # 拖动时显示当前值
sl.valueChanged.connect(print)
```

**DatePicker**（`date_picker.py`）—— 日期选择（自定义日历弹层）。

```python
from InstructionX_UIKit.components.date_picker import DatePicker
dp = DatePicker(size="md")                      # 默认今天；DatePicker(QDate(2025, 1, 1))
dp.dateChanged.connect(print)
print(dp.date_str())                            # "yyyy-MM-dd"
```

**TimePicker**（`time_picker.py`）—— 时间选择。

```python
from InstructionX_UIKit.components.time_picker import TimePicker
tp = TimePicker(size="md")                      # 默认当前时间
tp.timeChanged.connect(print)
print(tp.time_str())                            # "HH:mm"
```

**Rating**（`rating.py`）—— 星级评分，支持半星与只读。

```python
from InstructionX_UIKit.components.rating import Rating
rt = Rating(count=5, value=3.5, allow_half=True, star_size=20)
rt.valueChanged.connect(lambda v: print("评分", v))
rt.set_read_only(True)                          # 展示模式
```

**ColorPicker**（`color_picker.py`）—— 色块按钮 + QColorDialog。

```python
from InstructionX_UIKit.components.color_picker import ColorPicker
cp = ColorPicker(color="#3563E9", size="md", show_text=True)
cp.colorChanged.connect(lambda c: print(c.name()))
```

**AutoComplete**（`auto_complete.py`）—— 输入补全（QCompleter 封装，延迟过滤）。

```python
from InstructionX_UIKit.components.auto_complete import AutoComplete
ac = AutoComplete(["apple", "banana", "cherry"], placeholder="输入水果名", delay=200)
ac.set_items(["apricot", "blueberry"])         # 更新候选
```

**Cascader**（`cascader.py`）—— 级联选择。

```python
from InstructionX_UIKit.components.cascader import Cascader
cas = Cascader(options=[
    {"value": "zj", "label": "浙江", "children": [
        {"value": "hz", "label": "杭州"}, {"value": "nb", "label": "宁波"}]},
    {"value": "js", "label": "江苏", "children": [{"value": "nj", "label": "南京"}]},
], placeholder="请选择地区")
cas.pathChanged.connect(lambda path: print("选中路径", path, cas.labels()))
```

**Transfer**（`transfer.py`）—— 穿梭框。

```python
from InstructionX_UIKit.components.transfer import Transfer
tf = Transfer(items=["苹果", "香蕉", "橙子", "葡萄"], source_title="可选", target_title="已选")
tf.changed.connect(lambda targets: print("目标列表", targets))
tf.set_target_items(["苹果"])
```

**UploadWidget**（`upload.py`）—— 拖拽上传。

```python
from InstructionX_UIKit.components.upload import UploadWidget
up = UploadWidget(hint="拖拽文件到此处，或点击选择文件", button_text="选择文件")
up.filesChanged.connect(lambda files: print("当前文件", files))
up.remove_file("/tmp/a.txt")                    # 编程移除；clear() 清空
```

**SegmentedControl**（`segmented.py`）—— 分段控制器。

```python
from InstructionX_UIKit.components.segmented import SegmentedControl
seg = SegmentedControl(["日", "周", "月"], current=1, size="md")
seg.currentChanged.connect(lambda i: print("切到", seg.current_text()))
```

**FormLayout / FormItem**（`form.py`）—— 表单布局与校验。

```python
from InstructionX_UIKit.components.form import FormLayout
from InstructionX_UIKit.components.line_edit import LineEdit
form = FormLayout()
name = LineEdit(placeholder="必填")
form.add_row("姓名", name, required=True,
             validator=lambda v: len(v) >= 2 or "姓名至少 2 个字符")  # 校验器收字段值，返回 True/None 通过，返回字符串为错误信息
form.validate_all()                             # 全部校验，失败项显示红字错误行
```

### 4.2 数据展示

**Avatar**（`avatar.py`）—— 头像：图片 / 文字 / 图标回退。

```python
from InstructionX_UIKit.components.avatar import Avatar
av = Avatar(text="小明", size="md", shape="circle")   # size: sm(24)/md(32)/lg(40) 或像素 int；shape: circle/square
av.set_image("user.png")        # 传路径或 QPixmap；加载失败回退文字
av.set_icon(icon)               # 再次回退为图标
```

**Badge**（`badge.py`）—— 徽标角标。

```python
from InstructionX_UIKit.components.badge import Badge
from InstructionX_UIKit.components.button import Button
badge = Badge(Button("消息"), count=8, max_count=99)   # 超过 max 显示 "99+"
badge.set_count(100)
dot = Badge(Button("设置"), dot=True, color="danger")  # 独立红点模式
```

**Card**（`card.py`）—— 卡片容器。

```python
from InstructionX_UIKit.components.card import Card
from PySide6.QtWidgets import QLabel
card = Card(title="账户概览", bordered=True, hoverable=True)
card.set_extra(Button("更多", variant="link"))         # 右上角操作区
card.set_widget(QLabel("内容区"))                      # 也可 card.body_layout().addWidget(...)
card.set_footer(QLabel("更新于今天"))
```

**Descriptions**（`descriptions.py`）—— 描述列表，列数自适应。

```python
from InstructionX_UIKit.components.descriptions import Descriptions
desc = Descriptions(title="用户信息", column=2, bordered=True)   # column=0 按宽度自适应
desc.set_items([("姓名", "张三"), ("城市", "杭州"), ("角色", "管理员")])
desc.add_item("注册时间", "2025-01-01")
```

**ListWidget**（`list_view.py`）—— 统一项高列表。

```python
from InstructionX_UIKit.components.list_view import ListWidget
lw = ListWidget(item_height=36)
lw.add_item("收件箱"); lw.add_items(["星标", "草稿箱"])
lw.currentTextChanged.connect(print)
```

**Table**（`table.py`）—— 表格：斑马纹、排序、空状态。

```python
from InstructionX_UIKit.components.table import Table
tb = Table(sortable=True)
tb.set_data(["姓名", "分数"], [["张三", 90], ["李四", 86]])
tb.set_empty_text("暂无数据")
tb.cellClicked.connect(lambda r, c: print(r, c))
```

**Tree**（`tree.py`）—— 树：缩进线、复选。

```python
from InstructionX_UIKit.components.tree import Tree
tree = Tree(checkable=True, indent_lines=True)
tree.set_data([("水果", [("苹果", []), ("香蕉", [])]), ("蔬菜", [("白菜", [])])])
tree.expand_all()
tree.itemClicked.connect(lambda item, col: print(item.text(0)))
```

**Timeline**（`timeline.py`）—— 时间轴。

```python
from InstructionX_UIKit.components.timeline import Timeline
tl = Timeline(pending="进行中...")
tl.add_item("创建订单", time="09:30")
tl.add_item("支付成功", time="09:35", color="success")   # color: primary/success/warning/danger
tl.add_item("发货", time="10:00", color="primary")
```

**Statistic**（`statistic.py`）—— 统计数值卡。

```python
from InstructionX_UIKit.components.statistic import Statistic
st = Statistic(title="今日营收", value=12800, precision=0)
st.set_prefix("¥"); st.set_suffix("元")
st.set_trend(12.5)            # >=0 绿色上升箭头；<0 红色下降；clear_trend() 清除
```

**Calendar**（`calendar.py`）—— 日历（中文表头、周一为首日）。

```python
from InstructionX_UIKit.components.calendar import Calendar
cal = Calendar()
cal.clicked.connect(lambda d: print(d.toString("yyyy-MM-dd")))
```

**Carousel**（`carousel.py`）—— 走马灯。

```python
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel
from InstructionX_UIKit.components.carousel import Carousel
car = Carousel(autoplay=3000)               # 自动播放间隔 ms；0 关闭
car.add_page(QLabel("第一屏", alignment=Qt.AlignCenter))
car.add_page(QLabel("第二屏", alignment=Qt.AlignCenter))
car.go_to(0); car.next(); car.prev()
```

**ImageView**（`image_view.py`）—— 圆角图片，失败占位、hover 预览。

```python
from InstructionX_UIKit.components.image_view import ImageView
iv = ImageView(source="banner.png", radius=8)   # 路径不存在时显示占位插画
iv.clicked.connect(lambda: print("预览"))
iv.set_source("other.png")
```

**QRCodeView**（`qrcode_view.py`）—— 二维码（qrcode 库）。

```python
from InstructionX_UIKit.components.qrcode_view import QRCodeView
qr = QRCodeView(text="https://example.com", size=128, error_correction="M")  # L/M/Q/H
qr.set_text("https://example.org")
qr.to_pixmap().save("qr.png")
```

**CommentView**（`comment.py`）—— 评论，可嵌套回复。

```python
from InstructionX_UIKit.components.comment import CommentView
cm = CommentView(author="张三", content="写得很好", time="5 分钟前", actions=["回复", "赞"])
cm.action_triggered.connect(lambda name: print("操作", name))
cm.add_reply(CommentView(author="李四", content="谢谢", time="刚刚"))
```

**Collapse**（`collapse.py`）—— 折叠面板。

```python
from InstructionX_UIKit.components.collapse import Collapse
from PySide6.QtWidgets import QLabel
col = Collapse(accordion=True)                       # 手风琴：同时仅展开一个
col.add_panel("基础信息", QLabel("姓名 / 城市"), expanded=True)
col.add_panel("高级设置", QLabel("..."))
col.panel_toggled.connect(lambda i, expanded: print(i, expanded))
```

**Empty**（`empty.py`）—— 空状态。

```python
from InstructionX_UIKit.components.empty import Empty
em = Empty(description="暂无搜索结果")
em.set_action("重新加载", callback=lambda: print("reload"))
```

**set_tooltip**（`tooltip.py`）—— 富样式工具提示。

```python
from InstructionX_UIKit.components.tooltip import set_tooltip
set_tooltip(button, "快捷键 Ctrl+S", title="保存")   # title 可选；全局 QSS 已统一 QToolTip 样式
```

**Popover**（`popover.py`）—— 气泡卡片。

```python
from InstructionX_UIKit.components.popover import Popover
from PySide6.QtWidgets import QLabel
pop = Popover(title="筛选", content=QLabel("条件区域"))
pop.show_for(anchor_button, placement="bottom")    # top/bottom/left/right，空间不足自动翻转
```

### 4.3 导航与反馈

**Tabs**（`tabs.py`）—— 标签页：line / card / segmented 三种样式。

```python
from PySide6.QtWidgets import QLabel
from InstructionX_UIKit.components.tabs import Tabs
tabs = Tabs(variant="line")                        # line/card/segmented
tabs.addTab(QLabel("页一"), "概览"); tabs.addTab(QLabel("页二"), "明细")
tabs.currentChanged.connect(print)
```

**Anchor**（`anchor.py`）—— 锚点导航，配合 QScrollArea 高亮。

```python
from InstructionX_UIKit.components.anchor import Anchor
anchor = Anchor()
anchor.add_item("base", "基础", target=section_base)   # key / 标题 / 目标控件
anchor.add_item("adv", "高级", target=section_adv)
anchor.bind_scroll_area(scroll_area)                   # 滚动时自动高亮当前段
anchor.currentChanged.connect(lambda key: print("当前锚点", key))
```

**Breadcrumb**（`breadcrumb.py`）—— 面包屑。

```python
from InstructionX_UIKit.components.breadcrumb import Breadcrumb
bc = Breadcrumb(["首页", "商品", "详情"], separator="/")
bc.itemClicked.connect(lambda index, text: print("点击", index, text))
```

**DropdownButton**（`dropdown.py`）—— 下拉菜单按钮。

```python
from InstructionX_UIKit.components.dropdown import DropdownButton
dd = DropdownButton("更多操作")
dd.add_item("edit", "编辑", shortcut="Ctrl+E", callback=lambda: print("编辑"))
dd.add_item("del", "删除", danger=True)
dd.add_separator()
dd.triggered.connect(lambda key: print("菜单", key))
```

**NavMenu**（`nav_menu.py`）—— 侧边导航菜单。

```python
from InstructionX_UIKit.components.nav_menu import NavMenu
nav = NavMenu()
nav.add_group("控制台"); nav.add_item("dash", "仪表盘", group="控制台")
nav.add_item("set", "设置")                            # 顶层项
nav.set_current("dash")
nav.currentChanged.connect(lambda key: print("导航", key))
```

**PageHeader**（`page_header.py`）—— 页头。

```python
from InstructionX_UIKit.components.page_header import PageHeader
from InstructionX_UIKit.components.button import Button
ph = PageHeader(title="订单详情", subtitle="ORD-2025-0001", show_back=True)
ph.set_breadcrumb(["首页", "订单", "详情"])
ph.add_action(Button("导出", variant="default"))
ph.backClicked.connect(lambda: print("返回"))
```

**Pagination**（`pagination.py`）—— 分页。

```python
from InstructionX_UIKit.components.pagination import Pagination
pg = Pagination(total=235, page_size=10, current=1)
pg.set_show_jumper(True)
pg.set_show_size_changer(True, options=[10, 20, 50])
pg.currentChanged.connect(lambda p: print("页码", p))
pg.pageSizeChanged.connect(lambda s: print("每页", s))
```

**Steps**（`steps.py`）—— 步骤条。

```python
from PySide6.QtCore import Qt
from InstructionX_UIKit.components.steps import Steps
steps = Steps(orientation=Qt.Horizontal)
steps.set_steps(["填写信息", "确认订单", {"title": "支付", "description": "扫码或刷卡"}])
steps.set_current(1)                  # 之前自动 finish，当前 process，之后 wait
steps.set_status(2, "error")          # wait/process/finish/error
```

**Alert**（`alert.py`）—— 警告提示条。

```python
from InstructionX_UIKit.components.alert import Alert
al = Alert(type="warning", title="注意", description="磁盘空间不足 10%", closable=True)
al.add_action("去清理", callback=lambda: print("clean"))
al.closed.connect(lambda: print("已关闭"))
```

**Dialog**（`dialog.py`）—— 统一对话框。

```python
from PySide6.QtWidgets import QLabel
from InstructionX_UIKit.components.dialog import Dialog
Dialog.confirm(window, "删除确认", "删除后不可恢复，是否继续？",
               on_result=lambda ok: print("结果", ok))        # 非阻塞
Dialog.info(window, "提示", "保存成功", on_close=lambda: print("closed"))
dlg = Dialog(window, title="自定义"); dlg.set_content(QLabel("任意内容")); dlg.open()
```

**Drawer**（`drawer.py`）—— 抽屉。

```python
from PySide6.QtWidgets import QLabel
from InstructionX_UIKit.components.drawer import Drawer
dr = Drawer(window, position="right", size=360, title="详情", resizable=True)
dr.set_content(QLabel("抽屉内容"))
dr.open()                                     # 滑入动画；close() 滑出
```

**Notification**（`notification.py`）—— 右上角通知提醒。

```python
from InstructionX_UIKit.components.notification import Notification
Notification.notify(window, "构建完成", "耗时 32 秒", type="success", duration=4000)
Notification.error(window, "构建失败", "见第 3 个错误")     # info/success/warning/error 便捷方法
Notification.close_all()
```

**Message**（`message.py`）—— 顶部居中轻提示。

```python
from InstructionX_UIKit.components.message import Message
Message.show(window, "已保存", type="success", duration=2000)
Message.info(window, "正在同步"); Message.warning(window, "网络较慢")
Message.error(window, "提交失败")
```

**Popconfirm**（`popconfirm.py`）—— 气泡确认框。

```python
from InstructionX_UIKit.components.popconfirm import Popconfirm
pc = Popconfirm.confirm(del_button, "确认删除该记录？",
                        on_result=lambda ok: print("确认" if ok else "取消"))
pc.confirmed.connect(lambda: print("do delete"))          # 也可连信号
```

**ResultView**（`result.py`）—— 结果页。

```python
from InstructionX_UIKit.components.result import ResultView
rv = ResultView(status="404", title="页面不存在", subtitle="请检查地址是否正确")
rv.add_action("返回首页", callback=lambda: print("home"), variant="primary")
# status: success / error / info / warning / 404
```

**Skeleton**（`skeleton.py`）—— 骨架屏。

```python
from InstructionX_UIKit.components.skeleton import Skeleton
sk = Skeleton(avatar=True, title=True, rows=3, button=True, active=True)  # active: 微光动画
sk.stop(); sk.start()                          # 数据到达后 setVisible(False) 换真实内容
```

**Spinner**（`spinner.py`）—— 加载指示器。

```python
from InstructionX_UIKit.components.spinner import Spinner
sp = Spinner(size="md", tip="加载中...")       # size: sm(16)/md(24)/lg(32)
sp.set_spinning(False)                         # 暂停（等价 stop()）；start() 恢复
```

**ProgressBar / CircleProgress**（`progress_bar.py`）—— 进度。

```python
from InstructionX_UIKit.components.progress_bar import ProgressBar, CircleProgress
pb = ProgressBar(value=40, status="normal")    # status: normal/success/warning/error
pb.set_status("success"); pb.set_show_info(True)
cp = CircleProgress(value=75, width=110, stroke=8, status="normal")
cp.valueChanged.connect(lambda v: print(v)); cp.set_value(90)
```

**Tour**（`tour.py`）—— 漫游式引导。

```python
from InstructionX_UIKit.components.tour import Tour
tour = Tour(window)                            # 以窗口为父控件，全屏遮罩
tour.add_step(search_button, "搜索", "在此输入关键字")
tour.add_step(nav_menu, "导航", "从这里进入各模块")
tour.finished.connect(lambda: print("完成")); tour.skipped.connect(lambda: print("跳过"))
tour.start()
```

## 5. 布局用法

每个布局模块提供 `create_xxx(...) -> QWidget` 工厂函数，并导出同名 `QWidget` 子类可直接实例化；全部在 `resizeEvent` 中按断点响应（行为见 Design.md §7.2）。

**布局为 API 驱动、不含任何假数据**：内容（卡片 / 条目 / 文案 / 内容区控件）全部由调用方传入；不传内容时显示优雅的空占位（「在此放置内容」）。运行期可用 `set_items(...)` / `set_content(...)` 更换内容。示例内容见 Demo 的 `demo/pages/layout_samples.py`。

```python
from InstructionX_UIKit.layouts.top_nav_bar import create_top_nav_bar, TopNavBar
w = create_top_nav_bar(           # 工厂函数：内容全部参数化
    brand="控制台",
    menu_items=["首页", "产品", "文档"],
    search_placeholder="搜索文档、组件...",
    cards=[("功能模块一", "模块说明。", "color.primary.subtle")],
)
w = TopNavBar()                   # 不传内容：结构 + 空占位
```

各布局内容参数一览：

| 布局 | 内容参数 |
|---|---|
| `create_top_nav_bar(...)` | `brand` / `menu_items` / `search_placeholder` / `user_text` / `title` / `subtitle` / `cards=[(标题, 描述, 色块键)]` |
| `create_holy_grail(...)` | `title` / `nav_items` / `header_actions` / `footer_note` / `status` / `center=widget` / `side=widget` |
| `create_card_grid(...)` | `items=[(标题, 描述, 色块键)]`（或 QWidget）；`set_items()` |
| `create_single_column(...)` | `kicker` / `title` / `subtitle` / `cover_key` / `paragraphs` / `quote` / `actions=[(文本, variant)]` |
| `create_sidebar_layout(...)` | `brand` / `nav_items=[(图标名, 文本)]` / `content=widget`；`set_content()` |
| `create_master_detail(...)` | `items=[(标题, 摘要, 正文)]` / `title` / `actions`；`set_items()` |
| `create_split_panel(...)` | `nav_items` / `list_items` / `content=widget`；`set_content()` |
| `create_dashboard_grid(...)` | `cards=[QWidget × 9]`（依次占 3/3/3/3/8/4/6/6/12 列跨度）；`set_cards()` |
| `create_hero_section(...)` | `kicker` / `title` / `subtitle` / `primary_text` / `secondary_text` / `hint` / `illustration` |
| `create_centered_container(...)` | `title` / `subtitle` / `actions` / `cards=[(标题, 描述, 色块键)]` / `note` |
| `create_waterfall(...)` | `items=[(标题, 色块键, 档位2-6[, 元信息])]`（或 QWidget） |
| `create_media_left_right(...)` | `sections=[(标题, 正文, 色块键)]` / `link_text` |

| 函数 | 适用场景 |
|---|---|
| `create_top_nav_bar()` | 应用级顶栏：Logo + 菜单 + 搜索 + 头像，窄断点菜单折叠为「更多」 |
| `create_holy_grail()` | 经典后台框架：头 / 尾 / 双侧栏 / 主区，QSplitter 可拖拽调宽 |
| `create_card_grid()` | 卡片列表页：按断点 1/2/3/4 列重排 |
| `create_single_column()` | 阅读 / 表单页：限宽 760 居中，垂直节奏统一 |
| `create_sidebar_layout()` | 左侧导航 + 右侧内容，窄断点折叠为图标栏 |
| `create_master_detail()` | 列表-详情页：左列表右详情，窄断点垂直堆叠 |
| `create_split_panel()` | 多栏工作台：QSplitter 2-3 栏并记忆比例 |
| `create_dashboard_grid()` | 仪表盘：12 列网格，卡片跨 3/4/6/12 |
| `create_hero_section()` | 首页英雄区：大标题 + 副文案 + 双按钮 + 插图占位 |
| `create_centered_container()` | 内容限宽 960 的居中容器页 |
| `create_waterfall()` | 瀑布流：2-4 列不等高卡片 |
| `create_media_left_right()` | 产品介绍页：图左文右 / 图右文左交替段落 |

## 6. 动画用法

### 6.1 属性类动画（`InstructionX_UIKit/anim/property.py`，28 个预设）

统一约定：`from InstructionX_UIKit.anim import property as animp`，调用即启动并返回动画句柄（已 parent 到目标，可 `stop()`）；公共参数 `duration`（ms 或 DURATION 键名）、`easing`（QEasingCurve.Type 或 EASING 键名）、`loops`。

```python
from InstructionX_UIKit.anim import property as animp
animp.fade_in(widget)                                   # 透明度 0→1（normal/standard）
animp.fade_out(widget, hide=True)                       # 淡出后 setVisible(False)
animp.slide_in(panel, direction="right", distance=120)  # 从右侧滑入（建议无活动布局）
animp.zoom_in(dialog_card, from_scale=0.85)             # 缩放进入 + 淡入
animp.spring_pop(badge)                                 # OutBack 弹性弹出
animp.badge_pop(unread_badge)                           # 角标从 0 弹入
animp.stagger_in(card_box, interval=80)                 # 子控件依次淡入上移
animp.blur_in(hero_image, radius=24)                    # 模糊→清晰
animp.mask_reveal(banner, direction="circle")           # 遮罩揭示：right/left/down/up/circle
animp.hover_lift(card, dy=4)                            # 悬停上浮 + 阴影（装事件过滤器）
h = animp.button_morph_loading(submit_btn); h.restore() # 按钮收缩为方块呼吸；restore() 还原
animp.ripple(primary_btn)                               # 点击涟漪叠加层
animp.switch_toggle(switch_btn)                         # 按压回弹 + 切换选中态
animp.pulse(icon, loops=3)                              # 心跳缩放
animp.bounce(ok_icon)                                   # 弹跳（OutBounce）
animp.swing(bell_icon, angle=12)                        # 摇摆衰减
animp.shake(password_edit)                              # 水平抖动（表单错误反馈）
animp.flash_highlight(row, times=2)                     # 高亮闪烁（默认 warning 色）
animp.float_loop(tip_card)                              # 无限上下漂浮
animp.pulse_glow(avatar)                                # 阴影半径呼吸（辉光）
animp.breathing(tip_label)                              # 透明度呼吸
animp.gradient_flow(panel, colors=["#3563E9", "#1E9E6A"])  # 背景渐变流动
animp.gradient_text_flow(title_label)                   # 文字逐字渐变流动
animp.cross_fade(stacked, index=1)                      # 页面交叉淡化（或 a 淡出 b 淡入）
animp.page_transition(stacked, 1, kind="slide")         # QStackedWidget 切页 fade/slide
animp.slide_transition(panel_a, to=panel_b)             # 两控件间滑动过渡
animp.container_morph(card, size=(320, 200), radius=12) # 尺寸/圆角变形
animp.shared_element(thumb, to_widget=detail_slot)      # 共享元素从 A 几何飞到 B
```

### 6.2 自绘类动画（`InstructionX_UIKit/anim/painted.py`，24 个控件）

统一约定：`from InstructionX_UIKit.anim.painted import Xxx`，都是主题感知的 QWidget 子类，构造即运行（部分有 `start()/stop()`）。

```python
from InstructionX_UIKit.anim.painted import SpinnerArc, LikeBurstButton, MagneticButton, CheckDraw
from InstructionX_UIKit.anim.painted import BouncingDots, SkeletonShimmer, Shimmer, ProgressStriped
from InstructionX_UIKit.anim.painted import ParallaxArea, ScrollReveal, HorizontalScrollStrip, StickyHeader
from InstructionX_UIKit.anim.painted import ScrollProgressBar, ScrollStoryArea, MarqueeLabel, FluidBackground
from InstructionX_UIKit.anim.painted import TypewriterLabel, TextDecodeLabel, NumberRollLabel
from InstructionX_UIKit.anim.painted import LetterStaggerLabel, CardTilt, CubeRotator, FlipCard, CoverFlow

SpinnerArc(size=32, speed=10.0)                          # 旋转圈加载
LikeBurstButton(size=44)                                 # 点赞心形 + 粒子爆裂
MagneticButton(text="hover 我", max_offset=8.0)          # 磁吸跟随鼠标
ck = CheckDraw(size=28); ck.start()                      # 对勾逐笔描绘；start() 重播
BouncingDots(count=3, diameter=8)                        # 跳动的点（输入中暗示）
SkeletonShimmer()                                        # 骨架屏微光扫过
Shimmer(overlay=True)                                    # 任意区域微光（可作覆盖层）
ProgressStriped(value=0.6, height=10)                    # 条纹流动进度条
pa = ParallaxArea(); pa.addLayer(label, factor=0.5)      # 视差滚动容器，factor 越小越慢
ScrollReveal(content=page, threshold=0.85)               # 子控件入视口渐显
HorizontalScrollStrip(items=["苹果", "香蕉", "橙子"])      # 横向无缝循环（字符串或控件），悬停暂停
sh = StickyHeader(); sh.setHeaderWidget(bar); sh.setBody(body, cover_height=120)  # 粘性固定头
ScrollProgressBar(area=scroll_area, height=4)            # 滚动进度条
st = ScrollStoryArea(); st.addStep("第一步", "准备环境")   # 滚动驱动叙事时间线
MarqueeLabel(text="很长很长的公告文本", speed=1.6)        # 跑马灯
FluidBackground(colors=["#3563E9", "#1E9E6A"], blobs=3)  # 流体渐变背景
TypewriterLabel(text="逐字打出这段话", interval=60)       # 打字机
TextDecodeLabel(text="解码这段文字")                      # 乱码→明文解码
nr = NumberRollLabel(value=0, decimals=0, prefix="¥"); nr.setValue(12800)   # 数字滚动 count-up
LetterStaggerLabel(text="逐字进场标题")                   # 字符依次淡入上浮
CardTilt(content=card, max_angle=10.0)                   # 鼠标 3D 透视倾斜
CubeRotator(front="正面", side="侧面")                    # 立方体两面旋转
FlipCard(front="正面", back="背面")                       # 点击翻转 180°；flip() 编程翻转
CoverFlow(items=["一月", "二月", "三月", "四月", "五月"])   # 立体透视轮播（条目标题）
```

## 7. 图表用法（InstructionX_UIKit.charts 原生引擎）

`InstructionX_UIKit.charts` 是类 ECharts 的原生图表引擎：**纯 QPainter 自绘，无 WebView / 无 JS、无 QtCharts 依赖**，主题感知（亮 / 暗切换自动换肤），全部 option 经 `T()` 实时取令牌配色。Demo「图表」页（`demo/pages/charts.py`）对 21 个系列、4 个坐标系与全部组件各配了可交互演示卡，以下示例均提取自该演示页，可直接运行。

### 7.1 快速上手

```python
from InstructionX_UIKit.charts import ChartWidget

chart = ChartWidget(parent)
chart.set_option({                          # 全量设置（ECharts 风格 dict）
    "title": {"text": "月度销量"},
    "tooltip": {"trigger": "axis"},
    "legend": {"show": True},               # 点击图例切换系列显隐
    "xAxis": {"type": "category", "data": ["1月", "2月", "3月", "4月", "5月", "6月"]},
    "yAxis": {"type": "value", "name": "件"},
    "series": [
        {"type": "bar", "name": "线下门店", "data": [120, 132, 101, 134, 156, 230],
         "stack": "总量", "barWidth": 0.6, "barBorderRadius": 3},
        {"type": "bar", "name": "线上商城", "data": [220, 182, 191, 234, 290, 330],
         "stack": "总量", "barWidth": 0.6, "barBorderRadius": 3},
    ],
})
chart.update_option({"series": [{"data": [130, 120, 150, 160, 170, 240]}]})  # 深合并 + 旧→新动画
```

- `set_option(option)`：全量替换并播放入场动画；`update_option(option)`：dict 深合并、list 替换，数据变化自动插值过渡。
- `chart.option()` 取当前 option 拷贝；`chart.anim.set_progress(1.0)` 直接跳到动画末帧（截图 / 测试用）。
- 配色：默认调色板实时取主题令牌（`color.primary / success / warning / danger / …`）；option 顶层 `"color": ["#...", ...]` 可覆盖。
- 通用键：`title`（text/subtext/left）、`legend`（show/orient）、`tooltip`（trigger: item/axis）、`grid`（left/right/top/bottom 边距）。

### 7.2 直角坐标系列（grid / 平行 / 日历）

```python
# line 折线：smooth / areaStyle / step / showSymbol / lineStyle
{"type": "line", "name": "北京", "smooth": True, "areaStyle": {"opacity": 0.18},
 "data": [2, 5, 11, 19, 25, 29, 31, 30, 26, 19, 10, 4]}

# pictorialBar 象形柱：symbol(rect/circle/pin) / symbolRepeat / symbolSize
{"type": "pictorialBar", "name": "年降雨量", "symbol": "circle",
 "symbolRepeat": True, "symbolSize": 12, "data": [580, 1200, 1800, 1950, 1450, 950]}

# scatter 散点：symbolSize 固定值，或数据带第三维时按第三维 6~24px 映射
{"type": "scatter", "name": "城市天气样本",
 "data": [[25.3, 62.0, 80], [31.2, 78.5, 42]]}        # [气温, 湿度, AQI]

# effectScatter 涟漪散点：QTimer 驱动扩散圆
{"type": "effectScatter", "name": "热门签到城市", "symbolSize": 12,
 "rippleEffect": {"period": 3, "scale": 2.6}, "data": [[116, 40], [121, 31]]}

# candlestick K线（OHLC，红涨绿跌，colorUp/colorDown 可覆盖）
{"type": "candlestick", "name": "示例股价",
 "data": [[12.0, 13.2, 11.5, 13.8], [13.2, 12.6, 12.1, 13.9]]}   # [开, 收, 低, 高]

# boxplot 箱线：[min, Q1, 中位, Q3, max]
{"type": "boxplot", "name": "加班工时", "data": [[4.2, 8.5, 12.0, 18.3, 30.1]]}

# heatmap 热力（grid）：[x下标, y下标, 值]；配合顶层 visualMap 或默认主题色带
{"xAxis": {"type": "category", "data": ["8时", "10时", "12时"]},
 "yAxis": {"type": "category", "data": ["周一", "周二"]},
 "visualMap": {"min": 0, "max": 120, "inRange": {"colors": ["#EBEFF5", "#3F5E8C"]},
               "orient": "vertical"},
 "series": [{"type": "heatmap", "name": "客流量",
             "data": [[0, 0, 58], [1, 0, 96], [2, 1, 77]]}]}

# heatmap 热力（日历）：coordinateSystem: "calendar"，数据 [日期, 值]
{"calendar": {"year": 2026, "cellSize": "auto"},
 "series": [{"type": "heatmap", "name": "代码提交", "coordinateSystem": "calendar",
             "data": [["2026-01-05", 3], ["2026-06-01", 9], ["2026-12-31", 5]]}]}

# parallel 平行坐标：parallelAxis 定义维度，每行数据一条折线穿轴
{"parallelAxis": [{"name": "语文", "min": 40, "max": 100}, {"name": "数学"}],
 "series": [{"type": "parallel", "name": "学生成绩",
             "data": [[82, 90], [66, 78]]}]}

# themeRiver 主题河：[[时间, 值, 系列名], ...]，流带平滑 + 居中基线
{"series": [{"type": "themeRiver", "name": "话题热度",
             "data": [["2026-01", 16, "新机发布"], ["2026-01", 24, "系统更新"],
                      ["2026-02", 22, "新机发布"], ["2026-02", 18, "系统更新"]]}]}
```

### 7.3 层级占比系列

```python
# pie 饼 / 环形 / 南丁格尔玫瑰；label.position: outside/inside/center（中心总计）
{"type": "pie", "name": "部门预算", "radius": ["42%", "72%"], "roseType": "radius",
 "label": {"show": True, "position": "outside"},
 "data": [{"name": "研发", "value": 420}, {"name": "市场", "value": 260}]}

# radar 雷达：indicator 定义维度，多系列各一个多边形
{"type": "radar", "name": "产品评估", "shape": "polygon", "splitNumber": 5,
 "indicator": [{"name": "功能", "max": 100}, {"name": "性能", "max": 100}],
 "areaStyle": {"opacity": 0.22},
 "data": [{"name": "本季度", "value": [82, 90]}, {"name": "上季度", "value": [70, 78]}]}

# gauge 仪表盘：min/max、progress 进度弧、axisLine 分段色、pointer、detail
{"type": "gauge", "name": "季度目标完成率", "min": 0, "max": 100,
 "data": [{"name": "完成率", "value": 72}],
 "progress": {"show": True, "width": 10},
 "axisLine": {"lineStyle": {"width": 10, "color": [[0.6, "#3FA46A"], [1.0, "#E64545"]]}},
 "pointer": {"show": True, "length": "62%"}, "detail": {"show": True}}

# funnel 漏斗：sort / gap / label.position(outer/inside)
{"type": "funnel", "name": "注册转化", "sort": "descending", "gap": 2,
 "data": [{"name": "访问落地页", "value": 100}, {"name": "点击注册", "value": 64}]}

# sunburst 旭日：层级 data，value 缺省累计子级
{"type": "sunburst", "name": "营收构成", "radius": ["18%", "92%"],
 "label": {"show": True, "minAngle": 8},
 "data": [{"name": "硬件", "children": [{"name": "手机", "value": 46},
                                        {"name": "平板", "value": 22}]}]}

# treemap 矩形树图（squarified）：breadcrumb / gapWidth / label
{"type": "treemap", "name": "存储占用", "gapWidth": 1, "breadcrumb": {"show": True},
 "data": [{"name": "视频", "children": [{"name": "电影", "value": 46}]},
          {"name": "应用", "value": 24}]}
```

### 7.4 关系流向系列

```python
# tree 树图：orient(LR/TB)、edge(polyline/curve)、symbolSize
{"type": "tree", "name": "组织架构", "orient": "LR", "edge": "polyline",
 "data": [{"name": "总经理", "children": [{"name": "技术中心",
           "children": [{"name": "前端组"}, {"name": "后端组"}]}]}]}

# sankey 桑基：nodes/links（source/target 为名称或下标）
{"type": "sankey", "name": "能源流向", "nodeWidth": 14, "nodeGap": 10,
 "data": [{"name": "煤炭"}, {"name": "工业"}, {"name": "居民"}],
 "links": [{"source": "煤炭", "target": "工业", "value": 46},
           {"source": "煤炭", "target": "居民", "value": 12}]}

# graph 关系图：layout(force/circular)，force 可设 repulsion/seed
{"type": "graph", "name": "知识图谱", "layout": "force",
 "force": {"repulsion": 1.0, "seed": 42}, "symbolSize": 14, "label": {"show": True},
 "data": [{"name": "芯片"}, {"name": "手机"}],
 "links": [{"source": "芯片", "target": "手机"}]}

# lines 线图（grid 直角坐标下）：coords 起终点对；trailEffect 移动亮点
{"xAxis": {"type": "value", "name": "经度"}, "yAxis": {"type": "value", "name": "纬度"},
 "series": [{"type": "lines", "name": "热门航线",
             "lineStyle": {"width": 2, "curveness": 0.2},
             "trailEffect": {"show": True, "period": 4, "symbolSize": 5},
             "data": [{"coords": [[116.4, 39.9], [121.5, 31.2]]}]}]}
```

### 7.5 坐标系

除默认 grid 外还有三个坐标系，系列用 `coordinateSystem` 挂接：

```python
# polar 极坐标：angleAxis（类别/数值）+ radiusAxis
{"polar": {"shape": "polygon"},
 "angleAxis": {"type": "category", "data": ["北", "东北", "东", "东南"]},
 "radiusAxis": {"type": "value"},
 "series": [{"type": "line", "name": "风向频率", "coordinateSystem": "polar",
             "areaStyle": {"opacity": 0.2},
             "data": [["北", 12], ["东北", 8], ["东", 15], ["东南", 22]]}]}

# singleAxis 单轴：一行数值轴，系列在其上排布
{"singleAxis": {"left": 40, "right": 40, "name": "分数"},
 "series": [{"type": "scatter", "name": "期末成绩分布",
             "coordinateSystem": "singleAxis", "symbolSize": 10,
             "data": [62.5, 75.0, 88.5, 91.0]}]}

# calendar 日历：GitHub 式年历网格（行=星期，列=周）
{"calendar": {"year": 2026, "cellSize": "auto"},
 "series": [{"type": "heatmap", "name": "每日步数(千)",
             "coordinateSystem": "calendar",
             "data": [["2026-03-08", 8], ["2026-09-21", 11]]}]}
```

### 7.6 组件与地图

```python
# 标注（系列级）：markPoint / markLine / markArea
{"type": "line", "name": "月度均价", "data": [96, 102, 88, 115, 108, 130],
 "markPoint": {"data": [{"type": "max"}, {"type": "min"}]},
 "markLine": {"data": [{"type": "average", "name": "均值"}]},   # 或 {"yAxis": 300, "name": "警戒线"}
 "markArea": {"data": [[{"xAxis": "3月"}, {"xAxis": "5月"}]]}}

# dataZoom：slider（底部双把手）+ inside（滚轮缩放、拖拽平移），可同时存在
"dataZoom": [{"type": "slider", "start": 0, "end": 100}, {"type": "inside"}]

# brush 矩形刷选 / toolbox 工具箱（saveAsImage 导出 PNG、restore、dataZoom 开关）
"brush": {"toolbox": ["rect", "clear"], "outOfBrush": {"opacity": 0.35}}
"toolbox": {"feature": ["saveAsImage", "dataZoom", "restore"]}

# timeline 图表时间轴：options[i] 为各帧 option（切帧经 update_option 深合并，
# series 为 list 替换语义——帧内需携带完整系列定义，不能只给 data）
"timeline": {"data": ["2024", "2025", "2026"], "autoPlay": False}
"options": [{"series": [{"type": "bar", "name": "月度销量", "data": [...]}]}, ...]

# map 地图：内置 "demo" 7 大区块示意地图（演示数据），或 geo.regions 自定义多边形
{"visualMap": {"min": 0, "max": 100, "inRange": {"colors": ["#EBEFF5", "#3F5E8C"]}},
 "series": [{"type": "map", "name": "区域销量", "map": "demo",
             "data": [{"name": "华北", "value": 82}, {"name": "华东", "value": 95}]}]}
# 自定义：{"geo": {"regions": {"甲区": [[0, 0], [40, 0], [20, 30]]}}, ...}

# graphic 绝对定位图形元素（circle/rect/text/line）
"graphic": [{"type": "text", "left": 150, "top": 48,
             "style": {"text": "水印文本", "fill": "#C78A2B", "fontSize": 14}}]
```

### 7.7 与 QtCharts 的关系

- **推荐 `InstructionX_UIKit.charts`**：纯原生 QPainter 自绘，无 WebView / JS 桥接，主题令牌实时联动，ECharts 风格 option 覆盖面更广（21 系列 + 4 坐标系 + 标注/缩放/刷选/时间轴等组件）。
- Demo「图表」页已全面切换到 `InstructionX_UIKit.charts` 演示；`PySide6.QtCharts` 不再是图表页依赖，仅当你已有基于 QtCharts 的旧代码时才需要它，两者可共存互不影响。
- 引擎契约见仓库 `CHART_SPEC.md`；可经 `register_series` / `register_component` 扩展自定义系列与组件。

## 8. 蓝图模式（InstructionX_UIKit.blueprint 节点图）

类 UE5 Blueprint / ComfyUI 的节点图编辑器：**纯 UI 与交互，不含业务执行逻辑**。扩展性第一——节点类型、引脚类型、菜单、节点体内容全部可注册 / 覆写。完整演示见 Demo「蓝图」页（`demo/pages/blueprint.py`），组件契约见 `BP_SPEC.md`。

### 8.1 核心概念

| 概念 | 类 | 说明 |
| --- | --- | --- |
| 图 | `BlueprintGraph` | 节点 / 边容器，`add_edge` 全量校验（方向相反、类型兼容含 `any` 通配、单连接替换、禁止自连 / 重复），信号驱动界面同步 |
| 节点 | `BlueprintNode` | `inputs` / `outputs` 引脚、`properties` 自定义参数、`status`（idle/running/done/error）、`elapsed_ms` 耗时 |
| 引脚 | `Pin` / `PinDirection` | `data_type` 决定颜色（`PIN_COLORS`：any/int/float/str/image/tensor/exec），输入可设 `multi` 多连接 |
| 边 | `Edge` | `from_*`（输出端）→ `to_*`（输入端） |
| 注册表 | `NodeRegistry` / `register_node_type` | 节点类型单例注册表：注册 / 搜索 / 分类 / `create`，键为 `(owner, type_name)`，支持命名空间隔离；`register_pin_type` 扩展引脚配色 |
| 画布 | `BlueprintCanvas` | 平移 / 缩放 / 框选 / 拖线建边 / 创建与右键菜单 / Delete 删除 / 序列化 |
| 运行指示 | `ExecutionController` | 经 `canvas.execution()` 取得：仅做 UI 状态展示，**不执行业务逻辑** |

### 8.2 快速上手（10 行）

```python
from PySide6.QtCore import QPointF
from InstructionX_UIKit.blueprint import BlueprintGraph, BlueprintCanvas

graph = BlueprintGraph()
canvas = BlueprintCanvas(graph)                 # 直接当 QWidget 用
a = canvas.add_node_at("start", QPointF(40, 120))     # 内置起始节点
b = canvas.add_node_at("resize", QPointF(360, 120))   # 经注册表创建
graph.add_edge(a.id, "out", b.id, "in")          # 校验通过返回 Edge
canvas.fit_view()                                # 适应视图
```

### 8.3 注册自定义节点（含 body_builder）

```python
from InstructionX_UIKit.blueprint import register_node_type
from InstructionX_UIKit.components.spin_box import SpinBox
from InstructionX_UIKit.components.combo_box import ComboBox

def build_resize_body(node, container):
    """节点体构建器：container 透明、自带 QVBoxLayout，写回 node.properties。"""
    width = SpinBox(16, 4096, int(node.properties.get("width", 640)), size="sm")
    width.valueChanged.connect(lambda v: node.properties.__setitem__("width", int(v)))
    container.layout().addWidget(width)
    combo = ComboBox(items=["nearest", "bilinear", "bicubic"], size="sm")
    combo.currentTextChanged.connect(
        lambda s: node.properties.__setitem__("interpolation", s))
    container.layout().addWidget(combo)

register_node_type(
    "resize", "Resize", "处理",
    inputs=[{"id": "in", "name": "进入", "data_type": "exec"},
            {"id": "img", "name": "图像", "data_type": "image"}],
    outputs=[{"id": "out", "name": "退出", "data_type": "exec"},
             {"id": "img", "name": "图像", "data_type": "image"}],
    accent="warning", body_builder=build_resize_body,
    description="调整图像尺寸",
)
register_pin_type("audio", "#E0A030")  # 可选：扩展引脚类型配色
```

注意：画布为避免与节点拖拽冲突，将节点体设为鼠标透明——`body_builder` 注入的控件在画布内作展示用；交互编辑建议放到侧栏属性面板（Demo 蓝图页用 `demo.pages.playground.ParamForm` 实现，写回同一份 `node.properties` 后 `node.changed.emit()` 刷新外观）。

### 8.4 命名空间隔离（owner）

多个插件 / 模块可能注册**同名节点类型**（如 `load_image`）但引脚定义不同。注册、查询、创建均可携带 `owner` 关键字参数划定命名空间，同名类型在不同 owner 下共存、互不影响；`owner=None` 为全局命名空间（内置 `start` 等留在全局），**不传 owner 的旧调用行为完全不变**。

```python
from InstructionX_UIKit.blueprint import register_node_type, NodeRegistry, BlueprintCanvas, BlueprintGraph

# 两个「插件」各自注册同名但引脚不同的 load_image
register_node_type("load_image", "加载图像", "输入", owner="plugin_a",
                   outputs=[{"id": "img", "name": "图像", "data_type": "image"}])
register_node_type("load_image", "载入图像", "IO", owner="plugin_b",
                   outputs=[{"id": "mat", "name": "张量", "data_type": "tensor"}])

reg = NodeRegistry.instance()
reg.spec("load_image", owner="plugin_a")   # 各得各的定义
reg.spec("load_image", owner="plugin_b")
reg.spec("load_image")                     # 全局未命中时跨空间查找；
                                           # 多命中记 WARNING 并返回首个

# 画布 / 创建菜单 / 节点体在指定 owner 时按「该 owner + 全局」范围解析，
# 因此画布始终可用全局内置类型（start 等）
canvas = BlueprintCanvas(BlueprintGraph(), owner="plugin_a")
```

解析规则汇总：

- 指定 owner 的查询 / 创建（`spec` / `create` / `search` / `categories` / `specs`）范围为「该 owner + 全局命名空间」，该 owner 优先；
- 同命名空间内重复注册同名类型：引脚定义相同则静默幂等，不同则覆盖并记 WARNING（标准库 `logging`）；
- `NodeRegistry` 内部键为 `(owner, type_name)`；`NodeSpec.owner` 为信息性字段，`register` 未显式传 owner 时回退取它。

完整演示见 Demo「蓝图」页底部「命名空间隔离」小节（`demo/pages/blueprint.py`）。

### 8.5 运行指示 API（ComfyUI 式，纯 UI）

```python
ex = canvas.execution()
ex.set_path([a.id, b.id, c.id])   # 高亮路径边（流动虚线动画）
ex.start(a.id)                    # running：脉冲描边 + 标题栏旋转圈
ex.finish(a.id)                   # done：success 描边 + 耗时徽标（缺省自动计时）
ex.fail(b.id, "模拟失败")          # error：danger 描边 + tooltip
ex.reset()                        # 全部回 idle，清耗时与路径
# 信号：node_started(str) / node_finished(str, float) / finished()
```

Demo 蓝图页的「运行」按 exec 链拓扑序用 QTimer 逐节点模拟（每节点 200–800ms 随机耗时），「单步」逐节点推进——全部只是状态指示，无业务逻辑。

### 8.6 渲染后端（GPU 加速）

画布绘制由内部视口承载，**运行时自动选择后端，调用方无需修改任何代码**：

- **GL 后端（默认，可用时）**：视口为 `QOpenGLWidget`，背景 / 网格 / 边 / 节点位图合成走 GPU；无可见自定义体（`body_builder`）的节点以缓存位图代理由视口统一绘制，平移 / 缩放 / 拖动期间节点内容零重绘，高分辨率（4K+）与大节点量场景显著流畅。带可见自定义体的节点自动回退为真实控件渲染。
- **软件后端（自动回退）**：无 GL 环境（含 `QT_QPA_PLATFORM=offscreen` 的测试环境）时使用普通 QWidget 视口，行为与历史版本一致，离屏测试与截图回归不受影响。

环境变量 `UIKIT_BLUEPRINT_GL` 可控制后端选择：`auto`（默认，自动探测）/ `on`（强制尝试，失败仍回退并记 WARNING）/ `off`（强制软件渲染，可用于排查显示问题）。

```python
import os
os.environ["UIKIT_BLUEPRINT_GL"] = "off"   # 在 QApplication 创建前设置
```

> **注意（GL 后端的 Qt 固有行为）**：`QOpenGLWidget` 加入**已可见**的顶层窗口时，Qt 会重建该窗口的原生句柄，表现为窗口短暂关闭后重开一次。建议像 Demo 的 `MainWindow` 一样，在顶层窗口 `show()` 之前创建 `BlueprintCanvas`（或至少预创建一次蓝图页面）；一次性创建并长期持有画布的应用不受影响。

### 8.7 序列化

```python
data = canvas.to_dict()      # {"graph": {...}, "view": {"zoom", "offset"}}
canvas.from_dict(data)       # 重建节点 / 边并还原视图状态
graph.to_dict()              # 仅数据层：{"nodes": [...], "edges": [...]}
```

全部 JSON 友好（`json.dumps` 可直接序列化），含节点位置、引脚、properties 与画布 zoom/offset。

### 8.8 应用场景

节点图天然适合「可视化拼装 + 数据流」类工具：**PyTorch 模块拼装**（把 Conv / Attention / 融合等模块注册为节点类型，properties 承载超参数，图结构导出为构建脚本）、**着色器 / 材质流水线**（纹理输入、滤镜、混合节点，引脚类型映射数据格式）、**AI 流水线编排**（加载→预处理→推理→后处理→落盘，如 Demo 预置图），以及规则引擎、音视频转码链、ETL 流程等。库只负责编辑与状态展示，真正的执行调度由应用层按图拓扑自行实现。

## 9. 常见问题

**Q1：设置了 `size="sm"` 但样式不生效？**
`size` 是 QWidget 内置 `Q_PROPERTY`，`setProperty("size", "sm")` 会失败且不会成为动态属性。务必使用：

```python
from InstructionX_UIKit.theme import set_property
set_property(widget, "size", "sm")     # 内部自动映射为 uiksize 动态属性
```

QSS 中 `[size="..."]` 与 `[uiksize="..."]` 两组选择器均已定义，实际生效的是 `uiksize`。组件库构造参数（如 `Button(size="sm")`）与 `set_size()` 方法已内置该映射。

**Q2：如何在无显示环境下测试 / 截图？**

```bash
QT_QPA_PLATFORM=offscreen python your_script.py
```

```python
import os
os.environ["QT_QPA_PLATFORM"] = "offscreen"   # 须在 import PySide6 之前
from PySide6.QtWidgets import QApplication
app = QApplication([])
w = MyWidget(); w.resize(400, 300); w.show()
w.grab().save("shot.png")                     # 离屏下 grab() 可用
```

仓库 `tests/` 下的 `test_*.py` 均可直接 `python tests/test_xxx.py` 运行，截图输出到 `tests/shots/`。

**Q3：动画一闪而过 / 根本没动？**
动画对象被 Python 垃圾回收。`InstructionX_UIKit.anim.property` 的所有预设已把动画 parent 到目标控件，正常不会失效；如果你自己 new `QPropertyAnimation`，请保存引用：

```python
self._anim = QPropertyAnimation(w, b"pos", self)   # 给 parent 或存成员变量
self._anim.start()
```

**Q4：slide_in / bounce / float_loop 等位移动画被「弹回」原位？**
`pos` / `geometry` 动画作用于「被布局管理的控件」时，下一次布局刷新会把位置重置回布局计算值。处理方式：

- 对无布局（绝对定位）的控件使用位移动画；
- 或在动画播放期间暂时移除布局约束；
- 优先选用不依赖 `pos` 的预设：`fade_in`、`zoom_in`、`spring_pop`、`blur_in`、`mask_reveal`（基于图形效果或遮罩，布局中安全）。

**Q5：阴影 / 模糊 / 缩放动画互相覆盖？**
一个 QWidget 同时只能挂载一个 `QGraphicsEffect`：`apply_shadow()`、`blur_in()`、`zoom_in()`（内部 `_TransformEffect`）、`pulse_glow()` 会互相替换。需要「阴影 + 缩放」组合时，把阴影挂到父容器，缩放作用于内部子控件。

**Q6：主题切换后哪些东西需要手动处理？**
QSS 控件与组件库自绘控件全部自动跟随。仅以下两种情况需手动：

- 你自己 `apply_shadow()` 过的控件：阴影颜色来自生成时刻的令牌，切换后重新调用一次 `apply_shadow(widget, level)`；
- 你自己缓存过 `T()` 返回值的代码：改为在 `paintEvent` / 槽函数中实时取，或连接 `theme_changed` 信号更新。

**Q7：Notification / Message / Popconfirm 的 anchor 传什么？**
传依附的窗口级控件（通常是主窗口 `self`），用于定位弹层；它们是非阻塞的，静态方法调用即显示并返回实例，可继续连接信号或 `dismiss()`。

**Q8：Dialog.confirm 为什么是回调而不是 exec()？**
组件库对话框走「非阻塞 + 回调」风格：`Dialog.confirm(parent, title, text, on_result=lambda ok: ...)`。需要阻塞语义的场合可用 `dlg.exec()`（Dialog 继承 QDialog），但推荐保持回调风格与 Notification / Popconfirm 一致。

**Q9：FormLayout 的 validator 怎么写？**
校验器接收字段「值」（由 `extract_value` 从控件提取，如 LineEdit 的 text()），返回 `True` / `None` 表示通过，返回字符串表示错误信息，`False` 表示「不合法」通用错误：

```python
form.add_row("邮箱", edit, required=True,
             validator=lambda v: "@" in v or "邮箱格式不正确")
```

**Q10：如何给 QLabel 做文字降级？**
QSS 内置了 `role` 动态属性选择器：

```python
from InstructionX_UIKit.theme import set_property
set_property(label, "role", "secondary")   # secondary / tertiary / hint
```
