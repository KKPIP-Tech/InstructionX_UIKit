# -*- coding: utf-8 -*-
"""包级绘制原语：圆弧。

**为什么不用 ``QPainter.drawArc`` / ``QPainterPath.arcTo``**

实测（在 ``QT_QPA_PLATFORM=offscreen`` 下，用「同进程交替渲染、每轮
``repaint()`` 后取墨迹」的方式逐个调用点量）：Qt 的圆弧图元会把跨度
**截断**——画出来的角度明显小于请求值，且同一参数在重复渲染间不稳定。

| 调用点（跨度）        | drawArc | 折线  |
|-----------------------|---------|-------|
| 表盘进度弧 108°       | 91/108  | 108/108 |
| anim/painted 110°     | 91/110  | 110/110 |
| button 加载 270°      | 187/270 | 271/270 |
| mermaid 280°          | 207/280 | 281/280 |
| icons 刷新 290°       | 227/290 | 291/290 |
| drawer 圆角 90°       | 91/90   | 91/90（正常）|
| spinner 全圆 360°     | 360/360 | 360/360（正常）|

规律：跨度落在 **(90°, 360°) 开区间**内会被截断，90° 与 360° 正常。
分块逐段画同样会被截断，**只有自己按点连线才画得全**。

后果是全包级的：仪表盘进度弧、环形图、旭日图、树图、加载动画、刷新图标
都会出现「弧少一截 / 末端缺口」。因此本模块提供不依赖任何 Qt 圆弧图元的
实现，全包统一走这里。

放在包级（``_draw.py``）而非 ``charts/_utils.py``：``components`` /
``anim`` / ``mermaid`` / ``icons`` 都要用，而 ``components`` 的层级低于
``charts``，不能让下层反向 import 上层。
"""

import math

from PySide6.QtCore import QPointF, QRectF
from PySide6.QtGui import QPainterPath

__all__ = ["arc_points", "draw_arc", "annular_sector"]

#: 允许的弦高误差（px）。圆弧用折线逼近时，弦高即折线与真弧的最大偏离。
_ARC_TOLERANCE = 0.25


def _arc_step(radius: float) -> float:
    """按半径算分段角（度），使弦高误差不超过 ``_ARC_TOLERANCE``。

    半径越小需要的段数越少：小半径用固定角度会浪费，大半径用固定角度
    又会看出折线棱角。
    """
    r = max(abs(float(radius)), 0.5)
    # 弦高 tol = r(1 - cos(θ/2))  →  θ = 2·acos(1 - tol/r)
    ratio = 1.0 - _ARC_TOLERANCE / r
    if ratio <= -1.0:
        return 180.0
    step = 2.0 * math.degrees(math.acos(max(-1.0, ratio)))
    return max(1.0, min(45.0, step))


def arc_points(rect, start_deg: float, span_deg: float):
    """圆弧上的点列（``[(x, y), ...]``），不依赖 Qt 圆弧图元。

    角度沿用 Qt 约定：3 点钟为 0°，**逆时针为正**，设备坐标 Y 轴向下
    （因此角度递增在屏幕上是顺时针）。
    """
    r = min(float(rect.width()), float(rect.height())) / 2.0
    if r <= 0:
        return []
    cx = float(rect.x()) + float(rect.width()) / 2.0
    cy = float(rect.y()) + float(rect.height()) / 2.0
    span = float(span_deg)
    step = _arc_step(r)
    n = max(1, int(math.ceil(abs(span) / step)))
    pts = []
    for i in range(n + 1):
        a = math.radians(float(start_deg) + span * i / n)
        pts.append((cx + math.cos(a) * r, cy + math.sin(a) * r))
    return pts


def draw_arc(p, rect, start_deg: float, span_deg: float, pen=None) -> None:
    """用折线画圆弧（替代 ``QPainter.drawArc``）。

    ``pen`` 为 None 时沿用 painter 当前画笔。首尾点都会画出，配合
    ``Qt.FlatCap`` / ``Qt.RoundCap`` 与原生 ``drawArc`` 的观感一致。
    """
    pts = arc_points(rect, start_deg, span_deg)
    if len(pts) < 2:
        return
    if pen is not None:
        p.setPen(pen)
    prev = QPointF(pts[0][0], pts[0][1])
    for x, y in pts[1:]:
        cur = QPointF(x, y)
        p.drawLine(prev, cur)
        prev = cur


def annular_sector(outer, inner, start_deg: float, span_deg: float):
    """环形扇区路径：外弧正走 + 内弧回走 + 闭合。

    替代 ``QPainterPath`` 的 ``arcMoveTo/arcTo`` 组合（旭日图 / 树图 /
    环形图用）。``inner`` 为 None 时退化为扇形（含圆心闭合）。
    """
    path = QPainterPath()
    o = arc_points(outer, start_deg, span_deg)
    if not o:
        return path
    path.moveTo(o[0][0], o[0][1])
    for x, y in o[1:]:
        path.lineTo(x, y)
    if inner is None:
        cx = float(outer.x()) + float(outer.width()) / 2.0
        cy = float(outer.y()) + float(outer.height()) / 2.0
        path.lineTo(cx, cy)
    else:
        for x, y in arc_points(inner, start_deg + span_deg, -span_deg):
            path.lineTo(x, y)
    path.closeSubpath()
    return path
