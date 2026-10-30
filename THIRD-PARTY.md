# 第三方项目致谢 / Third-Party Notices

本文档记录 InstructionX_UIKit 使用、内置或参考过的第三方项目。新增或升级第三方资产时，必须同步更新本文件。

> 本文件不改变各项目原有许可证；各项目仍以其原始许可证为准。

## 1. Iconoir

- 项目：Iconoir
- 来源：<https://github.com/iconoir-icons/iconoir>
- 官网：<https://iconoir.com/>
- 版本：**v7.12.1**
- 许可证：**MIT License**
- 版权：Copyright (c) 2021 Luca Burgio
- 在项目中的用途：`InstructionX_UIKit/icons.py` 的主图标来源。项目内置完整的 Iconoir v7.12.1 图标集：**1,383 个 Regular + 288 个 Solid = 1,671 个 SVG**，运行时用主题颜色替换 `currentColor` 后通过 QtSvg 渲染。

图标名统一使用 Iconoir 原名，不再保留 UIKit 早期手绘图标名映射；也可以使用 `get_icon("iconoir:<原名>")` 显式入口。

完整图标列表可通过 `icon_names()` / `search_icons()` 获取；Demo 左侧「设计令牌 → 图标库」页可视化全部图标。

Iconoir 的 MIT 许可证全文如下：

```text
MIT License

Copyright (c) 2021 Luca Burgio

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

## 2. 运行时依赖

以下依赖由 `pyproject.toml` / `requirements.txt` 声明，未在本仓库中重新分发其源代码（PySide6 等由安装器提供）：

| 项目 | 许可证 | 来源 | 用途 |
|---|---|---|---|
| Qt for Python / PySide6 | LGPL-3.0 / GPL-3.0 / 商业许可（按 Qt 授权方式） | <https://doc.qt.io/qtforpython/> | GUI 基座、QtSvg、QtWebEngine |
| qrcode | BSD-3-Clause | <https://github.com/lincolnloop/python-qrcode> | QRCodeView |
| Pillow | HPND | <https://python-pillow.org/> | 图片编码 / QRCode 依赖 |
| matplotlib | PSF-based（Matplotlib License） | <https://matplotlib.org/> | MarkdownView 的 LaTeX 公式渲染 |
| numpy | BSD-3-Clause | <https://numpy.org/> | 图表引擎的大规模数据管线 |
| Mermaid | MIT | <https://github.com/mermaid-js/mermaid> | MarkdownView 的 Mermaid 图表渲染（内置 `mermaid.min.js`） |

## 3. 维护约定

- 新增图标、字体、示例代码或其他第三方资产时，在本文件补充来源、版本、许可证和用途。
- 若第三方资产要求保留版权声明，必须同时保留其完整许可证文本。
- 升级 Iconoir 时，请更新 `InstructionX_UIKit/iconoir_icons.py` 的版本号、SVG 资产和本文件对应章节。
- 本文件是致谢与许可证清单，不构成法律意见；发布前请按实际分发形态复核依赖许可证。
