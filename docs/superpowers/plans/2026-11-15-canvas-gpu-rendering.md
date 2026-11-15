# Canvas GPU Rendering Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在保持 ChartWidget 与 BlueprintCanvas 公共 QWidget API、完整 option、交互和视觉设计的前提下，取消真实窗口每帧 QPainter 全帧快照，改由 PySide6 自带的 QCanvasPainter / QRhi 绘制图元。

**Architecture:** Python 继续负责数据、布局、采样、动画状态与命中测试，内部视口使用 QCanvasPainterWidget。动态路径直接绘制，静态路径使用有界 path group；真实像素用离屏画布回读对照，不以桌面合成差异冒充渲染回归。

**Tech Stack:** Python >= 3.14、当前公开 PySide6 6.11.1、QCanvasPainterWidget、QCanvasPainter、QCanvasPath、QRhi、现有 NumPy。首轮只验收 PySide6 6.11.1；后续版本需重新验证。

## Global Constraints

- 只使用公开渠道现有 PySide6 自带能力，不新增第三方 Python 依赖，不编写 C++ 插件，不使用 MSVC/CMake，不生成自定义材质或额外原生二进制。
- 所有者已按首选路线批准 Qt Canvas Painter 的 GPLv3 许可；发布文档必须补充该许可，不得误导为 LGPL，也不得使用付费依赖。
- 范围为 Chart 与 Blueprint 的内置图元；普通 QWidget/QSS 组件和任意用户 QWidget 子树不在本轮全 GPU 承诺内。
- 公共 QWidget 构造、方法、属性、信号、返回值、dataIndex、焦点与键盘行为不得改变。
- 禁止每帧 QPainter 全帧 QImage 快照、QQuickPaintedItem、QML Canvas、强制 OpenGL、降低 DPR、减少数据、隐藏组件或接受像素差异换取性能。
- CPU 负责逻辑与数据准备，GPU 负责实际图元绘制；不得宣称路径与文本不需要任何 CPU 准备。
- 源码只在 `uniform_style` 修改；测试只在 `uniform_test` 修改。禁止 worktree，原 `test` 分支不动。
- 每个小项先写失败测试，验证后提交，再从 `uniform_style` 合并到 `uniform_test` 复验。不得自动合并 `dev`、发布或修改 InstructionX 主仓库。
- 任一像素、功能、性能或许可门禁失败均不得标为完成；许可或 PresentMon 权限不足必须标为阻塞，不得绕过。

---

### Task 0: 验证 QCanvasPainterWidget 的真实绘制与回读能力

**Files:**
- Create: `temp/probe_canvas_hello.py`
- Create: `temp/rhi_visibility/canvas_hello.json`

**Interfaces:**
- Consumes: `QCanvasPainterWidget.paint(QCanvasPainter)`、`QCanvasPath.moveTo/lineTo`、`QCanvasPainter.stroke`、`QCanvasPainterWidget.grabCanvas`。
- Produces: 真实图形 API、离屏 QImage、与 QPainter 参考图的逐像素差异和基础耗时，不进入公共 API。

- [ ] **Step 1: 创建最小真实窗口探针**

用 5 个 `QPointF` 构造一条路径，以 `QColor("#357ABD")`、线宽 2、RoundCap 和 RoundJoin 分别绘制 QPainter 参考图与 QCanvasPainter 离屏图。背景透明，物理尺寸 256×256，DPR=1，禁止裁减数据或关闭抗锯齿。

- [ ] **Step 2: 验证真实后端与资源释放**

Run: `PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe -u temp/probe_canvas_hello.py`
Expected: 输出实际 `api()`、回读图像尺寸、差异像素数和退出码；退出码必须为 0，回调不得悬空，窗口必须正常关闭。

- [ ] **Step 3: 记录初始像素差异**

Run: 读取 `temp/rhi_visibility/canvas_hello.json` 与实际回读 PNG。
Expected: 报告包含 `changed`、`max_delta`、`backend`、`physical_size`。若 `changed != 0`，后续 Task 1 必须先解决实线像素差异，不得替换正式后端。

### Task 1: 建立实线路径与真实像素回归

**Files:**
- Create: `InstructionX_UIKit/charts/canvas_paths.py`
- Create: `InstructionX_UIKit/charts/canvas_viewport.py`
- Create: `tests/test_canvas_paths.py`
- Create: `tests/perf/run_canvas_line.py`

**Interfaces:**
- Consumes: 现有 `LineSeriesRenderer._points`、`color()`、lineStyle.width、coord.plot、DPR 和 Task 0 的回读接口。
- Produces: `line_path(points: list[QPointF]) -> QCanvasPath`；内部 `CanvasLineViewport`，不替换 `ChartWidget` 的默认后端。

- [ ] **Step 1: 先写失败的路径与像素测试**

路径测试必须覆盖空输入、单点、重复点、反向折线、None 分段和命令数量；真实测试覆盖 DPR 1/1.25/1.5/2、线宽 1/2/4/8、锐角、自相交和多条系列的原顺序合成。断言 `changed == 0 and max_delta == 0`。

- [ ] **Step 2: 确认测试先失败**

Run: `QT_QPA_PLATFORM=offscreen QT_QPA_FONTDIR='C:\Windows\Fonts' .venv/Scripts/python.exe -u tests/test_canvas_paths.py`
Expected: 因 `InstructionX_UIKit.charts.canvas_paths` 不存在而失败，不得先写实现再补测试。

- [ ] **Step 3: 实现最小路径与视口**

`line_path` 使用 `QCanvasPath(len(points))`，按原顺序调用 `moveTo/lineTo`，空输入返回空路径。视口调用 `setLineCap(Round)`、`setLineJoin(Round)`、原 lineWidth 与裁剪，禁止生成每帧 QImage。动态路径不传静态 path group。

- [ ] **Step 4: 运行路径、真实像素与基础性能验证**

Run: `QT_QPA_PLATFORM=offscreen QT_QPA_FONTDIR='C:\Windows\Fonts' .venv/Scripts/python.exe -u tests/test_canvas_paths.py`
Expected: 全部通过。
Run: `PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe -u tests/perf/run_canvas_line.py`
Expected: 真实 QRhi 后端创建、绘制、回读与销毁成功；所有规定用例零像素差异；记录单帧耗时及资源上界。任一像素或稳定性失败则停止扩展。

- [ ] **Step 5: 提交并合并复验**

```bash
git add InstructionX_UIKit/charts/canvas_paths.py InstructionX_UIKit/charts/canvas_viewport.py
git commit -m "feat(charts): 增加 Canvas 实线绘制原型"
git switch uniform_test
git merge --no-ff --no-commit uniform_style
# 通过 tests/test_canvas_paths.py 与 tests/perf/run_canvas_line.py 后再提交合并
```

### Task 2: 完整折线与流式生命周期

**Files:**
- Modify: `InstructionX_UIKit/charts/canvas_paths.py`
- Modify: `InstructionX_UIKit/charts/canvas_viewport.py`
- Create: `tests/test_canvas_line.py`

**Interfaces:**
- Consumes: Task 1 的 `line_path` 与内部视口。
- Produces: smooth、step、areaStyle、虚线、符号、polar、singleAxis、None、主题、resize、隐藏、最小化和销毁支持。

- [ ] 为每类 option 与生命周期先写失败测试，逐一实现，禁止静默漏画或退化成整帧快照。
- [ ] 静态装饰使用有界 path group；动态曲线直接绘制。所有纹理、路径组与画布都有容量和释放上限。
- [ ] 运行 `test_canvas_line`、`test_perf_line`、`test_perf_stream`、`test_perf_resize`、`test_rhi_chart`，并复核命中下标、焦点、DPR 和最终像素。
- [ ] 通过后提交源码，合并 `uniform_test` 复验；失败则停止。

### Task 3: 完整 Chart 绘制

**Files:**
- Create: `InstructionX_UIKit/charts/canvas_scene.py`
- Create: `InstructionX_UIKit/charts/canvas_axes.py`
- Create: `InstructionX_UIKit/charts/canvas_series.py`
- Create: `InstructionX_UIKit/charts/canvas_components.py`

**Interfaces:**
- Consumes: 现有 option、坐标系、系列与组件模型以及 Task 2 的路径原语。
- Produces: 全部现有系列、坐标轴、文本、图例、tooltip、标注和交互组件的 Canvas 绘制。

- [ ] 按直角坐标、层级、文本与组件逐项写失败测试，保持原绘制顺序与 dataIndex。
- [ ] 运行 `test_chart_core`、`test_chart_cartesian`、`test_chart_hierarchy`、`test_chart_components`、`test_perf_scatter`、`test_perf_symbols`、`test_charts_gallery`。
- [ ] 全部 option 有实现后才替换真实窗口快照视口；离屏 QPainter 仅作参考验证，不作为真实窗口生产后端。
- [ ] 最终像素不全为零则停止，不启用半成品。

### Task 4: Blueprint 原生绘制

**Files:**
- Create: `InstructionX_UIKit/blueprint/canvas_viewport.py`
- Create: `InstructionX_UIKit/blueprint/canvas_scene.py`

**Interfaces:**
- Consumes: Task 2 的路径与生命周期原语、现有 Blueprint 模型、节点、边与交互。
- Produces: 节点、边、端口、选区和菜单装饰的 Canvas 绘制；自定义 QWidget 内容单独登记，不承诺自动 GPU 化。

- [ ] 为节点、边、拖动、连线、Delete、菜单、焦点、主题、resize 与最小化写失败测试。
- [ ] 运行 `test_blueprint`、`test_rhi_blueprint`、`test_perf_resize` 与真实桌面对照，保持模型与交互不变。
- [ ] 通过后提交并合并复验；不完整则停止。

### Task 5: 最终验收与文档

**Files:**
- Modify: `README.md`、`docs/USAGE.md`、`THIRD-PARTY.md`
- Modify: `docs/superpowers/plans/2026-11-14-gui-performance-acceptance.md`
- Modify: `tests/perf/final-evidence.json`

- [ ] 全量独立脚本与原始亮暗 160 状态零像素对照通过。
- [ ] 真实 3840×2160、八个 2 万点系列至少 5×60 秒：平均 FPS≥60、P95≤16.67ms、P99≤33.33ms，且无应用自身≥100ms 长任务。
- [ ] 窗口操作每类至少 5×30 秒，系统与手动路径、跨屏、最大化及资源生命周期均通过。
- [ ] 资源、音频、退出与 PresentMon 权限证据齐全；权限不足只能标为阻塞。
- [ ] 更新许可、最新架构、用法、证据索引和回滚说明。最终 SHA 由所有者决定是否验收；不自动合并或发布。

## Stop Conditions

- 不接受 GPLv3，或不能公开安装同一 PySide6 能力。
- 任一必需像素比较不为零，或真实图形后端、生命周期、option 覆盖不完整。
- 需要引入被禁止的编译组件、付费依赖、降低画质、减少数据或隐藏功能才能继续。
- 真实 4K、窗口、资源或权限门禁未通过。此时只交付原始证据与阻塞说明，不宣称完成。
