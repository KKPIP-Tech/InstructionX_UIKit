# InstructionX_UIKit GUI 性能升级实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在不重写 UIKit、不改变既有公开 API 与既有视觉设计的前提下，修复窗口交互、图表数据链路和普通组件的同步热点；只有局部 Scene Graph 后端经完整验收稳定优于修复后的 QWidget 基线时才启用。

**Architecture:** 保留 `ChartWidget`、`BlueprintCanvas` 及全部普通组件的 QWidget/QSS 实现。先优化数据、布局、缓存和生命周期，再为图表建立可独立回退的 `QQuickView + createWindowContainer + Scene Graph` 垂直切片。默认后端在验收前保持原实现，未迁移能力必须精确回退，不能静默忽略 option。

**Tech Stack:** Python `>=3.14`、PySide6 `>=6.11.1`、QWidget/QSS/QPainter、现有 NumPy；可选局部试点使用 QtQuick、`QQuickView`、`QQuickItem`、`QSGGeometryNode` 和现成 Scene Graph 材质。不新增第三方 Python 依赖。

## Global Constraints

- 唯一源码基线：上游 `InstructionX_UIKit/uniform_style`，SHA `949b7288a50b6ed5beed744db3c8bf46a13c00ef`，包版本 `alpha-v1.0.3`。
- 当前 `uv.lock` 的 `1.0.2a1 → 1.0.3a1` 是迁移前已有的本地修改，必须保留，不得用 `reset --hard` 或 `git checkout` 覆盖。
- QML 全量迁移已放弃；不恢复 `qml_support/`、QML 组件适配层或 QML 全窗口实现。
- 所有者已明确豁免四份 `private_docs/*_SPEC.md` 的原文恢复，不再以此阻塞实施。以 `uniform_style@949b728` 当前源码、公开 API、设计文档和新采集的视觉基线为准；后续根据新代码同步重建文档，旧 QML 短契约不得作为事实来源。
- 所有既有公开构造签名、方法、属性、信号槽、返回值、option 数据格式及 QWidget 返回类型保持兼容。新增内部参数必须可选，不能改变既有调用语义。
- 同一机器、Qt、字体、DPR、窗口尺寸、主题、数据和控件状态下，最终静态图像必须与基线逐像素相同；差异允许值为 0。不得用“差不多”“风格类似”或非空截图代替。
- 动态测试须冻结动画到指定进度或使用稳定的完成态，不能将动画自然抖动误判为回归。临时 resize 预览是报告明确允许的交互态；最终高清帧仍执行零像素差异验收。
- 默认 `showSymbol=True` 保持不变。`"auto"` 只能作为显式选择加入；自动隐藏默认符号会改变外观，若所有者决定采用，必须另立设计变更和截图基线，不能在性能修复中暗中改变。
- 不把 `processEvents()` 次数、`update()` 次数、定时器频率、`paintGL()` 耗时或离屏 benchmark 当作实际呈现 FPS。
- 复杂场景必须真实覆盖 3840×2160 物理像素；预热后每轮至少 60 秒、至少 5 轮，保留全部原始 frameSwapped／PresentMon／WPA 数据。
- 合格：每轮有效平均实际 FPS `>=60`，P95 `<=16.67 ms`，P99 `<=33.33 ms`，无应用自身 `>=100 ms` 长任务。优秀：平均 FPS `>=90`，P95 `<=11.11 ms`，P99 `<=16.67 ms`，无应用自身 `>=50 ms` 长任务。
- 窗口拖动、四边／四角缩放、最大化／还原、跨屏和窗口形状变化每种至少 30 秒、至少 5 轮。任一功能失败、错图、黑帧、闪烁、假死、资源无界增长或音频异常均使对应验收失败。
- 60 Hz 显示链路不得宣称 90 FPS 优秀档；当前没有完成的 4K、三平台或音频复测结果时，必须明确标为未验证。
- `uniform_style` 的全部测试统一在新分支 `uniform_test` 上维护；该分支从原 `test` 创建并同步候选源码，原 `test` 分支不直接修改。`uniform_style`、源码工作分支、`dev` 和 `main` 不新增 `tests/`。测试脚本直接运行，不使用 pytest。
- 离屏测试必须设置 `QT_QPA_PLATFORM=offscreen` 与 `QT_QPA_FONTDIR=C:\Windows\Fonts`。优先使用现有 `.venv/Scripts/python.exe`，避免离线环境重新同步依赖。
- 不使用 Qt Charts／Qt Graphs，不把 `QQuickPaintedItem` 当作高频大数据终态，不强制引入 qsb／Qt Shader Tools，不引入付费、商业专用或许可未评审的模块。
- 不自动合并 `dev`、不发布、不修改 InstructionX 主仓库，不删除主程序 GL 预热或全局 OpenGL 强制设置。P4 均需所有者另行批准。
- 每项实现先写失败回归测试，再修改源码；每个功能独立验证、独立审阅。任何 `git commit`、合并或推送都先取得用户确认；自定义 Commit 前缀也须另行确认。

---

## 文件边界

### 现有源码，按任务小步修改

- `InstructionX_UIKit/charts/series_cartesian.py`：折线无效插值、显式符号预算、普通实线批量绘制、散点零复制遍历、category 批量映射。
- `InstructionX_UIKit/charts/sampling.py`：有界 NumPy 分块极值计算，保留原采样语义。
- `InstructionX_UIKit/charts/axes.py`：只读取并复用 `AxisModel.map()` 的精确 category 语义，不另造近似公式。
- `InstructionX_UIKit/charts/core.py`：流式原子提交、轴缓存失效、resize 预览和生命周期，不改变 `ChartWidget` 公共入口。
- `InstructionX_UIKit/charts/stream.py`：auto-scale 降频、固定轴免扫描、隐藏时丢弃过期帧而保留有界最新窗口。
- `InstructionX_UIKit/charts/viewport.py`：保留 raster／GL 回退，增加受控预览和可观测回退原因。
- `InstructionX_UIKit/charts/gl_series.py`：仅在现有 GL 保留期间修正版本缓存与能力门禁，不扩大 GPU 功能范围。
- `InstructionX_UIKit/layouts/chat_conversation.py`：删除重入事件泵，合并 chunk／统计／滚动工作，完成时强制同步。
- `InstructionX_UIKit/components/markdown_view.py`：保留现有增量渲染，避免重复全量渲染；不重写公式和 Mermaid 管线。
- `InstructionX_UIKit/theme.py`：同值样式跳过；逐项、可回退地收窄背景 QSS，保留已验证的字体层级规则。
- `InstructionX_UIKit/blueprint/canvas.py`、`InstructionX_UIKit/blueprint/viewport.py`、`InstructionX_UIKit/blueprint/node_widget.py`：resize 预览、隐藏停更与资源释放，保持节点真实子控件行为。
- `demo/main_window.py`：只接入 UI 激活状态通知，不重排页面、不修改设计。
- `demo/pages/__init__.py`：仅在组件 API 示例确实改变时同步；本计划不改变既有调用方式。

### 新文件

- `InstructionX_UIKit/_metrics.py`：私有、固定容量的耗时样本与计数器，不依赖 Demo。
- `InstructionX_UIKit/_resize_preview.py`：图表与 Blueprint 共用的私有 single-shot 防抖状态机，不拥有业务数据。
- P2 单独设计通过后，才可创建 `InstructionX_UIKit/charts/quick_viewport.py`、`scene_item.py`、`scene_snapshot.py` 与最小 QML 场景文件；这些只承载图表局部试点，不是全组件 QML 层。
- 测试集成分支：`tests/test_perf_metrics.py`、`test_perf_line.py`、`test_perf_scatter.py`、`test_perf_sampling.py`、`test_perf_stream.py`、`test_gpu_direct.py`、`test_perf_chat.py`、`test_perf_resize.py`、`test_window_gestures.py`、`test_theme_regression.py`、`test_lifecycle.py`、`test_animation_resources.py`、`test_api_compat.py`、`test_visual_compat.py`、`test_scene_graph_chart.py` 及 `tests/perf/` 固定负载与测量脚本。
- 原始性能证据写入 gitignored 的 `temp/performance/<baseline-or-candidate-sha>/`，包含 JSON／CSV、环境、原始日志和截图；不得把临时输出提交到源码分支。

---

## P0：恢复可靠契约、建立基线并完成稳定性修复

### Task 0：冻结现有代码契约与原始基线

**Files:**
- Preserve: `uv.lock`
- Reference: `docs/USAGE.md`、`docs/Design.md`、`docs/COMPONENT-DESIGN-CONTRACT.md`
- Later synchronize from implementation: `private_docs/SPEC.md`、`private_docs/CHART_SPEC.md`、`private_docs/BP_SPEC.md`、`private_docs/CE_SPEC.md`
- Test: 新 `uniform_test` 分支全部现有 `tests/test_*.py`

**Interfaces:**
- Consumes: 原始 `uniform_style@949b728`、公开 API、现有设计文档与所有者作出的原文恢复豁免。
- Produces: 可复现的 API、截图、功能和性能基线；没有基线时不允许宣称“优化后更快”。

- [ ] **Step 1：确认没有误删用户原有修改**

Run:

```powershell
git status --short --branch
git log -1 --oneline
git diff -- uv.lock
```

Expected: 分支为 `uniform_style`；`uv.lock` 只保留迁移前已有的项目版本号差异。若出现未识别文件，先辨认归属，不清理。

- [ ] **Step 2：登记原文恢复豁免并冻结现有代码契约**

所有者已明确指示忽略四份私有契约的原文恢复，后续根据新代码同步文档。保存 `api-baseline.json`、当前 `docs/USAGE.md` 与设计文档、160 张亮暗截图和测试差异清单；不得再把旧 QML 短契约或历史过期副本当作当前接口依据。

Expected: 原始代码、公开 API 和视觉基线均可读取，后续文档同步任务保留，不再因原文缺失阻塞实施。

- [ ] **Step 3：在仓库根目录建立源码和测试工作区**

禁止创建或使用 `git worktree`。`uniform_test` 以原 `test` 为起点，合并候选源码并维护新增测试；原 `test` 分支不直接修改，测试不反向合并到 `uniform_style`。所有编辑、测试、提交和运行都在仓库根目录完成，使用者可在 VS Code 中直接切换分支并运行根目录 `main.py`。经用户确认后，在根目录 `uniform_test` 分支执行 `git merge --no-ff --no-commit perf/uniform-style` 并解决源码差异，使测试分支同时具有候选源码和 `tools/`；此合并不写入源码工作分支。

- [ ] **Step 4：运行原始功能测试与真实交互基线**

在测试工作区使用根目录现有解释器：

```powershell
$env:QT_QPA_PLATFORM = "offscreen"
$env:QT_QPA_FONTDIR = "C:\Windows\Fonts"
$python = "C:\Users\fuwa1\Documents\Project\InstructionX_UIKit\.venv\Scripts\python.exe"
Get-ChildItem tests\test_*.py | ForEach-Object {
    & $python $_.FullName
    if ($LASTEXITCODE -ne 0) { Write-Host "FAIL $($_.Name)" }
}
& $python tools\check_spacing.py
& $python tools\audit_components.py
& $python tools\smoke_click.py
```

Expected: 每项退出码 0。已知 CommentView 两条 DEGENERATE 需在原基线复现并单独登记；其他既有失败不能偷偷算作本任务回归，也不能为了变绿删除测试。

- [ ] **Step 5：保存原始视觉与性能证据**

固定字体、DPR、窗口尺寸、随机种子、亮暗主题及稳定控件状态，用原 `tools/shoot.py` 生成基线。记录所有页面的最终图像哈希和像素数组，而非只检查颜色数。真实性能基线按 Task 1 的脚本采集；未取得真实 4K 数据时写 `未验证`，不写 `通过`。

### Task 1：加入固定容量指标和可复现 A/B 负载

**Files:**
- Create: `InstructionX_UIKit/_metrics.py`
- Modify: `InstructionX_UIKit/charts/core.py`、`charts/stream.py`、`charts/viewport.py`
- Test: `tests/test_perf_metrics.py`、`tests/perf/run_widget_baseline.py`

**Interfaces:**
- Produces: 私有 `MetricRing(capacity=240)`、`add(name, seconds)`、`count(name, amount=1)`、`snapshot() -> dict`。
- Metrics: option update、rebuild、采样、映射、路径、缓存命中／重建、顶点转换／上传、隐藏 update、预览／最终重建、物理尺寸、DPR、后端与回退原因。

- [ ] **Step 1：先写容量和统计失败测试**

```python
import traceback

from InstructionX_UIKit._metrics import MetricRing

_FAILURES = []


def check(name):
    def decorate(function):
        try:
            function()
            print(f"  [通过] {name}")
        except Exception:
            _FAILURES.append(name)
            print(f"  [失败] {name}")
            traceback.print_exc()
    return decorate


@check("固定容量样本与精确计数")
def _():
    ring = MetricRing(capacity=2)
    ring.add("paint", 0.001)
    ring.add("paint", 0.003)
    ring.add("paint", 0.005)
    ring.count("hidden_update", 2)
    result = ring.snapshot()
    assert result["paint"]["count"] == 2
    assert abs(result["paint"]["mean"] - 0.004) < 1e-12
    assert result["hidden_update"] == 2


if __name__ == "__main__":
    raise SystemExit(1 if _FAILURES else 0)
```

- [ ] **Step 2：运行测试，确认模块尚不存在时失败**

Run: `& $python tests\test_perf_metrics.py`
Expected: FAIL，原因为 `InstructionX_UIKit._metrics` 不存在。

- [ ] **Step 3：实现最小固定容量指标类**

```python
# -*- coding: utf-8 -*-
"""UI 热路径的私有固定容量性能指标。"""

from collections import deque


class MetricRing:
    def __init__(self, capacity=240):
        self._capacity = max(1, int(capacity))
        self._samples = {}
        self._counters = {}

    def add(self, name, seconds):
        values = self._samples.get(name)
        if values is None:
            values = self._samples[name] = deque(maxlen=self._capacity)
        values.append(float(seconds))

    def count(self, name, amount=1):
        self._counters[name] = self._counters.get(name, 0) + int(amount)

    def snapshot(self):
        result = {name: dict(values) for name, values in self._counters.items()}
        for name, values in self._samples.items():
            ordered = sorted(values)
            result[name] = {
                "count": len(values),
                "mean": sum(values) / len(values) if values else 0.0,
                "p95": ordered[min(len(ordered) - 1,
                                   int(len(ordered) * 0.95))] if ordered else 0.0,
            }
        return result
```

指标写入不得分配无限历史，不得在 paint 内序列化 JSON。所有时间来自 `time.perf_counter()`。

- [ ] **Step 4：运行指标测试和原图表测试**

Run: `& $python tests\test_perf_metrics.py; & $python tests\test_chart_core.py`
Expected: 全部 `[通过]`，退出码 0。

- [ ] **Step 5：在真实窗口记录 A/B，不用离屏耗时替代 FPS**

测试负载包括 1 万／10 万／100 万静态折线、2 万点流式窗口、4／8／16 系列、1 万／10 万散点、Blueprint 与普通复杂控件。保存原始 `frameSwapped` 间隔，Windows 用 PresentMon 或 WPA 复核；脚本必须记录 SHA、机器、GPU、驱动、DPR、刷新率和物理像素。

### Task 2：终止折线无效动画插值

**Files:**
- Modify: `InstructionX_UIKit/charts/series_cartesian.py:953`
- Test: `tests/test_perf_line.py`

**Interfaces:**
- Consumes: `ChartWidget.anim.is_running()`、`LineSeriesRenderer._points`、既有 `prev_data`。
- Preserves: 首次入场、等长更新、不等长更新、None 断点及更新动画视觉。

- [ ] **Step 1：写“完成态零分配”及动画回归测试**

构造含 None 的点列，完成态调用 `_animated_points(1.0)` 必须返回同一对象；动画未运行时也返回同一对象。动画中、等长新旧数据必须逐点插值，不等长时直接返回当前点列。

```python
renderer._points = current
assert renderer._animated_points(1.0) is current
chart.anim.stop()
assert renderer._animated_points(0.5) is current
```

- [ ] **Step 2：运行测试确认旧实现失败**

Expected: 完成态和停止态返回新 list，断言失败。

- [ ] **Step 3：只增加快速返回，不改变有效动画**

```python
def _animated_points(self, anim_t):
    cur = self._points
    if anim_t >= 1.0 or not self.chart.anim.is_running():
        return cur
    prev_src = self._prev_points
    if self.prev_data is not None and len(self.prev_data) == len(self._entries):
        coord = self.chart.coord_for(self.opt)
        single = getattr(coord, "kind", "") == "singleAxis" if coord else False
        prev = []
        for i, item in enumerate(self.prev_data):
            x, y = parse_data_point(item, i)
            if y is None or coord is None:
                prev.append(None)
                continue
            try:
                prev.append(coord.map_point(y) if single
                            else coord.map_point(x, y))
            except Exception:
                prev.append(None)
        prev_src = prev
    if len(prev_src) != len(cur):
        return cur
    out = []
    for a, b in zip(prev_src, cur):
        if a is None or b is None:
            out.append(b)
        else:
            out.append(QPointF(_lerp(a.x(), b.x(), anim_t),
                               _lerp(a.y(), b.y(), anim_t)))
    return out
```

- [ ] **Step 4：运行折线、坐标系和视觉回归**

Run: `& $python tests\test_perf_line.py; & $python tests\test_chart_cartesian.py; & $python tests\test_chart_core.py`
Expected: 全部退出码 0；稳定完成态图像与基线零像素差异。

### Task 3：普通实线批量绘制，显式符号预算保持默认外观

**Files:**
- Modify: `InstructionX_UIKit/charts/series_cartesian.py:983-1108`
- Test: `tests/test_perf_line.py`、`tests/test_visual_compat.py`

**Interfaces:**
- Preserves: `showSymbol=True/False` 原语义和默认 `True`。
- Adds: `showSymbol="auto"` 为显式选择，初始终审预算 512，实际值由测量决定并写入指标。

- [ ] **Step 1：写 solid／smooth／step／area／polar／断线几何对照测试**

所有分支固定 `anim_t=1.0`、坐标范围、尺寸和主题。`showSymbol` 缺省和 `True` 必须与基线一致；`False` 不绘制符号；`"auto"` 小数据保留、超预算关闭，并报告实际符号数。

- [ ] **Step 2：运行测试，确认 `"auto"` 和批量路径尚未实现**

Expected: FAIL，不能先修改测试预期迎合实现。

- [ ] **Step 3：普通无面积实线使用 QPolygonF，其余继续原路径**

```python
from PySide6.QtGui import QPolygonF


def _line_needs_path(self, polar):
    return bool(
        polar
        or self.opt.get("smooth")
        or str(self.opt.get("step") or "") in ("start", "middle", "end")
        or self.opt.get("areaStyle")
    )


def _draw_line_body(self, painter, segments, polar):
    for segment in segments:
        if len(segment) < 2:
            continue
        if not self._line_needs_path(polar):
            painter.drawPolyline(QPolygonF(segment))
            continue
        path, _ = self._line_path(segment)
        if polar:
            path.closeSubpath()
        painter.drawPath(path)


def _draw_symbols(self, painter, valid, color, anim_t):
    setting = self.opt.get("showSymbol", True)
    enabled = bool(setting) if setting != "auto" else len(valid) <= 512
    if not enabled:
        return 0
    radius = max(1.0, _to_float(self.opt.get("symbolSize"), 6.0) / 2)
    radius *= max(0.2, anim_t)
    painter.setPen(QPen(color, 1.5))
    painter.setBrush(QColor(T("color.bg.elevated")))
    for point in valid:
        painter.drawEllipse(point, radius, radius)
    return len(valid)
```

若 `drawPolyline()` 在任何规定环境出现一像素差异，该路径不得启用，保留原 `QPainterPath`，再分析原因；不能修改基线截图。

- [ ] **Step 4：验证功能、零像素差异和指标**

Run: `& $python tests\test_perf_line.py; & $python tests\test_chart_cartesian.py; & $python tests\test_charts_gallery.py; & $python tests\test_visual_compat.py`
Expected: 全部通过；默认外观不变；显式 `"auto"` 的符号数符合预算。

### Task 4：散点去除数据复制并保护第三维点径与 dataIndex

**Files:**
- Modify: `InstructionX_UIKit/charts/series_cartesian.py:1142-1351`
- Modify: `InstructionX_UIKit/charts/sampling.py:251-318`
- Test: `tests/test_perf_scatter.py`

**Interfaces:**
- Consumes: `SeriesRenderer.data_view()`，禁止热路径 `self.data()`。
- Preserves: 数值／`[x,y]`／`[x,y,size]`／`{"value":...}`、dataZoom、tooltip 原始 `dataIndex`。

- [ ] **Step 1：写零复制和聚合索引测试**

让 `data()` 在被调用时抛异常，布局仍须成功。对固定种子数据，聚合点必须携带真实代表点下标，不能从浮点 x 猜测；第三维点径数据与一次性基线逐点比较。

```python
renderer.data = lambda: (_ for _ in ()).throw(AssertionError("禁止复制"))
renderer.layout(QRectF(0, 0, 800, 400))
assert [dot["index"] for dot in renderer._dots] == expected_indices
```

- [ ] **Step 2：确认旧布局调用 `data()` 时失败**

Expected: FAIL，抛出上述“禁止复制”。

- [ ] **Step 3：改为只读视图，聚合显式保存原始下标**

```python
for i, item in enumerate(self.data_view()):
    x, y = parse_data_point(item, i)
    # 后续点径与坐标映射逻辑保持原实现。
```

在 `column_aggregate()` 每个桶的输出中新增 `"index": mid`，`x` 仍按原契约取真实 x 的中点；`_large_dots()` 直接使用 `b["index"]`。含第三维点径或不被聚合实现支持的 option 必须回退非聚合路径，不能静默变成统一点径。

- [ ] **Step 4：验证散点与全部 tooltip**

Run: `& $python tests\test_perf_scatter.py; & $python tests\test_chart_cartesian.py; & $python tests\test_chart_components.py`
Expected: 全部通过，第三维点径、命中位置和原始 `dataIndex` 不变，完成态零像素差异。

### Task 5：采样与 category 批量映射保持逐点语义

**Files:**
- Modify: `InstructionX_UIKit/charts/sampling.py:182-248`
- Modify: `InstructionX_UIKit/charts/series_cartesian.py:874-951`
- Test: `tests/test_perf_sampling.py`

**Interfaces:**
- Preserves: 桶区间 `[ceil(c*n/m), ceil((c+1)*n/m))`、首尾、原 x 顺序、原始 `dataIndex`、浮点 `QPointF` 坐标及 `_fast_map_matches` 首用自检。
- Produces: 每次最多 64 个桶的二维临时块，不创建 `n × buckets` 巨型矩阵。

- [ ] **Step 1：写逐桶参考实现对照测试**

对 list、`NumericBuffer`、ndarray、含 None／NaN／Inf 和非法混合项分别比较：完整输出对、顺序、逐列极值、首尾和坐标值，不只比较长度。category 数据覆盖非空类目、空类目隐式下标、负下标和 dataZoom 偏移。

- [ ] **Step 2：运行新测试确认优化入口尚不存在**

Expected: 新分块函数或 category 快路径缺失导致 FAIL。

- [ ] **Step 3：实现有界分块极值计算并保留原回退**

```python
def _blocked_numpy_extrema(values, bounds, block=64):
    output = []
    for offset in range(0, len(bounds), block):
        part = bounds[offset:offset + block]
        extrema = [None] * len(part)
        valid_rows = []
        width = max(end - start for start, end in part)
        lows = _np.full((len(part), width), _np.inf)
        highs = _np.full((len(part), width), -_np.inf)
        for row, (start, end) in enumerate(part):
            segment = values[start:end]
            if _np.isnan(segment).any():
                # 与原 np.argmin/argmax 的 NaN 选择保持一致。
                extrema[row] = (start + int(_np.argmin(segment)),
                                start + int(_np.argmax(segment)))
                continue
            lows[row, :end - start] = segment
            highs[row, :end - start] = segment
            valid_rows.append(row)
        for row in valid_rows:
            start, _ = part[row]
            extrema[row] = (start + int(_np.argmin(lows[row])),
                            start + int(_np.argmax(highs[row])))
        output.extend(extrema)
    return output
```

集成时必须保持每个桶在原列表中的位置，不能按 `append` 顺序混入 NaN 特殊桶；实现者在测试中先固定此顺序，再替换 `bucket_sample()` 内逐桶 NumPy 调用。若实现不能同时保证顺序、NaN 和并列极值语义，就不接入该快路径。

category 快路径按 `AxisModel.local_index()` 的数字截断、窗口偏移、类目／隐式 band 数逐项实现，屏幕坐标保持浮点；首用自检逐点与 `coord.map_point()` 比较，差异超过 `1e-9` 即永久禁用快路径。

- [ ] **Step 4：运行几何与采样保真回归**

Run: `& $python tests\test_perf_sampling.py; & $python tests\test_chart_large.py; & $python tests\test_chart_cartesian.py`
Expected: 全部通过；`_fast_map_disabled` 为 False；逐列极值与参考实现完全一致。若测试分支尚无 `test_chart_large.py`，先在测试分支建立该覆盖，不能跳过保真检查。

### Task 6：流式数据和轴范围原子提交

**Files:**
- Modify: `InstructionX_UIKit/charts/core.py:1300-1379`
- Modify: `InstructionX_UIKit/charts/stream.py:254-454`
- Test: `tests/test_perf_stream.py`

**Interfaces:**
- Preserves: `stream(series=0, window=20000, interval=1/90, auto_scale=True)`、`set_stream_data(values, series=0)`、有界 RingBuffer、FrameCoalescer 和线程归属。
- Adds private: `ChartWidget._apply_stream_data(values, series=0, y_range=None, refresh_axes=None) -> bool`、`StreamSession.set_active(active)`。`refresh_axes=None` 保留公共入口“仅长度变化时刷新轴”的既有行为。

- [ ] **Step 1：写失败测试**

覆盖：auto-scale 不调用 `_rebuild()`／`update_option()`；不启动动画；固定 y 轴不扫描 min/max；每帧 `_option["series"][idx]["data"]` 与渲染器一致；长度变化正确刷新空 category 轴；轴更新频率不超过 10 Hz；隐藏时零重绘且队列有界；恢复只画最新窗口；关闭后定时器停止。

- [ ] **Step 2：运行测试确认旧 auto-scale 走全量更新**

Expected: auto-scale 分支调用 `update_option()`，测试失败。

- [ ] **Step 3：增加内部原子入口，公共方法保持兼容**

```python
def set_stream_data(self, values, series=0) -> bool:
    return self._apply_stream_data(values, series)


def _apply_stream_data(self, values, series=0, y_range=None,
                       refresh_axes=None) -> bool:
    try:
        index = int(series)
        if index < 0:
            return False
        renderer = self._series[index]
    except (TypeError, ValueError, IndexError):
        return False
    if values is None:
        return False
    buffer = to_buffer(values)
    data = buffer if buffer is not None else values
    try:
        length = len(data)
        series_option = self._option["series"][index]
    except (TypeError, KeyError, IndexError):
        return False
    renderer.opt["data"] = data
    series_option["data"] = data
    length_changed = self._stream_len.get(index) != length
    self._stream_len[index] = length
    if length_changed or refresh_axes is True or y_range is not None:
        if y_range is not None:
            low, high = y_range
            axis_option = self._option.get("yAxis")
            if not isinstance(axis_option, dict):
                axis_option = self._option["yAxis"] = {}
            axis_option["min"] = low
            axis_option["max"] = high
        self._refresh_axes_extent()
        self._static_key = None
        self._series_key = None
    self._layout_key = None
    self._paint_only_dirty = True
    self.anim.stop()
    self.anim.set_progress(1.0)
    self.update()
    return True
```

当前 `CHART_SPEC` 与 `GridCoord` 使用单个 xAxis／yAxis 字典，本入口保持该范围，不擅自增加多轴语义。坐标范围推导必须复用 `GridCoord.set_series()` 的既有逻辑；数据每次提交都同步 `_option`，不再只在长度变化时同步。固定 y 轴时不得为了 auto-scale 额外执行 `min(vals)`／`max(vals)`，长度变化引起的 category band 更新仍须正确执行。

- [ ] **Step 4：StreamSession 只调用原子入口**

auto-scale 使用初始 8 Hz 更新预算，只有数值轴且非两端固定时计算有限值范围。固定轴跳过扫描；范围未显著变化时不使静态层失效。隐藏时仍取空 coalescer 以防积压，但不入图；恢复时只提交 RingBuffer 的最新窗口。任何不支持原子入口的自定义图表才走旧 `update_option()` 回退并记录原因。

- [ ] **Step 5：运行流式、生命周期和几何验收**

Run: `& $python tests\test_perf_stream.py; & $python tests\test_chart_core.py; & $python tests\test_chart_cartesian.py`
Expected: auto-scale 全周期 `_rebuild` 次数为 0；无动画；隐藏 update 为 0；坐标铺满绘图区，不能只看“有数据”。

### Task 7A：修正保留 GL 的 gpuDirect 缓存与能力门禁

**Files:**
- Modify: `InstructionX_UIKit/charts/series_cartesian.py:667-734`
- Modify: `InstructionX_UIKit/charts/gl_series.py`、`charts/viewport.py`
- Test: `tests/test_gpu_direct.py`

**Interfaces:**
- Preserves: `gpuDirect=False` 默认路径、GL 不可用时软件回退和全部视觉 option。
- Adds internal: 显式数据版本、逐系列顶点缓存、实际上传计数及可观测回退原因。

- [ ] **Step 1：写顶点内容同长变化、逐系列隔离、上传次数和能力回退测试。**

相同 id／长度但内容变化时，只有调用方递增显式版本才更新 VBO；不允许再用 id＋长度推断内容未变。两个系列交替绘制不得共享顶点状态；smooth、step、areaStyle、symbol、虚线等未实现样式必须回退 QPainter。

- [ ] **Step 2：运行测试确认当前版本推断和共享管线不能满足契约。**

- [ ] **Step 3：按显式版本缓存转换结果，每个系列持有独立上传状态。**

只有 `GLSeriesPipeline.vertex_count == 数据点数` 且变换有效时才设置 GPU claim；此时跳过该系列不必要的 CPU 屏幕点布局。上传失败、超上限、着色器失败或不支持样式不得报告 `gpu_active=True`，QPainter 回退仍必须完整出图。`paintGL()` 内禁止再次 `makeCurrent()`。

- [ ] **Step 4：跑真实 GL 几何对照和原图表回归。**

断言顶点数、顶点内容、实际上传次数和屏幕坐标分布，不能只看非空截图。完成态与基线逐像素不同则不扩大 GPU claim 范围。

### Task 7B：删除聊天重入事件泵

**Files:**
- Modify: `InstructionX_UIKit/layouts/chat_conversation.py:783-855`
- Test: `tests/test_perf_chat.py`、原 `tests/test_fix_mdstream.py`

**Interfaces:**
- Preserves: `append_to_message()`、`finish_message()`、滚动跟随状态、公式异步到达、用户上翻阅读位置。

- [ ] **Step 1：写真实滚动与重入回归测试**

连续追加文本和模拟文档高度变化，用户上翻后不强拉到底；底部跟随后公式／图片增高仍完成一次最终跟随；延迟回调不得重入执行用户槽四次。

- [ ] **Step 2：确认旧实现对 `processEvents()` 的调用可被观测**

Expected: 旧 `_flush_and_follow` 连续调用四次。

- [ ] **Step 3：改为文档尺寸和滚动范围信号驱动的单次合并**

```python
def _follow_after_doc_change(self):
    if not self._follow or self._follow_pending:
        return
    self._follow_pending = True
    QTimer.singleShot(0, self._flush_follow_once)


def _flush_follow_once(self):
    self._follow_pending = False
    if self._follow:
        self._follow_scroll()
```

构造时连接 `verticalScrollBar().rangeChanged` 到 `_on_scroll_range`：仅在跟随开启、最大值实际变化且当前无 `_follow_pending` 时安排一次 `_follow_after_doc_change()`。删除 `QCoreApplication` 导入和四轮 `processEvents()`，不得在 mouseMove／resize／paint／token 路径新增同类调用。

- [ ] **Step 4：验证原有 Markdown 和聊天行为**

Run: `& $python tests\test_perf_chat.py; & $python tests\test_fix_mdstream.py; & $python tests\test_fix_chatactions.py`
Expected: 全部通过；最终滚动位置正确，零重入事件泵。

---

## P1：窗口交互、普通组件和生命周期

### Task 8：为 ChartWidget 与 BlueprintCanvas 增加受控 resize 预览

**Files:**
- Create: `InstructionX_UIKit/_resize_preview.py`
- Modify: `charts/core.py`、`charts/viewport.py`、`blueprint/canvas.py`、`blueprint/viewport.py`、`blueprint/node_widget.py`
- Test: `tests/test_perf_resize.py`

**Interfaces:**
- Adds private: `begin(size)`、`update(size)`、`finish()`、`cancel()`；single-shot 初始 100 ms，可在 80–120 ms 内按实测调整。
- Preserves: 原全质量路径可通过 `UIKIT_RESIZE_PREVIEW=off` 一键恢复；最终 DPR、命中、tooltip、焦点和坐标必须正确。

- [ ] **Step 1：写首次无旧帧、连续 resize、隐藏、销毁和 DPR 变化测试。**
- [ ] **Step 2：确认旧实现每个 resize 都全量布局／重建，测试失败。**
- [ ] **Step 3：先捕获旧有效帧，再改变视口几何；预览期间只缩放已有帧，停止该视口动画和自动缩放。**

```python
def schedule(self):
    self._timer.start(100)


def finish(self):
    self._timer.stop()
    if not self._active:
        return False
    self._active = False
    self._preview = None
    return True
```

无有效旧帧时直接执行一次全质量绘制，不能显示空白。隐藏／销毁调用 `cancel()` 并释放预览。最终只执行一次 `_layout_all(force=True)`、静态层和系列层重建。

Blueprint 必须同时处理节点子控件与边，不能只缩放背景而留下原位节点；优先复用已有 gesture proxy，不能正确截取／嵌入时保持旧路径并记录原因。

- [ ] **Step 4：验证预览次数、最终零像素差异和真实窗口操作。**

Expected: 连续尺寸变化期间不全量重建；松开 80–120 ms 后只重建一次；最终图像与基线一致，tooltip 命中和节点拖动正确。

### Task 9：在 UIKit 自有宿主验证系统窗口手势与回退

**Files:**
- Create in test workspace: `tests/perf/window_host.py`
- Test: `tests/test_window_gestures.py`
- Do not modify: InstructionX 的 `ui/main_window.py`、`ui/title_bar.py`

**Interfaces:**
- Uses: `QWindow.startSystemMove()`、`QWindow.startSystemResize(edges)`。
- Preserves: 只有返回 False 才进入手动回退；不拦截输入控件、菜单和按钮。

- [ ] **Step 1：建立空白、普通表单、图表、Blueprint、Mermaid 的 A–H 隔离矩阵。**
- [ ] **Step 2：验证空白原生边框、不透明、GL 全关时的音频症状；区分 UIKit 与系统／驱动因素。**
- [ ] **Step 3：在测试宿主接入系统手势，保留原手动路径用于 False 回退。**

```python
handle = window.windowHandle()
if handle is not None and handle.startSystemMove():
    event.accept()
    return
```

resize 将命中边缘准确映射为 `Qt.Edge` 组合；不给顶层 `setGeometry()` 加 16 ms 延迟。

- [ ] **Step 4：执行四边／四角、最大化还原、跨屏和形状变化各 5×30 秒，保存实际呈现与资源证据。**

### Task 10：同值样式跳过与逐步收窄 QSS

**Files:**
- Modify: `InstructionX_UIKit/theme.py:174-209` 及 `build_qss()` 的基座背景规则
- Test: `tests/test_theme_regression.py`、`tests/test_visual_compat.py`

- [ ] **Step 1：写同值不 polish、不同值只刷新一次的测试。**
- [ ] **Step 2：实现无行为变化的快速返回。**

```python
real = _SIZE_ALIAS.get(name, name)
if widget.property(real) == value:
    return
widget.setProperty(real, value)
style = widget.style()
style.unpolish(widget)
style.polish(widget)
widget.update()
```

- [ ] **Step 3：每次只移除一条冗余背景规则，跑全套亮暗截图和透明弹窗真机检查。**

不得直接删除 `QWidget` 字阶基座后改用 `setFont()`；当前 Qt 版本已验证它会被基座吞掉。字体改动须单独证明特异度，保持标题／正文／提示层级与图像完全一致。

- [ ] **Step 4：运行 `test_core`、`test_token_state`、全部组件／布局／gallery 和 `tools/check_spacing.py`。**

### Task 11：合并聊天渲染、统计与滚动，统一激活生命周期

**Files:**
- Modify: `layouts/chat_conversation.py`、`components/markdown_view.py`
- Modify: `charts/core.py`、`charts/stream.py`、`blueprint/canvas.py`
- Modify: `demo/main_window.py`
- Test: `tests/test_perf_chat.py`、`tests/test_lifecycle.py`

**Interfaces:**
- Adds: `on_ui_activated(self) -> None`、`on_ui_deactivated(self) -> None`，供页面宿主和下游插件管理器调用。
- Preserves: `MarkdownView.append_markdown()` 的直接调用语义和增量一致性；`ChatConversation` 公共消息 API 不变。

- [ ] **Step 1：写 chunk 分片一致性、最终刷新、统计定时、隐藏停更、恢复最新状态和重复销毁测试。**
- [ ] **Step 2：ChatConversation 合并 chunk，初始上限 30 Hz、统计 8 Hz，finish_message 先冲刷再冻结。**

`_messages[index]["content"]` 仍即时包含全部源文本；视图批次使用有界 pending 字符串，不按 token 排队。定时器必须可取消，更新消息／清空消息时 generation 失效，防止旧回调覆盖新消息。

- [ ] **Step 3：保留 MarkdownView 已有 `_append_incremental()`，避免额外 `setMarkdown → toHtml → setHtml`。**

只有未闭合代码块、公式和 Mermaid 等现有规则要求的场景才全量重渲染；不得重写为纯文本后丢失富文本、公式或图表。

- [ ] **Step 4：接入 activated／deactivated，并验证真实页面与最小化。**

隐藏时停止图表、流式入图、Blueprint 流动和装饰动画；恢复只刷新最新状态一次，不补跑历史帧。调用方显式开启的动画在恢复时保持原状态。长期资源和重复创建数量有界。

### Task 11A：普通动画、快照和阴影的有界优化

**Files:**
- Modify only measured hot paths: `InstructionX_UIKit/anim/property.py`、`anim/painted.py`、`theme.py`
- Test: `tests/test_animation_resources.py`、原 `test_anim_property.py`、`test_anim_painted.py`

- [ ] **Step 1：记录快照创建、缓存重建、每帧样式写入和隐藏 update。**

覆盖 4K 大区域、DPR 1／1.25／1.5／2、文字复杂子树、连续切页和重复播放。没有实测热点的小组件不做重写。

- [ ] **Step 2：写固定动画进度与主题下的像素回归和资源上界测试。**

每一预设保存初始、中段、完成帧；不能连拍两张自然抖动的图就判断样式变化。

- [ ] **Step 3：仅复用等价的静态快照和阴影缓存，键包含实际尺寸、DPR、主题和相关样式。**

保留 `_SnapshotOverlay` 方案，不重新引入已失效的 QGraphicsEffect／pos／geometry 动画路径。不得把 3×DPR 直接降为固定 1×来冒充优化；任何超采样策略改变都必须通过对应帧的零像素差异检查，否则保留原策略。禁止每帧 `setStyleSheet()` 的改动必须保持原自绘视觉。

- [ ] **Step 4：运行原动画、组件截图和真实播放验收，确认隐藏停更与资源释放。**

---

## P2：局部 Scene Graph 垂直切片（P0／P1 通过后才实施）

### Task 12：先写独立设计与能力门禁，再实现图表试点

**Files:**
- Create after separate design approval: `charts/quick_viewport.py`、`charts/scene_item.py`、`charts/scene_snapshot.py`、最小 QML 场景文件
- Modify: `charts/viewport.py`，不删除旧实现
- Test: `tests/test_scene_graph_chart.py`、`tests/perf/run_scene_graph.py`

**Interfaces:**
- `ChartWidget` 公共 API 不变。
- 显式实验开关 `UIKIT_CHART_BACKEND=raster|gl|quick`；默认保持原后端。
- 首批只接收普通实线折线、统一尺寸／已聚合散点、静态轴层、tooltip、pan／zoom、dataZoom、主题和最终高清 resize。

- [ ] **Step 1：登记模块许可和实际运行后端。**

逐项记录 QtQuick／Scene Graph 导入名、PySide6 版本、许可证、商业使用与分发义务。不得强制 qsb，不使用 Qt Charts／Qt Graphs。

- [ ] **Step 2：写精确能力门禁测试。**

smooth、step、areaStyle、symbol、虚线、极坐标、层级系列及任何未迁移 option 必须回退到已验证 QWidget 后端；回退原因可观测。不能让 Scene Graph 静默少画某一项。

- [ ] **Step 3：使用 QQuickView + createWindowContainer，不改用 QQuickWidget。**

验证原生窗口嵌入、裁剪、层叠、焦点、Tab 顺序、滚轮、tooltip、透明顶层、跨屏 DPR 和最终 resize。任何一项失败均不切换默认后端。

- [ ] **Step 4：UI 线程生成不可变快照，updatePaintNode 只同步 Scene Graph。**

采样、轴范围、Python 数据解析、主题读取和三角化不得进入 `updatePaintNode()`。静态数据只上传一次；节点和资源在正确线程创建／销毁。原生线宽不一致时使用有界采样几何三角化，不能以 1px 线替代原 2px 线。

- [ ] **Step 5：同机对照修复后的 QWidget 基线。**

只有功能与最终像素全部通过、4K 合格线每轮通过且性能稳定更优，才讨论默认工厂切换；否则保留实验开关或停止该路线。不得降低场景复杂度来促成切换。

### Task 13：Blueprint 只在图表试点成功后复用架构

**Files:**
- Modify only after chart gate: `blueprint/viewport.py` 及新的私有 Scene Graph 支持文件
- Test: 原 `test_blueprint.py`、`test_blueprint_demo.py` 和新真实交互矩阵

- [ ] **Step 1：逐项验证节点、连线、框选、拖动、缩放、平移、嵌入子控件、菜单和命中。**
- [ ] **Step 2：图表和 Blueprint 分别保留回退，但检查同一顶层窗口图形 API 一致。**
- [ ] **Step 3：完成三平台、高 DPI、隐藏／销毁／热重载与资源生命周期验收。**
- [ ] **Step 4：未通过时退出新热路径，保留完整旧实现；不删除功能。**

---

## P3：最终验收与候选交付

### Task 14：全组件功能、视觉、性能与许可验收

**Files:**
- Test: 全量原测试、新测试、`tests/checklist.md`、原始证据目录
- Modify only when actual documented behavior changes: `docs/USAGE.md`、相关 `AGENTS.md`

- [ ] **Step 1：API 快照逐项对比。**

覆盖包级导出、构造参数、公开方法／属性／信号、QWidget 返回类型、数据格式和默认值。快照只能发现接口差异，不能代替行为测试。

- [ ] **Step 2：全组件人工与自动交互矩阵。**

覆盖普通控件、13 布局、52 动画、全部图表系列与 option、Blueprint、CodeEditor／DiffEditor、Markdown／Mermaid、弹窗、键盘、IME、复制粘贴、焦点、滚轮、禁用、空／非法／极值、异步、高频、主题和生命周期。任何已知 P0／P1 回归都不能标记通过。

- [ ] **Step 3：最终图像逐像素对比。**

同一环境下逐像素差异必须为 0，暗色不能因亮色表面令牌相同而漏检。跨平台分别与该平台的原始基线比较，不混用不同字体／DPR 的图像。

- [ ] **Step 4：执行最终 4K 和窗口红线。**

每轮保存原始 JSON／CSV、最长帧、missed frames、P50／P95／P99、UI 长任务、CPU／GPU／内存／显存、音频现象和环境。未测 4K、三平台或音频就不能声称该项完成。

- [ ] **Step 5：检查许可、依赖和回滚。**

记录直接与传递依赖，验证干净环境只安装已批准依赖即可运行。证明 raster／GL／实验后端、resize 预览及各自回退开关有效，无无限缓存。

### Task 15：候选提交回 uniform_style 后重新验收并停止

- [ ] **Step 1：每个功能测试通过后，先请求用户确认，再按功能颗粒度提交。**

Commit 格式：`<type>(<scope>): <中文描述>`。不得自行使用 `Major_Fix:` 等前缀。

- [ ] **Step 2：最终候选经用户批准后提交回 `uniform_style`，记录明确 SHA。**
- [ ] **Step 3：测试集成工作区同步该最终 SHA，从零重跑完整测试、视觉和真实性能验收。**
- [ ] **Step 4：交付 SHA、原始帧时间、全组件矩阵、窗口操作记录、许可清单和回滚说明。**

任一门禁失败均不标记完成。到此停止：不合并 `dev`、不发布、不接入 InstructionX、不删除主程序 GL 预热或 OpenGL 强制设置。

---

## 计划自检

- 报告 P0 的动画、符号、直线、散点、采样、流式、聊天和生命周期分别落在 Task 2–7、11；P1 的 resize、QSS、系统手势、Markdown 与 activated／deactivated 落在 Task 8–11；P2／P3 落在 Task 12–15。
- 与报告有一处明确差异：默认符号不自动隐藏，因为用户要求外观不变。若必须满足报告“1 万点默认折线不画符号”的新视觉语义，需所有者单独批准该设计变化并重新冻结基线。
- 音频根因尚未确定。最小原生／不透明／GL 关闭构建仍复现时，必须保留系统／驱动独立调查；不能宣称 UIKit 修改必然修复。
- 不把“局部试点完成”当作“全部系列已迁移”；未迁移能力依靠已验证后端保持完整功能。
- 当前没有执行上述实施任务，没有创建分支、提交或发布，也没有真实的 4K／三平台／音频验收结果。
