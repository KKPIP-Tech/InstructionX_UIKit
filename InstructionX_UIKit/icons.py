# -*- coding: utf-8 -*-
"""Iconoir 图标集（完整 v7.12.1，MIT License）。

- 图标来自 Iconoir v7.12.1（1,383 Regular + 288 Solid，共 1,671 个）；
- 使用 QtSvg 渲染，运行时把 ``currentColor`` 替换为调用方颜色；
- 不提供旧图标别名：图标名就是 Iconoir 原名；
- 完整第三方许可见项目根目录 ``THIRD-PARTY.md``。

开发者接口::

    from InstructionX_UIKit import Icon, get_icon, get_pixmap, icon_svg

    get_icon("home", size=24, color="#1677ff", stroke_width=2.0)
    get_pixmap("heart-solid", 32, color="#e5484d")
    icon = Icon("search", size=20).set_color("#1677ff")
    widget.setIcon(icon.qicon())
"""

from PySide6.QtCore import QByteArray, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap

try:
    from PySide6.QtSvg import QSvgRenderer
except ImportError:  # pragma: no cover - 精简 PySide6 分发可能不带 QtSvg
    QSvgRenderer = None

from .iconoir_icons import (
    ICONOIR_ICONS,
    ICONOIR_LICENSE,
    ICONOIR_REGULAR_NAMES,
    ICONOIR_SOLID_NAMES,
    ICONOIR_SOURCE,
    ICONOIR_VERSION,
)
from .theme import T

__all__ = [
    "Icon",
    "get_icon",
    "get_pixmap",
    "icon_svg",
    "icon_names",
    "search_icons",
    "ICON_NAMES",
    "ICONOIR_NAMES",
    "ICONOIR_REGULAR_NAMES",
    "ICONOIR_SOLID_NAMES",
    "ICONOIR_VERSION",
    "ICONOIR_SOURCE",
    "ICONOIR_LICENSE",
]

#: 完整 Iconoir 图标名（Regular 在前、Solid 在后）。
ICONOIR_NAMES = list(ICONOIR_REGULAR_NAMES) + list(ICONOIR_SOLID_NAMES)

#: 完整 Iconoir 名列表（与 ``ICONOIR_NAMES`` 相同，保留公共常量名）。
ICON_NAMES = list(ICONOIR_NAMES)


def _resolve_name(name: str):
    """解析 Iconoir 原名；只接受原名与 ``iconoir:`` / ``io:`` 前缀。"""
    text = str(name or "")
    if text.startswith("iconoir:"):
        text = text.split(":", 1)[1]
    elif text.startswith("io:"):
        text = text.split(":", 1)[1]
    return text if text in ICONOIR_ICONS else None


def _normalize_color(color) -> QColor:
    return color if isinstance(color, QColor) else QColor(
        color or T("color.text.secondary"))


def _normalize_stroke(width) -> float:
    try:
        value = float(width)
    except (TypeError, ValueError):
        value = 1.5
    return max(0.5, min(4.0, value))


def _svg_color(color: QColor) -> str:
    if color.alpha() >= 255:
        return color.name()
    return (f"rgba({color.red()}, {color.green()}, "
            f"{color.blue()}, {color.alpha() / 255:.3f})")


def icon_names(solid=None) -> list:
    """返回 Iconoir 图标名。

    ``solid=None`` 返回全部；``False`` 只返回 Regular；``True`` 只返回 Solid。
    """
    if solid is True:
        return list(ICONOIR_SOLID_NAMES)
    if solid is False:
        return list(ICONOIR_REGULAR_NAMES)
    return list(ICONOIR_NAMES)


def search_icons(query: str = "", solid=None) -> list:
    """按名称子串搜索 Iconoir 图标（大小写不敏感）。"""
    text = str(query or "").strip().lower()
    names = icon_names(solid)
    if not text:
        return names
    return [name for name in names if text in name.lower()]


def icon_svg(name: str, color=None, stroke_width=1.5) -> str:
    """返回替换好颜色/描边宽度的 Iconoir SVG 源码。"""
    iconoir_name = _resolve_name(name)
    if iconoir_name is None:
        raise ValueError(
            f"未知图标: {name!r}；请使用 Iconoir 原名，"
            f"共 {len(ICONOIR_ICONS)} 个（见 ICONOIR_NAMES）")
    source = ICONOIR_ICONS[iconoir_name]
    source = source.replace("currentColor", _svg_color(_normalize_color(color)))
    width = _normalize_stroke(stroke_width)
    return source.replace('stroke-width="1.5"',
                          f'stroke-width="{width:g}"')


def get_pixmap(name: str, size: int = 16, color=None,
               stroke_width=1.5) -> QPixmap:
    """生成图标 QPixmap（尺寸、颜色、描边可配置，2x 设备像素）。"""
    iconoir_name = _resolve_name(name)
    if iconoir_name is None:
        raise ValueError(
            f"未知图标: {name!r}；请使用 Iconoir 原名，"
            f"共 {len(ICONOIR_ICONS)} 个（见 ICONOIR_NAMES）")
    if QSvgRenderer is None:
        raise RuntimeError("当前 PySide6 分发不包含 QtSvg，无法渲染 Iconoir 图标")
    source = icon_svg(iconoir_name, color, stroke_width)
    renderer = QSvgRenderer(QByteArray(source.encode("utf-8")))
    if not renderer.isValid():
        raise ValueError(f"Iconoir SVG 无效: {iconoir_name!r}")
    side = max(int(size), 2)
    dpr = 2.0
    pm = QPixmap(int(round(side * dpr)), int(round(side * dpr)))
    pm.setDevicePixelRatio(dpr)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    # QPainter 在高 DPI pixmap 上使用逻辑坐标，目标矩形不能乘 dpr。
    renderer.render(p, QRectF(0, 0, side, side))
    p.end()
    return pm


def get_icon(name: str, size: int = 16, color=None,
             stroke_width=1.5) -> QIcon:
    """生成图标 QIcon（尺寸、颜色、描边可配置）。"""
    return QIcon(get_pixmap(name, size, color, stroke_width))


class Icon:
    """可复用的图标对象：封装名称、尺寸、颜色和描边宽度。

    用法::

        icon = Icon("home", size=24)
        icon.set_color("#1677ff").set_stroke_width(2.0)
        button.setIcon(icon.qicon())
        label.setPixmap(icon.pixmap())
    """

    def __init__(self, name: str, size: int = 16, color=None,
                 stroke_width=1.5):
        self._name = str(name)
        self._size = max(int(size), 2)
        self._color = _normalize_color(color)
        self._stroke_width = _normalize_stroke(stroke_width)

    @property
    def name(self) -> str:
        return self._name

    def set_name(self, name: str) -> "Icon":
        self._name = str(name)
        return self

    def set_size(self, size: int) -> "Icon":
        self._size = max(int(size), 2)
        return self

    def set_color(self, color) -> "Icon":
        """设置颜色；``color=None`` 恢复当前主题次要文本色。"""
        self._color = _normalize_color(color)
        return self

    def set_stroke_width(self, width) -> "Icon":
        self._stroke_width = _normalize_stroke(width)
        return self

    def color(self) -> QColor:
        """当前颜色（副本）。"""
        return QColor(self._color)

    def size(self) -> int:
        return self._size

    def stroke_width(self) -> float:
        return self._stroke_width

    def svg(self) -> str:
        return icon_svg(self._name, self._color, self._stroke_width)

    def pixmap(self) -> QPixmap:
        return get_pixmap(self._name, self._size, self._color,
                          self._stroke_width)

    def qicon(self) -> QIcon:
        return QIcon(self.pixmap())

    def __repr__(self) -> str:
        return (f"Icon({self._name!r}, size={self._size}, "
                f"color={self._color.name()!r}, "
                f"stroke_width={self._stroke_width:g})")
