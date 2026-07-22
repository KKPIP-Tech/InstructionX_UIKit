# Design — InstructionX_UIKit 设计规范

> 本文档是 InstructionX_UIKit 的完整设计规范，与 `InstructionX_UIKit/tokens.py`、`InstructionX_UIKit/theme.py` 中的数值严格一致。
> 所有令牌均可通过 `InstructionX_UIKit.theme.T(key)` 在运行时按当前主题取出（颜色为 `str`，数值为 `int`，阴影为 `dict`）。
> 键名规则：色彩 `color.*`、字阶 `font.*`、间距 `space.*`、圆角 `radius.*`、阴影 `shadow.*`、断点 `breakpoint.*`、动效 `duration.*` / `easing.*`。

## 目录

- [1. 设计原则](#1-设计原则)
- [2. 色彩](#2-色彩)
- [3. 字体排版](#3-字体排版)
- [4. 间距](#4-间距)
- [5. 圆角](#5-圆角)
- [6. 阴影](#6-阴影)
- [7. 断点](#7-断点)
- [8. 动效](#8-动效)
- [9. 组件状态矩阵](#9-组件状态矩阵)
- [10. 控件尺寸体系](#10-控件尺寸体系)
- [11. QSS 约定](#11-qss-约定)

## 1. 设计原则

1. **紧凑优先**：正文基准 13px，控件默认高度 32px，间距以 4pt 基线取小档位，信息密度面向桌面生产力应用，而非移动端营销页。
2. **现代中性**：大面积中性灰白底 + 单一品牌蓝作为强调色；圆角中等（6px 为主），阴影轻而低，避免厚重拟物。
3. **主题一致**：一切视觉数值来自令牌，禁止在代码中硬编码颜色 / 尺寸；亮、暗两套主题由同一份 QSS 模板参数化生成，切换主题后任意控件无需重写绘制逻辑。
4. **原生可实现性**：能用「Qt 原生控件子类化 + 动态属性 + 全局 QSS」表达的，绝不自绘；必须自绘的（开关、评分、时间轴等）在 `paintEvent` 中实时调用 `T()` 取色，并连接 `theme_changed` 信号触发 `update()`，保证主题切换即时生效。
5. **状态完备**：hover / pressed / disabled / focus / error / loading 六类状态每个交互控件都必须有可见表达，禁用态文字统一使用 `text.disabled`。

## 2. 色彩

### 2.1 语义令牌总表（与 tokens.py 完全一致）

| 令牌键（`T()` 参数） | 亮色 | 暗色 | 用途 |
|---|---|---|---|
| `color.bg.base` | `#FFFFFF` | `#15181E` | 窗口 / 页面基底背景 |
| `color.bg.subtle` | `#F6F7F9` | `#1B1F27` | 次背景：表头、斑马纹、状态栏 |
| `color.bg.muted` | `#EFF1F5` | `#232936` | 填充背景：hover 底色、禁用底、滑轨 |
| `color.bg.elevated` | `#FFFFFF` | `#1F242E` | 抬升面：卡片、输入框、菜单、弹层 |
| `color.border` | `#E3E6EB` | `#2C333F` | 常规边框 / 分割线 |
| `color.border.strong` | `#C9CFD8` | `#3D4654` | 强调边框：hover 边框、滚动条 |
| `color.text.primary` | `#1C2330` | `#E7EAF0` | 主要文字 |
| `color.text.secondary` | `#59636F` | `#A6AEBB` | 次要文字、表头、说明 |
| `color.text.tertiary` | `#98A0AC` | `#6E7684` | 占位符、辅助提示 |
| `color.text.disabled` | `#C2C8D0` | `#4A515C` | 禁用态文字 / 图标 |
| `color.primary` | `#3563E9` | `#5B87F2` | 品牌主色 |
| `color.primary.hover` | `#2B54C9` | `#7499F5` | 主色 hover |
| `color.primary.pressed` | `#21419E` | `#8AACF7` | 主色 pressed |
| `color.primary.subtle` | `#EDF1FE` | `#22304F` | 主色浅底：选中底、徽标底 |
| `color.on.primary` | `#FFFFFF` | `#FFFFFF` | 主色上的文字 / 图标 |
| `color.success` | `#1E9E6A` | `#3CBF8C` | 成功 |
| `color.success.hover` | `#177E55` | `#55D0A0` | 成功 hover |
| `color.success.subtle` | `#E5F6EE` | `#1C3A2F` | 成功浅底 |
| `color.warning` | `#E0962A` | `#F0B45A` | 警告 |
| `color.warning.subtle` | `#FCF3E2` | `#3D3220` | 警告浅底 |
| `color.danger` | `#D94848` | `#E86060` | 危险 / 错误 |
| `color.danger.hover` | `#B93A3A` | `#F07878` | 危险 hover |
| `color.danger.subtle` | `#FBECEC` | `#402424` | 危险浅底 |
| `color.overlay` | `rgba(28,35,48,0.45)` | `rgba(0,0,0,0.55)` | 模态遮罩 |

### 2.2 语义用法

| 语义 | 适用场景 | 典型组件 |
|---|---|---|
| primary | 页面主行动按钮、选中态、链接、focus 边框、进行中步骤 | `Button(variant="primary")`、Tabs 选中、Steps process |
| success | 操作成功反馈、正向趋势、完成步骤 | Alert success、ResultView success、Statistic 上升箭头 |
| warning | 需要留意但不阻断的提醒、高亮闪烁 | Alert warning、Notification warning、flash_highlight 默认色 |
| danger / error | 破坏性操作、校验失败、错误反馈 | Button(variant="danger")、Alert error、表单 error 边框 |

规则：

- 一个视图内 primary 级按钮不超过 1 个，其余用 default / text / link 降级。
- danger 仅用于不可逆或破坏性动作（删除、清空），普通「取消」不得使用。
- 状态浅底（`*.subtle`）只作背景，上面的文字用 `text.primary` 或对应语义色，禁止白字压浅底。
- `overlay` 仅用于模态遮罩（Dialog / Drawer），暗色下使用 55% 纯黑而不是更浅的颜色，保证弹层浮起感。

### 2.3 状态色

| 状态 | 取色规则 |
|---|---|
| hover | 主色控件用 `primary.hover` / `danger.hover` / `success.hover`（亮模式加深、暗模式提亮）；中性控件用 `bg.muted` 铺底或 `border.strong` 描边 |
| pressed | 主色控件用 `primary.pressed`（亮模式进一步加深；暗模式继续提亮）；中性控件用 `border` 级深底 |
| subtle | 选中 / 激活背景：`primary.subtle` 底 + `primary` 文字图标（菜单选中、列表选中、ToolButton checked） |
| disabled | 背景 `bg.muted`、边框 `border`、文字 `text.disabled`；主色按钮禁用态退化为中性灰，不再保留彩色 |
| focus | 边框变为 `primary`；QSS 不支持外发光（box-shadow），统一用 1px 主色边框表达 |

### 2.4 对比度说明

按 WCAG 2.x 相对亮度公式计算（亮色基底取 `bg.base=#FFFFFF`，暗色基底取 `bg.base=#15181E`）：

| 色彩对 | 亮色对比度 | 暗色对比度 | 评级 |
|---|---|---|---|
| text.primary / bg.base | 15.76:1 | 14.75:1 | AAA（正文） |
| text.secondary / bg.base | 6.11:1 | 7.95:1 | AA（正文） |
| text.tertiary / bg.base | 2.64:1 | 3.88:1 | 仅用于占位 / 辅助信息，不承载关键内容 |
| on.primary / primary | 5.11:1 | 3.39:1 | AA（大字号 / 按钮文字） |
| primary / bg.base | 5.11:1 | 5.24:1 | AA（链接、图标） |
| success / bg.base | 3.41:1 | 7.64:1 | AA（大字号 / 状态图标） |
| danger / bg.base | 4.22:1 | 5.31:1 | AA（正文级） |
| warning / bg.base | 2.45:1 | 9.63:1 | 亮模式仅用于图标 / 边框 / 大字号，不作小字正文 |

结论：正文一律使用 `text.primary` / `text.secondary`；`text.tertiary` 与亮模式 `warning` 不用于 13px 以下关键文字；暗模式下各语义色均经过提亮处理，反而拥有更高对比度。

### 2.5 暗色模式策略

1. **面层级提升**：暗色不是亮色的简单反相。`bg.base` 最深（#15181E），`subtle → muted → elevated` 逐层变亮，弹层 / 卡片用更亮的 `bg.elevated`（#1F242E）浮于基底之上，用「更亮」代替「白色」表达高度。
2. **主色提亮**：`primary` 由 #3563E9 提为 #5B87F2，`hover / pressed` 相应向更亮方向偏移（暗模式下越按越亮，与亮模式「越按越深」方向相反，但视觉重量一致）。
3. **阴影 alpha 调整**：暗色下阴影颜色改为纯黑 RGB=(0,0,0)，alpha 由 15%/25%/36% 提高到 40%/55%/70%，弥补深色背景下阴影可见性的下降。
4. **遮罩加深**：overlay 由 45% 深灰蓝改为 55% 纯黑。
5. **自绘组件**：必须在 `paintEvent` 内实时调用 `T()`，并在 `__init__` 连接 `ThemeManager.instance().theme_changed` 到 `self.update()`，禁止把颜色缓存为成员变量。

## 3. 字体排版

### 3.1 字族栈

| 用途 | QSS font-family 字符串 | 常量 |
|---|---|---|
| 正文 / 界面 | `"Segoe UI", "PingFang SC", "Microsoft YaHei", "Noto Sans CJK SC", "WenQuanYi Micro Hei", sans-serif` | `tokens.FONT_FAMILY` |
| 等宽 / 代码 | `"Cascadia Code", "JetBrains Mono", "Consolas", monospace` | `tokens.MONO_FAMILY` |

栈顺序覆盖 Windows（Segoe UI / 雅黑）、macOS（PingFang SC）、Linux（Noto Sans CJK / 文泉驿），`ThemeManager.apply()` 会按此栈设置应用级 `QFont`，并带 `QFont.SansSerif` 回退提示。

### 3.2 字阶（9 级，px）

| 令牌键 | 数值 | 用途 |
|---|---|---|
| `font.xs` | 11 | 进度条内文字、角标等最小信息 |
| `font.sm` | 12 | 辅助说明、表格次级信息、sm 尺寸控件 |
| `font.md` | 13 | 正文基准，md 尺寸控件默认字号 |
| `font.lg` | 14 | 强调正文、lg 尺寸控件 |
| `font.title.sm` | 15 | 卡片标题、分组标题 |
| `font.title.md` | 17 | 区块标题、对话框标题 |
| `font.title.lg` | 20 | 页面标题 |
| `font.display` | 24 | 展示级数字（Statistic）、大标题 |
| `font.hero` | 32 | 英雄区主标题 |

### 3.3 字重（4 档）

| 令牌键 | 数值 | 用途 |
|---|---|---|
| `font.weight.regular` | 400 | 正文 |
| `font.weight.medium` | 500 | 强调正文、按钮 |
| `font.weight.semibold` | 600 | 小标题、表头 |
| `font.weight.bold` | 700 | 标题、面包屑末级 |

### 3.4 行高

| 令牌键 | 数值 | 规则 |
|---|---|---|
| `font.line_height.body` | 1.5 | 正文与多行文本（TextArea、Alert 描述、评论内容） |
| `font.line_height.title` | 1.3 | 标题类单行 / 短行 |

### 3.5 控件默认字号对照

| 控件 | 字号 | 说明 |
|---|---|---|
| 按钮 sm / md / lg | 12 / 13 / 14 | 与 `font.sm / md / lg` 对应 |
| 输入框 sm / md / lg | 12 / 13 / 14 | QLineEdit / ComboBox / SpinBox 同规格 |
| 表格 / 树 / 列表 | 13 | 表头 13 + semibold |
| QToolTip | 12 | `font.sm` |
| QGroupBox 标题 | 13 + bold | 全局 QSS 定义 |
| 菜单项 / 下拉项 | 13 | 与正文一致 |
| Statistic 数值 | 24 | `font.display` |
| 页头标题 / 副标题 | 20 / 13 | `font.title.lg` / `font.md` |

## 4. 间距

### 4.1 4pt 基线与 12 档间距表

所有间距均为 4 的倍数（仅 `space.05=2` 用于微调），单位 px：

| 令牌键 | 数值 | 典型用途 |
|---|---|---|
| `space.0` | 0 | 无间距 |
| `space.05` | 2 | 图标与文字的微距、紧凑列表项间距 |
| `space.1` | 4 | 控件内部小填充、工具栏间距 |
| `space.2` | 8 | 控件内填充、复选框与文字间距、sm 按钮水平 padding |
| `space.3` | 12 | 输入框水平 padding、表单项间距、卡片内容区间距 |
| `space.4` | 16 | 卡片内边距、md 按钮水平 padding、弹层内边距 |
| `space.5` | 20 | lg 按钮水平 padding、卡片组间距 |
| `space.6` | 24 | 区块间距、页面小节间距 |
| `space.8` | 32 | 大区块间距、页面级留白 |
| `space.10` | 40 | 页面段落间距 |
| `space.12` | 48 | 英雄区上下留白 |
| `space.16` | 64 | 页面级大留白、空状态上下边距 |

### 4.2 常见模式

| 模式 | 取值 | 说明 |
|---|---|---|
| 卡片内边距 | 16（`space.4`） | Card / Alert / Popover 的内容边距 |
| 区块间距 | 24（`space.6`） | 页面内两个 Card / GroupBox 之间 |
| 表单项间距 | 12（`space.3`） | FormLayout 行间距 |
| 表单标签与控件 | 8（`space.2`） | 水平表单标签右间距 |
| 按钮组间距 | 8（`space.2`） | 对话框按钮区、工具栏按钮 |
| 页面边距 | 16 ~ 24 | 窗口内容外边距 |
| 标题与正文 | 8（`space.2`） | 卡片标题与内容之间 |
| 图标与文字 | 4 ~ 8 | 按钮内、菜单项内 |

## 5. 圆角

| 令牌键 | 数值(px) | 适用控件 |
|---|---|---|
| `radius.sm` | 4 | 小元素：复选框、菜单项、标签、进度条、QToolTip |
| `radius.md` | 6 | 主力圆角：按钮、输入框、下拉框、卡片边框、表格、分组框 |
| `radius.lg` | 8 | 弹层：菜单、下拉面板、Popover、抽屉头部 |
| `radius.xl` | 12 | 大型容器：对话框、抽屉面板、结果页插画底 |
| `radius.pill` | 999 | 胶囊 / 正圆：round 与 circle 形状按钮、徽标、头像、开关 |

说明：QSS 中 `shape="round"` / `shape="circle"` 选择器按档位输出 12 / 16 / 20px 半径（对应 sm/md/lg 的半高），视觉等同 pill。

## 6. 阴影

### 6.1 三级参数表

阴影通过 `theme.apply_shadow(widget, level)` 应用，底层为 `QGraphicsDropShadowEffect`；令牌值为 dict：`{"blur", "offset", "color": (r, g, b, a)}`。

| 级别 | blur(px) | offset(x,y) | 亮色颜色 | 暗色颜色 |
|---|---|---|---|---|
| `shadow.sm` | 6 | (0, 1) | (16, 24, 40, 15%) | (0, 0, 0, 40%) |
| `shadow.md` | 16 | (0, 4) | (16, 24, 40, 25%) | (0, 0, 0, 55%) |
| `shadow.lg` | 32 | (0, 8) | (16, 24, 40, 36%) | (0, 0, 0, 70%) |

（令牌中 alpha 以 0-255 存储：亮色 38 / 64 / 92，暗色 102 / 140 / 179。）

### 6.2 适用场景与亮暗差异

| 级别 | 适用场景 |
|---|---|
| sm | 常驻抬升：卡片 hoverable 悬停、输入框聚焦物、徽章 |
| md | 浮层：下拉菜单、Popover、Notification、Message |
| lg | 模态：Dialog、Drawer、Tour 气泡 |

亮暗差异：亮色主题为蓝灰投影（RGB=16,24,40），暗色主题为纯黑投影且 alpha 显著提高（40%/55%/70%），保证在深色面上阴影仍然可辨。切换主题后需对已应用阴影的控件重新调用 `apply_shadow()`（自绘组件如 Popover / Dialog 已在内部处理）。

注意：一个 QWidget 同时只能挂载一个 `QGraphicsEffect`，阴影会与动画库的缩放 / 模糊 / 透明度效果互相替换，组合使用时见 USAGE.md 常见问题。

## 7. 断点

### 7.1 五档断点表（按窗口宽度 px）

| 断点 | 宽度范围 | 令牌键（最小阈值） | 典型设备 |
|---|---|---|---|
| xs | < 640 | `breakpoint.xs` = 0 | 窄窗口 / 分屏小窗 |
| sm | 640 - 767 | `breakpoint.sm` = 640 | 小平板竖屏 |
| md | 768 - 1023 | `breakpoint.md` = 768 | 平板横屏 / 小桌面窗 |
| lg | 1024 - 1439 | `breakpoint.lg` = 1024 | 常规桌面 |
| xl | >= 1440 | `breakpoint.xl` = 1440 | 宽屏桌面 |

判定接口：`Breakpoint.from_width(w) -> "xs"/"sm"/"md"/"lg"/"xl"`。布局在 `resizeEvent` 中调用并仅在档位变化时重排。

### 7.2 各布局的响应行为摘要

| 布局 | xs | sm | md | lg / xl |
|---|---|---|---|---|
| 顶部导航栏 TopNavBar | 菜单折叠进「更多」，隐藏搜索 | 菜单展开，仍隐藏搜索 | 菜单展开，显示搜索 | 同 md |
| 圣杯 HolyGrail | 双侧栏隐藏 | 仅左侧栏 | 双侧栏显示 | 同 md |
| 卡片网格 CardGrid | 1 列 | 2 列 | 3 列 | 4 列 |
| 单列堆叠 SingleColumn | 内容限宽 760 居中，宽度自适应 | 同左 | 同左 | 同左 |
| 侧边栏 SidebarLayout | 侧栏折叠为 56px 图标栏 | 同 xs | 侧栏展开 208px | 同 md |
| 列表-详情 MasterDetail | 垂直堆叠 | 同 xs | 水平分栏（QSplitter 可调） | 同 md |
| 分栏面板 SplitPanel | 单栏 | 2 栏 | 3 栏 | 3 栏 |
| 仪表盘网格 DashboardGrid | 全部卡片通栏（跨 12）逐行堆叠 | 同 xs | 统计卡跨 6（2x2）+ 跨 8/4 + 跨 6/6 + 通栏 | 统计卡跨 3（1x4）+ 跨 8/4 + 跨 6/6 + 通栏 |
| 英雄区 HeroSection | 上下排布（文案在上） | 同 xs | 左右排布（文案左、插图右） | 同 md |
| 居中容器 CenteredContainer | 1 列 | 2 列 | 3 列 | 3 列 |
| 瀑布流 Waterfall | 2 列 | 2 列 | 3 列 | 4 列 |
| 图文左右 MediaLeftRight | 上下堆叠 | 同 xs | 图左文右 / 图右文左交替 | 同 md |

## 8. 动效

### 8.1 时长（5 档，ms）

| 令牌键 | 数值 | 用途 |
|---|---|---|
| `duration.instant` | 80 | 微反馈：涟漪扩散、按压缩放 |
| `duration.fast` | 120 | hover 过渡、开关切换、Tab 指示块滑动 |
| `duration.normal` | 200 | 默认：淡入淡出、滑入、提示条进出 |
| `duration.slow` | 320 | 页面切换、抽屉 / 对话框进出、抖动 |
| `duration.slower` | 480 | 弹性入场、弹跳、大型容器变形 |

### 8.2 缓动映射（QEasingCurve.Type）

| 令牌键 | Qt 曲线 | 视觉感受 | 用途 |
|---|---|---|---|
| `easing.standard` | `QEasingCurve.OutCubic` | 快进慢出 | 绝大多数过渡的默认曲线 |
| `easing.entrance` | `QEasingCurve.OutQuint` | 更强的进场减速 | 页面 / 弹层入场 |
| `easing.spring` | `QEasingCurve.OutBack` | 过冲回弹 | 弹性弹出、角标弹入、开关回弹 |
| `easing.emphasis` | `QEasingCurve.OutQuart` | 强调型减速 | 需要被注意的强调动画 |
| `easing.linear` | `QEasingCurve.Linear` | 匀速 | 旋转、跑马灯、条纹流动等循环动画 |

### 8.3 各类动画预设的推荐时长

| 类别 | 预设（anim/property.py） | 推荐时长 | 默认缓动 |
|---|---|---|---|
| 淡入淡出 | fade_in / fade_out / cross_fade | normal(200) | standard |
| 位移进入 | slide_in / mask_reveal | normal ~ slow | entrance |
| 缩放进入 | zoom_in / badge_pop | normal | standard / spring |
| 弹性 | spring_pop | slow(320) | spring |
| 交错入场 | stagger_in（interval=60） | normal（单项） | entrance |
| 强调一次 | pulse / bounce / swing | slow ~ slower | emphasis / OutBounce |
| 错误反馈 | shake / flash_highlight | slow(320) / fast | standard |
| 无限循环 | float_loop / pulse_glow / breathing / gradient_flow | 1600 ~ 2400 | InOutSine / linear |
| 页面过渡 | page_transition | slow(320) | entrance |
| 加载变形 | button_morph_loading | normal（变形）+ 900（呼吸） | standard |

## 9. 组件状态矩阵

六类状态的统一视觉表达规则（QSS 动态属性 / 伪状态见 §11）：

| 状态 | 视觉表达 | 实现方式 |
|---|---|---|
| hover | 边框加深（`border.strong`）或主色描边；填充类控件底色变为 `*.hover`；中性按钮 / 菜单项铺 `bg.muted`；hoverable 卡片叠加 sm 阴影 | QSS `:hover` |
| pressed | 主色控件底色 `*.pressed`；中性控件铺 `border` 级深底；可配 1~2px 下沉缩放（switch_toggle 预设） | QSS `:pressed` |
| disabled | 底 `bg.muted`、边 `border`、文字 `text.disabled`；主色按钮退化为灰；禁止仅降透明度（Qt 中不可见度不可控） | QSS `:disabled` / `setEnabled(False)` |
| focus | 边框 1px `primary`；不做外发光（QSS 不支持 box-shadow） | QSS `:focus` |
| error | 边框 `danger`，hover 时 `danger.hover`；表单组件下方出现 12px 红色错误行；可接 shake 动画 | 动态属性 `[error="true"]`（LineEdit / FormLayout） |
| loading | 按钮进入加载态：文字清空、宽度收缩为正方形、自绘旋转弧（Button.set_loading）或呼吸透明度（button_morph_loading）；期间禁用点击 | 组件属性 / 动画预设 |

补充：

- 选中（checked / selected）用 `primary.subtle` 底 + `primary` 文字，如菜单项、列表项、分段控件指示块。
- 只读（read_only）与禁用区分：只读保留正文色与边框，仅禁止编辑（Rating、LineEdit）。
- 禁用态必须对自绘组件同样生效：`paintEvent` 中检测 `isEnabled()` 并改用 `text.disabled` 绘制。

## 10. 控件尺寸体系

三档高度规范（输入类控件与按钮统一对齐，方便水平混排）：

| 档位 | 总高(px) | 字号 | 水平 padding | 适用场景 |
|---|---|---|---|---|
| sm | 24 | 12 | 8 | 紧凑表格工具栏、密集表单 |
| md | 32 | 13 | 12 ~ 16 | 默认档，绝大多数场景 |
| lg | 40 | 14 | 20 | 登录页、主操作区、营销页 |

实现细节（theme.py 中的口径）：

- QSS 盒模型为内容盒：`min-height/max-height = 总高 - 2*边框(1px)`，按钮与输入框内容盒为 22 / 30 / 38。
- `QAbstractSpinBox` 系列（SpinBox / DateEdit / TimeEdit）在 Fusion 样式下额外增高 3px，QSS 对其使用 19 / 27 / 35 的内容盒口径对齐总高。
- Switch 仅 sm / md 两档（32x16 / 44x22 滑轨）；Avatar 提供 sm/md/lg（24/32/40）及像素自定义；Spinner 按 sm/md/lg 对应 16/24/32。
- 尺寸一律通过 `set_property(widget, "size", "sm"/"md"/"lg")` 或组件构造参数 `size=` 设置，内部自动映射 `uiksize` 动态属性（原因见 §11.3）。

## 11. QSS 约定

### 11.1 变体与尺寸：动态属性选择器

全局 QSS（`build_qss()` 输出）通过 Qt 动态属性选择器实现变体，不使用 objectName 硬编码：

```css
QPushButton[variant="primary"] { ... }
QPushButton[uiksize="sm"] { ... }
QPushButton[shape="circle"] { ... }
QLineEdit[error="true"] { border-color: #D94848; }
QProgressBar[status="success"]::chunk { ... }
```

使用规则：

1. 设置属性必须走 `theme.set_property(widget, name, value)`——它会在赋值后执行 `unpolish/polish` 刷新样式，并自动处理别名映射；直接 `setProperty()` 不会触发 QSS 重算。
2. 组件库内部均已封装好（如 `Button(variant="primary", size="sm")`），业务代码通常无需手动调用。
3. 新增自定义变体时，优先复用已有选择器；新增选择器要同时在亮 / 暗两套令牌下验证。

### 11.2 常用动态属性一览

| 属性 | 取值 | 作用控件 |
|---|---|---|
| `variant` | primary / default / dashed / text / link / danger | QPushButton（Button）；primary / default / danger（QToolButton / IconButton） |
| `uiksize`（别名 `size`） | sm / md / lg | QPushButton / QToolButton / QLineEdit / QComboBox / QSpinBox 等输入按钮类 |
| `shape` | round / circle | QPushButton / QToolButton |
| `error` | true / false | QLineEdit（LineEdit.set_error 封装） |
| `status` | success / warning / error | QProgressBar（ProgressBar.set_status 封装） |
| `role` | secondary / tertiary / hint | QLabel（文字降级） |

### 11.3 `size` 属性冲突说明（重要）

`size` 是 QWidget 的内置 `Q_PROPERTY`（读写窗口尺寸的 `QSize`），对其调用 `setProperty("size", "sm")` 会类型转换失败，**不会**生成动态属性，因此 QSS 选择器 `[size="sm"]` 在 Qt 中永远命中不了。

约定做法：

- 一律使用 `set_property(widget, "size", v)`，内部自动改写为 `uiksize` 动态属性；
- 全局 QSS 同时输出 `[size="..."]` 与 `[uiksize="..."]` 两组选择器（前者兑现 SPEC 契约文本，后者是实际生效路径）；
- 组件的 `size=` 构造参数与 `set_size()` 方法均已走该映射，业务代码无需感知。

### 11.4 主题感知自绘约定

- QSS 表达不了的（圆弧、进度环、星级、时间轴），在 `paintEvent` 中用 `T("color.xxx")` 取色绘制；
- 构造函数中连接 `ThemeManager.instance().theme_changed` 到 `self.update()`（组件库已统一封装为 `_connect_theme(widget, slot)` 辅助函数）；
- 自绘禁用态必须检测 `isEnabled()` 并切换为 `text.disabled`；
- `T()` 取的是「当前主题」令牌，主题切换后 QSS 由 `ThemeManager.set_mode()` 自动重建并设置到 QApplication，无需业务代码干预。
