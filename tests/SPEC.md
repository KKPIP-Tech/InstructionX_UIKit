# SPEC — InstructionX_UIKit（设计系统 + 组件库 + 布局库 + 动画库 + Demo 演示程序）

> 本文件是唯一事实来源。所有子代理必须严格遵循其中的接口契约、令牌数值与文件归属。
> 禁止修改不属于自己的文件；禁止新增第三方依赖（qrcode 除外）；禁止使用 emoji；UI 文案与注释使用中文。

## 1. 项目结构

```
pyside6_ui_kit/
├── SPEC.md
├── requirements.txt
├── main.py                     # Demo 入口（demo 代理）
├── InstructionX_UIKit/
│   ├── tokens.py               # 设计令牌（core 代理）
│   ├── theme.py                # 主题管理 + QSS 生成（core 代理）
│   ├── components/             # 组件库（A/B/C 三个代理，按文件归属）
│   ├── layouts/                # 12 个布局预设（layouts 代理）
│   └── anim/
│       ├── property.py         # 属性类动画（anim-A 代理）
│       └── painted.py          # 自绘/定时器类动画（anim-B 代理）
├── demo/                    # Demo 应用（demo 代理）
│   ├── main_window.py
│   └── pages/
├── tests/                      # 每个代理附带 test_<area>.py（离屏构造 + 截图）
└── docs/
    ├── Design.md               # 设计规范文档（docs 代理）
    └── USAGE.md                # 使用方法（docs 代理）
```

运行与测试一律使用 `QT_QPA_PLATFORM=offscreen`。截图用 `widget.grab()`（离屏可用）。

## 2. 设计令牌（InstructionX_UIKit/tokens.py 必须实现的精确数值）

### 2.1 色彩（语义令牌，亮/暗两套）

| 令牌 | 亮色 | 暗色 |
|---|---|---|
| bg.base | #FFFFFF | #15181E |
| bg.subtle | #F6F7F9 | #1B1F27 |
| bg.muted | #EFF1F5 | #232936 |
| bg.elevated | #FFFFFF | #1F242E |
| border | #E3E6EB | #2C333F |
| border.strong | #C9CFD8 | #3D4654 |
| text.primary | #1C2330 | #E7EAF0 |
| text.secondary | #59636F | #A6AEBB |
| text.tertiary | #98A0AC | #6E7684 |
| text.disabled | #C2C8D0 | #4A515C |
| primary | #3563E9 | #5B87F2 |
| primary.hover | #2B54C9 | #7499F5 |
| primary.pressed | #21419E | #8AACF7 |
| primary.subtle | #EDF1FE | #22304F |
| on.primary | #FFFFFF | #FFFFFF |
| success | #1E9E6A | #3CBF8C |
| success.hover | #177E55 | #55D0A0 |
| success.subtle | #E5F6EE | #1C3A2F |
| warning | #E0962A | #F0B45A |
| warning.subtle | #FCF3E2 | #3D3220 |
| danger | #D94848 | #E86060 |
| danger.hover | #B93A3A | #F07878 |
| danger.subtle | #FBECEC | #402424 |
| overlay | rgba(28,35,48,0.45) | rgba(0,0,0,0.55) |

### 2.2 字体排版
- 字族（QSS font-family 字符串）：`"Segoe UI", "PingFang SC", "Microsoft YaHei", "Noto Sans CJK SC", "WenQuanYi Micro Hei", sans-serif`
- 等宽字族：`"Cascadia Code", "JetBrains Mono", "Consolas", monospace`
- 字阶（px）：xs=11, sm=12, md=13（正文基准）, lg=14, title.sm=15, title.md=17, title.lg=20, display=24, hero=32
- 字重：regular=400, medium=500, semibold=600, bold=700
- 行高：正文 1.5，标题 1.3

### 2.3 间距（4pt 基线，px）
0, 2, 4, 8, 12, 16, 20, 24, 32, 40, 48, 64 → 键名 `space.0, space.05, space.1, space.2, space.3, space.4, space.5, space.6, space.8, space.10, space.12, space.16`

### 2.4 圆角
radius.sm=4, radius.md=6, radius.lg=8, radius.xl=12, radius.pill=999

### 2.5 阴影（用于 QGraphicsDropShadowEffect）
- shadow.sm: blur=6, offset=(0,1), color=(16,24,40,15%)
- shadow.md: blur=16, offset=(0,4), color=(16,24,40,25%)
- shadow.lg: blur=32, offset=(0,8), color=(16,24,40,36%)
- 暗色主题 color 的 alpha 分别 40%、55%、70%，RGB=(0,0,0)
- 契约：`theme.apply_shadow(widget, level)`，level ∈ {"sm","md","lg"}

### 2.6 断点（窗口宽度 px）
xs<640, sm 640-767, md 768-1023, lg 1024-1439, xl≥1440
- 契约：`tokens.Breakpoint.from_width(w:int) -> str`，返回 "xs"/"sm"/"md"/"lg"/"xl"

### 2.7 动效
- 时长(ms)：instant=80, fast=120, normal=200, slow=320, slower=480
- 缓动映射：standard=QEasingCurve.OutCubic, entrance=QEasingCurve.OutQuint, spring=QEasingCurve.OutBack, emphasis=QEasingCurve.OutQuart, linear=QEasingCurve.Linear

### 2.8 tokens.py 契约
```python
LIGHT: dict[str, object]   # 键如 "color.primary"、"space.4"、"radius.md"
DARK:  dict[str, object]
FONT_FAMILY: str
MONO_FAMILY: str
class Breakpoint: @staticmethod from_width(w) -> str
DURATION: dict[str,int]    # instant/fast/normal/slow/slower
EASING: dict[str, QEasingCurve.Type]
```

## 3. 主题系统（InstructionX_UIKit/theme.py 契约）

```python
class ThemeManager(QObject):
    theme_changed = Signal(str)      # 发射 "light"/"dark"
    @classmethod
    def instance(cls) -> ThemeManager
    @property
    def mode(self) -> str            # "light" | "dark"，默认 "light"
    def set_mode(self, mode: str) -> None
    def toggle(self) -> None
    def apply(self, app: QApplication) -> None   # 生成并设置全局 QSS
    @property
    def tokens(self) -> dict         # 当前模式令牌字典

def T(key: str):                     # 取当前主题令牌值（颜色为 str，数值为 int）
def build_qss(tokens: dict) -> str   # 全局 QSS（见 §4）
def apply_shadow(widget: QWidget, level: str = "sm") -> None
```
- 自绘组件在 paintEvent 中实时调用 `T()`，并在 __init__ 中 `ThemeManager.instance().theme_changed.connect(lambda *_: self.update())`。
- `set_mode` 后若已 apply 过则自动重新生成 QSS 设置到 QApplication。

## 4. 全局 QSS 约定（build_qss 必须覆盖）
- 基座：QWidget 背景/文字、QToolTip、QMenu、QScrollBar（细滚动条 8px，hover 变深）、QSplitter::handle。
- 通过 dynamic property 选择器实现变体，例如：
  - `QPushButton[variant="primary"|"default"|"dashed"|"text"|"link"|"danger"]`
  - `QPushButton[size="sm"|"md"|"lg"]`，`QPushButton[shape="circle"|"round"]`
  - 状态：`:hover`、`:pressed`、`:disabled`
- 覆盖 Qt 基础控件：QLineEdit/QTextEdit/QPlainTextEdit/QSpinBox/QDoubleSpinBox/QComboBox/QDateEdit/QTimeEdit/QDateTimeEdit/QSlider/QProgressBar/QCheckBox/QRadioButton/QTabWidget/QTabBar/QTableView/QTreeView/QListView/QHeaderView/QGroupBox/QFrame/QCalendarWidget/QMenuBar/QToolBar/QStatusBar/QDockWidget/QMessageBox 内控件。
- 输入控件统一：高 32px（size=md），sm=24，lg=40；边框 border，focus 时 primary 边框 + 不实现外发光（QSS 不支持，用边框色表达）。

## 5. 组件契约（InstructionX_UIKit/components/）

通用约定：
- 每个组件一个文件，文件归属见下表；类名、文件名单词小写下划线。
- 尽量用「Qt 原生控件子类化 + objectName/dynamic property + 全局 QSS」实现；必须自绘时按 §3 的主题感知方式。
- 每个公开类带中文 docstring：用途、主要参数、示例 3 行。
- 组件尺寸遵循 §4 的高度体系；禁用态必须可见（T("text.disabled")）。

### 5.1 输入与按钮（components-inputs 分支，agent A）
| 文件 | 类 | 说明 |
|---|---|---|
| button.py | Button(QPushButton) | variant: primary/default/dashed/text/link/danger；size；loading 状态（自绘旋转弧）；block(撑满) |
| icon_button.py | IconButton(QToolButton) | 图标按钮，variant/size/shape，支持 QIcon 或文本符号 |
| checkbox.py | CheckBox(QCheckBox) | 三态支持；QSS 自绘指示框 |
| radio.py | RadioButton(QRadioButton), RadioGroup(QButtonGroup 便捷封装) | |
| switch.py | Switch(QAbstractButton) | 自绘滑块开关，checked 属性 + 动画，size sm/md |
| line_edit.py | LineEdit(QLineEdit) | 前缀/后缀图标槽、清除按钮、密码切换、error 状态（红色边框） |
| text_area.py | TextArea(QTextEdit) | 自适应高度选项、字数统计 |
| spin_box.py | SpinBox(QSpinBox), DoubleSpinBox(QDoubleSpinBox) | 统一高度与按钮样式 |
| combo_box.py | ComboBox(QComboBox) | 下拉样式、搜索过滤选项 |
| slider.py | Slider(QSlider) | 刻度/提示值；QSS 精致滑轨 |
| date_picker.py | DatePicker(QDateEdit) | 弹出自定义样式 QCalendarWidget |
| time_picker.py | TimePicker(QTimeEdit) | |
| rating.py | Rating(QWidget) | 自绘星级，value/changed 信号，允许半星选项 |
| color_picker.py | ColorPicker(QWidget) | 色块按钮 + QColorDialog，colorChanged 信号 |
| auto_complete.py | AutoComplete(LineEdit) | QCompleter 封装，延迟过滤 |
| cascader.py | Cascader(QWidget) | 级联选择（按钮 + 多级 QMenu），pathChanged 信号 |
| transfer.py | Transfer(QWidget) | 穿梭框：双 QListWidget + 左右移动按钮 |
| upload.py | UploadWidget(QWidget) | 拖拽区 + 选择文件按钮，filesChanged 信号，列表显示文件名与移除 |
| segmented.py | SegmentedControl(QWidget) | 分段控制器，自绘滑动指示块，currentChanged 信号 |
| form.py | FormLayout(QFormLayout 增强), FormItem 校验辅助 | required 星号、错误提示行 |

### 5.2 数据展示（components-display 分支，agent B）
| 文件 | 类 | 说明 |
|---|---|---|
| avatar.py | Avatar(QLabel) | 圆形/方形、图片/文字/图标回退、size |
| badge.py | Badge(QWidget) | 徽标数（包裹任意子控件角标）、独立点模式、max 值 99+ |
| card.py | Card(QFrame) | title/extra/footer 槽，hoverable、bordered 变体 |
| descriptions.py | Descriptions(QWidget) | 描述列表，列数自适应 |
| list_view.py | ListWidget(QListWidget) | 统一项高、hover、选中样式、ItemDelegate 辅助 |
| table.py | Table(QTableWidget) | 斑马纹、紧凑行高、排序、空状态占位 |
| tree.py | Tree(QTreeWidget) | 缩进线样式、复选支持 |
| timeline.py | Timeline(QWidget) | 自绘时间轴，节点颜色/图标，pending 尾部 |
| statistic.py | Statistic(QWidget) | 标题+大数值+前后缀+趋势箭头 |
| calendar.py | Calendar(QCalendarWidget) | 中文表头、今日高亮 |
| carousel.py | Carousel(QWidget) | 走马灯：QStackedLayout + 指示点 + 左右箭头，autoplay |
| image_view.py | ImageView(QLabel) | 圆角图片、加载失败占位、hover 预览蒙层 |
| qrcode_view.py | QRCodeView(QWidget) | qrcode 库生成，容错级别参数 |
| comment.py | CommentView(QWidget) | 评论：头像+作者+时间+内容+操作行，可嵌套回复 |
| collapse.py | Collapse(QWidget) | 折叠面板（手风琴可选），动画展开 |
| empty.py | Empty(QWidget) | 空状态：自绘插画（简单几何）+描述+操作按钮槽 |
| tooltip.py | 工具函数 set_tooltip(widget, text) | 富样式 QToolTip（QSS 统一） |
| popover.py | Popover(QWidget) | 气泡卡片：相对锚点弹出（QFrame,Popup），带箭头 |

### 5.3 导航与反馈（components-feedback 分支，agent C）
| 文件 | 类 | 说明 |
|---|---|---|
| tabs.py | Tabs(QTabWidget) | 三种样式：line/card/segmented |
| anchor.py | Anchor(QWidget) | 锚点：配合 QScrollArea 高亮当前段 |
| breadcrumb.py | Breadcrumb(QWidget) | 面包屑，分隔符可配，末级加粗 |
| dropdown.py | DropdownButton(QPushButton) | 下拉菜单按钮（QMenu 封装），菜单项带图标/快捷键/危险项 |
| nav_menu.py | NavMenu(QWidget) | 侧边导航菜单：分组、折叠、选中条指示 |
| page_header.py | PageHeader(QWidget) | 页头：返回、标题、副标题、面包屑槽、操作区 |
| pagination.py | Pagination(QWidget) | 分页：页码省略、跳转输入、每页条数 |
| steps.py | Steps(QWidget) | 步骤条：水平/垂直，wait/process/finish/error 状态 |
| alert.py | Alert(QFrame) | 警告提示：info/success/warning/error，可关闭、带操作 |
| dialog.py | Dialog(QDialog) | 统一对话框：标题栏、按钮区，confirm()/info() 静态便捷方法 |
| drawer.py | Drawer(QDialog) | 抽屉：四边滑入，宽度可拖拽 |
| notification.py | Notification 管理器 | 通知提醒框：右上角堆叠弹出，自动消失，进度条 |
| message.py | Message 管理器 | 全局提示：顶部居中轻提示 info/success/warning/error |
| popconfirm.py | Popconfirm(Popover 式) | 气泡确认框：确认/取消 |
| result.py | ResultView(QWidget) | 结果页：success/error/info/404 自绘图标+标题+副标题+操作 |
| skeleton.py | Skeleton(QWidget) | 骨架屏：标题/段落/头像/按钮形状，微光动画 |
| spinner.py | Spinner(QWidget) | 加载中：旋转弧，size，tip 文案 |
| progress_bar.py | ProgressBar(QProgressBar), CircleProgress(QWidget) | 直线/环形进度，状态色 |
| tour.py | Tour(QWidget) | 漫游式引导：高亮目标控件 + 步骤气泡，上一步/下一步/跳过 |

## 6. 布局契约（InstructionX_UIKit/layouts/，layouts 代理）

每个文件一个函数 `create_xxx(parent=None) -> QWidget`，内部使用示例占位内容（卡片/色块/文本），并导出同名 QWidget 子类（便于复用）。所有布局响应窗口尺寸（按 §2.6 断点调整列数/是否折叠侧栏），在 resizeEvent 中处理。

| 文件 | 名称 | 要点 |
|---|---|---|
| top_nav_bar.py | 顶部导航栏 | Logo+菜单+搜索+头像；窗口级示例 |
| holy_grail.py | 圣杯布局 | header/footer/双侧栏/主区，QSplitter 可调 |
| card_grid.py | 卡片网格 | 按断点 1/2/3/4 列 |
| single_column.py | 单列堆叠 | 最大宽 760 居中，垂直节奏 spacing |
| sidebar_layout.py | 侧边栏布局 | 左 NavMenu + 右内容，可折叠为图标栏 |
| master_detail.py | 列表-详情 | 左列表右详情，窄断点堆叠 |
| split_panel.py | 分栏面板 | QSplitter 2-3 栏，记忆比例 |
| dashboard_grid.py | 仪表盘网格 | 12 列网格，卡片跨 3/4/6/12 |
| hero_section.py | 英雄区 | 大标题+副文案+双按钮+右侧插图占位 |
| centered_container.py | 居中容器 | 内容限宽 960 居中（剧中容器） |
| waterfall.py | 瀑布流 | 2-4 列不等高卡片（QGridLayout 按列分配） |
| media_left_right.py | 图文左右 | 图左文右/图右文左交替段落 |

## 7. 动画契约（InstructionX_UIKit/anim/）

统一约定：每个预设一个函数，签名为 `def <name>(target, **opts)`；函数内部即启动动画并返回动画/定时器句柄（便于 stop）。所有时长默认取 DURATION，缓动取 EASING。docstring 中文说明用途与参数。不得阻塞事件循环。

### 7.1 property.py（anim-A 代理，基于 QPropertyAnimation/QVariantAnimation/QParallelAnimationGroup）
fade_in, fade_out, slide_in(direction: left/right/up/down), zoom_in, spring_pop, stagger_in(children, interval=60), blur_in(QGraphicsBlurEffect 半径→0), mask_reveal(direction), hover_lift(widget, dy=4 安装事件过滤器), button_morph_loading(button)，ripple(button 自绘涟漪叠加层), switch_toggle(switch), pulse, bounce, swing, shake, flash_highlight, float_loop, pulse_glow(阴影半径呼吸), breathing(opacity 呼吸), gradient_flow(背景渐变色相位动画, 自绘), gradient_text_flow, cross_fade(a→b), page_transition(stacked, index, kind=fade/slide), slide_transition, container_morph(widget, 大小/圆角变形), shared_element(widget, 从几何A到B), badge_pop(角标弹入)

### 7.2 painted.py（anim-B 代理，基于 QTimer + paintEvent 自绘控件）
SpinnerArc(旋转圈), LikeBurstButton(点赞爆裂：心形+粒子), MagneticButton(磁吸按钮：随鼠标位移), CheckDraw(对勾描绘), BouncingDots(跳动的点), SkeletonShimmer(骨架屏微光扫过，可被 components 复用), Shimmer(任意区域微光扫过), ProgressStriped(条纹流动进度条), ParallaxArea(视差滚动容器), ScrollReveal(QScrollArea 内子控件进入视口渐显), HorizontalScrollStrip(横向滚动条带), StickyHeader(粘性固定头), ScrollProgressBar(滚动进度条), ScrollStoryArea(滚动叙事：按滚动驱动时间线), MarqueeLabel(跑马灯), FluidBackground(流体渐变背景，正弦叠加), TypewriterLabel(打字机), TextDecodeLabel(文字解码), NumberRollLabel(数字滚动 count-up), LetterStaggerLabel(逐字进场), CardTilt(卡片倾斜，随鼠标 3D 透视), CubeRotator(立方体旋转，两画面), FlipCard(翻转), CoverFlow(立体轮播，3-5 项透视堆叠)

## 8. Demo 契约（demo 代理）

- `main.py`：`QT_QPA_PLATFORM` 不强制（用户本机运行）；创建 QApplication → ThemeManager.instance().apply(app) → MainWindow(1280×800) 显示。
- MainWindow：顶部条（标题「InstructionX_UIKit」+ 主题切换 SegmentedControl 亮/暗 + GitHub 式版本标签 v1.0）；左侧 QTreeWidget 导航（分类：设计令牌 / 布局预设 / 组件·输入 / 组件·展示 / 组件·反馈 / 动画·属性 / 动画·自绘 / 基础控件 / 图表）；右侧 QStackedWidget。
- `demo/pages/`：每组件/布局/动画一个页面函数 `create_page() -> QWidget`；页面 = 标题 + 说明 + 分组演示（GroupBox/Card 分区，紧凑）。
- 动画页：卡片网格，每卡一个演示元件 + 「播放」按钮重放。
- 基础控件页：展示 QSS 美化后的 Qt 原生控件全家福（QPushButton/QLineEdit/QSpinBox/QSlider/QProgressBar/QTableWidget/QTreeWidget/QCalendarWidget/QTabWidget/QGroupBox/QDockWidget/QMessageBox 触发等）。
- 图表页：若 PySide6.QtCharts 可用，展示折线/平滑/面积/柱状/堆叠/饼/散点；否则展示「未安装 QtCharts」提示页（try/except 导入）。
- 设计令牌页：色板、字阶、间距、圆角、阴影、断点、动效可视化。

## 9. 测试契约（每个实现代理必须附带并运行）

- `tests/test_<area>.py`：无 pytest 依赖，直接 `python tests/test_<area>.py` 可跑；offscreen 下实例化本代理负责的每个组件/布局/动画 1 次，`grab()` 保存到 `tests/shots/<name>.png`；任何异常即失败退出码 1。
- 代理交付前必须实际运行并保证 0 错误、0 段错误。

## 10. 文档契约（docs 代理）

- `docs/Design.md`：完整设计规范——设计原则、色彩（含对比度说明与语义用法）、字体排版、间距、圆角、阴影、断点、动效（时长/缓动表）、组件状态矩阵（hover/pressed/disabled/focus/error）、暗色模式策略。
- `docs/USAGE.md`：安装（pip install -r requirements.txt）、快速开始（main.py）、主题切换、每个组件/布局/动画的最小用法示例代码（从 demo 页面提取真实可运行片段）。
