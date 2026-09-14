# -*- coding: utf-8 -*-
"""行号槽（CE_SPEC §2.1）。

绘制内容（从左到右）：诊断着色条 | 断点圆点 | 行号 | 标记列 | 折叠箭头。

- 行号模式：``"on"``（绝对）/ ``"off"``（隐藏整条槽）/ ``"relative"``
  （其他行显示与当前行的距离，当前行显示绝对行号）；当前行号高亮加粗。
- 双列行号（``dual_line_label_provider``，VS Code 内联 diff 样式）：
  左列 = 原始文件行号、右列 = 修改文件行号，``+`` 后缀 success 色、
  ``−`` 后缀 danger 色；槽宽随之加宽。
- 行标记（``line_marker_provider``）：行号右侧标记列绘制 ``+`` /
  ``−`` 等符号，``+`` success 色、``−`` danger 色（并排 diff）。
- 断点：点击槽（非折叠箭头区）切换断点；圆点用 danger 色。
- 折叠箭头：折叠起始行绘制三角箭头，hover 时显现，点击切换折叠。
- 诊断着色条：该行最重诊断级别的竖条。

透明前科防御：``setAutoFillBackground(False)`` + 实例级透明 QSS，
背景全部由 ``paintEvent`` 自绘。
"""

from PySide6.QtCore import QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen

from PySide6.QtWidgets import QWidget

from ..theme import T
from .regions import SEVERITY_COLORS

__all__ = ["Gutter"]

#: 布局常量（px）
_DIAG_W = 3
_BP_ZONE = 18
_FOLD_ZONE = 14
_PAD = 6


class Gutter(QWidget):
    """行号槽控件。

    参数:
        editor: 所属 ``CodeEditor``（读取其文本区 / 断点 / 折叠状态）。
    """

    #: 某行断点被点击切换 ``(line 1-based)``
    breakpoint_clicked = Signal(int)
    #: 某行折叠箭头被点击 ``(line 1-based)``
    fold_clicked = Signal(int)

    def __init__(self, editor, parent=None):
        super().__init__(parent or editor)
        self._editor = editor
        self._hover_line = -1
        self.setAutoFillBackground(False)
        self.setStyleSheet("background: transparent;")
        self.setMouseTracking(True)

    # ------------------------------------------------------------------
    # 尺寸
    # ------------------------------------------------------------------
    def _mark_w(self, fm) -> int:
        """行标记列宽（未设置标记 provider 时 0）。"""
        if getattr(self._editor, "line_marker_provider", lambda: None)() is None:
            return 0
        return fm.horizontalAdvance("+") + 4

    def desired_width(self) -> int:
        """按行号位数与模式计算槽宽；模式 ``off`` 返回 0。"""
        ed = self._editor
        if ed.line_number_mode() == "off":
            return 0
        digits = max(2, len(str(max(1, ed.text_area().document().blockCount()))))
        fm = ed.text_area().fontMetrics()
        dual_fn = getattr(ed, "dual_line_label_provider", lambda: None)()
        if dual_fn is not None:
            # 双列行号（VS Code 内联 diff）：每列预留 1 字符放 +/− 后缀
            col_w = fm.horizontalAdvance("9") * (digits + 1)
            return (
                _DIAG_W + _BP_ZONE + col_w * 2 + _PAD * 3 + _FOLD_ZONE
            )
        return (
            _DIAG_W + _BP_ZONE + fm.horizontalAdvance("9") * digits
            + self._mark_w(fm) + _FOLD_ZONE + _PAD * 2
        )

    def sizeHint(self):
        return QSize(self.desired_width(), 100)

    def refresh(self) -> None:
        """重新计算宽度并重绘。"""
        w = self.desired_width()
        self.setFixedWidth(max(0, w))
        self.setVisible(w > 0)
        self.update()

    # ------------------------------------------------------------------
    # 绘制
    # ------------------------------------------------------------------
    def _visible_blocks(self):
        """产出 ``(block, top, height)``：文本区当前可见的块几何。"""
        ta = self._editor.text_area()
        block = ta.firstVisibleBlock()
        offset = ta.contentOffset()
        viewport_h = ta.viewport().height()
        while block.isValid():
            geo = ta.blockBoundingGeometry(block).translated(offset)
            top = geo.top()
            height = geo.height()
            if top > viewport_h:
                break
            if block.isVisible() and top + height >= 0:
                yield block, top, height
            block = block.next()

    def paintEvent(self, event):  # noqa: N802 - Qt 命名
        ed = self._editor
        if ed.line_number_mode() == "off":
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        # 背景
        p.fillRect(self.rect(), QColor(T("color.bg.subtle")))
        # 右侧分隔线
        p.setPen(QColor(T("color.border")))
        p.drawLine(self.width() - 1, 0, self.width() - 1, self.height())

        mode = ed.line_number_mode()
        current = ed.cursor_position()[0]
        bps = ed.breakpoints()
        fold_points = ed.fold_points()
        folded = ed.folded_lines()
        diag = ed.diagnostic_lines()
        fm = ed.text_area().fontMetrics()
        digits = max(2, len(str(max(1, ed.text_area().document().blockCount()))))
        num_w = fm.horizontalAdvance("9") * digits
        dual_fn = getattr(ed, "dual_line_label_provider", lambda: None)()
        marker_fn = getattr(ed, "line_marker_provider", lambda: None)()
        mark_w = self._mark_w(fm)
        if dual_fn is not None:
            col_w = fm.horizontalAdvance("9") * (digits + 1)
            left_rect_x = _DIAG_W + _BP_ZONE
            right_rect_x = left_rect_x + col_w + _PAD
            fold_x = right_rect_x + col_w + _PAD + _FOLD_ZONE / 2
        else:
            num_right = _DIAG_W + _BP_ZONE + num_w + _PAD
            fold_x = num_right + mark_w + _FOLD_ZONE / 2

        p.setFont(ed.text_area().font())
        for block, top, height in self._visible_blocks():
            line = block.blockNumber() + 1
            cy = top + height / 2
            # 诊断着色条
            sev = diag.get(line)
            if sev:
                p.fillRect(
                    QRectF(0, top, _DIAG_W, height),
                    QColor(T(SEVERITY_COLORS.get(sev, "color.primary"))),
                )
            # 断点圆点
            if line in bps:
                p.setPen(Qt.NoPen)
                p.setBrush(QColor(T("color.danger")))
                r = min(5.0, height / 4)
                p.drawEllipse(QRectF(_DIAG_W + _BP_ZONE / 2 - r, cy - r,
                                     2 * r, 2 * r))
            # 行号（自定义 provider 优先；返回 None 的行不绘制——占位行）
            if dual_fn is not None:
                self._paint_dual_labels(p, dual_fn, line, current, top,
                                        height, left_rect_x, right_rect_x,
                                        col_w)
            else:
                label_fn = ed.line_label_provider()
                if label_fn is not None:
                    label = label_fn(line)
                    text = None if label is None else str(label)
                elif mode == "relative" and line != current:
                    text = str(abs(line - current))
                else:
                    text = str(line)
                if text is not None:
                    if line == current:
                        p.setPen(QPen(QColor(T("color.text.primary"))))
                        f = p.font()
                        f.setBold(True)
                        p.setFont(f)
                    else:
                        p.setPen(QPen(QColor(T("color.text.tertiary"))))
                        f = p.font()
                        f.setBold(False)
                        p.setFont(f)
                    p.drawText(
                        QRectF(_DIAG_W + _BP_ZONE, top, num_w + _PAD, height),
                        Qt.AlignRight | Qt.AlignVCenter,
                        text,
                    )
                # 行标记（diff 并排：插入 + / 删除 −），行号右侧标记列
                if marker_fn is not None and mark_w > 0:
                    marker = marker_fn(line)
                    if marker:
                        p.setPen(QPen(self._marker_color(str(marker))))
                        f = p.font()
                        f.setBold(False)
                        p.setFont(f)
                        p.drawText(
                            QRectF(num_right + 1, top, mark_w - 2, height),
                            Qt.AlignLeft | Qt.AlignVCenter,
                            str(marker),
                        )
            # 折叠箭头（hover 该行 / 已折叠时显现）
            if line in fold_points and (
                line == self._hover_line or line in folded
            ):
                p.setPen(Qt.NoPen)
                p.setBrush(QColor(T("color.text.secondary")))
                s = 3.2
                path = QPainterPath()
                if line in folded:  # 向右三角
                    path.moveTo(fold_x - s, cy - s - 1)
                    path.lineTo(fold_x - s, cy + s + 1)
                    path.lineTo(fold_x + s, cy)
                else:               # 向下三角
                    path.moveTo(fold_x - s - 1, cy - s)
                    path.lineTo(fold_x + s + 1, cy - s)
                    path.lineTo(fold_x, cy + s)
                path.closeSubpath()
                p.drawPath(path)
        p.end()

    # ------------------------------------------------------------------
    # diff 标记 / 双列行号
    # ------------------------------------------------------------------
    @staticmethod
    def _marker_color(marker: str) -> QColor:
        """``+`` → success、``−``/``-`` → danger、其余 → 次要文本色。"""
        if marker.endswith("+"):
            return QColor(T("color.success"))
        if marker.endswith(("−", "-")):
            return QColor(T("color.danger"))
        return QColor(T("color.text.secondary"))

    def _paint_dual_labels(self, p: QPainter, dual_fn, line: int,
                           current: int, top: float, height: float,
                           left_x: float, right_x: float,
                           col_w: float) -> None:
        """双列行号：左列原始文件行号，右列修改文件行号。

        provider 返回 ``(left, right, marker)``（2 元组时 marker 由
        后缀推断）；``+`` 后缀 success 色、``−`` 后缀 danger 色。
        """
        res = dual_fn(line)
        if not res:
            return
        if len(res) == 2:
            left, right = res
            marker = None
        else:
            left, right, marker = res
        for idx, (x, label) in enumerate(((left_x, left),
                                          (right_x, right))):
            if label is None:
                continue
            text = str(label)
            if idx == 0:
                colored = (marker in ("−", "-")) or text.endswith(("−", "-"))
                color = (QColor(T("color.danger")) if colored
                         else QColor(T("color.text.tertiary")))
            else:
                if (marker == "+") or text.endswith("+"):
                    color = QColor(T("color.success"))
                elif text.endswith(("−", "-")):
                    color = QColor(T("color.danger"))
                else:
                    color = QColor(T("color.text.tertiary"))
            colored = (idx == 0 and text.endswith(("−", "-"))) or (
                idx == 1 and (text.endswith("+")
                              or text.endswith(("−", "-"))))
            if line == current and not colored:
                color = QColor(T("color.text.primary"))
            p.setPen(QPen(color))
            f = p.font()
            f.setBold(line == current and not colored)
            p.setFont(f)
            p.drawText(
                QRectF(x, top, col_w, height),
                Qt.AlignRight | Qt.AlignVCenter,
                text,
            )

    # ------------------------------------------------------------------
    # 交互
    # ------------------------------------------------------------------
    def _line_at(self, y: float) -> int:
        for block, top, height in self._visible_blocks():
            if top <= y < top + height:
                return block.blockNumber() + 1
        return -1

    def mousePressEvent(self, event):  # noqa: N802 - Qt 命名
        if event.button() != Qt.LeftButton:
            return super().mousePressEvent(event)
        line = self._line_at(event.position().y())
        if line <= 0:
            return
        # 折叠箭头区优先
        num_right = self.width() - _FOLD_ZONE - 2
        if (
            line in self._editor.fold_points()
            and event.position().x() >= num_right
        ):
            self.fold_clicked.emit(line)
        else:
            self.breakpoint_clicked.emit(line)

    def mouseMoveEvent(self, event):  # noqa: N802 - Qt 命名
        line = self._line_at(event.position().y())
        if line != self._hover_line:
            self._hover_line = line
            self.update()
        super().mouseMoveEvent(event)

    def leaveEvent(self, event):  # noqa: N802 - Qt 命名
        self._hover_line = -1
        self.update()
        super().leaveEvent(event)
