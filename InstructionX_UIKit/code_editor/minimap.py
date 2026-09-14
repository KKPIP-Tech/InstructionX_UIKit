# -*- coding: utf-8 -*-
"""小地图（CE_SPEC §2.1）。

右侧字符级缩略渲染（按行色块近似：每行一条横向色条，长度近似行长，
颜色取该行首个语法着色片段，否则用三级文本色），叠加：

- 视口框（可拖动）；点击 / 拖动跳转；
- 搜索命中与诊断的右侧刻度标记；
- 主题切换 / 文本变更自动重绘（文本变更经 150ms 去抖）。

性能：只绘制当前可见的小地图行区间；10 千行文档滚动仅重绘可见条。
"""

from PySide6.QtCore import QRectF, QTimer, Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QWidget

from ..theme import T, ThemeManager
from .regions import SEVERITY_COLORS

__all__ = ["MiniMap"]

_WIDTH = 96          # 小地图宽（px）
_LINE_H = 3.0        # 每行在小地图中的高度（px）
_CHAR_W = 1.4        # 每字符在小地图中的宽度（px）
_MAX_CHARS = 56      # 每行最多参与渲染的字符数


class MiniMap(QWidget):
    """小地图控件。

    参数:
        editor: 所属 ``CodeEditor``。
    """

    def __init__(self, editor, parent=None):
        super().__init__(parent or editor)
        self._editor = editor
        self._dragging = False
        self.setFixedWidth(_WIDTH)
        self.setAutoFillBackground(False)
        self.setStyleSheet("background: transparent;")
        self.setMouseTracking(False)
        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(150)
        self._debounce.timeout.connect(self.update)
        def _reload(_mode):
            try:
                self.update()
            except RuntimeError:
                pass  # 控件已销毁

        ThemeManager.instance().theme_changed.connect(_reload)

    # ------------------------------------------------------------------
    # 几何映射
    # ------------------------------------------------------------------
    def _doc(self):
        return self._editor.text_area().document()

    def _total_height(self) -> float:
        return self._doc().blockCount() * _LINE_H

    def _offset(self) -> float:
        """小地图内容的纵向滚动偏移（与文本区滚动比例联动）。"""
        total = self._total_height()
        view = self.height()
        if total <= view:
            return 0.0
        bar = self._editor.text_area().verticalScrollBar()
        maximum = max(1, bar.maximum())
        return (total - view) * (bar.value() / maximum)

    def _viewport_rect(self) -> QRectF:
        """视口框（文本区可见范围在小地图中的映射）。"""
        ta = self._editor.text_area()
        total = self._total_height()
        first = ta.firstVisibleBlock().blockNumber()
        # 可见行数估算
        fm = ta.fontMetrics()
        visible = max(1, int(ta.viewport().height() / max(1, fm.height())))
        if total <= self.height():
            top = first * _LINE_H
            height = visible * _LINE_H
        else:
            off = self._offset()
            top = first * _LINE_H - off
            height = visible * _LINE_H
        return QRectF(0, top, self.width(), max(14.0, height))

    # ------------------------------------------------------------------
    # 绘制
    # ------------------------------------------------------------------
    def paintEvent(self, event):  # noqa: N802 - Qt 命名
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, False)
        p.fillRect(self.rect(), QColor(T("color.bg.subtle")))
        p.setPen(QColor(T("color.border")))
        p.drawLine(0, 0, 0, self.height())

        doc = self._doc()
        off = self._offset()
        first = max(0, int(off / _LINE_H))
        last = min(doc.blockCount() - 1,
                   int((off + self.height()) / _LINE_H) + 1)
        default_color = QColor(T("color.text.tertiary"))
        default_color.setAlpha(150)
        diag = self._editor.diagnostic_lines()
        search = set(self._editor.search_match_lines())
        bps = self._editor.breakpoints()

        for i in range(first, last + 1):
            block = doc.findBlockByNumber(i)
            if not block.isValid():
                continue
            y = i * _LINE_H - off
            text = block.text()
            indent = len(text) - len(text.lstrip(" \t"))
            # 行色条：颜色取该行首个语法着色片段
            color = None
            layout = block.layout()
            if layout is not None:
                for fr in layout.formats():
                    if fr.length > 0:
                        color = fr.format.foreground().color()
                        break
            if color is None:
                color = default_color
            else:
                color = QColor(color)
                color.setAlpha(170)
            chars = min(len(text.strip()), _MAX_CHARS)
            if chars > 0:
                x = 4 + min(indent, 24) * _CHAR_W
                w = chars * _CHAR_W
                p.fillRect(QRectF(x, y + 0.5, w, _LINE_H - 1.2), color)
            line = i + 1
            # 断点标记
            if line in bps:
                p.fillRect(QRectF(0, y, 2.5, _LINE_H), QColor(T("color.danger")))
            # 诊断标记
            sev = diag.get(line)
            if sev:
                p.fillRect(
                    QRectF(self.width() - 6, y, 3, _LINE_H),
                    QColor(T(SEVERITY_COLORS.get(sev, "color.primary"))),
                )
            # 搜索命中标记
            if line in search:
                p.fillRect(
                    QRectF(self.width() - 11, y, 3, _LINE_H),
                    QColor(T("color.warning")),
                )

        # 视口框
        vr = self._viewport_rect()
        box = QColor(T("color.primary"))
        fill = QColor(box)
        fill.setAlpha(28)
        p.fillRect(vr, fill)
        p.setPen(QPen(box, 1))
        p.drawRect(vr)
        p.end()

    # ------------------------------------------------------------------
    # 交互：点击 / 拖动跳转
    # ------------------------------------------------------------------
    def _scroll_to_y(self, y: float) -> None:
        ta = self._editor.text_area()
        bar = ta.verticalScrollBar()
        total = self._total_height()
        if total <= self.height():
            # 内容不足一屏：按比例映射
            line = int(y / max(1.0, _LINE_H))
            doc = ta.document()
            block = doc.findBlockByNumber(
                max(0, min(line, doc.blockCount() - 1)))
            cur = ta.textCursor()
            cur.setPosition(block.position())
            ta.setTextCursor(cur)
            ta.centerCursor()
            return
        off = self._offset()
        target = y + off - ta.viewport().height() / 2 * (
            _LINE_H / max(1, ta.fontMetrics().height())
        )
        fraction = max(0.0, min(1.0, target / max(1.0, total - self.height())))
        bar.setValue(int(bar.maximum() * fraction))

    def mousePressEvent(self, event):  # noqa: N802 - Qt 命名
        if event.button() == Qt.LeftButton:
            self._dragging = True
            self._scroll_to_y(event.position().y())
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):  # noqa: N802 - Qt 命名
        if self._dragging:
            self._scroll_to_y(event.position().y())
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):  # noqa: N802 - Qt 命名
        self._dragging = False
        super().mouseReleaseEvent(event)

    # ------------------------------------------------------------------
    # 外部触发
    # ------------------------------------------------------------------
    def schedule_refresh(self) -> None:
        """文本变更后的去抖重绘。"""
        self._debounce.start()
