# InstructionX_UIKit

基于 PySide6（Qt for Python）的纯桌面 UI 组件库：设计令牌 + 亮/暗双主题、59 个组件、13 个响应式布局预设、52 个动画预设、原生图表引擎、蓝图节点图编辑器与仿 VS Code 代码编辑器。

![Python](https://img.shields.io/badge/Python-3.14%2B-3776AB?logo=python&logoColor=white)
![PySide6](https://img.shields.io/badge/PySide6-6.11.1%2B-41CD52?logo=qt&logoColor=white)
![Platform](https://img.shields.io/badge/Platform-Windows%20%7C%20macOS%20%7C%20Linux-lightgrey)
![Version](https://img.shields.io/badge/Version-alpha--v1.0.3-orange)

## 特性

- **设计令牌 + 双主题**：色彩 / 字体 / 间距 / 圆角 / 阴影 / 断点 / 动效全部令牌化，`ThemeManager` 一键切换亮 / 暗主题，无需重启，全部组件实时热切换（**暗色主题目前为实验性功能**，个别组件的细节表现仍在打磨）。
- **59 个组件**：输入 / 展示 / 反馈三大类，动态属性 + 全局 QSS 驱动，统一 sm / md / lg 尺寸体系与状态矩阵（hover / pressed / disabled / focus）。
- **13 个响应式布局预设**：API 驱动的工厂函数（`create_card_grid(items=...)` 等），基于断点的响应式重排，空数据自动显示优雅占位。
- **52 个动画预设**：28 个属性动画（快照覆盖层方案，规避 Qt6 + QSS + 高 DPI 下 QGraphicsEffect 失效问题）+ 24 个 QTimer 自绘动画组件。
- **原生图表引擎**：纯 QPainter 实现的 ECharts 风格图表，不依赖 WebView / JavaScript；`set_option` 数据驱动，**21 种系列**（直角坐标 / 层级占比 / 关系流向 / 极坐标 / 日历 / 地图 / 平行坐标）、9 种组件（标题 / 图例 / tooltip / markPoint / markLine / markArea / graphic / map / toolbox），主题感知实时换肤。
- **RHI 与大规模数据**：Chart 与 Blueprint 默认由 `QQuickView + Scene Graph + RHI` 承载，Qt 自动选择 Direct3D 11 / Metal / Vulkan 等平台 API，不强制 OpenGL；公共 QWidget API 与视觉设计保持不变。运行时按「绘图区像素宽」自动降采样并保留逐像素列极值，紧凑存储与零拷贝摄入避免深拷贝大数组。当前系列仍由 QPainter 生成最终快照后上传纹理，`gpuDirect` 仅保留 option 兼容，不再创建 VBO / GLSL 管线；复杂 4K 实时场景尚未达到 60 FPS 验收线，详见验收记录。
- **实时数据接入**：`chart.stream()` 提供无锁环形缓冲（单写单读）+ 帧合并（不丢点）+ 定时入图；生产者在任意线程写入、界面按刷新节奏取数，滚动窗口写满丢最旧。
- **蓝图节点图**：类 UE5 Blueprint / ComfyUI 的节点图编辑器，支持右键建节点、引脚拖线、类型校验、序列化与执行状态模拟。
- **代码编辑器**：纯 PySide6（无 WebView）对齐 VS Code 编辑区体验——语法高亮（9 种内置语言 + 注册表扩展）、小地图、查找替换、诊断 / 断点 / 折叠、补全与悬停 provider、Ctrl+D 多选批量编辑，另含并排 / 内联 / 自动断点的 Diff 对比编辑器。
- **完整图标库**：内置 Iconoir v7.12.1 的 1,383 Regular + 288 Solid（共 1,671 个 SVG），提供 `Icon` / `get_icon` / `get_pixmap` / `icon_svg` / `search_icons` / `icon_names` 接口，可设置尺寸、颜色与描边宽度；Demo「设计令牌 → 图标库」可搜索、过滤与预览全部图标。
- **职责分离**：`InstructionX_UIKit/` 为纯 Kit 包（零假数据、零 Demo 逻辑，一切内容由调用方 API 传入，无内容时显示优雅空占位）；`demo/` 为独立演示程序（**11 大类、80 个演示页**，每页顶部附「用法」代码示例）。

## 界面预览

| 亮色主题 | 暗色主题 |
|---|---|
| ![亮色主题](docs/screenshots/overview_light.png) | ![暗色主题](docs/screenshots/overview_dark.png) |

| 原生图表引擎 | 图表 · 暗色 |
|---|---|
| ![图表](docs/screenshots/charts_light.png) | ![图表暗色](docs/screenshots/charts_dark.png) |

| 响应式仪表盘布局 | 蓝图节点图 |
|---|---|
| ![仪表盘布局](docs/screenshots/layout_dashboard_light.png) | ![蓝图](docs/screenshots/blueprint_light.png) |

| 代码编辑器（仿 VS Code） | |
|---|---|
| ![代码编辑器](docs/screenshots/code_editor_light.png) | |

| 自绘动画（24 预设） | |
|---|---|
| ![自绘动画](docs/screenshots/anim_painted_light.png) | |

## 安装

```bash
pip install -r requirements.txt
# 官方源较慢时可用镜像：
# pip install -r requirements.txt -i https://mirrors.aliyun.com/pypi/simple/
```

依赖：`PySide6>=6.11.1`（含 Addons）、`qrcode[pil]>=7.4`、`matplotlib>=3.11.1`（MarkdownView 的 LaTeX 公式渲染）与 `numpy>=2.0`（图表引擎大规模数据管线：紧凑存储、向量化降采样与坐标映射、分层采样金字塔），除此之外无任何第三方依赖。

## 快速上手

```python
import sys
from PySide6.QtWidgets import QApplication, QVBoxLayout, QWidget

from InstructionX_UIKit.theme import ThemeManager
from InstructionX_UIKit.components import Button, LineEdit, Statistic, Switch
from InstructionX_UIKit.layouts import create_card_grid

app = QApplication(sys.argv)
ThemeManager.instance().apply(app)          # 应用全局主题（默认亮色）

win = QWidget()
lay = QVBoxLayout(win)

lay.addWidget(Statistic(title="活跃用户", value=24317))
lay.addWidget(LineEdit(placeholder="请输入关键词"))
lay.addWidget(Button("确定", variant="primary"))
lay.addWidget(Switch(checked=True))

# 布局为 API 驱动：内容由调用方传入
grid = create_card_grid(items=[
    ("数据看板", "汇总关键指标。", "color.primary.subtle"),
    ("任务中心", "展示待办与进度。", "color.success.subtle"),
])
lay.addWidget(grid, 1)

win.resize(720, 560)
win.show()
sys.exit(app.exec())
```

切换暗色主题（无需重启，全部组件实时换肤；**暗色主题为实验性功能**）：

```python
tm = ThemeManager.instance()
tm.set_mode("dark")   # 或 tm.toggle() 亮暗互切
```

## 运行 Demo

```bash
python main.py
```

左侧导航含：设计令牌 / 布局预设（13）/ 组件·输入 / 组件·展示 / 组件·反馈 / 动画·属性（28）/ 动画·自绘（24）/ 基础控件 / 图表（21 系列 + 巨量数据与实时滚动流演示）/ 蓝图（节点图）/ 代码编辑器（编辑器 + Diff），共 11 大类 80 页。顶栏可随时切换亮 / 暗主题（实验性）；每个演示页顶部有「用法」代码标签，看 Demo 即可学会对应 API 的调用方式。

**图表页的巨量数据演示**：`1,500,000` 点起（可拉到 500 万）实时重建，读数给出实际渲染点数、QPainter 参考绘制耗时与实际 RHI 后端；`benchmark()` 的 `gpu_ms` 保留兼容字段，但当前没有独立 GPU 顶点绘制计时可填。「实时滚动流」开关模拟约 1000 点/秒的传感器。单帧绘制耗时与 `frameSwapped` 都只能反映各自阶段，不能互相替代；最终性能以真实窗口验收为准。

## 项目结构

```
项目根/
├── InstructionX_UIKit/          # 纯 Kit 包（零假数据、零 Demo 逻辑）
│   ├── tokens.py                # 设计令牌（唯一数值来源 + TokenState）
│   ├── theme.py                 # ThemeManager + 全局 QSS 生成
│   ├── icons.py                 # Iconoir SVG 图标（QtSvg 渲染 + QPainter 回退）
│   ├── iconoir_icons.py         # Iconoir v7.12.1 完整图标资产（1,671 个，MIT）
│   ├── components/              # 59 个组件（输入 / 展示 / 反馈）
│   ├── layouts/                 # 13 个响应式布局预设（API 驱动）
│   ├── anim/                    # 28 属性动画 + 24 自绘动画
│   ├── charts/                  # 原生图表引擎（ECharts 风格）
│   │   ├── core.py              #   ChartWidget（set_option / update_option）+ 分层渲染缓存
│   │   ├── viewport.py          #   默认 RHI 与离屏软件视口
│   │   ├── rhi_viewport.py      #   QQuickView 原生容器、输入与生命周期
│   │   ├── scene_snapshot.py    #   GUI 线程完整最终帧快照
│   │   ├── data.py              #   紧凑存储与零拷贝摄入（大规模数据管线）
│   │   ├── sampling.py          #   运行时降采样与「逐像素列极值一致」保真承诺
│   │   ├── stream.py            #   实时接入：RingBuffer / FrameCoalescer / StreamSession
│   │   ├── axes.py              #   坐标系与轴模型
│   │   ├── series_cartesian.py  #   直角坐标 / 单轴 / 平行坐标 / 日历系列
│   │   ├── series_hierarchy.py  #   pie / radar / gauge / tree / treemap / sankey / graph
│   │   ├── components.py        #   图表组件（markPoint / markLine / graphic / map …）
│   │   ├── interact.py          #   dataZoom / brush / visualMap / timeline / toolbox
│   │   └── pyramid.py           #   分层采样金字塔（可选组件，默认不接入）
│   ├── blueprint/               # 蓝图节点图（模型 / 画布 / 连线 / 菜单 / 执行模拟）
│   └── code_editor/             # 仿 VS Code 代码编辑器（高亮 / 小地图 / Diff）
├── demo/                        # 独立 Demo 程序（11 大类、80 演示页，惰性加载）
├── docs/                        # Design.md（设计规范）/ USAGE.md（使用手册）/ screenshots/
├── main.py                      # Demo 启动入口
└── requirements.txt
```

## 分支与测试

| 分支 | 内容 |
|---|---|
| `uniform_style` | UIKit、Demo、工具与文档的唯一源码修改分支，不提交 `tests/` |
| `uniform_test` | 完整源码 + 全部离屏自测（`tests/`，含截图回归与真实性能脚本） |
| `test` | 原测试分支，保持不动 |

所有工作都在仓库根目录完成，**禁止创建或使用 worktree**。源码提交后先在 `uniform_test` 合并最新实现，再运行测试：

```powershell
git switch uniform_test
git merge --no-ff uniform_style
# Windows PowerShell；offscreen 平台需指定系统字体目录，否则文本渲染为豆腐块
$env:QT_QPA_PLATFORM="offscreen"; $env:QT_QPA_FONTDIR="C:\Windows\Fonts"
python tests\test_core.py
```

测试为独立可执行脚本（无 pytest 依赖），退出码 0 即通过。真实性能脚本位于 `tests/perf/`，用法见 `docs/USAGE.md` 与 `docs/superpowers/plans/`；离屏结果不能替代真实窗口验收。

## 致谢与第三方

感谢以下开源项目与社区的工作：

- **[Iconoir](https://github.com/iconoir-icons/iconoir)**：本项目 `icons.py` 的主图标来源。Iconoir 由 Luca Burgio 创建，采用 MIT License；已内置 v7.12.1 完整图标集（1,383 Regular + 288 Solid，共 1,671 个），统一使用 Iconoir 原名，也可通过 `get_icon("iconoir:<名称>")` 显式入口；左侧「设计令牌 → 图标库」可视化全部图标，并支持调色盘实时换色。
- **Qt for Python / PySide6**、**qrcode**、**Pillow**、**matplotlib**、**numpy**、**Mermaid** 等运行时依赖；它们让本项目的 GUI、二维码、公式、数据处理与图表渲染成为可能。

完整的来源、版本、许可证文本和维护约定见 **[THIRD-PARTY.md](THIRD-PARTY.md)**。

## 文档

- [docs/Design.md](docs/Design.md) — 设计规范（令牌数值、断点、动效、状态矩阵、暗色策略）
- [docs/USAGE.md](docs/USAGE.md) — 使用手册，共 11 章：
  - §1–§7 安装 / 快速开始 / 主题系统 / 组件 / 布局 / 动画 / 图表用法
  - **§8 大数据与实时渲染** — 渲染后端（RHI 与软件双视口）、自动降采样与保真承诺、实时数据接入（`chart.stream()`）、`gpuDirect` option 兼容与统一快照、同屏多图性能特征
  - §9 蓝图模式 · §10 代码编辑器 · §11 常见问题
- [THIRD-PARTY.md](THIRD-PARTY.md) — 第三方项目来源、许可证与致谢清单（Iconoir 等）

## 仓库

`https://github.com/KKPIP-Tech/InstructionX_UIKit.git`
