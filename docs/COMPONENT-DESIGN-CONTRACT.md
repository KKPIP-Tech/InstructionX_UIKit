# 组件设计契约（Component Design Contract）

> 所有组件优化任务共同遵守。**这不是建议，是验收依据。**
> 违反契约的问题会被 `tools/audit_components.py` / `tools/check_spacing.py` 判为不合格。

本轮目标三件事：**现代、扁平、高密度**。三者不是三个独立诉求，是同一件事的
三个侧面——把装饰层（厚边框、重投影、多余嵌套）换成留白与层级，把控件尺寸压到
桌面端合理密度，并用一套令牌锁死所有间距。

---

## 0. 先读这个：为什么不能用肉眼验收

上一轮出现过「79 个页面全部渲染成功、截图全过」但**导航一点就抛异常**的情况。
原因是验证方式绕过了真实链路。因此本轮**禁止把「截图看起来没问题」当作完成**，
必须以下面三条可执行命令为准：

```bash
QT_QPA_PLATFORM=offscreen python tools/audit_components.py --only <你的模块>  # 版面审计
QT_QPA_PLATFORM=offscreen python tools/shoot.py --out /tmp/shots --mode light --pages <页面>
QT_QPA_PLATFORM=offscreen python tools/smoke_click.py                        # 交互冒烟
```

---

## 1. 密度刻度（不可协商）

控件高度由 `theme._INPUT_HEIGHTS` 统一定义，自绘组件必须与之对齐：

| 档位 | 高度 | 用途 |
|---|---|---|
| `sm` | **22px** | 表格内、工具条、密集表单 |
| `md` | **28px** | 默认。表单、筛选器、按钮 |
| `lg` | **34px** | 页面级主行动、空状态 |

> **常见违规**：组件设了 `uiksize="md"` 却把自己画成 20px 高（`switch`），
> 或 25px（`spin_box` / `date_picker` / `time_picker`）。
> 「声明的档位」与「实际渲染高度」必须一致，消费者才能正确排版。

### 1.1 滑块家族刻度

滑槽、手柄、手柄外扩量三者在原生 `QSlider` 与组件 `Slider`、
`BudgetSliderGroup` 之间**必须逐档一致**。单一来源是 `theme._GROOVE` /
`_HANDLE` / `_HANDLE_MARGIN` 三张表，`components/slider.py` 的 `_HANDLE`
表与之逐档镜像，改一处必须同步另一处。

| 档位 | 槽宽 | 手柄 QSS 宽度 | 手柄外扩 margin | **视觉手柄宽度** |
|---|---|---|---|---|
| `sm` | 4px | 10px | −4px | **14px** |
| `md` | 4px | 12px | −5px | **16px** |
| `lg` | 6px | 14px | −6px | **18px** |

> **为什么视觉宽度比 QSS 宽度大 4px**：QSS 中 `::handle` 的 `width` 指定的是
> **内容盒**，手柄有 2px 描边，两侧各加 2px。核对尺寸时按最后一列量，
> 拿 QSS 里的数字去对像素必然对不上。
>
> `margin` **不是** `(手柄 − 槽) / 2` 的公式值，而是逐档手调出来的
> （手柄带描边，视觉居中与几何居中并不重合）。直接照抄表，不要推导。
>
> 验收：`value=0` 时 `sub-page` 宽度为 0，槽里唯一的蓝色像素就是手柄描边环，
> 量它的列跨度即可得到视觉手柄宽度。

---

## 2. 间距：2px 基网格 + 令牌单一来源

- **间距一律取偶数像素**（主节奏 4px，2px 为半档）。
- **内边距取值必须来自令牌集合**，不得随手写 9 / 14 / 18 / 22。

可用令牌（`T("space.*")` / `T("layout.*")`）：

| 场景 | 令牌 |
|---|---|
| 同级控件之间 | `layout.inline.gap`（8） |
| 标签 → 控件 | `layout.field.gap`（8） |
| 图标 ↔ 文字 | `layout.icon.gap`（6） |
| 控件内部左右 | `layout.inset.pad_x`（8） |
| 控件内部上下 | `layout.inset.pad_y`（6） |
| 卡片内边距 | `layout.card.pad_x`（12）/ `pad_top`（8）/ `pad_bottom`（12） |
| 分区间距 | `layout.gutter`（12） |
| 代码块内边距 | `layout.code.pad`（8） |

需要令牌里没有的值时，**先在 `tokens.py` 的 `_LAYOUT` 里加一个命名令牌**，
再用 `T()` 引用。禁止裸数字。

---

## 3. 对齐基准

| 基准 | 规则 |
|---|---|
| 水平排列 | 同一行控件**垂直居中对齐**；高度不同也要对齐中心，不要顶对齐 |
| 文字左缘 | 标签类元素（label / 图标 / 徽标）左缘必须严格一致 |
| 图标中心 | 同一行内所有图标的几何中心应在同一水平线上 |
| 数值列 | 右对齐（表格数值、统计值），不要左对齐 |
| 内部文本 | 控件内文字的上下内边距对称，除非为光学补偿且**写注释说明** |

---

## 4. 扁平化

**减法优先**，按下面顺序考虑，不要一上来就加装饰：

1. ✅ 先删：多余边框、多余嵌套容器、装饰性投影、重复的背景层
2. ✅ 再压：把层级从「边框 + 阴影」改成「留白 + 底色差」
3. ⚠️ 最后才加：且新增装饰必须由令牌驱动

具体约定：

- 组件内部**不要**再套一层带边框的容器；需要分区时用 `spacing` + 底色。
- 阴影只用于浮层（Dialog / Drawer），**普通控件禁用**。
- **半透明弹出窗（`WA_TranslucentBackground`）默认不画投影，改用 1px 描边承担层次。**
  投影要在窗口边缘留一圈不同 alpha 的过渡带，真机合成器如何处理这圈 alpha
  无法在离屏环境保证（Windows 上实测表现为卡体外一圈矩形色块）。Popover 已按此
  改造并移除投影。**新增透明弹出窗一律照此办理**，不要引入半透明过渡。
- 透明弹出窗必须同时设 `WA_TranslucentBackground` **和** `WA_NoSystemBackground`，
  只设前者时 Qt 仍会用系统背景刷子把整个窗口矩形填成不透明色。
- 边框统一 `border`（1px），不要用 `border.strong` 画常规分隔。
- 圆角按元素的物理尺寸选档，见下表，**不要所有元素一个圆角**。

| 元素 | 圆角 |
|---|---|
| 小徽标 / 进度条 / 复选框 | `radius.sm`（4） |
| 按钮 / 输入框 / 导航项 / 代码块 | `radius.md`（8） |
| 卡片 / 浮层 / 下拉面板 | `radius.lg`（12） |

---

## 5. 色彩

- 语义色一律 `T("color.*")`，**禁止硬编码 hex**。
- 状态层级固定：页面 `bg.canvas` → 组件面 `bg.base` → 浮层 `bg.elevated`。
- 文字层级固定四级：`text.primary`（正文）/ `secondary`（说明）/
  `tertiary`（占位、辅助）/ `disabled`（禁用）。
- **前景与背景对比度 ≥ 4.5:1**（13px 正文），装饰性文字 ≥ 3:1。

---

## 6. 字体

**必须用 `set_font(w, "<scale>", "<weight>")`，不能用 `QFont` + `setFont()`。**

原因：全局 QSS 的 `QWidget { font-size }` 优先级高于控件自身字体，
`setFont()` 设置的字号会被**静默覆盖**，导致层级全部塌缩。

字阶：`font.xs` 11 / `sm` 12 / `md` 13（正文）/ `lg` 14 /
`title.sm` 15（卡片标题）/ `title.md` 17（区块标题）/ `title.lg` 20（页面标题）

字重：标题用 `semibold`，正文用 `regular`，数字强调用 `medium`。

---

## 7. 换行文本的处理

页面说明、代码行等**会换行的文本**，不要依赖 `QLabel.setWordWrap`：

`QLabel` 开 `wordWrap` 后 `minimumSizeHint` 高度几乎为 0，在
`QScrollArea` 的布局里会被优先压缩，实测出现「说明第二行被下一张卡片盖住」。

组件内部若需要换行文本：

1. 优先**预设固定宽度**并自行折行（参考 `demo/pages/common.py` 的 `_wrap_text`）；
2. 或给文本控件设置 `role="plain"` 容器并显式锁定高度；
3. 不要只加 `setWordWrap(True)` 就完事。

---

## 8. 常见错误速查

| 症状 | 根因 | 正确做法 |
|---|---|---|
| 高度和声明的 `uiksize` 对不上 | 自绘组件用了私有几何表 | 对齐 `_INPUT_HEIGHTS`，或改由 QSS 驱动 |
| 同类组件内边距不一样 | 各自写了字面量 | 统一引用 `layout.*` |
| 文字被压扁 / 第二行被盖 | wordWrap 标签在滚动布局里被压缩 | 自行折行 + 锁定高度 |
| 一行控件顶对齐、参差不齐 | 用了默认布局对齐 | 垂直居中对齐 |
| 控件内部还有一层灰框 | 多套了一层带边框容器 | 删掉，用 spacing 分区 |
| 深色下几乎看不见 | 用了 bg.base 而非 elevated | 按层级选 `canvas/base/elevated` |

---

## 9. 完成定义

一个组件算改完，必须同时满足：

- [ ] `audit_components.py --only <模块>` 输出 0 条该模块的问题
- [ ] `check_spacing.py` 通过
- [ ] 亮色 + 暗色两种主题下截图无异常
- [ ] 三档尺寸（sm/md/lg）渲染均正常
- [ ] 无硬编码 hex / 裸间距数字
- [ ] 改动写在 `deliverable.md`，并列出**需要共享层（theme.py / tokens.py）配合的改动**