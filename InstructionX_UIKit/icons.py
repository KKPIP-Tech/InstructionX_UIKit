# -*- coding: utf-8 -*-
"""轻量矢量图标集（QPainter 运行时绘制，无外部资源依赖）。

统一视觉规范（对齐 Feather / Lucide 线性图标）：

- 24px 设计网格：所有路径坐标按 24x24 定义，渲染时缩放到目标尺寸；
- 1.5px 描边（网格坐标系），圆角端点 / 圆角连接；
- 抗锯齿绘制，透明背景；
- 颜色由调用方传入（主题感知），缺省取 ``T("color.text.secondary")``。

对外 API::

    from InstructionX_UIKit.icons import get_icon, ICON_NAMES

    icon = get_icon("home")                                  # 16px，次要文本色
    icon = get_icon("settings", size=20, color="#1677ff")    # 指定尺寸与颜色
    icon = get_icon("check", color=T("color.success"))       # 令牌色
"""

import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (
    QColor,
    QIcon,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
)

from .theme import T

__all__ = ["get_icon", "ICON_NAMES"]

#: 设计网格边长（图标坐标均以 24x24 定义）
_GRID = 24.0
#: 网格坐标系下的描边宽度（px）
_STROKE = 1.5


# ---------------------------------------------------------------------------
# 绘制辅助
# ---------------------------------------------------------------------------

def _pen(color: QColor) -> QPen:
    """统一描边画笔：1.5px、圆角端点与连接。"""
    pen = QPen(color)
    pen.setWidthF(_STROKE)
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    return pen


def _dot(p: QPainter, color: QColor, x: float, y: float, r: float = 1.1) -> None:
    """实心圆点（info / warning 图标的感叹点）。"""
    p.save()
    p.setPen(Qt.NoPen)
    p.setBrush(color)
    p.drawEllipse(QPointF(x, y), r, r)
    p.restore()


def _line(p: QPainter, x1, y1, x2, y2) -> None:
    p.drawLine(QPointF(x1, y1), QPointF(x2, y2))


def _polyline(p: QPainter, pts) -> None:
    p.drawPolyline([QPointF(x, y) for x, y in pts])


def _rect(p: QPainter, x, y, w, h, r=0.0) -> None:
    rect = QRectF(x, y, w, h)
    if r > 0:
        p.drawRoundedRect(rect, r, r)
    else:
        p.drawRect(rect)


# ---------------------------------------------------------------------------
# 各图标路径（painter 已按 24 网格缩放，画笔/画刷颜色已就绪）
# ---------------------------------------------------------------------------

def _draw_home(p: QPainter, color: QColor) -> None:
    """房子：屋顶折线 + 墙体 + 门。"""
    _polyline(p, [(3.5, 11), (12, 3.8), (20.5, 11)])
    _polyline(p, [(5.5, 9.6), (5.5, 20), (18.5, 20), (18.5, 9.6)])
    _rect(p, 10, 14, 4, 6)


def _draw_chart(p: QPainter, color: QColor) -> None:
    """柱状图：三根递增柱 + 基线。"""
    _line(p, 4, 20, 20, 20)
    _line(p, 7, 20, 7, 13)
    _line(p, 12, 20, 12, 8.5)
    _line(p, 17, 20, 17, 4.5)


def _draw_layout(p: QPainter, color: QColor) -> None:
    """布局：外框 + 左栏 + 右侧上下分区。"""
    _rect(p, 3.5, 4, 17, 16, 2)
    _line(p, 9.5, 4, 9.5, 20)
    _line(p, 9.5, 11, 20.5, 11)


def _draw_component(p: QPainter, color: QColor) -> None:
    """方块组合：一个实心块 + 三个描边块。"""
    p.save()
    p.setBrush(color)
    _rect(p, 4, 4, 7, 7, 1.5)
    p.restore()
    _rect(p, 13, 4, 7, 7, 1.5)
    _rect(p, 4, 13, 7, 7, 1.5)
    _rect(p, 13, 13, 7, 7, 1.5)


def _draw_animation(p: QPainter, color: QColor) -> None:
    """播放 / 闪电：一道闪电折线。"""
    _polyline(p, [(13, 3), (6, 13.2), (11, 13.2), (10.2, 21), (18, 10.4), (13, 10.4)])


def _draw_settings(p: QPainter, color: QColor) -> None:
    """齿轮：外环 + 八根轮齿 + 中心毂。"""
    p.drawEllipse(QPointF(12, 12), 5.6, 5.6)
    for i in range(8):
        a = math.radians(i * 45)
        ca, sa = math.cos(a), math.sin(a)
        _line(p, 12 + 5.6 * ca, 12 + 5.6 * sa, 12 + 8.4 * ca, 12 + 8.4 * sa)
    p.drawEllipse(QPointF(12, 12), 2.1, 2.1)


def _draw_user(p: QPainter, color: QColor) -> None:
    """人像：头部圆 + 肩部弧线。"""
    p.drawEllipse(QPointF(12, 8), 3.4, 3.4)
    path = QPainterPath(QPointF(5, 20))
    path.quadTo(QPointF(5, 14.8), QPointF(12, 14.8))
    path.quadTo(QPointF(19, 14.8), QPointF(19, 20))
    p.drawPath(path)


def _draw_search(p: QPainter, color: QColor) -> None:
    """放大镜：镜片圆 + 手柄。"""
    p.drawEllipse(QPointF(10.8, 10.8), 6.2, 6.2)
    _line(p, 15.3, 15.3, 20, 20)


def _draw_menu(p: QPainter, color: QColor) -> None:
    """汉堡菜单：三条横线。"""
    for y in (6, 12, 18):
        _line(p, 4, y, 20, y)


def _draw_arrow_left(p: QPainter, color: QColor) -> None:
    """左箭头（折角）。"""
    _polyline(p, [(14.5, 5), (6.5, 12), (14.5, 19)])


def _draw_arrow_right(p: QPainter, color: QColor) -> None:
    """右箭头（折角）。"""
    _polyline(p, [(9.5, 5), (17.5, 12), (9.5, 19)])


def _draw_plus(p: QPainter, color: QColor) -> None:
    """加号。"""
    _line(p, 12, 5, 12, 19)
    _line(p, 5, 12, 19, 12)


def _draw_close(p: QPainter, color: QColor) -> None:
    """关闭（叉）。"""
    _line(p, 6, 6, 18, 18)
    _line(p, 18, 6, 6, 18)


def _draw_info(p: QPainter, color: QColor) -> None:
    """信息：圆圈 + i。"""
    p.drawEllipse(QPointF(12, 12), 8.4, 8.4)
    _dot(p, color, 12, 7.9)
    _line(p, 12, 11.2, 12, 16.4)


def _draw_warning(p: QPainter, color: QColor) -> None:
    """警告：圆角三角 + 感叹号。"""
    path = QPainterPath(QPointF(12, 4.6))
    path.lineTo(QPointF(20.8, 19))
    path.lineTo(QPointF(3.2, 19))
    path.closeSubpath()
    p.drawPath(path)
    _line(p, 12, 10, 12, 14.4)
    _dot(p, color, 12, 17)


def _draw_check(p: QPainter, color: QColor) -> None:
    """对勾。"""
    _polyline(p, [(4.8, 12.6), (10, 17.6), (19.2, 7)])


#: 图标注册表：名称 -> 绘制函数
_DRAWERS = {
    "home": _draw_home,
    "chart": _draw_chart,
    "layout": _draw_layout,
    "component": _draw_component,
    "animation": _draw_animation,
    "settings": _draw_settings,
    "user": _draw_user,
    "search": _draw_search,
    "menu": _draw_menu,
    "arrow_left": _draw_arrow_left,
    "arrow_right": _draw_arrow_right,
    "plus": _draw_plus,
    "close": _draw_close,
    "info": _draw_info,
    "warning": _draw_warning,
    "check": _draw_check,
}

#: 全部可用图标名（注册表键的有序列表）
ICON_NAMES = list(_DRAWERS)


def get_icon(name: str, size: int = 16, color=None) -> QIcon:
    """按名称生成矢量图标。

    参数:
        name: 图标名，见 ``ICON_NAMES``。
        size: 输出边长（px），默认 16。
        color: 描边颜色，``str``（如 ``"#5c6b7a"``）或 ``QColor``；
            缺省取当前主题 ``color.text.secondary``。

    返回:
        ``QIcon``（抗锯齿、透明背景；按 2x 设备像素比绘制，高清屏不糊）。
    """
    drawer = _DRAWERS.get(name)
    if drawer is None:
        raise ValueError(f"未知图标: {name!r}，可用: {ICON_NAMES}")
    size = max(int(size), 2)
    qcolor = color if isinstance(color, QColor) else QColor(color or T("color.text.secondary"))

    dpr = 2.0  # 固定 2x 超采样，保证任意尺寸下边缘平滑
    pm = QPixmap(int(size * dpr), int(size * dpr))
    pm.setDevicePixelRatio(dpr)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.scale(size / _GRID, size / _GRID)
    p.setPen(_pen(qcolor))
    p.setBrush(Qt.NoBrush)
    drawer(p, qcolor)
    p.end()
    return QIcon(pm)
