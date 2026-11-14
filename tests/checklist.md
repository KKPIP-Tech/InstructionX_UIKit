# 需求完整性与功能验收核对表

## 组件与布局

- [x] 13 个布局预设：top_nav_bar、holy_grail、card_grid、single_column、sidebar_layout、master_detail、split_panel、dashboard_grid、hero_section、centered_container、waterfall、media_left_right、chat_conversation。
- [x] 52 个动画预设：28 个属性动画与 24 个自绘动画；原动画回归、固定帧、隐藏停更和资源上界通过。
- [x] 59 个组件的输入／展示／反馈行为、空态、亮暗主题与真实导航点击。
- [x] `set_property()` 同值跳过 polish；160 个亮暗页面状态的最终 RGBA 像素零差异。
- [x] 248 个公开导出、构造签名、基类、方法、属性与信号兼容；允许的新生命周期接口存在。
- [x] 6 类顶层透明弹窗、Tour 覆盖层与预算徽标：原始与当前实现的原生 Win32 图像在亮暗共 16 个状态下零像素差异。

## 图表与大数据

- [x] 直角坐标、层级关系、极坐标、日历、地图、平行坐标等 21 种系列及图表组件回归。
- [x] 普通实线批量绘制、显式符号预算、散点原始 dataIndex、采样极值、category 映射与流式原子提交。
- [x] 原 `gpuDirect` option 在 RHI 下的字段保留、样式、像素、缓存与有界资源；旧 GL VBO 管线已删除。
- [x] resize 预览与高清恢复、父控件不重复绘制、最终图像一致。
- [x] 默认 RHI、offscreen 软件回退、真实 Direct3D 11 嵌入与 8 次创建销毁。
- [x] Chart 的 tooltip／图例／dataZoom／主题／resize 与 Blueprint 的节点／引脚／文本／菜单交互；快照和桌面图像零像素差异。
- [ ] RHI 复杂 4K 性能门禁；完整快照的 QPainter 光栅化仍未达到帧预算。

## 生命周期与内容

- [x] ScrollStoryArea、ScrollReveal、横向滚动条和聊天延迟回调销毁后不再访问失效对象。
- [x] 聊天 chunk 合并、统计降频、最终同步、编辑／删除／清空代次失效、底部跟随与隐藏恢复。
- [x] Chart／Blueprint／页面宿主的 `on_ui_activated` / `on_ui_deactivated`；恢复最新状态且保留显式动画状态。
- [x] Markdown 分片一致性、公式、Mermaid 主／降级路径、主题与销毁清理。
- [x] CodeEditor／DiffEditor 的键盘、IME 预编辑与提交、焦点、多选、查找替换、补全、悬停、撤销重做、滚动同步、自动断点、只读与 hunk 交互矩阵。

## 性能与系统验收

- [ ] 真实 3840×2160 复杂场景：预热后至少 5 轮、每轮至少 60 秒；平均 FPS≥60、P95≤16.67ms、P99≤33.33ms，无应用自身≥100ms 长任务。
- [ ] 拖动、四边／四角缩放、最大化／还原、跨屏和形状变化：每类至少 30 秒且至少 5 轮，均达到同一红线。
- [ ] 原生鼠标、黑帧、闪烁、假死、音频异常和资源无界增长；`tests/perf/check_native_input.py` 已确认当前会话 `SetCursorPos` 返回 False 且 `SendInput` 不移动光标，原生鼠标与长期资源均未验收。
- [ ] PresentMon／WPA 权限与原始呈现证据；当前未提权，未将缺失数据标为通过。
- [x] `ae3f59d` 上 55/55 独立脚本正常退出，真实 RHI、透明弹窗、160 状态视觉 A/B、80 页点击、`main.py` 启动退出及纹理创建／释放／关闭清理均已复核。

## 文档与交付

- [x] `docs/Design.md`：设计令牌与视觉规范。
- [x] `docs/USAGE.md`：安装、快速开始、主题、组件、布局、动画、图表、后端与生命周期。
- [x] `README.md`：当前结构、安装、Demo 启动和 `uniform_style`／`uniform_test` 工作流。
- [x] `THIRD-PARTY.md`：运行时依赖与 PresentMon 测量工具许可、哈希和权限说明。
- [x] `docs/superpowers/plans/`：性能实施、Scene Graph 设计与验收状态，未验证项不标通过。
- [ ] 最终 SHA 上从零重跑并交付原始证据、功能矩阵与回滚说明；不合并 `dev`、不发布、不接入 InstructionX 主仓库。
