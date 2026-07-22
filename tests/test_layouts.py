# -*- coding: utf-8 -*-
"""布局预设自测：12 个布局离屏构建 + 双尺寸双主题截图（SPEC §6/§9）。

直接运行（无 pytest 依赖）::

    QT_QPA_PLATFORM=offscreen python tests/test_layouts.py

流程：
- 逐个实例化 12 个布局预设（800x600 与 1280x800 两种尺寸）；
- 同一实例上切换亮 / 暗主题，各 grab() 截图到
  ``tests/shots/layout_<name>_<宽>x<高>_<主题>.png``（共 48 张）；
- 追加 480x700 / 390x700 窄断点 smoke（不截图），验证响应式路径无异常；
- 校验截图非空且文件足够大，任何异常记为失败，退出码 1。
"""

import os
import sys
import traceback
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

SHOTS = ROOT / "tests" / "shots"
SIZES = ((800, 600), (1280, 800))
THEMES = ("light", "dark")

_FAILURES = []
_shots = 0


def _check(name, fn):
    """登记一项检查，异常即记为失败。"""
    try:
        fn()
        print(f"  [通过] {name}")
    except Exception:
        _FAILURES.append(name)
        print(f"  [失败] {name}")
        traceback.print_exc()


def main() -> int:
    from PySide6.QtWidgets import QApplication

    from InstructionX_UIKit.theme import ThemeManager
    # 布局为 API 驱动、不含假数据；测试用 Demo 的示例内容构建器传入数据
    from demo.pages.layouts import (
        _build_card_grid,
        _build_centered_container,
        _build_dashboard_grid,
        _build_hero_section,
        _build_holy_grail,
        _build_master_detail,
        _build_media_left_right,
        _build_sidebar_layout,
        _build_single_column,
        _build_split_panel,
        _build_top_nav_bar,
        _build_waterfall,
    )

    layouts = [
        ("top_nav_bar", _build_top_nav_bar),
        ("holy_grail", _build_holy_grail),
        ("card_grid", _build_card_grid),
        ("single_column", _build_single_column),
        ("sidebar_layout", _build_sidebar_layout),
        ("master_detail", _build_master_detail),
        ("split_panel", _build_split_panel),
        ("dashboard_grid", _build_dashboard_grid),
        ("hero_section", _build_hero_section),
        ("centered_container", _build_centered_container),
        ("waterfall", _build_waterfall),
        ("media_left_right", _build_media_left_right),
    ]

    app = QApplication.instance() or QApplication(sys.argv)
    tm = ThemeManager.instance()
    tm.set_mode("light")
    tm.apply(app)
    SHOTS.mkdir(parents=True, exist_ok=True)

    print("布局预设自测开始（offscreen）")
    print("-" * 60)

    for name, factory in layouts:
        # -- 双尺寸 × 双主题截图（同一实例切换主题，验证主题感知）---------
        for width, height in SIZES:
            def run(size=(width, height), make=factory, label=name):
                global _shots
                w, h = size
                widget = make()
                try:
                    widget.resize(w, h)
                    widget.show()
                    for mode in THEMES:
                        tm.set_mode(mode)
                        tm.apply(app)
                        app.processEvents()
                        pm = widget.grab()
                        if pm.isNull() or pm.width() < 50:
                            raise AssertionError(f"{mode} 主题 grab() 返回空图像")
                        path = SHOTS / f"layout_{label}_{w}x{h}_{mode}.png"
                        if not pm.save(str(path)):
                            raise AssertionError(f"截图保存失败: {path}")
                        if path.stat().st_size < 2048:
                            raise AssertionError(f"截图文件过小: {path}")
                        _shots += 1
                finally:
                    widget.close()
                    widget.deleteLater()

            _check(f"{name} {width}x{height} 双主题截图", run)

        # -- 窄断点 smoke：xs 折叠路径不截图，仅验证无异常 ----------------
        def smoke(make=factory, label=name):
            widget = make()
            try:
                widget.resize(480, 700)
                widget.show()
                app.processEvents()
                widget.resize(390, 700)
                app.processEvents()
                widget.resize(1500, 900)
                app.processEvents()
            finally:
                widget.close()
                widget.deleteLater()

        _check(f"{name} 窄断点 smoke（480/390/1500 缩放）", smoke)

    # -- 空内容 smoke：不传 items 也能构造，显示优雅空占位 ----------------
    def empty_state():
        from InstructionX_UIKit import layouts as kit_layouts

        factories = [
            kit_layouts.create_top_nav_bar,
            kit_layouts.create_holy_grail,
            kit_layouts.create_card_grid,
            kit_layouts.create_single_column,
            kit_layouts.create_sidebar_layout,
            kit_layouts.create_master_detail,
            kit_layouts.create_split_panel,
            kit_layouts.create_dashboard_grid,
            kit_layouts.create_hero_section,
            kit_layouts.create_centered_container,
            kit_layouts.create_waterfall,
            kit_layouts.create_media_left_right,
        ]
        for make in factories:
            widget = make()
            try:
                widget.resize(800, 600)
                widget.show()
                app.processEvents()
                widget.resize(390, 700)
                app.processEvents()
                pm = widget.grab()
                assert not pm.isNull() and pm.width() >= 50, make.__name__
            finally:
                widget.close()
                widget.deleteLater()

    _check("12 个布局空内容构造 + 空占位截图", empty_state)

    tm.set_mode("light")
    tm.apply(app)
    app.processEvents()

    print("-" * 60)
    print(f"截图输出目录: {SHOTS}（共 {_shots} 张）")
    if _FAILURES:
        print(f"共 {len(_FAILURES)} 项失败: {_FAILURES}")
        return 1
    print("全部检查通过，0 错误")
    return 0


if __name__ == "__main__":
    sys.exit(main())
