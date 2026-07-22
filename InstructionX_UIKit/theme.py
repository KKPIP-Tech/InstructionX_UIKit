# -*- coding: utf-8 -*-
"""主题系统（SPEC §3 / §4）。

对外契约：

- ``ThemeManager``：单例主题管理器，``theme_changed`` 信号，
  ``set_mode`` / ``toggle`` / ``apply`` / ``tokens``。
- ``T(key)``：取当前主题令牌值（颜色为 str，数值为 int）。
- ``build_qss(tokens)``：由令牌字典生成全局 QSS，亮 / 暗双主题由此参数化。
- ``apply_shadow(widget, level)``：按 ``shadow.sm/md/lg`` 令牌应用投影。
- ``set_property(widget, name, value)``：设置动态属性并 unpolish/polish 刷新。

注意（重要）：``size`` 是 QWidget 内置 Q_PROPERTY（读写窗口尺寸），
``setProperty("size", ...)`` 会失败且不会成为动态属性，因此 QSS 中
``[size="sm"]`` 选择器在 Qt 中无法命中。本模块的 QSS 同时输出
``[size="..."]``（SPEC 契约）与 ``[uiksize="..."]``（可用别名）两组选择器，
组件请通过 ``set_property(widget, "size", v)`` 设置尺寸（内部自动映射为
``uiksize``），即可获得正确的 sm/md/lg 样式。
"""

import tempfile
from pathlib import Path

from PySide6.QtCore import QObject, QPointF, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QFont,
    QGuiApplication,
    QPainter,
    QPalette,
    QPen,
    QPixmap,
)
from PySide6.QtWidgets import QApplication, QGraphicsDropShadowEffect, QWidget

from .tokens import DARK, FONT_FAMILY, LIGHT, MONO_FAMILY, TokenState

__all__ = [
    "ThemeManager",
    "T",
    "build_qss",
    "apply_shadow",
    "set_property",
]

#: 合法主题模式
MODES = ("light", "dark")

# ---------------------------------------------------------------------------
# 尺寸速查表
# Qt QSS 盒模型为内容盒：控件总高 = min/max-height + 2 * 边框宽(1px)。
# 输入控件统一高度（SPEC §4）：sm=24 / md=32 / lg=40。
# QAbstractSpinBox 系列由样式额外增加 3px（实测 Fusion 风格）。
# ---------------------------------------------------------------------------

_INPUT_HEIGHTS = {"sm": 24, "md": 32, "lg": 40}
#: 一般输入控件 / 按钮的内容盒高度（总高 - 2）
_CONTENT_BOX = {k: v - 2 for k, v in _INPUT_HEIGHTS.items()}
#: 数字/日期调节框的内容盒高度（总高 - 5）
_SPIN_BOX = {k: v - 5 for k, v in _INPUT_HEIGHTS.items()}

#: 与 QWidget 内置属性冲突的动态属性别名映射
_SIZE_ALIAS = {"size": "uiksize"}


class ThemeManager(QObject):
    """主题管理器（单例）。

    用法::

        app = QApplication([])
        ThemeManager.instance().apply(app)      # 应用亮色主题
        ThemeManager.instance().toggle()        # 切换暗色
    """

    #: 主题切换信号，参数为 "light" / "dark"
    theme_changed = Signal(str)

    _instance = None

    def __init__(self, parent=None):
        super().__init__(parent)
        self._mode = "light"
        self._app = None  # 已 apply 过的 QApplication（弱语义，仅用于自动重应用）

    # -- 单例 ------------------------------------------------------------
    @classmethod
    def instance(cls) -> "ThemeManager":
        """返回全局唯一实例。"""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    # -- 状态 ------------------------------------------------------------
    @property
    def mode(self) -> str:
        """当前模式：``"light"`` 或 ``"dark"``，默认 ``"light"``。"""
        return self._mode

    @property
    def tokens(self) -> dict:
        """当前模式的令牌字典。"""
        return DARK if self._mode == "dark" else LIGHT

    # -- 操作 ------------------------------------------------------------
    def set_mode(self, mode: str) -> None:
        """设置主题模式。

        若之前已调用过 ``apply``，会自动重新生成 QSS 并设置到 QApplication，
        然后发射 ``theme_changed``。
        """
        if mode not in MODES:
            raise ValueError(f"未知主题模式: {mode!r}，应为 {MODES} 之一")
        if mode == self._mode:
            return
        self._mode = mode
        # 同步令牌状态机（发射 TokenState.mode_changed）
        TokenState.instance()._sync_mode(mode)
        if self._app is not None:
            self.apply(self._app)
        self.theme_changed.emit(mode)

    def toggle(self) -> None:
        """在亮 / 暗之间切换。"""
        self.set_mode("dark" if self._mode == "light" else "light")

    def apply(self, app: QApplication = None) -> None:
        """生成并设置全局 QSS（含基础样式、字体、调色板）。"""
        if app is None:
            app = QApplication.instance()
        if app is None:
            raise RuntimeError("ThemeManager.apply 需要可用的 QApplication 实例")
        self._app = app
        tokens = self.tokens
        app.setStyle("Fusion")
        app.setFont(_build_font(tokens))
        app.setPalette(_build_palette(tokens))
        app.setStyleSheet(build_qss(tokens))


def T(key: str):
    """取当前主题令牌值（颜色为 str，数值为 int，阴影为 dict）。

    内部委托令牌状态机 ``TokenState``：含会话级 ``set_token`` 覆盖，
    未知键仍抛 KeyError，行为与旧版一致。

    示例::

        color = T("color.primary")
        gap = T("space.4")
    """
    return TokenState.instance()[key]


def set_property(widget: QWidget, name: str, value) -> None:
    """设置动态属性并刷新控件样式（unpolish/polish）。

    参数 ``name="size"`` 时自动映射为 ``"uiksize"``（规避 QWidget 内置
    ``size`` 属性冲突），QSS 中 ``[size=...]`` 与 ``[uiksize=...]`` 选择器
    均已定义。
    """
    real = _SIZE_ALIAS.get(name, name)
    widget.setProperty(real, value)
    style = widget.style()
    style.unpolish(widget)
    style.polish(widget)
    widget.update()


def apply_shadow(widget: QWidget, level: str = "sm") -> None:
    """按令牌为控件添加投影（QGraphicsDropShadowEffect）。

    参数:
        widget: 目标控件。
        level: ``"sm"`` / ``"md"`` / ``"lg"`` 之一。
    """
    if level not in ("sm", "md", "lg"):
        raise ValueError(f"未知阴影级别: {level!r}，应为 sm/md/lg 之一")
    spec = ThemeManager.instance().tokens[f"shadow.{level}"]
    r, g, b, a = spec["color"]
    effect = QGraphicsDropShadowEffect(widget)
    effect.setBlurRadius(spec["blur"])
    effect.setOffset(*spec["offset"])
    effect.setColor(QColor(r, g, b, a))
    widget.setGraphicsEffect(effect)


# ---------------------------------------------------------------------------
# 应用字体 / 调色板（QSS 之外的底座）
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


def _build_font(tokens: dict) -> QFont:
    """按字族与正文字阶构造应用字体。"""
    font = QFont()
    font.setFamilies(_families(FONT_FAMILY))
    font.setStyleHint(QFont.SansSerif)
    font.setPixelSize(tokens["font.md"])
    return font


def _build_palette(tokens: dict) -> QPalette:
    """按令牌构造 QPalette（供 QStyle 绘制的箭头/图标等取色）。"""
    c = lambda k: QColor(tokens[f"color.{k}"])  # noqa: E731
    p = QPalette()
    p.setColor(QPalette.Window, c("bg.base"))
    p.setColor(QPalette.WindowText, c("text.primary"))
    p.setColor(QPalette.Base, c("bg.base"))
    p.setColor(QPalette.AlternateBase, c("bg.subtle"))
    p.setColor(QPalette.Text, c("text.primary"))
    p.setColor(QPalette.PlaceholderText, c("text.tertiary"))
    p.setColor(QPalette.Button, c("bg.elevated"))
    p.setColor(QPalette.ButtonText, c("text.primary"))
    p.setColor(QPalette.BrightText, c("on.primary"))
    p.setColor(QPalette.Highlight, c("primary"))
    p.setColor(QPalette.HighlightedText, c("on.primary"))
    p.setColor(QPalette.Link, c("primary"))
    p.setColor(QPalette.LinkVisited, c("primary.hover"))
    p.setColor(QPalette.ToolTipBase, c("bg.elevated"))
    p.setColor(QPalette.ToolTipText, c("text.primary"))
    p.setColor(QPalette.Light, c("bg.base"))
    p.setColor(QPalette.Midlight, c("bg.subtle"))
    p.setColor(QPalette.Mid, c("border.strong"))
    p.setColor(QPalette.Dark, c("border"))
    p.setColor(QPalette.Shadow, c("border"))
    disabled = c("text.disabled")
    p.setColor(QPalette.Disabled, QPalette.Text, disabled)
    p.setColor(QPalette.Disabled, QPalette.WindowText, disabled)
    p.setColor(QPalette.Disabled, QPalette.ButtonText, disabled)
    return p


# ---------------------------------------------------------------------------
# QSS 内嵌小图标（勾选、下拉箭头等），按令牌色运行时生成并缓存
# ---------------------------------------------------------------------------

_ASSET_DIR = Path(tempfile.gettempdir()) / "ui_kit_qss_assets"


def _stroke(painter: QPainter, color: str, width: float = 1.6) -> None:
    pen = QPen(QColor(color))
    pen.setWidthF(width)
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    painter.setPen(pen)
    painter.setBrush(Qt.NoBrush)


def _save_asset(name: str, draw) -> str:
    """绘制 12x12 透明 PNG 并缓存，返回 QSS 可用的 url 路径；失败返回空串。"""
    if QGuiApplication.instance() is None:
        return ""
    try:
        _ASSET_DIR.mkdir(parents=True, exist_ok=True)
    except OSError:
        return ""
    path = _ASSET_DIR / name
    if not path.exists():
        pm = QPixmap(12, 12)
        pm.fill(Qt.transparent)
        painter = QPainter(pm)
        painter.setRenderHint(QPainter.Antialiasing)
        draw(painter)
        painter.end()
        if not pm.save(str(path)):
            return ""
    return path.as_posix()


def _draw_check(color: str):
    def fn(p: QPainter) -> None:
        _stroke(p, color, 1.7)
        p.drawPolyline([QPointF(2.8, 6.6), QPointF(5.3, 9.1), QPointF(9.4, 3.2)])
    return fn


def _draw_dash(color: str):
    def fn(p: QPainter) -> None:
        _stroke(p, color, 1.8)
        p.drawLine(QPointF(3.0, 6.0), QPointF(9.0, 6.0))
    return fn


def _draw_chevron(color: str, direction: str):
    pts = {
        "down": [(2.8, 4.6), (6.0, 7.8), (9.2, 4.6)],
        "up": [(2.8, 7.4), (6.0, 4.2), (9.2, 7.4)],
        "right": [(4.6, 2.8), (7.8, 6.0), (4.6, 9.2)],
        "left": [(7.4, 2.8), (4.2, 6.0), (7.4, 9.2)],
    }[direction]

    def fn(p: QPainter) -> None:
        _stroke(p, color, 1.5)
        p.drawPolyline([QPointF(x, y) for x, y in pts])
    return fn


def _build_assets(tokens: dict) -> dict:
    """按令牌色生成全部小图标，返回 {名称: 路径}。"""
    c = lambda k: tokens[f"color.{k}"]  # noqa: E731
    key = c("text.secondary").lstrip("#")
    dis = c("text.disabled").lstrip("#")
    on = c("on.primary").lstrip("#")
    return {
        "check": _save_asset(f"check_{on}.png", _draw_check(c("on.primary"))),
        "check_dis": _save_asset(f"check_{dis}.png", _draw_check(c("text.disabled"))),
        "dash": _save_asset(f"dash_{on}.png", _draw_dash(c("on.primary"))),
        "chev_up": _save_asset(f"chev_up_{key}.png", _draw_chevron(c("text.secondary"), "up")),
        "chev_down": _save_asset(f"chev_down_{key}.png", _draw_chevron(c("text.secondary"), "down")),
        "chev_right": _save_asset(f"chev_right_{key}.png", _draw_chevron(c("text.secondary"), "right")),
        "chev_up_dis": _save_asset(f"chev_up_{dis}.png", _draw_chevron(c("text.disabled"), "up")),
        "chev_down_dis": _save_asset(f"chev_down_{dis}.png", _draw_chevron(c("text.disabled"), "down")),
    }


# ---------------------------------------------------------------------------
# 全局 QSS 生成（SPEC §4）
# ---------------------------------------------------------------------------

def build_qss(tokens: dict) -> str:
    """根据令牌字典生成全局 QSS。

    亮 / 暗双主题完全由传入的 ``tokens``（LIGHT 或 DARK）参数化，
    覆盖 SPEC §4 要求的全部控件与选择器。
    """
    if not isinstance(tokens, dict) or "color.primary" not in tokens:
        raise ValueError("build_qss: tokens 必须是 LIGHT / DARK 令牌字典")
    c = lambda k: tokens[f"color.{k}"]  # noqa: E731
    assets = _build_assets(tokens)

    def img(name: str) -> str:
        path = assets.get(name) or ""
        return f'image: url("{path}");' if path else ""

    sections = [
        _qss_base(c, tokens, img),
        _qss_buttons(c, tokens, img),
        _qss_inputs(c, tokens, img),
        _qss_views(c, tokens, img),
    ]
    return "\n".join(sections)


def _qss_base(c, t, img) -> str:
    """基座：QWidget / QToolTip / QMenu / QScrollBar / QSplitter / 窗口部件。"""
    return f"""
/* ==================== 基座 ==================== */
QWidget {{
    background-color: {c('bg.base')};
    color: {c('text.primary')};
    font-size: {t['font.md']}px;
}}
QMainWindow, QDialog {{ background-color: {c('bg.base')}; }}
QLabel {{ background-color: transparent; color: {c('text.primary')}; }}
QLabel[role="secondary"] {{ color: {c('text.secondary')}; }}
QLabel[role="tertiary"], QLabel[role="hint"] {{ color: {c('text.tertiary')}; }}
QLabel:disabled {{ color: {c('text.disabled')}; }}
QScrollArea {{ background-color: transparent; border: none; }}
QSizeGrip {{ background: none; width: 12px; height: 12px; }}

QToolTip {{
    background-color: {c('text.primary')};
    color: {c('bg.base')};
    border: 1px solid {c('border.strong')};
    border-radius: {t['radius.sm']}px;
    padding: {t['space.1']}px {t['space.2']}px;
    font-size: {t['font.sm']}px;
    opacity: 255;
}}

QMenu {{
    background-color: {c('bg.elevated')};
    color: {c('text.primary')};
    border: 1px solid {c('border')};
    border-radius: {t['radius.lg']}px;
    padding: {t['space.1']}px;
}}
QMenu::item {{
    padding: 6px 28px 6px 12px;
    border-radius: {t['radius.sm']}px;
    background-color: transparent;
    color: {c('text.primary')};
}}
QMenu::item:selected {{ background-color: {c('primary.subtle')}; color: {c('primary')}; }}
QMenu::item:disabled {{ color: {c('text.disabled')}; }}
QMenu::separator {{ height: 1px; background-color: {c('border')}; margin: 4px 8px; }}
QMenu::indicator {{ width: 16px; height: 16px; }}
QMenu::right-arrow {{ {img('chev_right')} width: 10px; height: 10px; }}

/* 细滚动条 8px，hover 变深（SPEC §4） */
QScrollBar:vertical {{ background-color: transparent; width: 8px; margin: 2px 0px; }}
QScrollBar::handle:vertical {{
    background-color: {c('border.strong')}; min-height: 24px; border-radius: 4px;
}}
QScrollBar::handle:vertical:hover {{ background-color: {c('text.tertiary')}; }}
QScrollBar::handle:vertical:pressed {{ background-color: {c('text.secondary')}; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0px; border: none; background: none;
}}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: none; }}
QScrollBar:horizontal {{ background-color: transparent; height: 8px; margin: 0px 2px; }}
QScrollBar::handle:horizontal {{
    background-color: {c('border.strong')}; min-width: 24px; border-radius: 4px;
}}
QScrollBar::handle:horizontal:hover {{ background-color: {c('text.tertiary')}; }}
QScrollBar::handle:horizontal:pressed {{ background-color: {c('text.secondary')}; }}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
    width: 0px; border: none; background: none;
}}
QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{ background: none; }}

QSplitter::handle {{ background-color: {c('border')}; }}
QSplitter::handle:horizontal {{ width: 2px; }}
QSplitter::handle:vertical {{ height: 2px; }}
QSplitter::handle:hover {{ background-color: {c('primary')}; }}
QSplitter::handle:pressed {{ background-color: {c('primary.pressed')}; }}

QFrame {{ border: none; }}
QFrame[frameShape="4"] {{ border-top: 1px solid {c('border')}; max-height: 1px; background: none; }}
QFrame[frameShape="5"] {{ border-left: 1px solid {c('border')}; max-width: 1px; background: none; }}
QFrame[frameShape="6"] {{
    border: 1px solid {c('border')};
    border-radius: {t['radius.md']}px;
    background-color: {c('bg.elevated')};
}}

QMenuBar {{
    background-color: {c('bg.base')};
    border-bottom: 1px solid {c('border')};
    padding: 2px;
}}
QMenuBar::item {{
    background-color: transparent;
    color: {c('text.primary')};
    padding: 5px 10px;
    border-radius: {t['radius.sm']}px;
}}
QMenuBar::item:selected, QMenuBar::item:pressed {{ background-color: {c('bg.muted')}; }}

QToolBar {{ background-color: {c('bg.base')}; border: none; padding: 4px; spacing: 4px; }}
QToolBar::separator:horizontal {{
    width: 1px; background-color: {c('border')}; margin: 4px 6px;
}}
QToolBar::separator:vertical {{
    height: 1px; background-color: {c('border')}; margin: 6px 4px;
}}
QToolBar QToolButton {{ padding: 5px; }}

QStatusBar {{
    background-color: {c('bg.subtle')};
    color: {c('text.secondary')};
    border-top: 1px solid {c('border')};
}}
QStatusBar::item {{ border: none; }}
QStatusBar QLabel {{ background-color: transparent; color: {c('text.secondary')}; }}

QDockWidget {{ color: {c('text.primary')}; font-weight: bold; }}
QDockWidget::title {{
    background-color: {c('bg.subtle')};
    padding: 8px 12px;
    border-bottom: 1px solid {c('border')};
    text-align: left;
}}
QDockWidget::close-button, QDockWidget::float-button {{
    background-color: transparent;
    border-radius: {t['radius.sm']}px;
    padding: 2px;
}}
QDockWidget::close-button:hover, QDockWidget::float-button:hover {{
    background-color: {c('bg.muted')};
}}

QMessageBox {{ background-color: {c('bg.base')}; }}
QMessageBox QLabel {{
    background-color: transparent; color: {c('text.primary')}; font-size: {t['font.md']}px;
}}
QMessageBox QPushButton, QDialogButtonBox QPushButton {{ min-width: 72px; }}
"""


def _qss_buttons(c, t, img) -> str:
    """按钮：QPushButton 变体 / 尺寸 / 形状 + QToolButton。"""
    sm, md, lg = _CONTENT_BOX["sm"], _CONTENT_BOX["md"], _CONTENT_BOX["lg"]
    return f"""
/* ==================== 按钮 ==================== */
QPushButton, QPushButton[variant="default"] {{
    background-color: {c('bg.elevated')};
    color: {c('text.primary')};
    border: 1px solid {c('border')};
    border-radius: {t['radius.md']}px;
    padding: 0 {t['space.4']}px;
    min-height: {md}px;
    max-height: {md}px;
    font-size: {t['font.md']}px;
}}
QPushButton:hover, QPushButton[variant="default"]:hover {{
    border-color: {c('primary')}; color: {c('primary')};
}}
QPushButton:pressed, QPushButton[variant="default"]:pressed {{
    border-color: {c('primary.pressed')}; color: {c('primary.pressed')};
}}
QPushButton:focus {{ border-color: {c('primary')}; }}
QPushButton:disabled {{
    background-color: {c('bg.muted')};
    border-color: {c('border')};
    color: {c('text.disabled')};
}}

QPushButton[variant="primary"] {{
    background-color: {c('primary')};
    border-color: {c('primary')};
    color: {c('on.primary')};
}}
QPushButton[variant="primary"]:hover {{
    background-color: {c('primary.hover')}; border-color: {c('primary.hover')};
}}
QPushButton[variant="primary"]:pressed {{
    background-color: {c('primary.pressed')}; border-color: {c('primary.pressed')};
}}
QPushButton[variant="primary"]:disabled {{
    background-color: {c('bg.muted')};
    border-color: {c('bg.muted')};
    color: {c('text.disabled')};
}}

QPushButton[variant="dashed"] {{
    background-color: {c('bg.elevated')};
    border: 1px dashed {c('border.strong')};
    color: {c('text.primary')};
}}
QPushButton[variant="dashed"]:hover {{ border-color: {c('primary')}; color: {c('primary')}; }}
QPushButton[variant="dashed"]:pressed {{
    border-color: {c('primary.pressed')}; color: {c('primary.pressed')};
}}

QPushButton[variant="text"] {{
    background-color: transparent; border-color: transparent; color: {c('text.primary')};
}}
QPushButton[variant="text"]:hover {{
    background-color: {c('bg.muted')}; border-color: transparent; color: {c('text.primary')};
}}
QPushButton[variant="text"]:pressed {{ background-color: {c('border')}; }}

QPushButton[variant="link"] {{
    background-color: transparent; border-color: transparent; color: {c('primary')};
}}
QPushButton[variant="link"]:hover {{
    background-color: transparent; border-color: transparent; color: {c('primary.hover')};
}}
QPushButton[variant="link"]:pressed {{
    background-color: transparent; border-color: transparent; color: {c('primary.pressed')};
}}
QPushButton[variant="link"]:disabled {{
    background-color: transparent; border-color: transparent; color: {c('text.disabled')};
}}

QPushButton[variant="danger"] {{
    background-color: {c('danger')};
    border-color: {c('danger')};
    color: {c('on.primary')};
}}
QPushButton[variant="danger"]:hover {{
    background-color: {c('danger.hover')}; border-color: {c('danger.hover')};
}}
QPushButton[variant="danger"]:pressed {{
    background-color: {c('danger.hover')}; border-color: {c('danger.hover')};
}}
QPushButton[variant="danger"]:disabled {{
    background-color: {c('bg.muted')};
    border-color: {c('bg.muted')};
    color: {c('text.disabled')};
}}

/* 尺寸：sm=24 / md=32 / lg=40（size 与 uiksize 别名选择器并存） */
QPushButton[size="sm"], QPushButton[uiksize="sm"] {{
    min-height: {sm}px; max-height: {sm}px;
    padding: 0 {t['space.2']}px; font-size: {t['font.sm']}px;
}}
QPushButton[size="md"], QPushButton[uiksize="md"] {{
    min-height: {md}px; max-height: {md}px;
    padding: 0 {t['space.4']}px; font-size: {t['font.md']}px;
}}
QPushButton[size="lg"], QPushButton[uiksize="lg"] {{
    min-height: {lg}px; max-height: {lg}px;
    padding: 0 {t['space.5']}px; font-size: {t['font.lg']}px;
}}

/* 形状：round 为胶囊圆角，circle 为正圆（配合组件固定宽=高） */
QPushButton[shape="round"] {{ border-radius: 16px; }}
QPushButton[shape="round"][size="sm"], QPushButton[shape="round"][uiksize="sm"] {{ border-radius: 12px; }}
QPushButton[shape="round"][size="lg"], QPushButton[shape="round"][uiksize="lg"] {{ border-radius: 20px; }}
QPushButton[shape="circle"] {{ border-radius: 16px; padding: 0; }}
QPushButton[shape="circle"][size="sm"], QPushButton[shape="circle"][uiksize="sm"] {{ border-radius: 12px; }}
QPushButton[shape="circle"][size="lg"], QPushButton[shape="circle"][uiksize="lg"] {{ border-radius: 20px; }}

QToolButton {{
    background-color: transparent;
    color: {c('text.primary')};
    border: 1px solid transparent;
    border-radius: {t['radius.md']}px;
    padding: 4px;
}}
QToolButton:hover {{ background-color: {c('bg.muted')}; }}
QToolButton:pressed {{ background-color: {c('border')}; }}
QToolButton:checked {{
    background-color: {c('primary.subtle')}; color: {c('primary')};
}}
QToolButton:disabled {{ color: {c('text.disabled')}; }}
QToolButton::menu-indicator {{
    {img('chev_down')} width: 10px; height: 10px;
    subcontrol-position: right center;
}}
QToolButton[variant="primary"] {{
    background-color: {c('primary')}; border-color: {c('primary')};
    color: {c('on.primary')}; padding: 0 12px;
}}
QToolButton[variant="primary"]:hover {{
    background-color: {c('primary.hover')}; border-color: {c('primary.hover')};
}}
QToolButton[variant="primary"]:pressed {{
    background-color: {c('primary.pressed')}; border-color: {c('primary.pressed')};
}}
QToolButton[variant="default"] {{
    background-color: {c('bg.elevated')}; border-color: {c('border')}; padding: 0 12px;
}}
QToolButton[variant="default"]:hover {{
    border-color: {c('primary')}; color: {c('primary')};
}}
QToolButton[variant="danger"] {{
    background-color: {c('danger')}; border-color: {c('danger')};
    color: {c('on.primary')}; padding: 0 12px;
}}
QToolButton[variant="danger"]:hover {{
    background-color: {c('danger.hover')}; border-color: {c('danger.hover')};
}}
QToolButton[size="sm"], QToolButton[uiksize="sm"] {{
    min-height: {sm}px; max-height: {sm}px; font-size: {t['font.sm']}px;
}}
QToolButton[size="md"], QToolButton[uiksize="md"] {{
    min-height: {md}px; max-height: {md}px; font-size: {t['font.md']}px;
}}
QToolButton[size="lg"], QToolButton[uiksize="lg"] {{
    min-height: {lg}px; max-height: {lg}px; font-size: {t['font.lg']}px;
}}
QToolButton[shape="circle"] {{ border-radius: 16px; }}
QToolButton[shape="circle"][size="sm"], QToolButton[shape="circle"][uiksize="sm"] {{ border-radius: 12px; }}
QToolButton[shape="circle"][size="lg"], QToolButton[shape="circle"][uiksize="lg"] {{ border-radius: 20px; }}
QToolButton[shape="round"] {{ border-radius: 16px; }}
QToolButton[shape="round"][size="sm"], QToolButton[shape="round"][uiksize="sm"] {{ border-radius: 12px; }}
QToolButton[shape="round"][size="lg"], QToolButton[shape="round"][uiksize="lg"] {{ border-radius: 20px; }}
"""


def _qss_inputs(c, t, img) -> str:
    """输入控件：高度体系 sm=24 / md=32 / lg=40，focus 主色边框。"""
    sm, md, lg = _CONTENT_BOX["sm"], _CONTENT_BOX["md"], _CONTENT_BOX["lg"]
    ssm, smd, slg = _SPIN_BOX["sm"], _SPIN_BOX["md"], _SPIN_BOX["lg"]
    return f"""
/* ==================== 输入控件 ==================== */
QLineEdit {{
    background-color: {c('bg.elevated')};
    color: {c('text.primary')};
    border: 1px solid {c('border')};
    border-radius: {t['radius.md']}px;
    padding: 0 {t['space.3']}px;
    min-height: {md}px;
    max-height: {md}px;
    selection-background-color: {c('primary')};
    selection-color: {c('on.primary')};
}}
QLineEdit:hover {{ border-color: {c('border.strong')}; }}
QLineEdit:focus {{ border-color: {c('primary')}; }}
QLineEdit:disabled {{
    background-color: {c('bg.muted')}; border-color: {c('border')}; color: {c('text.disabled')};
}}
QLineEdit[size="sm"], QLineEdit[uiksize="sm"] {{
    min-height: {sm}px; max-height: {sm}px;
    padding: 0 {t['space.2']}px; font-size: {t['font.sm']}px;
}}
QLineEdit[size="md"], QLineEdit[uiksize="md"] {{
    min-height: {md}px; max-height: {md}px; font-size: {t['font.md']}px;
}}
QLineEdit[size="lg"], QLineEdit[uiksize="lg"] {{
    min-height: {lg}px; max-height: {lg}px;
    padding: 0 {t['space.3']}px; font-size: {t['font.lg']}px;
}}
QLineEdit[error="true"] {{ border-color: {c('danger')}; }}
QLineEdit[error="true"]:hover {{ border-color: {c('danger.hover')}; }}
QLineEdit[error="true"]:focus {{ border-color: {c('danger')}; }}

QTextEdit, QPlainTextEdit {{
    background-color: {c('bg.elevated')};
    color: {c('text.primary')};
    border: 1px solid {c('border')};
    border-radius: {t['radius.md']}px;
    padding: {t['space.1']}px {t['space.2']}px;
    selection-background-color: {c('primary')};
    selection-color: {c('on.primary')};
}}
QTextEdit:hover, QPlainTextEdit:hover {{ border-color: {c('border.strong')}; }}
QTextEdit:focus, QPlainTextEdit:focus {{ border-color: {c('primary')}; }}
QTextEdit:disabled, QPlainTextEdit:disabled {{
    background-color: {c('bg.muted')}; border-color: {c('border')}; color: {c('text.disabled')};
}}

/* 数字 / 日期时间调节框（高度口径与 QLineEdit 对齐） */
QSpinBox, QDoubleSpinBox, QDateEdit, QTimeEdit, QDateTimeEdit {{
    background-color: {c('bg.elevated')};
    color: {c('text.primary')};
    border: 1px solid {c('border')};
    border-radius: {t['radius.md']}px;
    padding: 0 {t['space.2']}px;
    min-height: {smd}px;
    max-height: {smd}px;
    selection-background-color: {c('primary')};
    selection-color: {c('on.primary')};
}}
QSpinBox:hover, QDoubleSpinBox:hover, QDateEdit:hover, QTimeEdit:hover, QDateTimeEdit:hover {{
    border-color: {c('border.strong')};
}}
QSpinBox:focus, QDoubleSpinBox:focus, QDateEdit:focus, QTimeEdit:focus, QDateTimeEdit:focus {{
    border-color: {c('primary')};
}}
QSpinBox:disabled, QDoubleSpinBox:disabled, QDateEdit:disabled, QTimeEdit:disabled, QDateTimeEdit:disabled {{
    background-color: {c('bg.muted')}; border-color: {c('border')}; color: {c('text.disabled')};
}}
QSpinBox[size="sm"], QDoubleSpinBox[size="sm"], QDateEdit[size="sm"], QTimeEdit[size="sm"], QDateTimeEdit[size="sm"],
QSpinBox[uiksize="sm"], QDoubleSpinBox[uiksize="sm"], QDateEdit[uiksize="sm"], QTimeEdit[uiksize="sm"], QDateTimeEdit[uiksize="sm"] {{
    min-height: {ssm}px; max-height: {ssm}px; font-size: {t['font.sm']}px;
}}
QSpinBox[size="md"], QDoubleSpinBox[size="md"], QDateEdit[size="md"], QTimeEdit[size="md"], QDateTimeEdit[size="md"],
QSpinBox[uiksize="md"], QDoubleSpinBox[uiksize="md"], QDateEdit[uiksize="md"], QTimeEdit[uiksize="md"], QDateTimeEdit[uiksize="md"] {{
    min-height: {smd}px; max-height: {smd}px; font-size: {t['font.md']}px;
}}
QSpinBox[size="lg"], QDoubleSpinBox[size="lg"], QDateEdit[size="lg"], QTimeEdit[size="lg"], QDateTimeEdit[size="lg"],
QSpinBox[uiksize="lg"], QDoubleSpinBox[uiksize="lg"], QDateEdit[uiksize="lg"], QTimeEdit[uiksize="lg"], QDateTimeEdit[uiksize="lg"] {{
    min-height: {slg}px; max-height: {slg}px; font-size: {t['font.lg']}px;
}}
QSpinBox::up-button, QDoubleSpinBox::up-button, QDateEdit::up-button, QTimeEdit::up-button, QDateTimeEdit::up-button {{
    subcontrol-origin: border;
    subcontrol-position: top right;
    width: 20px;
    background-color: transparent;
    border: none;
    border-left: 1px solid {c('border')};
    border-top-right-radius: {t['radius.md']}px;
}}
QSpinBox::down-button, QDoubleSpinBox::down-button, QDateEdit::down-button, QTimeEdit::down-button, QDateTimeEdit::down-button {{
    subcontrol-origin: border;
    subcontrol-position: bottom right;
    width: 20px;
    background-color: transparent;
    border: none;
    border-left: 1px solid {c('border')};
    border-bottom-right-radius: {t['radius.md']}px;
}}
QSpinBox::up-button:hover, QDoubleSpinBox::up-button:hover, QDateEdit::up-button:hover,
QTimeEdit::up-button:hover, QDateTimeEdit::up-button:hover,
QSpinBox::down-button:hover, QDoubleSpinBox::down-button:hover, QDateEdit::down-button:hover,
QTimeEdit::down-button:hover, QDateTimeEdit::down-button:hover {{
    background-color: {c('bg.muted')};
}}
QSpinBox::up-arrow, QDoubleSpinBox::up-arrow, QDateEdit::up-arrow, QTimeEdit::up-arrow, QDateTimeEdit::up-arrow {{
    {img('chev_up')} width: 10px; height: 10px;
}}
QSpinBox::down-arrow, QDoubleSpinBox::down-arrow, QDateEdit::down-arrow, QTimeEdit::down-arrow, QDateTimeEdit::down-arrow {{
    {img('chev_down')} width: 10px; height: 10px;
}}
QSpinBox::up-arrow:disabled, QDoubleSpinBox::up-arrow:disabled, QDateEdit::up-arrow:disabled,
QTimeEdit::up-arrow:disabled, QDateTimeEdit::up-arrow:disabled {{
    {img('chev_up_dis')}
}}
QSpinBox::down-arrow:disabled, QDoubleSpinBox::down-arrow:disabled, QDateEdit::down-arrow:disabled,
QTimeEdit::down-arrow:disabled, QDateTimeEdit::down-arrow:disabled {{
    {img('chev_down_dis')}
}}

/* 下拉框 */
QComboBox {{
    combobox-popup: 0;
    background-color: {c('bg.elevated')};
    color: {c('text.primary')};
    border: 1px solid {c('border')};
    border-radius: {t['radius.md']}px;
    padding: 0 {t['space.2']}px 0 {t['space.3']}px;
    min-height: {md}px;
    max-height: {md}px;
    selection-background-color: {c('primary')};
    selection-color: {c('on.primary')};
}}
QComboBox:hover {{ border-color: {c('border.strong')}; }}
QComboBox:focus, QComboBox:on {{ border-color: {c('primary')}; }}
QComboBox:disabled {{
    background-color: {c('bg.muted')}; border-color: {c('border')}; color: {c('text.disabled')};
}}
QComboBox[size="sm"], QComboBox[uiksize="sm"] {{
    min-height: {sm}px; max-height: {sm}px; font-size: {t['font.sm']}px;
}}
QComboBox[size="md"], QComboBox[uiksize="md"] {{
    min-height: {md}px; max-height: {md}px; font-size: {t['font.md']}px;
}}
QComboBox[size="lg"], QComboBox[uiksize="lg"] {{
    min-height: {lg}px; max-height: {lg}px; font-size: {t['font.lg']}px;
}}
QComboBox::drop-down {{
    subcontrol-origin: padding;
    subcontrol-position: center right;
    width: 28px;
    border: none;
    border-top-right-radius: {t['radius.md']}px;
    border-bottom-right-radius: {t['radius.md']}px;
}}
QComboBox::down-arrow {{ {img('chev_down')} width: 12px; height: 12px; }}
QComboBox::down-arrow:on {{ {img('chev_up')} }}
QComboBox::down-arrow:disabled {{ {img('chev_down_dis')} }}
QComboBox QLineEdit {{
    border: none; background-color: transparent; border-radius: 0;
    min-height: 0px; max-height: 1000px; padding: 0 4px;
}}
QComboBox QAbstractItemView {{
    background-color: {c('bg.elevated')};
    color: {c('text.primary')};
    border: 1px solid {c('border')};
    border-radius: {t['radius.md']}px;
    padding: {t['space.1']}px;
    outline: none;
    selection-background-color: {c('primary.subtle')};
    selection-color: {c('text.primary')};
}}
QComboBox QAbstractItemView::item {{
    min-height: 26px; padding: 0 {t['space.2']}px; border-radius: {t['radius.sm']}px;
}}

/* 滑块 */
QSlider::groove:horizontal {{
    height: 4px; background-color: {c('bg.muted')}; border-radius: 2px;
}}
QSlider::sub-page:horizontal {{ background-color: {c('primary')}; border-radius: 2px; }}
QSlider::add-page:horizontal {{ background-color: {c('bg.muted')}; border-radius: 2px; }}
QSlider::handle:horizontal {{
    background-color: {c('on.primary')};
    border: 2px solid {c('primary')};
    width: 12px; height: 12px; margin: -6px 0; border-radius: 8px;
}}
/* hover 仅改描边色：vertical 的 :hover background-color 会渗漏到常态渲染，
   使常态手柄被主色实心覆盖（Qt 6.11 实测），pressed 不受影响 */
QSlider::handle:horizontal:hover, QSlider::handle:vertical:hover {{
    border-color: {c('primary.hover')};
}}
QSlider::handle:horizontal:pressed {{
    background-color: {c('primary.pressed')}; border-color: {c('primary.pressed')};
}}
QSlider::handle:horizontal:disabled {{ border-color: {c('text.disabled')}; }}
QSlider::groove:vertical {{
    width: 4px; background-color: {c('bg.muted')}; border-radius: 2px;
}}
QSlider::sub-page:vertical {{ background-color: {c('primary')}; border-radius: 2px; }}
QSlider::add-page:vertical {{ background-color: {c('bg.muted')}; border-radius: 2px; }}
QSlider::handle:vertical {{
    background-color: {c('on.primary')};
    border: 2px solid {c('primary')};
    width: 12px; height: 12px; margin: 0 -6px; border-radius: 8px;
}}
QSlider::handle:vertical:pressed {{
    background-color: {c('primary.pressed')}; border-color: {c('primary.pressed')};
}}
QSlider::handle:vertical:disabled {{ border-color: {c('text.disabled')}; }}

/* 进度条 */
QProgressBar {{
    background-color: {c('bg.muted')};
    border: none;
    border-radius: 4px;
    min-height: 8px;
    max-height: 8px;
    text-align: center;
    color: transparent;
    font-size: {t['font.xs']}px;
}}
QProgressBar::chunk {{ background-color: {c('primary')}; border-radius: 4px; }}
QProgressBar[status="success"]::chunk {{ background-color: {c('success')}; }}
QProgressBar[status="warning"]::chunk {{ background-color: {c('warning')}; }}
QProgressBar[status="error"]::chunk {{ background-color: {c('danger')}; }}
QProgressBar:disabled::chunk {{ background-color: {c('text.disabled')}; }}

/* 复选框 */
QCheckBox {{ color: {c('text.primary')}; spacing: 8px; background-color: transparent; }}
QCheckBox:disabled {{ color: {c('text.disabled')}; }}
QCheckBox::indicator {{
    width: 16px; height: 16px;
    border: 1px solid {c('border.strong')};
    border-radius: {t['radius.sm']}px;
    background-color: {c('bg.elevated')};
}}
QCheckBox::indicator:hover {{ border-color: {c('primary')}; }}
QCheckBox::indicator:checked {{
    background-color: {c('primary')}; border-color: {c('primary')}; {img('check')}
}}
QCheckBox::indicator:indeterminate {{
    background-color: {c('primary')}; border-color: {c('primary')}; {img('dash')}
}}
QCheckBox::indicator:disabled {{
    background-color: {c('bg.muted')}; border-color: {c('border')};
}}
QCheckBox::indicator:checked:disabled, QCheckBox::indicator:indeterminate:disabled {{
    background-color: {c('bg.muted')}; border-color: {c('border')}; {img('check_dis')}
}}

/* 单选框（厚边框成环，中心留白成点；选中态缩小内容盒保持外径不变，避免指示器被裁） */
QRadioButton {{ color: {c('text.primary')}; spacing: 8px; background-color: transparent; }}
QRadioButton:disabled {{ color: {c('text.disabled')}; }}
QRadioButton::indicator {{
    width: 16px; height: 16px;
    border: 1px solid {c('border.strong')};
    border-radius: 9px;
    background-color: {c('bg.elevated')};
}}
QRadioButton::indicator:hover {{ border-color: {c('primary')}; }}
QRadioButton::indicator:checked {{
    width: 8px; height: 8px;
    border: 5px solid {c('primary')};
    border-radius: 9px;
    background-color: {c('bg.elevated')};
}}
QRadioButton::indicator:disabled {{
    background-color: {c('bg.muted')}; border-color: {c('border')};
}}
QRadioButton::indicator:checked:disabled {{
    width: 8px; height: 8px;
    background-color: {c('bg.muted')}; border: 5px solid {c('text.disabled')};
    border-radius: 9px;
}}
/* 尺寸：sm 外径 14 / md 外径 18 / lg 外径 20，选中态外径与未选中一致 */
QRadioButton[size="sm"]::indicator, QRadioButton[uiksize="sm"]::indicator {{
    width: 12px; height: 12px; border-radius: 7px;
}}
QRadioButton[size="sm"]::indicator:checked, QRadioButton[uiksize="sm"]::indicator:checked {{
    width: 6px; height: 6px; border: 4px solid {c('primary')}; border-radius: 7px;
}}
QRadioButton[size="sm"]::indicator:checked:disabled, QRadioButton[uiksize="sm"]::indicator:checked:disabled {{
    width: 6px; height: 6px; border: 4px solid {c('text.disabled')}; border-radius: 7px;
}}
QRadioButton[size="lg"]::indicator, QRadioButton[uiksize="lg"]::indicator {{
    width: 18px; height: 18px; border-radius: 10px;
}}
QRadioButton[size="lg"]::indicator:checked, QRadioButton[uiksize="lg"]::indicator:checked {{
    width: 10px; height: 10px; border: 5px solid {c('primary')}; border-radius: 10px;
}}
QRadioButton[size="lg"]::indicator:checked:disabled, QRadioButton[uiksize="lg"]::indicator:checked:disabled {{
    width: 10px; height: 10px; border: 5px solid {c('text.disabled')}; border-radius: 10px;
}}
"""


def _qss_views(c, t, img) -> str:
    """容器与数据视图：分组框、标签页、表 / 树 / 列表、表头、日历。"""
    return f"""
/* ==================== 容器与视图 ==================== */
QGroupBox {{
    background-color: {c('bg.elevated')};
    border: 1px solid {c('border')};
    border-radius: {t['radius.md']}px;
    margin-top: 16px;
    padding: {t['space.3']}px;
    font-weight: bold;
    color: {c('text.primary')};
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 10px;
    top: 2px;
    padding: 0 {t['space.1']}px;
    color: {c('text.primary')};
}}

QTabWidget::pane {{
    border: none;
    border-top: 1px solid {c('border')};
    background-color: {c('bg.base')};
}}
QTabBar {{ background-color: transparent; }}
QTabBar::tab {{
    background-color: transparent;
    color: {c('text.secondary')};
    padding: 8px 14px;
    border: none;
}}
QTabBar::tab:hover {{ color: {c('text.primary')}; }}
QTabBar::tab:disabled {{ color: {c('text.disabled')}; }}
QTabBar::tab:top {{ border-bottom: 2px solid transparent; margin-right: 2px; }}
QTabBar::tab:top:selected {{ color: {c('primary')}; border-bottom-color: {c('primary')}; }}
QTabBar::tab:bottom {{ border-top: 2px solid transparent; margin-right: 2px; }}
QTabBar::tab:bottom:selected {{ color: {c('primary')}; border-top-color: {c('primary')}; }}
QTabBar::tab:left {{ border-right: 2px solid transparent; margin-bottom: 2px; }}
QTabBar::tab:left:selected {{ color: {c('primary')}; border-right-color: {c('primary')}; }}
QTabBar::tab:right {{ border-left: 2px solid transparent; margin-bottom: 2px; }}
QTabBar::tab:right:selected {{ color: {c('primary')}; border-left-color: {c('primary')}; }}

QTableView, QTreeView, QListView {{
    background-color: {c('bg.base')};
    alternate-background-color: {c('bg.subtle')};
    color: {c('text.primary')};
    border: 1px solid {c('border')};
    border-radius: {t['radius.md']}px;
    gridline-color: {c('border')};
    selection-background-color: {c('primary.subtle')};
    selection-color: {c('text.primary')};
    outline: none;
}}
QTableView::item, QTreeView::item, QListView::item {{
    padding: 4px 8px; border: none;
}}
QTableView::item:hover, QTreeView::item:hover, QListView::item:hover {{
    background-color: {c('bg.muted')};
}}
QTableView::item:selected, QTreeView::item:selected, QListView::item:selected {{
    background-color: {c('primary.subtle')}; color: {c('text.primary')};
}}
QTableView::item:disabled, QTreeView::item:disabled, QListView::item:disabled {{
    color: {c('text.disabled')};
}}
QTreeView::branch {{ background-color: transparent; }}
QTreeView::branch:closed:has-children {{ {img('chev_right')} }}
QTreeView::branch:open:has-children {{ {img('chev_down')} }}

QHeaderView {{ background-color: {c('bg.subtle')}; border: none; }}
QHeaderView::section {{
    background-color: {c('bg.subtle')};
    color: {c('text.secondary')};
    padding: 6px 10px;
    border: none;
    border-right: 1px solid {c('border')};
    border-bottom: 1px solid {c('border')};
    font-weight: bold;
}}
QHeaderView::section:first {{ border-left: none; }}
QHeaderView::section:last {{ border-right: none; }}
QHeaderView::section:hover {{ color: {c('text.primary')}; }}
QTableCornerButton::section {{
    background-color: {c('bg.subtle')};
    border: none;
    border-right: 1px solid {c('border')};
    border-bottom: 1px solid {c('border')};
}}

/* 日历 */
QCalendarWidget QWidget {{ alternate-background-color: {c('bg.subtle')}; }}
QCalendarWidget QWidget#qt_calendar_navigationbar {{
    background-color: {c('bg.subtle')};
    border-bottom: 1px solid {c('border')};
    padding: 4px 8px;
}}
QCalendarWidget QToolButton {{
    color: {c('text.primary')};
    background-color: transparent;
    border-radius: {t['radius.sm']}px;
    padding: 4px 6px;
    font-weight: bold;
    icon-size: 16px;
}}
QCalendarWidget QToolButton:hover {{ background-color: {c('bg.muted')}; }}
QCalendarWidget QToolButton::menu-indicator {{
    {img('chev_down')} width: 8px; height: 8px;
    subcontrol-position: right center;
}}
QCalendarWidget QSpinBox#qt_calendar_yearedit {{
    background-color: transparent;
    border: none;
    min-height: 0px;
    max-height: 1000px;
    font-weight: bold;
    padding: 0 2px;
}}
QCalendarWidget QSpinBox#qt_calendar_yearedit::up-button,
QCalendarWidget QSpinBox#qt_calendar_yearedit::down-button {{
    width: 14px; border: none;
}}
QCalendarWidget QTableView {{
    border: none;
    background-color: {c('bg.base')};
    alternate-background-color: {c('bg.subtle')};
    selection-background-color: {c('primary')};
    selection-color: {c('on.primary')};
}}
/* 日历日期单元格：清除全局 ::item 内边距，否则列宽不足导致日期数字被省略号替代 */
QCalendarWidget QTableView::item {{
    padding: 0px;
    border: none;
}}
QCalendarWidget QHeaderView::section {{
    background-color: {c('bg.base')};
    color: {c('text.tertiary')};
    border: none;
    padding: 4px 0;
    font-weight: normal;
    font-size: {t['font.sm']}px;
}}
QCalendarWidget QAbstractItemView:enabled {{
    color: {c('text.primary')};
    background-color: {c('bg.base')};
    selection-background-color: {c('primary')};
    selection-color: {c('on.primary')};
}}
QCalendarWidget QAbstractItemView:disabled {{ color: {c('text.disabled')}; }}
"""
