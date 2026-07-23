# -*- coding: utf-8 -*-
"""布局演示的示例数据与卡片构建器（Demo 程序专用）。

InstructionX_UIKit 的 12 个布局预设全部为 API 驱动、不含任何假数据；
本模块集中存放演示用的示例内容（原是布局内置的占位数据，已迁入
Demo），``layouts.py`` 各演示页从这里取数据并传给布局。

同时，每个布局给出 ``USAGE`` 单行调用示例，演示页顶部以灰字代码
标签展示，开发者照此即可用 Kit 复现相同效果。
"""

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QProgressBar,
    QVBoxLayout,
    QWidget,
)

from InstructionX_UIKit.theme import T, ThemeManager
from InstructionX_UIKit.layouts.helpers import (
    TokenColorChip,
    apply_token_font,
    titled_card,
)

# ---------------------------------------------------------------------------
# 各布局的单行用法示例（演示页顶部灰字代码标签）
# ---------------------------------------------------------------------------

USAGE = {
    "top_nav_bar": 'create_top_nav_bar(brand="控制台", menu_items=[...], cards=[(标题, 描述, 色块键), ...])',
    "holy_grail": 'create_holy_grail(title="圣杯布局", nav_items=[...], center=widget, side=widget)',
    "card_grid": 'create_card_grid(items=[("数据看板", "描述", "color.primary.subtle"), ...])',
    "single_column": 'create_single_column(title=..., subtitle=..., paragraphs=[...], actions=[(文本, variant)])',
    "sidebar_layout": 'create_sidebar_layout(brand="控制台", nav_items=[(图标名, 文本)], content=widget)',
    "master_detail": 'create_master_detail(items=[(标题, 摘要, 正文)], title="收件箱")',
    "split_panel": 'create_split_panel(nav_items=[...], list_items=[...], content=widget)',
    "dashboard_grid": 'create_dashboard_grid(cards=[card × 9])  # 依次占 3/3/3/3/8/4/6/6/12 列跨度',
    "hero_section": 'create_hero_section(kicker=..., title=..., primary_text="开始使用", secondary_text="查看文档")',
    "centered_container": 'create_centered_container(title=..., actions=[...], cards=[(标题, 描述, 色块键)])',
    "waterfall": 'create_waterfall(items=[(标题, 色块键, 档位2-6), ...])',
    "media_left_right": 'create_media_left_right(sections=[(标题, 正文, 色块键)], link_text="了解更多")',
}

# ---------------------------------------------------------------------------
# 顶部导航栏
# ---------------------------------------------------------------------------

TOP_NAV_BAR = dict(
    brand="UI Kit 控制台",
    menu_items=("首页", "产品", "文档", "社区", "关于"),
    search_placeholder="搜索文档、组件...",
    user_text="我",
    title="欢迎使用 UI Kit",
    subtitle="这是顶部导航栏布局预设的窗口级示例，下方为内容卡片，主题切换时颜色自动跟随。",
    cards=(
        ("功能模块一", "用于演示的内容卡片，色块取 primary.subtle 令牌。", "color.primary.subtle"),
        ("功能模块二", "用于演示的内容卡片，色块取 success.subtle 令牌。", "color.success.subtle"),
        ("功能模块三", "用于演示的内容卡片，色块取 warning.subtle 令牌。", "color.warning.subtle"),
        ("功能模块四", "用于演示的内容卡片，色块取 danger.subtle 令牌。", "color.danger.subtle"),
    ),
)

# ---------------------------------------------------------------------------
# 圣杯布局
# ---------------------------------------------------------------------------

HOLY_GRAIL = dict(
    title="圣杯布局",
    nav_items=("概览", "分析", "报表", "成员", "设置"),
    header_actions=("刷新", "设置"),
    footer_note="页脚：拖拽中间分栏手柄可调整侧栏宽度",
    status="就绪",
)


def build_holy_grail_center() -> QWidget:
    """圣杯布局主内容区示例：标题 + 色块 + 说明段落。"""
    panel = QWidget()
    lay = QVBoxLayout(panel)
    lay.setContentsMargins(T("space.2"), T("space.2"), T("space.2"), T("space.2"))
    lay.setSpacing(T("space.3"))
    title = QLabel("主内容区")
    apply_token_font(title, "font.title.md", "font.weight.semibold")
    lay.addWidget(title)
    chip = TokenColorChip("color.primary.subtle", "radius.md")
    chip.setMinimumHeight(T("space.16") * 2)
    lay.addWidget(chip)
    for text in (
        "圣杯布局由页头、页脚、左右侧栏与主内容区组成，中间三区放在 QSplitter 中，"
        "拖拽分栏手柄即可调整各栏宽度。",
        "窗口变窄时按断点依次隐藏右侧栏与左侧栏，保证主内容区始终可用。",
    ):
        para = QLabel(text)
        para.setProperty("role", "secondary")
        para.setWordWrap(True)
        lay.addWidget(para)
    lay.addStretch(1)
    return panel


def build_holy_grail_side() -> QWidget:
    """圣杯布局右侧栏示例：相关信息列表。"""
    panel = QWidget()
    lay = QVBoxLayout(panel)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(T("space.2"))
    head = QLabel("相关信息")
    apply_token_font(head, "font.sm", "font.weight.semibold")
    head.setProperty("role", "tertiary")
    lay.addWidget(head)
    listing = QListWidget()
    listing.addItems(("更新日志 v1.0", "设计规范", "组件清单", "常见问题"))
    lay.addWidget(listing, 1)
    return panel

# ---------------------------------------------------------------------------
# 卡片网格
# ---------------------------------------------------------------------------

#: 示例卡片数据（标题、描述、色块令牌）
CARD_GRID_ITEMS = (
    ("数据看板", "汇总关键指标的内容卡片，色块取 primary.subtle 令牌。", "color.primary.subtle"),
    ("任务中心", "展示待办与进度的内容卡片，色块取 success.subtle 令牌。", "color.success.subtle"),
    ("消息通知", "聚合系统消息的内容卡片，色块取 warning.subtle 令牌。", "color.warning.subtle"),
    ("风险预警", "呈现异常项的内容卡片，色块取 danger.subtle 令牌。", "color.danger.subtle"),
    ("团队动态", "展示协作动态的内容卡片，主题切换自动跟随。", "color.primary.subtle"),
    ("文件库", "管理项目文件的内容卡片，主题切换自动跟随。", "color.success.subtle"),
    ("日程安排", "查看近期日程的内容卡片，主题切换自动跟随。", "color.warning.subtle"),
    ("系统设置", "进入偏好设置的内容卡片，主题切换自动跟随。", "color.danger.subtle"),
)

# ---------------------------------------------------------------------------
# 单列堆叠
# ---------------------------------------------------------------------------

SINGLE_COLUMN = dict(
    kicker="布局预设 · 单列堆叠",
    title="用统一的垂直节奏组织长文内容",
    subtitle="单列布局将阅读动线收敛到一条中轴：所有区块限宽 760px 居中，"
             "段落与区块间距全部取自 space 令牌。",
    cover_key="color.primary.subtle",
    paragraphs=(
        "单列堆叠适合文档、博客与公告等以阅读为主的场景。"
        "限宽让每行文字保持舒适的阅读长度，居中留白则让内容在宽屏下依然聚焦。",
        "本示例中的间距（space.4 段落、space.6 区块）、圆角（radius.lg 封面）"
        "与颜色（primary.subtle 封面、secondary 正文）全部来自设计令牌，"
        "切换亮 / 暗主题时自动跟随。",
        "窗口继续收窄时，本布局不做分档重排，而是让 760px 的列随窗口线性收缩，"
        "保证任何宽度下都只有一条阅读中轴。",
    ),
    quote="「好的布局不喧哗：它退到内容背后，用节奏与留白说话。」",
    actions=(("阅读全文", "primary"), ("收藏", "default")),
)

# ---------------------------------------------------------------------------
# 侧边栏布局
# ---------------------------------------------------------------------------

#: 导航项示例：（图标名, 文本），图标取自 InstructionX_UIKit.icons
SIDEBAR_NAV_ITEMS = (
    ("home", "首页"),
    ("component", "组件"),
    ("chart", "图表"),
    ("layout", "布局"),
    ("animation", "动画"),
    ("settings", "设置"),
)


def _stat_card(title, value, note):
    """构造内容区顶部的统计卡片。"""
    card = QFrame()
    card.setFrameShape(QFrame.StyledPanel)
    lay = QVBoxLayout(card)
    lay.setContentsMargins(T("space.4"), T("space.3"), T("space.4"), T("space.3"))
    lay.setSpacing(T("space.1"))
    head = QLabel(title)
    head.setProperty("role", "secondary")
    lay.addWidget(head)
    number = QLabel(value)
    apply_token_font(number, "font.display", "font.weight.bold")
    lay.addWidget(number)
    foot = QLabel(note)
    foot.setProperty("role", "tertiary")
    apply_token_font(foot, "font.sm")
    lay.addWidget(foot)
    return card


def build_sidebar_content() -> QWidget:
    """侧边栏布局内容区示例：面包屑 + 标题 + 统计卡 + 内容面板。"""
    content = QWidget()
    lay = QVBoxLayout(content)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(T("space.4"))

    crumb = QLabel("首页 / 概览")
    crumb.setProperty("role", "tertiary")
    apply_token_font(crumb, "font.sm")
    lay.addWidget(crumb)
    title = QLabel("项目概览")
    apply_token_font(title, "font.title.lg", "font.weight.semibold")
    lay.addWidget(title)

    stats = QGridLayout()
    stats.setSpacing(T("space.4"))
    stats.addWidget(_stat_card("访问用户", "12,846", "较上周 +8.2%"), 0, 0)
    stats.addWidget(_stat_card("活跃项目", "36", "本周新增 4 个"), 0, 1)
    stats.addWidget(_stat_card("待办事项", "9", "3 项即将到期"), 0, 2)
    lay.addLayout(stats)

    panel = QFrame()
    panel.setFrameShape(QFrame.StyledPanel)
    panel_lay = QVBoxLayout(panel)
    panel_lay.setContentsMargins(T("space.4"), T("space.4"), T("space.4"), T("space.4"))
    panel_lay.setSpacing(T("space.2"))
    chip = TokenColorChip("color.primary.subtle", "radius.md")
    chip.setMinimumHeight(T("space.16") * 2)
    panel_lay.addWidget(chip)
    note = QLabel("内容区：可替换为表格、表单或图表。侧栏在窄窗口下会自动折叠为图标栏。")
    note.setProperty("role", "secondary")
    note.setWordWrap(True)
    panel_lay.addWidget(note)
    lay.addWidget(panel, 1)
    return content

# ---------------------------------------------------------------------------
# 列表-详情
# ---------------------------------------------------------------------------

#: 示例条目：（标题, 摘要, 详情正文）
MASTER_DETAIL_ITEMS = (
    ("产品周报 · 第 24 期", "本周核心指标回顾", "本周活跃用户环比增长 8.2%，新增项目 4 个，"
     "重点跟进项 3 个均已按期推进。下周将发布 v1.1 灰度版本。"),
    ("设计评审纪要", "令牌与主题契约确认", "评审确认了色彩、间距、圆角与阴影令牌的最终数值，"
     "亮 / 暗双主题共用同一套语义键，组件侧只引用令牌不写死数值。"),
    ("发布检查单", "v1.0 发布前核对", "检查单覆盖：令牌完整性、双主题截图、离屏自测退出码、"
     "文档与示例代码同步。全部通过后方可打 tag。"),
    ("用户访谈记录", "5 位种子用户反馈", "用户普遍认可响应式侧栏与分栏面板；"
     "希望在后续版本增加密度切换与更多图表示例。"),
    ("迭代计划草稿", "下一周期范围初拟", "下一迭代聚焦：组件库补齐、动画预设验收、"
     "Demo 导航完善。列表-详情布局将用于邮件与任务中心。"),
)

MASTER_DETAIL = dict(
    items=MASTER_DETAIL_ITEMS,
    title="收件箱",
    actions=(("标记已读", "primary"), ("归档", "default")),
)

# ---------------------------------------------------------------------------
# 分栏面板
# ---------------------------------------------------------------------------

SPLIT_PANEL = dict(
    nav_items=("工作台", "项目", "数据", "设置"),
    list_items=("季度总结", "里程碑计划", "评审纪要", "发布检查单",
                "访谈记录", "迭代草稿"),
)


def build_split_panel_content() -> QWidget:
    """分栏面板内容区示例：标题 + 色块 + 说明。"""
    panel = QWidget()
    lay = QVBoxLayout(panel)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(T("space.3"))
    title = QLabel("内容区")
    apply_token_font(title, "font.title.md", "font.weight.semibold")
    lay.addWidget(title)
    chip = TokenColorChip("color.primary.subtle", "radius.md")
    chip.setMinimumHeight(T("space.16") + T("space.8"))
    lay.addWidget(chip)
    note = QLabel("拖动分栏手柄调整栏宽，本布局会记忆调整后的比例；"
                  "窗口尺寸变化时按比例重新分配。窄断点下依次隐藏导航栏与列表栏。")
    note.setProperty("role", "secondary")
    note.setWordWrap(True)
    lay.addWidget(note)
    lay.addStretch(1)
    return panel

# ---------------------------------------------------------------------------
# 仪表盘网格
# ---------------------------------------------------------------------------

#: 示例柱状图相对高度（0~1）
_DEMO_BAR_VALUES = (0.45, 0.70, 0.55, 0.90, 0.62, 0.80, 0.50, 0.66)


class _DemoBarChart(QWidget):
    """主题感知示例柱状图（Demo 数据）：自绘，paintEvent 实时取令牌色。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(T("space.16") * 2)
        ThemeManager.instance().theme_changed.connect(self.update)

    def paintEvent(self, event):  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(Qt.NoPen)
        gap = T("space.2")
        radius = T("radius.sm")
        count = len(_DEMO_BAR_VALUES)
        bar_w = max(T("space.1"), (self.width() - gap * (count + 1)) // count)
        for i, ratio in enumerate(_DEMO_BAR_VALUES):
            bar_h = int((self.height() - T("space.2")) * ratio)
            x = gap + i * (bar_w + gap)
            painter.setBrush(QColor(T("color.primary")))
            painter.drawRoundedRect(x, self.height() - bar_h, bar_w, bar_h, radius, radius)


def build_dashboard_cards() -> list:
    """构建仪表盘 9 张示例卡片（依次对应 3/3/3/3/8/4/6/6/12 列跨度）。"""
    cards = []

    stats = (("总用户数", "24,317", "较上周 +8.2%"),
             ("活跃项目", "142", "本周新增 12 个"),
             ("总收入", "¥86,400", "达成月度目标 76%"),
             ("异常告警", "3", "2 项待处理"))
    for title, value, note in stats:
        card, lay = titled_card(title)
        number = QLabel(value)
        apply_token_font(number, "font.display", "font.weight.bold")
        lay.addWidget(number)
        foot = QLabel(note)
        foot.setProperty("role", "secondary")
        apply_token_font(foot, "font.sm")
        lay.addWidget(foot)
        lay.addStretch(1)
        cards.append(card)

    chart_card, chart_lay = titled_card("近八周访问趋势")
    chart_lay.addWidget(_DemoBarChart(), 1)
    cards.append(chart_card)

    feed_card, feed_lay = titled_card("最新动态")
    for text in ("发布了 v1.0 正式版", "合并了 6 个组件分支",
                 "新增 2 位协作者", "更新了设计规范文档"):
        row = QHBoxLayout()
        row.setSpacing(T("space.2"))
        dot = TokenColorChip("color.primary", "radius.pill")
        dot.setFixedSize(T("space.2"), T("space.2"))
        row.addWidget(dot, 0, Qt.AlignVCenter)
        label = QLabel(text)
        label.setProperty("role", "secondary")
        row.addWidget(label, 1)
        feed_lay.addLayout(row)
    feed_lay.addStretch(1)
    cards.append(feed_card)

    quota_card, quota_lay = titled_card("资源用量")
    for name, value in (("存储空间", 65), ("计算配额", 42)):
        label = QLabel(name)
        label.setProperty("role", "secondary")
        quota_lay.addWidget(label)
        bar = QProgressBar()
        bar.setRange(0, 100)
        bar.setValue(value)
        quota_lay.addWidget(bar)
    quota_lay.addStretch(1)
    cards.append(quota_card)

    todo_card, todo_lay = titled_card("本周待办")
    for text in ("完成布局库验收", "补齐组件双主题截图", "撰写使用文档"):
        label = QLabel(f"· {text}")
        label.setProperty("role", "secondary")
        todo_lay.addWidget(label)
    todo_lay.addStretch(1)
    cards.append(todo_card)

    banner_card, banner_lay = titled_card("公告")
    banner = QLabel("布局预设已覆盖全部 12 个场景；跨度随断点自动重排，窗口收窄时卡片纵向堆叠。")
    banner.setProperty("role", "secondary")
    banner.setWordWrap(True)
    banner_lay.addWidget(banner)
    cards.append(banner_card)

    return cards

# ---------------------------------------------------------------------------
# 英雄区
# ---------------------------------------------------------------------------

HERO_SECTION = dict(
    kicker="InstructionX_UIKit · 布局预设",
    title="用令牌与断点\n搭建响应式界面",
    subtitle="颜色、间距、圆角全部取自设计令牌，亮 / 暗主题开箱即用；"
             "按窗口宽度自动切换排布，窄屏下插图移到文案下方。",
    primary_text="开始使用",
    secondary_text="查看文档",
    hint="无需编写样式表，动态属性 + 全局 QSS 即可完成主题化。",
)

# ---------------------------------------------------------------------------
# 居中容器
# ---------------------------------------------------------------------------

CENTERED_CONTAINER = dict(
    title="账号设置",
    subtitle="居中容器示例：内容限宽 960px，窗口收窄时内容卡片按 3/2/1 列重排。",
    actions=(("保存修改", "primary"), ("取消", "default")),
    cards=(
        ("个人资料", "头像、昵称与签名等基础信息。", "color.primary"),
        ("安全设置", "密码、二次验证与登录设备。", "color.success"),
        ("消息偏好", "通知渠道与免打扰时段。", "color.warning"),
        ("主题外观", "亮色 / 暗色主题与密度。", "color.primary"),
        ("API 密钥", "访问令牌与调用配额。", "color.success"),
        ("账单信息", "套餐、发票与支付方式。", "color.warning"),
    ),
    note="提示：居中容器通过「两侧弹性留白 + 内容最大宽度」实现，"
         "在超宽屏下内容依然保持可读的中轴宽度。",
)

# ---------------------------------------------------------------------------
# 瀑布流
# ---------------------------------------------------------------------------

#: 示例卡片：（标题, 色块令牌, 内容量档位 2-6, 元信息）
WATERFALL_ITEMS = tuple(
    (title, key, ratio, f"作品 {i + 1:02d} · 演示")
    for i, (title, key, ratio) in enumerate((
        ("山间晨雾", "color.primary.subtle", 3),
        ("城市夜景", "color.success.subtle", 5),
        ("静物写生", "color.warning.subtle", 2),
        ("海边日落", "color.danger.subtle", 4),
        ("森林小径", "color.primary.subtle", 6),
        ("老街巷口", "color.success.subtle", 3),
        ("雨后屋檐", "color.warning.subtle", 5),
        ("雪原足迹", "color.danger.subtle", 2),
        ("沙漠星空", "color.primary.subtle", 4),
        ("湖畔倒影", "color.success.subtle", 6),
        ("窗台绿植", "color.warning.subtle", 3),
        ("巷尾猫影", "color.danger.subtle", 5),
    ))
)

# ---------------------------------------------------------------------------
# 图文左右
# ---------------------------------------------------------------------------

MEDIA_LEFT_RIGHT = dict(
    sections=(
        ("特性一：令牌驱动",
         "颜色、间距、圆角全部来自统一的设计令牌。组件与布局只引用语义键，"
         "不写死任何数值，因此换肤与品牌定制只需要改一份令牌表。",
         "color.primary.subtle"),
        ("特性二：双主题开箱即用",
         "亮色与暗色主题共用同一套语义键，切换时全局 QSS 与自绘色块同步刷新，"
         "无需重启应用，也无需为每个页面单独适配。",
         "color.success.subtle"),
        ("特性三：响应式断点",
         "布局按窗口宽度在 xs 到 xl 五档断点间自适应：网格重排列数、侧栏折叠、"
         "图文上下堆叠，全部在 resizeEvent 中完成。",
         "color.warning.subtle"),
    ),
    link_text="了解更多",
)
