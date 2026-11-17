#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""QGroupBox / QSplitter 现状诊断（开发辅助）。

把同一个 QGroupBox 分别放在「画布 / 卡片 / 纯面」三种背景上渲染，
用于验证标题挖空底色是否与所在表面匹配；并在卡片内放一个 QSplitter，
用于观察分隔条在不同容器下的实际观感。

用法::

    QT_QPA_PLATFORM=offscreen python tools/diag_group_splitter.py --out /tmp/diag.png
"""

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import (  # noqa: E402
    QGroupBox, QHBoxLayout, QLabel, QSplitter, QVBoxLayout, QWidget,
)

from InstructionX_UIKit.theme import T, ThemeManager, set_property  # noqa: E402


def group(title: str) -> QGroupBox:
    gb = QGroupBox(title)
    gl = QVBoxLayout(gb)
    gl.setContentsMargins(12, 8, 12, 8)
    gl.setSpacing(6)
    gl.addWidget(QLabel("分组框内的内容，用来观察标题与边框的关系。"))
    return gb


def build() -> QWidget:
    root = QWidget()
    set_property(root, "role", "canvas")
    lay = QVBoxLayout(root)
    pad = T("layout.page.pad")
    lay.setContentsMargins(pad, pad, pad, pad)
    lay.setSpacing(T("layout.gutter"))

    # 1) 画布上的 GroupBox（标题挖空底色 = canvas，应当吻合）
    lay.addWidget(group("画布上的分组框"))

    # 2) 卡片内的 GroupBox（标题挖空底色仍是 canvas，但父背景是 bg.base -> 不匹配）
    card = QWidget()
    set_property(card, "role", "card")
    cl = QVBoxLayout(card)
    cl.setContentsMargins(12, 8, 12, 12)
    cl.setSpacing(T("layout.card.gap"))
    head = QLabel("卡片内的分组框")
    from InstructionX_UIKit.theme import set_font
    set_font(head, "font.title.sm", "semibold")
    cl.addWidget(head)
    cl.addWidget(group("父背景是卡片时的分组框"))
    lay.addWidget(card)

    # 3) 卡片内的 QSplitter：观察分隔条
    card2 = QWidget()
    set_property(card2, "role", "card")
    c2 = QVBoxLayout(card2)
    c2.setContentsMargins(12, 8, 12, 12)
    c2.setSpacing(T("layout.card.gap"))
    set_font(head, "font.title.sm", "semibold")
    c2.addWidget(QLabel("卡片内的分隔条"))
    sp = QSplitter(Qt.Horizontal)
    for name in ("左侧", "右侧"):
        pane = QWidget()
        pl = QVBoxLayout(pane)
        pl.setContentsMargins(12, 12, 12, 12)
        pl.addWidget(QLabel(name))
        sp.addWidget(pane)
    sp.setSizes([300, 400])
    c2.addWidget(sp)
    lay.addWidget(card2)

    # 4) 水平分隔条
    row = QWidget()
    set_property(row, "role", "plain")
    rl = QHBoxLayout(row)
    rl.setContentsMargins(0, 0, 0, 0)
    rl.setSpacing(T("space.2"))
    rl.addWidget(group("水平分隔条左"))
    vsplit = QSplitter(Qt.Vertical)
    vsplit.setOrientation(Qt.Vertical)
    for name in ("上", "下"):
        pane = QWidget()
        pl = QVBoxLayout(pane)
        pl.setContentsMargins(12, 12, 12, 12)
        pl.addWidget(QLabel(name))
        vsplit.addWidget(pane)
    vsplit.setSizes([100, 100])
    rl.addWidget(vsplit)
    lay.addWidget(row)
    return root


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="/tmp/diag.png")
    ap.add_argument("--mode", default="light", choices=["light", "dark"])
    args = ap.parse_args()

    from PySide6.QtWidgets import QApplication

    app = QApplication(sys.argv)
    ThemeManager.instance().apply(app)
    ThemeManager.instance().set_mode(args.mode)

    w = build()
    w.resize(1100, 1000)
    w.show()
    for _ in range(20):
        app.processEvents()
    w.grab().save(args.out)
    print("saved", args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())