# 需求完整性核对表（供验证代理逐项打勾）

## 布局预设（12）
- [ ] 顶部导航栏 top_nav_bar
- [ ] 圣杯布局 holy_grail
- [ ] 卡片网格 card_grid
- [ ] 单列堆叠 single_column
- [ ] 侧边栏布局 sidebar_layout
- [ ] 列表-详情 master_detail
- [ ] 分栏面板 split_panel
- [ ] 仪表盘网格 dashboard_grid
- [ ] 英雄区 hero_section
- [ ] 居中容器 centered_container
- [ ] 瀑布流 waterfall
- [ ] 图文左右 media_left_right

## 动画预设（52）
property.py（28）：fade_in 淡入淡出 / slide_in 滑入 / zoom_in 放大进场 / spring_pop 弹性弹出 / stagger_in 错落进场 / blur_in 模糊渐显 / mask_reveal 遮罩揭示 / hover_lift 悬停抬升 / button_morph_loading 按钮变形加载 / ripple 点击涟漪 / switch_toggle 开关切换 / pulse 脉冲 / bounce 弹跳 / swing 摇摆 / shake 错误抖动 / flash_highlight 闪烁高亮 / float_loop 漂浮元素 / pulse_glow 脉冲发光 / breathing 呼吸待机 / gradient_flow 流动渐变 / gradient_text_flow 渐变流动文字 / cross_fade 交叉淡化 / page_transition 页面切换 / slide_transition 滑动转场 / container_morph 容器变形 / shared_element 共享元素 / badge_pop 角标提示
painted.py（24）：SpinnerArc 旋转圈 / LikeBurstButton 点赞爆裂 / MagneticButton 磁吸按钮 / CheckDraw 对勾描绘 / BouncingDots 跳动的点 / SkeletonShimmer 骨架屏 / Shimmer 微光扫过 / ProgressStriped 进度条 / ParallaxArea 视差 / ScrollReveal 滚动渐显 / HorizontalScrollStrip 横向滚动 / StickyHeader 粘性固定 / ScrollProgressBar 滚动进度 / ScrollStoryArea 滚动叙事 / MarqueeLabel 跑马灯 / FluidBackground 流体 / TypewriterLabel 打字机 / TextDecodeLabel 文字解码 / NumberRollLabel 数字滚动 / LetterStaggerLabel 逐字进场 / CardTilt 卡片倾斜 / CubeRotator 立方体旋转 / FlipCard 翻转 / CoverFlow 立体轮播

## 组件（57）
输入：按钮 Button / 图标按钮 IconButton / 复选框 CheckBox / 单选按钮 RadioButton+RadioGroup / 开关 Switch / 输入框 LineEdit / 多行 TextArea / 数字输入 SpinBox+DoubleSpinBox / 下拉选择 ComboBox / 滑块 Slider / 日期选择 DatePicker / 时间选择 TimePicker / 评分 Rating / 颜色选择 ColorPicker / 自动完成 AutoComplete / 级联选择 Cascader / 穿梭框 Transfer / 上传 UploadWidget / 分段控制器 SegmentedControl / 表单 FormLayout
展示：头像 Avatar / 徽标数 Badge / 内容卡片 Card / 描述列表 Descriptions / 列表 ListWidget / 表格 Table / 树形控件 Tree / 时间轴 Timeline / 统计数值 Statistic / 日历 Calendar / 走马灯 Carousel / 图片 ImageView / 二维码 QRCodeView / 评论 CommentView / 折叠面板 Collapse / 空状态 Empty / 文字提示 set_tooltip / 气泡卡片 Popover
反馈：标签页 Tabs / 锚点 Anchor / 面包屑 Breadcrumb / 下拉菜单 DropdownButton / 导航菜单 NavMenu / 页头 PageHeader / 分页 Pagination / 步骤条 Steps / 警告提示 Alert / 对话框 Dialog / 抽屉 Drawer / 通知提醒框 Notification / 全局提示 Message / 气泡确认框 Popconfirm / 结果 ResultView / 骨架屏 Skeleton / 加载中 Spinner / 进度条 ProgressBar+CircleProgress / 漫游式引导 Tour

## 基础控件覆盖（demo 基础控件页 + 全局 QSS）
QPushButton/QToolButton/QRadioButton/QCheckBox/QLineEdit/QTextEdit/QPlainTextEdit/QSpinBox/QDoubleSpinBox/QComboBox/QFontComboBox/QDateEdit/QTimeEdit/QDateTimeEdit/QCalendarWidget/QSlider/QScrollBar/QDial/QProgressBar/QLabel/QTextBrowser/QGroupBox/QFrame/QTabWidget/QScrollArea/QStackedWidget/QToolBox/QDockWidget/QListWidget/QTreeWidget/QTableWidget/QMenuBar/QMenu/QToolBar/QStatusBar/QMessageBox/QFileDialog/QColorDialog/QFontDialog/QInputDialog + QtCharts（若可用）

## 文档与交付
- [ ] docs/Design.md（色彩/字体排版/间距/圆角/阴影/断点/动效/状态矩阵/暗色策略）
- [ ] docs/USAGE.md（安装/快速开始/主题切换/每组件最小示例）
- [ ] main.py 可运行、亮暗主题切换正常
- [ ] 全部 tests 退出码 0

## 结构（feat/restructure 重构后）
- [ ] InstructionX_UIKit/ 为纯 Kit 包：零假数据、零 Demo 逻辑、零 UI 演示操作
- [ ] 12 个布局全部 API 驱动（items/cards/sections 由调用方传入，空内容显示「在此放置内容」空占位）
- [ ] 示例数据集中在 demo/pages/layout_samples.py；demo 各演示页含「用法」代码标签
- [ ] charts 仅保留功能性 DEMO_MAP 内置示意地图（docstring 注明）
- [ ] README.md（项目根）含目录结构 / 安装 / 快速上手 / Demo 启动 / 测试运行说明
