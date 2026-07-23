# -*- coding: utf-8 -*-
"""设计令牌（Design Tokens）。

本模块是整套 UI Kit 的唯一数值事实来源，实现 SPEC §2 的全部契约：

- ``LIGHT`` / ``DARK``：亮 / 暗两套语义令牌字典，键如
  ``"color.primary"``、``"space.4"``、``"radius.md"``、``"shadow.sm"``。
- ``FONT_FAMILY`` / ``MONO_FAMILY``：QSS font-family 字符串。
- ``Breakpoint``：窗口宽度断点判定。
- ``DURATION`` / ``EASING``：动效时长（ms）与缓动曲线映射。
- ``TokenState``：令牌状态机（单例），统一读取 / 分组导出 / 运行时覆盖 /
  断点跟踪，并与 ThemeManager 联动。

颜色令牌值为十六进制字符串；数值令牌为 ``int``（行高为 ``float``）；
阴影令牌为 ``dict``：``{"blur": int, "offset": (x, y), "color": (r, g, b, a)}``。
"""

from PySide6.QtCore import QEasingCurve, QObject, Signal
from PySide6.QtGui import QColor, QFont

__all__ = [
    "LIGHT",
    "DARK",
    "FONT_FAMILY",
    "MONO_FAMILY",
    "Breakpoint",
    "DURATION",
    "EASING",
    "TokenState",
]

# ---------------------------------------------------------------------------
# 字体排版（SPEC §2.2）
# ---------------------------------------------------------------------------

#: 正文字族（QSS font-family 字符串）
FONT_FAMILY = (
    '"Segoe UI", "PingFang SC", "Microsoft YaHei", '
    '"Noto Sans CJK SC", "WenQuanYi Micro Hei", sans-serif'
)

#: 等宽字族（QSS font-family 字符串）
MONO_FAMILY = '"Cascadia Code", "JetBrains Mono", "Consolas", monospace'

# ---------------------------------------------------------------------------
# 间距（SPEC §2.3，4pt 基线，单位 px）
# ---------------------------------------------------------------------------

_SPACING = {
    "space.0": 0,
    "space.05": 2,
    "space.1": 4,
    "space.2": 8,
    "space.3": 12,
    "space.4": 16,
    "space.5": 20,
    "space.6": 24,
    "space.8": 32,
    "space.10": 40,
    "space.12": 48,
    "space.16": 64,
}

# ---------------------------------------------------------------------------
# 圆角（SPEC §2.4，单位 px）
# ---------------------------------------------------------------------------

_RADIUS = {
    "radius.sm": 4,
    "radius.md": 6,
    "radius.lg": 8,
    "radius.xl": 12,
    "radius.pill": 999,
}

# ---------------------------------------------------------------------------
# 字阶 / 字重 / 行高（SPEC §2.2）
# ---------------------------------------------------------------------------

_FONT = {
    # 字阶（px），md=13 为正文基准
    "font.xs": 11,
    "font.sm": 12,
    "font.md": 13,
    "font.lg": 14,
    "font.title.sm": 15,
    "font.title.md": 17,
    "font.title.lg": 20,
    "font.display": 24,
    "font.hero": 32,
    # 字重
    "font.weight.regular": 400,
    "font.weight.medium": 500,
    "font.weight.semibold": 600,
    "font.weight.bold": 700,
    # 行高
    "font.line_height.body": 1.5,
    "font.line_height.title": 1.3,
}

# ---------------------------------------------------------------------------
# 断点（SPEC §2.6，窗口宽度 px）
# ---------------------------------------------------------------------------

_BREAKPOINT = {
    # 各档最小宽度（xs 为 0，表示 <640 的兜底档）
    "breakpoint.xs": 0,
    "breakpoint.sm": 640,
    "breakpoint.md": 768,
    "breakpoint.lg": 1024,
    "breakpoint.xl": 1440,
}


class Breakpoint:
    """窗口宽度断点。

    档位划分（SPEC §2.6）：
    ``xs < 640``，``sm 640-767``，``md 768-1023``，``lg 1024-1439``，``xl >= 1440``。
    """

    #: 各档位名称，按宽度从小到大排列
    NAMES = ("xs", "sm", "md", "lg", "xl")
    #: 各档位最小宽度阈值（与 NAMES 一一对应）
    THRESHOLDS = (0, 640, 768, 1024, 1440)

    @staticmethod
    def from_width(w: int) -> str:
        """按窗口宽度返回断点名。

        参数:
            w: 窗口宽度（px）。

        返回:
            ``"xs"`` / ``"sm"`` / ``"md"`` / ``"lg"`` / ``"xl"`` 之一。
        """
        w = int(w)
        if w < 640:
            return "xs"
        if w < 768:
            return "sm"
        if w < 1024:
            return "md"
        if w < 1440:
            return "lg"
        return "xl"


# ---------------------------------------------------------------------------
# 动效（SPEC §2.7）
# ---------------------------------------------------------------------------

#: 时长（ms）
DURATION = {
    "instant": 80,
    "fast": 120,
    "normal": 200,
    "slow": 320,
    "slower": 480,
}

#: 缓动曲线映射
EASING = {
    "standard": QEasingCurve.OutCubic,
    "entrance": QEasingCurve.OutQuint,
    "spring": QEasingCurve.OutBack,
    "emphasis": QEasingCurve.OutQuart,
    "linear": QEasingCurve.Linear,
}

# 同步进令牌字典，便于 T() 统一读取（亮暗一致）
_MOTION = {
    **{f"duration.{k}": v for k, v in DURATION.items()},
    **{f"easing.{k}": v for k, v in EASING.items()},
}

# ---------------------------------------------------------------------------
# 阴影（SPEC §2.5，用于 QGraphicsDropShadowEffect）
# ---------------------------------------------------------------------------

# 亮色：RGB=(16,24,40)，alpha 分别 15% / 25% / 36%
_SHADOW_LIGHT = {
    "shadow.sm": {"blur": 6, "offset": (0, 1), "color": (16, 24, 40, 38)},
    "shadow.md": {"blur": 16, "offset": (0, 4), "color": (16, 24, 40, 64)},
    "shadow.lg": {"blur": 32, "offset": (0, 8), "color": (16, 24, 40, 92)},
}

# 暗色：RGB=(0,0,0)，alpha 分别 40% / 55% / 70%
_SHADOW_DARK = {
    "shadow.sm": {"blur": 6, "offset": (0, 1), "color": (0, 0, 0, 102)},
    "shadow.md": {"blur": 16, "offset": (0, 4), "color": (0, 0, 0, 140)},
    "shadow.lg": {"blur": 32, "offset": (0, 8), "color": (0, 0, 0, 179)},
}

# ---------------------------------------------------------------------------
# 色彩（SPEC §2.1，语义令牌，亮 / 暗两套）
# ---------------------------------------------------------------------------

_COLOR_LIGHT = {
    "color.bg.base": "#FFFFFF",
    "color.bg.subtle": "#F6F7F9",
    "color.bg.muted": "#EFF1F5",
    "color.bg.elevated": "#FFFFFF",
    "color.border": "#E3E6EB",
    "color.border.strong": "#C9CFD8",
    "color.text.primary": "#1C2330",
    "color.text.secondary": "#59636F",
    "color.text.tertiary": "#98A0AC",
    "color.text.disabled": "#C2C8D0",
    "color.primary": "#3F5E8C",
    "color.primary.hover": "#35507A",
    "color.primary.pressed": "#2B4266",
    "color.primary.subtle": "#EBEFF5",
    "color.on.primary": "#FFFFFF",
    "color.success": "#3E7E5F",
    "color.success.hover": "#34684F",
    "color.success.subtle": "#E9F2EC",
    "color.warning": "#C08A3E",
    "color.warning.subtle": "#F7F0E3",
    "color.danger": "#B25050",
    "color.danger.hover": "#9A4444",
    "color.danger.subtle": "#F7EBEB",
    "color.overlay": "rgba(28,35,48,0.45)",
}

_COLOR_DARK = {
    "color.bg.base": "#15181E",
    "color.bg.subtle": "#1B1F27",
    "color.bg.muted": "#232936",
    "color.bg.elevated": "#1F242E",
    "color.border": "#2C333F",
    "color.border.strong": "#3D4654",
    "color.text.primary": "#E7EAF0",
    "color.text.secondary": "#A6AEBB",
    "color.text.tertiary": "#6E7684",
    "color.text.disabled": "#4A515C",
    "color.primary": "#7C98C4",
    "color.primary.hover": "#93AAD1",
    "color.primary.pressed": "#A9BDDD",
    "color.primary.subtle": "#26324A",
    "color.on.primary": "#15181E",
    "color.success": "#6BA98A",
    "color.success.hover": "#55D0A0",
    "color.success.subtle": "#22362D",
    "color.warning": "#D2A668",
    "color.warning.subtle": "#3A3226",
    "color.danger": "#CD7A7A",
    "color.danger.hover": "#F07878",
    "color.danger.subtle": "#3E2A2A",
    "color.overlay": "rgba(0,0,0,0.55)",
}

# ---------------------------------------------------------------------------
# 汇总：亮 / 暗令牌字典（SPEC §2.8）
# ---------------------------------------------------------------------------

#: 亮色主题令牌字典
LIGHT = {
    **_COLOR_LIGHT,
    **_FONT,
    **_SPACING,
    **_RADIUS,
    **_SHADOW_LIGHT,
    **_BREAKPOINT,
    **_MOTION,
}

#: 暗色主题令牌字典
DARK = {
    **_COLOR_DARK,
    **_FONT,
    **_SPACING,
    **_RADIUS,
    **_SHADOW_DARK,
    **_BREAKPOINT,
    **_MOTION,
}


# ---------------------------------------------------------------------------
# 令牌状态机（TokenState）
# ---------------------------------------------------------------------------

def _families(qss_family: str):
    """把 QSS font-family 字符串解析为字族列表（剔除 generic 族）。"""
    generic = {"sans-serif", "serif", "monospace", "cursive", "fantasy"}
    result = []
    for item in qss_family.split(","):
        name = item.strip().strip('"').strip("'")
        if name and name.lower() not in generic:
            result.append(name)
    return result


class TokenState(QObject):
    """设计令牌状态机（单例）。

    令牌读取的统一入口：以 ThemeManager 当前模式（亮 / 暗）为源，
    叠加会话级运行时覆盖，并跟踪窗口断点状态。预设常量 ``LIGHT`` /
    ``DARK`` 永远保持不变；``set_token`` 只影响本会话的状态机视图。

    信号:
        token_changed(str key): 某令牌被 ``set_token`` / ``reset_*`` 改变。
        mode_changed(str): 模式刷新（``"light"`` / ``"dark"``）。
        breakpoint_changed(str): 断点档位跳变（``xs/sm/md/lg/xl``）。

    示例::

        ts = TokenState.instance()
        ts.token_changed.connect(lambda key: print("令牌变更:", key))
        ts.set_token("color.primary", "#FF6600")   # 仅本会话
        ts.reset_all()                             # 还原全部覆盖
    """

    #: 令牌变更信号，参数为令牌键（如 ``"color.primary"``）
    token_changed = Signal(str)
    #: 模式刷新信号，参数为 ``"light"`` / ``"dark"``
    mode_changed = Signal(str)
    #: 断点跳变信号，参数为 ``"xs"`` / ``"sm"`` / ``"md"`` / ``"lg"`` / ``"xl"``
    breakpoint_changed = Signal(str)

    _instance = None

    def __init__(self, parent=None):
        super().__init__(parent)
        self._mode = "light"
        self._overrides = {}          # 会话级覆盖，不污染 LIGHT / DARK
        self._width = 0
        self._breakpoint = "xs"

    # -- 单例 ------------------------------------------------------------
    @classmethod
    def instance(cls) -> "TokenState":
        """返回全局唯一实例（与 ThemeManager 联动，也可独立使用）。"""
        if cls._instance is None:
            cls._instance = cls()
            cls._instance._attach_theme_manager()
        return cls._instance

    def _attach_theme_manager(self) -> None:
        """以 ThemeManager 当前模式为源并订阅其切换（惰性导入避免循环依赖）。"""
        try:
            from .theme import ThemeManager
        except Exception:
            return
        tm = ThemeManager.instance()
        self._mode = tm.mode
        tm.theme_changed.connect(self._sync_mode)

    # -- 模式 ------------------------------------------------------------
    @property
    def mode(self) -> str:
        """当前模式：``"light"`` / ``"dark"``。"""
        return self._mode

    @property
    def tokens(self) -> dict:
        """当前模式令牌视图（预设 + 会话覆盖）的副本。"""
        merged = dict(DARK if self._mode == "dark" else LIGHT)
        merged.update(self._overrides)
        return merged

    def _sync_mode(self, mode: str) -> None:
        """刷新模式（由 ThemeManager.set_mode / theme_changed 驱动）。"""
        if mode not in ("light", "dark") or mode == self._mode:
            return
        self._mode = mode
        self.mode_changed.emit(mode)

    # -- 读取 ------------------------------------------------------------
    def value(self, key: str, default=None):
        """取令牌值（覆盖优先，其次当前模式预设），缺省返回 ``default``。

        与 ``T()`` 等价但走状态机，且不会抛 KeyError。
        """
        if key in self._overrides:
            return self._overrides[key]
        return (DARK if self._mode == "dark" else LIGHT).get(key, default)

    def __getitem__(self, key: str):
        """取令牌值（语义同 ``T()``：未知键抛 KeyError）。"""
        if key in self._overrides:
            return self._overrides[key]
        return (DARK if self._mode == "dark" else LIGHT)[key]

    def color(self, key: str) -> QColor:
        """取颜色令牌，返回 ``QColor``。"""
        return QColor(self[key])

    def size(self, key: str) -> int:
        """取数值令牌（``space.*`` / ``radius.*`` / ``font.*`` 等），返回 int。

        行高（``font.line_height.*``）为 float，按原样返回。
        """
        v = self[key]
        return v if isinstance(v, float) else int(v)

    def font(self, scale: str = "md", weight: str = "regular") -> QFont:
        """按字阶 + 字重直接构造 ``QFont``。

        参数:
            scale: 字阶名（``xs`` / ``sm`` / ``md`` / ``lg`` / ``title.sm`` 等）。
            weight: 字重名（``regular`` / ``medium`` / ``semibold`` / ``bold``）。
        """
        f = QFont()
        f.setFamilies(_families(FONT_FAMILY))
        f.setStyleHint(QFont.SansSerif)
        f.setPixelSize(int(self.value(f"font.{scale}", LIGHT["font.md"])))
        w = int(self.value(f"font.weight.{weight}", LIGHT["font.weight.regular"]))
        f.setWeight(QFont.Weight(w))
        return f

    def shadow(self, level: str = "sm") -> dict:
        """取阴影令牌（``sm`` / ``md`` / ``lg``），返回 dict 副本。"""
        spec = self[f"shadow.{level}"]
        return {
            "blur": spec["blur"],
            "offset": tuple(spec["offset"]),
            "color": tuple(spec["color"]),
        }

    # -- 分组导出（当前模式视图 dict 副本） --------------------------------
    def _group(self, prefix: str) -> dict:
        return {k: v for k, v in self.tokens.items() if k.startswith(prefix)}

    def colors(self) -> dict:
        """全部 ``color.*`` 令牌。"""
        return self._group("color.")

    def typography(self) -> dict:
        """全部 ``font.*`` 令牌（字阶 / 字重 / 行高）。"""
        return self._group("font.")

    def spacing(self) -> dict:
        """全部 ``space.*`` 令牌。"""
        return self._group("space.")

    def radii(self) -> dict:
        """全部 ``radius.*`` 令牌。"""
        return self._group("radius.")

    def shadows(self) -> dict:
        """全部 ``shadow.*`` 令牌（dict 深拷贝一层）。"""
        return {k: dict(v) for k, v in self._group("shadow.").items()}

    def durations(self) -> dict:
        """全部 ``duration.*`` 令牌（ms）。"""
        return self._group("duration.")

    def easings(self) -> dict:
        """全部 ``easing.*`` 令牌（QEasingCurve.Type）。"""
        return self._group("easing.")

    def breakpoints(self) -> dict:
        """全部 ``breakpoint.*`` 令牌（各档最小宽度 px）。"""
        return self._group("breakpoint.")

    # -- 断点状态 ----------------------------------------------------------
    @property
    def current_breakpoint(self) -> str:
        """当前断点档位：``xs`` / ``sm`` / ``md`` / ``lg`` / ``xl``。"""
        return self._breakpoint

    @property
    def width(self) -> int:
        """最近一次 ``set_width`` 的窗口宽度（px）。"""
        return self._width

    def set_width(self, px: int) -> None:
        """更新窗口宽度；断点档位跳变时发射 ``breakpoint_changed``。

        响应式组件可订阅该信号按需重排。
        """
        self._width = int(px)
        bp = Breakpoint.from_width(self._width)
        if bp != self._breakpoint:
            self._breakpoint = bp
            self.breakpoint_changed.emit(bp)

    # -- 运行时覆盖（仅当前会话，不改预设常量） ------------------------------
    def set_token(self, key: str, value) -> None:
        """会话级覆盖某令牌并发射 ``token_changed``。

        只影响状态机视图（``value`` / ``T()`` / 分组导出），
        不修改本模块的 ``LIGHT`` / ``DARK`` 预设常量。
        """
        self._overrides[key] = value
        self.token_changed.emit(key)

    def reset_token(self, key: str) -> None:
        """撤销某令牌的会话覆盖（若存在）并发射 ``token_changed``。"""
        if key in self._overrides:
            del self._overrides[key]
            self.token_changed.emit(key)

    def reset_all(self) -> None:
        """撤销全部会话覆盖，逐键发射 ``token_changed``。"""
        keys = list(self._overrides)
        self._overrides.clear()
        for key in keys:
            self.token_changed.emit(key)

    def is_overridden(self, key: str) -> bool:
        """某令牌当前是否被会话覆盖。"""
        return key in self._overrides

    def overrides(self) -> dict:
        """当前全部会话覆盖的副本。"""
        return dict(self._overrides)
