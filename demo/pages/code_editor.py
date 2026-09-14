# -*- coding: utf-8 -*-
"""代码编辑器演示页（CE_SPEC §5，E4）。

两个子页（``Tabs`` 切换）：

- **编辑器演示**：工具条（语言 / 字体族 / 字号 ± / 小地图 / 换行 /
  括号着色）+ ``CodeEditor``（载入语法丰富的 Python 示例，切语言换示例）
  + 演示按钮组（诊断 / 断点 / 查找 / 替换 / 跳行 / 补全 / 悬停 / 折叠）
  + 底部状态栏（行:列 / 选中字符数 / 语言 / 缩进 / UTF-8，
  由 ``cursor_position_changed`` / ``selection_changed`` 等信号实时驱动，
  演示「信号实时反馈主程序」的对接方式）；
- **Diff 对比演示**：左右两个可编辑 ``TextArea`` + 「更新对比」实时重算，
  ``DiffEditor`` 自带模式切换（并排 / 内联 / 自动，断点 900px）与
  hunk 导航 / 统计。

补全 provider 返回 Python 关键字 + 代码片段（kind / detail 齐全）；
悬停 provider 对示例中的函数名给出签名富文本气泡。
页面仅组合既有组件，主题切换由 CodeEditor / DiffEditor / 组件库各自保证。
"""

import keyword
import re

from PySide6.QtGui import QFont
from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget

from InstructionX_UIKit.code_editor import CodeEditor, DiffEditor
from InstructionX_UIKit.components import (
    Button,
    ComboBox,
    Switch,
    Tabs,
    TextArea,
)
from InstructionX_UIKit.theme import T, set_property
from InstructionX_UIKit.tokens import MONO_FAMILY

from .common import Section, hint_label, make_page, row

__all__ = ["create_page", "EditorDemoPage", "DiffDemoPage"]

# ---------------------------------------------------------------------------
# 示例代码（切语言时载入）
# ---------------------------------------------------------------------------

PY_SAMPLE = '''#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""订单服务示例：演示 CodeEditor 的 Python 语法高亮。

覆盖：关键字 / 字符串（含三引号与 f-string）/ 注释 / 数字 /
装饰器 / 类型标注 / 运算符 / 内置函数。悬停 `calculate_total`
等函数名可见签名气泡；Ctrl+Space 触发补全（默认不自动弹出）。
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from enum import Enum, auto
from pathlib import Path
from typing import Iterable, Optional


TAX_RATE = 0.06          # 税率常量
MAX_RETRY = 3            # 重试上限
_DATA_DIR = Path("./data")


class OrderStatus(Enum):
    """订单状态机。"""

    PENDING = auto()
    PAID = auto()
    SHIPPED = auto()
    CANCELLED = auto()


@dataclass(order=True)
class OrderItem:
    """单个订单条目。"""

    name: str
    price: float
    quantity: int = 1
    tags: list[str] = field(default_factory=list)

    @property
    def subtotal(self) -> float:
        return round(self.price * self.quantity, 2)


def calculate_total(items: Iterable[OrderItem],
                    discount: float = 0.0) -> float:
    """计算订单总额（含折扣与税率）。"""
    if not 0.0 <= discount < 1.0:
        raise ValueError(f"折扣越界: {discount!r}")
    base = sum(item.subtotal for item in items)
    total = (base * (1 - discount)) * (1 + TAX_RATE)
    return math.floor(total * 100) / 100


async def load_orders(path: Path) -> list[dict]:
    """异步载入订单 JSON（示例占位）。"""
    text = path.read_text(encoding="utf-8")
    return json.loads(text)


def render_report(orders: list[dict]) -> str:
    """渲染文本报表，返回多行字符串。"""
    lines = ["=== 订单报表 ==="]
    for idx, order in enumerate(orders, start=1):
        status = OrderStatus[order.get("status", "PENDING")]
        mark = "√" if status is OrderStatus.PAID else "…"
        lines.append(f"{idx:>3}. [{mark}] {order['name']:<12}"
                     f" ¥{order['total']:>8.2f}")
    return "\\n".join(lines)


def main() -> None:
    items = [OrderItem("机械键盘", 399.0, 1, tags=["外设"]),
             OrderItem("腕托", 59.5, 2)]
    total = calculate_total(items, discount=0.1)
    print(f"应付总额: ¥{total:.2f}")
    assert total > 0, "总额必须为正"


if __name__ == "__main__":
    main()
'''

CPP_SAMPLE = '''// 最小线程池示例（C++17）
#include <atomic>
#include <condition_variable>
#include <functional>
#include <mutex>
#include <queue>
#include <thread>
#include <vector>

class ThreadPool {
public:
    explicit ThreadPool(size_t workers = 4) : stop_(false) {
        for (size_t i = 0; i < workers; ++i) {
            pool_.emplace_back([this] { run(); });
        }
    }

    ~ThreadPool() {
        stop_ = true;
        cv_.notify_all();
        for (auto& t : pool_) t.join();
    }

    void submit(std::function<void()> fn) {
        std::lock_guard<std::mutex> lk(mu_);
        tasks_.push(std::move(fn));
        cv_.notify_one();
    }

private:
    void run() {
        while (!stop_) {
            std::function<void()> task;
            {
                std::unique_lock<std::mutex> lk(mu_);
                cv_.wait(lk, [this] { return stop_ || !tasks_.empty(); });
                if (tasks_.empty()) return;
                task = std::move(tasks_.front());
                tasks_.pop();
            }
            task();
        }
    }

    std::vector<std::thread> pool_;
    std::queue<std::function<void()>> tasks_;
    std::mutex mu_;
    std::condition_variable cv_;
    std::atomic<bool> stop_;
};
'''

JS_SAMPLE = '''// 防抖 + 简单事件总线（ES2022）
export function debounce(fn, delay = 200) {
  let timer = null;
  return (...args) => {
    clearTimeout(timer);
    timer = setTimeout(() => fn(...args), delay);
  };
}

export class EventBus {
  #handlers = new Map();

  on(name, fn) {
    const list = this.#handlers.get(name) ?? [];
    list.push(fn);
    this.#handlers.set(name, list);
    return () => this.off(name, fn);
  }

  off(name, fn) {
    const list = this.#handlers.get(name) ?? [];
    this.#handlers.set(name, list.filter((h) => h !== fn));
  }

  emit(name, payload) {
    for (const fn of this.#handlers.get(name) ?? []) {
      try {
        fn(payload);
      } catch (err) {
        console.error(`[bus] ${name} 处理失败`, err);
      }
    }
  }
}

const bus = new EventBus();
bus.on("save", debounce((doc) => console.log("saved", doc.id), 300));
'''

TS_SAMPLE = '''// 泛型仓库模式（TypeScript）
interface Entity {
  readonly id: string;
  createdAt: Date;
}

type Predicate<T> = (item: T) => boolean;

class Repository<T extends Entity> {
  private items = new Map<string, T>();

  add(item: T): void {
    if (this.items.has(item.id)) {
      throw new Error(`重复主键: ${item.id}`);
    }
    this.items.set(item.id, item);
  }

  find(where: Predicate<T>): T[] {
    return [...this.items.values()].filter(where);
  }

  async remove(id: string): Promise<boolean> {
    return this.items.delete(id);
  }
}

interface User extends Entity {
  name: string;
  age?: number;
}

const repo = new Repository<User>();
repo.add({ id: "u-1", name: "张三", createdAt: new Date() });
const adults = repo.find((u) => (u.age ?? 0) >= 18);
console.log(adults.length);
'''

JSON_SAMPLE = '''{
  "name": "instructionx-uikit",
  "version": "1.4.0",
  "private": true,
  "description": "纯 PySide6 桌面组件库",
  "keywords": ["pyside6", "ui-kit", "desktop"],
  "engines": { "python": ">=3.9" },
  "scripts": {
    "demo": "python main.py",
    "test": "python tests/test_gallery.py"
  },
  "dependencies": {
    "PySide6": ">=6.5",
    "qrcode": "^7.4"
  },
  "theme": {
    "light": { "primary": "#3F5E8C", "radius": 8 },
    "dark": { "primary": "#7FA6E0", "radius": 8 }
  },
  "features": {
    "editor": true,
    "charts": true,
    "blueprint": false
  },
  "counts": [28, 24, 9, null]
}
'''

HTML_SAMPLE = '''<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <title>代码编辑器 · 示例页</title>
  <style>
    body { font-family: system-ui, sans-serif; margin: 24px; }
    .badge { color: #3f5e8c; border: 1px solid currentColor; }
  </style>
</head>
<body>
  <!-- 主区域 -->
  <main id="app" class="layout" data-theme="light">
    <h1>InstructionX UIKit</h1>
    <p>纯 <strong>PySide6</strong> 实现的桌面组件库。</p>
    <ul class="toc">
      <li><a href="#editor">代码编辑器</a></li>
      <li><a href="#charts">图表引擎</a></li>
    </ul>
    <button type="button" disabled>加载中…</button>
    <img src="logo.png" alt="logo" width="96">
  </main>
  <script src="./app.js" defer></script>
</body>
</html>
'''

CSS_SAMPLE = '''/* 主题变量 + 卡片样式 */
:root {
  --primary: #3f5e8c;
  --radius-lg: 12px;
  --shadow: 0 4px 16px rgba(15, 23, 42, 0.12);
}

.card {
  display: grid;
  grid-template-rows: auto 1fr;
  gap: 8px;
  padding: 16px 20px;
  border: 1px solid color-mix(in srgb, var(--primary) 30%, transparent);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow);
  transition: transform 0.2s ease-in-out, opacity 0.2s;
}

.card:hover {
  transform: translateY(-2px);
}

.card > h3.title::before {
  content: "◆";
  margin-right: 6px;
  color: var(--primary);
}

@media (max-width: 768px) {
  .card { padding: 12px; }
}
'''

MARKDOWN_SAMPLE = '''# InstructionX UIKit 使用指南

> 纯 **PySide6** 桌面组件库，亮 / 暗主题一键切换。

## 快速开始

1. 安装依赖：`pip install PySide6 qrcode[pil]`
2. 运行演示：`python main.py`
3. 在页面中查看每个组件的「用法」代码标签。

## 代码示例

```python
from InstructionX_UIKit.components import Button

btn = Button("确定", variant="primary", size="md")
btn.clicked.connect(lambda: print("clicked"))
```

## 功能清单

- [x] 设计令牌与主题系统
- [x] 50+ 组件换肤
- [x] 原生图表引擎
- [ ] ~~WebView 内嵌~~（刻意不做）

| 模块 | 说明 |
| ---- | ---- |
| `theme` | 主题管理 |
| `code_editor` | 代码编辑器 |

详见 [USAGE.md](../docs/USAGE.md)。
'''

QSS_SAMPLE = '''/* Qt 样式表示例（UIKit 主题 QSS 片段） */
QWidget {
    font-family: "Noto Sans CJK SC", "Microsoft YaHei", sans-serif;
    font-size: 14px;
    color: #1f2430;
}

QPushButton[variant="primary"] {
    background-color: #3f5e8c;
    color: #ffffff;
    border: none;
    border-radius: 8px;
    padding: 6px 16px;
}

QPushButton[variant="primary"]:hover {
    background-color: #4a6ca3;
}

QPushButton[variant="primary"]:pressed {
    background-color: #354c73;
}

QPushButton:disabled {
    background-color: rgba(63, 94, 140, 0.4);
    color: rgba(255, 255, 255, 0.7);
}

QLineEdit:focus {
    border: 1px solid #3f5e8c;
}
'''

#: 语言名 -> (下拉显示名, 示例代码)
LANG_SAMPLES = {
    "python": ("Python", PY_SAMPLE),
    "cpp": ("C++", CPP_SAMPLE),
    "js": ("JavaScript", JS_SAMPLE),
    "ts": ("TypeScript", TS_SAMPLE),
    "json": ("JSON", JSON_SAMPLE),
    "html": ("HTML", HTML_SAMPLE),
    "css": ("CSS", CSS_SAMPLE),
    "markdown": ("Markdown", MARKDOWN_SAMPLE),
    "qss": ("QSS", QSS_SAMPLE),
}

#: 字体族下拉：显示名 -> set_font_family 参数（≥4 种等宽字体）
FONT_OPTIONS = [
    ("Cascadia Code", "Cascadia Code, Consolas, monospace"),
    ("JetBrains Mono", "JetBrains Mono, Cascadia Code, monospace"),
    ("Consolas", "Consolas, Courier New, monospace"),
    ("Fira Code", "Fira Code, Cascadia Code, monospace"),
    ("Courier New", "Courier New, monospace"),
    ("系统等宽", MONO_FAMILY),
]

# ---------------------------------------------------------------------------
# 补全 / 悬停 provider 演示数据
# ---------------------------------------------------------------------------

_PY_SNIPPETS = [
    {"label": "def", "kind": "snippet", "detail": "函数定义片段",
     "insert": "def name(args):\n    pass"},
    {"label": "class", "kind": "snippet", "detail": "类定义片段",
     "insert": "class Name:\n    def __init__(self):\n        pass"},
    {"label": "for", "kind": "snippet", "detail": "for 循环片段",
     "insert": "for item in items:\n    pass"},
    {"label": "ifmain", "kind": "snippet", "detail": "主程序入口片段",
     "insert": "if __name__ == \"__main__\":\n    main()"},
    {"label": "try", "kind": "snippet", "detail": "异常捕获片段",
     "insert": "try:\n    pass\nexcept Exception as exc:\n    raise"},
]

_HOVER_DOCS = {
    "calculate_total": (
        "<b>def</b> calculate_total(items: Iterable[OrderItem], "
        "discount: float = 0.0) -&gt; float"
        "<br><i>计算订单总额（含折扣与税率）。</i>"),
    "render_report": (
        "<b>def</b> render_report(orders: list[dict]) -&gt; str"
        "<br><i>渲染文本报表，返回多行字符串。</i>"),
    "load_orders": (
        "<b>async def</b> load_orders(path: Path) -&gt; list[dict]"
        "<br><i>异步载入订单 JSON（示例占位）。</i>"),
    "main": "<b>def</b> main() -&gt; None<br><i>演示入口函数。</i>",
    "OrderItem": (
        "<b>@dataclass</b> class OrderItem"
        "<br><i>单个订单条目：name / price / quantity / tags。</i>"),
}

_WORD_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def _completion_items():
    """Python 关键字 + 片段的完整候选（kind / detail 齐全）。"""
    items = list(_PY_SNIPPETS)
    for kw in sorted(keyword.kwlist):
        items.append({"label": kw, "kind": "keyword",
                      "detail": "Python 关键字", "insert": kw})
    for fn in ("print", "len", "range", "enumerate", "isinstance", "sum"):
        items.append({"label": fn, "kind": "function",
                      "detail": "内置函数", "insert": fn})
    return items


# ---------------------------------------------------------------------------
# 子页 A：编辑器演示
# ---------------------------------------------------------------------------

class EditorDemoPage(QWidget):
    """编辑器演示子页：工具条 + CodeEditor + 演示按钮 + 实时状态栏。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._font_size = 13

        # -- 编辑器 -------------------------------------------------------
        self.editor = CodeEditor()
        self.editor.setMinimumHeight(460)
        self.editor.set_language("python")
        self.editor.set_text(PY_SAMPLE)

        # -- 工具条 -------------------------------------------------------
        self.lang_combo = ComboBox(
            [label for label, _s in LANG_SAMPLES.values()], size="sm")
        self.lang_combo.setCurrentText("Python")
        self.lang_combo.currentTextChanged.connect(self._on_lang_changed)

        self.font_combo = ComboBox([n for n, _f in FONT_OPTIONS], size="sm")
        self.font_combo.currentTextChanged.connect(self._on_font_changed)

        self.btn_font_down = Button("A-", variant="default", size="sm")
        self.btn_font_up = Button("A+", variant="default", size="sm")
        self.font_size_label = QLabel(f"{self._font_size}px")
        self.btn_font_down.clicked.connect(lambda: self._bump_font(-1))
        self.btn_font_up.clicked.connect(lambda: self._bump_font(+1))

        self.sw_minimap = Switch(checked=True, size="sm")
        self.sw_minimap.toggled.connect(self.editor.set_minimap_visible)
        self.sw_wrap = Switch(checked=False, size="sm")
        self.sw_wrap.toggled.connect(self.editor.set_word_wrap)
        self.sw_bracket = Switch(checked=True, size="sm")
        self.sw_bracket.toggled.connect(self.editor.set_bracket_colorization)
        # 快捷键系统演示：总开关 + 自动补全开关
        self.sw_shortcuts = Switch(checked=True, size="sm")
        self.sw_shortcuts.setToolTip(
            "关闭后编辑器不安装任何自定义快捷键（Ctrl+F/H/G/D/Space/Y）")
        self.sw_shortcuts.toggled.connect(self.editor.set_shortcuts_enabled)
        self.sw_autocomplete = Switch(checked=False, size="sm")
        self.sw_autocomplete.setToolTip(
            "默认关闭：补全仅 Ctrl+Space 触发；开启后输入字符自动弹出")
        self.sw_autocomplete.toggled.connect(
            self.editor.set_completion_auto_trigger)

        toolbar = row(
            QLabel("语言"), self.lang_combo,
            QLabel("字体"), self.font_combo,
            QLabel("字号"), self.btn_font_down, self.font_size_label,
            self.btn_font_up,
            QLabel("小地图"), self.sw_minimap,
            QLabel("换行"), self.sw_wrap,
            QLabel("括号着色"), self.sw_bracket,
            QLabel("快捷键"), self.sw_shortcuts,
            QLabel("自动补全"), self.sw_autocomplete,
            spacing=6,
        )

        # -- 演示按钮组 ----------------------------------------------------
        self.btn_diag = Button("注入诊断", size="sm")
        self.btn_diag_clear = Button("清除诊断", size="sm")
        self.btn_bp = Button("切换断点(当前行)", size="sm")
        self.btn_find = Button("查找 (Ctrl+F)", size="sm")
        self.btn_replace = Button("替换 (Ctrl+H)", size="sm")
        self.btn_goto = Button("跳到第 42 行", size="sm")
        self.btn_completion = Button("补全演示: 开", size="sm")
        self.btn_hover = Button("悬停演示: 开", size="sm")
        self.btn_fold = Button("折叠全部", size="sm")
        self.btn_unfold = Button("展开全部", size="sm")
        # 自定义快捷键演示：trigger_completion 改绑 Ctrl+J（再点还原）
        self.btn_remap = Button("补全键→Ctrl+J", size="sm")
        self.btn_remap.setToolTip(
            "set_shortcut('trigger_completion', 'Ctrl+J') 示例；再点还原 Ctrl+Space")
        self.btn_remap.clicked.connect(self._toggle_completion_remap)

        self.btn_diag.clicked.connect(self.inject_diagnostics)
        self.btn_diag_clear.clicked.connect(self.clear_diagnostics)
        self.btn_bp.clicked.connect(self._toggle_bp_at_cursor)
        self.btn_find.clicked.connect(lambda: self.editor.open_find_bar(False))
        self.btn_replace.clicked.connect(lambda: self.editor.open_find_bar(True))
        self.btn_goto.clicked.connect(lambda: self.editor.goto_line(42))
        self.btn_completion.clicked.connect(self._toggle_completion)
        self.btn_hover.clicked.connect(self._toggle_hover)
        self.btn_fold.clicked.connect(self.editor.fold_all)
        self.btn_unfold.clicked.connect(self.editor.unfold_all)

        actions1 = row(self.btn_diag, self.btn_diag_clear, self.btn_bp,
                       self.btn_find, self.btn_replace, self.btn_goto,
                       spacing=6)
        actions2 = row(self.btn_completion, self.btn_hover,
                       self.btn_fold, self.btn_unfold, self.btn_remap,
                       spacing=6)

        # -- 状态栏（信号实时反馈主程序示例） --------------------------------
        self.status_pos = QLabel()
        self.status_sel = QLabel()
        self.status_lang = QLabel()
        self.status_indent = QLabel()
        self.status_enc = QLabel("UTF-8")
        self.status_diag = QLabel()
        for lab in (self.status_pos, self.status_sel, self.status_lang,
                    self.status_indent, self.status_enc, self.status_diag):
            lab.setFont(self._mono(12))
            set_property(lab, "role", "secondary")
        status_bar = QWidget()
        status_lay = QHBoxLayout(status_bar)
        status_lay.setContentsMargins(4, 2, 4, 2)
        status_lay.setSpacing(14)
        for lab in (self.status_pos, self.status_sel, self.status_diag):
            status_lay.addWidget(lab)
        status_lay.addStretch(1)
        for lab in (self.status_enc, self.status_indent, self.status_lang):
            status_lay.addWidget(lab)

        # provider 默认注册（演示开箱即用）
        self._completion_on = True
        self._hover_on = True
        self.editor.set_completion_provider(self._completion_provider)
        self.editor.set_hover_provider(self._hover_provider)

        # 信号驱动状态栏
        self.editor.cursor_position_changed.connect(self._on_cursor)
        self.editor.selection_changed.connect(self._on_selection)
        self.editor.language_changed.connect(self._on_language)
        self.editor.breakpoint_toggled.connect(self._on_breakpoint)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)
        lay.addWidget(toolbar)
        lay.addWidget(self.editor, 1)
        lay.addWidget(actions1)
        lay.addWidget(actions2)
        lay.addWidget(hint_label(
            "提示：按 Ctrl+Space 触发补全（默认不自动弹出；可开工具条"
            "「自动补全」开关体验输入即弹，弹窗不抢焦点）；点"
            "「补全键→Ctrl+J」演示快捷键自定义；鼠标悬停在 "
            "calculate_total / render_report / OrderItem 等函数名上 "
            "约 300ms 弹出签名气泡；点击行号槽左侧切换断点。"))
        lay.addWidget(status_bar)

        self._on_cursor(*self.editor.cursor_position())
        self._on_language("python")
        self._update_diag_status()

    # ------------------------------------------------------------------
    @staticmethod
    def _mono(px: int) -> QFont:
        f = QFont()
        f.setFamily(MONO_FAMILY)
        f.setPixelSize(px)
        return f

    # ------------------------------------------------------------------
    # 工具条回调
    # ------------------------------------------------------------------
    def _on_lang_changed(self, label: str) -> None:
        for name, (disp, sample) in LANG_SAMPLES.items():
            if disp == label:
                self.editor.set_language(name)
                self.editor.set_text(sample)
                self.clear_diagnostics()
                break

    def _on_font_changed(self, label: str) -> None:
        for name, family in FONT_OPTIONS:
            if name == label:
                self.editor.set_font_family(family)
                break

    def _bump_font(self, delta: int) -> None:
        self._font_size = max(8, min(32, self._font_size + delta))
        self.editor.set_font_size(self._font_size)
        self.font_size_label.setText(f"{self._font_size}px")

    # ------------------------------------------------------------------
    # 演示动作
    # ------------------------------------------------------------------
    def inject_diagnostics(self) -> None:
        """注入 error / warning / info 各若干条（对应当前示例文本）。"""
        self.editor.set_diagnostics([
            {"line": 47, "column": 5, "length": 14, "severity": "error",
             "message": "示例错误：discount 未做边界检查（演示）"},
            {"line": 68, "column": 9, "length": 8, "severity": "warning",
             "message": "示例警告：get() 缺省值可能为 None（演示）"},
            {"line": 20, "column": 1, "length": 10, "severity": "info",
             "message": "示例提示：TAX_RATE 建议放入配置（演示）"},
        ])
        self._update_diag_status()

    def clear_diagnostics(self) -> None:
        self.editor.set_diagnostics([])
        self._update_diag_status()

    def _toggle_bp_at_cursor(self) -> None:
        line, _col = self.editor.cursor_position()
        self.editor.toggle_breakpoint(line)

    def _toggle_completion(self) -> None:
        self._completion_on = not self._completion_on
        self.editor.set_completion_provider(
            self._completion_provider if self._completion_on else None)
        self.btn_completion.setText(
            "补全演示: 开" if self._completion_on else "补全演示: 关")

    def _toggle_hover(self) -> None:
        self._hover_on = not self._hover_on
        self.editor.set_hover_provider(
            self._hover_provider if self._hover_on else None)
        self.btn_hover.setText(
            "悬停演示: 开" if self._hover_on else "悬停演示: 关")

    def _toggle_completion_remap(self) -> None:
        """自定义快捷键示例：trigger_completion 在 Ctrl+J / Ctrl+Space 间切换。"""
        current = self.editor.shortcut("trigger_completion")
        if current == "Ctrl+J":
            self.editor.set_shortcut("trigger_completion", "Ctrl+Space")
            self.btn_remap.setText("补全键→Ctrl+J")
        else:
            self.editor.set_shortcut("trigger_completion", "Ctrl+J")
            self.btn_remap.setText("补全键→Ctrl+Space(还原)")

    # ------------------------------------------------------------------
    # provider 实现（演示）
    # ------------------------------------------------------------------
    def _completion_provider(self, prefix: str, line: int, col: int) -> list:
        """补全 provider：按前缀过滤 Python 关键字 + 代码片段。"""
        items = _completion_items()
        if prefix:
            matched = [it for it in items
                       if it["label"].startswith(prefix.lower())]
            return matched
        return items[:12]  # 空前缀时给最常用的前 12 项，避免超长列表

    def _hover_provider(self, line: int, col: int):
        """悬停 provider：函数名 / 类名悬停显示签名富文本。"""
        lines = self.editor.text().split("\n")
        if not 1 <= line <= len(lines):
            return None
        src = lines[line - 1]
        for m in _WORD_RE.finditer(src):
            if m.start() < col <= m.end():
                return _HOVER_DOCS.get(m.group(0))
        return None

    # ------------------------------------------------------------------
    # 状态栏刷新（信号实时反馈）
    # ------------------------------------------------------------------
    def _on_cursor(self, line: int, col: int) -> None:
        self.status_pos.setText(f"行 {line}, 列 {col}")

    def _on_selection(self, text: str) -> None:
        n = len(text.replace(" ", "\n"))
        self.status_sel.setText(f"已选 {n} 字符" if n else "未选择")

    def _on_language(self, name: str) -> None:
        disp = LANG_SAMPLES.get(name, (name, ""))[0]
        self.status_lang.setText(disp)
        self.status_indent.setText(f"空格: {self.editor.tab_size()}")

    def _on_breakpoint(self, line: int, on: bool) -> None:
        self.status_diag.setText(
            f"断点 {'+' if on else '-'} 第 {line} 行")

    def _update_diag_status(self) -> None:
        counts = {"error": 0, "warning": 0, "info": 0}
        for d in self.editor.diagnostics():
            sev = d.get("severity", "info")
            counts[sev] = counts.get(sev, 0) + 1
        total = sum(counts.values())
        if total == 0:
            self.status_diag.setText("无诊断")
            self.status_diag.setStyleSheet("")
        else:
            self.status_diag.setText(
                f"诊断: {counts['error']} 错误 / "
                f"{counts['warning']} 警告 / {counts['info']} 提示")
            color_key = ("color.danger" if counts["error"]
                         else "color.warning" if counts["warning"]
                         else "color.primary")
            self.status_diag.setStyleSheet(f"color: {T(color_key)};")


# ---------------------------------------------------------------------------
# 子页 B：Diff 对比演示
# ---------------------------------------------------------------------------

DIFF_OLD = '''"""库存服务 v1"""


def check_stock(sku, warehouse):
    qty = query_db(sku, warehouse)
    if qty > 0:
        return True
    return False


def reserve(sku, warehouse, count):
    if check_stock(sku, warehouse):
        update_db(sku, warehouse, -count)
        return "ok"
    return "out_of_stock"


def main():
    print(reserve("KB-87", "华东仓", 2))
'''

DIFF_NEW = '''"""库存服务 v2：增加日志与预占返回结构"""

import logging

log = logging.getLogger("stock")


def check_stock(sku, warehouse):
    qty = query_db(sku, warehouse)
    log.info("查询库存 %s@%s = %s", sku, warehouse, qty)
    return qty > 0


def reserve(sku, warehouse, count):
    if not check_stock(sku, warehouse):
        log.warning("库存不足: %s", sku)
        return {"status": "out_of_stock", "sku": sku}
    update_db(sku, warehouse, -count)
    log.info("预占成功: %s x%d", sku, count)
    return {"status": "ok", "reserved": count}


def main():
    result = reserve("KB-87", "华东仓", 2)
    print(result["status"])
'''


class DiffDemoPage(QWidget):
    """Diff 对比演示子页：可编辑双文本框 + DiffEditor + 统计。"""

    def __init__(self, parent=None):
        super().__init__(parent)

        self.old_edit = TextArea(placeholder="原始代码", min_rows=8)
        self.new_edit = TextArea(placeholder="修改后代码", min_rows=8)
        for edit, text in ((self.old_edit, DIFF_OLD),
                           (self.new_edit, DIFF_NEW)):
            edit.setPlainText(text)
            edit.setFont(self._mono(12))
            edit.setMinimumHeight(170)

        self.btn_update = Button("更新对比", variant="primary", size="sm")
        self.btn_reset = Button("还原示例", size="sm")
        self.btn_update.clicked.connect(self.update_diff)
        self.btn_reset.clicked.connect(self._reset_samples)

        edits_row = QWidget()
        edits_lay = QHBoxLayout(edits_row)
        edits_lay.setContentsMargins(0, 0, 0, 0)
        edits_lay.setSpacing(10)
        edits_lay.addWidget(self._labeled("原始（旧）", self.old_edit), 1)
        edits_lay.addWidget(self._labeled("修改后（新）", self.new_edit), 1)

        self.stats_label = QLabel()
        set_property(self.stats_label, "role", "secondary")
        self.stats_label.setFont(self._mono(12))

        self.diff = DiffEditor()
        self.diff.setMinimumHeight(420)
        self.diff.hunk_changed.connect(self._on_hunk)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)
        lay.addWidget(hint_label(
            "修改左右文本框内容后点「更新对比」实时重算差异。"
            "模式切换在下方工具条右侧（并排 / 内联 / 自动）；"
            "拖窄窗口或切到「自动」模式可观察 并排↔内联 的自动切换"
            "（宽度断点 900px）。"))
        lay.addWidget(edits_row)
        lay.addWidget(row(self.btn_update, self.btn_reset,
                          self.stats_label, spacing=10))
        lay.addWidget(self.diff, 1)

        self.update_diff()

    # ------------------------------------------------------------------
    @staticmethod
    def _mono(px: int) -> QFont:
        f = QFont()
        f.setFamily(MONO_FAMILY)
        f.setPixelSize(px)
        return f

    @staticmethod
    def _labeled(title: str, widget: QWidget) -> QWidget:
        host = QWidget()
        v = QVBoxLayout(host)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(4)
        lab = QLabel(title)
        set_property(lab, "role", "secondary")
        v.addWidget(lab)
        v.addWidget(widget)
        return host

    # ------------------------------------------------------------------
    def update_diff(self) -> None:
        """读取左右文本框，实时重算差异。"""
        self.diff.set_documents(
            self.old_edit.toPlainText(),
            self.new_edit.toPlainText(),
            "python", old_title="库存服务 v1", new_title="库存服务 v2")
        self._refresh_stats()

    def _reset_samples(self) -> None:
        self.old_edit.setPlainText(DIFF_OLD)
        self.new_edit.setPlainText(DIFF_NEW)
        self.update_diff()

    def _on_hunk(self, index: int, total: int) -> None:
        self._refresh_stats(current=index)

    def _refresh_stats(self, current: int = None) -> None:
        n = self.diff.hunk_count()
        if current is None:
            current = self.diff.current_hunk()
        pos = f"，当前 {current + 1}/{n}" if 0 <= current < n else ""
        self.stats_label.setText(f"共 {n} 处差异块{pos}")


# ---------------------------------------------------------------------------
# 页面组装
# ---------------------------------------------------------------------------

def create_page():
    """构建「代码编辑器」演示页（CE_SPEC §5）。"""
    editor_demo = EditorDemoPage()
    diff_demo = DiffDemoPage()

    tabs = Tabs(variant="line")
    tabs.addTab(editor_demo, "编辑器演示")
    tabs.addTab(diff_demo, "Diff 对比")
    tabs.setMinimumHeight(720)

    sec = Section("CodeEditor / DiffEditor")
    sec.layout().addWidget(tabs)

    page = make_page(
        "代码编辑器",
        "对齐 VS Code 编辑区体验的纯 PySide6 代码编辑器：语法高亮（9 种内置语言 + "
        "注册表扩展）、小地图、查找替换、诊断、断点、折叠、补全 / 悬停 provider、"
        "Ctrl+D 多选批量编辑；右侧 Diff 子页演示行级对比（并排 / 内联 / 自动断点）。",
        [sec],
    )
    # 供测试与集成的句柄
    page.tabs = tabs
    page.editor_demo = editor_demo
    page.diff_demo = diff_demo
    page.editor = editor_demo.editor
    page.diff = diff_demo.diff
    return page
