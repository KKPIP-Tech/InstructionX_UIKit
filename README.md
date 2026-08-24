# InstructionX_UIKit

基于 PySide6（Qt for Python）的纯桌面 UI 组件库：设计令牌 + 亮/暗双主题、58 个组件、13 个响应式布局预设、52 个动画预设、原生图表引擎与蓝图节点图编辑器。

![Python](https://img.shields.io/badge/Python-3.14%2B-3776AB?logo=python&logoColor=white)
![PySide6](https://img.shields.io/badge/PySide6-6.11.1%2B-41CD52?logo=qt&logoColor=white)
![Platform](https://img.shields.io/badge/Platform-Windows%20%7C%20macOS%20%7C%20Linux-lightgrey)
![Version](https://img.shields.io/badge/Version-alpha--v1.0.2-orange)

## 特性

- **设计令牌 + 双主题**：色彩 / 字体 / 间距 / 圆角 / 阴影 / 断点 / 动效全部令牌化，`ThemeManager` 一键切换亮 / 暗主题，无需重启，全部组件实时热切换（**暗色主题目前为实验性功能**，个别组件的细节表现仍在打磨）。
- **58 个组件**：输入 / 展示 / 反馈三大类，动态属性 + 全局 QSS 驱动，统一 sm / md / lg 尺寸体系与状态矩阵（hover / pressed / disabled / focus）。
- **13 个响应式布局预设**：API 驱动的工厂函数（`create_card_grid(items=...)` 等），基于断点的响应式重排，空数据自动显示优雅占位。
- **52 个动画预设**：28 个属性动画（快照覆盖层方案，规避 Qt6 + QSS + 高 DPI 下 QGraphicsEffect 失效问题）+ 24 个 QTimer 自绘动画组件。
- **原生图表引擎**：纯 QPainter 实现的 ECharts 风格图表，不依赖 WebView / JavaScript；`set_option` 数据驱动，20+ 系列类型，主题感知实时换肤。
- **蓝图节点图**：类 UE5 Blueprint / ComfyUI 的节点图编辑器，支持右键建节点、引脚拖线、类型校验、序列化与执行状态模拟。
- **职责分离**：`InstructionX_UIKit/` 为纯 Kit 包（零假数据、零 Demo 逻辑，一切内容由调用方 API 传入）；`demo/` 为独立演示程序（77 演示页，每页顶部附「用法」代码示例）。

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

| 自绘动画（24 预设） | |
|---|---|
| ![自绘动画](docs/screenshots/anim_painted_light.png) | |

## 安装

```bash
pip install -r requirements.txt
# 官方源较慢时可用镜像：
# pip install -r requirements.txt -i https://mirrors.aliyun.com/pypi/simple/
```

依赖：`PySide6>=6.11.1`（含 Addons）、`qrcode[pil]>=7.4` 与 `matplotlib>=3.11.1`（MarkdownView 的 LaTeX 公式渲染），除此之外无任何第三方依赖。

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

左侧导航含：设计令牌 / 布局预设（13）/ 组件·输入 / 组件·展示 / 组件·反馈 / 动画·属性（28）/ 动画·自绘（24）/ 基础控件 / 图表 / 蓝图。顶栏可随时切换亮 / 暗主题（实验性）；每个演示页顶部有「用法」代码标签，看 Demo 即可学会对应 API 的调用方式。

## 项目结构

```
项目根/
├── InstructionX_UIKit/          # 纯 Kit 包（零假数据、零 Demo 逻辑）
│   ├── tokens.py                # 设计令牌（唯一数值来源 + TokenState）
│   ├── theme.py                 # ThemeManager + 全局 QSS 生成
│   ├── icons.py                 # QPainter 运行时矢量图标集
│   ├── components/              # 58 个组件（输入 / 展示 / 反馈）
│   ├── layouts/                 # 13 个响应式布局预设（API 驱动）
│   ├── anim/                    # 28 属性动画 + 24 自绘动画
│   ├── charts/                  # 原生图表引擎（ECharts 风格）
│   └── blueprint/               # 蓝图节点图（模型 / 画布 / 连线 / 菜单 / 执行模拟）
├── demo/                        # 独立 Demo 程序（77 演示页）
├── docs/                        # Design.md（设计规范）/ USAGE.md（使用手册）/ screenshots/
├── main.py                      # Demo 启动入口
└── requirements.txt
```

## 分支与测试

| 分支 | 内容 |
|---|---|
| `main` / `dev` | 仅项目源码与文档，不含测试代码 |
| `test` | 完整源码 + 全部离屏自测（`tests/`，含截图回归） |

测试为独立可执行脚本（无 pytest 依赖），退出码 0 即通过：

```powershell
git switch test
# Windows PowerShell；offscreen 平台需指定系统字体目录，否则文本渲染为豆腐块
$env:QT_QPA_PLATFORM="offscreen"; $env:QT_QPA_FONTDIR="C:\Windows\Fonts"
python tests\test_core.py
```

## 文档

- [docs/Design.md](docs/Design.md) — 设计规范（令牌数值、断点、动效、状态矩阵、暗色策略）
- [docs/USAGE.md](docs/USAGE.md) — 使用手册（主题系统、全部组件 / 布局 / 动画 / 图表 / 蓝图示例）

## 仓库

`https://github.com/KKPIP-Tech/InstructionX_UIKit.git`
