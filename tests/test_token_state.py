# -*- coding: utf-8 -*-
"""F5 自测：设计令牌状态机 TokenState（tokens.py / theme.py 集成）。

直接运行（无 pytest 依赖）::

    QT_QPA_PLATFORM=offscreen python tests/test_token_state.py

覆盖：
- TokenState 单例与 ThemeManager 联动；
- value / color / size / font / shadow 各类型正确；
- 分组导出（colors/typography/spacing/radii/shadows/durations/easings/
  breakpoints）键完整性（对照 LIGHT 字典）；
- set_token 生效并发射 token_changed，且不改 LIGHT / DARK 预设常量；
- reset_token / reset_all 还原；
- 模式切换（set_mode / toggle）刷新并发射 mode_changed；
- set_width 断点跳变发射 breakpoint_changed；
- T() 兼容（委托状态机、含覆盖、未知键 KeyError）；
- Switch / Rating / SegmentedControl 换色冒烟（grab 像素验证）。
"""

import os
import sys
import traceback
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

_FAILURES = []


def check(name):
    """装饰器：登记一项检查，异常即记为失败。"""

    def deco(fn):
        try:
            fn()
            print(f"  [通过] {name}")
        except Exception:
            _FAILURES.append(name)
            print(f"  [失败] {name}")
            traceback.print_exc()

    return deco


def assert_eq(actual, expected, msg=""):
    if actual != expected:
        raise AssertionError(f"{msg} 期望 {expected!r}，实际 {actual!r}")


def _grab_color_names(widget):
    """grab 控件并返回画面内出现的全部颜色名集合（#rrggbb）。"""
    from PySide6.QtGui import QColor, QImage
    img = widget.grab().toImage().convertToFormat(QImage.Format_ARGB32)
    names = set()
    for x in range(img.width()):
        for y in range(img.height()):
            names.add(QColor(img.pixel(x, y)).name())
    return names


# ---------------------------------------------------------------------------
# 1. 单例与 ThemeManager 联动
# ---------------------------------------------------------------------------

@check("单例：instance() 全局唯一，初始模式联动 ThemeManager")
def _():
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from InstructionX_UIKit.theme import ThemeManager
    from InstructionX_UIKit.tokens import TokenState

    ts1 = TokenState.instance()
    ts2 = TokenState.instance()
    assert ts1 is ts2, "TokenState.instance() 应返回同一实例"
    assert_eq(ts1.mode, ThemeManager.instance().mode, "初始模式应以 ThemeManager 为源")


# ---------------------------------------------------------------------------
# 2. 读取 API 类型
# ---------------------------------------------------------------------------

@check("value / color / size / font / shadow 各类型正确")
def _():
    from PySide6.QtGui import QColor, QFont
    from InstructionX_UIKit.tokens import LIGHT, TokenState

    ts = TokenState.instance()
    # value
    assert_eq(ts.value("color.primary"), LIGHT["color.primary"])
    assert_eq(ts.value("space.4"), 16)
    assert ts.value("no.such.key") is None, "未知键应返回 default(None)"
    assert_eq(ts.value("no.such.key", 42), 42)
    # color
    c = ts.color("color.primary")
    assert isinstance(c, QColor), "color() 应返回 QColor"
    assert_eq(c.name(), LIGHT["color.primary"].lower())
    # size
    s = ts.size("space.4")
    assert isinstance(s, int) and s == 16, "size(space.4) 应为 int 16"
    assert_eq(ts.size("radius.lg"), 8)
    assert_eq(ts.size("font.md"), 13)
    assert_eq(ts.size("font.line_height.body"), 1.5)  # 行高保持 float
    # font
    f = ts.font()
    assert isinstance(f, QFont), "font() 应返回 QFont"
    assert_eq(f.pixelSize(), LIGHT["font.md"])
    assert_eq(int(f.weight()), LIGHT["font.weight.regular"])
    f2 = ts.font("title.lg", "bold")
    assert_eq(f2.pixelSize(), 20)
    assert_eq(int(f2.weight()), 700)
    # shadow
    sh = ts.shadow("md")
    assert isinstance(sh, dict), "shadow() 应返回 dict"
    assert_eq(sh, LIGHT["shadow.md"])
    sh["blur"] = 999
    assert ts.shadow("md")["blur"] != 999, "shadow() 应返回副本"


# ---------------------------------------------------------------------------
# 3. 分组导出键完整性（对照 LIGHT）
# ---------------------------------------------------------------------------

@check("分组导出：八组键与 LIGHT 字典完全一致")
def _():
    from InstructionX_UIKit.tokens import LIGHT, TokenState

    ts = TokenState.instance()
    groups = {
        "color.": ts.colors(),
        "font.": ts.typography(),
        "space.": ts.spacing(),
        "radius.": ts.radii(),
        "shadow.": ts.shadows(),
        "duration.": ts.durations(),
        "easing.": ts.easings(),
        "breakpoint.": ts.breakpoints(),
    }
    for prefix, group in groups.items():
        expected = {k for k in LIGHT if k.startswith(prefix)}
        assert_eq(set(group), expected, f"{prefix}* 分组键")
        for k in expected:
            assert_eq(group[k], LIGHT[k], f"{prefix}* 分组值 {k}")
    assert expected, "LIGHT 不应为空"
    # 导出为副本：修改不影响状态机
    ts.colors()["color.primary"] = "#000000"
    assert_eq(ts.value("color.primary"), LIGHT["color.primary"], "colors() 应为副本")


# ---------------------------------------------------------------------------
# 4. 运行时覆盖：set_token / reset_token / reset_all
# ---------------------------------------------------------------------------

@check("set_token 生效并发射 token_changed，预设常量不变；reset 还原")
def _():
    from InstructionX_UIKit.tokens import DARK, LIGHT, TokenState

    ts = TokenState.instance()
    assert ts.mode == "light", "前置：应处于亮色模式"
    origin = LIGHT["color.primary"]
    fired = []
    ts.token_changed.connect(fired.append)

    ts.set_token("color.primary", "#FF6600")
    assert_eq(ts.value("color.primary"), "#FF6600", "set_token 应立即生效")
    assert_eq(fired, ["color.primary"], "set_token 应发射 token_changed")
    assert ts.is_overridden("color.primary"), "is_overridden 应为 True"
    assert_eq(LIGHT["color.primary"], origin, "LIGHT 预设常量不得被修改")
    assert_eq(DARK["color.primary"], "#7C98C4", "DARK 预设常量不得被修改")
    assert_eq(ts.colors()["color.primary"], "#FF6600", "分组导出应含会话覆盖")

    ts.reset_token("color.primary")
    assert_eq(ts.value("color.primary"), origin, "reset_token 应还原预设")
    assert_eq(fired, ["color.primary", "color.primary"], "reset_token 应再发射一次")
    assert not ts.is_overridden("color.primary")

    ts.set_token("space.4", 99)
    ts.set_token("radius.md", 1)
    fired.clear()
    ts.reset_all()
    assert_eq(ts.value("space.4"), 16, "reset_all 应还原 space.4")
    assert_eq(ts.value("radius.md"), 6, "reset_all 应还原 radius.md")
    assert_eq(sorted(fired), ["radius.md", "space.4"], "reset_all 应逐键发射")
    assert_eq(ts.overrides(), {}, "reset_all 后覆盖表应为空")


# ---------------------------------------------------------------------------
# 5. 模式切换刷新（set_mode / toggle -> mode_changed）
# ---------------------------------------------------------------------------

@check("模式切换：set_mode/toggle 同步刷新并发射 mode_changed")
def _():
    from InstructionX_UIKit.theme import ThemeManager
    from InstructionX_UIKit.tokens import DARK, LIGHT, TokenState

    ts = TokenState.instance()
    tm = ThemeManager.instance()
    tm.set_mode("light")
    modes = []
    ts.mode_changed.connect(modes.append)

    tm.set_mode("dark")
    assert_eq(ts.mode, "dark", "set_mode(dark) 后状态机应刷新")
    assert_eq(ts.value("color.primary"), DARK["color.primary"], "暗色取值应来自 DARK")
    assert_eq(ts.color("color.bg.base").name(), DARK["color.bg.base"].lower())
    assert_eq(modes, ["dark"], "应发射 mode_changed('dark')")

    tm.toggle()
    assert_eq(ts.mode, "light", "toggle 后应回到亮色")
    assert_eq(ts.value("color.primary"), LIGHT["color.primary"])
    assert_eq(modes, ["dark", "light"], "toggle 应再发射 mode_changed('light')")

    tm.set_mode("light")  # 同模式不重复发射
    assert_eq(modes, ["dark", "light"], "同模式 set_mode 不应重复发射")
    ts.mode_changed.disconnect(modes.append)


# ---------------------------------------------------------------------------
# 6. 断点状态机
# ---------------------------------------------------------------------------

@check("set_width 断点跳变发射 breakpoint_changed，同档不重复")
def _():
    from InstructionX_UIKit.tokens import TokenState

    ts = TokenState.instance()
    bps = []
    ts.breakpoint_changed.connect(bps.append)

    ts.set_width(500)
    assert_eq(ts.current_breakpoint, "xs")
    ts.set_width(800)
    assert_eq(ts.current_breakpoint, "md", "800px 应为 md 档")
    assert_eq(bps[-1], "md", "跨档应发射 breakpoint_changed")
    n = len(bps)
    ts.set_width(900)  # 同档
    assert_eq(len(bps), n, "同档宽度变化不应重复发射")
    assert_eq(ts.width, 900)
    ts.set_width(1500)
    assert_eq(ts.current_breakpoint, "xl")
    assert_eq(bps[-1], "xl")
    ts.set_width(100)
    assert_eq(ts.current_breakpoint, "xs")
    assert_eq(bps[-1], "xs")
    ts.breakpoint_changed.disconnect(bps.append)


# ---------------------------------------------------------------------------
# 7. T() 兼容（委托状态机）
# ---------------------------------------------------------------------------

@check("T() 委托 TokenState：取值一致、含覆盖、未知键 KeyError")
def _():
    from InstructionX_UIKit.theme import T
    from InstructionX_UIKit.tokens import LIGHT, TokenState

    ts = TokenState.instance()
    assert_eq(T("color.primary"), LIGHT["color.primary"], "T() 基础取值")
    assert_eq(T("space.4"), 16)
    assert_eq(T("shadow.sm"), LIGHT["shadow.sm"])

    ts.set_token("color.primary", "#00AAFF")
    assert_eq(T("color.primary"), "#00AAFF", "T() 应感知 set_token 覆盖")
    ts.reset_token("color.primary")
    assert_eq(T("color.primary"), LIGHT["color.primary"], "reset 后 T() 还原")

    try:
        T("no.such.key")
    except KeyError:
        pass
    else:
        raise AssertionError("T() 未知键应抛 KeyError（保持旧行为）")


# ---------------------------------------------------------------------------
# 8. 自绘组件换色冒烟（Switch / Rating / SegmentedControl）
# ---------------------------------------------------------------------------

@check("冒烟：Switch set_token(color.primary) 后重绘使用新值")
def _():
    from InstructionX_UIKit.components.switch import Switch
    from InstructionX_UIKit.tokens import LIGHT, TokenState

    ts = TokenState.instance()
    ts.reset_all()
    sw = Switch(checked=True, size="md")
    before = _grab_color_names(sw)
    assert LIGHT["color.primary"].lower() in before, \
        f"选中态轨道应为主色: {sorted(before)}"

    ts.set_token("color.primary", "#12AB34")
    after = _grab_color_names(sw)
    assert "#12ab34" in after, f"set_token 后轨道应为新主色: {sorted(after)}"
    assert LIGHT["color.primary"].lower() not in after, "旧主色不应再出现"
    ts.reset_token("color.primary")
    sw.deleteLater()


@check("冒烟：Rating set_token(color.warning) 后重绘使用新值")
def _():
    from InstructionX_UIKit.components.rating import Rating
    from InstructionX_UIKit.tokens import LIGHT, TokenState

    ts = TokenState.instance()
    ts.reset_all()
    r = Rating(count=5, value=5.0, read_only=True)
    r.resize(r.sizeHint())
    before = _grab_color_names(r)
    assert LIGHT["color.warning"].lower() in before, \
        f"实星应为 warning 色: {sorted(before)}"

    ts.set_token("color.warning", "#ABCDEF")
    after = _grab_color_names(r)
    assert "#abcdef" in after, f"set_token 后实星应为新色: {sorted(after)}"
    ts.reset_token("color.warning")
    r.deleteLater()


@check("冒烟：SegmentedControl set_token(color.bg.muted) 后重绘使用新值")
def _():
    from InstructionX_UIKit.components.segmented import SegmentedControl
    from InstructionX_UIKit.tokens import LIGHT, TokenState

    ts = TokenState.instance()
    ts.reset_all()
    seg = SegmentedControl(["日", "周", "月"], current=1)
    seg.resize(240, 32)
    before = _grab_color_names(seg)
    assert LIGHT["color.bg.muted"].lower() in before, \
        f"底槽应为 bg.muted: {sorted(before)}"

    ts.set_token("color.bg.muted", "#654321")
    after = _grab_color_names(seg)
    assert "#654321" in after, f"set_token 后底槽应为新色: {sorted(after)}"
    ts.reset_token("color.bg.muted")
    seg.deleteLater()


def main() -> int:
    print("TokenState 令牌状态机自测开始（offscreen）")
    print("-" * 60)
    if _FAILURES:
        print(f"共 {len(_FAILURES)} 项失败: {_FAILURES}")
        return 1
    print("全部检查通过，0 错误")
    return 0


if __name__ == "__main__":
    sys.exit(main())
