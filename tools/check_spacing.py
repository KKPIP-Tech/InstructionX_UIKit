#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""版面度量检查（开发辅助，不属于 Kit 运行时）。

检查两件事，都是「肉眼很难发现、缩放一档就露馅」的那类问题：

1. **奇数像素间距** —— 间距刻度以 2px 为基网格（主节奏 4px，2px 为半档）。
   奇数间距会让相邻元素在中点对不齐，是版面「看着差不多但就是不正」的
   主要来源（如 `13, 10, 13, 13` 这类随手写的魔数）。
2. **写死的版面度量** —— 页面边距、卡片内边距、导航行高等应当引用
   ``layout.*`` 令牌，而不是散落成字面量。字面量会让同类元素在不同页面
   悄悄漂移，对齐关系随改动一点点崩掉。

用法::

    python tools/check_spacing.py            # 全量检查
    python tools/check_spacing.py --quiet    # 只在失败时输出
"""

import argparse
import ast
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKIP_DIRS = {".venv", ".git", "__pycache__", "shots", "docs", "temp"}

#: 允许写死边距的调用
CALL_OK = {
    "setContentsMargins",
    "setSpacing",
}

#: **页面骨架**文件：这些文件决定了全站对齐关系，其边距必须引用 layout.* 令牌。
#: 组件内部边距（徽标内边距、图标按钮留白等）只需满足 2px 基网格，
#: 不必强行套用页面级令牌——否则检查规则会宽到没人愿意维护。
SCAFFOLD = {
    "demo/pages/common.py",
    "demo/main_window.py",
}

_DECL = re.compile(
    r"(?:setContentsMargins|setSpacing|setFixedHeight|setMinimumHeight|setMaximumHeight)\(")


def _odd_px_in_qss(path: Path, text: str):
    """QSS：找出 padding/margin 声明里的奇数像素值。"""
    bad = []
    for lineno, line in enumerate(text.splitlines(), 1):
        for block in re.findall(r"(?:padding|margin)[a-z-]*:[^;}]+", line):
            for v in re.findall(r"(\d+)px", block):
                if int(v) % 2:
                    bad.append((lineno, v, line.strip()[:70]))
    return bad


def _literal_margins(path: Path):
    """Python：找出把数字**直接写死**在 setContentsMargins / setSpacing 的调用。

    只拦纯整数字面量参数。传入 ``T("layout.*")``、由令牌派生的局部变量
    （``pad = T(...)``）、以及按 dense 等开关做的三元表达式都属于合规写法——
    判它们只会制造噪声，让检查器没人愿意用。

    分级：
    - ``scaffold=True``（页面骨架文件）→ 违规，必须改走 layout.* 令牌；
    - 组件内部 → 仅当数值为奇数时算违规（违反 2px 基网格）。
    """
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError as exc:
        return [(0, 0, f"语法错误: {exc}")]
    bad = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        name = fn.attr if isinstance(fn, ast.Attribute) else (
            fn.id if isinstance(fn, ast.Name) else "")
        if name not in CALL_OK:
            continue
        offenders = []
        for a in node.args:
            if isinstance(a, ast.Starred):
                continue
            if isinstance(a, ast.Constant) and isinstance(a.value, (int, float)) \
                    and a.value != 0:
                offenders.append(str(a.value))
        scaffold = path.relative_to(ROOT).as_posix() in SCAFFOLD
        if scaffold:
            if offenders:
                bad.append((node.lineno, 0,
                            f"{name}(...) 内写死数字 {'/'.join(offenders)}"
                            f"  -> 改用 T(\"layout.*\")"))
        else:
            odd = [v for v in offenders if int(v) % 2]
            if odd:
                bad.append((node.lineno, 0,
                            f"{name}(...) 内奇数间距 {'/'.join(odd)}  -> 取 2px 网格值"))
    return bad


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--quiet", action="store_true", help="仅在失败时输出")
    args = ap.parse_args()

    py_files = sorted(
        p for p in ROOT.rglob("*.py")
        if not any(part in SKIP_DIRS for part in p.parts)
    )

    total = 0
    for p in py_files:
        rel = p.relative_to(ROOT)
        text = p.read_text(encoding="utf-8")

        issues = []
        if p.name == "theme.py":
            issues += [(rel, ln, v, frag) for ln, v, frag in _odd_px_in_qss(p, text)]
        issues += [(rel, ln, 0, frag) for ln, _v, frag in _literal_margins(p)]

        for rel, lineno, val, frag in issues:
            total += 1
            loc = f"{rel}:{lineno}"
            if val:
                print(f"[奇数间距] {loc}  {val}px  {frag}")
            else:
                print(f"[硬编码]   {loc}  {frag}")

    if total:
        print(f"\n[FAIL] 共 {total} 处版面度量问题")
        return 1
    if not args.quiet:
        print(f"[PASS] {len(py_files)} 个文件，版面度量全部合规"
              f"（间距遵循 2px 基网格，边距引用 layout.* 令牌）")
    return 0


if __name__ == "__main__":
    sys.exit(main())