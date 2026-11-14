# 局部 Scene Graph 图表试点设计与门禁结论

## 边界

- 仅新增可选的 `UIKIT_CHART_BACKEND=quick` 实验路径，默认 `raster`／`gl` 行为不变。
- 保持 `ChartWidget(QWidget)` 的公开构造、option、信号槽与返回类型；不迁移普通组件，不使用 QQuickWidget、QQuickPaintedItem、Qt Charts 或 Qt Graphs。
- 首批仅接受普通实线折线、静态坐标轴与最终帧。smooth、step、areaStyle、符号、虚线、非 Grid 坐标、交互覆盖层、组件、动画中状态及超载数据均精确回退到既有 QWidget 后端。
- 不使用 `qsb`，不增加 Python 依赖。

## 许可与模块

本机 PySide6 `6.11.1` 的 `METADATA` 声明 `LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only`，同时提供商业许可。使用既有 PySide6 附带的 `QtQuick`、`QtQml`、`QtQuickWidgets`、Scene Graph 与 OpenGL 模块，不引入新的模块或工具链。分发时沿用项目现有 Qt/PySide6 许可与源码提供义务；本文件不替代法律审查。

## 结构

- `scene_snapshot.py`：在 UI 线程调用既有布局与静态层，冻结采样后屏幕坐标、颜色、线宽、绘图区与静态位图。
- `scene_item.py`：在 `updatePaintNode()` 中仅同步不可变快照，使用 `QQuickItem + QSGGeometry + QSGSimpleRectNode` 内部 C++ 几何/材质。最近三帧节点引用有界，纹理按键复用；不在这里解析数据、采样、读主题或调用 QPainter。
- `quick_viewport.py`：`QQuickView + QWidget.createWindowContainer`，合并多次更新到一次事件循环同步；回退视口按需创建，稳定使用 Scene Graph 时释放。QML 场景先于 QWidget 销毁时以 `shiboken6.isValid()` 阻止悬空清理。
- `quick_scene.qml`：仅承载一个 `ChartSceneItem`，不是全组件 QML 层。

直接构造的 `QSGGeometryNode` 和 Python 材质在本机持续运行时发生访问违例；现采用 `QSGSimpleRectNode` 内部 C++ 几何与材质，替换其顶点为折线。不能用非空截图代替该生命周期验证。

## 验证与结论

- `tests/test_scene_graph_chart.py` 覆盖能力门禁、快照形状与样式、offscreen 回退、真实 QQuickView 逐点屏幕几何、option 回退及 8 次创建/渲染/销毁循环。
- `tests/perf/run_realtime.py --backend quick` 与原复杂负载共用数据、窗口和交换帧口径。
- 实测真实渲染器为 `Intel(R) Graphics`，不是 NVIDIA 独立显卡。
- 当前局部 Scene Graph 约 15 FPS，低于修复后的现有 GPU 路径，更远低于 60 FPS 合格线；不得启用为默认后端。
- 保留显式实验开关和本证据，不以离线 benchmark、平均绘制耗时或静态截图冒充性能通过。后续只有完整交互能力、最终像素和真实 4K 门槛全部通过，才重新评估默认接入。
