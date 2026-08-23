# -*- coding: utf-8 -*-
"""Mermaid 图表渲染（纯 QPainter 实现，供 mermaid 子包与调用方使用）。

支持 Mermaid 语法的三个图型子集：

- **flowchart / graph**：``flowchart TD`` / ``graph LR``（方向 TD/TB/LR/RL/BT），
  节点形状 ``id[文本]`` 矩形、``id(文本)`` 圆角矩形、``id([文本])`` 体育场形、
  ``id{文本}`` 菱形，标签可双引号包围；连线 ``-->``（箭头）、``---``（无箭头）、
  ``-- 文本 -->``（带标签）、``-.->`` / ``-. 文本 .->``（虚线箭头），链式写法
  ``A --> B --> C`` 展开为多条边；分层布局（最长路径定层），整体宽度上限
  800 逻辑 px，超出等比缩小；
- **sequenceDiagram**：``participant A [as 别名]``，消息 ``->>`` 实线箭头、
  ``-->>`` 虚线箭头、``->`` 实线无箭头、``-->`` 虚线无箭头，支持自消息回环；
- **pie**：``pie [title 标题]`` + ``"标签" : 数值`` 数据行（引号可省），
  固定 6 色 ECharts 风调色板，图例在右侧（标签 + 百分比）。

渲染产物为透明底 ``QImage``，2x 超采样（``devicePixelRatio=2``，
QTextDocument / 视图按逻辑尺寸排版），图四周留白 12 逻辑 px。
所有文本尺寸经 QFontMetricsF 实测。解析失败 / 不支持的语法抛出
``ValueError``（中文原因）。``%%`` 注释行与空行跳过。

线程：QPainter 直接在 QImage 上绘制是线程安全的（QPixmap 不行），
本模块的渲染函数可在后台 worker 线程调用（见 hub.py）。
"""

import math
import re

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontMetricsF,
    QImage,
    QPainter,
    QPen,
    QPolygonF,
)

__all__ = ["render_diagram"]

#: 超采样倍率（高 DPI 清晰度；视图尊重 QImage 的 DPR）
_SS = 2
#: 图四周留白（逻辑 px）
_MARGIN = 12.0
#: 层内节点最小间距（逻辑 px）
_NODE_GAP = 24.0
#: 层间最小间距（逻辑 px）
_LAYER_GAP = 60.0
#: 流程图整体宽度上限（逻辑 px，超出等比缩小）
_MAX_WIDTH = 800.0
#: 饼图固定调色板（ECharts 风，6 色轮换）
_PIE_COLORS = ("#5470c6", "#91cc75", "#fac858", "#ee6666", "#73c0de", "#3ba272")
#: style 字典必需键
_STYLE_KEYS = ("text", "line", "node_fill", "node_border", "label_bg", "font_family")
#: 72 dpi（dots per meter），显式固定使 pt 与 px 按 1:1 换算（与测量探针一致）
_DPM_72 = 2835

#: 节点 id（Python re 的 \w 默认含 CJK 等 Unicode 单词字符）
_ID_RE = re.compile(r"\w+")
#: 带标签实线连线：-- 文本 --> / -- 文本 ---
_EDGE_LABELED_RE = re.compile(r"--\s+(.+?)\s*(-->|---)")
#: 带标签虚线连线：-. 文本 .->
_EDGE_LABELED_DOTTED_RE = re.compile(r"-\.\s+(.+?)\s*\.->")
#: 时序图消息（注意算子按长优先排列；参与者 id 用 \w，避免贪婪吞掉算子的 '-'）
_SEQ_MSG_RE = re.compile(r"^(\w+)\s*(-->>|->>|-->|->)\s*(\w+)\s*:\s*(.*)$")
#: 时序图参与者声明
_SEQ_PART_RE = re.compile(r"^participant\s+(\S+)(?:\s+as\s+(.+))?$")
#: 饼图数据行
_PIE_ROW_RE = re.compile(r'^"?(.*?)"?\s*:\s*([0-9]+(?:\.[0-9]+)?)\s*$')
#: 流程图首行
_FLOW_HEAD_RE = re.compile(r"^(flowchart|graph)(?:\s+(\w+))?$")
#: 不支持的流程图关键字（出现时给出可读错误）
_FLOW_UNSUPPORTED = ("subgraph", "classdef", "click", "linkstyle", "direction")
#: 不支持的连线类型前缀
_EDGE_UNSUPPORTED = ("==", "~~", "--x", "--o", "-.-)")


def _families(qss_family: str):
    """把 QSS font-family 字符串解析为字族列表（剔除 generic 族）。"""
    generic = {"sans-serif", "serif", "monospace", "cursive", "fantasy"}
    result = []
    for item in qss_family.split(","):
        name = item.strip().strip('"').strip("'")
        if name and name.lower() not in generic:
            result.append(name)
    return result


def _new_image(width: int, height: int) -> QImage:
    """创建固定 72 dpi 的透明底 QImage（测量探针与最终产物共用参数）。"""
    img = QImage(max(1, width), max(1, height), QImage.Format.Format_ARGB32_Premultiplied)
    img.setDotsPerMeterX(_DPM_72)
    img.setDotsPerMeterY(_DPM_72)
    img.fill(Qt.GlobalColor.transparent)
    return img


class _Measure:
    """文本实测与字体载体（探针 QImage 与最终图同 dpi，保证测量即排版）。

    不持有常驻 QPainter（避免退出期 QPainter 晚于 QApplication 销毁而崩溃），
    测量经 ``QFontMetricsF(font, 探针设备)`` 完成。
    """

    def __init__(self, style: dict, pt: float):
        self._font = QFont()
        self._font.setFamilies(_families(style["font_family"]))
        self._font.setPointSizeF(pt)
        self._bold = QFont(self._font)
        self._bold.setBold(True)
        self._probe = _new_image(8, 8)

    def font(self, bold: bool = False) -> QFont:
        return self._bold if bold else self._font

    def size(self, text: str, bold: bool = False):
        """返回 ``(宽, 高)``（逻辑 px）。"""
        fm = QFontMetricsF(self.font(bold), self._probe)
        return fm.horizontalAdvance(text), float(fm.height())


class _Drawing:
    """布局结果：逻辑尺寸 + 在已缩放 painter 上按逻辑坐标绘制。"""

    def __init__(self, w: float, h: float, draw):
        self.w = w
        self.h = h
        self._draw = draw

    def draw(self, p: QPainter) -> None:
        self._draw(p)


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------

def render_diagram(code: str, style: dict, pt: float) -> QImage:
    """解析 Mermaid 源码并渲染为透明底 ``QImage``（2x 超采样）。

    :param code: Mermaid 源码（支持 flowchart/graph、sequenceDiagram、pie 子集）
    :param style: 样式字典，键见 ``_STYLE_KEYS``（全部为 str）
    :param pt: 逻辑字号（pt）
    :raises ValueError: 解析失败或不支持的语法（中文原因）
    """
    for k in _STYLE_KEYS:
        if k not in style:
            raise ValueError(f"style 缺少必需键: {k!r}")
    lines = []
    for lineno, raw in enumerate(code.splitlines(), 1):
        s = raw.strip()
        if not s or s.startswith("%%"):
            continue  # 空行与 %% 注释行跳过
        lines.append((lineno, s))
    if not lines:
        raise ValueError("Mermaid 源码为空")

    meas = _Measure(style, pt)
    head = lines[0][1]
    low = head.lower()
    if low.startswith("flowchart") or low.startswith("graph"):
        drawing = _layout_flowchart(lines, style, meas)
    elif head.startswith("sequenceDiagram"):
        drawing = _layout_sequence(lines, style, meas)
    elif low.startswith("pie"):
        drawing = _layout_pie(lines, style, meas)
    else:
        keyword = head.split()[0] if head.split() else head
        raise ValueError(
            f"不支持的图类型: {keyword!r}（仅支持 flowchart/graph、sequenceDiagram、pie）")

    # 整体宽度上限 800 逻辑 px，超出等比缩小
    f = min(1.0, _MAX_WIDTH / drawing.w) if drawing.w > 0 else 1.0
    width = drawing.w * f
    height = drawing.h * f
    img = _new_image(math.ceil(width * _SS), math.ceil(height * _SS))
    img.setDevicePixelRatio(float(_SS))
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    # 注意：QPainter 在 DPR=2 的 QImage 上自动按 DPR 缩放坐标，
    # 这里只需叠加 800px 上限的等比缩小因子，不得再乘 _SS
    p.scale(f, f)
    drawing.draw(p)
    p.end()
    return img


# ---------------------------------------------------------------------------
# 绘制辅助
# ---------------------------------------------------------------------------

def _pen(color: str, width: float = 1.5, dashed: bool = False) -> QPen:
    pen = QPen(QColor(color))
    pen.setWidthF(width)
    if dashed:
        pen.setStyle(Qt.PenStyle.DashLine)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    return pen


def _draw_arrow_head(p: QPainter, tip: QPointF, src: QPointF, color: str,
                     size: float = 9.0) -> None:
    """在 tip 处绘制指向 src→tip 方向的实心三角箭头。"""
    ang = math.atan2(tip.y() - src.y(), tip.x() - src.x())
    half = math.radians(24)
    p1 = QPointF(tip.x() - size * math.cos(ang - half),
                 tip.y() - size * math.sin(ang - half))
    p2 = QPointF(tip.x() - size * math.cos(ang + half),
                 tip.y() - size * math.sin(ang + half))
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(color))
    p.drawPolygon(QPolygonF([tip, p1, p2]))


def _draw_centered_text(p: QPainter, meas: _Measure, rect: QRectF, text: str,
                        color: str, bold: bool = False) -> None:
    p.setFont(meas.font(bold))
    p.setPen(_pen(color, 1.0))
    p.drawText(rect, Qt.AlignmentFlag.AlignCenter, text)


# ---------------------------------------------------------------------------
# flowchart / graph
# ---------------------------------------------------------------------------

class _FlowNode:
    __slots__ = ("nid", "label", "shape", "w", "h", "x", "y")

    def __init__(self, nid: str, label: str, shape: str):
        self.nid = nid
        self.label = label
        self.shape = shape
        self.w = 0.0
        self.h = 0.0
        self.x = 0.0
        self.y = 0.0

    @property
    def rect(self) -> QRectF:
        return QRectF(self.x, self.y, self.w, self.h)

    @property
    def center(self) -> QPointF:
        return self.rect.center()


class _FlowEdge:
    __slots__ = ("src", "dst", "kind", "label")

    def __init__(self, src: str, dst: str, kind: str, label):
        self.src = src
        self.dst = dst
        self.kind = kind  # "arrow" | "plain" | "dotted"
        self.label = label


def _unquote(text: str) -> str:
    text = text.strip()
    if len(text) >= 2 and text.startswith('"') and text.endswith('"'):
        return text[1:-1]
    return text


def _parse_flow_node(stmt: str, pos: int, lineno: int):
    """在 pos 处解析 ``id[标签]`` 等节点声明，返回 ``(节点三元组, 新pos)``。"""
    while pos < len(stmt) and stmt[pos].isspace():
        pos += 1
    m = _ID_RE.match(stmt, pos)
    if m is None:
        raise ValueError(f"第 {lineno} 行语法错误（无法识别节点）: {stmt!r}")
    nid = m.group(0)
    pos = m.end()
    while pos < len(stmt) and stmt[pos].isspace():
        pos += 1
    label, shape = nid, "rect"
    rest = stmt[pos:]
    openers = {"([": ("])", "stadium"), "(": (")", "rounded"),
               "[": ("]", "rect"), "{": ("}", "diamond")}
    for opener, (closer, shp) in openers.items():
        if rest.startswith(opener):
            inner_start = pos + len(opener)
            if inner_start < len(stmt) and stmt[inner_start] == '"':
                # 双引号包围的标签（允许内部含括号等标点）
                qend = stmt.find('"', inner_start + 1)
                if qend < 0:
                    raise ValueError(f"第 {lineno} 行语法错误（引号未闭合）: {stmt!r}")
                label = stmt[inner_start + 1:qend]
                end = qend + 1
                while end < len(stmt) and stmt[end].isspace():
                    end += 1
                if not stmt.startswith(closer, end):
                    raise ValueError(f"第 {lineno} 行语法错误（节点括号未闭合）: {stmt!r}")
                pos = end + len(closer)
            else:
                end = stmt.find(closer, inner_start)
                if end < 0:
                    raise ValueError(f"第 {lineno} 行语法错误（节点括号未闭合）: {stmt!r}")
                label = _unquote(stmt[inner_start:end])
                pos = end + len(closer)
            shape = shp
            break
    return (nid, label, shape), pos


def _parse_flow_edge(stmt: str, pos: int, lineno: int):
    """在 pos 处解析连线算子，返回 ``(kind, label, 新pos)``；无连线返回 None。"""
    while pos < len(stmt) and stmt[pos].isspace():
        pos += 1
    rest = stmt[pos:]
    if not rest:
        return None
    if rest.startswith("-.->"):
        return "dotted", None, pos + 4
    if rest.startswith("-->"):
        return "arrow", None, pos + 3
    if rest.startswith("---"):
        return "plain", None, pos + 3
    m = _EDGE_LABELED_DOTTED_RE.match(rest)
    if m is not None:
        return "dotted", _unquote(m.group(1)), pos + m.end()
    m = _EDGE_LABELED_RE.match(rest)
    if m is not None:
        kind = "arrow" if m.group(2) == "-->" else "plain"
        return kind, _unquote(m.group(1)), pos + m.end()
    for bad in _EDGE_UNSUPPORTED:
        if rest.startswith(bad):
            raise ValueError(
                f"第 {lineno} 行不支持的连线类型: {bad!r}"
                f"（仅支持 -->、---、-- 文本 -->、-.->）")
    raise ValueError(f"第 {lineno} 行语法错误（无法识别连线）: {stmt!r}")


def _layout_flowchart(lines, style: dict, meas: _Measure) -> _Drawing:
    m = _FLOW_HEAD_RE.match(lines[0][1])
    direction = (m.group(2) or "TD").upper()
    if direction not in ("TD", "TB", "LR", "RL", "BT"):
        raise ValueError(f"未知的流程图方向: {direction!r}（支持 TD/TB/LR/RL/BT）")
    horizontal = direction in ("LR", "RL")
    reversed_dir = direction in ("RL", "BT")

    nodes = {}   # id -> _FlowNode（插入序）
    edges = []   # _FlowEdge

    def ensure_node(spec):
        nid, label, shape = spec
        if nid in nodes:
            node = nodes[nid]
            if label != nid or shape != "rect":
                # 显式声明覆盖隐式声明（边引用裸 id 时标签即 id）
                node.label, node.shape = label, shape
            return node
        node = _FlowNode(nid, label, shape)
        nodes[nid] = node
        return node

    for lineno, line in lines[1:]:
        for stmt in line.split(";"):
            stmt = stmt.strip()
            if not stmt:
                continue
            if stmt.lower().split(None, 1)[0] in _FLOW_UNSUPPORTED:
                raise ValueError(f"第 {lineno} 行不支持的流程图语法: {stmt!r}")
            spec, pos = _parse_flow_node(stmt, 0, lineno)
            prev = ensure_node(spec)
            while True:
                while pos < len(stmt) and stmt[pos].isspace():
                    pos += 1
                if pos >= len(stmt):
                    break
                kind, elabel, pos = _parse_flow_edge(stmt, pos, lineno)
                spec, pos = _parse_flow_node(stmt, pos, lineno)
                nxt = ensure_node(spec)
                edges.append(_FlowEdge(prev.nid, nxt.nid, kind, elabel))
                prev = nxt
    if not nodes:
        raise ValueError("流程图无任何节点")

    # ---- 节点尺寸（按形状放大量文本实测尺寸）----
    for node in nodes.values():
        tw, th = meas.size(node.label)
        if node.shape == "stadium":
            node.w, node.h = tw + 32, th + 14
        elif node.shape == "diamond":
            # 菱形内接矩形为 (w/2, h/2)，需双倍尺寸容纳文本
            node.w, node.h = 2 * tw + 28, 2 * th + 20
        else:  # rect / rounded
            node.w, node.h = tw + 24, th + 14

    # ---- 分层（最长路径定层，环以层数上限防护）----
    layer_of = {nid: 0 for nid in nodes}
    cap = len(nodes)
    for _ in range(cap):
        for e in edges:
            if layer_of[e.dst] < layer_of[e.src] + 1:
                layer_of[e.dst] = min(layer_of[e.src] + 1, cap - 1)
    layers = {}
    for nid, lv in layer_of.items():
        layers.setdefault(lv, []).append(nid)
    ordered = [layers[lv] for lv in sorted(layers)]
    if reversed_dir:
        ordered.reverse()

    # ---- 层间距需容纳边标签 ----
    label_sizes = [meas.size(e.label) for e in edges if e.label]
    if horizontal:
        max_label = max((s[0] for s in label_sizes), default=0.0)
    else:
        max_label = max((s[1] for s in label_sizes), default=0.0)
    layer_gap = max(_LAYER_GAP, max_label + 32)

    # ---- 坐标 ----
    def extent(nid_list, along):
        vals = [(nodes[nid].w if along == "x" else nodes[nid].h) for nid in nid_list]
        return sum(vals) + _NODE_GAP * (len(vals) - 1)

    axis = "x" if not horizontal else "y"
    band = "h" if not horizontal else "w"   # 层带厚度
    span = max(extent(ids, axis) for ids in ordered)
    pos = _MARGIN
    for ids in ordered:
        thickness = max(getattr(nodes[nid], band) for nid in ids)
        cursor = _MARGIN + (span - extent(ids, axis)) / 2
        for nid in ids:
            node = nodes[nid]
            if axis == "x":
                node.x = cursor
                node.y = pos + (thickness - node.h) / 2
                cursor += node.w + _NODE_GAP
            else:
                node.y = cursor
                node.x = pos + (thickness - node.w) / 2
                cursor += node.h + _NODE_GAP
        pos += thickness + layer_gap
    total = pos - layer_gap + _MARGIN
    if not horizontal:
        total_w, total_h = _MARGIN * 2 + span, total
    else:
        total_w, total_h = total, _MARGIN * 2 + span

    # ---- 跨层连线的侧边绕行通道（避免直线穿过中间层节点）----
    skip_edges = [e for e in edges
                  if e.src != e.dst and abs(layer_of[e.src] - layer_of[e.dst]) > 1]
    channel = None
    if skip_edges:
        if not horizontal:
            max_lw = max((meas.size(e.label)[0] for e in skip_edges if e.label),
                         default=0.0)
            channel = max(n.x + n.w for n in nodes.values()) + 24
            total_w = max(total_w, channel + 6 + max_lw + _MARGIN)
        else:
            max_lh = max((meas.size(e.label)[1] for e in skip_edges if e.label),
                         default=0.0)
            channel = max(n.y + n.h for n in nodes.values()) + 24
            total_h = max(total_h, channel + 6 + max_lh + _MARGIN)

    def boundary(node: _FlowNode, toward: QPointF) -> QPointF:
        """从节点中心朝 toward 方向求形状边界点（菱形按真实边界，其余按外接矩形）。"""
        c = node.center
        dx, dy = toward.x() - c.x(), toward.y() - c.y()
        if dx == 0 and dy == 0:
            return c
        a, b = node.w / 2, node.h / 2
        if node.shape == "diamond":
            t = 1.0 / (abs(dx) / a + abs(dy) / b)
        else:
            tx = a / abs(dx) if dx else math.inf
            ty = b / abs(dy) if dy else math.inf
            t = min(tx, ty)
        return QPointF(c.x() + dx * t, c.y() + dy * t)

    def edge_points(e: _FlowEdge):
        """连线的折线点列（跨层边经侧边通道绕行）。"""
        src, dst = nodes[e.src], nodes[e.dst]
        ps = boundary(src, dst.center)
        pt_ = boundary(dst, src.center)
        pts = [ps]
        skipping = abs(layer_of[e.src] - layer_of[e.dst]) > 1
        if skipping and channel is not None:
            if not horizontal:
                sy = 20.0 if pt_.y() > ps.y() else -20.0
                pts += [QPointF(ps.x(), ps.y() + sy),
                        QPointF(channel, ps.y() + sy),
                        QPointF(channel, pt_.y() - sy),
                        QPointF(pt_.x(), pt_.y() - sy)]
            else:
                sx = 20.0 if pt_.x() > ps.x() else -20.0
                pts += [QPointF(ps.x() + sx, ps.y()),
                        QPointF(ps.x() + sx, channel),
                        QPointF(pt_.x() - sx, channel),
                        QPointF(pt_.x() - sx, pt_.y())]
        pts.append(pt_)
        return pts, skipping

    def draw(p: QPainter) -> None:
        line_color = style["line"]
        # 1) 连线（先画线，节点填充覆盖端点，箭头后补在边界处）
        for e in edges:
            src = nodes[e.src]
            p.setPen(_pen(line_color, 1.5, e.kind == "dotted"))
            p.setBrush(Qt.BrushStyle.NoBrush)
            if e.src == e.dst:
                # 自环防护：节点右侧画小回环，避免崩溃
                r = QRectF(src.x + src.w - 4, src.y + src.h / 2 - 10, 26, 20)
                p.drawArc(r, 40 * 16, 280 * 16)
                if e.kind != "plain":
                    tip = QPointF(r.left() + 2, r.center().y() + 8)
                    _draw_arrow_head(p, tip, QPointF(tip.x(), tip.y() - 6), line_color)
                continue
            pts, _skipping = edge_points(e)
            p.drawPolyline(QPolygonF(pts))
            if e.kind != "plain":
                _draw_arrow_head(p, pts[-1], pts[-2], line_color)
        # 2) 节点
        for node in nodes.values():
            r = node.rect
            p.setPen(_pen(style["node_border"], 1.5))
            p.setBrush(QColor(style["node_fill"]))
            if node.shape == "rounded":
                p.drawRoundedRect(r, 6, 6)
            elif node.shape == "stadium":
                p.drawRoundedRect(r, r.height() / 2, r.height() / 2)
            elif node.shape == "diamond":
                c = node.center
                p.drawPolygon(QPolygonF([
                    QPointF(c.x(), r.top()), QPointF(r.right(), c.y()),
                    QPointF(c.x(), r.bottom()), QPointF(r.left(), c.y()),
                ]))
            else:
                p.drawRect(r)
            _draw_centered_text(p, meas, r, node.label, style["text"])
        # 3) 边标签（最后绘制 + label_bg 衬底，保证不被节点遮挡；
        #    跨层边的标签放在绕行通道旁）
        for e in edges:
            if not e.label or e.src == e.dst:
                continue
            pts, skipping = edge_points(e)
            ps, pt_ = pts[0], pts[-1]
            tw, th = meas.size(e.label)
            if skipping:
                if not horizontal:
                    sy = 20.0 if pt_.y() > ps.y() else -20.0
                    mid_y = (ps.y() + sy + pt_.y() - sy) / 2
                    bg = QRectF(channel + 6, mid_y - th / 2 - 3, tw + 10, th + 6)
                else:
                    sx = 20.0 if pt_.x() > ps.x() else -20.0
                    mid_x = (ps.x() + sx + pt_.x() - sx) / 2
                    bg = QRectF(mid_x - tw / 2 - 5, channel + 6, tw + 10, th + 6)
            else:
                mid = QPointF((ps.x() + pt_.x()) / 2, (ps.y() + pt_.y()) / 2)
                bg = QRectF(mid.x() - tw / 2 - 5, mid.y() - th / 2 - 3,
                            tw + 10, th + 6)
            p.setPen(_pen(style["node_border"], 1.0))
            p.setBrush(QColor(style["label_bg"]))
            p.drawRoundedRect(bg, 3, 3)
            _draw_centered_text(p, meas, bg, e.label, style["text"])

    return _Drawing(total_w, total_h, draw)


# ---------------------------------------------------------------------------
# sequenceDiagram
# ---------------------------------------------------------------------------

class _SeqMessage:
    __slots__ = ("src", "dst", "dashed", "arrow", "text", "y")

    def __init__(self, src, dst, dashed, arrow, text):
        self.src = src
        self.dst = dst
        self.dashed = dashed
        self.arrow = arrow
        self.text = text
        self.y = 0.0


def _layout_sequence(lines, style: dict, meas: _Measure) -> _Drawing:
    order = []     # 参与者 id（首次出现序）
    names = {}     # id -> 显示名
    messages = []

    def ensure(pid: str) -> None:
        if pid not in names:
            names[pid] = pid
            order.append(pid)

    for lineno, line in lines[1:]:
        m = _SEQ_PART_RE.match(line)
        if m is not None:
            ensure(m.group(1))
            if m.group(2):
                names[m.group(1)] = m.group(2).strip()
            continue
        m = _SEQ_MSG_RE.match(line)
        if m is not None:
            src, op, dst, text = m.groups()
            ensure(src)
            ensure(dst)
            dashed = op.startswith("--")
            arrow = op.endswith(">>")
            messages.append(_SeqMessage(src, dst, dashed, arrow, text.strip()))
            continue
        keyword = line.split(None, 1)[0] if line.split() else line
        raise ValueError(
            f"第 {lineno} 行不支持的时序图语法: {keyword!r}"
            f"（仅支持 participant 与 ->>/-->>/->/--> 消息）")
    if not order:
        raise ValueError("时序图无任何参与者")
    if not messages:
        raise ValueError("时序图无任何消息")

    # ---- 参与者框尺寸 ----
    box_w, box_h = {}, 0.0
    for pid in order:
        tw, th = meas.size(names[pid])
        box_w[pid] = max(64.0, tw + 24)
        box_h = max(box_h, th + 14)

    # ---- 生命线 x 坐标（最小间距 + 消息文本宽度推挤，两遍收敛）----
    x = {order[0]: _MARGIN + box_w[order[0]] / 2}
    for i in range(1, len(order)):
        prev, cur = order[i - 1], order[i]
        x[cur] = x[prev] + box_w[prev] / 2 + box_w[cur] / 2 + 56
    idx = {pid: i for i, pid in enumerate(order)}
    for _ in range(2):
        for msg in messages:
            if msg.src == msg.dst:
                continue
            i, j = idx[msg.src], idx[msg.dst]
            if i > j:
                i, j = j, i
            tw, _ = meas.size(msg.text)
            need = tw + 56
            if x[order[j]] - x[order[i]] < need:
                delta = need - (x[order[j]] - x[order[i]])
                for pid in order[j:]:
                    x[pid] += delta

    # ---- 消息纵向排布 ----
    y = _MARGIN + box_h + 40
    for msg in messages:
        msg.y = y
        y += 56 if msg.src == msg.dst else 40
    lifeline_end = y - 40 + 28
    total_h = lifeline_end + _MARGIN

    loop = 40.0  # 自消息回环宽度
    right_most = max(
        x[pid] + box_w[pid] / 2 + (loop if any(
            m.src == m.dst == pid for m in messages) else 0.0)
        for pid in order)
    total_w = right_most + _MARGIN

    def draw(p: QPainter) -> None:
        # 1) 生命线（虚线）
        p.setPen(_pen(style["line"], 1.2, dashed=True))
        p.setBrush(Qt.BrushStyle.NoBrush)
        for pid in order:
            p.drawLine(QPointF(x[pid], _MARGIN + box_h),
                       QPointF(x[pid], lifeline_end))
        # 2) 参与者框
        for pid in order:
            r = QRectF(x[pid] - box_w[pid] / 2, _MARGIN, box_w[pid], box_h)
            p.setPen(_pen(style["node_border"], 1.5))
            p.setBrush(QColor(style["node_fill"]))
            p.drawRoundedRect(r, 6, 6)
            _draw_centered_text(p, meas, r, names[pid], style["text"])
        # 3) 消息
        for msg in messages:
            p.setPen(_pen(style["line"], 1.5, msg.dashed))
            p.setBrush(Qt.BrushStyle.NoBrush)
            if msg.src == msg.dst:
                sx = x[msg.src]
                p.drawLine(QPointF(sx, msg.y), QPointF(sx + loop, msg.y))
                p.drawLine(QPointF(sx + loop, msg.y), QPointF(sx + loop, msg.y + 16))
                p.drawLine(QPointF(sx + loop, msg.y + 16), QPointF(sx + 2, msg.y + 16))
                if msg.arrow:
                    _draw_arrow_head(p, QPointF(sx + 2, msg.y + 16),
                                     QPointF(sx + 12, msg.y + 16), style["line"])
                tw, th = meas.size(msg.text)
                tr = QRectF(sx + loop / 2 - tw / 2 - 4, msg.y - th - 8,
                            tw + 8, th + 4)
            else:
                sx, dx = x[msg.src], x[msg.dst]
                tip_x = dx - (2 if dx > sx else -2)
                p.drawLine(QPointF(sx, msg.y), QPointF(tip_x, msg.y))
                if msg.arrow:
                    _draw_arrow_head(p, QPointF(tip_x, msg.y),
                                     QPointF(sx, msg.y), style["line"])
                tw, th = meas.size(msg.text)
                mid = (sx + dx) / 2
                tr = QRectF(mid - tw / 2 - 4, msg.y - th - 8, tw + 8, th + 4)
            # 消息文字（label_bg 衬底，避免压生命线）
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(style["label_bg"]))
            p.drawRect(tr)
            _draw_centered_text(p, meas, tr, msg.text, style["text"])

    return _Drawing(total_w, total_h, draw)


# ---------------------------------------------------------------------------
# pie
# ---------------------------------------------------------------------------

def _layout_pie(lines, style: dict, meas: _Measure) -> _Drawing:
    head = lines[0][1]
    title = ""
    m = re.match(r"^pie(?:\s+title\s+(.+))?$", head)
    if m is None:
        raise ValueError(f"第 {lines[0][0]} 行语法错误: {head!r}")
    if m.group(1):
        title = m.group(1).strip()

    data = []
    for lineno, line in lines[1:]:
        m = _PIE_ROW_RE.match(line)
        if m is None:
            raise ValueError(
                f"第 {lineno} 行语法错误（饼图数据行应为 \"标签\" : 数值）: {line!r}")
        value = float(m.group(2))
        if value > 0:
            data.append((m.group(1).strip(), value))
    if not data:
        raise ValueError("饼图无有效数据（需要至少一行 \"标签\" : 正数）")

    total = sum(v for _, v in data)
    pie_d = 200.0

    title_w = title_h = 0.0
    if title:
        title_w, title_h = meas.size(title, bold=True)
        title_h += 8

    # 图例行：色块 + "标签 百分比"
    rows = []
    legend_w = 0.0
    for label, value in data:
        text = f"{label} {value / total * 100:.1f}%"
        tw, th = meas.size(text)
        rows.append((label, text, tw))
        legend_w = max(legend_w, tw + 10 + 8)  # 色块 10 + 间隔 8
    row_h = max(18.0, meas.size("Ag")[1] + 4)
    legend_h = row_h * len(rows)

    body_h = max(pie_d, legend_h)
    total_w = _MARGIN * 2 + max(pie_d + 28 + legend_w, title_w)
    total_h = _MARGIN * 2 + title_h + (8 if title else 0) + body_h

    pie_x = _MARGIN
    pie_y = _MARGIN + title_h + (8 if title else 0) + (body_h - pie_d) / 2
    legend_x = _MARGIN + pie_d + 28
    legend_y = _MARGIN + title_h + (8 if title else 0) + (body_h - legend_h) / 2

    def draw(p: QPainter) -> None:
        if title:
            _draw_centered_text(p, meas,
                                QRectF(0, _MARGIN, total_w, title_h),
                                title, style["text"], bold=True)
        rect = QRectF(pie_x, pie_y, pie_d, pie_d)
        start = 90 * 16  # 从正上方开始，顺时针（Qt 负角度）
        for i, (label, value) in enumerate(data):
            span = -round(value / total * 360 * 16)
            if i == len(data) - 1:
                span = (90 - 360) * 16 - start  # 末片补齐到整圆，消除累计误差
            p.setPen(_pen(style["label_bg"], 1.0))
            p.setBrush(QColor(_PIE_COLORS[i % len(_PIE_COLORS)]))
            p.drawPie(rect, start, span)
            start += span
        for i, (label, text, tw) in enumerate(rows):
            cy = legend_y + i * row_h
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(_PIE_COLORS[i % len(_PIE_COLORS)]))
            p.drawRoundedRect(QRectF(legend_x, cy + (row_h - 10) / 2, 10, 10), 2, 2)
            tr = QRectF(legend_x + 18, cy, tw + 4, row_h)
            p.setFont(meas.font())
            p.setPen(_pen(style["text"], 1.0))
            p.drawText(tr, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                       text)

    return _Drawing(total_w, total_h, draw)
