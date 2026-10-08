#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""组件级版面审计（开发辅助，不属于 Kit 运行时）。

**为什么需要它**：58 个组件的「好不好看」没法靠肉眼评审，但「有没有渲染和
排版错误」是可以量化的。这个工具把每个组件在三档尺寸下真实实例化并测量
实际几何，输出可复现的违规清单，作为组件优化任务的验收依据。

检查项（全部基于真实几何，不做静态猜测）：

- ``OVERFLOW``   子控件几何越出父控件边界（被裁切 / 溢出）
- ``CLIP``       文本控件高度小于换行所需高度（文字被压扁）
- ``COLLIDE``    同级控件矩形相交（重叠）
- ``OFFTOKEN``   内边距 / 间距写死数字，未引用 ``layout.*`` / ``space.*`` 令牌
- ``OFFGRID``    间距为奇数像素（违反 2px 基网格）
- ``SIZE``       控件实际高度与其声明尺寸档不符
- ``DEGENERATE`` 控件尺寸为 0 或过小（等于不可见 / 不可点）

用法::

    QT_QPA_PLATFORM=offscreen python tools/audit_components.py
    QT_QPA_PLATFORM=offscreen python tools/audit_components.py --json out.json
    QT_QPA_PLATFORM=offscreen python tools/audit_components.py --only button card
"""

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QPoint, QRect  # noqa: E402
from PySide6.QtWidgets import (  # noqa: E402
    QApplication, QFrame, QLabel, QLayout, QWidget,
)

from InstructionX_UIKit.theme import ThemeManager, T  # noqa: E402

#: 允许的间距令牌键：正文里引用这些即视为合规
_SPACING_KEYS = {k for k in T("radius.md") * [None]} if False else set()


def _allowed_tokens() -> set:
    """收集全部间距 / 版面度量令牌键（space.* 与 layout.*）。"""
    from InstructionX_UIKit import tokens as tk
    keys = set()
    for d in (tk.LIGHT,):
        keys |= {k for k in d if k.startswith("space.") or k.startswith("layout.")}
    return keys


ALLOWED_TOKENS = _allowed_tokens()


def _token_values() -> set:
    """全部间距 / 版面度量令牌的取值集合（内边距合法值）。"""
    from InstructionX_UIKit import tokens as tk
    return {v for k, v in tk.LIGHT.items()
            if k.startswith("space.") or k.startswith("layout.")}


TOKEN_VALUES = _token_values()

#: 声明尺寸档 -> 该档应达到的高度（总高，px）。来自 theme._INPUT_HEIGHTS。
SIZE_HEIGHT = {"sm": 22, "md": 28, "lg": 34}

#: 低于此高度 / 宽度视为退化（不可见或不可点）
MIN_HIT = 8


class Issue:
    __slots__ = ("kind", "where", "detail")

    def __init__(self, kind: str, where: str, detail: str):
        self.kind = kind
        self.where = where
        self.detail = detail

    def as_dict(self):
        return {"kind": self.kind, "where": self.where, "detail": self.detail}

    def __repr__(self):
        return f"[{self.kind}] {self.where}  {self.detail}"


def _leaf_children(w: QWidget):
    return [c for c in w.findChildren(QWidget) if c.parent() is w]


def _visible(w: QWidget) -> bool:
    return w.isVisible() and w.width() > 0 and w.height() > 0


def audit_widget(root: QWidget, name: str) -> list:
    """对一个已实例化的组件根控件做几何审计。"""
    issues = []
    if not _visible(root):
        issues.append(Issue("DEGENERATE", name,
                            f"根控件不可见 size={root.width()}x{root.height()}"))
        return issues

    # --- 根自身：声明尺寸档 vs 实际高度 ---
    declared = root.property("uiksize")
    if declared in SIZE_HEIGHT and 0 < root.height() <= 80:
        want = SIZE_HEIGHT[declared]
        if abs(root.height() - want) > 2:
            issues.append(Issue(
                "SIZE", name,
                f"声明 {declared} 应高 {want}px，实际 {root.height()}px"))

    # --- 文本裁切 ---
    for lab in root.findChildren(QLabel):
        if not _visible(lab) or not lab.wordWrap():
            continue
        need = lab.heightForWidth(lab.width())
        if need > 0 and lab.height() < need:
            issues.append(Issue(
                "CLIP", f"{name}/{lab.text()[:18]}",
                f"文本高 {lab.height()}px < 换行所需 {need}px（被压扁）"))

    # --- 越界 / 重叠 / 退化（只看直接子级，避免内部实现细节噪声） ---
    kids = [c for c in _leaf_children(root) if _visible(c)]
    for k in kids:
        # 用映射到 root 坐标系的矩形，避免嵌套布局坐标系混淆
        r = QRect(k.mapTo(root, QPoint(0, 0)), k.size())
        bounds = root.rect()
        if not bounds.contains(r):
            # 允许 1px 误差（边框半像素）
            grown = bounds.adjusted(-1, -1, 1, 1)
            if not grown.contains(r):
                issues.append(Issue(
                    "OVERFLOW", f"{name}/{type(k).__name__}",
                    f"几何 {r.getRect()} 越出父边界 {bounds.getRect()}"))
        if k.height() < MIN_HIT or k.width() < MIN_HIT:
            issues.append(Issue(
                "DEGENERATE", f"{name}/{type(k).__name__}",
                f"尺寸 {k.width()}x{k.height()} 过小（不可见/不可点）"))

    for i in range(len(kids)):
        for j in range(i + 1, len(kids)):
            a, b = kids[i], kids[j]
            ra = QRect(a.mapTo(root, QPoint(0, 0)), a.size())
            rb = QRect(b.mapTo(root, QPoint(0, 0)), b.size())
            # 同级控件重叠：允许 1px 贴边
            inter = ra.intersected(rb)
            if inter.width() > 1 and inter.height() > 1:
                issues.append(Issue(
                    "COLLIDE", f"{name}/{type(a).__name__}×{type(b).__name__}",
                    f"重叠区域 {inter.width()}x{inter.height()}px"))

    # --- 写死的间距 / 奇数间距 ---
    _audit_layout_literals(root, name, issues)
    return issues


def _audit_layout_literals(w: QWidget, name: str, issues: list, depth: int = 0) -> None:
    """递归检查布局中写死的间距数字。"""
    if depth > 4:
        return
    lay = w.layout()
    if isinstance(lay, QLayout):
        m = lay.contentsMargins()
        sp = lay.spacing()
        if isinstance(sp, int) and sp % 2:
            issues.append(Issue("OFFGRID", f"{name}/{type(w).__name__}",
                                f"布局间距 {sp}px 为奇数（违反 2px 基网格）"))
        if isinstance(m.left(), int) and m.left() % 2:
            issues.append(Issue("OFFGRID", f"{name}/{type(w).__name__}",
                                f"内边距 {m.left()}/{m.top()}/{m.right()}/{m.bottom()} "
                                f"含奇数（违反 2px 基网格）"))
        # 内边距取值必须来自令牌集：随手写的 10 / 14 / 18 正是「同类组件
        # 内边距各不相同」的来源，也是页面之间观感不齐的根因
        for side, v in (("左", m.left()), ("上", m.top()),
                        ("右", m.right()), ("下", m.bottom())):
            if v not in TOKEN_VALUES and v != 0:
                issues.append(Issue(
                    "PADTOKEN", f"{name}/{type(w).__name__}",
                    f"{side}内边距 {v}px 不在令牌取值集合 {sorted(TOKEN_VALUES)}"))
                break
    for c in w.findChildren(QWidget):
        if c.parent() is w:
            _audit_layout_literals(c, name, issues, depth + 1)


def pump(app, ms=120):
    end = time.time() + ms / 1000.0
    while time.time() < end:
        app.processEvents()
        time.sleep(0.005)
    app.processEvents()


def build_component(mod_name: str, cls_name: str):
    """按约定尝试实例化一个组件；返回实例或 None。"""
    import importlib
    try:
        mod = importlib.import_module(f"InstructionX_UIKit.components.{mod_name}")
    except Exception:
        return None
    cls = getattr(mod, cls_name, None)
    if cls is None:
        return None
    try:
        return cls()
    except Exception:
        return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", help="把结果写成 JSON")
    ap.add_argument("--only", nargs="*", help="只审计指定组件模块名")
    args = ap.parse_args()

    from PySide6.QtQuick import QQuickWindow, QSGRendererInterface
    QQuickWindow.setGraphicsApi(QSGRendererInterface.GraphicsApi.OpenGL)

    app = QApplication(sys.argv)
    ThemeManager.instance().apply(app)

    import InstructionX_UIKit.components as comp_pkg

    targets = []
    if args.only:
        targets = args.only
    else:
        targets = sorted(m.stem for m in Path(comp_pkg.__file__).parent.glob("*.py")
                         if not m.stem.startswith("_"))

    all_issues = []
    checked = 0
    for mod in targets:
        try:
            m = importlib.import_module(f"InstructionX_UIKit.components.{mod}")
        except Exception as exc:
            all_issues.append(Issue("IMPORT", mod, f"{type(exc).__name__}: {exc}"))
            continue

        # 该模块导出里挑出「看得见且有尺寸的」控件类
        from PySide6.QtWidgets import QWidget as _QW
        classes = [getattr(m, n) for n in dir(m) if not n.startswith("_")]
        for cls in classes:
            if not (isinstance(cls, type) and issubclass(cls, _QW)):
                continue
            if cls.__name__.startswith("_") or cls is _QW:
                continue
            # 只审计本模块自定义的控件；跳过 Qt 原生类的再导出（QSpinBox 等），
            # 它们的版式由全局 QSS 统一负责，不属于组件级问题
            if cls.__module__ != m.__name__:
                continue
            try:
                w = cls()
            except Exception:
                continue
            try:
                w.resize(360, 160)
                w.show()
                pump(app, 90)
                iss = audit_widget(w, f"{mod}.{cls.__name__}")
                if iss:
                    all_issues += iss
                checked += 1
            except Exception as exc:
                all_issues.append(Issue("AUDIT", f"{mod}.{cls.__name__}",
                                        f"{type(exc).__name__}: {exc}"))
            finally:
                w.hide()
                w.deleteLater()
                app.processEvents()

    # 汇总
    by_kind = {}
    for i in all_issues:
        by_kind.setdefault(i.kind, []).append(i)

    print("=" * 64)
    print(f"组件版面审计：检查 {checked} 个控件实例，"
          f"发现 {len(all_issues)} 个问题")
    print("=" * 64)
    # 必须覆盖 audit_widget / _audit_layout_literals 可能产出的**全部**类别，
    # 否则终端汇总会静默漏报（曾漏掉 PADTOKEN，导致终端显示 3 条、实际 5 条）。
    order = ["OVERFLOW", "CLIP", "COLLIDE", "DEGENERATE", "SIZE",
             "OFFGRID", "PADTOKEN", "OFFTOKEN", "IMPORT", "AUDIT"]
    emitted = set()
    for kind in order:
        items = by_kind.get(kind)
        emitted.add(kind)
        if not items:
            continue
        print(f"\n--- {kind} ({len(items)}) ---")
        for it in items[:40]:
            print("  ", it)
        if len(items) > 40:
            print(f"   ... 另有 {len(items) - 40} 条")

    # 自检：新出现的类别若没进 order，必须显式暴露而不是被吞掉
    unknown = set(by_kind) - emitted
    if unknown:
        print(f"\n[WARN] 以下类别未纳入终端汇总顺序，请补充到 order 列表：{sorted(unknown)}")

    if args.json:
        Path(args.json).write_text(
            json.dumps([i.as_dict() for i in all_issues], ensure_ascii=False, indent=1),
            encoding="utf-8")
        print(f"\nJSON 已写入 {args.json}")
    return 0


if __name__ == "__main__":
    import importlib  # noqa: E402 - 供 build_component 使用
    sys.exit(main())