# Chart / Blueprint 的 RHI 后端设计与验收现状

## 当前默认直接 Canvas（`uniform_style@2aee131`）

- 真实窗口默认使用 `QCanvasPainterWidget + QCanvasPainter + QRhi` 直接绘制，由 Qt 自动选择平台 API。显式 `rhi` 选项保留下述 `QQuickView + Scene Graph` 完整快照路径；Canvas 能力不足时也回退到该路径。公共 QWidget API 不变，不做全组件 QML 迁移。
- 每个 Canvas 视口都是普通 QWidget 子控件，不经过 `QQuickWidget`、离屏 `QQuickWindow`、人工鼠标转发或独立原生透明覆盖窗口。28 个图表演示与 2 个蓝图画布的默认后端、真实首帧和重复切换已由 `tests/test_canvas_default_pages.py` 验证。
- `charts/canvas_item_viewport.py` 复用现有布局、坐标映射、采样、option、主题、信号和命中逻辑，绘制静态层、系列、组件与 tooltip；`blueprint/canvas_viewport.py` 只更新 Blueprint 场景，真实节点子控件继续接收 Qt 原生输入。
- 缩放直接更新布局并绘制，不使用旧帧拉伸。`ChartWidget.grab()` / `BlueprintCanvas.grab()` 委托真实视口，支持 QWidget 风格的矩形裁剪；显式导出与测试通过真实控件合成回读，不进入正常帧循环。
- Canvas 功能集合（`tests/test_canvas_*.py` 与 `test_blueprint_grid_texture.py`）全部通过。所有者将 Canvas 视觉验收定为**内容完整、视觉近似且无明显伪影**；不同光栅化器的单纯像素差异不单独判失败。`tests/shots/canvas_default_charts.png` 与 `canvas_default_blueprint.png` 保存了当前真实画面。
- Demo 主窗口在显示前将顶层表面映射到 Qt 自动选择的 RHI API，避免首次嵌入重型视口时销毁并重建可见窗口。`tests/test_page_switch_real.py` 九次顺序真实点击中主窗口销毁为 0、蓝图 `mapFrom` 警告为 0。
- 文档内 Mermaid 复用官方隐藏 Hub 的 QImage，以 QWidget 画布完成缩放和平移，不创建可见 WebEngine 子窗口；独立 MermaidView 的 WebEngine 路径由 `tests/test_mermaid_standalone_real.py` 单独验证。
- 普通交互启动器 `tests/perf/run_interactive.ps1` 不提升管理员权限。Canvas 真实 4K 短测约 53.7 FPS、P95 约 30.67ms，仍未达标；正式复杂场景 5×60 秒不能由短测代替。当前代码不得标记为最终验收成品，也不自动合并或发布。

## 当前边界

- Qt 自动选择 Direct3D 11、Metal、Vulkan 或平台支持的其他 RHI 后端，不强制 OpenGL。旧 `QOpenGLWidget`、GL 探测、VBO / GLSL 管线、`gl_series.py`、`quick_viewport.py` 与 `quick_scene.qml` 已移除。
- `QSG_RENDER_LOOP=basic` 只服务于显式 QQuickView 快照路径，不是图形 API 选择。离屏或 RHI 初始化失败时使用同一绘制体的 QWidget 软件视口；软件结果不能冒充真实呈现性能。

## 结构与所有权

- `InstructionX_UIKit/_rhi_texture.py`：`RhiTextureItem` 共享纹理节点、不可变帧结构、透明纹理清理和最多三帧引用。清空时保留并复用纹理节点，避免旧帧残留。节点使用 `ownsTexture=False` 时，`_retain_frame()` 必须对超龄纹理显式调用 `deleteLater()`；`_release_textures()` 在控件销毁时清理剩余纹理，不能只缩短 Python 引用队列而不删除 Qt 对象。
- `charts/rhi_viewport.py`：Chart 的原生容器、事件转发、焦点、最小化／隐藏恢复与同步计时。`scene_snapshot.py` 在 GUI 线程调用既有 `_paint_contents()`，完整保留静态轴、全部系列、组件、主题、tooltip、动画和 resize 预览。
- `blueprint/rhi_viewport.py`：节点／引脚／自定义体命中、键盘焦点和菜单路由。`scene_snapshot.py` 按既有顺序绘制背景、边、节点位图与可见自定义体；手势代理在结束后恢复真实子控件。
- `rhi_scene.qml` 仅承载对应 Scene Item。`updatePaintNode()` 只更新纹理与节点，不解析 option、采样、读取主题或调用 QPainter。

## 许可与模块

使用项目已有 PySide6 附带的 QtQuick、QtQml、QtQuickWidgets、Scene Graph、QtCanvasPainter 与 QRhiWidget，不新增 Python 依赖，不使用 Qt Charts／Qt Graphs，不要求 qsb／Qt Shader Tools 或额外原生插件。QtCanvasPainter 的 GPLv3／商业许可边界记录于 `THIRD-PARTY.md`，不得误写成 LGPL；其他组件继续履行既有 Qt/PySide6 许可与源码提供义务。本文件不替代法律审查。

## 功能与像素证据

- `tests/test_rhi_chart.py`、`test_rhi_blueprint.py`、`test_gpu_direct.py` 覆盖完整 option、样式、清理与软件快照。
- `tests/perf/run_rhi_chart.py` 验证 tooltip、图例、dataZoom、resize、主题、隐藏和最小化恢复；RHI 回读、完整快照与桌面合成均零像素差异。
- `tests/perf/run_rhi_blueprint.py` 验证节点、连线、拖动、缩放、嵌入文本、Delete、菜单、resize 与最小化恢复；节点与桌面图像均零像素差异。
- `tests/perf/run_gpu_direct.py` 验证旧 `gpuDirect` option 的兼容、样式、像素和有界资源，不再虚构 VBO 上传或 GL 管线认领。
- `tests/perf/compare_visual_baseline.py` 在同一冻结状态下对原始 `949b728` 源码与当前实现比较亮暗各 80 页；流式内容完成、异步内容稳定、时钟固定后才截图。

## 性能结论：当前未通过

显式 `rhi` 快照路径由 QPainter 生成完整帧图像，再交给 RHI 纹理节点；默认直接 Canvas 不走这段整帧快照。RHI 呈现不会自动加速 QPainter 的 CPU 路径光栅化。快照路径的初步分段测量中，Chart `_series_pixmap` 平均约 283.77ms，而纹理节点更新约 0.0866ms；瓶颈在普通实线的 `RoundJoin` 光栅化与整帧快照，不在平台 API 名称。

真实 3840×2160、DPR 1.5、八个 2 万点系列的初步短测记录为：一张 Chart 约 1.19 FPS，另一张仅 1 帧，Blueprint 约 2.39 FPS，并出现多个 286–455ms UI 长任务。该结果远低于 60 FPS 门槛，不能宣称升级完成。

以下方案均被拒绝或未达标，不得为追求数字而降低画质：

- 原生线几何：有 40,707 个差异像素。
- 渐变纹理描边：有 1,807 个差异像素。
- 改用 BevelJoin／MiterJoin 或关闭抗锯齿：有 7,726／22,273／12,402 个差异像素。
- 保留重叠区的并行线程分片：零像素差异，但最快仍约 154ms。
- 独立进程分片：零像素差异，但单张 Chart 最快约 62ms，进程调度与回传成本过高，未接入正式后端。

## 必须继续满足的门禁

- Canvas 要求内容完整、视觉近似且无明显伪影；显式 RHI 快照仍要求最终图像零像素差异。全量公开 API、组件交互和生命周期不得回归。
- 真实 3840×2160 复杂场景每轮至少 60 秒、至少 5 轮，平均 FPS≥60、P95≤16.67ms、P99≤33.33ms，且无应用自身≥100ms 长任务。
- 窗口操作每类至少 30 秒、至少 5 轮，无黑帧、闪烁、假死、音频异常或资源无界增长。
- 普通交互启动器已解决前台与原生指针探针；完整手势、跨屏、时长与资源矩阵仍未闭环。PresentMon 因权限不足没有数据，不能与前台权限问题混淆。
- 只有最终 SHA 上完整证据全部通过才可交付为验收成品；不得自动合并 `dev`、发布或接入 InstructionX。
