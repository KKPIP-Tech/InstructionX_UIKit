# -*- coding: utf-8 -*-
"""组件 · 展示演示页：18 个数据展示组件，每组件一页，覆盖主要变体。

页面 = 标题 + 说明 + 分区演示，紧凑排布；亮 / 暗主题切换自动换肤。
"""

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPixmap
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
from InstructionX_UIKit.components.markdown_view import MarkdownView
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

_POPOVERS = []  # 防止弹出层被 GC（销毁时自动移除，不累积）


def _gradient_pixmap(w=240, h=160, c1=None, c2=None):
    """生成一张渐变测试图（颜色取自主题令牌，暗色主题自动换肤）。"""
    pm = QPixmap(w, h)
    grad = QLinearGradient(0, 0, w, h)
    grad.setColorAt(0, QColor(c1 or T("color.primary")))
    grad.setColorAt(1, QColor(c2 or T("color.success")))
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

    绘制参数经基类公开 setter（set_axis_side / set_line / set_dot /
    set_row_spacing / set_fonts）转发，本类以属性形式暴露给 Playground
    绑定；数据与绘制完全复用基类实现。
    """

    def __init__(self, pending: str = None, parent=None):
        super().__init__(pending, parent)
        self._title_font_size = T("font.md")
        self._time_font_size = T("font.xs")

    @property
    def line_width(self):
        return self._line_width

    @line_width.setter
    def line_width(self, v):
        self.set_line(float(v), self._line_style)

    @property
    def line_style(self):
        return self._line_style

    @line_style.setter
    def line_style(self, v):
        self.set_line(self._line_width, v)

    @property
    def dot_radius(self):
        return self._dot_radius

    @dot_radius.setter
    def dot_radius(self, v):
        self.set_dot(int(v))

    @property
    def extra_spacing(self):
        return self._extra_spacing

    @extra_spacing.setter
    def extra_spacing(self, v):
        self.set_row_spacing(int(v))

    @property
    def axis_side(self):
        return self._axis_side

    @axis_side.setter
    def axis_side(self, v):
        self.set_axis_side(v)

    @property
    def title_font_size(self):
        return self._title_font_size

    @title_font_size.setter
    def title_font_size(self, v):
        self.set_fonts(title_size=int(v))

    @property
    def time_font_size(self):
        return self._time_font_size

    @time_font_size.setter
    def time_font_size(self, v):
        self.set_fonts(time_size=int(v))


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
    # 演示底色取自语义令牌（primary / success / warning），亮暗主题自动换肤
    for i, color_key in enumerate(("color.primary", "color.success", "color.warning")):
        page = QLabel(f"第 {i + 1} 屏")
        page.setAlignment(Qt.AlignCenter)
        page.setStyleSheet(
            f"background-color: {T(color_key)}; color: {T('color.on.primary')}; "
            f"font-size: 20px; border-radius: 8px; margin: 4px;")
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
    # 弹层销毁时从防 GC 列表移除（销毁时连接随对象一并释放，不会累积；
    # 幂等：进程退出期销毁顺序不定，remove 缺失元素会在槽里抛 SystemError）
    pop.destroyed.connect(
        lambda: _POPOVERS.remove(pop) if pop in _POPOVERS else None)
    anchor.clicked.connect(lambda: pop.show_for(anchor, placement="bottom"))
    s.layout().addWidget(row(anchor))
    s.layout().addWidget(hint_label("点击按钮相对锚点弹出带箭头气泡卡片。", role="tertiary"))
    return make_page("Popover 气泡卡片", "相对锚点弹出（QFrame, Popup），带箭头。", [s])


_MARKDOWN_SAMPLE = """## 渲染能力一览

正文支持 **加粗**、*斜体*、~~删除线~~ 与 `行内代码`。

- 无序列表项
- 支持任务列表：
- [x] 已完成的事项
- [ ] 待办事项

> 引用块使用次要文本色，适合展示引用与提示。

```python
def fibonacci(n):
    a, b = 0, 1
    for _ in range(n):
        a, b = b, a + b
    return a
```

| 语法 | 支持情况 |
|------|----------|
| 表格 | 支持 |
| 代码围栏 | 支持（等宽字体 + 底色，不做语法高亮） |

[链接使用主题主色](https://github.com/KKPIP-Tech/InstructionX_UIKit)
"""

_MARKDOWN_MATH = r"""行内公式：质能方程 $E=mc^2$，以及欧拉恒等式 $e^{i\pi}+1=0$。

块级公式（求根公式）：

$$\frac{-b \pm \sqrt{b^2-4ac}}{2a}$$

也支持 `\[...\]` 与 `\begin{equation}` 环境：

\[\int_0^\infty e^{-x^2}\,dx = \frac{\sqrt{\pi}}{2}\]

\begin{equation}
a^2 + b^2 = c^2
\end{equation}

公式由 matplotlib mathtext 在后台线程异步渲染并缓存，渲染期间以源码占位；
代码围栏与行内代码中的 `$...$` 不会被当作公式。
"""

_MARKDOWN_STREAM = r"""## 流式渲染能力演示

这段内容由**逐 token 追加**生成，涵盖 Markdown 与 LaTeX 的主要渲染能力。

### 文本样式

支持 **加粗**、*斜体*、~~删除线~~、`行内代码` 与 [链接](https://github.com/KKPIP-Tech/InstructionX_UIKit)。

- [x] 无序 / 有序 / 任务列表
- [x] 引用块、表格与代码围栏
- [ ] 脚注（不支持）

### 行内公式

质能方程 $E=mc^2$、欧拉恒等式 $e^{i\pi}+1=0$、勾股定理 $a^2+b^2=c^2$；
希腊字母 $\alpha, \beta, \gamma, \Delta, \Omega$；向量点积
$\vec{a} \cdot \vec{b} = |\vec{a}||\vec{b}|\cos\theta$。

### 块级公式

求根公式：

$$
\frac{-b \pm \sqrt{b^2-4ac}}{2a}
$$

泰勒级数：

$$
e^x = \sum_{n=0}^{\infty} \frac{x^n}{n!}
$$

高斯积分：

$$
\int_{-\infty}^{\infty} e^{-x^2} dx = \sqrt{\pi}
$$

重要极限（单行写法）：

$$\lim_{x \to 0} \frac{\sin x}{x} = 1$$

傅里叶变换：

$$
\hat{f}(\xi) = \int_{-\infty}^{\infty} f(x) e^{-2\pi i x \xi} dx
$$

简谐振动微分方程：

$$
\frac{d^2 y}{dx^2} + \omega^2 y = 0
$$

### 表格与代码

| 语法 | 写法 |
|------|------|
| 行内公式 | `$...$` |
| 块级公式 | `$$...$$` / `\[...\]` |
| 矩阵环境 | 不支持（mathtext 限制） |

> 公式由 matplotlib mathtext 后台异步渲染，命中 LRU 缓存零耗时。

```python
view = MarkdownView()
for token in stream:       # 逐 token 到达
    view.append_markdown(token)
```
"""

_MARKDOWN_STREAM_ALL = r"""# Markdown 全格式总览

本段由流式追加实时渲染，覆盖组件支持的全部 Markdown 格式。

## 1. 标题与段落

支持 `#` 至 `######` 六级标题；正文段落自动换行，空行分段。

## 2. 行内样式

**加粗**、*斜体*、~~删除线~~、`行内代码`、
[主题色链接](https://github.com/KKPIP-Tech/InstructionX_UIKit)。

## 3. 列表

无序列表：

- 苹果
- 香蕉
  - 嵌套子项

有序列表：

1. 第一步
2. 第二步

任务列表：

- [x] 已完成事项
- [ ] 待办事项

## 4. 引用与分割线

> 引用块使用次级文字颜色，
> 可以跨越多行。

---

## 5. 表格

| 名称 | 类型 | 说明 |
|------|------|------|
| `set_markdown` | 方法 | 全量替换内容 |
| `append_markdown` | 方法 | 流式追加 |
| `linkActivated` | 信号 | 点击链接时发射 |

## 6. 代码围栏

```python
def render(text):
    view = MarkdownView(text)   # 全量渲染
    return view
```

## 7. 数学公式

行内公式 $e^{i\pi}+1=0$，以及块级公式：

$$
\int_{-\infty}^{\infty} e^{-x^2} dx = \sqrt{\pi}
$$

## 8. Mermaid 图表

```mermaid
flowchart LR
    A[输入] --> B{校验}
    B -- 通过 --> C[渲染]
    B -- 失败 --> D[占位提示]
```

> 提示：脚注、内嵌 HTML 与网络图片不在支持之列；
> Mermaid 由官方 mermaid.js 引擎渲染，全量图型可用。
"""


_MARKDOWN_MERMAID = r"""Mermaid 图表由官方 mermaid.js 引擎渲染（WebEngine，随包分发不联网），
官方全量图型可用，随主题令牌着色。图表是可交互的：拖动平移、
Ctrl+滚轮缩放，右上角工具条可放大 / 缩小 / 复位 / 适宽。

```mermaid
flowchart LR
    A[用户提问] --> B{理解意图}
    B -- 明确 --> C[检索知识库]
    B -- 模糊 --> D[请求澄清]
    C --> E[生成回答]
    D --> E
```

```mermaid
sequenceDiagram
    participant U as 用户
    participant A as 助手
    U->>A: 发送问题
    A->>A: 推理与检索
    A-->>U: 流式返回回答
```

```mermaid
stateDiagram-v2
    待机 --> 运行中: 启动
    运行中 --> 已暂停: 暂停
    已暂停 --> 运行中: 继续
    运行中 --> 已停止: 停止
```

```mermaid
gantt
    title 迭代计划
    dateFormat YYYY-MM-DD
    section 设计
    需求梳理: 2026-01-01, 5d
    交互稿: 2026-01-06, 4d
    section 开发
    前端实现: 2026-01-10, 8d
    联调测试: 2026-01-18, 5d
```

```mermaid
pie title 本周时间分布
    "编码": 40
    "阅读文档": 25
    "讨论设计": 20
    "其他": 15
```

流式追加中未闭合的 mermaid 围栏按代码块降级显示，闭合后重排为图表；
语法错误时显示失败占位图。WebEngine 不可用时自动降级为内置自绘渲染器
（flowchart / sequenceDiagram / pie 子集）。
"""


def _stream_section(title: str, text: str, height: int) -> Section:
    """构造一个流式追加演示分区：自动播放 + 重新播放按钮。"""
    sec = Section(title)
    view = MarkdownView()
    view.setMinimumHeight(height)
    chunks = [""]
    timer = QTimer(view)

    def _replay():
        view.clear()
        # 按小片段切分，模拟逐 token 到达
        chunks[:] = [text[i:i + 8] for i in range(0, len(text), 8)]
        timer.start(40)

    def _tick():
        if not chunks:
            timer.stop()
            return
        view.append_markdown(chunks.pop(0))

    timer.timeout.connect(_tick)
    sec.layout().addWidget(view)
    btn = QPushButton("重新播放")
    set_property(btn, "variant", "primary")
    set_property(btn, "size", "sm")
    btn.clicked.connect(_replay)
    sec.layout().addWidget(row(btn))
    _replay()
    return sec


def create_markdown_page() -> QWidget:
    s = Section("基础渲染")
    view = MarkdownView(_MARKDOWN_SAMPLE)
    view.setMinimumHeight(380)
    s.layout().addWidget(view)

    s2 = _stream_section("流式追加（模拟 AI 逐字输出，含 LaTeX 公式实时渲染）",
                         _MARKDOWN_STREAM, 420)
    s_all = _stream_section("流式追加 · Markdown 全格式总览",
                            _MARKDOWN_STREAM_ALL, 480)

    s_math = Section("数学公式（LaTeX）")
    math_view = MarkdownView(_MARKDOWN_MATH)
    math_view.setMinimumHeight(300)
    s_math.layout().addWidget(math_view)

    s_mmd = Section("Mermaid 图表")
    mmd_view = MarkdownView(_MARKDOWN_MERMAID)
    mmd_view.setMinimumHeight(1750)
    s_mmd.layout().addWidget(mmd_view)

    s3 = Section("空状态")
    empty_view = MarkdownView()
    empty_view.setFixedHeight(120)
    s3.layout().addWidget(empty_view)
    return make_page("MarkdownView Markdown 渲染",
                     "Qt 内置引擎原生渲染 Markdown，令牌化样式，支持流式追加、LaTeX 公式与 Mermaid 图表。",
                     [s, s2, s_all, s_math, s_mmd, s3])


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
    ("markdown_view", "MarkdownView Markdown 渲染", create_markdown_page),
]
