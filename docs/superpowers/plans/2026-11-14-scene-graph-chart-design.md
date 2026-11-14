# Chart / Blueprint 的 RHI 后端设计与验收现状

## 当前边界

- Chart 与 Blueprint 默认使用 `QQuickView + QWidget.createWindowContainer + Scene Graph + RHI`，不是全组件 QML 层。公共 QWidget 构造、option、信号槽、命中和返回类型保持兼容。
- Qt 自动选择 Direct3D 11、Metal、Vulkan 或平台支持的其他 RHI 后端，不强制 OpenGL。旧 `QOpenGLWidget`、GL 探测、VBO / GLSL 管线、`gl_series.py`、`quick_viewport.py` 与 `quick_scene.qml` 已移除。
- `QSG_RENDER_LOOP=basic` 是原生嵌入的线程调度保护，不是图形 API 选择。离屏或 RHI 初始化失败时使用同一绘制体的 QWidget 软件视口；软件结果不能冒充真实呈现性能。

## 结构与所有权

- `InstructionX_UIKit/_rhi_texture.py`：`RhiTextureItem` 共享纹理节点、不可变帧结构、透明纹理清理和最多三帧引用。清空时保留并复用纹理节点，避免旧帧残留。节点使用 `ownsTexture=False` 时，`_retain_frame()` 必须对超龄纹理显式调用 `deleteLater()`；`_release_textures()` 在控件销毁时清理剩余纹理，不能只缩短 Python 引用队列而不删除 Qt 对象。
- `charts/rhi_viewport.py`：Chart 的原生容器、事件转发、焦点、最小化／隐藏恢复与同步计时。`scene_snapshot.py` 在 GUI 线程调用既有 `_paint_contents()`，完整保留静态轴、全部系列、组件、主题、tooltip、动画和 resize 预览。
- `blueprint/rhi_viewport.py`：节点／引脚／自定义体命中、键盘焦点和菜单路由。`scene_snapshot.py` 按既有顺序绘制背景、边、节点位图与可见自定义体；手势代理在结束后恢复真实子控件。
- `rhi_scene.qml` 仅承载对应 Scene Item。`updatePaintNode()` 只更新纹理与节点，不解析 option、采样、读取主题或调用 QPainter。

## 许可与模块

使用项目已有 PySide6 附带的 QtQuick、QtQml、QtQuickWidgets 与 Scene Graph，不新增 Python 依赖，不使用 Qt Charts／Qt Graphs，不要求 qsb／Qt Shader Tools。本机 PySide6 `6.11.1` 的 `METADATA` 声明 `LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only`，同时提供商业许可；分发继续履行既有 Qt/PySide6 许可与源码提供义务，本文件不替代法律审查。

## 功能与像素证据

- `tests/test_rhi_chart.py`、`test_rhi_blueprint.py`、`test_gpu_direct.py` 覆盖完整 option、样式、清理与软件快照。
- `tests/perf/run_rhi_chart.py` 验证 tooltip、图例、dataZoom、resize、主题、隐藏和最小化恢复；RHI 回读、完整快照与桌面合成均零像素差异。
- `tests/perf/run_rhi_blueprint.py` 验证节点、连线、拖动、缩放、嵌入文本、Delete、菜单、resize 与最小化恢复；节点与桌面图像均零像素差异。
- `tests/perf/run_gpu_direct.py` 验证旧 `gpuDirect` option 的兼容、样式、像素和有界资源，不再虚构 VBO 上传或 GL 管线认领。
- `tests/perf/compare_visual_baseline.py` 在同一冻结状态下对原始 `949b728` 源码与当前实现比较亮暗各 80 页；流式内容完成、异步内容稳定、时钟固定后才截图。

## 性能结论：当前未通过

当前实现由 QPainter 生成完整帧图像，再交给 RHI 纹理节点。RHI 负责平台呈现，不会自动加速 QPainter 的 CPU 路径光栅化。初步分段测量中，Chart `_series_pixmap` 平均约 283.77ms，而纹理节点更新约 0.0866ms；瓶颈在普通实线的 `RoundJoin` 光栅化与整帧快照，不在平台 API 名称。

真实 3840×2160、DPR 1.5、八个 2 万点系列的初步短测记录为：一张 Chart 约 1.19 FPS，另一张仅 1 帧，Blueprint 约 2.39 FPS，并出现多个 286–455ms UI 长任务。该结果远低于 60 FPS 门槛，不能宣称升级完成。

以下方案均被拒绝或未达标，不得为追求数字而降低画质：

- 原生线几何：有 40,707 个差异像素。
- 渐变纹理描边：有 1,807 个差异像素。
- 改用 BevelJoin／MiterJoin 或关闭抗锯齿：有 7,726／22,273／12,402 个差异像素。
- 保留重叠区的并行线程分片：零像素差异，但最快仍约 154ms。
- 独立进程分片：零像素差异，但单张 Chart 最快约 62ms，进程调度与回传成本过高，未接入正式后端。

## 必须继续满足的门禁

- 最终图像零像素差异；全量公开 API、组件交互和生命周期无回归。
- 真实 3840×2160 复杂场景每轮至少 60 秒、至少 5 轮，平均 FPS≥60、P95≤16.67ms、P99≤33.33ms，且无应用自身≥100ms 长任务。
- 窗口操作每类至少 30 秒、至少 5 轮，无黑帧、闪烁、假死、音频异常或资源无界增长。
- 当前 Win32 原生指针预检失败，`SetCursorPos` 返回 False 且光标不动，`SendInput` 也没有移动光标；原生鼠标验收仍为未验证。PresentMon 另行因权限不足而没有数据，二者不得混淆。
- 只有最终 SHA 上完整证据全部通过才可交付为验收成品；不得自动合并 `dev`、发布或接入 InstructionX。
